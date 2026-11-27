import Foundation
import XCTest
@testable import InkyStudio

final class SoftAPBootstrapCodeTests: XCTestCase {
    private var qr: String {
        "{\"v\":3,\"p\":\"softap\",\"id\":\"11111111-2222-3333-4444-555555555555\",\"k\":\"\(FrameTrustTestFixtures.pinHex)\",\"t\":\"\(String(repeating: "b", count: 64))\",\"s\":\"Inky synthetic\",\"w\":\"synthetic-ap-password\",\"u\":\"tcp://192.168.4.1:9443\"}"
    }

    func testV3RetainsPhysicalTrustAndOnlyTheFixedAPLocator() throws {
        let code = try FrameBootstrapCode.parse(qr)
        XCTAssertEqual(code.identity.id, FrameTrustTestFixtures.id)
        XCTAssertEqual(code.adoptionToken, Data(repeating: 0xbb, count: 32))
        XCTAssertEqual(code.softAP?.ssid, "Inky synthetic")
        XCTAssertEqual(code.softAP?.passphrase, "synthetic-ap-password")
        XCTAssertThrowsError(try FrameAdoptionCode.parse(qr))
        let bounded = qr + String(repeating: " ", count: 1024 - qr.utf8.count)
        XCTAssertNoThrow(try FrameBootstrapCode.parse(bounded))
        XCTAssertThrowsError(try FrameBootstrapCode.parse(bounded + " "))
    }

    func testV3RejectsDuplicateFieldsTypesProfilesAndArbitraryLocators() {
        let invalid = [qr.replacingOccurrences(of: "{", with: "{\"v\":3,"),
            qr.replacingOccurrences(of: "{", with: "{\"\\u0073\":\"other\","),
            qr.replacingOccurrences(of: "{", with: "{\"extra\":0,"),
            qr.replacingOccurrences(of: "\"v\":3", with: "\"v\":3.0"),
            qr.replacingOccurrences(of: "\"v\":3", with: "\"v\":true"),
            qr.replacingOccurrences(of: "\"p\":\"softap\"", with: "\"p\":\"bootstrap\""),
            qr.replacingOccurrences(of: "tcp://192.168.4.1:9443", with: "tcp://example.com:9443"),
            qr.replacingOccurrences(of: "tcp://192.168.4.1:9443", with: "tcp://192.168.4.1:9443/"),
            qr.replacingOccurrences(of: "synthetic-ap-password", with: "short"),
            qr.replacingOccurrences(of: "synthetic-ap-password", with: "mot-de-passe-é"),
            qr.replacingOccurrences(of: "Inky synthetic", with: String(repeating: "a", count: 33)),
            qr.replacingOccurrences(of: "Inky synthetic", with: "Inky\\u0000test"),
            qr.replacingOccurrences(of: "synthetic-ap-password", with: "secret\\npassword"), qr + "{}"]
        for value in invalid { XCTAssertThrowsError(try FrameBootstrapCode.parse(value), value) }
    }

    func testManifestRejectsWrongProfileIdentityDuplicatesAndCertificateBounds() throws {
        let identity = try FrameIdentity(id: FrameTrustTestFixtures.id, spkiSHA256: Data(repeating: 0, count: 32))
        let valid = "{\"v\":1,\"p\":\"bootstrap\",\"id\":\"\(identity.id.uuidString.lowercased())\",\"c\":\"AQ==\"}"
        XCTAssertEqual(try SoftAPManifest.parse(Data(valid.utf8), profile: .bootstrap, identity: identity).certificateDER, Data([1]))
        let invalid = [valid.replacingOccurrences(of: "{", with: "{\"c\":\"AQ==\","),
            valid.replacingOccurrences(of: "bootstrap", with: "normal"),
            valid.replacingOccurrences(of: "AQ==", with: "AQ"),
            valid.replacingOccurrences(of: "AQ==", with: "AQ==\\n"),
            valid.replacingOccurrences(of: "AQ==", with: Data(count: 2049).base64EncodedString()),
            valid.replacingOccurrences(of: identity.id.uuidString.lowercased(), with: UUID().uuidString.lowercased())]
        for value in invalid { XCTAssertThrowsError(try SoftAPManifest.parse(Data(value.utf8), profile: .bootstrap, identity: identity)) }
    }
}

