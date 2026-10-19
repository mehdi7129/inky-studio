import XCTest
@testable import InkyStudio

/// Coordinator state/protocol tests with synthetic peers. No physical BLE, TLS handshake or Keychain ACL is qualified here.
@MainActor
final class BluetoothFactorySetupCoordinatorTests: XCTestCase {
    func testBackgroundBeforeBootstrapOwnershipRequiresNewScanWithoutConnectingOnResume() async throws {
        let h = try FactoryCoordinatorHarness()
        h.coordinator.acceptBootstrapCode(h.code)
        XCTAssertEqual(h.coordinator.stage, .nearby)
        h.coordinator.suspend()
        XCTAssertEqual(h.coordinator.stage, .scanQR)
        XCTAssertNotNil(h.coordinator.errorMessage)
        XCTAssertFalse(h.coordinator.isFactory, "The QR secret must still be purged")
        await h.coordinator.resume()
        XCTAssertEqual(h.coordinator.stage, .scanQR)
        XCTAssertEqual(h.peer.bootstrapConnections, 0)
        XCTAssertEqual(h.peer.normalConnections, 0)
        XCTAssertTrue(h.peer.operations.isEmpty)
        XCTAssertNil(h.vault.record)

        let rescanned = try FrameBootstrapCode(identity: h.identity, adoptionToken: Data(repeating: 0x2a, count: 32))
        h.coordinator.acceptBootstrapCode(rescanned)
        XCTAssertEqual(h.coordinator.stage, .nearby)
        XCTAssertTrue(h.coordinator.isFactory)
        XCTAssertEqual(h.coordinator.discoveryProfile, .bootstrap)
        XCTAssertNil(h.coordinator.errorMessage)
        XCTAssertEqual(h.peer.bootstrapConnections, 0, "A new scan still requires an explicit connection")
        XCTAssertEqual(h.peer.normalConnections, 0)
        XCTAssertTrue(h.peer.operations.isEmpty)
        h.coordinator.close()
    }

    func testBackgroundWithSavedBootstrapOwnerPreservesOwnershipAndResume() async throws {
        let h = try FactoryCoordinatorHarness()
        h.installClaimedBootstrap()
        let saved = try XCTUnwrap(h.vault.record)
        h.coordinator.acceptBootstrapCode(h.code)
        h.coordinator.suspend()
        XCTAssertEqual(h.coordinator.stage, .suspended)
        XCTAssertTrue(h.coordinator.isFactory)
        XCTAssertEqual(h.coordinator.owner, saved)
        await h.coordinator.resume()
        XCTAssertEqual(h.coordinator.stage, .nearby)
        XCTAssertEqual(h.coordinator.discoveryProfile, .bootstrap)
        XCTAssertEqual(h.coordinator.owner, saved)
        XCTAssertEqual(h.vault.record, saved)
        XCTAssertEqual(h.peer.bootstrapConnections, 0)
        XCTAssertEqual(h.peer.normalConnections, 0)
        XCTAssertTrue(h.peer.operations.isEmpty)
        h.coordinator.close()
    }

    func testFactoryAuthorizationFailureSendsNothing() async throws {
        let h = try FactoryCoordinatorHarness(authorize: { false })
        h.coordinator.acceptBootstrapCode(h.code)
        await h.coordinator.connect(peripheralID: UUID())
        XCTAssertEqual(h.peer.bootstrapConnections, 0)
        XCTAssertTrue(h.peer.operations.isEmpty)
        XCTAssertNil(h.vault.record)
    }

    func testBootstrapClaimHasDurableOwnerBeforeMutationAndCountryHasNoDefault() async throws {
        let h = try FactoryCoordinatorHarness()
        await h.adopt()
        XCTAssertTrue(h.peer.ownerWasSavedBeforeClaim)
        XCTAssertEqual(h.vault.record?.factoryProfile, .bootstrap)
        XCTAssertEqual(h.vault.record?.state, .claimed)
        XCTAssertEqual(h.coordinator.selectedCountry, "")
        XCTAssertEqual(h.coordinator.stage, .factoryCountry)
        XCTAssertFalse(h.peer.operations.contains("system_setup.challenge"))
        await h.coordinator.beginFactorySystemSetup()
        XCTAssertFalse(h.peer.operations.contains("system_setup.apply"))
        h.coordinator.close()
    }

