import Foundation

/// Closed factory RPC v2 codecs and the unchanged bootstrap RPC v1 subset.
enum FactorySetupWire {
    static let maximumMessageBytes = 16_384
    static let capabilities = ["system_setup.challenge", "system_setup.apply", "system_setup.status", "system_setup.continue"]
    private static let publicErrors: Set<String> = ["invalid_request", "unsupported_version", "negotiation_required",
        "unauthorized", "request_not_found", "request_conflict", "epoch_changed", "rate_limited", "service_stopping",
        "recovery_required", "unavailable"]
    private static let bootstrapErrors: Set<String> = ["invalid_request", "unauthorized", "qr_unavailable", "request_conflict",
        "request_not_found", "epoch_changed", "owner_capacity", "rate_limited", "service_stopping", "recovery_required", "unavailable"]

    /// Structural gate for other closed factory messages; callers still validate their exact fields and types.
    static func validateClosedJSON(_ data: Data) throws { _ = try parse(data) }

    static func encodeRequest(operation: String, requestID: UUID, owner: OwnershipRecord,
                              fields: [String: Any] = [:], bootstrap: Bool = false) throws -> Data {
        guard owner.ownerToken.count == 32, owner.ownerID != owner.identity.id else { throw FactorySetupError.identityMismatch }
        var value: [String: Any] = ["v": bootstrap ? 1 : 2, "id": uuid(requestID), "op": operation,
                                    "owner_id": uuid(owner.ownerID), "owner_token": owner.ownerTokenHex]
        if !bootstrap { value["claim_request_id"] = uuid(owner.claimRequestID) }
        guard fields.keys.allSatisfy({ value[$0] == nil }) else { throw FactorySetupError.invalidMessage }
        value.merge(fields) { _, _ in NSNull() }
        let data = try JSONSerialization.data(withJSONObject: value, options: [.sortedKeys])
        try validateRequest(object(parse(data)), bootstrap: bootstrap)
        return data
    }

    private static func validateRequest(_ value: [String: FactoryJSONValue], bootstrap: Bool) throws {
        guard try integer(value["v"]) == (bootstrap ? 1 : 2) else { throw FactorySetupError.invalidMessage }
        _ = try requiredUUID(value["id"]); _ = try requiredUUID(value["owner_id"]); _ = try hexData(value["owner_token"])
        let operation = try string(value["op"])
        var keys: Set<String> = ["v", "id", "op", "owner_id", "owner_token"]
        if bootstrap {
            switch operation {
            case "bootstrap.claim": keys.insert("claim_token"); _ = try hexData(value["claim_token"])
            case "bootstrap.status": keys.insert("claim_request_id"); _ = try requiredUUID(value["claim_request_id"])
            default: throw FactorySetupError.invalidMessage
            }
        } else {
            keys.insert("claim_request_id"); _ = try requiredUUID(value["claim_request_id"])
            if operation == "system_setup.negotiate" {
                keys.insert("versions")
                guard case .array(let versions)? = value["versions"], versions.count == 1,
                      try integer(versions.first) == 2 else { throw FactorySetupError.invalidMessage }
            } else {
                keys.insert("op_id")
                let opID = try requiredUUID(value["op_id"])
                switch operation {
                case "system_setup.challenge":
                    keys.insert("supersedes_op_id")
                    guard try nullableUUID(value["supersedes_op_id"]) != opID else { throw FactorySetupError.invalidMessage }
                case "system_setup.apply":
                    keys.formUnion(["challenge_id", "nonce", "utc_seconds", "country"])
                    _ = try requiredUUID(value["challenge_id"]); _ = try hexData(value["nonce"])
                    guard try FactorySetupValidation.utc(integer(value["utc_seconds"])),
                          try FactorySetupValidation.country(string(value["country"])) else { throw FactorySetupError.invalidMessage }
                case "system_setup.status", "system_setup.continue": break
                default: throw FactorySetupError.invalidMessage
                }
            }
        }
        try closed(value, keys)
    }

    static func decodeNegotiation(_ data: Data, requestID: UUID) throws -> FactorySetupNegotiation {
        let value = try result(data, requestID: requestID)
        try closed(value, ["selected_version", "latest_operation_id", "capabilities"])
        guard try integer(value["selected_version"]) == 2,
              case .array(let rawCapabilities)? = value["capabilities"],
              try rawCapabilities.map({ try string($0) }) == capabilities else { throw FactorySetupError.invalidMessage }
        return FactorySetupNegotiation(latestOperationID: try nullableUUID(value["latest_operation_id"]))
    }

