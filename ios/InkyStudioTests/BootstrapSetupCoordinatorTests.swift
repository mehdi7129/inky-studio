import XCTest
@testable import InkyStudio

@MainActor final class BootstrapSetupCoordinatorTests: XCTestCase {
    private func environment() throws -> (BootstrapTestPeer, BootstrapMemoryStorage) {
        let identity = try FrameIdentity(id: FrameTrustTestFixtures.id,
            spkiSHA256: XCTUnwrap(Data.bootstrapHexBytes(FrameTrustTestFixtures.pinHex)))
        return (BootstrapTestPeer(trust: try BootstrapFrameTrust(identity: identity,
            certificateDER: FrameTrustTestFixtures.certificate)), BootstrapMemoryStorage())
    }
    private func qr(_ peer: BootstrapTestPeer, token: String = String(repeating: "a", count: 64)) -> String {
        "{\"v\":2,\"p\":\"bootstrap\",\"id\":\"\(peer.trust.identity.id.uuidString.lowercased())\",\"k\":\"\(peer.trust.identity.spkiSHA256.bootstrapHex)\",\"t\":\"\(token)\"}"
    }
    func testKeychainPreparationFailureEmitsZeroClaimAndZeroStatus() async throws {
        let (peer, storage) = try environment(); storage.rejectPrepare = true
        let coordinator = BootstrapSetupCoordinator(channel: peer, vault: storage)
        coordinator.acceptQRCode(qr(peer)); await coordinator.connect(peripheralID: UUID())
        XCTAssertTrue(peer.messages.isEmpty)
        XCTAssertNil(storage.record)
        XCTAssertEqual(coordinator.stage, .recoveryRequired)
    }
    func testDurableClaimStopsAtPreparationAndStatusIDsAreIndependent() async throws {
        let (peer, storage) = try environment()
        peer.onClaim = { XCTAssertNotNil(storage.record, "Ownership must precede mutation") }
        let coordinator = BootstrapSetupCoordinator(channel: peer, vault: storage)
        coordinator.acceptQRCode(qr(peer)); await coordinator.connect(peripheralID: UUID())
        XCTAssertEqual(coordinator.stage, .adoptedAwaitingPreparation)
        let saved = try XCTUnwrap(storage.record)
        XCTAssertEqual(saved.state, .adoptedAwaitingPreparation)
        XCTAssertEqual(peer.messages.map(\.operation), [.status, .claim])
        XCTAssertNotEqual(peer.messages[0].id, saved.claimRequestID)
        XCTAssertEqual(peer.messages[0].claimRequestID, saved.claimRequestID)
        XCTAssertEqual(peer.messages[1].id, saved.claimRequestID)
        XCTAssertFalse(String(decoding: try JSONEncoder().encode(saved), as: UTF8.self).contains("claimToken"))
    }
    func testLostReplyAndRelaunchRecoverSameWinningIntentionWithoutClaimRetry() async throws {
        let (peer, storage) = try environment(); peer.loseClaimReply = true
        var coordinator = BootstrapSetupCoordinator(channel: peer, vault: storage)
        coordinator.acceptQRCode(qr(peer)); await coordinator.connect(peripheralID: UUID())
        XCTAssertEqual(coordinator.stage, .uncertain)
        let pending = try XCTUnwrap(storage.record)
        XCTAssertEqual(pending.state, .pending)
        coordinator.close()
        peer.loseClaimReply = false
        coordinator = BootstrapSetupCoordinator(channel: peer, vault: storage)
        coordinator.selectSavedFrame(pending); await coordinator.connect(peripheralID: UUID())
        XCTAssertEqual(coordinator.stage, .adoptedAwaitingPreparation)
        XCTAssertEqual(storage.record?.ownerID, pending.ownerID)
        XCTAssertEqual(storage.record?.ownerToken, pending.ownerToken)
        XCTAssertEqual(storage.record?.claimRequestID, pending.claimRequestID)
        XCTAssertEqual(peer.messages.filter { $0.operation == .claim }.count, 1)
        XCTAssertEqual(peer.messages.last?.claimRequestID, pending.claimRequestID)
    }
    func testCrashBeforeLocalAcknowledgementRecoversWithoutReplacingOwner() async throws {
        let (peer, storage) = try environment(); storage.rejectMark = true
        let first = BootstrapSetupCoordinator(channel: peer, vault: storage)
        first.acceptQRCode(qr(peer)); await first.connect(peripheralID: UUID())
        let pending = try XCTUnwrap(storage.record)
        XCTAssertEqual(pending.state, .pending)
        storage.rejectMark = false
        let relaunched = BootstrapSetupCoordinator(channel: peer, vault: storage)
        relaunched.selectSavedFrame(pending); await relaunched.connect(peripheralID: UUID())
        XCTAssertEqual(relaunched.stage, .adoptedAwaitingPreparation)
        XCTAssertEqual(storage.prepareCount, 1)
        XCTAssertEqual(peer.messages.filter { $0.operation == .claim }.count, 1)
    }
    func testTwoPhonesPreserveOneWinnerAndLosingCredentialWithoutReminting() async throws {
        let (peer, winnerStorage) = try environment()
        let winner = BootstrapSetupCoordinator(channel: peer, vault: winnerStorage)
        winner.acceptQRCode(qr(peer)); await winner.connect(peripheralID: UUID())
        let losingStorage = BootstrapMemoryStorage()
        let loser = BootstrapSetupCoordinator(channel: peer, vault: losingStorage)
        loser.acceptQRCode(qr(peer)); await loser.connect(peripheralID: UUID())
        XCTAssertEqual(winner.stage, .adoptedAwaitingPreparation)
        XCTAssertEqual(loser.stage, .recoveryRequired)
        let loserRecord = try XCTUnwrap(losingStorage.record)
        XCTAssertNotEqual(loserRecord.ownerID, winnerStorage.record?.ownerID)
        XCTAssertEqual(loserRecord.state, .pending)
        await loser.resume()
        XCTAssertEqual(losingStorage.prepareCount, 1)
        XCTAssertEqual(losingStorage.record?.ownerID, loserRecord.ownerID)
        XCTAssertEqual(losingStorage.record?.claimRequestID, loserRecord.claimRequestID)
        XCTAssertEqual(peer.winningOwner, winnerStorage.record?.ownerID)
    }
    func testUnauthenticatedRecoveryDoesNotClaimAndAdoptedRescanDoesNotRemint() async throws {
        let (peer, storage) = try environment()
        let initial = BootstrapSetupCoordinator(channel: peer, vault: storage)
        initial.acceptQRCode(qr(peer)); await initial.connect(peripheralID: UUID())
        let adopted = try XCTUnwrap(storage.record)
        peer.revoked = true
        let resumed = BootstrapSetupCoordinator(channel: peer, vault: storage)
        resumed.selectSavedFrame(adopted); await resumed.connect(peripheralID: UUID())
        XCTAssertEqual(resumed.stage, .recoveryRequired)
        resumed.acceptQRCode(qr(peer)); await resumed.connect(peripheralID: UUID())
        XCTAssertEqual(storage.record?.ownerID, adopted.ownerID)
        XCTAssertEqual(storage.record?.claimRequestID, adopted.claimRequestID)
        XCTAssertEqual(peer.messages.filter { $0.operation == .claim }.count, 1)
    }
    func testPendingUnauthenticatedRecoveryWithoutPhysicalQRDoesNotClaim() async throws {
        let (peer, storage) = try environment()
        let pending = try storage.prepare(identity: peer.trust.identity, certificateDER: peer.trust.certificateDER)
        let coordinator = BootstrapSetupCoordinator(channel: peer, vault: storage)
        coordinator.selectSavedFrame(pending); await coordinator.connect(peripheralID: UUID())
        XCTAssertEqual(coordinator.stage, .recoveryRequired)
        XCTAssertEqual(peer.messages.map(\.operation), [.status])
        XCTAssertEqual(storage.record, pending)
    }
    func testSuspendAfterRemoteCommitPreservesPendingThenResumesByStatus() async throws {
        let (peer, storage) = try environment()
        let coordinator = BootstrapSetupCoordinator(channel: peer, vault: storage)
        peer.onClaim = { coordinator.suspend() }
        coordinator.acceptQRCode(qr(peer)); await coordinator.connect(peripheralID: UUID())
        XCTAssertEqual(coordinator.stage, .suspended)
        let pending = try XCTUnwrap(storage.record)
        XCTAssertEqual(pending.state, .pending)
        peer.onClaim = {}; await coordinator.resume()
        XCTAssertEqual(coordinator.stage, .adoptedAwaitingPreparation)
        XCTAssertEqual(peer.messages.filter { $0.operation == .claim }.count, 1)
    }
    func testUncorrelatedUnauthorizedResponseDoesNotTriggerClaim() async throws {
        let (peer, storage) = try environment(); peer.omitCorrelation = true
        let coordinator = BootstrapSetupCoordinator(channel: peer, vault: storage)
        coordinator.acceptQRCode(qr(peer)); await coordinator.connect(peripheralID: UUID())
        XCTAssertEqual(coordinator.stage, .uncertain)
        XCTAssertEqual(peer.messages.map(\.operation), [.status])
        XCTAssertNotNil(storage.record)
    }
    func testWrongFrameOrOwnerOrClaimCannotAcknowledgeAdoption() async throws {
        for wrong in ["frame_id", "owner_id", "claim_request_id"] {
            let (peer, storage) = try environment(); peer.corruptSuccessField = wrong
            let coordinator = BootstrapSetupCoordinator(channel: peer, vault: storage)
            coordinator.acceptQRCode(qr(peer)); await coordinator.connect(peripheralID: UUID())
            XCTAssertEqual(coordinator.stage, .uncertain, wrong)
            XCTAssertEqual(storage.record?.state, .pending, wrong)
        }
    }
    func testLostReplyThenKeychainLossNeverPreparesAnotherIntentionEvenAfterRescan() async throws {
        for rescannedToken in [nil, String(repeating: "a", count: 64), String(repeating: "c", count: 64)] as [String?] {
            let (peer, storage) = try environment(); peer.loseClaimReply = true
            let coordinator = BootstrapSetupCoordinator(channel: peer, vault: storage)
            coordinator.acceptQRCode(qr(peer)); await coordinator.connect(peripheralID: UUID())
            let pending = try XCTUnwrap(storage.record)
            XCTAssertEqual(coordinator.stage, .uncertain)
            storage.record = nil
            peer.loseClaimReply = false
            if let token = rescannedToken {
                coordinator.acceptQRCode(qr(peer, token: token))
                await coordinator.connect(peripheralID: UUID())
            } else { await coordinator.resume() }
            XCTAssertEqual(coordinator.stage, .recoveryRequired)
            XCTAssertFalse(coordinator.hasSavedIntention)
            XCTAssertEqual(storage.prepareCount, 1)
            XCTAssertEqual(peer.messages.filter { $0.operation == .claim }.count, 1)
            XCTAssertNil(storage.record)
            XCTAssertEqual(coordinator.owner?.ownerID, pending.ownerID)
            XCTAssertEqual(coordinator.owner?.claimRequestID, pending.claimRequestID)
        }
    }
    func testChangedDurableOwnerCannotReplaceKnownIntentionAfterReplyLoss() async throws {
        let (peer, storage) = try environment(); peer.loseClaimReply = true
        let coordinator = BootstrapSetupCoordinator(channel: peer, vault: storage)
        coordinator.acceptQRCode(qr(peer)); await coordinator.connect(peripheralID: UUID())
        let pending = try XCTUnwrap(storage.record)
        storage.record = BootstrapOwnershipRecord(provenance: pending.provenance, identity: pending.identity,
            certificateDER: pending.certificateDER, ownerID: UUID(), ownerToken: Data(repeating: 0xcc, count: 32),
            claimRequestID: UUID(), state: .pending)
        await coordinator.resume()
        XCTAssertEqual(coordinator.stage, .recoveryRequired)
        XCTAssertEqual(coordinator.owner?.ownerID, pending.ownerID)
        XCTAssertEqual(coordinator.owner?.claimRequestID, pending.claimRequestID)
        XCTAssertEqual(peer.messages.filter { $0.operation == .claim }.count, 1)
    }
    func testSuspensionBeforePreparationDoesNotClaimToHaveSavedAuthorization() throws {
        let (peer, storage) = try environment()
        let coordinator = BootstrapSetupCoordinator(channel: peer, vault: storage)
        coordinator.acceptQRCode(qr(peer)); coordinator.suspend()
        XCTAssertEqual(coordinator.stage, .suspended)
        XCTAssertFalse(coordinator.hasSavedIntention)
        XCTAssertNil(storage.record)
    }

