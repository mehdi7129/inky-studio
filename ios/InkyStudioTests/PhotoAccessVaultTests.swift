import XCTest
@testable import InkyStudio

/// Serialization/state tests with injected storage. These do not prove a physical Keychain ACL or Face ID prompt.
@MainActor
final class PhotoAccessVaultTests: XCTestCase {
    private func identity() throws -> FrameIdentity {
        try FrameIdentity(id: UUID(uuidString: "11111111-2222-4333-8444-555555555555")!, spkiSHA256: Data(repeating: 0x12, count: 32))
    }
    private func credential() throws -> PhotoAccessCredential {
        try PhotoAccessCredential.make(identity: identity(), endpoint: URL(string: "https://frame.local:8443")!, role: .media, invitationID: UUID())
    }

    func testRoundTripKeepsExactRetryCredentialAndSelectionBindings() async throws {
        let memory = AccessMemory()
        let vault = memory.vault()
        let original = try credential()
        let selection = PhotoAccessSelection(original)
        try vault.save(original, account: selection.account)
        let restored = try await vault.loadCredential(account: selection.account)
        XCTAssertEqual(restored, original)
        XCTAssertTrue(selection.validates(restored))
        XCTAssertEqual(restored.deviceToken.count, 64)
        XCTAssertEqual(restored.state, .pending)
        XCTAssertEqual(memory.writes, 1)
        let marker = try JSONEncoder().encode(selection)
        XCTAssertFalse(String(decoding: marker, as: UTF8.self).contains(original.deviceToken))
        XCTAssertFalse(String(decoding: marker, as: UTF8.self).contains(original.requestID.uuidString))
    }

    func testFailedProtectedWriteDoesNotReplaceOldCredential() async throws {
        let memory = AccessMemory()
        let vault = memory.vault()
        let original = try credential()
        let account = PhotoAccessSelection(original).account
        try vault.save(original, account: account)
        memory.rejectWrites = true
        var replacement = original; replacement.state = .active
        XCTAssertThrowsError(try vault.save(replacement, account: account))
        let retained = try await vault.loadCredential(account: account)
        XCTAssertEqual(retained, original)
    }

    func testIssuerDraftRetainsExactTokenIDsAndExpiryUntilExplicitPurge() async throws {
        let memory = AccessMemory()
        let vault = memory.vault()
        var draft = try PhotoInvitationDraft.make(identity: identity(), endpoint: URL(string: "https://frame.local:8443")!)
        draft.expiresAt = Date().timeIntervalSince1970 + 300
        try vault.save(draft, account: "invitation:selected")
        let restored = try await vault.loadDraft(account: "invitation:selected")
        XCTAssertEqual(restored, draft)
        XCTAssertTrue(vault.contains(account: "invitation:selected"))
        memory.values["unrelated"] = "keep"
        try vault.remove(account: "invitation:selected")
        XCTAssertFalse(vault.contains(account: "invitation:selected"))
        XCTAssertEqual(memory.values["unrelated"], "keep")
    }

    func testInvalidPersistedCredentialFailsClosed() async throws {
        let memory = AccessMemory()
        let vault = memory.vault()
        let original = try credential()
        let data = try JSONEncoder().encode(original)
        var object = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
        for (key, value) in [("deviceToken", "invalid"), ("endpoint", "http://frame.local:8000"), ("expectedRole", "admin")] {
            var corrupted = object; corrupted[key] = value
            memory.values["corrupt"] = String(decoding: try JSONSerialization.data(withJSONObject: corrupted), as: UTF8.self)
            do { _ = try await vault.loadCredential(account: "corrupt"); XCTFail("Malformed credential must not be accepted") } catch {}
        }
        object["deviceToken"] = String(repeating: "A", count: 64)
        memory.values["corrupt"] = String(decoding: try JSONSerialization.data(withJSONObject: object), as: UTF8.self)
        do { _ = try await vault.loadCredential(account: "corrupt"); XCTFail("Noncanonical token must not be accepted") } catch {}
    }

    func testCancelledReadCannotReturnCredential() async throws {
        let original = try credential()
        let text = String(decoding: try JSONEncoder().encode(original), as: UTF8.self)
        let vault = PhotoAccessVault(loadValue: { _ in
            withUnsafeCurrentTask { $0?.cancel() }
            return text
        })
        let read = Task { try await vault.loadCredential(account: "selected") }
        do { _ = try await read.value; XCTFail("Cancelled reads must not expose a credential") }
        catch { XCTAssertTrue(error is CancellationError) }
    }

    func testSelectionRejectsSameDeviceMovedToAnotherIdentityOrOrigin() throws {
        let original = try credential()
        let selection = PhotoAccessSelection(original)
        let changed = try PhotoAccessCredential(identity: original.identity, endpoint: URL(string: "https://other.local:8443")!,
            deviceID: original.deviceID, deviceToken: original.deviceToken, requestID: original.requestID,
            expectedRole: original.expectedRole, invitationID: original.invitationID)
        XCTAssertFalse(selection.validates(changed))
        let changedRole = try PhotoAccessCredential(identity: original.identity, endpoint: original.endpoint,
            deviceID: original.deviceID, deviceToken: original.deviceToken, requestID: original.requestID,
            expectedRole: .owner, invitationID: original.invitationID)
        XCTAssertFalse(selection.validates(changedRole))
    }
}

@MainActor
private final class AccessMemory {
    var values: [String: String] = [:]
    var rejectWrites = false
    var writes = 0
    func vault() -> PhotoAccessVault {
        PhotoAccessVault(saveValue: { value, account in
            guard !self.rejectWrites else { throw VaultError.unavailable }
            self.values[account] = value; self.writes += 1
        }, loadValue: { account in
            guard let value = self.values[account] else { throw VaultError.missing }
            return value
        }, containsValue: { self.values[$0] != nil }, removeValue: { self.values.removeValue(forKey: $0) })
    }
}