    func testExactCountryUTCAndCheckpointPrecedeChallengeAndApply() async throws {
        let h = try FactoryCoordinatorHarness()
        await h.adopt()
        h.coordinator.chooseCountry("FR")
        let ready = expectation(description: "Readonly status reaches explicit continuation")
        h.peer.onSetupStatus = { if h.peer.state == .setupReady { ready.fulfill(); h.peer.onSetupStatus = nil } }
        await h.coordinator.beginFactorySystemSetup()
        await fulfillment(of: [ready], timeout: 2)
        for _ in 0..<5 { await Task.yield() }
        XCTAssertTrue(h.peer.checkpointBeforeChallenge)
        XCTAssertTrue(h.peer.intentBeforeApply)
        XCTAssertEqual(h.checkpoints.value?.applyIntent?.country, "FR")
        XCTAssertEqual(h.checkpoints.value?.applyIntent?.utcSeconds, 1_792_000_000)
        XCTAssertEqual(h.clockSamples, 1)
        XCTAssertEqual(h.peer.operations.filter { $0 == "system_setup.apply" }.count, 1)
        XCTAssertEqual(h.coordinator.stage, .factoryContinue)
        XCTAssertFalse(h.peer.operations.contains("system_setup.continue"), "A next_step never admits a mutation")
        h.coordinator.close()
    }

    func testFailedCheckpointOrMarkerPreventsChallengeAndApply() async throws {
        for markerFailure in [false, true] {
            let h = try FactoryCoordinatorHarness()
            await h.adopt()
            h.coordinator.chooseCountry("US")
            h.checkpoints.rejectSave = !markerFailure
            h.vault.rejectMarker = markerFailure
            await h.coordinator.beginFactorySystemSetup()
            XCTAssertFalse(h.peer.operations.contains("system_setup.challenge"))
            XCTAssertFalse(h.peer.operations.contains("system_setup.apply"))
            XCTAssertEqual(h.coordinator.stage, .factoryRecovery)
            h.coordinator.close()
        }
    }

    func testColdResumeDiscoversOperationWithoutCheckpointAndNeverReplaysApply() async throws {
        let h = try FactoryCoordinatorHarness()
        h.installClaimedBootstrap()
        let historical = UUID()
        h.peer.latestOperation = historical
        h.peer.state = .uncertain
        h.coordinator.selectSavedFrame(try XCTUnwrap(h.vault.record))
        await h.coordinator.connect(peripheralID: UUID())
        XCTAssertEqual(h.coordinator.factoryStatus?.operationID, historical)
        XCTAssertEqual(h.coordinator.stage, .factoryRecovery)
        XCTAssertFalse(h.peer.operations.contains("bootstrap.claim"))
        XCTAssertFalse(h.peer.operations.contains("system_setup.apply"))
        XCTAssertNil(h.checkpoints.value)
        h.coordinator.close()
    }

    func testExplicitSupersedeUsesNewOperationAndFreshCountryUTC() async throws {
        let h = try FactoryCoordinatorHarness()
        h.installClaimedBootstrap()
        let historical = UUID()
        h.peer.latestOperation = historical
        h.peer.state = .uncertain
        h.coordinator.selectSavedFrame(try XCTUnwrap(h.vault.record))
        await h.coordinator.connect(peripheralID: UUID())
        h.coordinator.chooseCountry("GB")
        await h.coordinator.beginFactorySystemSetup()
        XCTAssertNotEqual(h.checkpoints.value?.operationID, historical)
        XCTAssertEqual(h.checkpoints.value?.supersedesOperationID, historical)
        XCTAssertEqual(h.checkpoints.value?.country, "GB")
        XCTAssertEqual(h.peer.operations.filter { $0 == "system_setup.apply" }.count, 1)
        h.coordinator.close()
    }

