import XCTest
import Security
@testable import InkyStudio

@MainActor final class BootstrapOwnershipVaultTests: XCTestCase {
    func testPendingAndAdoptedRetainOneIntentionWithoutNormalTrustOrQRSecret() throws {
        let vault = BootstrapOwnershipVault(service: "inky.bootstrap.test.\(UUID().uuidString)")
        let identity = try FrameIdentity(id: FrameTrustTestFixtures.id,
            spkiSHA256: XCTUnwrap(Data.bootstrapHexBytes(FrameTrustTestFixtures.pinHex)))
        defer { try? vault.remove(id: identity.id) }
        let pending = try vault.prepare(identity: identity, certificateDER: FrameTrustTestFixtures.certificate)
        XCTAssertEqual(try vault.load(id: identity.id), pending)
        let repeated = try vault.prepare(identity: identity, certificateDER: FrameTrustTestFixtures.certificate)
        XCTAssertEqual(repeated, pending)
        let adopted = try vault.markAdopted(record: pending)
        XCTAssertEqual(adopted.state, .adoptedAwaitingPreparation)
        let afterRescan = try vault.prepare(identity: identity, certificateDER: FrameTrustTestFixtures.certificate)
        XCTAssertEqual(afterRescan, adopted)
        XCTAssertEqual(afterRescan.ownerID, pending.ownerID)
        XCTAssertEqual(afterRescan.claimRequestID, pending.claimRequestID)
        XCTAssertEqual(afterRescan.ownerToken, pending.ownerToken)
        XCTAssertEqual(try vault.allRecords(), [adopted])
        let fields = try XCTUnwrap(JSONSerialization.jsonObject(with: JSONEncoder().encode(adopted)) as? [String: Any])
        XCTAssertNil(fields["claimToken"])
        XCTAssertNil(fields["endpoints"])
        XCTAssertNil(fields["wifiTransactionID"])
        XCTAssertEqual(fields["provenance"] as? String, "physicalBootstrapQRV2")
    }
    func testDifferentPhysicalPinCannotReplaceStoredBootstrapOwner() throws {
        let vault = BootstrapOwnershipVault(service: "inky.bootstrap.test.\(UUID().uuidString)")
        let identity = try FrameIdentity(id: FrameTrustTestFixtures.id,
            spkiSHA256: XCTUnwrap(Data.bootstrapHexBytes(FrameTrustTestFixtures.pinHex)))
        defer { try? vault.remove(id: identity.id) }
        let original = try vault.prepare(identity: identity, certificateDER: FrameTrustTestFixtures.certificate)
        let changed = try FrameIdentity(id: identity.id,
            spkiSHA256: PinnedFrameTrust.spkiSHA256(certificateDER: FrameTrustTestFixtures.newKeyCertificate))
        XCTAssertThrowsError(try vault.prepare(identity: changed, certificateDER: FrameTrustTestFixtures.newKeyCertificate))
        XCTAssertEqual(try vault.load(id: identity.id), original)
    }
    func testFutureCertificateRemainsTypedBootstrapAndDoesNotEnterNormalVault() throws {
        let service = "inky.bootstrap.test.\(UUID().uuidString)"
        let bootstrap = BootstrapOwnershipVault(service: service)
        let normal = OwnershipVault(service: service + ".normal")
        let identity = try FrameIdentity(id: FrameTrustTestFixtures.id,
            spkiSHA256: XCTUnwrap(Data.bootstrapHexBytes(FrameTrustTestFixtures.pinHex)))
        defer { try? bootstrap.remove(id: identity.id) }
        let record = try bootstrap.prepare(identity: identity, certificateDER: FrameTrustTestFixtures.renewedCertificate)
        XCTAssertEqual(record.provenance, .physicalBootstrapQRV2)
        XCTAssertNil(try normal.load(id: identity.id))
        XCTAssertThrowsError(try PinnedFrameTrust(identity: identity, certificateDER: record.certificateDER,
            at: FrameTrustTestFixtures.date))
        XCTAssertNoThrow(try record.validate())
    }
    func testCorruptedDurableBlobStaysClosedWithoutReplacementCredential() throws {
        let service = "inky.bootstrap.test.\(UUID().uuidString)"
        let vault = BootstrapOwnershipVault(service: service)
        let identity = try FrameIdentity(id: FrameTrustTestFixtures.id,
            spkiSHA256: XCTUnwrap(Data.bootstrapHexBytes(FrameTrustTestFixtures.pinHex)))
        defer { try? vault.remove(id: identity.id) }
        let original = try vault.prepare(identity: identity, certificateDER: FrameTrustTestFixtures.certificate)
        let bytes = try JSONEncoder().encode(original)
        let corrupted = Data((String(decoding: bytes.dropLast(), as: UTF8.self) + ",\"unexpected\":true}").utf8)
        let query: [String: Any] = [kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service, kSecAttrAccount as String: identity.id.uuidString.lowercased()]
        XCTAssertEqual(SecItemUpdate(query as CFDictionary, [kSecValueData as String: corrupted] as CFDictionary), errSecSuccess)
        XCTAssertThrowsError(try vault.load(id: identity.id))
        XCTAssertThrowsError(try vault.prepare(identity: identity, certificateDER: FrameTrustTestFixtures.certificate))
        var readQuery = query
        readQuery[kSecReturnData as String] = true
        var result: CFTypeRef?
        XCTAssertEqual(SecItemCopyMatching(readQuery as CFDictionary, &result), errSecSuccess)
        XCTAssertEqual(result as? Data, corrupted)
    }

    func testMarkAdoptedRejectsAnotherOwnerOrClaimWithoutMutation() throws {
        let vault = BootstrapOwnershipVault(service: "inky.bootstrap.test.\(UUID().uuidString)")
        let identity = try FrameIdentity(id: FrameTrustTestFixtures.id,
            spkiSHA256: XCTUnwrap(Data.bootstrapHexBytes(FrameTrustTestFixtures.pinHex)))
        defer { try? vault.remove(id: identity.id) }
        let original = try vault.prepare(identity: identity, certificateDER: FrameTrustTestFixtures.certificate)
        let stranger = BootstrapOwnershipRecord(provenance: original.provenance, identity: identity,
            certificateDER: original.certificateDER, ownerID: UUID(), ownerToken: original.ownerToken,
            claimRequestID: UUID(), state: .pending)
        XCTAssertThrowsError(try vault.markAdopted(record: stranger))
        XCTAssertEqual(try vault.load(id: identity.id), original)
    }
}
