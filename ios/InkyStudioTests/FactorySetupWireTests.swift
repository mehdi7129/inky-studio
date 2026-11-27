import Foundation
import XCTest
@testable import InkyStudio

final class FactorySetupWireTests: XCTestCase {
    func testRequestEncoderRejectsUnknownFieldsVersionsAndInvalidIntentBeforeTransmission() throws {
        let owner = try FactorySetupFixtures.owner()
        for fields: [String: Any] in [["versions": [2], "unknown": 0], ["versions": [true]], ["versions": [1]]] {
            XCTAssertThrowsError(try FactorySetupWire.encodeRequest(operation: "system_setup.negotiate", requestID: FactorySetupFixtures.rpc,
                                                                   owner: owner, fields: fields))
        }
        XCTAssertThrowsError(try FactorySetupWire.encodeRequest(operation: "system_setup.UNKNOWN", requestID: FactorySetupFixtures.rpc, owner: owner))
        XCTAssertThrowsError(try FactorySetupWire.encodeRequest(operation: "system_setup.challenge", requestID: FactorySetupFixtures.rpc, owner: owner,
            fields: ["op_id": FactorySetupFixtures.operation.uuidString.lowercased(), "supersedes_op_id": FactorySetupFixtures.operation.uuidString.lowercased()]))
        XCTAssertThrowsError(try FactorySetupWire.encodeRequest(operation: "bootstrap.claim", requestID: FactorySetupFixtures.rpc, owner: owner,
            fields: ["claim_token": String(repeating: "a", count: 63)], bootstrap: true))
    }

    func testNegotiationPreservesVerifiedNullOrLatestOperation() throws {
        let empty = try FactorySetupWire.decodeNegotiation(FactorySetupFixtures.negotiate(), requestID: FactorySetupFixtures.rpc)
        XCTAssertNil(empty.latestOperationID)
        XCTAssertEqual(empty.selectedVersion, 2)
        let found = try FactorySetupWire.decodeNegotiation(FactorySetupFixtures.negotiate(latest: FactorySetupFixtures.operation),
                                                          requestID: FactorySetupFixtures.rpc)
        XCTAssertEqual(found.latestOperationID, FactorySetupFixtures.operation)
    }

    func testVersionsRequireLiteralIntegerAndCapabilitiesAreExact() throws {
        let text = String(decoding: try FactorySetupFixtures.negotiate(), as: UTF8.self)
        for token in ["true", "2.0", "2e0", "\"2\"", "02", "-0", "1", "null"] {
            XCTAssertThrowsError(try FactorySetupWire.decodeNegotiation(Data(text.replacingOccurrences(of: "\"v\":2", with: "\"v\":\(token)").utf8),
                                                                        requestID: FactorySetupFixtures.rpc))
        }
        let reordered = text.replacingOccurrences(of: "system_setup.challenge", with: "system_setup.UNKNOWN")
        XCTAssertThrowsError(try FactorySetupWire.decodeNegotiation(Data(reordered.utf8), requestID: FactorySetupFixtures.rpc))
        let floatingSelection = text.replacingOccurrences(of: "\"selected_version\":2", with: "\"selected_version\":2.0")
        XCTAssertThrowsError(try FactorySetupWire.decodeNegotiation(Data(floatingSelection.utf8), requestID: FactorySetupFixtures.rpc))
    }

    func testClosedEnvelopesAndDecodedDuplicateNamesAreRejected() throws {
        let text = String(decoding: try FactorySetupFixtures.negotiate(), as: UTF8.self)
        let variants = [
            text.replacingOccurrences(of: "\"v\":2", with: "\"v\":2,\"\\u0076\":2"),
            text.replacingOccurrences(of: "\"v\":2", with: "\"v\":2,\"extra\":false"),
            text.replacingOccurrences(of: "\"result\":{", with: "\"result\":{\"unknown\":0,"),
            text.replacingOccurrences(of: "\"latest_operation_id\":null", with: "\"latest_operation_id\":null,\"latest_operation_id\":null"),
            text + "{}", String(text.dropLast()) + ",}",
        ]
        for variant in variants {
            XCTAssertThrowsError(try FactorySetupWire.decodeNegotiation(Data(variant.utf8), requestID: FactorySetupFixtures.rpc))
        }
    }