    func testBackgroundDuringApplyIgnoresLateACKAndResumeUsesStatusOnly() async throws {
        let h = try FactoryCoordinatorHarness()
        await h.adopt()
        h.coordinator.chooseCountry("FR")
        let gate = FactoryPeerGate()
        h.peer.applyGate = gate
        let apply = Task { await h.coordinator.beginFactorySystemSetup() }
        await fulfillment(of: [gate.started], timeout: 2)
        h.coordinator.suspend()
        h.peer.state = .uncertain
        gate.release(); await apply.value
        XCTAssertEqual(h.coordinator.stage, .suspended)
        let before = h.peer.operations.filter { $0 == "system_setup.apply" }.count
        await h.coordinator.resume()
        XCTAssertEqual(h.coordinator.stage, .factoryRecovery)
        XCTAssertEqual(h.peer.operations.filter { $0 == "system_setup.apply" }.count, before)
        XCTAssertEqual(h.peer.operations.filter { $0 == "bootstrap.claim" }.count, 1)
        h.coordinator.close()
    }

    func testLostPublicationReplyResumesNormalSamePinWithoutRescanOrClaim() async throws {
        let h = try FactoryCoordinatorHarness()
        h.installClaimedBootstrap()
        h.peer.latestOperation = UUID()
        h.peer.state = .setupReady
        h.coordinator.selectSavedFrame(try XCTUnwrap(h.vault.record))
        await h.coordinator.connect(peripheralID: UUID())
        XCTAssertEqual(h.coordinator.stage, .factoryContinue)
        h.peer.loseContinueReply = true
        await h.coordinator.continueFactorySetup()
        XCTAssertEqual(h.vault.record?.factoryExpectedNormal, true)
        XCTAssertEqual(h.coordinator.stage, .suspended)
        h.peer.loseContinueReply = false
        await h.coordinator.resume()
        for _ in 0..<5 { await Task.yield() }
        XCTAssertEqual(h.peer.normalConnections, 1)
        XCTAssertEqual(h.vault.record?.factoryProfile, .normalV1)
        XCTAssertEqual(h.vault.record?.identity, h.identity)
        XCTAssertFalse(h.peer.operations.contains("bootstrap.claim"))
        XCTAssertTrue(h.peer.operations.contains("wifi.scan"))
        h.coordinator.close()
    }

    func testNormalSecurityFailureNeverFallsBackToBootstrap() async throws {
        let h = try FactoryCoordinatorHarness()
        h.installClaimedBootstrap(expectedNormal: true)
        h.peer.normalFailure = FrameIdentityError.pinMismatch
        h.coordinator.selectSavedFrame(try XCTUnwrap(h.vault.record))
        await h.coordinator.connect(peripheralID: UUID())
        XCTAssertEqual(h.peer.normalConnections, 1)
        XCTAssertEqual(h.peer.bootstrapConnections, 0)
        XCTAssertEqual(h.coordinator.stage, .suspended)
        XCTAssertEqual(h.vault.record?.factoryProfile, .bootstrap)
    }

    func testMissingNormalServiceBeforeVerifiedHandoffCanResumeBootstrapReadonly() async throws {
        let h = try FactoryCoordinatorHarness()
        h.installClaimedBootstrap(expectedNormal: true)
        h.peer.normalFailure = BluetoothTransportError.unsupportedFrame
        h.peer.latestOperation = UUID()
        h.peer.state = .uncertain
        h.coordinator.selectSavedFrame(try XCTUnwrap(h.vault.record))
        await h.coordinator.connect(peripheralID: UUID())
        XCTAssertEqual(h.peer.bootstrapConnections, 1)
        XCTAssertEqual(h.coordinator.stage, .factoryRecovery)
        XCTAssertFalse(h.peer.operations.contains("bootstrap.claim"))
        XCTAssertFalse(h.peer.operations.contains("system_setup.apply"))
        h.coordinator.close()
    }

