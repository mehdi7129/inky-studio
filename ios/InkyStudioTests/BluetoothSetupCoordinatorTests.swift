import XCTest
@testable import InkyStudio

@MainActor
final class BluetoothSetupCoordinatorTests: XCTestCase {
    func testKeychainSaveFailurePreventsSendingClaim() async throws {
        let harness = try SetupHarness()
        harness.vault.rejectPrepare = true
        harness.coordinator.acceptQRCode(harness.qr)
        await harness.coordinator.connect(peripheralID: UUID())
        XCTAssertTrue(harness.channel.operations.isEmpty)
        XCTAssertEqual(harness.coordinator.stage, .nearby)
        XCTAssertNotNil(harness.coordinator.errorMessage)
    }

    func testClaimUsesCredentialAndRequestIDPersistedBeforeMutation() async throws {
        let harness = try SetupHarness()
        await harness.adopt()
        let record = try XCTUnwrap(harness.vault.record)
        let claim = try XCTUnwrap(harness.channel.messages.first { $0["op"] as? String == "claim" })
        XCTAssertEqual(claim["id"] as? String, record.claimRequestID.uuidString.lowercased())
        XCTAssertEqual(claim["owner_id"] as? String, record.ownerID.uuidString.lowercased())
        XCTAssertEqual(claim["owner_token"] as? String, record.ownerTokenHex)
        XCTAssertEqual(record.state, .claimed)
        XCTAssertEqual(harness.coordinator.stage, .networks)
        XCTAssertTrue(harness.preparedBeforeClaim)
        harness.coordinator.close()
    }

    func testLostClaimReplyRecoversPendingOwnerWithoutClaimReplay() async throws {
        let harness = try SetupHarness()
        let original = harness.makeRecord(state: .pending)
        harness.vault.record = original
        harness.channel.claimed = true
        harness.coordinator.selectSavedFrame(original)
        await harness.coordinator.connect(peripheralID: UUID())
        XCTAssertFalse(harness.channel.operations.contains("claim"))
        XCTAssertEqual(harness.vault.record?.ownerToken, original.ownerToken)
        XCTAssertEqual(harness.vault.record?.claimRequestID, original.claimRequestID)
        XCTAssertEqual(harness.vault.record?.state, .claimed)
        harness.coordinator.close()
    }

    func testRevokedOwnerCanReadoptWithNewPhysicalQRAndNewCredential() async throws {
        let harness = try SetupHarness()
        let old = harness.makeRecord(state: .claimed)
        harness.vault.record = old
        harness.coordinator.acceptQRCode(harness.qr)
        await harness.coordinator.connect(peripheralID: UUID())
        let replacement = try XCTUnwrap(harness.vault.record)
        XCTAssertNotEqual(replacement.ownerID, old.ownerID)
        XCTAssertNotEqual(replacement.claimRequestID, old.claimRequestID)
        XCTAssertNotEqual(replacement.ownerToken, old.ownerToken)
        XCTAssertEqual(replacement.identity, old.identity)
        XCTAssertEqual(replacement.state, .claimed)
        XCTAssertEqual(harness.channel.operations.filter { $0 == "claim" }.count, 1)
        harness.coordinator.close()
    }

    func testUnauthorizedOwnerWithoutNewQRDoesNotReplaceCredential() async throws {
        let harness = try SetupHarness()
        let old = harness.makeRecord(state: .claimed)
        harness.vault.record = old
        harness.coordinator.selectSavedFrame(old)
        await harness.coordinator.connect(peripheralID: UUID())
        XCTAssertEqual(harness.vault.record?.ownerID, old.ownerID)
        XCTAssertEqual(harness.vault.record?.ownerToken, old.ownerToken)
        XCTAssertFalse(harness.channel.operations.contains("claim"))
        XCTAssertEqual(harness.coordinator.stage, .scanQR)
        harness.coordinator.close()
    }

    func testPendingOwnerRevokedAfterLostReplyCanReadoptWithNewQR() async throws {
        let harness = try SetupHarness()
        let old = harness.makeRecord(state: .pending)
        harness.vault.record = old
        harness.channel.rejectedOwnerIDs = [old.ownerID.uuidString.lowercased()]
        harness.coordinator.acceptQRCode(harness.qr)
        await harness.coordinator.connect(peripheralID: UUID())
        XCTAssertNotEqual(harness.vault.record?.ownerID, old.ownerID)
        XCTAssertEqual(harness.vault.record?.state, .claimed)
        XCTAssertEqual(harness.coordinator.stage, .networks)
        XCTAssertEqual(harness.channel.operations.filter { $0 == "claim" }.count, 2)
        harness.coordinator.close()
    }