    func testNormalQRRejectedByBootstrapBeforeBluetoothOrStorage() throws {
        let (peer, storage) = try environment()
        let coordinator = BootstrapSetupCoordinator(channel: peer, vault: storage)
        coordinator.acceptQRCode(qr(peer).replacingOccurrences(of: "\"v\":2,\"p\":\"bootstrap\",", with: "\"v\":1,"))
        XCTAssertEqual(coordinator.stage, .scanQR)
        XCTAssertNil(storage.record); XCTAssertEqual(peer.connectCount, 0)
    }
    func testChangedPhysicalProofRetainsOwnerAndClaimID() async throws {
        let (peer, storage) = try environment(); peer.rejectClaims = true
        let coordinator = BootstrapSetupCoordinator(channel: peer, vault: storage)
        coordinator.acceptQRCode(qr(peer)); await coordinator.connect(peripheralID: UUID())
        let pending = try XCTUnwrap(storage.record)
        coordinator.acceptQRCode(qr(peer, token: String(repeating: "c", count: 64)))
        await coordinator.connect(peripheralID: UUID())
        XCTAssertEqual(storage.prepareCount, 1)
        XCTAssertEqual(storage.record?.ownerID, pending.ownerID)
        XCTAssertEqual(storage.record?.claimRequestID, pending.claimRequestID)
        XCTAssertEqual(peer.messages.filter { $0.operation == .claim }.map(\.id), [pending.claimRequestID, pending.claimRequestID])
    }
}