    func testNullOriginStillAllowsBLEWiFiButNeverHTTPSConfirmation() async throws {
        let h = try FactoryCoordinatorHarness()
        h.installClaimedNormal()
        h.peer.latestOperation = UUID()
        h.peer.state = .tlsReady
        h.peer.hasOrigin = false
        h.coordinator.selectSavedFrame(try XCTUnwrap(h.vault.record))
        await h.coordinator.connect(peripheralID: UUID())
        for _ in 0..<5 { await Task.yield() }
        XCTAssertTrue(h.peer.operations.contains("wifi.scan"))
        h.coordinator.chooseNetwork(nil)
        let observed = expectation(description: "Origin is queried after Wi-Fi status")
        h.peer.onSetupStatus = { observed.fulfill(); h.peer.onSetupStatus = nil }
        await h.coordinator.applyNetwork(ssid: "Synthetic Wi-Fi", password: "synthetic-password")
        await fulfillment(of: [observed], timeout: 2)
        XCTAssertTrue(h.peer.operations.contains("wifi.begin"))
        XCTAssertEqual(h.confirmations, 0)
        XCTAssertNotEqual(h.coordinator.stage, .completed)
        h.coordinator.suspend()
    }

    func testWiFiUsesAttestedOriginAndPhotoFailureKeepsResumableState() async throws {
        let h = try FactoryCoordinatorHarness()
        h.installClaimedNormal()
        h.peer.latestOperation = UUID()
        h.peer.state = .tlsReady
        h.coordinator.selectSavedFrame(try XCTUnwrap(h.vault.record))
        await h.coordinator.connect(peripheralID: UUID())
        for _ in 0..<5 { await Task.yield() }
        h.coordinator.chooseNetwork(nil)
        let confirmed = expectation(description: "Only attested origin reaches HTTPS confirm")
        h.onConfirm = { endpoint in
            XCTAssertEqual(endpoint, h.peer.origin)
            confirmed.fulfill()
        }
        await h.coordinator.applyNetwork(ssid: "Synthetic Wi-Fi", password: "synthetic-password")
        await fulfillment(of: [confirmed], timeout: 2)
        for _ in 0..<8 { await Task.yield() }
        XCTAssertEqual(h.coordinator.stage, .factoryContinue)
        XCTAssertEqual(h.photoFinishes, 0)
        h.photoSuccess = false
        await h.coordinator.continueFactorySetup()
        XCTAssertEqual(h.coordinator.stage, .factoryPhotoAccess)
        XCTAssertEqual(h.photoFinishes, 1)
        XCTAssertNotEqual(h.vault.record?.factoryPhotoAccessComplete, true)
        h.photoSuccess = true
        await h.coordinator.finishFactoryPhotoAccess()
        XCTAssertEqual(h.coordinator.stage, .completed)
        XCTAssertEqual(h.vault.record?.factoryPhotoAccessComplete, true)
        h.coordinator.close()
    }
}

@MainActor
private final class FactoryCoordinatorHarness {
    let vault = FactoryCoordinatorOwnership()
    let checkpoints = FactoryCoordinatorCheckpoints()
    let peer: FactoryCoordinatorPeer
    let identity: FrameIdentity
    let code: FrameBootstrapCode
    let coordinator: BluetoothSetupCoordinator
    var confirmations = 0
    var onConfirm: (URL) -> Void = { _ in }
    var photoFinishes = 0
    var photoSuccess = false
    var clockSamples = 0