@MainActor
final class SoftAPTransportTests: XCTestCase {
    private final class Joiner: SoftAPJoining {
        var joins = 0
        var leaves = 0
        var refused = false
        var pending: CheckedContinuation<Void, Error>?
        var block = false
        func join(_ descriptor: SoftAPDescriptor) async throws {
            joins += 1
            if refused { throw SoftAPError.unavailable }
            if block { try await withCheckedThrowingContinuation { pending = $0 } }
        }
        func leave(_ descriptor: SoftAPDescriptor) { leaves += 1 }
        func cancel() { pending?.resume(throwing: SoftAPError.cancelled); pending = nil }
    }
    private final class Stream: ProvisioningByteStream {
        var bytes: Data
        var maximumFragment = 1
        var writes: [Data] = []
        var cancelled = false
        init(_ bytes: Data) { self.bytes = bytes }
        func connect() async throws {}
        func read(maximum: Int) async throws -> Data {
            guard !cancelled, !bytes.isEmpty else { throw SoftAPError.disconnected }
            let part = Data(bytes.prefix(min(maximum, maximumFragment)))
            bytes.removeFirst(part.count)
            return part
        }
        func write(_ bytes: Data) async throws { writes.append(bytes) }
        func cancel() { cancelled = true }
    }
    private func identity(pin: Data? = nil) throws -> FrameIdentity {
        try FrameIdentity(id: FrameTrustTestFixtures.id,
            spkiSHA256: pin ?? PinnedFrameTrust.spkiSHA256(certificateDER: FrameTrustTestFixtures.certificate))
    }
    private func manifest(profile: String = "bootstrap") throws -> Data {
        let data = try JSONSerialization.data(withJSONObject: ["v": 1, "p": profile,
            "id": FrameTrustTestFixtures.id.uuidString.lowercased(), "c": FrameTrustTestFixtures.certificate.base64EncodedString()])
        let count = UInt32(data.count)
        return Data([UInt8(count >> 24), UInt8((count >> 16) & 255), UInt8((count >> 8) & 255), UInt8(count & 255)]) + data
    }
    private func descriptor() throws -> SoftAPDescriptor { try SoftAPDescriptor(ssid: "Synthetic", passphrase: "synthetic-password") }

    func testHotspotRefusalNeverOpensTCPOrSendsAnySecret() async throws {
        let joiner = Joiner(); joiner.refused = true
        var streams = 0
        let connection = TCPProvisioningConnection(hotspot: joiner, makeStream: { _ in streams += 1; return Stream(Data()) })
        connection.configure(try descriptor())
        do { _ = try await connection.connectBootstrap(peripheralID: UUID(), identity: identity()); XCTFail("Expected refusal") }
        catch { XCTAssertEqual(error as? SoftAPError, .unavailable) }
        XCTAssertEqual(streams, 0)
        XCTAssertEqual(joiner.joins, 1)
    }

    func testWrongPinAndMalformedPrefaceSendNoTLSOrApplicationBytes() async throws {
        for data in [try manifest(), Data([0, 0, 16, 1]), Data([0, 0, 0, 0])] {
            let joiner = Joiner(); let stream = Stream(data)
            let connection = TCPProvisioningConnection(hotspot: joiner, makeStream: { _ in stream })
            connection.configure(try descriptor())
            do {
                _ = try await connection.connectBootstrap(peripheralID: UUID(), identity: identity(pin: Data(count: 32)))
                XCTFail("Expected rejection")
            } catch {}
            XCTAssertTrue(stream.writes.isEmpty)
            XCTAssertTrue(stream.cancelled)
        }
    }

