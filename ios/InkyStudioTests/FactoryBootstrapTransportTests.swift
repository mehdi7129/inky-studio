import CoreBluetooth
import Foundation
import XCTest
@testable import InkyStudio

final class FrameBootstrapCodeTests: XCTestCase {
    private let id = "01234567-89ab-4cde-8fab-0123456789ab"
    private var qr: String {
        "{\"v\":2,\"p\":\"bootstrap\",\"id\":\"\(id)\",\"k\":\"\(String(repeating: "a", count: 64))\",\"t\":\"\(String(repeating: "b", count: 64))\"}"
    }

    func testFactoryQRIsTypedAndDistinctFromNormalV1() throws {
        let code = try FrameBootstrapCode.parse(qr)
        XCTAssertEqual(code.identity.id.uuidString.lowercased(), id)
        XCTAssertEqual(code.identity.spkiSHA256, Data(repeating: 0xaa, count: 32))
        XCTAssertEqual(code.adoptionToken, Data(repeating: 0xbb, count: 32))
        XCTAssertThrowsError(try FrameAdoptionCode.parse(qr))
        let normal = qr.replacingOccurrences(of: "\"v\":2,\"p\":\"bootstrap\",", with: "\"v\":1,")
        XCTAssertNoThrow(try FrameAdoptionCode.parse(normal))
        XCTAssertThrowsError(try FrameBootstrapCode.parse(normal))
    }

    func testFactoryQRRejectsAmbiguousTypesProfilesDuplicatesAndExtraFields() {
        var invalid = [String]()
        for version in ["true", "false", "2.0", "2e0", "02", "\"2\"", "1", "3", "null", "[]"] {
            invalid.append(qr.replacingOccurrences(of: "\"v\":2", with: "\"v\":\(version)"))
        }
        for prefix in ["\"v\":2,", "\"\\u0076\":2,", "\"p\":\"bootstrap\",", "\"owner_token\":\"x\","] {
            invalid.append("{" + prefix + qr.dropFirst())
        }
        invalid += [qr.replacingOccurrences(of: "bootstrap", with: "normal-v1"),
                    qr.replacingOccurrences(of: "\"p\":\"bootstrap\",", with: ""),
                    qr.replacingOccurrences(of: id, with: id.uppercased()),
                    qr.replacingOccurrences(of: String(repeating: "a", count: 64), with: String(repeating: "A", count: 64)),
                    qr.replacingOccurrences(of: String(repeating: "b", count: 64), with: String(repeating: "b", count: 62)),
                    qr + "{}", qr.replacingOccurrences(of: "}", with: ",}"), "https://example.com/" + qr]
        for text in invalid { XCTAssertThrowsError(try FrameBootstrapCode.parse(text)) }
    }

    func testFactoryQRBoundAndTokenConstructorAreFailClosed() throws {
        let exact = qr + String(repeating: " ", count: 512 - qr.utf8.count)
        XCTAssertNoThrow(try FrameBootstrapCode.parse(exact))
        XCTAssertThrowsError(try FrameBootstrapCode.parse(exact + " "))
        XCTAssertThrowsError(try FrameBootstrapCode(identity: FrameBootstrapCode.parse(qr).identity, adoptionToken: Data(count: 31)))
    }
}

@MainActor
final class BootstrapGATTProfileTests: XCTestCase {
    func testServiceAndAllCharacteristicsAreProfileBound() {
        for (profile, prefix) in [(BluetoothProfile.normalV1, "000"), (.bootstrap, "001")] {
            let values = [profile.serviceUUID, profile.identityUUID, profile.streamUUID] + profile.certificateUUIDs
            for (index, value) in values.enumerated() {
                XCTAssertEqual(value.uuidString.lowercased(), "713b\(prefix)\(index + 1)-8890-4cc9-a2bf-26f32c43db22")
            }
        }
        XCTAssertEqual(BluetoothTransport.serviceUUID, BluetoothProfile.normalV1.serviceUUID)
    }

