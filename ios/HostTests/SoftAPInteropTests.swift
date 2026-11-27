import Foundation
@preconcurrency import Network
import XCTest
@testable import InkyStudio

/// Real Python/OpenSSL server ↔ real Swift/MbedTLS client on localhost. Radio,
/// NEHotspotConfiguration, Pi switching and physical qualification remain separate.
@MainActor final class SoftAPInteropTests: XCTestCase {
    private struct Fixture: Decodable {
        let host: String
        let normalPort: UInt16
        let bootstrapPort: UInt16
        let frameID: UUID
        let pin: String
        enum CodingKeys: String, CodingKey {
            case host, normalPort = "normal_port", bootstrapPort = "bootstrap_port", frameID = "frame_id", pin = "spki_sha256"
        }
    }
    private final class Joiner: SoftAPJoining {
        var joins = 0
        func join(_ descriptor: SoftAPDescriptor) async throws { joins += 1 }
        func leave(_ descriptor: SoftAPDescriptor) {}
        func cancel() {}
    }
    private final class Stream: ProvisioningByteStream {
        let connection: NWConnection
        private var pending: CheckedContinuation<Void, Error>?
        init(host: String, port: UInt16) {
            connection = NWConnection(host: NWEndpoint.Host(host), port: NWEndpoint.Port(rawValue: port)!, using: .tcp)
        }
        func connect() async throws {
            try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
                pending = continuation
                connection.stateUpdateHandler = { [weak self] state in
                    Task { @MainActor in
                        guard let self, let pending = self.pending else { return }
                        switch state {
                        case .ready: self.pending = nil; pending.resume()
                        case .failed, .cancelled: self.pending = nil; pending.resume(throwing: SoftAPError.disconnected)
                        default: break
                        }
                    }
                }
                connection.start(queue: .main)
            }
        }
        func read(maximum: Int) async throws -> Data {
            try await withCheckedThrowingContinuation { continuation in
                connection.receive(minimumIncompleteLength: 1, maximumLength: maximum) { data, _, _, error in
                    if error == nil, let data, !data.isEmpty { continuation.resume(returning: data) }
                    else { continuation.resume(throwing: SoftAPError.disconnected) }
                }
            }
        }
        func write(_ bytes: Data) async throws {
            try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
                connection.send(content: bytes, completion: .contentProcessed { error in
                    if error == nil { continuation.resume() } else { continuation.resume(throwing: SoftAPError.disconnected) }
                })
            }
        }
        func cancel() { connection.cancel() }
    }
    private func fixture() throws -> Fixture {
        guard let path = ProcessInfo.processInfo.environment["INKY_SOFTAP_INTEROP_FIXTURE"] else {
            throw XCTSkip("Run with the bounded synthetic backend fixture path")
        }
        return try JSONDecoder().decode(Fixture.self, from: Data(contentsOf: URL(fileURLWithPath: path)))
    }

    func testRealBootstrapTLS13ALPNAndFramedJSONRequest() async throws { try await exercise(bootstrap: true) }
    func testRealNormalTLS13PinAndFramedJSONRequest() async throws { try await exercise(bootstrap: false) }
    func testRealNormalTLSUsesUUIDServerNameDespiteDistinctLANLocatorWithoutAPJoin() async throws {
        try await exercise(bootstrap: false, lan: true)
    }

    private func exercise(bootstrap: Bool, lan: Bool = false) async throws {
        let fixture = try fixture()
        let pin = try XCTUnwrap(BootstrapFlatObject.hex(fixture.pin))
        let identity = try FrameIdentity(id: fixture.frameID, spkiSHA256: pin)
        let hotspot = Joiner()
        var requestedHosts: [String] = []
        let connection = TCPProvisioningConnection(hotspot: hotspot, makeStream: { host in
            requestedHosts.append(host)
            return Stream(host: fixture.host, port: bootstrap ? fixture.bootstrapPort : fixture.normalPort)
        })
        connection.configure(try SoftAPDescriptor(ssid: "Synthetic fixture", passphrase: "synthetic-password"))
        if lan {
            connection.leaveAccessPoint()
            try connection.useLAN(origin: URL(string: "https://inky-aaaaaaaaaaaabbbbccccdddddddddddd.local:8443")!)
        }
        if bootstrap { _ = try await connection.connectBootstrap(peripheralID: fixture.frameID, identity: identity) }
        else { _ = try await connection.connect(peripheralID: fixture.frameID, identity: identity) }
        let id = UUID().uuidString.lowercased()
        let data = try JSONSerialization.data(withJSONObject: ["v": 1, "id": id, "op": "synthetic.test"])
        let reply: Data
        if bootstrap { reply = try await connection.requestBootstrap(data, timeout: 5) }
        else { reply = try await connection.request(data, timeout: 5) }
        let value = try XCTUnwrap(JSONSerialization.jsonObject(with: reply) as? [String: Any])
        XCTAssertEqual(value["id"] as? String, id)
        XCTAssertEqual(value["ok"] as? Bool, true)
        XCTAssertEqual((value["result"] as? [String: Bool])?["synthetic"], true)
        XCTAssertEqual(hotspot.joins, lan ? 0 : 1)
        XCTAssertEqual(requestedHosts, [lan ? "inky-aaaaaaaaaaaabbbbccccdddddddddddd.local" : "192.168.4.1"])
        connection.disconnect()
    }
}