    init(authorize: @escaping () async -> Bool = { true }) throws {
        let identity = try FrameIdentity(id: FrameTrustTestFixtures.id,
            spkiSHA256: PinnedFrameTrust.spkiSHA256(certificateDER: FrameTrustTestFixtures.certificate))
        self.identity = identity
        code = try FrameBootstrapCode(identity: identity, adoptionToken: Data(repeating: 0x19, count: 32))
        peer = try FactoryCoordinatorPeer(identity: identity, vault: vault, checkpoints: checkpoints)
        var onConfirm: ((URL) -> Void)?
        var onPhoto: (() -> Bool)?
        var onClock: (() -> UInt64)?
        let peer = self.peer
        coordinator = BluetoothSetupCoordinator(channel: peer, vault: vault,
            confirmHTTPS: { endpoint, _, _ in onConfirm?(endpoint); peer.wifiCommitted = true; return "committed" },
            authorizeFactory: authorize, factoryCheckpoints: checkpoints,
            factoryUTCNow: { onClock?() ?? 1_792_000_000 },
            didFinishFactory: { _, _, _ in onPhoto?() ?? false }, didFinish: { _, _ in XCTFail("Factory setup must not finish through the legacy callback") })
        onConfirm = { [weak self] endpoint in self?.confirmations += 1; self?.onConfirm(endpoint) }
        onPhoto = { [weak self] in self?.photoFinishes += 1; return self?.photoSuccess ?? false }
        onClock = { [weak self] in self?.clockSamples += 1; return 1_792_000_000 }
    }
    func adopt() async { coordinator.acceptBootstrapCode(code); await coordinator.connect(peripheralID: UUID()) }
    func installClaimedBootstrap(expectedNormal: Bool = false) {
        vault.record = OwnershipRecord(identity: identity, certificateDER: FrameTrustTestFixtures.certificate,
            ownerID: UUID(), claimRequestID: UUID(), ownerToken: Data(repeating: 0x42, count: 32), endpoints: [], state: .claimed,
            factoryProfile: .bootstrap, factoryExpectedNormal: expectedNormal)
        peer.claimed = true
    }
    func installClaimedNormal() {
        installClaimedBootstrap()
        vault.record?.factoryProfile = .normalV1
        peer.normalPublished = true
    }
}

