#if os(macOS)
import Darwin
import Foundation
import XCTest
@testable import InkyStudio

/// Actual Swift app channel against production Python bootstrap TLS/GATT and
/// SQLite ownership. Only OS authorization, radio and physical output are fake.
@MainActor final class BootstrapChannelInteropTests: XCTestCase {
    private final class PeerTransport: BootstrapBluetoothExchanging {
        let maxFrameLength: Int
        var profile: BluetoothGATTProfile = .bootstrap
        private let process = Process(), input = Pipe(), output = Pipe()
        private let directory: URL
        private(set) var publicIdentity: Data
        let code: BootstrapAdoptionCode
        private(set) var exchangeCount = 0
        private(set) var handlerCalls = 0
        private(set) var authenticated = false
        private(set) var alpn: String?
        private(set) var adopted = false
        private(set) var qrCount = 0
        private(set) var cancelled = false
        var dropReplyAfterCommit = false
        var corruptACK = false
        private var stopped = false

        init(maximum: Int = 244, peerProfile: String = "bootstrap") throws {
            guard let root = ProcessInfo.processInfo.environment["INKY_REPO_ROOT"],
                  let python = ProcessInfo.processInfo.environment["INKY_TLS_TEST_PYTHON"] else {
                throw XCTSkip("Run scripts/test-bootstrap-channel.sh for pipe-only native interop")
            }
            maxFrameLength = maximum
            directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: false,
                                                    attributes: [.posixPermissions: 0o700])
            process.executableURL = URL(fileURLWithPath: python)
            process.arguments = ["-u", root + "/scripts/bootstrap-channel-bench/peer.py", root,
                                 directory.appendingPathComponent("private").path,
                                 String(maximum + 3), peerProfile]
            process.standardInput = input
            process.standardOutput = output
            process.standardError = FileHandle.standardError
            publicIdentity = Data()
            do {
                try process.run()
                let initial = try Self.read(output.fileHandleForReading)
                guard let identity = initial["identity"], let qr = initial["qr"],
                      let count = initial["qr_count"] as? Int else { throw SecureBluetoothError.invalidIdentity }
                publicIdentity = try JSONSerialization.data(withJSONObject: identity)
                code = try BootstrapAdoptionCode.parse(JSONSerialization.data(withJSONObject: qr))
                qrCount = count
            } catch {
                if process.isRunning { process.terminate(); process.waitUntilExit() }
                try? FileManager.default.removeItem(at: directory)
                throw error
            }
        }

        func connect(peripheralID: UUID) async throws -> Data {
            cancelled = false
            return publicIdentity
        }

        func exchange(_ frame: Data) async throws -> Data {
            exchangeCount += 1
            try send(["frame": frame.base64EncodedString()])
            let reply = try Self.read(output.fileHandleForReading)
            handlerCalls = reply["handler_calls"] as? Int ?? handlerCalls
            authenticated = reply["authenticated"] as? Bool ?? false
            alpn = reply["alpn"] as? String
            adopted = reply["adopted"] as? Bool ?? adopted
            guard let encoded = reply["frame"] as? String, var response = Data(base64Encoded: encoded) else {
                throw SecureBluetoothError.invalidRecord
            }
            if dropReplyAfterCommit, adopted {
                dropReplyAfterCommit = false
                throw BluetoothTransportError.disconnected
            }
            if corruptACK, response.first == 1, response.count >= 5 { response[4] ^= 1 }
            return response
        }

        func cancel() { cancelled = true }

        func reopenDurableRuntime() throws {
            try send(["control": "restart"])
            let reply = try Self.read(output.fileHandleForReading)
            guard let identity = reply["identity"], let count = reply["qr_count"] as? Int,
                  let isAdopted = reply["adopted"] as? Bool else { throw SecureBluetoothError.invalidIdentity }
            publicIdentity = try JSONSerialization.data(withJSONObject: identity)
            qrCount = count
            adopted = isAdopted
        }

        func stop() {
            guard !stopped else { return }
            stopped = true
            try? send(["control": "stop"])
            try? input.fileHandleForWriting.close()
            // The helper drains its real admitted tasks before exiting.
            if process.isRunning { process.waitUntilExit() }
            try? output.fileHandleForReading.close()
            try? FileManager.default.removeItem(at: directory)
        }

        private func send(_ object: [String: Any]) throws {
            try input.fileHandleForWriting.write(contentsOf: JSONSerialization.data(withJSONObject: object) + Data([10]))
        }