    func testChallengeKeepsUInt63PrecisionAndExactBootTTL() throws {
        var result = FactorySetupFixtures.challengeResult()
        let issued = UInt64(Int64.max) - 30_000_000_000
        result["issued_boottime_ns"] = issued
        result["expires_boottime_ns"] = UInt64(Int64.max)
        let challenge = try FactorySetupWire.decodeChallenge(FactorySetupFixtures.reply(result), requestID: FactorySetupFixtures.rpc,
                                                             operationID: FactorySetupFixtures.operation)
        XCTAssertEqual(challenge.issuedBoottimeNS, issued)
        XCTAssertEqual(challenge.expiresBoottimeNS, UInt64(Int64.max))
        result["expires_boottime_ns"] = UInt64(Int64.max) - 1
        XCTAssertThrowsError(try FactorySetupWire.decodeChallenge(FactorySetupFixtures.reply(result), requestID: FactorySetupFixtures.rpc,
                                                                 operationID: FactorySetupFixtures.operation))
        result["expires_boottime_ns"] = UInt64(Int64.max) + 1
        XCTAssertThrowsError(try FactorySetupWire.decodeChallenge(FactorySetupFixtures.reply(result), requestID: FactorySetupFixtures.rpc,
                                                                 operationID: FactorySetupFixtures.operation))
    }

    func testChallengeRejectsCoercedNumbersAndNoncanonicalIdentifiers() throws {
        let text = String(decoding: try FactorySetupFixtures.reply(FactorySetupFixtures.challengeResult()), as: UTF8.self)
        for token in ["true", "1000000000.0", "1e9", "\"1000000000\"", "-1", "NaN", "Infinity"] {
            let mutated = text.replacingOccurrences(of: "\"issued_boottime_ns\":1000000000", with: "\"issued_boottime_ns\":\(token)")
            XCTAssertThrowsError(try FactorySetupWire.decodeChallenge(Data(mutated.utf8), requestID: FactorySetupFixtures.rpc,
                                                                     operationID: FactorySetupFixtures.operation))
        }
        let uppercaseID = text.replacingOccurrences(of: FactorySetupFixtures.operation.uuidString.lowercased(),
                                                    with: FactorySetupFixtures.operation.uuidString.uppercased())
        XCTAssertThrowsError(try FactorySetupWire.decodeChallenge(Data(uppercaseID.utf8), requestID: FactorySetupFixtures.rpc,
                                                                 operationID: FactorySetupFixtures.operation))
        let uppercaseNonce = text.replacingOccurrences(of: String(repeating: "ab", count: 32), with: String(repeating: "AB", count: 32))
        XCTAssertThrowsError(try FactorySetupWire.decodeChallenge(Data(uppercaseNonce.utf8), requestID: FactorySetupFixtures.rpc,
                                                                 operationID: FactorySetupFixtures.operation))
    }

    func testApplyAcknowledgesOnlyRegistrationNotDurableSuccess() throws {
        let binding = FactorySetupBinding(owner: try FactorySetupFixtures.owner())
        let acknowledgement = try FactorySetupWire.decodeApply(FactorySetupFixtures.reply(FactorySetupFixtures.ackResult()),
            requestID: FactorySetupFixtures.rpc, operationID: FactorySetupFixtures.operation, binding: binding)
        XCTAssertEqual(acknowledgement.state, .applying)
        XCTAssertEqual(acknowledgement.nextStep, .status)
        for (key, value) in [("state", "complete"), ("durability", "confirmed"), ("submission", "durable"), ("next_step", "photo_enroll")] {
            var result = FactorySetupFixtures.ackResult(); result[key] = value
            XCTAssertThrowsError(try FactorySetupWire.decodeApply(FactorySetupFixtures.reply(result), requestID: FactorySetupFixtures.rpc,
                operationID: FactorySetupFixtures.operation, binding: binding))
        }
    }

    func testEveryResultIsBoundToOperationFrameOwnerAndClaim() throws {
        let binding = FactorySetupBinding(owner: try FactorySetupFixtures.owner())
        for key in ["op_id", "frame_id", "owner_id", "claim_request_id"] {
            var result = FactorySetupFixtures.statusResult()
            result[key] = UUID().uuidString.lowercased()
            XCTAssertThrowsError(try FactorySetupWire.decodeStatus(FactorySetupFixtures.reply(result), requestID: FactorySetupFixtures.rpc,
                operationID: FactorySetupFixtures.operation, binding: binding))
        }
    }

    func testPublicationLineageCanDifferFromCurrentRecoveryOperation() throws {
        let binding = FactorySetupBinding(owner: try FactorySetupFixtures.owner())
        let status = try FactorySetupWire.decodeStatus(FactorySetupFixtures.reply(FactorySetupFixtures.statusResult()),
            requestID: FactorySetupFixtures.rpc, operationID: FactorySetupFixtures.operation, binding: binding)
        XCTAssertEqual(status.normalIdentity?.identity, binding.identity)
        XCTAssertEqual(status.normalIdentity?.publicationOperationID, FactorySetupFixtures.publication)
        XCTAssertNotEqual(status.normalIdentity?.publicationOperationID, status.operationID)
        XCTAssertEqual(status.httpsOrigin?.absoluteString, FactorySetupFixtures.origin)
        XCTAssertNotNil(status.completionID)
    }

