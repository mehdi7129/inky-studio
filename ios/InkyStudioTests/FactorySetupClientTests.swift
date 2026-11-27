import Foundation
import XCTest
@testable import InkyStudio

@MainActor
final class FactorySetupClientTests: XCTestCase {
    func testOnlyNegotiateCanSendV2BeforeThisPeerNegotiates() async throws {
        let harness = try FactorySetupClientHarness()
        await assertFailure(.negotiationRequired) { _ = try await harness.client.status(operationID: FactorySetupFixtures.operation) }
        await assertFailure(.negotiationRequired) { _ = try await harness.client.challenge() }
        await assertFailure(.negotiationRequired) { _ = try await harness.client.apply(utcSeconds: 1_792_152_000) }
        await assertFailure(.negotiationRequired) { _ = try await harness.client.continueSetup(operationID: FactorySetupFixtures.operation) }
        XCTAssertThrowsError(try harness.client.prepareOperation(country: "FR"))
        XCTAssertTrue(harness.peer.messages.isEmpty)
        _ = try await harness.client.negotiate()
        XCTAssertEqual(harness.peer.operations, ["system_setup.negotiate"])
        let request = try XCTUnwrap(harness.peer.messages.first)
        XCTAssertEqual(Set(request.keys), ["v", "id", "op", "owner_id", "owner_token", "claim_request_id", "versions"])
        XCTAssertEqual(request["versions"] as? [Int], [2])
    }

    func testBootstrapRequestsUseUnchangedV1AndExactPersistedClaimCredential() async throws {
        let harness = try FactorySetupClientHarness()
        _ = try await harness.client.bootstrapStatus()
        _ = try await harness.client.bootstrapClaim(claimToken: Data(repeating: 0xb6, count: 32))
        let status = harness.peer.messages[0], claim = harness.peer.messages[1]
        XCTAssertEqual(Set(status.keys), ["v", "id", "op", "owner_id", "owner_token", "claim_request_id"])
        XCTAssertEqual(Set(claim.keys), ["v", "id", "op", "owner_id", "owner_token", "claim_token"])
        XCTAssertEqual(status["v"] as? Int, 1)
        XCTAssertEqual(claim["v"] as? Int, 1)
        XCTAssertEqual(status["claim_request_id"] as? String, harness.owner.claimRequestID.uuidString.lowercased())
        XCTAssertEqual(claim["id"] as? String, harness.owner.claimRequestID.uuidString.lowercased())
        XCTAssertEqual(claim["owner_token"] as? String, harness.owner.ownerTokenHex)
        XCTAssertEqual(claim["claim_token"] as? String, String(repeating: "b6", count: 32))
        await assertFailure(.negotiationRequired) { _ = try await harness.client.status(operationID: FactorySetupFixtures.operation) }
    }

    func testCountryIsExplicitAndFailedPreparationNeverSendsChallenge() async throws {
        let harness = try FactorySetupClientHarness()
        _ = try await harness.client.negotiate()
        for country in ["", "fr", "F", "FRA", "ÉU", "F1", " F"] {
            XCTAssertThrowsError(try harness.client.prepareOperation(country: country))
        }
        harness.storage.rejectWrites = true
        XCTAssertThrowsError(try harness.client.prepareOperation(country: "FR"))
        await assertFailure(.missingCheckpoint) { _ = try await harness.client.challenge() }
        XCTAssertEqual(harness.peer.operations, ["system_setup.negotiate"])
    }

    func testOperationCountryAndRequestIDExistDurablyBeforeChallengeIsSent() async throws {
        let harness = try FactorySetupClientHarness()
        _ = try await harness.client.negotiate()
        let saved = try harness.client.prepareOperation(country: "FR")
        harness.peer.onRequest = { request in
            guard request["op"] as? String == "system_setup.challenge" else { return }
            XCTAssertEqual(harness.storage.value, saved)
            XCTAssertEqual(request["op_id"] as? String, saved.operationID.uuidString.lowercased())
            XCTAssertEqual(request["id"] as? String, saved.challengeRequestID.uuidString.lowercased())
            XCTAssertTrue(request["supersedes_op_id"] is NSNull)
            XCTAssertEqual(Set(request.keys), ["v", "id", "op", "owner_id", "owner_token", "claim_request_id", "op_id", "supersedes_op_id"])
        }
        let challenge = try await harness.client.challenge()
        XCTAssertEqual(try harness.client.checkpoint()?.challenge, challenge)
        XCTAssertEqual(harness.storage.saveCount, 2)
        _ = try await harness.client.challenge()
        XCTAssertEqual(harness.peer.operations.filter { $0 == "system_setup.challenge" }.count, 1)
    }