    func testFragmentedManifestOnlyPermitsTLSHandshakeNotRPCBeforePeerAuthentication() async throws {
        let joiner = Joiner(); let stream = Stream(try manifest())
        let connection = TCPProvisioningConnection(hotspot: joiner, makeStream: { _ in stream })
        connection.configure(try descriptor())
        do { _ = try await connection.connectBootstrap(peripheralID: UUID(), identity: identity()); XCTFail("Peer has no TLS server") }
        catch {}
        XCTAssertFalse(stream.writes.isEmpty, "The validated manifest starts the real TLSClient handshake")
        XCTAssertEqual(stream.writes.first?.first, 22, "TLS handshake record")
        XCTAssertTrue(stream.cancelled)
        do { _ = try await connection.requestBootstrap(Data("secret".utf8), timeout: 1); XCTFail("Not authenticated") }
        catch { XCTAssertEqual(error as? SoftAPError, .disconnected) }
    }

    func testLANReconnectDoesNotRequestHotspotConsentOrRejoinAP() async throws {
        let joiner = Joiner(); let stream = Stream(Data([0, 0, 0, 0]))
        var hosts: [String] = []
        let connection = TCPProvisioningConnection(hotspot: joiner, makeStream: { hosts.append($0); return stream })
        connection.configure(try descriptor())
        connection.leaveAccessPoint()
        try connection.useLAN(origin: URL(string: "https://inky-11111111222233334444555555555555.local:8443")!)
        do { _ = try await connection.connect(peripheralID: UUID(), identity: identity()); XCTFail("Invalid manifest") } catch {}
        XCTAssertEqual(joiner.joins, 0)
        XCTAssertEqual(joiner.leaves, 1)
        XCTAssertEqual(hosts, ["inky-11111111222233334444555555555555.local"])
    }

    func testActualNormalManifestRedirectsOnlyAfterStrictPinValidationAndSendsNoRPC() async throws {
        for wrongPin in [false, true] {
            let joiner = Joiner(); let stream = Stream(try manifest(profile: "normal"))
            let connection = TCPProvisioningConnection(hotspot: joiner, makeStream: { _ in stream })
            connection.configure(try descriptor())
            do {
                _ = try await connection.connectBootstrap(peripheralID: UUID(),
                    identity: identity(pin: wrongPin ? Data(count: 32) : nil))
                XCTFail("Expected typed profile redirect or pin refusal")
            } catch {
                if wrongPin { XCTAssertEqual(error as? FrameIdentityError, .pinMismatch) }
                else { XCTAssertEqual(error as? SoftAPError, .normalProfileAvailable) }
            }
            XCTAssertTrue(stream.writes.isEmpty)
        }
    }

    func testDisconnectInvalidatesJoinOnceBeforeTheNextAPConnection() async throws {
        let joiner = Joiner()
        let connection = TCPProvisioningConnection(hotspot: joiner, makeStream: { _ in Stream(Data([0, 0, 0, 0])) })
        connection.configure(try descriptor())
        for _ in 0..<2 {
            do { _ = try await connection.connectBootstrap(peripheralID: UUID(), identity: identity()); XCTFail("Invalid manifest") }
            catch {}
            connection.disconnect()
        }
        XCTAssertEqual(joiner.joins, 2, "A disconnected joinOnce session must request association again")
    }

    func testCancellationDuringHotspotPromptCannotContinueToTCP() async throws {
        let joiner = Joiner(); joiner.block = true
        var streams = 0
        let connection = TCPProvisioningConnection(hotspot: joiner, makeStream: { _ in streams += 1; return Stream(Data()) })
        connection.configure(try descriptor())
        let identity = try identity()
        let operation = Task { try await connection.connectBootstrap(peripheralID: UUID(), identity: identity) }
        while joiner.pending == nil { await Task.yield() }
        operation.cancel()
        do { _ = try await operation.value; XCTFail("Cancelled") } catch {}
        XCTAssertEqual(streams, 0)
    }
}