    func testClaimTimeoutNeverReplacesPreparedOwner() async throws {
        let harness = try SetupHarness()
        harness.channel.loseClaimReply = true
        await harness.adopt()
        let pending = try XCTUnwrap(harness.vault.record)
        XCTAssertEqual(pending.state, .pending)
        XCTAssertEqual(harness.channel.operations.filter { $0 == "claim" }.count, 1)
        harness.channel.loseClaimReply = false
        await harness.coordinator.connect(peripheralID: UUID())
        XCTAssertEqual(harness.vault.record?.ownerID, pending.ownerID)
        XCTAssertEqual(harness.vault.record?.ownerToken, pending.ownerToken)
        XCTAssertEqual(harness.vault.record?.claimRequestID, pending.claimRequestID)
        XCTAssertEqual(harness.vault.record?.state, .claimed)
        XCTAssertEqual(harness.channel.operations.filter { $0 == "claim" }.count, 1)
        harness.coordinator.close()
    }

    func testDHCPWithoutPinnedHTTPSConfirmationNeverCompletes() async throws {
        let harness = try SetupHarness()
        let triedHTTPS = expectation(description: "Pinned HTTPS verification attempted")
        var observed = false
        harness.onConfirm = {
            if !observed { observed = true; triedHTTPS.fulfill() }
            throw URLError(.cannotConnectToHost)
        }
        await harness.adopt()
        harness.coordinator.chooseNetwork(nil)
        await harness.coordinator.applyNetwork(ssid: "Test Wi-Fi", password: "synthetic-password")
        await fulfillment(of: [triedHTTPS], timeout: 2)
        XCTAssertNotEqual(harness.coordinator.stage, .completed)
        XCTAssertNil(harness.coordinator.completedEndpoint)
        XCTAssertNotNil(harness.vault.record?.wifiTransactionID)
        XCTAssertEqual(harness.finishedCount, 0)
        harness.coordinator.suspend()
    }

    func testSuccessfulHTTPSConfirmationPersistsEndpointAndCompletes() async throws {
        let harness = try SetupHarness()
        let finished = expectation(description: "HTTPS committed")
        harness.onConfirm = { "committed" }
        harness.onFinish = { finished.fulfill() }
        await harness.adopt()
        harness.coordinator.chooseNetwork(nil)
        await harness.coordinator.applyNetwork(ssid: "Test Wi-Fi", password: "synthetic-password")
        await fulfillment(of: [finished], timeout: 2)
        XCTAssertEqual(harness.coordinator.stage, .completed)
        XCTAssertNil(harness.vault.record?.wifiTransactionID)
        XCTAssertEqual(harness.vault.record?.endpoints.first?.scheme, "https")
        XCTAssertEqual(harness.channel.operations.filter { $0 == "wifi.begin" }.count, 1)
        harness.coordinator.close()
    }

    func testTransactionSaveFailurePreventsWiFiMutation() async throws {
        let harness = try SetupHarness()
        await harness.adopt()
        harness.vault.rejectBegin = true
        harness.coordinator.chooseNetwork(nil)
        await harness.coordinator.applyNetwork(ssid: "Test Wi-Fi", password: "synthetic-password")
        XCTAssertFalse(harness.channel.operations.contains("wifi.begin"))
        XCTAssertEqual(harness.coordinator.stage, .credentials)
        harness.coordinator.close()
    }

    func testLostWiFiBeginReplyQueriesSavedIDWithoutReplayingPassword() async throws {
        let harness = try SetupHarness()
        let resumed = expectation(description: "Ambiguous begin resumes by status")
        harness.channel.loseBeginReply = true
        var observed = false
        harness.onConfirm = {
            if !observed { observed = true; resumed.fulfill() }
            throw URLError(.cannotConnectToHost)
        }
        await harness.adopt()
        harness.coordinator.chooseNetwork(nil)
        await harness.coordinator.applyNetwork(ssid: "Test Wi-Fi", password: "synthetic-password")
        await fulfillment(of: [resumed], timeout: 2)
        let begin = try XCTUnwrap(harness.channel.messages.first { $0["op"] as? String == "wifi.begin" })
        let status = try XCTUnwrap(harness.channel.messages.first { $0["op"] as? String == "wifi.status" })
        XCTAssertEqual(begin["id"] as? String, status["transaction_id"] as? String)
        XCTAssertNil(status["password"])
        XCTAssertEqual(harness.channel.operations.filter { $0 == "wifi.begin" }.count, 1)
        XCTAssertEqual(harness.finishedCount, 0)
        harness.coordinator.suspend()
    }