    func testNormalIdentityRequiresClosedShapeAndExactFrameAndPin() throws {
        let binding = FactorySetupBinding(owner: try FactorySetupFixtures.owner())
        for key in ["frame_id", "spki_sha256", "extra"] {
            var result = FactorySetupFixtures.statusResult()
            var identity = try XCTUnwrap(result["normal_identity"] as? [String: Any])
            identity[key] = key == "spki_sha256" ? String(repeating: "cd", count: 32) : UUID().uuidString.lowercased()
            result["normal_identity"] = identity
            XCTAssertThrowsError(try FactorySetupWire.decodeStatus(FactorySetupFixtures.reply(result), requestID: FactorySetupFixtures.rpc,
                operationID: FactorySetupFixtures.operation, binding: binding))
        }
        let text = String(decoding: try FactorySetupFixtures.reply(FactorySetupFixtures.statusResult()), as: UTF8.self)
        let duplicate = text.replacingOccurrences(of: "\"normal_identity\":{", with: "\"normal_identity\":{\"\\u0066rame_id\":\"\(binding.identity.id.uuidString.lowercased())\",")
        XCTAssertThrowsError(try FactorySetupWire.decodeStatus(Data(duplicate.utf8), requestID: FactorySetupFixtures.rpc,
            operationID: FactorySetupFixtures.operation, binding: binding))
    }

    func testCompletedAndReadyStatesGateIdentityCompletionAndOrigin() throws {
        let binding = FactorySetupBinding(owner: try FactorySetupFixtures.owner())
        for state in [FactorySetupState.tlsReady, .wifiPending, .complete] {
            var result = FactorySetupFixtures.statusResult(state: state, hasOrigin: false)
            let status = try FactorySetupWire.decodeStatus(FactorySetupFixtures.reply(result), requestID: FactorySetupFixtures.rpc,
                operationID: FactorySetupFixtures.operation, binding: binding)
            XCTAssertNil(status.httpsOrigin)
            XCTAssertEqual(status.nextStep, .waitOrigin)
            result["next_step"] = state == .complete ? "photo_enroll" : "wifi"
            XCTAssertThrowsError(try FactorySetupWire.decodeStatus(FactorySetupFixtures.reply(result), requestID: FactorySetupFixtures.rpc,
                operationID: FactorySetupFixtures.operation, binding: binding))
            result = FactorySetupFixtures.statusResult(state: state)
            result["normal_identity"] = NSNull()
            XCTAssertThrowsError(try FactorySetupWire.decodeStatus(FactorySetupFixtures.reply(result), requestID: FactorySetupFixtures.rpc,
                operationID: FactorySetupFixtures.operation, binding: binding))
            result = FactorySetupFixtures.statusResult(state: state)
            result["completion_id"] = state == .complete ? NSNull() : FactorySetupFixtures.completion.uuidString.lowercased() as Any
            XCTAssertThrowsError(try FactorySetupWire.decodeStatus(FactorySetupFixtures.reply(result), requestID: FactorySetupFixtures.rpc,
                operationID: FactorySetupFixtures.operation, binding: binding))
        }
    }

    func testContinuationExactVariantsAndWaitOrigin() throws {
        let binding = FactorySetupBinding(owner: try FactorySetupFixtures.owner())
        let variants: [(String, FactorySetupState)] = [("publication_finalized", .tlsReady), ("wifi_pending", .wifiPending),
            ("completion_finalized", .complete), ("already_complete", .complete)]
        for (action, state) in variants {
            for origin in [true, false] {
                var result = FactorySetupFixtures.statusResult(state: state, hasOrigin: origin)
                result["action"] = action
                let continued = try FactorySetupWire.decodeContinuation(FactorySetupFixtures.reply(result), requestID: FactorySetupFixtures.rpc,
                    operationID: FactorySetupFixtures.operation, binding: binding)
                XCTAssertEqual(continued.action.rawValue, action)
                XCTAssertEqual(continued.status.state, state)
                result["action"] = state == .complete ? "publication_finalized" : "already_complete"
                XCTAssertThrowsError(try FactorySetupWire.decodeContinuation(FactorySetupFixtures.reply(result), requestID: FactorySetupFixtures.rpc,
                    operationID: FactorySetupFixtures.operation, binding: binding))
            }
        }
    }