@MainActor
private final class FactoryCoordinatorPeer: ProvisioningConnection {
    let identity: FrameIdentity
    let normalTrust: PinnedFrameTrust
    let bootstrapTrust: BootstrapFrameTrust
    let vault: FactoryCoordinatorOwnership
    let checkpoints: FactoryCoordinatorCheckpoints
    var claimed = false
    var latestOperation: UUID?
    var state: FactorySetupState = .setupReady
    var normalPublished = false
    var hasOrigin = true
    var normalFailure: Error?
    var normalConnections = 0
    var bootstrapConnections = 0
    var ownerWasSavedBeforeClaim = false
    var checkpointBeforeChallenge = false
    var intentBeforeApply = false
    var loseContinueReply = false
    var wifiCommitted = false
    var transactionID: UUID?
    var applyGate: FactoryPeerGate?
    var onSetupStatus: (() -> Void)?
    var operations: [String] = []
    var origin: URL { URL(string: "https://inky-11111111111111111111111111111111.local:8443")! }
    init(identity: FrameIdentity, vault: FactoryCoordinatorOwnership, checkpoints: FactoryCoordinatorCheckpoints) throws {
        self.identity = identity; self.vault = vault; self.checkpoints = checkpoints
        normalTrust = try PinnedFrameTrust(identity: identity, certificateDER: FrameTrustTestFixtures.certificate, at: FrameTrustTestFixtures.date)
        bootstrapTrust = try BootstrapFrameTrust(identity: identity, certificateDER: FrameTrustTestFixtures.certificate)
    }
    func connect(peripheralID: UUID, identity: FrameIdentity) async throws -> PinnedFrameTrust {
        normalConnections += 1
        if let normalFailure { throw normalFailure }
        guard normalPublished else { throw BluetoothTransportError.unsupportedFrame }
        return normalTrust
    }
    func connectBootstrap(peripheralID: UUID, identity: FrameIdentity) async throws -> BootstrapFrameTrust {
        bootstrapConnections += 1; return bootstrapTrust
    }
    func disconnect() {}
    func request(_ data: Data, timeout: TimeInterval) async throws -> Data { try await reply(data) }
    func requestBootstrap(_ data: Data, timeout: TimeInterval) async throws -> Data { try await reply(data) }
    private func reply(_ data: Data) async throws -> Data {
        let message = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
        let operation = try XCTUnwrap(message["op"] as? String)
        let requestID = try XCTUnwrap(message["id"] as? String)
        let owner = try XCTUnwrap(vault.record)
        operations.append(operation)
        let binding: [String: Any] = ["frame_id": identity.id.uuidString.lowercased(), "owner_id": owner.ownerID.uuidString.lowercased(),
                                     "claim_request_id": owner.claimRequestID.uuidString.lowercased()]
        var result: [String: Any]
        switch operation {
        case "bootstrap.status" where !claimed:
            return try JSONSerialization.data(withJSONObject: ["v": 1, "id": requestID, "ok": false, "error": "unauthorized"])
        case "bootstrap.claim", "bootstrap.status":
            if operation == "bootstrap.claim" { ownerWasSavedBeforeClaim = vault.record != nil; claimed = true }
            result = binding.merging(["factory_state": "adopted", "next_step": "system_setup"]) { _, new in new }
        case "system_setup.negotiate":
            result = ["selected_version": 2, "latest_operation_id": latestOperation.map { $0.uuidString.lowercased() as Any } ?? NSNull(),
                      "capabilities": FactorySetupWire.capabilities]
        case "system_setup.challenge":
            let id = try XCTUnwrap((message["op_id"] as? String).flatMap(UUID.init(uuidString:)))
            checkpointBeforeChallenge = checkpoints.value?.operationID == id && vault.record?.factorySetupOperationID == id
            latestOperation = id
            state = .challengeIssued
            result = ["op_id": id.uuidString.lowercased(), "challenge_id": UUID().uuidString.lowercased(), "nonce": String(repeating: "a", count: 64),
                      "boot_id": UUID().uuidString.lowercased(), "issued_boottime_ns": 10, "expires_boottime_ns": 30_000_000_010 as UInt64]
        case "system_setup.apply":
            let id = try XCTUnwrap(latestOperation)
            intentBeforeApply = checkpoints.value?.applyIntent?.requestID.uuidString.lowercased() == requestID &&
                checkpoints.value?.applyIntent?.country == message["country"] as? String &&
                checkpoints.value?.applyIntent?.utcSeconds == (message["utc_seconds"] as? NSNumber)?.uint64Value
            state = .setupReady
            if let applyGate { await applyGate.wait() }
            result = binding.merging(["op_id": id.uuidString.lowercased(), "state": "applying", "submission": "registered",
                                     "durability": "not_confirmed", "next_step": "status"]) { _, new in new }
        case "system_setup.status":
            result = status(binding: binding)
            onSetupStatus?()
        case "system_setup.continue":
            let action: String
            if !normalPublished { normalPublished = true; state = .tlsReady; action = "publication_finalized" }
            else if wifiCommitted { state = .complete; action = "completion_finalized" }
            else { state = .wifiPending; action = "wifi_pending" }
            if loseContinueReply { throw SecureBluetoothError.notConnected }
            result = status(binding: binding); result["action"] = action
        case "wifi.scan": result = ["networks": [["ssid": "Synthetic Wi-Fi", "security": "wpa2", "strength": 80]]]
        case "wifi.begin":
            transactionID = UUID(uuidString: requestID)
            result = wifiStatus()
        case "wifi.status": result = wifiStatus()
        default: throw FactorySetupError.invalidMessage
        }
        return try JSONSerialization.data(withJSONObject: ["v": operation.hasPrefix("bootstrap.") || operation.hasPrefix("wifi.") ? 1 : 2,
            "id": requestID, "ok": true, "result": result])
    }
    private func status(binding: [String: Any]) -> [String: Any] {
        let next: String
        switch state {
        case .setupReady: next = "continue"
        case .challengeIssued: next = "apply"
        case .applying: next = "status"
        case .uncertain, .refused: next = "recover_explicit"
        case .tlsReady, .wifiPending: next = hasOrigin ? "wifi" : "wait_origin"
        case .complete: next = hasOrigin ? "photo_enroll" : "wait_origin"
        }
        let normal: Any = normalPublished ? ["frame_id": identity.id.uuidString.lowercased(),
            "spki_sha256": FactorySetupValidation.hex(identity.spkiSHA256), "publication_op_id": latestOperation!.uuidString.lowercased()] : NSNull()
        return binding.merging(["op_id": latestOperation!.uuidString.lowercased(), "state": state.rawValue,
            "normal_identity": normal, "https_origin": hasOrigin && normalPublished ? origin.absoluteString as Any : NSNull(),
            "completion_id": state == .complete ? UUID().uuidString.lowercased() as Any : NSNull(), "next_step": next]) { _, new in new }
    }
    private func wifiStatus() -> [String: Any] {
        ["id": transactionID!.uuidString.lowercased(), "state": "awaiting_confirmation", "addresses": ["192.0.2.99"], "remaining_seconds": 170]
    }
}

