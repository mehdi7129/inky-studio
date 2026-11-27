import Foundation
import Security
import XCTest
@testable import InkyStudio

@MainActor
final class FactorySetupCheckpointTests: XCTestCase {
    func testCheckpointRoundTripRejectsForeignBindingAndChangedIntent() throws {
        let owner = try FactorySetupFixtures.owner()
        let binding = FactorySetupBinding(owner: owner)
        var checkpoint = try sampleCheckpoint(binding: binding)
        let data = try JSONEncoder().encode(checkpoint)
        let restored = try JSONDecoder().decode(FactorySetupCheckpoint.self, from: data)
        XCTAssertEqual(restored, checkpoint)
        XCTAssertNoThrow(try restored.validate(binding: binding))
        let foreignOwner = OwnershipRecord(identity: owner.identity, certificateDER: Data(), ownerID: UUID(),
            claimRequestID: owner.claimRequestID, ownerToken: owner.ownerToken, endpoints: [], state: .claimed)
        XCTAssertThrowsError(try restored.validate(binding: FactorySetupBinding(owner: foreignOwner)))
        let challenge = try XCTUnwrap(checkpoint.challenge)
        checkpoint.applyIntent = FactorySetupApplyIntent(requestID: UUID(), utcSeconds: 1_792_152_000, country: "US", challenge: challenge)
        XCTAssertThrowsError(try checkpoint.validate(binding: binding))
    }

    func testKeychainPersistsExactIntentAcrossInstancesWithDeviceOnlyProtectionAndScopedAccounts() throws {
        let service = "FactorySetupCheckpointTests.\(UUID().uuidString)"
        defer { SecItemDelete([kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service] as CFDictionary) }
        let owner = try FactorySetupFixtures.owner(), binding = FactorySetupBinding(owner: owner)
        let checkpoint = try sampleCheckpoint(binding: binding)
        let first = FactorySetupKeychainCheckpointStore(service: service)
        try first.save(checkpoint)
        let reopened = FactorySetupKeychainCheckpointStore(service: service)
        XCTAssertEqual(try reopened.load(binding: binding), checkpoint)
        let query: [String: Any] = [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service,
            kSecReturnAttributes as String: true, kSecMatchLimit as String: kSecMatchLimitOne]
        var result: CFTypeRef?
        XCTAssertEqual(SecItemCopyMatching(query as CFDictionary, &result), errSecSuccess)
        let attributes = try XCTUnwrap(result as? [String: Any])
        XCTAssertEqual(attributes[kSecAttrAccessible as String] as? String, kSecAttrAccessibleWhenUnlockedThisDeviceOnly as String)
        let changedClaim = OwnershipRecord(identity: owner.identity, certificateDER: Data(), ownerID: owner.ownerID,
            claimRequestID: UUID(), ownerToken: owner.ownerToken, endpoints: [], state: .claimed)
        XCTAssertNil(try reopened.load(binding: FactorySetupBinding(owner: changedClaim)))
        let changedPin = try FrameIdentity(id: owner.id, spkiSHA256: Data(repeating: 0xcd, count: 32))
        let changedIdentity = OwnershipRecord(identity: changedPin, certificateDER: Data(), ownerID: owner.ownerID,
            claimRequestID: owner.claimRequestID, ownerToken: owner.ownerToken, endpoints: [], state: .claimed)
        XCTAssertNil(try reopened.load(binding: FactorySetupBinding(owner: changedIdentity)))
        // Atomic update changes only this checkpoint, and removal is similarly claim-scoped.
        var updated = checkpoint
        updated.applyIntent = FactorySetupApplyIntent(requestID: UUID(), utcSeconds: 1_792_152_000, country: checkpoint.country,
                                                      challenge: try XCTUnwrap(checkpoint.challenge))
        try reopened.save(updated)
        XCTAssertEqual(try first.load(binding: binding), updated)
        try reopened.remove(binding: FactorySetupBinding(owner: changedClaim))
        XCTAssertEqual(try first.load(binding: binding), updated)
        try reopened.remove(binding: binding)
        XCTAssertNil(try first.load(binding: binding))
    }

    func testMalformedOrOversizedStoredCheckpointFailsClosedWithoutDeletion() throws {
        let service = "FactorySetupCheckpointInvalidTests.\(UUID().uuidString)"
        defer { SecItemDelete([kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service] as CFDictionary) }
        let binding = FactorySetupBinding(owner: try FactorySetupFixtures.owner())
        let store = FactorySetupKeychainCheckpointStore(service: service)
        try store.save(sampleCheckpoint(binding: binding))
        let query = [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service] as [String: Any]
        for invalid in [Data("{}".utf8), Data(repeating: 32, count: 16_385)] {
            XCTAssertEqual(SecItemUpdate(query as CFDictionary, [kSecValueData as String: invalid] as CFDictionary), errSecSuccess)
            XCTAssertThrowsError(try store.load(binding: binding))
            var read = query; read[kSecReturnData as String] = true
            var value: CFTypeRef?
            XCTAssertEqual(SecItemCopyMatching(read as CFDictionary, &value), errSecSuccess)
            XCTAssertEqual(value as? Data, invalid)
        }
    }

    private func sampleCheckpoint(binding: FactorySetupBinding) throws -> FactorySetupCheckpoint {
        let challenge = try FactorySetupWire.decodeChallenge(FactorySetupFixtures.reply(FactorySetupFixtures.challengeResult()),
            requestID: FactorySetupFixtures.rpc, operationID: FactorySetupFixtures.operation)
        return FactorySetupCheckpoint(binding: binding, operationID: FactorySetupFixtures.operation, country: "FR",
            supersedesOperationID: nil, challengeRequestID: FactorySetupFixtures.rpc, challenge: challenge,
            applyIntent: FactorySetupApplyIntent(requestID: UUID(), utcSeconds: 1_792_152_000, country: "FR", challenge: challenge))
    }
}