    static func decodeChallenge(_ data: Data, requestID: UUID, operationID: UUID) throws -> FactorySetupChallenge {
        let value = try result(data, requestID: requestID)
        try closed(value, ["op_id", "challenge_id", "nonce", "boot_id", "issued_boottime_ns", "expires_boottime_ns"])
        let challenge = FactorySetupChallenge(operationID: try requiredUUID(value["op_id"]),
            challengeID: try requiredUUID(value["challenge_id"]), nonce: try hexData(value["nonce"]),
            bootID: try requiredUUID(value["boot_id"]), issuedBoottimeNS: try integer(value["issued_boottime_ns"]),
            expiresBoottimeNS: try integer(value["expires_boottime_ns"]))
        guard challenge.operationID == operationID, FactorySetupValidation.challenge(challenge) else {
            throw FactorySetupError.invalidMessage
        }
        return challenge
    }

    static func decodeApply(_ data: Data, requestID: UUID, operationID: UUID,
                            binding: FactorySetupBinding) throws -> FactorySetupApplyAcknowledgement {
        let value = try result(data, requestID: requestID)
        try closed(value, ["op_id", "state", "submission", "durability", "frame_id", "owner_id", "claim_request_id", "next_step"])
        try bound(value, operationID: operationID, binding: binding)
        guard try string(value["state"]) == "applying", try string(value["submission"]) == "registered",
              try string(value["durability"]) == "not_confirmed", try string(value["next_step"]) == "status" else {
            throw FactorySetupError.invalidMessage
        }
        return FactorySetupApplyAcknowledgement(operationID: operationID, frameID: binding.identity.id,
                                                ownerID: binding.ownerID, claimRequestID: binding.claimRequestID)
    }

    static func decodeStatus(_ data: Data, requestID: UUID, operationID: UUID,
                             binding: FactorySetupBinding) throws -> FactorySetupStatus {
        try status(result(data, requestID: requestID), operationID: operationID, binding: binding, continuation: false)
    }

    static func decodeContinuation(_ data: Data, requestID: UUID, operationID: UUID,
                                   binding: FactorySetupBinding) throws -> FactorySetupContinuation {
        let value = try result(data, requestID: requestID)
        let decoded = try status(value, operationID: operationID, binding: binding, continuation: true)
        guard let action = FactorySetupContinueAction(rawValue: try string(value["action"])) else {
            throw FactorySetupError.invalidMessage
        }
        let expected: FactorySetupState
        switch action {
        case .publicationFinalized: expected = .tlsReady
        case .wifiPending: expected = .wifiPending
        case .completionFinalized, .alreadyComplete: expected = .complete
        }
        guard decoded.state == expected, decoded.normalIdentity != nil else { throw FactorySetupError.invalidMessage }
        return FactorySetupContinuation(status: decoded, action: action)
    }

    static func decodeBootstrap(_ data: Data, requestID: UUID, binding: FactorySetupBinding) throws -> FactoryBootstrapStatus {
        let value = try result(data, requestID: requestID, bootstrap: true)
        try closed(value, ["frame_id", "owner_id", "claim_request_id", "factory_state", "next_step"])
        try bound(value, operationID: nil, binding: binding)
        guard try string(value["factory_state"]) == "adopted", try string(value["next_step"]) == "system_setup" else {
            throw FactorySetupError.invalidMessage
        }
        return FactoryBootstrapStatus(frameID: binding.identity.id, ownerID: binding.ownerID, claimRequestID: binding.claimRequestID)
    }