@MainActor
private final class FactoryCoordinatorCheckpoints: FactorySetupCheckpointStorage {
    var value: FactorySetupCheckpoint?
    var rejectSave = false
    func load(binding: FactorySetupBinding) throws -> FactorySetupCheckpoint? { value }
    func save(_ checkpoint: FactorySetupCheckpoint) throws {
        guard !rejectSave else { throw FactorySetupError.storageUnavailable }; value = checkpoint
    }
    func remove(binding: FactorySetupBinding) throws { value = nil }
}

@MainActor
private final class FactoryCoordinatorOwnership: OwnershipStorage {
    var record: OwnershipRecord?
    var rejectMarker = false
    func allRecords() throws -> [OwnershipRecord] { record.map { [$0] } ?? [] }
    func load(id: UUID) throws -> OwnershipRecord? { record?.id == id ? record : nil }
    func prepare(identity: FrameIdentity, certificateDER: Data, endpoint: URL?) throws -> OwnershipRecord { throw OwnershipVaultError.invalidRecord }
    func prepareBootstrap(identity: FrameIdentity, certificateDER: Data) throws -> OwnershipRecord {
        record = OwnershipRecord(identity: identity, certificateDER: certificateDER, ownerID: UUID(), claimRequestID: UUID(),
            ownerToken: Data(repeating: 0x42, count: 32), endpoints: [], state: .pending, factoryProfile: .bootstrap)
        return record!
    }
    func refreshBootstrapCertificate(id: UUID, certificateDER: Data) throws -> OwnershipRecord { record!.certificateDER = certificateDER; return record! }
    func promoteFactoryNormal(id: UUID, certificateDER: Data) throws -> OwnershipRecord {
        record!.certificateDER = certificateDER; record!.factoryProfile = .normalV1; record!.factoryExpectedNormal = nil; return record!
    }
    func refreshCertificate(id: UUID, certificateDER: Data) throws -> OwnershipRecord { record!.certificateDER = certificateDER; return record! }
    func replaceUnauthorizedOwner(id: UUID, certificateDER: Data) throws -> OwnershipRecord { throw OwnershipVaultError.invalidRecord }
    func markClaimed(id: UUID, endpoint: URL?) throws -> OwnershipRecord { record!.state = .claimed; if let endpoint { record!.endpoints = [endpoint] }; return record! }
    func setFactoryOperation(id: UUID, operationID: UUID) throws -> OwnershipRecord {
        guard !rejectMarker else { throw OwnershipVaultError.unavailable }; record!.factorySetupOperationID = operationID; return record!
    }
    func expectFactoryNormal(id: UUID) throws -> OwnershipRecord { record!.factoryExpectedNormal = true; return record! }
    func markFactoryPhotoCompleted(id: UUID) throws -> OwnershipRecord { record!.factoryPhotoAccessComplete = true; return record! }
    func beginWiFiTransaction(id: UUID, transactionID: UUID, ssid: String) throws -> OwnershipRecord {
        record!.wifiTransactionID = transactionID; record!.wifiSSID = ssid; return record!
    }
    func finishWiFiTransaction(id: UUID, transactionID: UUID) throws -> OwnershipRecord {
        record!.wifiTransactionID = nil; record!.wifiSSID = nil; return record!
    }
}

@MainActor
private final class FactoryPeerGate {
    let started = XCTestExpectation(description: "Factory apply admitted")
    private var continuation: CheckedContinuation<Void, Never>?
    func wait() async { await withCheckedContinuation { continuation = $0; started.fulfill() } }
    func release() { continuation?.resume(); continuation = nil }
}