    func testExplicitFactoryOriginRejectsCredentialsPathsInferenceAndMalformedURLs() throws {
        let binding = FactorySetupBinding(owner: try FactorySetupFixtures.owner())
        for origin in ["http://inky-" + String(repeating: "a", count: 32) + ".local:8443", FactorySetupFixtures.origin + "/",
                       FactorySetupFixtures.origin + "?x=y", FactorySetupFixtures.origin + "#x", "https://192.0.2.1:8443",
                       "https://user:secret@inky-" + String(repeating: "a", count: 32) + ".local:8443",
                       FactorySetupFixtures.origin.replacingOccurrences(of: "8443", with: "443"), "https://frame.local:8443"] {
            var result = FactorySetupFixtures.statusResult(); result["https_origin"] = origin
            XCTAssertThrowsError(try FactorySetupWire.decodeStatus(FactorySetupFixtures.reply(result), requestID: FactorySetupFixtures.rpc,
                operationID: FactorySetupFixtures.operation, binding: binding))
        }
    }

    func testGateBoundsRawBytesAndDepthAndRejectsInvalidJSONTokens() throws {
        let base = Data("{}".utf8)
        XCTAssertNoThrow(try FactorySetupWire.validateClosedJSON(base + Data(repeating: 32, count: 16_382)))
        XCTAssertThrowsError(try FactorySetupWire.validateClosedJSON(base + Data(repeating: 32, count: 16_383)))
        for token in ["1.0", "1e0", "01", "-0", "NaN", "Infinity", "-Infinity"] {
            XCTAssertThrowsError(try FactorySetupWire.validateClosedJSON(Data("{\"x\":\(token)}".utf8)))
        }
        let atLimit = "{\"x\":" + String(repeating: "[", count: 31) + "null" + String(repeating: "]", count: 31) + "}"
        XCTAssertNoThrow(try FactorySetupWire.validateClosedJSON(Data(atLimit.utf8)))
        let overLimit = "{\"x\":" + String(repeating: "[", count: 32) + "null" + String(repeating: "]", count: 32) + "}"
        XCTAssertThrowsError(try FactorySetupWire.validateClosedJSON(Data(overLimit.utf8)))
        for invalid in [Data([255]) + base, Data("{\"a\":null,\"\\u0061\":null}".utf8), Data("{\"x\":\"\\uD800\"}".utf8)] {
            XCTAssertThrowsError(try FactorySetupWire.validateClosedJSON(invalid))
        }
    }

    func testBootstrapV1ExactSuccessAndClosedFailureEnvelopeRemainDistinctFromV2() throws {
        let binding = FactorySetupBinding(owner: try FactorySetupFixtures.owner())
        let response = try FactorySetupFixtures.reply(FactorySetupFixtures.bootstrapResult(), version: 1)
        let result = try FactorySetupWire.decodeBootstrap(response, requestID: FactorySetupFixtures.rpc, binding: binding)
        XCTAssertEqual(result.claimRequestID, binding.claimRequestID)
        XCTAssertThrowsError(try FactorySetupWire.decodeBootstrap(FactorySetupFixtures.reply(FactorySetupFixtures.bootstrapResult()),
            requestID: FactorySetupFixtures.rpc, binding: binding))
        var wrong = FactorySetupFixtures.bootstrapResult(); wrong["factory_state"] = "normal"
        XCTAssertThrowsError(try FactorySetupWire.decodeBootstrap(FactorySetupFixtures.reply(wrong, version: 1),
            requestID: FactorySetupFixtures.rpc, binding: binding))
        let error = try JSONSerialization.data(withJSONObject: ["v": 1, "id": FactorySetupFixtures.rpc.uuidString.lowercased(),
                                                                 "ok": false, "error": "unauthorized"])
        XCTAssertThrowsError(try FactorySetupWire.decodeBootstrap(error, requestID: FactorySetupFixtures.rpc, binding: binding)) {
            XCTAssertEqual($0 as? FactorySetupError, .remote("unauthorized"))
        }
    }