    private static func status(_ value: [String: FactoryJSONValue], operationID: UUID, binding: FactorySetupBinding,
                               continuation: Bool) throws -> FactorySetupStatus {
        var keys: Set<String> = ["op_id", "state", "frame_id", "owner_id", "claim_request_id", "normal_identity",
                                  "https_origin", "completion_id", "next_step"]
        if continuation { keys.insert("action") }
        try closed(value, keys)
        try bound(value, operationID: operationID, binding: binding)
        guard let state = FactorySetupState(rawValue: try string(value["state"])),
              let next = FactorySetupNextStep(rawValue: try string(value["next_step"])) else { throw FactorySetupError.invalidMessage }
        let identity: FactorySetupNormalIdentity?
        if case .null? = value["normal_identity"] { identity = nil }
        else {
            let raw = try object(value["normal_identity"])
            try closed(raw, ["frame_id", "spki_sha256", "publication_op_id"])
            let frame = try FrameIdentity(id: requiredUUID(raw["frame_id"]), spkiSHA256: hexData(raw["spki_sha256"]))
            guard frame == binding.identity else { throw FactorySetupError.identityMismatch }
            identity = FactorySetupNormalIdentity(identity: frame, publicationOperationID: try requiredUUID(raw["publication_op_id"]))
        }
        let origin: URL?
        if case .null? = value["https_origin"] { origin = nil }
        else { origin = try FactorySetupValidation.origin(string(value["https_origin"])) }
        let completion = try nullableUUID(value["completion_id"])
        guard (completion != nil) == (state == .complete) else { throw FactorySetupError.invalidMessage }
        if [.tlsReady, .wifiPending, .complete].contains(state) {
            let expected: FactorySetupNextStep = origin == nil ? .waitOrigin : (state == .complete ? .photoEnroll : .wifi)
            guard identity != nil, next == expected else { throw FactorySetupError.invalidMessage }
        }
        return FactorySetupStatus(operationID: operationID, state: state, frameID: binding.identity.id,
            ownerID: binding.ownerID, claimRequestID: binding.claimRequestID, normalIdentity: identity,
            httpsOrigin: origin, completionID: completion, nextStep: next)
    }

    private static func result(_ data: Data, requestID: UUID, bootstrap: Bool = false) throws -> [String: FactoryJSONValue] {
        let value = try object(parse(data))
        guard try integer(value["v"]) == (bootstrap ? 1 : 2), case .bool(let ok)? = value["ok"] else {
            throw FactorySetupError.invalidMessage
        }
        let responseID = try nullableUUID(value["id"])
        // Null is a grammar-level server error only, never a successful correlated response.
        guard responseID == requestID || (!ok && responseID == nil) else { throw FactorySetupError.invalidMessage }
        if ok {
            try closed(value, ["v", "id", "ok", "result"])
            guard responseID != nil else { throw FactorySetupError.invalidMessage }
            return try object(value["result"])
        }
        try closed(value, ["v", "id", "ok", "error"])
        let code = try string(value["error"])
        guard (bootstrap ? bootstrapErrors : publicErrors).contains(code) else { throw FactorySetupError.invalidMessage }
        throw FactorySetupError.remote(code)
    }

    private static func bound(_ value: [String: FactoryJSONValue], operationID: UUID?, binding: FactorySetupBinding) throws {
        guard try requiredUUID(value["frame_id"]) == binding.identity.id,
              try requiredUUID(value["owner_id"]) == binding.ownerID,
              try requiredUUID(value["claim_request_id"]) == binding.claimRequestID else { throw FactorySetupError.identityMismatch }
        if let operationID, try requiredUUID(value["op_id"]) != operationID { throw FactorySetupError.identityMismatch }
    }