    func testBootstrapMetadataAssemblesOnlyExactProfileAndCertificateParts() throws {
        let id = UUID(uuidString: "01234567-89ab-4cde-8fab-0123456789ab")!
        for count in [1, 480, 481, 960] {
            var assembly = BluetoothIdentityAssembly(profile: .bootstrap)
            let metadata = Data("{\"v\":2,\"p\":\"bootstrap\",\"id\":\"\(id.uuidString.lowercased())\",\"cert_length\":\(count)}".utf8)
            let certificate = Data((0..<count).map { UInt8($0 % 251) })
            try assembly.readMetadata(metadata)
            try assembly.readFirstCertificatePart(Data(certificate.prefix(480)))
            let result = try assembly.finish(secondCertificatePart: Data(certificate.dropFirst(min(count, 480))))
            let fields = try XCTUnwrap(JSONSerialization.jsonObject(with: result) as? [String: Any])
            XCTAssertEqual(Set(fields.keys), ["v", "p", "id", "cert"])
            XCTAssertEqual(fields["v"] as? Int, 2)
            XCTAssertEqual(fields["p"] as? String, "bootstrap")
            XCTAssertEqual(Data(base64Encoded: try XCTUnwrap(fields["cert"] as? String)), certificate)
            var normal = BluetoothIdentityAssembly()
            XCTAssertThrowsError(try normal.readMetadata(metadata))
        }
    }

    func testBootstrapMetadataRejectsUnknownProfileTypesDuplicatesBoundsAndMixedParts() throws {
        let metadata = "{\"v\":2,\"p\":\"bootstrap\",\"id\":\"01234567-89ab-4cde-8fab-0123456789ab\",\"cert_length\":600}"
        var invalid = [metadata.replacingOccurrences(of: "\"v\":2", with: "\"v\":1"),
                       metadata.replacingOccurrences(of: "\"p\":\"bootstrap\",", with: ""),
                       metadata.replacingOccurrences(of: "bootstrap", with: "normal-v1"),
                       metadata.replacingOccurrences(of: "{", with: "{\"\\u0076\":2,"),
                       metadata.replacingOccurrences(of: "{", with: "{\"extra\":1,"),
                       metadata.replacingOccurrences(of: "89ab", with: "89AB")]
        for length in ["0", "961", "600.0", "6e2", "true", "\"600\"", "-1"] {
            invalid.append(metadata.replacingOccurrences(of: "600", with: length))
        }
        for text in invalid {
            var assembly = BluetoothIdentityAssembly(profile: .bootstrap)
            XCTAssertThrowsError(try assembly.readMetadata(Data(text.utf8)))
        }
        var assembly = BluetoothIdentityAssembly(profile: .bootstrap)
        try assembly.readMetadata(Data(metadata.utf8))
        XCTAssertThrowsError(try assembly.readMetadata(Data(metadata.utf8)))
        XCTAssertThrowsError(try assembly.readFirstCertificatePart(Data(count: 479)))
        try assembly.readFirstCertificatePart(Data(count: 480))
        XCTAssertThrowsError(try assembly.finish(secondCertificatePart: Data(count: 119)))
        XCTAssertThrowsError(try assembly.finish(secondCertificatePart: Data(count: 121)))
    }
}

@MainActor
final class BootstrapBluetoothChannelTests: XCTestCase {
    private final class ProfileTransport: BluetoothExchanging {
        let maxFrameLength = 244
        var identity = Data()
        var profiles: [BluetoothProfile] = []
        var frames: [Data] = []
        var pending: CheckedContinuation<Data, Error>?
        var onHandshake: (() -> Void)?
        func connect(peripheralID: UUID) async throws -> Data { try await connect(peripheralID: peripheralID, profile: .normalV1) }
        func connect(peripheralID: UUID, profile: BluetoothProfile) async throws -> Data {
            profiles.append(profile)
            return identity
        }
        func exchange(_ frame: Data) async throws -> Data {
            frames.append(frame)
            if frame.first == 0 { return frame }
            return try await withCheckedThrowingContinuation { pending = $0; onHandshake?() }
        }
        func cancel() { let previous = pending; pending = nil; previous?.resume(throwing: BluetoothTransportError.cancelled) }
    }
    private final class LegacyTransport: BluetoothExchanging {
        let maxFrameLength = 20
        var calls = 0
        func connect(peripheralID: UUID) async throws -> Data { calls += 1; return Data() }
        func exchange(_ frame: Data) async throws -> Data { calls += 1; return Data() }
        func cancel() {}
    }

