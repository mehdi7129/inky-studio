#if os(macOS)
import Foundation
import Darwin
import XCTest
@testable import InkyStudio

/// Runs the production Swift channel against the production Python GATT/TLS state
/// machine in pipes. Opt in with INKY_REPO_ROOT and INKY_TLS_FIXTURES; no radio.
@MainActor final class BluetoothChannelInteropTests: XCTestCase {
    private final class PeerTransport: BluetoothExchanging {
        let maxFrameLength: Int
        let process = Process(), input = Pipe(), output = Pipe()
        let identity: Data
        var exchangeCount = 0
        var cancelled = false
        var badACK = false
        var block = false
        var pending: CheckedContinuation<Data, Error>?
        var directory: URL
        init(maximum: Int, serverMaximum: Int?, root: String, fixtures: String, delayFirstReply: Bool) throws {
            maxFrameLength = maximum
            let fixture = URL(fileURLWithPath: fixtures)
            identity = try JSONSerialization.data(withJSONObject: ["v": 1,
                "id": "00000000-0000-4000-8000-000000000001",
                "cert": Data(contentsOf: fixture.appendingPathComponent("valid.der")).base64EncodedString()])
            directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: false,
                                                    attributes: [.posixPermissions: 0o700])
            let helper = directory.appendingPathComponent("peer.py")
            try Self.python.write(to: helper, atomically: true, encoding: .utf8)
            let python = ProcessInfo.processInfo.environment["INKY_TLS_TEST_PYTHON"]
            process.executableURL = URL(fileURLWithPath: python ?? "/usr/bin/env")
            process.arguments = (python == nil ? ["python3"] : []) + ["-u", helper.path, root, fixtures, String((serverMaximum ?? maximum) + 3), delayFirstReply ? "1" : "0"]
            process.standardInput = input; process.standardOutput = output; process.standardError = FileHandle.standardError
            try process.run()
        }
        func connect(peripheralID: UUID) async throws -> Data { cancelled = false; return identity }
        func exchange(_ frame: Data) async throws -> Data {
            if block { return try await withCheckedThrowingContinuation { pending = $0 } }
            exchangeCount += 1
            try input.fileHandleForWriting.write(contentsOf: Data(frame.base64EncodedString().utf8) + Data([10]))
            var line = Data()
            let deadline = Date().addingTimeInterval(10)
            while line.last != 10 {
                var descriptor = pollfd(fd: output.fileHandleForReading.fileDescriptor, events: Int16(POLLIN), revents: 0)
                guard Date() < deadline else { throw SecureBluetoothError.timeout }
                let ready = poll(&descriptor, 1, 1000)
                if ready == 0 || (ready < 0 && errno == EINTR) { continue }
                guard ready > 0 else { throw SecureBluetoothError.invalidRecord }
                var bytes = [UInt8](repeating: 0, count: 4096)
                let count = Darwin.read(output.fileHandleForReading.fileDescriptor, &bytes, bytes.count)
                if count < 0 && errno == EINTR { continue }
                guard count > 0, line.count + count < 8192 else { throw SecureBluetoothError.invalidRecord }
                line.append(contentsOf: bytes.prefix(count))
            }
            let encoded = String(decoding: line.dropLast(), as: UTF8.self)
            guard var response = Data(base64Encoded: encoded) else { throw SecureBluetoothError.invalidRecord }
            if badACK, response.first == 1 { response[2] ^= 1 }
            return response
        }
        func cancel() {
            cancelled = true
            let previous = pending; pending = nil
            previous?.resume(throwing: BluetoothTransportError.cancelled)
        }
        func stop() {
            try? input.fileHandleForWriting.close()
            if process.isRunning { process.terminate() }
            try? FileManager.default.removeItem(at: directory)
        }
        static let python = """
        import asyncio, base64, importlib.util, ssl, sys
        from pathlib import Path
        root, fixtures, mtu = Path(sys.argv[1]), Path(sys.argv[2]), int(sys.argv[3])
        spec = importlib.util.spec_from_file_location('inky_transport', root/'server/inky_web/provisioning/transport.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = context.maximum_version = ssl.TLSVersion.TLSv1_3
        context.num_tickets = 0
        context.load_cert_chain(fixtures/'valid.pem', fixtures/'server.key')
        async def echo(message):
            return message
        async def main():
            transport = module.GATTTransport(context, echo)
            delay = sys.argv[4] == '1'
            for line in sys.stdin:
                if delay:
                    await asyncio.sleep(1.2)
                    delay = False
                transport.write('synthetic', base64.b64decode(line), mtu=mtu)
                await asyncio.sleep(0)
                print(base64.b64encode(transport.read('synthetic')).decode(), flush=True)
            transport.close()
        asyncio.run(main())
        """
    }
    private func setup(maximum: Int = 244, serverMaximum: Int? = nil, delayFirstReply: Bool = false) throws -> (PeerTransport, FrameIdentity) {
        guard let root = ProcessInfo.processInfo.environment["INKY_REPO_ROOT"],
              let fixtures = ProcessInfo.processInfo.environment["INKY_TLS_FIXTURES"] else {
            throw XCTSkip("Set INKY_REPO_ROOT and INKY_TLS_FIXTURES for pipe-only TLS interop")
        }
        let peer = try PeerTransport(maximum: maximum, serverMaximum: serverMaximum, root: root, fixtures: fixtures, delayFirstReply: delayFirstReply)
        let identity = try FrameIdentity(id: UUID(uuidString: "00000000-0000-4000-8000-000000000001")!,
            spkiSHA256: Data(contentsOf: URL(fileURLWithPath: fixtures).appendingPathComponent("pin.bin")))
        return (peer, identity)
    }

    func testPipeTransportWaitsBeyondOnePollInterval() async throws {
        let (peer, identity) = try setup(delayFirstReply: true)
        defer { peer.stop() }
        let channel = SecureBluetoothChannel(transport: peer)
        let began = Date()
        _ = try await channel.connect(peripheralID: UUID(), identity: identity)
        XCTAssertGreaterThanOrEqual(Date().timeIntervalSince(began), 1.1)
        let command = Data("{\"echo\":\"delayed peer\"}".utf8)
        let reply = try await channel.request(command)
        XCTAssertEqual(reply, command)
        channel.disconnect()
    }

    func testLargerReadAfterSmallWritesDuringMTUNegotiation() async throws {
        // Real Mac/Pi failure: a cached initial write cap was 20 bytes while the
        // peer could already return 182-byte values after ATT MTU negotiation.
        let (peer, identity) = try setup(maximum: 20, serverMaximum: 182)
        defer { peer.stop() }
        let channel = SecureBluetoothChannel(transport: peer)
        _ = try await channel.connect(peripheralID: UUID(), identity: identity)
        let command = try JSONSerialization.data(withJSONObject: ["echo": String(repeating: "x", count: 600)])
        let reply = try await channel.request(command)
        XCTAssertEqual(try JSONSerialization.jsonObject(with: reply) as? [String: String],
                       try JSONSerialization.jsonObject(with: command) as? [String: String])
        channel.disconnect()
    }

    func testRealTLSOverMTU23And247WithMaximumJSONAndReconnect() async throws {
        for maximum in [20, 244] {
            let (peer, identity) = try setup(maximum: maximum)
            defer { peer.stop() }
            let channel = SecureBluetoothChannel(transport: peer)
            let peripheral = UUID()
            _ = try await channel.connect(peripheralID: peripheral, identity: identity)
            let data = Data(("{\"echo\":\"" + String(repeating: "x", count: 16_373) + "\"}").utf8)
            XCTAssertEqual(data.count, 16_384)
            let response = try await channel.request(data)
            XCTAssertEqual(response, data)
            channel.disconnect()
            _ = try await channel.connect(peripheralID: peripheral, identity: identity)
            let tiny = Data("{\"echo\":\"new session\"}".utf8)
            let fresh = try await channel.request(tiny)
            XCTAssertEqual(fresh, tiny)
            channel.disconnect()
        }
    }

    func testWrongPinRejectedBeforeAnyGATTWriteAndBadAckClosesConnection() async throws {
        let (peer, identity) = try setup()
        defer { peer.stop() }
        let channel = SecureBluetoothChannel(transport: peer)
        let wrong = try FrameIdentity(id: identity.id, spkiSHA256: Data(repeating: 0, count: 32))
        do { _ = try await channel.connect(peripheralID: UUID(), identity: wrong); XCTFail("Wrong pin accepted") }
        catch { XCTAssertEqual(error as? FrameIdentityError, .pinMismatch) }
        XCTAssertEqual(peer.exchangeCount, 0)
        peer.badACK = true
        do { _ = try await channel.connect(peripheralID: UUID(), identity: identity); XCTFail("Bad ACK accepted") }
        catch { XCTAssertEqual(error as? SecureBluetoothError, .invalidRecord) }
        XCTAssertNil(channel.trust)
        XCTAssertTrue(peer.cancelled)
    }

    func testTimeoutAndConcurrentRequestClearConnectionWithoutQueue() async throws {
        let (peer, identity) = try setup()
        defer { peer.stop() }
        let channel = SecureBluetoothChannel(transport: peer)
        _ = try await channel.connect(peripheralID: UUID(), identity: identity)
        peer.block = true
        let data = Data("{\"echo\":\"timeout\"}".utf8)
        let pending = Task { try await channel.request(data, timeout: 0.05) }
        while peer.pending == nil { await Task.yield() }
        do { _ = try await channel.request(data); XCTFail("Concurrent request accepted") }
        catch { XCTAssertEqual(error as? SecureBluetoothError, .busy) }
        do { _ = try await pending.value; XCTFail("Timed-out request succeeded") }
        catch { XCTAssertEqual(error as? SecureBluetoothError, .timeout) }
        XCTAssertNil(channel.trust)
        XCTAssertNil(peer.pending)
        XCTAssertTrue(peer.cancelled)
        do { _ = try await channel.request(data); XCTFail("Closed connection reused") }
        catch { XCTAssertEqual(error as? SecureBluetoothError, .notConnected) }
    }
}
#endif