    func testLostChallengeReplyRetriesSameOperationAndRPCIdentifier() async throws {
        let harness = try FactorySetupClientHarness()
        _ = try await harness.client.negotiate()
        _ = try harness.client.prepareOperation(country: "FR")
        harness.peer.failNextOperation = "system_setup.challenge"
        do { _ = try await harness.client.challenge(); XCTFail("Expected transport timeout") } catch {}
        XCTAssertNil(try harness.client.checkpoint()?.challenge)
        _ = try await harness.client.challenge()
        let requests = harness.peer.rawRequestsFor("system_setup.challenge")
        XCTAssertEqual(requests.count, 2)
        XCTAssertEqual(requests.first, requests.last)
    }

    func testExactApplyIntentIsPersistedBeforeWireAndIdenticalOnRetryAfterLostACK() async throws {
        let harness = try FactorySetupClientHarness()
        try await harness.prepareChallenge()
        let utc: UInt64 = 1_792_152_000
        harness.peer.onRequest = { request in
            guard request["op"] as? String == "system_setup.apply" else { return }
            let intent = harness.storage.value?.applyIntent
            XCTAssertEqual(intent?.utcSeconds, utc)
            XCTAssertEqual(intent?.country, "FR")
            XCTAssertEqual(intent?.requestID.uuidString.lowercased(), request["id"] as? String)
            XCTAssertEqual(intent?.challenge.challengeID.uuidString.lowercased(), request["challenge_id"] as? String)
            XCTAssertEqual(Set(request.keys), ["v", "id", "op", "owner_id", "owner_token", "claim_request_id", "op_id", "challenge_id", "nonce", "utc_seconds", "country"])
        }
        harness.peer.failNextOperation = "system_setup.apply"
        do { _ = try await harness.client.apply(utcSeconds: utc); XCTFail("Expected transport timeout") } catch {}
        let original = try XCTUnwrap(harness.client.checkpoint())
        let result = try await harness.client.retryApply()
        XCTAssertEqual(result.state, .applying)
        XCTAssertEqual(result.nextStep, .status)
        XCTAssertEqual(try harness.client.checkpoint(), original)
        let requests = harness.peer.rawRequestsFor("system_setup.apply")
        XCTAssertEqual(requests.count, 2)
        XCTAssertEqual(requests.first, requests.last)
    }

    func testNewClientAfterReconnectReusesPersistedIntentButMustRenegotiate() async throws {
        let harness = try FactorySetupClientHarness()
        try await harness.prepareChallenge()
        harness.peer.failNextOperation = "system_setup.apply"
        do { _ = try await harness.client.apply(utcSeconds: 1_792_152_000) } catch {}
        let original = try XCTUnwrap(harness.client.checkpoint())
        harness.peer.latest = original.operationID
        let replacement = FactorySetupClient(request: harness.peer.send, owner: harness.owner, checkpoints: harness.storage)
        await assertFailure(.negotiationRequired) { _ = try await replacement.retryApply() }
        _ = try await replacement.negotiate()
        _ = try await replacement.retryApply()
        XCTAssertEqual(harness.peer.rawRequestsFor("system_setup.apply").first, harness.peer.rawRequestsFor("system_setup.apply").last)
        XCTAssertEqual(try replacement.checkpoint(), original)
    }

    func testChangedUTCOrCountryCannotOverwriteSavedIntent() async throws {
        let harness = try FactorySetupClientHarness()
        try await harness.prepareChallenge()
        _ = try await harness.client.apply(utcSeconds: 1_792_152_000)
        let original = try harness.client.checkpoint()
        await assertFailure(.checkpointConflict) { _ = try await harness.client.apply(utcSeconds: 1_792_152_001) }
        XCTAssertThrowsError(try harness.client.prepareOperation(country: "US"))
        XCTAssertEqual(try harness.client.checkpoint(), original)
        XCTAssertEqual(harness.peer.rawRequestsFor("system_setup.apply").count, 1)
    }

    func testApplyStorageFailureAndInvalidUTCPreventSubmission() async throws {
        let harness = try FactorySetupClientHarness()
        try await harness.prepareChallenge()
        for utc: UInt64 in [0, 1_767_225_599, 4_102_444_800, 9_007_199_254_740_991, UInt64.max] {
            await assertFailure(.invalidMessage) { _ = try await harness.client.apply(utcSeconds: utc) }
        }
        harness.storage.rejectWrites = true
        await assertFailure(.storageUnavailable) { _ = try await harness.client.apply(utcSeconds: 1_792_152_000) }
        XCTAssertNil(try harness.client.checkpoint()?.applyIntent)
        XCTAssertTrue(harness.peer.rawRequestsFor("system_setup.apply").isEmpty)
    }

