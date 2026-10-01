import Foundation
import Security
import XCTest
@testable import InkyStudio

@MainActor
final class OwnershipVaultTests: XCTestCase {
    func testSeventeenthEndpointEvictsOldestAndPersistsPendingTransaction() throws {
        try withRecord(endpoints: (1...16).map(endpoint)) { vault, before, service in
            let after = try vault.markClaimed(id: before.id, endpoint: endpoint(17))

            XCTAssertEqual(after.endpoints, (2...17).map(endpoint))
            assertOwnershipPreserved(after, from: before)
            XCTAssertEqual(try OwnershipVault(service: service).load(id: before.id), after)

            // Endpoint history must not prevent the existing transaction from finishing.
            let transactionID = try XCTUnwrap(before.wifiTransactionID)
            let finished = try vault.finishWiFiTransaction(id: before.id, transactionID: transactionID)
            XCTAssertNil(finished.wifiTransactionID)
            XCTAssertNil(finished.wifiSSID)
            XCTAssertEqual(finished.endpoints, after.endpoints)
            XCTAssertEqual(finished.ownerToken, before.ownerToken)
            XCTAssertEqual(try OwnershipVault(service: service).load(id: before.id), finished)
        }
    }

    func testRevisitedEndpointBecomesMostRecentWithoutDuplicates() throws {
        try withRecord(endpoints: (1...16).map(endpoint)) { vault, before, service in
            let revisited = endpoint(5)
            let after = try vault.markClaimed(id: before.id, endpoint: revisited)
            let expected = before.endpoints.filter { $0 != revisited } + [revisited]

            XCTAssertEqual(after.endpoints, expected)
            XCTAssertEqual(after.endpoints.count, 16)
            XCTAssertEqual(after.endpoints.filter { $0 == revisited }.count, 1)
            assertOwnershipPreserved(after, from: before)
            XCTAssertEqual(try OwnershipVault(service: service).load(id: before.id), after)
        }
    }

    func testExistingDuplicatesKeepOnlyTheirMostRecentOccurrence() throws {
        let history = [endpoint(1), endpoint(2), endpoint(1), endpoint(3)]
        try withRecord(endpoints: history) { vault, before, service in
            let after = try vault.markClaimed(id: before.id, endpoint: endpoint(4))

            XCTAssertEqual(after.endpoints, [endpoint(2), endpoint(1), endpoint(3), endpoint(4)])
            assertOwnershipPreserved(after, from: before)
            XCTAssertEqual(try OwnershipVault(service: service).load(id: before.id), after)
        }
    }

    func testInvalidEndpointLeavesPersistedOwnershipAndTransactionUntouched() throws {
        try withRecord(endpoints: (1...16).map(endpoint)) { vault, before, service in
            let originalData = try storedData(service: service, id: before.id)
            for address in ["http://192.0.2.17:8443", "https://user:synthetic@192.0.2.17:8443",
                            "https://192.0.2.17:8443/api", "https://192.0.2.17:8443/?token=synthetic"] {
                XCTAssertThrowsError(try vault.markClaimed(id: before.id, endpoint: XCTUnwrap(URL(string: address))))
                XCTAssertEqual(try storedData(service: service, id: before.id), originalData)
                XCTAssertEqual(try OwnershipVault(service: service).load(id: before.id), before)
            }
        }
    }

    private func endpoint(_ number: Int) -> URL {
        // RFC 5737 documentation addresses; these tests never open a connection.
        URL(string: "https://192.0.2.\(number):8443")!
    }

    private func assertOwnershipPreserved(_ after: OwnershipRecord, from before: OwnershipRecord,
                                          file: StaticString = #filePath, line: UInt = #line) {
        XCTAssertEqual(after.identity, before.identity, file: file, line: line)
        XCTAssertEqual(after.certificateDER, before.certificateDER, file: file, line: line)
        XCTAssertEqual(after.ownerID, before.ownerID, file: file, line: line)
        XCTAssertEqual(after.claimRequestID, before.claimRequestID, file: file, line: line)
        XCTAssertEqual(after.ownerToken, before.ownerToken, file: file, line: line)
        XCTAssertEqual(after.wifiTransactionID, before.wifiTransactionID, file: file, line: line)
        XCTAssertEqual(after.wifiSSID, before.wifiSSID, file: file, line: line)
        XCTAssertEqual(after.state, .claimed, file: file, line: line)
    }

    private func withRecord(endpoints: [URL],
                            _ body: (OwnershipVault, OwnershipRecord, String) throws -> Void) throws {
        // A fresh namespace per case isolates all reads, writes and cleanup from
        // the application's real ownership service and any previous test run.
        let service = "InkyOwnershipVaultTests.\(UUID().uuidString)"
        let certificate = FrameTrustTestFixtures.certificate
        let identity = try FrameIdentity(id: FrameTrustTestFixtures.id,
                                         spkiSHA256: PinnedFrameTrust.spkiSHA256(certificateDER: certificate))
        let record = OwnershipRecord(identity: identity, certificateDER: certificate,
                                     ownerID: UUID(), claimRequestID: UUID(),
                                     ownerToken: Data(repeating: 0xa5, count: 32),
                                     endpoints: endpoints, state: .claimed,
                                     wifiTransactionID: UUID(), wifiSSID: "Synthetic history network")
        let query = keychainQuery(service: service, id: record.id)
        var insertion = query
        insertion[kSecAttrAccessible as String] = kSecAttrAccessibleWhenUnlockedThisDeviceOnly
        insertion[kSecValueData as String] = try JSONEncoder().encode(record)
        let status = SecItemAdd(insertion as CFDictionary, nil)
        XCTAssertEqual(status, errSecSuccess)
        guard status == errSecSuccess else { throw OwnershipVaultError.unavailable }
        defer { XCTAssertEqual(SecItemDelete(query as CFDictionary), errSecSuccess) }

        let vault = OwnershipVault(service: service)
        XCTAssertEqual(try vault.load(id: record.id), record)
        try body(vault, record, service)
    }

    private func storedData(service: String, id: UUID) throws -> Data {
        var query = keychainQuery(service: service, id: id)
        query[kSecReturnData as String] = true
        query[kSecMatchLimit as String] = kSecMatchLimitOne
        var result: CFTypeRef?
        XCTAssertEqual(SecItemCopyMatching(query as CFDictionary, &result), errSecSuccess)
        return try XCTUnwrap(result as? Data)
    }

    private func keychainQuery(service: String, id: UUID) -> [String: Any] {
        precondition(service.hasPrefix("InkyOwnershipVaultTests."))
        return [kSecClass as String: kSecClassGenericPassword,
                kSecAttrService as String: service,
                kSecAttrAccount as String: id.uuidString.lowercased()]
    }
}