    func testWiFiInputRejectsOpenStyleAndOversizedCredentials() {
        XCTAssertFalse(BluetoothSetupCoordinator.validWiFiInput(ssid: "Test", password: ""))
        XCTAssertFalse(BluetoothSetupCoordinator.validWiFiInput(ssid: String(repeating: "é", count: 17), password: "password"))
        XCTAssertFalse(BluetoothSetupCoordinator.validWiFiInput(ssid: "Test", password: String(repeating: "z", count: 64)))
        XCTAssertTrue(BluetoothSetupCoordinator.validWiFiInput(ssid: "Test", password: String(repeating: "a", count: 64)))
    }

    func testInterruptedQRPreparationReturnsToScannerBeforeDiscovery() async throws {
        let harness = try SetupHarness()
        var gate: CheckedContinuation<Void, Never>?
        let preparing = Task { await harness.coordinator.displayQR { await withCheckedContinuation { gate = $0 } } }
        while gate == nil { await Task.yield() }
        harness.coordinator.suspend()
        gate?.resume()
        await preparing.value
        XCTAssertEqual(harness.coordinator.stage, .scanQR)
        XCTAssertTrue(harness.channel.operations.isEmpty)
        harness.coordinator.close()
    }
}

@MainActor
private final class SetupHarness {
    let vault = MemoryOwnershipStorage()
    let channel: SetupChannel
    private(set) var coordinator: BluetoothSetupCoordinator!
    var onConfirm: () throws -> String = { throw URLError(.cannotConnectToHost) }
    var onFinish: () -> Void = {}
    var finishedCount = 0
    var preparedBeforeClaim = false
    let identity: FrameIdentity
    var qr: String {
        "{\"v\":1,\"id\":\"\(identity.id.uuidString.lowercased())\",\"k\":\"\(FrameTrustTestFixtures.pinHex)\",\"t\":\"\(String(repeating: "b", count: 64))\"}"
    }
    init() throws {
        identity = try FrameIdentity(id: FrameTrustTestFixtures.id,
            spkiSHA256: PinnedFrameTrust.spkiSHA256(certificateDER: FrameTrustTestFixtures.certificate))
        channel = SetupChannel(trust: try PinnedFrameTrust(identity: identity,
            certificateDER: FrameTrustTestFixtures.certificate, at: FrameTrustTestFixtures.date))
        coordinator = BluetoothSetupCoordinator(channel: channel, vault: vault,
            confirmHTTPS: { [weak self] _, _, _ in try self?.onConfirm() ?? "awaiting_confirmation" },
            didFinish: { [weak self] _, _ in self?.finishedCount += 1; self?.onFinish() })
        channel.onClaim = { [weak self] in self?.preparedBeforeClaim = self?.vault.record != nil }
    }
    func adopt() async { coordinator.acceptQRCode(qr); await coordinator.connect(peripheralID: UUID()) }
    func makeRecord(state: OwnershipRecord.State) -> OwnershipRecord {
        OwnershipRecord(identity: identity, certificateDER: FrameTrustTestFixtures.certificate,
                        ownerID: UUID(), claimRequestID: UUID(), ownerToken: Data(repeating: 0xaa, count: 32),
                        endpoints: [], state: state)
    }
}