    func testErrorEnvelopeNeverReturnsSuccessAndWrongIDsOrUnknownCodesAreRejected() throws {
        for id in [FactorySetupFixtures.rpc.uuidString.lowercased() as Any, NSNull()] {
            let error = try JSONSerialization.data(withJSONObject: ["v": 2, "id": id, "ok": false, "error": "unavailable"])
            XCTAssertThrowsError(try FactorySetupWire.decodeNegotiation(error, requestID: FactorySetupFixtures.rpc)) {
                XCTAssertEqual($0 as? FactorySetupError, .remote("unavailable"))
            }
        }
        for fields: [String: Any] in [["v": 2, "id": UUID().uuidString.lowercased(), "ok": false, "error": "unavailable"],
                                      ["v": 2, "id": NSNull(), "ok": false, "error": "secret_debug_message"],
                                      ["v": 2, "id": NSNull(), "ok": true, "result": [:]]] {
            let data = try JSONSerialization.data(withJSONObject: fields)
            XCTAssertThrowsError(try FactorySetupWire.decodeNegotiation(data, requestID: FactorySetupFixtures.rpc)) {
                XCTAssertEqual($0 as? FactorySetupError, .invalidMessage)
            }
        }
    }
}

/// Synthetic public identities; no real frame or credentials are used by these tests.
enum FactorySetupFixtures {
    static let rpc = UUID(uuidString: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")!
    static let frame = UUID(uuidString: "11111111-1111-4111-8111-111111111111")!
    static let ownerID = UUID(uuidString: "22222222-2222-4222-8222-222222222222")!
    static let claim = UUID(uuidString: "33333333-3333-4333-8333-333333333333")!
    static let operation = UUID(uuidString: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")!
    static let publication = UUID(uuidString: "44444444-4444-4444-8444-444444444444")!
    static let completion = UUID(uuidString: "55555555-5555-4555-8555-555555555555")!
    static let origin = "https://inky-" + String(repeating: "a", count: 32) + ".local:8443"
    static func owner() throws -> OwnershipRecord {
        OwnershipRecord(identity: try FrameIdentity(id: frame, spkiSHA256: Data(repeating: 0xab, count: 32)),
            certificateDER: Data(), ownerID: ownerID, claimRequestID: claim, ownerToken: Data(repeating: 0xa5, count: 32),
            endpoints: [], state: .claimed)
    }
    static func reply(_ result: [String: Any], id: UUID = rpc, version: Int = 2) throws -> Data {
        try JSONSerialization.data(withJSONObject: ["v": version, "id": id.uuidString.lowercased(), "ok": true, "result": result], options: [.sortedKeys])
    }
    static func negotiate(id: UUID = rpc, latest: UUID? = nil) throws -> Data {
        try reply(["selected_version": 2, "latest_operation_id": latest.map { $0.uuidString.lowercased() as Any } ?? NSNull(),
                   "capabilities": FactorySetupWire.capabilities], id: id)
    }
    static func challengeResult(operation: UUID = operation) -> [String: Any] {
        ["op_id": operation.uuidString.lowercased(), "challenge_id": "66666666-6666-4666-8666-666666666666",
         "nonce": String(repeating: "ab", count: 32), "boot_id": "77777777-7777-4777-8777-777777777777",
         "issued_boottime_ns": UInt64(1_000_000_000), "expires_boottime_ns": UInt64(31_000_000_000)]
    }
    static func ackResult(operation: UUID = operation) -> [String: Any] {
        ["op_id": operation.uuidString.lowercased(), "state": "applying", "submission": "registered", "durability": "not_confirmed",
         "frame_id": frame.uuidString.lowercased(), "owner_id": ownerID.uuidString.lowercased(),
         "claim_request_id": claim.uuidString.lowercased(), "next_step": "status"]
    }
    static func statusResult(operation: UUID = operation, state: FactorySetupState = .complete, hasOrigin: Bool = true) -> [String: Any] {
        let ready = [FactorySetupState.tlsReady, .wifiPending, .complete].contains(state)
        return ["op_id": operation.uuidString.lowercased(), "state": state.rawValue, "frame_id": frame.uuidString.lowercased(),
         "owner_id": ownerID.uuidString.lowercased(), "claim_request_id": claim.uuidString.lowercased(),
         "normal_identity": ready ? ["frame_id": frame.uuidString.lowercased(), "spki_sha256": String(repeating: "ab", count: 32),
                                     "publication_op_id": publication.uuidString.lowercased()] as Any : NSNull(),
         "https_origin": hasOrigin ? origin as Any : NSNull(),
         "completion_id": state == .complete ? completion.uuidString.lowercased() as Any : NSNull(),
         "next_step": ready ? (hasOrigin ? (state == .complete ? "photo_enroll" : "wifi") : "wait_origin") : "status"]
    }
    static func bootstrapResult() -> [String: Any] {
        ["frame_id": frame.uuidString.lowercased(), "owner_id": ownerID.uuidString.lowercased(),
         "claim_request_id": claim.uuidString.lowercased(), "factory_state": "adopted", "next_step": "system_setup"]
    }
}
