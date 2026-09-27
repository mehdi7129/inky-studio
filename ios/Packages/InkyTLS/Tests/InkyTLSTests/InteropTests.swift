#if os(macOS)
import Foundation
import Darwin
import XCTest
@testable import InkyTLS

@MainActor
final class InteropTests: XCTestCase {
    private let frameName = "frame-00000000-0000-4000-8000-000000000001.inky.invalid"
    private var fixtures: URL {
        URL(fileURLWithPath: #filePath).deletingLastPathComponent()
            .deletingLastPathComponent().deletingLastPathComponent()
            .appendingPathComponent(".generated/test-fixtures")
    }
    private func client(anchor: String = "valid", serverName: String? = nil,
                        badPin: Bool = false, capacity: Int = 1024) throws -> TLSClient {
        var pin = try Data(contentsOf: fixtures.appendingPathComponent("pin.bin"))
        if badPin { pin[0] ^= 1 }
        return try TLSClient(configuration: TLSConfiguration(
            serverName: serverName ?? frameName,
            trustedCertificatesDER: [Data(contentsOf: fixtures.appendingPathComponent(anchor + ".der"))],
            pinnedSPKISHA256: pin, bufferCapacity: capacity))
    }

    private final class Peer {
        let process = Process()
        let input = Pipe()
        let output = Pipe()
        var queued = Data()
        var received = Data()
        var ready = false
        init(fixtures: URL, label: String) throws {
            let python = ProcessInfo.processInfo.environment["INKY_TLS_TEST_PYTHON"]
            process.executableURL = URL(fileURLWithPath: python ?? "/usr/bin/env")
            let helper = try XCTUnwrap(Bundle.module.url(forResource: "openssl_peer", withExtension: "py", subdirectory: "Support"))
            process.arguments = (python == nil ? ["python3"] : []) + ["-u", helper.path, fixtures.path, label]
            process.standardInput = input
            process.standardOutput = output
            process.standardError = FileHandle.standardError
            try process.run()
        }
        func request(_ value: [String: String]) throws {
            let data = try JSONSerialization.data(withJSONObject: value) + Data([10])
            try input.fileHandleForWriting.write(contentsOf: data)
            var line = Data()
            let deadline = Date().addingTimeInterval(10)
            while line.last != 10 {
                var descriptor = pollfd(fd: output.fileHandleForReading.fileDescriptor,
                                        events: Int16(POLLIN), revents: 0)
                guard Date() < deadline else { throw TLSError.invalidState }
                let ready = poll(&descriptor, 1, 1000)
                if ready == 0 || (ready < 0 && errno == EINTR) { continue }
                guard ready > 0 else { throw TLSError.invalidState }
                var bytes = [UInt8](repeating: 0, count: 4096)
                let count = Darwin.read(output.fileHandleForReading.fileDescriptor, &bytes, bytes.count)
                if count < 0 && errno == EINTR { continue }
                guard count > 0 else { throw TLSError.invalidState }
                line.append(contentsOf: bytes.prefix(count))
                guard line.count <= 100_000 else { throw TLSError.invalidState }
            }
            let result = try XCTUnwrap(JSONSerialization.jsonObject(with: line) as? [String: Any])
            queued.append(try XCTUnwrap(Data(base64Encoded: result["out"] as? String ?? "")))
            received = try XCTUnwrap(Data(base64Encoded: result["received"] as? String ?? ""))
            ready = result["ready"] as? Bool ?? false
        }
        func stop() {
            try? input.fileHandleForWriting.close()
            if process.isRunning { process.terminate() }
        }
        deinit { stop() }
    }

    private func transfer(_ client: TLSClient, _ peer: Peer) async throws {
        let bytes = try await client.drainCiphertext(maxBytes: 20)
        try peer.request(["feed": bytes.base64EncodedString()])
        if !peer.queued.isEmpty {
            let count = min(20, peer.queued.count)
            try await client.receiveCiphertext(peer.queued.prefix(count))
            peer.queued.removeFirst(count)
        }
    }
    private func establish(_ client: TLSClient, _ peer: Peer) async throws {
        for _ in 0..<2000 {
            let result = try await client.advanceHandshake()
            try await transfer(client, peer)
            if result == .complete && peer.ready { return }
        }
        throw TLSError.invalidState
    }

    func testPipePeerWaitsBeyondOnePollInterval() throws {
        let peer = try Peer(fixtures: fixtures, label: "valid")
        defer { peer.stop() }
        let began = Date()
        try peer.request(["delay_reply": "true"])
        XCTAssertGreaterThanOrEqual(Date().timeIntervalSince(began), 1.1)
        XCTAssertFalse(peer.ready)
        XCTAssertTrue(peer.received.isEmpty)
    }

    func testSelfSignedPhysicalIdentityAnchorAndBoundedPartialWrite() async throws {
        let tls = try client()
        let peer = try Peer(fixtures: fixtures, label: "valid")
        defer { peer.stop() }
        do { try await tls.queuePlaintext(Data([1])); XCTFail("Unauthenticated write accepted") }
        catch { XCTAssertEqual(error as? TLSError, .invalidState) }
        try await establish(tls, peer)
        let state = await tls.state
        XCTAssertEqual(state, .open)

        let payload = Data((0..<16_384).map { UInt8($0 % 251) })
        try await tls.queuePlaintext(payload)
        do { try await tls.queuePlaintext(Data([2])); XCTFail("Unbounded plaintext queue") }
        catch { XCTAssertEqual(error as? TLSError, .backpressure) }
        let firstFlush = try await tls.flushPlaintext()
        XCTAssertEqual(firstFlush, .needsWrite)
        for _ in 0..<3000 {
            _ = try await tls.flushPlaintext()
            try await transfer(tls, peer)
            if peer.received == payload { break }
        }
        XCTAssertEqual(peer.received, payload)
        let pending = await tls.pendingPlaintextByteCount
        XCTAssertEqual(pending, 0)
        let response = Data((0..<600).map { UInt8($0 % 233) })
        try peer.request(["write": response.base64EncodedString()])
        var plaintext = Data()
        for _ in 0..<500 {
            try await transfer(tls, peer)
            if case let .bytes(bytes) = try await tls.readPlaintext() { plaintext.append(bytes) }
            if plaintext == response { break }
        }
        XCTAssertEqual(plaintext, response)
    }

    func testWrongPinNameDatesAndAnchorFailClosed() async throws {
        let cases: [(String, String, String?, Bool)] = [
            ("valid", "valid", nil, true),
            ("valid", "valid", "wrong.inky.invalid", false),
            ("expired", "expired", nil, false),
            ("future", "future", nil, false),
            ("valid", "other", nil, false),
        ]
        for (certificate, anchor, name, badPin) in cases {
            let tls = try client(anchor: anchor, serverName: name, badPin: badPin)
            let peer = try Peer(fixtures: fixtures, label: certificate)
            defer { peer.stop() }
            do { try await establish(tls, peer); XCTFail("Invalid trust accepted: \(certificate), \(anchor)") }
            catch {
                if badPin { XCTAssertEqual(error as? TLSError, .pinMismatch) }
                let state = await tls.state
                XCTAssertEqual(state, .failed)
            }
            do { try await tls.queuePlaintext(Data([1])); XCTFail("Write after failure") }
            catch { XCTAssertEqual(error as? TLSError, .invalidState) }
            XCTAssertTrue(peer.received.isEmpty)
        }
    }

    func testReceiveBackpressureConsumesNothing() async throws {
        let tls = try client()
        try await tls.receiveCiphertext(Data(count: 1000))
        do { try await tls.receiveCiphertext(Data(count: 25)); XCTFail("Overfull receive queue") }
        catch { XCTAssertEqual(error as? TLSError, .backpressure) }
        let available = await tls.availableReceiveCapacity
        XCTAssertEqual(available, 24)
    }

    func testAbruptTransportEndIsTerminal() async throws {
        let tls = try client()
        let peer = try Peer(fixtures: fixtures, label: "valid")
        defer { peer.stop() }
        try await establish(tls, peer)
        await tls.transportDidEnd()
        do { _ = try await tls.readPlaintext(); XCTFail("Truncated TLS accepted") }
        catch { XCTAssertEqual(error as? TLSError, .truncatedTransport) }
        let state = await tls.state
        XCTAssertEqual(state, .failed)
    }

    func testPeerCloseNotifyCanBeAcknowledged() async throws {
        let tls = try client()
        let peer = try Peer(fixtures: fixtures, label: "valid")
        defer { peer.stop() }
        try await establish(tls, peer)
        try peer.request(["close": "true"])
        var closed = false
        for _ in 0..<100 {
            try await transfer(tls, peer)
            if try await tls.readPlaintext() == .closed { closed = true; break }
        }
        XCTAssertTrue(closed)
        let result = try await tls.close()
        XCTAssertEqual(result, .complete)
        let acknowledgement = try await tls.drainCiphertext(maxBytes: 1024)
        XCTAssertFalse(acknowledgement.isEmpty)
        await tls.transportDidEnd()
        let read = try await tls.readPlaintext()
        XCTAssertEqual(read, .closed)
    }

    func testCorruptRecordIsTerminalWithoutPlaintext() async throws {
        let tls = try client()
        let peer = try Peer(fixtures: fixtures, label: "valid")
        defer { peer.stop() }
        try await establish(tls, peer)
        try peer.request(["write": Data(repeating: 42, count: 600).base64EncodedString()])
        peer.queued[peer.queued.index(before: peer.queued.endIndex)] ^= 1
        var rejected = false
        for _ in 0..<100 {
            try await transfer(tls, peer)
            do {
                if case .bytes = try await tls.readPlaintext() { XCTFail("Corrupt plaintext was exposed") }
            } catch {
                rejected = true
                let state = await tls.state
                XCTAssertEqual(state, .failed)
                break
            }
        }
        XCTAssertTrue(rejected)
    }
}
#endif