    func testMissingCheckpointRecoversLatestReadOnlyAndNeverAutoAppliesSuggestedNextStep() async throws {
        let harness = try FactorySetupClientHarness()
        harness.peer.latest = FactorySetupFixtures.operation
        harness.peer.state = .challengeIssued
        harness.peer.nextStepOverride = "apply"
        let negotiated = try await harness.client.negotiate()
        XCTAssertEqual(negotiated.latestOperationID, FactorySetupFixtures.operation)
        let status = try await harness.client.status(operationID: FactorySetupFixtures.operation)
        XCTAssertEqual(status.nextStep, .apply)
        XCTAssertNil(try harness.client.checkpoint())
        XCTAssertThrowsError(try harness.client.prepareOperation(country: "FR"))
        await assertFailure(.missingCheckpoint) { _ = try await harness.client.apply(utcSeconds: 1_792_152_000) }
        XCTAssertEqual(harness.peer.operations, ["system_setup.negotiate", "system_setup.status"])
    }

    func testExplicitSupersedeBindsDiscoveredLatestEvenWithDivergentLocalCheckpoint() async throws {
        let harness = try FactorySetupClientHarness()
        try await harness.prepareChallenge()
        let old = try XCTUnwrap(harness.client.checkpoint())
        harness.peer.latest = FactorySetupFixtures.operation
        _ = try await harness.client.negotiate()
        XCTAssertThrowsError(try harness.client.prepareOperation(country: "FR", supersedesOperationID: UUID()))
        let fresh = try harness.client.prepareOperation(country: "US", supersedesOperationID: FactorySetupFixtures.operation)
        XCTAssertNotEqual(fresh.operationID, old.operationID)
        XCTAssertEqual(fresh.supersedesOperationID, FactorySetupFixtures.operation)
        XCTAssertNil(fresh.challenge)
        XCTAssertNil(fresh.applyIntent)
        _ = try await harness.client.challenge()
        let request = try XCTUnwrap(harness.peer.messages.last)
        XCTAssertEqual(request["supersedes_op_id"] as? String, FactorySetupFixtures.operation.uuidString.lowercased())
        XCTAssertFalse(harness.peer.operations.contains("system_setup.apply"))
    }

    func testContinueIsAnExplicitSeparateRequestAndStatusDoesNotInvokeIt() async throws {
        let harness = try FactorySetupClientHarness()
        _ = try await harness.client.negotiate()
        harness.peer.state = .setupReady
        harness.peer.nextStepOverride = "continue"
        _ = try await harness.client.status(operationID: FactorySetupFixtures.operation)
        XCTAssertFalse(harness.peer.operations.contains("system_setup.continue"))
        harness.peer.state = .complete
        harness.peer.nextStepOverride = nil
        let continued = try await harness.client.continueSetup(operationID: FactorySetupFixtures.operation)
        XCTAssertEqual(continued.action, .alreadyComplete)
        XCTAssertEqual(continued.status.nextStep, .photoEnroll)
        XCTAssertNil(try harness.client.checkpoint())
        XCTAssertEqual(harness.peer.operations, ["system_setup.negotiate", "system_setup.status", "system_setup.continue"])
    }

    func testCancellationRejectsLateChallengeWithoutPersistingIt() async throws {
        let harness = try FactorySetupClientHarness()
        _ = try await harness.client.negotiate()
        let initial = try harness.client.prepareOperation(country: "FR")
        harness.peer.deferOperation = "system_setup.challenge"
        let task = Task { try await harness.client.challenge() }
        await harness.peer.waitForPending()
        task.cancel()
        harness.peer.completePending()
        do { _ = try await task.value; XCTFail("Expected cancellation") }
        catch { XCTAssertTrue(error is CancellationError) }
        XCTAssertEqual(try harness.client.checkpoint(), initial)
    }

    func testPeerInvalidationRejectsLateReplyAndRevokesNegotiation() async throws {
        let harness = try FactorySetupClientHarness()
        _ = try await harness.client.negotiate()
        let initial = try harness.client.prepareOperation(country: "FR")
        harness.peer.deferOperation = "system_setup.challenge"
        let task = Task { try await harness.client.challenge() }
        await harness.peer.waitForPending()
        harness.client.invalidate()
        harness.peer.completePending()
        do { _ = try await task.value; XCTFail("Expected invalidation") }
        catch { XCTAssertEqual(error as? FactorySetupError, .invalidated) }
        XCTAssertEqual(try harness.client.checkpoint(), initial)
        await assertFailure(.negotiationRequired) { _ = try await harness.client.status(operationID: initial.operationID) }
    }

    func testFailedNegotiationDoesNotOpenOtherV2Operations() async throws {
        let harness = try FactorySetupClientHarness()
        harness.peer.serverError = "unsupported_version"
        await assertFailure(.remote("unsupported_version")) { _ = try await harness.client.negotiate() }
        await assertFailure(.negotiationRequired) { _ = try await harness.client.status(operationID: FactorySetupFixtures.operation) }
        XCTAssertEqual(harness.peer.operations, ["system_setup.negotiate"])
    }