    private static func parse(_ data: Data) throws -> FactoryJSONValue {
        guard !data.isEmpty, data.count <= maximumMessageBytes, String(data: data, encoding: .utf8) != nil else {
            throw FactorySetupError.invalidMessage
        }
        var parser = FactoryJSONParser(bytes: Array(data))
        let value = try parser.parse()
        guard case .object = value else { throw FactorySetupError.invalidMessage }
        return value
    }
    private static func closed(_ object: [String: FactoryJSONValue], _ keys: Set<String>) throws {
        guard Set(object.keys) == keys else { throw FactorySetupError.invalidMessage }
    }
    private static func object(_ value: FactoryJSONValue?) throws -> [String: FactoryJSONValue] {
        guard case .object(let result)? = value else { throw FactorySetupError.invalidMessage }; return result
    }
    private static func string(_ value: FactoryJSONValue?) throws -> String {
        guard case .string(let result)? = value else { throw FactorySetupError.invalidMessage }; return result
    }
    private static func integer(_ value: FactoryJSONValue?) throws -> UInt64 {
        guard case .integer(let token)? = value, let result = UInt64(token), result <= UInt64(Int64.max) else {
            throw FactorySetupError.invalidMessage
        }; return result
    }
    private static func requiredUUID(_ value: FactoryJSONValue?) throws -> UUID {
        let raw = try string(value)
        guard raw.utf8.count == 36, let id = UUID(uuidString: raw), id.uuidString.lowercased() == raw else {
            throw FactorySetupError.invalidMessage
        }; return id
    }
    private static func nullableUUID(_ value: FactoryJSONValue?) throws -> UUID? {
        if case .null? = value { return nil }; return try requiredUUID(value)
    }
    private static func hexData(_ value: FactoryJSONValue?) throws -> Data {
        let raw = try string(value)
        let bytes = Array(raw.utf8)
        guard bytes.count == 64, bytes.allSatisfy({ (48...57).contains($0) || (97...102).contains($0) }) else {
            throw FactorySetupError.invalidMessage
        }
        func nibble(_ byte: UInt8) -> UInt8 { byte < 58 ? byte - 48 : byte - 87 }
        return Data(stride(from: 0, to: 64, by: 2).map { nibble(bytes[$0]) * 16 + nibble(bytes[$0 + 1]) })
    }
    private static func uuid(_ id: UUID) -> String { id.uuidString.lowercased() }
}

/// One instance belongs to one authenticated TLS peer. Recreate it after reconnect/profile change.
@MainActor
final class FactorySetupClient {
    typealias Request = @MainActor (Data, TimeInterval) async throws -> Data
    private let request: Request
    private let owner: OwnershipRecord
    private let binding: FactorySetupBinding
    private let checkpoints: any FactorySetupCheckpointStorage
    private var negotiated = false
    private var latestOperationID: UUID?
    private var generation = UUID()
    private var inFlight = false

    init(request: @escaping Request, owner: OwnershipRecord, checkpoints: (any FactorySetupCheckpointStorage)? = nil) {
        self.request = request; self.owner = owner; self.binding = FactorySetupBinding(owner: owner)
        self.checkpoints = checkpoints ?? FactorySetupKeychainCheckpointStore()
    }
    convenience init(channel: any ProvisioningConnection, owner: OwnershipRecord,
                     checkpoints: (any FactorySetupCheckpointStorage)? = nil) {
        self.init(request: { data, timeout in try await channel.request(data, timeout: timeout) }, owner: owner, checkpoints: checkpoints)
    }

    func invalidate() { generation = UUID(); negotiated = false; latestOperationID = nil }

    func checkpoint() throws -> FactorySetupCheckpoint? {
        let value = try checkpoints.load(binding: binding)
        try value?.validate(binding: binding)
        return value
    }

    func bootstrapClaim(claimToken: Data) async throws -> FactoryBootstrapStatus {
        guard claimToken.count == 32 else { throw FactorySetupError.invalidMessage }
        let id = owner.claimRequestID
        let data = try FactorySetupWire.encodeRequest(operation: "bootstrap.claim", requestID: id, owner: owner,
            fields: ["claim_token": FactorySetupValidation.hex(claimToken)], bootstrap: true)
        return try FactorySetupWire.decodeBootstrap(await send(data), requestID: id, binding: binding)
    }

    func bootstrapStatus() async throws -> FactoryBootstrapStatus {
        let id = UUID()
        let data = try FactorySetupWire.encodeRequest(operation: "bootstrap.status", requestID: id, owner: owner,
            fields: ["claim_request_id": owner.claimRequestID.uuidString.lowercased()], bootstrap: true)
        return try FactorySetupWire.decodeBootstrap(await send(data), requestID: id, binding: binding)
    }

    func negotiate() async throws -> FactorySetupNegotiation {
        guard !inFlight else { throw FactorySetupError.requestInProgress }
        negotiated = false
        latestOperationID = nil
        let id = UUID()
        let data = try FactorySetupWire.encodeRequest(operation: "system_setup.negotiate", requestID: id, owner: owner, fields: ["versions": [2]])
        let response = try await send(data)
        let result = try FactorySetupWire.decodeNegotiation(response, requestID: id)
        latestOperationID = result.latestOperationID
        negotiated = true
        return result
    }