    private func identity() throws -> FrameIdentity {
        try FrameIdentity(id: FrameTrustTestFixtures.id,
                          spkiSHA256: PinnedFrameTrust.spkiSHA256(certificateDER: FrameTrustTestFixtures.certificate))
    }
    private func advertised(_ identity: FrameIdentity) throws -> Data {
        try JSONSerialization.data(withJSONObject: ["v": 2, "p": "bootstrap", "id": identity.id.uuidString.lowercased(),
            "cert": FrameTrustTestFixtures.certificate.base64EncodedString()])
    }

    func testNormalOnlyAdapterCannotSilentlyConnectBootstrap() async throws {
        let transport = LegacyTransport()
        let channel = SecureBluetoothChannel(transport: transport)
        do { _ = try await channel.connectBootstrap(peripheralID: UUID(), identity: identity()); XCTFail("Normal adapter accepted bootstrap") }
        catch { XCTAssertEqual(error as? BluetoothTransportError, .unsupportedFrame) }
        XCTAssertEqual(transport.calls, 0)
        XCTAssertNil(channel.bootstrapTrust)
        XCTAssertNil(channel.trust)
    }

    func testBootstrapWrongMetadataAndPinFailBeforeResetOrTLS() async throws {
        let expected = try identity()
        let transport = ProfileTransport()
        let channel = SecureBluetoothChannel(transport: transport)
        let correct = try advertised(expected)
        var wrong = try XCTUnwrap(String(data: correct, encoding: .utf8))
        wrong = wrong.replacingOccurrences(of: "\"v\":2", with: "\"v\":2.0")
        for data in [Data("{}".utf8), Data(wrong.utf8), Data(repeating: 32, count: 4097)] {
            transport.identity = data
            do { _ = try await channel.connectBootstrap(peripheralID: UUID(), identity: expected); XCTFail("Invalid bootstrap metadata accepted") }
            catch {}
        }
        transport.identity = correct
        let wrongPin = try FrameIdentity(id: expected.id, spkiSHA256: Data(count: 32))
        do { _ = try await channel.connectBootstrap(peripheralID: UUID(), identity: wrongPin); XCTFail("Wrong pin accepted") }
        catch { XCTAssertEqual(error as? FrameIdentityError, .pinMismatch) }
        XCTAssertEqual(transport.frames.count, 0)
        XCTAssertTrue(transport.profiles.allSatisfy { $0 == .bootstrap })
    }

    func testNoBootstrapOrNormalRequestCanSendASecretBeforeHandshakeOrAfterCancellation() async throws {
        let expected = try identity()
        let transport = ProfileTransport()
        transport.identity = try advertised(expected)
        let started = expectation(description: "Real bootstrap TLS handshake reached the transport")
        transport.onHandshake = { started.fulfill() }
        let channel = SecureBluetoothChannel(transport: transport)
        let connect = Task { try await channel.connectBootstrap(peripheralID: UUID(), identity: expected) }
        await fulfillment(of: [started], timeout: 3)
        XCTAssertNil(channel.bootstrapTrust)
        XCTAssertNil(channel.trust)
        let count = transport.frames.count
        let syntheticSecret = Data("{\"claim_token\":\"synthetic-only-secret\"}".utf8)
        do { _ = try await channel.requestBootstrap(syntheticSecret); XCTFail("Bootstrap secret admitted before TLS/ALPN") }
        catch { XCTAssertEqual(error as? SecureBluetoothError, .notConnected) }
        do { _ = try await channel.request(syntheticSecret); XCTFail("Normal request admitted on pending bootstrap") }
        catch { XCTAssertEqual(error as? SecureBluetoothError, .notConnected) }
        XCTAssertEqual(transport.frames.count, count)
        connect.cancel()
        do { _ = try await connect.value; XCTFail("Cancelled bootstrap became trusted") }
        catch { XCTAssertEqual(error as? SecureBluetoothError, .cancelled) }
        XCTAssertNil(channel.bootstrapTrust)
        XCTAssertNil(channel.trust)
        do { _ = try await channel.requestBootstrap(syntheticSecret); XCTFail("Cancelled bootstrap reused") }
        catch { XCTAssertEqual(error as? SecureBluetoothError, .notConnected) }
    }
}