    private func assertFailure(_ expected: FactorySetupError, _ action: () async throws -> Void,
                               file: StaticString = #filePath, line: UInt = #line) async {
        do { try await action(); XCTFail("Expected \(expected)", file: file, line: line) }
        catch { XCTAssertEqual(error as? FactorySetupError, expected, file: file, line: line) }
    }
}

@MainActor
final class FactorySetupMemoryCheckpoints: FactorySetupCheckpointStorage {
    var value: FactorySetupCheckpoint?
    var saveCount = 0
    var rejectWrites = false
    func load(binding: FactorySetupBinding) throws -> FactorySetupCheckpoint? {
        guard value?.binding == binding else { return nil }; return value
    }
    func save(_ checkpoint: FactorySetupCheckpoint) throws {
        if rejectWrites { throw FactorySetupError.storageUnavailable }
        try checkpoint.validate(binding: checkpoint.binding)
        value = checkpoint; saveCount += 1
    }
    func remove(binding: FactorySetupBinding) throws { if value?.binding == binding { value = nil } }
}

@MainActor
private final class FactorySetupClientHarness {
    let owner: OwnershipRecord
    let storage = FactorySetupMemoryCheckpoints()
    let peer = FactorySetupTestPeer()
    let client: FactorySetupClient
    init() throws {
        owner = try FactorySetupFixtures.owner()
        client = FactorySetupClient(request: peer.send, owner: owner, checkpoints: storage)
    }
    func prepareChallenge() async throws {
        _ = try await client.negotiate()
        _ = try client.prepareOperation(country: "FR")
        _ = try await client.challenge()
    }
}

@MainActor
private final class FactorySetupTestPeer {
    var messages: [[String: Any]] = []
    var rawRequests: [Data] = []
    var operations: [String] { messages.compactMap { $0["op"] as? String } }
    var latest: UUID?
    var state: FactorySetupState = .complete
    var nextStepOverride: String?
    var failNextOperation: String?
    var serverError: String?
    var onRequest: (([String: Any]) -> Void)?
    var deferOperation: String?
    private var pending: CheckedContinuation<Data, Error>?
    private var pendingData: Data?

    func rawRequestsFor(_ operation: String) -> [Data] {
        zip(messages, rawRequests).filter { $0.0["op"] as? String == operation }.map(\.1)
    }
    func send(_ data: Data, _ timeout: TimeInterval) async throws -> Data {
        XCTAssertEqual(timeout, 20)
        let request = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
        messages.append(request); rawRequests.append(data)
        onRequest?(request)
        let operation = try XCTUnwrap(request["op"] as? String)
        let rpc = try XCTUnwrap(UUID(uuidString: XCTUnwrap(request["id"] as? String)))
        if failNextOperation == operation { failNextOperation = nil; throw URLError(.timedOut) }
        if let serverError {
            return try JSONSerialization.data(withJSONObject: ["v": 2, "id": rpc.uuidString.lowercased(), "ok": false, "error": serverError])
        }
        let response: Data
        switch operation {
        case "system_setup.negotiate": response = try FactorySetupFixtures.negotiate(id: rpc, latest: latest)
        case "bootstrap.claim", "bootstrap.status": response = try FactorySetupFixtures.reply(FactorySetupFixtures.bootstrapResult(), id: rpc, version: 1)
        default:
            let opID = try XCTUnwrap(UUID(uuidString: XCTUnwrap(request["op_id"] as? String)))
            switch operation {
            case "system_setup.challenge": response = try FactorySetupFixtures.reply(FactorySetupFixtures.challengeResult(operation: opID), id: rpc)
            case "system_setup.apply": response = try FactorySetupFixtures.reply(FactorySetupFixtures.ackResult(operation: opID), id: rpc)
            case "system_setup.status", "system_setup.continue":
                var result = FactorySetupFixtures.statusResult(operation: opID, state: state)
                if let nextStepOverride { result["next_step"] = nextStepOverride }
                if operation == "system_setup.continue" { result["action"] = "already_complete" }
                response = try FactorySetupFixtures.reply(result, id: rpc)
            default: throw FactorySetupError.invalidMessage
            }
        }
        if deferOperation == operation {
            pendingData = response
            return try await withCheckedThrowingContinuation { pending = $0 }
        }
        return response
    }
    func waitForPending() async {
        for _ in 0..<100 where pending == nil { await Task.yield() }
        XCTAssertNotNil(pending)
    }
    func completePending() {
        let continuation = pending, data = pendingData
        pending = nil; pendingData = nil
        if let data { continuation?.resume(returning: data) }
        else { continuation?.resume(throwing: FactorySetupError.invalidMessage) }
    }
}