@MainActor private final class BootstrapTestPeer: BootstrapConnection {
    let trust: BootstrapFrameTrust
    var messages: [BootstrapRequest] = []
    var winningOwner: UUID?
    var winningToken: Data?
    var winningClaim: UUID?
    var connectCount = 0
    var loseClaimReply = false
    var revoked = false
    var rejectClaims = false
    var omitCorrelation = false
    var corruptSuccessField: String?
    var onClaim: () -> Void = {}
    init(trust: BootstrapFrameTrust) { self.trust = trust }
    func connect(peripheralID: UUID, identity: FrameIdentity) async throws -> BootstrapFrameTrust {
        connectCount += 1; return trust
    }
    func disconnect() {}
    func request(_ data: Data, timeout: TimeInterval) async throws -> Data {
        let fields = try BootstrapWire.object(data)
        let operation: BootstrapRequest.Operation
        switch fields["op"] {
        case .string("bootstrap.claim"): operation = .claim
        case .string("bootstrap.status"): operation = .status
        default: XCTFail("Phase B or normal operation escaped lot A"); throw URLError(.unsupportedURL)
        }
        let request = try BootstrapRequest.parse(data, operation: operation)
        messages.append(request)
        func failure(_ code: String) throws -> Data {
            try JSONSerialization.data(withJSONObject: ["v": 1,
                "id": omitCorrelation ? NSNull() : request.id.uuidString.lowercased() as Any,
                "ok": false, "error": code])
        }
        switch operation {
        case .status:
            guard !revoked, winningOwner == request.ownerID, winningToken == request.ownerToken else {
                return try failure("unauthorized")
            }
            guard winningClaim == request.claimRequestID else { return try failure("request_not_found") }
        case .claim:
            if rejectClaims || revoked { return try failure("unauthorized") }
            guard winningOwner == nil || winningOwner == request.ownerID else { return try failure("qr_unavailable") }
            winningOwner = request.ownerID; winningToken = request.ownerToken; winningClaim = request.id
            onClaim()
            if loseClaimReply { throw URLError(.timedOut) }
        }
        var result = ["frame_id": trust.identity.id.uuidString.lowercased(), "owner_id": request.ownerID.uuidString.lowercased(),
            "claim_request_id": try XCTUnwrap(winningClaim).uuidString.lowercased(), "factory_state": "adopted", "next_step": "system_setup"]
        if let key = corruptSuccessField { result[key] = UUID().uuidString.lowercased() }
        return try JSONSerialization.data(withJSONObject: ["v": 1, "id": request.id.uuidString.lowercased(), "ok": true, "result": result])
    }
}