    /// Explicit user action. Merely inspecting a remote status never invokes this method.
    @discardableResult
    func prepareOperation(country: String, supersedesOperationID: UUID? = nil) throws -> FactorySetupCheckpoint {
        try requireNegotiated()
        guard !inFlight, FactorySetupValidation.country(country) else { throw FactorySetupError.invalidMessage }
        let saved = try checkpoint()
        if let supersedesOperationID {
            // Discovery is readonly authority for which historical operation to supersede,
            // never authority to replay that operation's effects.
            guard latestOperationID == supersedesOperationID else { throw FactorySetupError.checkpointConflict }
        } else if let saved {
            guard saved.country == country,
                  latestOperationID == nil || latestOperationID == saved.operationID else { throw FactorySetupError.checkpointConflict }
            return saved
        } else if latestOperationID != nil {
            throw FactorySetupError.checkpointConflict
        }
        let fresh = FactorySetupCheckpoint(binding: binding, operationID: UUID(), country: country,
            supersedesOperationID: supersedesOperationID, challengeRequestID: UUID(), challenge: nil, applyIntent: nil)
        try checkpoints.save(fresh)
        return fresh
    }

    func challenge() async throws -> FactorySetupChallenge {
        try requireNegotiated()
        guard var saved = try checkpoint() else { throw FactorySetupError.missingCheckpoint }
        if let challenge = saved.challenge { return challenge }
        let data = try FactorySetupWire.encodeRequest(operation: "system_setup.challenge", requestID: saved.challengeRequestID, owner: owner,
            fields: ["op_id": saved.operationID.uuidString.lowercased(),
                     "supersedes_op_id": saved.supersedesOperationID.map { $0.uuidString.lowercased() as Any } ?? NSNull()])
        let response = try await send(data)
        let challenge = try FactorySetupWire.decodeChallenge(response, requestID: saved.challengeRequestID, operationID: saved.operationID)
        // Reject local replacement while the request was in flight, preserving the original checkpoint.
        guard try checkpoint() == saved else { throw FactorySetupError.checkpointConflict }
        saved.challenge = challenge
        try checkpoints.save(saved)
        latestOperationID = saved.operationID
        return challenge
    }

    func apply(utcSeconds: UInt64) async throws -> FactorySetupApplyAcknowledgement {
        try requireNegotiated()
        guard !inFlight, var saved = try checkpoint(), let challenge = saved.challenge else { throw FactorySetupError.missingCheckpoint }
        guard FactorySetupValidation.utc(utcSeconds) else { throw FactorySetupError.invalidMessage }
        if let intent = saved.applyIntent {
            guard intent.utcSeconds == utcSeconds else { throw FactorySetupError.checkpointConflict }
        } else {
            saved.applyIntent = FactorySetupApplyIntent(requestID: UUID(), utcSeconds: utcSeconds, country: saved.country, challenge: challenge)
            try checkpoints.save(saved)
        }
        return try await submit(saved)
    }

    func retryApply() async throws -> FactorySetupApplyAcknowledgement {
        try requireNegotiated()
        guard let saved = try checkpoint(), saved.applyIntent != nil else { throw FactorySetupError.missingCheckpoint }
        return try await submit(saved)
    }

    func status(operationID: UUID) async throws -> FactorySetupStatus {
        try requireNegotiated()
        let id = UUID()
        let data = try FactorySetupWire.encodeRequest(operation: "system_setup.status", requestID: id, owner: owner,
                                                       fields: ["op_id": operationID.uuidString.lowercased()])
        return try FactorySetupWire.decodeStatus(await send(data), requestID: id, operationID: operationID, binding: binding)
    }

    func continueSetup(operationID: UUID) async throws -> FactorySetupContinuation {
        try requireNegotiated()
        let id = UUID()
        let data = try FactorySetupWire.encodeRequest(operation: "system_setup.continue", requestID: id, owner: owner,
                                                       fields: ["op_id": operationID.uuidString.lowercased()])
        return try FactorySetupWire.decodeContinuation(await send(data), requestID: id, operationID: operationID, binding: binding)
    }