        private static func read(_ handle: FileHandle) throws -> [String: Any] {
            var line = Data()
            let deadline = Date().addingTimeInterval(20)
            while line.last != 10 {
                var descriptor = pollfd(fd: handle.fileDescriptor, events: Int16(POLLIN), revents: 0)
                guard Date() < deadline else { throw SecureBluetoothError.timeout }
                let ready = poll(&descriptor, 1, 1000)
                if ready == 0 || (ready < 0 && errno == EINTR) { continue }
                guard ready > 0 else { throw SecureBluetoothError.invalidRecord }
                var bytes = [UInt8](repeating: 0, count: 4096)
                let count = Darwin.read(handle.fileDescriptor, &bytes, bytes.count)
                if count < 0 && errno == EINTR { continue }
                guard count > 0, line.count + count < 16_384 else { throw SecureBluetoothError.invalidRecord }
                line.append(contentsOf: bytes.prefix(count))
            }
            guard let value = try JSONSerialization.jsonObject(with: line) as? [String: Any] else {
                throw SecureBluetoothError.invalidRecord
            }
            return value
        }
    }

    private func claim(_ code: BootstrapAdoptionCode) -> BootstrapRequest {
        BootstrapRequest(operation: .claim, id: UUID(), ownerID: UUID(),
                         ownerToken: Data(repeating: 0xab, count: 32), proof: code.claimToken, claimRequestID: nil)
    }

    private func status(_ claim: BootstrapRequest) -> BootstrapRequest {
        BootstrapRequest(operation: .status, id: UUID(), ownerID: claim.ownerID,
                         ownerToken: claim.ownerToken, proof: nil, claimRequestID: claim.id)
    }

    private func parsed(_ reply: Data, request: BootstrapRequest,
                        original: BootstrapRequest, frame: UUID) throws -> BootstrapResponse {
        try BootstrapResponse.parse(reply, context: BootstrapResponseContext(rpcID: request.id,
            frameID: frame, ownerID: original.ownerID, claimRequestID: original.id))
    }

    func testClaimReplayStatusAndDurableReopenAtMTU23And247() async throws {
        for maximum in [20, 244] {
            let peer = try PeerTransport(maximum: maximum)
            defer { peer.stop() }
            let channel = BootstrapBluetoothChannel(transport: peer)
            _ = try await channel.connect(peripheralID: UUID(), identity: peer.code.identity)
            XCTAssertTrue(peer.authenticated)
            XCTAssertEqual(peer.alpn, "inky-bootstrap/1")
            XCTAssertEqual(peer.handlerCalls, 0, "TLS must finish before any application operation")
            let original = claim(peer.code)
            let encoded = try original.encoded()
            let first = try await channel.request(encoded)
            XCTAssertEqual(try parsed(first, request: original, original: original, frame: peer.code.identity.id),
                           .adoptedAwaitingPreparation)
            let replay = try await channel.request(encoded)
            XCTAssertEqual(replay, first)
            let check = status(original)
            let checked = try await channel.request(check.encoded())
            XCTAssertNotEqual(check.id, original.id)
            XCTAssertEqual(try parsed(checked, request: check, original: original, frame: peer.code.identity.id),
                           .adoptedAwaitingPreparation)
            channel.disconnect()
            try peer.reopenDurableRuntime()
            XCTAssertTrue(peer.adopted)
            XCTAssertEqual(peer.qrCount, 1, "An adopted ledger must not generate another physical proof")
            _ = try await channel.connect(peripheralID: UUID(), identity: peer.code.identity)
            let recovered = status(original)
            let reply = try await channel.request(recovered.encoded())
            XCTAssertEqual(try parsed(reply, request: recovered, original: original, frame: peer.code.identity.id),
                           .adoptedAwaitingPreparation)
            XCTAssertEqual(peer.handlerCalls, 4)
            channel.disconnect()
        }
    }

    func testLostClaimReplyIsRecoveredWithSameOwnerAfterReconnectAndReopen() async throws {
        let peer = try PeerTransport()
        defer { peer.stop() }
        let channel = BootstrapBluetoothChannel(transport: peer)
        _ = try await channel.connect(peripheralID: UUID(), identity: peer.code.identity)
        let original = claim(peer.code)
        peer.dropReplyAfterCommit = true
        do { _ = try await channel.request(original.encoded()); XCTFail("Synthetic reply loss was not injected") }
        catch { XCTAssertEqual(error as? BluetoothTransportError, .disconnected) }
        XCTAssertTrue(peer.adopted)
        XCTAssertNil(channel.trust)
        XCTAssertTrue(peer.cancelled)
        try peer.reopenDurableRuntime()
        XCTAssertEqual(peer.qrCount, 1)
        _ = try await channel.connect(peripheralID: UUID(), identity: peer.code.identity)
        let recovery = status(original)
        let receipt = try await channel.request(recovery.encoded())
        XCTAssertEqual(try parsed(receipt, request: recovery, original: original, frame: peer.code.identity.id),
                       .adoptedAwaitingPreparation)
        let replay = try await channel.request(original.encoded())
        XCTAssertEqual(try parsed(replay, request: original, original: original, frame: peer.code.identity.id),
                       .adoptedAwaitingPreparation)
        XCTAssertEqual(peer.handlerCalls, 3)
        channel.disconnect()
    }

    func testPinIsVerifiedBeforeRESETAndWrongACKClosesConnection() async throws {
        let peer = try PeerTransport()
        defer { peer.stop() }
        let channel = BootstrapBluetoothChannel(transport: peer)
        let wrong = try FrameIdentity(id: peer.code.identity.id, spkiSHA256: Data(repeating: 0, count: 32))
        do { _ = try await channel.connect(peripheralID: UUID(), identity: wrong); XCTFail("Wrong pin accepted") }
        catch { XCTAssertEqual(error as? FrameIdentityError, .pinMismatch) }
        XCTAssertEqual(peer.exchangeCount, 0)
        XCTAssertEqual(peer.handlerCalls, 0)
        peer.corruptACK = true
        do { _ = try await channel.connect(peripheralID: UUID(), identity: peer.code.identity); XCTFail("Bad ACK accepted") }
        catch { XCTAssertEqual(error as? SecureBluetoothError, .invalidRecord) }
        XCTAssertNil(channel.trust)
        XCTAssertTrue(peer.cancelled)
        XCTAssertEqual(peer.handlerCalls, 0)
    }

    func testNormalProfileAndALPNAreRefusedBeforeApplicationOperation() async throws {
        let peer = try PeerTransport()
        defer { peer.stop() }
        peer.profile = .normalV1
        let channel = BootstrapBluetoothChannel(transport: peer)
        do { _ = try await channel.connect(peripheralID: UUID(), identity: peer.code.identity); XCTFail("Normal profile accepted") }
        catch { XCTAssertEqual(error as? SecureBluetoothError, .invalidIdentity) }
        XCTAssertEqual(peer.exchangeCount, 0)
        let incompatible = try PeerTransport(peerProfile: "normal-alpn")
        defer { incompatible.stop() }
        let wrongTLS = BootstrapBluetoothChannel(transport: incompatible)
        do { _ = try await wrongTLS.connect(peripheralID: UUID(), identity: incompatible.code.identity); XCTFail("Normal ALPN accepted") }
        catch { XCTAssertNil(wrongTLS.trust) }
        XCTAssertEqual(incompatible.handlerCalls, 0)
        XCTAssertFalse(incompatible.adopted)
    }

    func testPhaseBCommandsAndConflictingOwnerAreRefusedOverAuthenticatedTLS() async throws {
        let peer = try PeerTransport()
        defer { peer.stop() }
        let channel = BootstrapBluetoothChannel(transport: peer)
        _ = try await channel.connect(peripheralID: UUID(), identity: peer.code.identity)
        let original = claim(peer.code)
        _ = try await channel.request(original.encoded())
        for operation in ["wifi.scan", "wifi.begin", "bootstrap.time", "owner.revoke"] {
            var fields = try XCTUnwrap(JSONSerialization.jsonObject(with: original.encoded()) as? [String: Any])
            fields["op"] = operation
            let reply = try await channel.request(JSONSerialization.data(withJSONObject: fields))
            XCTAssertEqual(try parsed(reply, request: original, original: original, frame: peer.code.identity.id),
                           .failure(.invalidRequest, correlated: true))
        }
        let another = claim(peer.code)
        let denied = try await channel.request(another.encoded())
        let decoded = try BootstrapResponse.parse(denied, context: BootstrapResponseContext(rpcID: another.id,
            frameID: peer.code.identity.id, ownerID: another.ownerID, claimRequestID: another.id))
        XCTAssertEqual(decoded, .failure(.qrUnavailable, correlated: true))
        let unknown = status(another)
        let unauthenticated = try await channel.request(unknown.encoded())
        XCTAssertEqual(try parsed(unauthenticated, request: unknown, original: another, frame: peer.code.identity.id),
                       .failure(.unauthorized, correlated: true))
        channel.disconnect()
    }
}
#endif
