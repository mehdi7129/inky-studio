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
        let profile: BluetoothProfile
        var exchangeCount = 0
        var cancelled = false
        var badACK = false
        var block = false
        var pending: CheckedContinuation<Data, Error>?
        var directory: URL
        init(maximum: Int, serverMaximum: Int?, root: String, fixtures: String, delayFirstReply: Bool,
             profile: BluetoothProfile = .normalV1, serverALPN: String = "default", certificateLabel: String = "valid") throws {
            maxFrameLength = maximum
            self.profile = profile
            let fixture = URL(fileURLWithPath: fixtures)
            var metadata: [String: Any] = ["v": profile == .bootstrap ? 2 : 1,
                "id": "00000000-0000-4000-8000-000000000001",
                "cert": try Data(contentsOf: fixture.appendingPathComponent(certificateLabel + ".der")).base64EncodedString()]
            if profile == .bootstrap { metadata["p"] = "bootstrap" }
            identity = try JSONSerialization.data(withJSONObject: metadata)
            directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: false,
                                                    attributes: [.posixPermissions: 0o700])
            let helper = directory.appendingPathComponent("peer.py")
            try Self.python.write(to: helper, atomically: true, encoding: .utf8)
            let python = ProcessInfo.processInfo.environment["INKY_TLS_TEST_PYTHON"]
            process.executableURL = URL(fileURLWithPath: python ?? "/usr/bin/env")
            process.arguments = (python == nil ? ["python3"] : []) + ["-u", helper.path, root, fixtures,
                String((serverMaximum ?? maximum) + 3), delayFirstReply ? "1" : "0", profile.rawValue, serverALPN, certificateLabel]
            process.standardInput = input; process.standardOutput = output; process.standardError = FileHandle.standardError
            try process.run()
        }
        func connect(peripheralID: UUID) async throws -> Data { try await connect(peripheralID: peripheralID, profile: .normalV1) }
        func connect(peripheralID: UUID, profile: BluetoothProfile) async throws -> Data {
            guard profile == self.profile else { throw BluetoothTransportError.unsupportedFrame }
            cancelled = false
            return identity
        }
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
        profile, alpn, label = sys.argv[5:8]
        if profile == 'bootstrap':
            sys.path.insert(0, str(root/'server'))
            from inky_web.provisioning import transport as module
            from inky_web.provisioning.bootstrap_tls import BootstrapTLSContext
            from inky_web.provisioning.identity import Identity
            identity = Identity('00000000-0000-4000-8000-000000000001',
                                (fixtures/(label+'.pem')).read_bytes(), (fixtures/'server.key').read_bytes(), fixtures)
            context = BootstrapTLSContext(identity)
            if alpn != 'default':
                context._context.set_alpn_protocols([] if alpn == 'none' else [alpn])
            options = {'profile': module.BOOTSTRAP_PROFILE}
        else:
            spec = importlib.util.spec_from_file_location('inky_transport', root/'server/inky_web/provisioning/transport.py')
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            spec.loader.exec_module(module)
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.minimum_version = context.maximum_version = ssl.TLSVersion.TLSv1_3
            context.num_tickets = 0
            context.load_cert_chain(fixtures/(label+'.pem'), fixtures/'server.key')
            options = {}
        async def echo(message):
            return message
        async def main():
            transport = module.GATTTransport(context, echo, **options)
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
    private func setup(maximum: Int = 244, serverMaximum: Int? = nil, delayFirstReply: Bool = false,
                       profile: BluetoothProfile = .normalV1, serverALPN: String = "default",
                       certificateLabel: String = "valid") throws -> (PeerTransport, FrameIdentity) {
        guard let root = ProcessInfo.processInfo.environment["INKY_REPO_ROOT"],
              let fixtures = ProcessInfo.processInfo.environment["INKY_TLS_FIXTURES"] else {
            throw XCTSkip("Set INKY_REPO_ROOT and INKY_TLS_FIXTURES for pipe-only TLS interop")
        }
        let peer = try PeerTransport(maximum: maximum, serverMaximum: serverMaximum, root: root, fixtures: fixtures,
            delayFirstReply: delayFirstReply, profile: profile, serverALPN: serverALPN, certificateLabel: certificateLabel)
        let identity = try FrameIdentity(id: UUID(uuidString: "00000000-0000-4000-8000-000000000001")!,
            spkiSHA256: Data(contentsOf: URL(fileURLWithPath: fixtures).appendingPathComponent("pin.bin")))
        return (peer, identity)
    }

    func testRealBootstrapTLSAndALPNUseOnlyBootstrapRequestCapability() async throws {
        for maximum in [20, 244] {
            let (peer, identity) = try setup(maximum: maximum, profile: .bootstrap)
            defer { peer.stop() }
            let channel = SecureBluetoothChannel(transport: peer)
            let verified = try await channel.connectBootstrap(peripheralID: UUID(), identity: identity)
            XCTAssertEqual(verified.identity, identity)
            XCTAssertEqual(channel.bootstrapTrust, verified)
            XCTAssertNil(channel.trust, "Bootstrap must never manufacture normal pinned trust")
            let request = Data("{\"echo\":\"synthetic bootstrap only\"}".utf8)
            let before = peer.exchangeCount
            do { _ = try await channel.request(request); XCTFail("Normal API admitted a bootstrap request") }
            catch { XCTAssertEqual(error as? SecureBluetoothError, .notConnected) }
            XCTAssertEqual(peer.exchangeCount, before)
            let response = try await channel.requestBootstrap(request)
            XCTAssertEqual(response, request)
            channel.disconnect()
            XCTAssertNil(channel.bootstrapTrust)
        }
    }

    func testRealBootstrapRejectsMissingOrIncorrectALPNBeforePlaintext() async throws {
        for alpn in ["none", "other-protocol/1"] {
            let (peer, identity) = try setup(profile: .bootstrap, serverALPN: alpn)
            defer { peer.stop() }
            let channel = SecureBluetoothChannel(transport: peer)
            do { _ = try await channel.connectBootstrap(peripheralID: UUID(), identity: identity); XCTFail("Incorrect ALPN accepted") }
            catch {}
            XCTAssertNil(channel.bootstrapTrust)
            XCTAssertNil(channel.trust)
            XCTAssertTrue(peer.cancelled)
            do { _ = try await channel.requestBootstrap(Data("{\"claim_token\":\"synthetic-only\"}".utf8)); XCTFail("Secret admitted after failed ALPN") }
            catch { XCTAssertEqual(error as? SecureBluetoothError, .notConnected) }
        }
    }

    func testBootstrapDateExceptionDoesNotCarryIntoFreshNormalTrust() async throws {
        let (peer, identity) = try setup(profile: .bootstrap, certificateLabel: "expired")
        defer { peer.stop() }
        let channel = SecureBluetoothChannel(transport: peer)
        _ = try await channel.connectBootstrap(peripheralID: UUID(), identity: identity)
        channel.disconnect()
        let (normalPeer, normalIdentity) = try setup(certificateLabel: "expired")
        defer { normalPeer.stop() }
        XCTAssertEqual(normalIdentity, identity)
        let normal = SecureBluetoothChannel(transport: normalPeer)
        do { _ = try await normal.connect(peripheralID: UUID(), identity: identity); XCTFail("Bootstrap date exception leaked into normal TLS") }
        catch { XCTAssertEqual(error as? FrameIdentityError, .certificateRejected) }
        XCTAssertEqual(normalPeer.exchangeCount, 0)
        XCTAssertNil(normal.trust)
        XCTAssertNil(normal.bootstrapTrust)
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