    private func submit(_ saved: FactorySetupCheckpoint) async throws -> FactorySetupApplyAcknowledgement {
        guard let intent = saved.applyIntent else { throw FactorySetupError.missingCheckpoint }
        let data = try FactorySetupWire.encodeRequest(operation: "system_setup.apply", requestID: intent.requestID, owner: owner,
            fields: ["op_id": saved.operationID.uuidString.lowercased(), "challenge_id": intent.challenge.challengeID.uuidString.lowercased(),
                     "nonce": FactorySetupValidation.hex(intent.challenge.nonce), "utc_seconds": intent.utcSeconds, "country": intent.country])
        return try FactorySetupWire.decodeApply(await send(data), requestID: intent.requestID, operationID: saved.operationID, binding: binding)
    }

    private func requireNegotiated() throws {
        try Task.checkCancellation()
        guard negotiated else { throw FactorySetupError.negotiationRequired }
    }

    private func send(_ data: Data) async throws -> Data {
        try Task.checkCancellation()
        guard !inFlight else { throw FactorySetupError.requestInProgress }
        inFlight = true
        defer { inFlight = false }
        let expectedGeneration = generation
        let reply = try await request(data, 20)
        try Task.checkCancellation()
        guard generation == expectedGeneration else { throw FactorySetupError.invalidated }
        return reply
    }
}

private indirect enum FactoryJSONValue {
    case object([String: FactoryJSONValue]), array([FactoryJSONValue]), string(String), integer(String), bool(Bool), null
}

/// Bounded recursive descent preserves number lexemes and rejects duplicate decoded keys before Foundation can collapse them.
private struct FactoryJSONParser {
    let bytes: [UInt8]
    private var index = 0
    init(bytes: [UInt8]) { self.bytes = bytes }
    mutating func parse() throws -> FactoryJSONValue {
        let parsed = try value(depth: 0)
        whitespace()
        guard index == bytes.count else { throw FactorySetupError.invalidMessage }
        return parsed
    }
    private var current: UInt8? { index < bytes.count ? bytes[index] : nil }
    private mutating func whitespace() { while let byte = current, [9, 10, 13, 32].contains(byte) { index += 1 } }
    private mutating func consume(_ byte: UInt8) throws {
        guard current == byte else { throw FactorySetupError.invalidMessage }; index += 1
    }
    private mutating func value(depth: Int) throws -> FactoryJSONValue {
        whitespace()
        switch current {
        case 123:
            guard depth < 32 else { throw FactorySetupError.invalidMessage }
            index += 1; whitespace()
            var result: [String: FactoryJSONValue] = [:]
            if current == 125 { index += 1; return .object(result) }
            while true {
                whitespace()
                let key = try string()
                guard result[key] == nil else { throw FactorySetupError.invalidMessage }
                whitespace(); try consume(58)
                result[key] = try value(depth: depth + 1)
                whitespace()
                if current == 125 { index += 1; return .object(result) }
                try consume(44)
            }
        case 91:
            guard depth < 32 else { throw FactorySetupError.invalidMessage }
            index += 1; whitespace()
            var result: [FactoryJSONValue] = []
            if current == 93 { index += 1; return .array(result) }
            while true {
                result.append(try value(depth: depth + 1)); whitespace()
                if current == 93 { index += 1; return .array(result) }
                try consume(44)
            }
        case 34: return .string(try string())
        case 116: try literal("true"); return .bool(true)
        case 102: try literal("false"); return .bool(false)
        case 110: try literal("null"); return .null
        default:
            let start = index
            if current == 45 { index += 1 }
            let digits = index
            while let byte = current, (48...57).contains(byte) { index += 1 }
            guard index > digits, index - digits == 1 || bytes[digits] != 48 else { throw FactorySetupError.invalidMessage }
            let token = String(decoding: bytes[start..<index], as: UTF8.self)
            guard token != "-0" else { throw FactorySetupError.invalidMessage }
            return .integer(token)
        }
    }
    private mutating func literal(_ value: String) throws { for byte in value.utf8 { try consume(byte) } }
    private mutating func string() throws -> String {
        let start = index
        try consume(34)
        while let byte = current {
            index += 1
            if byte == 92 {
                guard current != nil else { throw FactorySetupError.invalidMessage }; index += 1
            } else if byte == 34 {
                guard let value = try? JSONDecoder().decode(String.self, from: Data(bytes[start..<index])) else {
                    throw FactorySetupError.invalidMessage
                }; return value
            }
        }
        throw FactorySetupError.invalidMessage
    }
}