@MainActor private final class BootstrapMemoryStorage: BootstrapOwnershipStorage {
    var record: BootstrapOwnershipRecord?
    var rejectPrepare = false
    var rejectMark = false
    var prepareCount = 0
    func allRecords() throws -> [BootstrapOwnershipRecord] { record.map { [$0] } ?? [] }
    func load(id: UUID) throws -> BootstrapOwnershipRecord? { record?.id == id ? record : nil }
    func prepare(identity: FrameIdentity, certificateDER: Data) throws -> BootstrapOwnershipRecord {
        if rejectPrepare { throw OwnershipVaultError.unavailable }
        if let record { return record }
        prepareCount += 1
        let pending = BootstrapOwnershipRecord(provenance: .physicalBootstrapQRV2, identity: identity,
            certificateDER: certificateDER, ownerID: UUID(), ownerToken: Data(repeating: 0xbb, count: 32),
            claimRequestID: UUID(), state: .pending)
        record = pending; return pending
    }
    func refreshCertificate(id: UUID, certificateDER: Data) throws -> BootstrapOwnershipRecord { try XCTUnwrap(record) }
    func markAdopted(record: BootstrapOwnershipRecord) throws -> BootstrapOwnershipRecord {
        if rejectMark { throw OwnershipVaultError.unavailable }
        let adopted = BootstrapOwnershipRecord(provenance: record.provenance, identity: record.identity,
            certificateDER: record.certificateDER, ownerID: record.ownerID, ownerToken: record.ownerToken,
            claimRequestID: record.claimRequestID, state: .adoptedAwaitingPreparation)
        self.record = adopted; return adopted
    }
}