@MainActor
private final class SetupChannel: ProvisioningConnection {
    let trust: PinnedFrameTrust
    var messages: [[String: Any]] = []
    var operations: [String] { messages.compactMap { $0["op"] as? String } }
    var claimed = false
    var loseBeginReply = false
    var loseClaimReply = false
    var rejectedOwnerIDs = Set<String>()
    var transactionID: String?
    var onClaim: () -> Void = {}
    init(trust: PinnedFrameTrust) { self.trust = trust }
    func connect(peripheralID: UUID, identity: FrameIdentity) async throws -> PinnedFrameTrust { trust }
    func disconnect() {}
    func request(_ data: Data, timeout: TimeInterval) async throws -> Data {
        let message = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
        messages.append(message)
        let operation = try XCTUnwrap(message["op"] as? String)
        let id = try XCTUnwrap(message["id"] as? String)
        var result: [String: Any]
        switch operation {
        case "status" where !claimed:
            return try JSONSerialization.data(withJSONObject: ["v": 1, "id": id, "ok": false, "error": "unauthorized"])
        case "status", "claim":
            if operation == "claim" {
                if rejectedOwnerIDs.contains(message["owner_id"] as? String ?? "") {
                    return try JSONSerialization.data(withJSONObject: ["v": 1, "id": id, "ok": false, "error": "unauthorized"])
                }
                onClaim()
                claimed = true
                if loseClaimReply { throw URLError(.timedOut) }
            }
            result = ["frame_id": trust.identity.id.uuidString.lowercased(), "hostname": "inky-test.local", "https_port": 8443]
        case "wifi.scan": result = ["networks": [["ssid": "Test Wi-Fi", "security": "wpa2", "strength": 85]]]
        case "wifi.begin":
            transactionID = id
            if loseBeginReply { throw URLError(.timedOut) }
            result = ["id": id, "state": "connecting", "addresses": [], "remaining_seconds": 180]
        case "wifi.status":
            result = ["id": try XCTUnwrap(transactionID), "state": "awaiting_confirmation", "addresses": ["192.0.2.1"], "remaining_seconds": 170]
        default: throw URLError(.unsupportedURL)
        }
        return try JSONSerialization.data(withJSONObject: ["v": 1, "id": id, "ok": true, "result": result])
    }
}

@MainActor
private final class MemoryOwnershipStorage: OwnershipStorage {
    var record: OwnershipRecord?
    var rejectPrepare = false
    var rejectBegin = false
    func allRecords() throws -> [OwnershipRecord] { record.map { [$0] } ?? [] }
    func load(id: UUID) throws -> OwnershipRecord? { record?.id == id ? record : nil }
    func prepare(identity: FrameIdentity, certificateDER: Data, endpoint: URL?) throws -> OwnershipRecord {
        if rejectPrepare { throw OwnershipVaultError.unavailable }
        let value = OwnershipRecord(identity: identity, certificateDER: certificateDER,
            ownerID: UUID(), claimRequestID: UUID(), ownerToken: Data(repeating: 0xaa, count: 32), endpoints: [], state: .pending)
        record = value
        return value
    }
    func refreshCertificate(id: UUID, certificateDER: Data) throws -> OwnershipRecord { try XCTUnwrap(record) }
    func replaceUnauthorizedOwner(id: UUID, certificateDER: Data) throws -> OwnershipRecord {
        let old = try XCTUnwrap(record)
        let value = OwnershipRecord(identity: old.identity, certificateDER: certificateDER,
            ownerID: UUID(), claimRequestID: UUID(), ownerToken: Data(repeating: 0xcc, count: 32),
            endpoints: old.endpoints, state: .pending)
        record = value
        return value
    }
    func markClaimed(id: UUID, endpoint: URL?) throws -> OwnershipRecord {
        let old = try XCTUnwrap(record)
        let value = OwnershipRecord(identity: old.identity, certificateDER: old.certificateDER,
            ownerID: old.ownerID, claimRequestID: old.claimRequestID, ownerToken: old.ownerToken,
            endpoints: endpoint.map { [$0] } ?? old.endpoints, state: .claimed,
            wifiTransactionID: old.wifiTransactionID, wifiSSID: old.wifiSSID)
        record = value
        return value
    }
    func beginWiFiTransaction(id: UUID, transactionID: UUID, ssid: String) throws -> OwnershipRecord {
        if rejectBegin { throw OwnershipVaultError.unavailable }
        var value = try XCTUnwrap(record)
        value.wifiTransactionID = transactionID
        value.wifiSSID = ssid
        record = value
        return value
    }
    func finishWiFiTransaction(id: UUID, transactionID: UUID) throws -> OwnershipRecord {
        var value = try XCTUnwrap(record)
        value.wifiTransactionID = nil
        value.wifiSSID = nil
        record = value
        return value
    }
}
