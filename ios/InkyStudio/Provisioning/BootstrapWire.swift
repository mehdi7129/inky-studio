import Foundation

/// Distinct provenance. No conversion to a normal adoption code or TLS policy.
struct BootstrapAdoptionCode: Equatable, Sendable {
    let identity: FrameIdentity
    let claimToken: Data
    static func parse(_ bytes: Data) throws -> Self {
        let fields = try BootstrapWire.object(bytes, maximum: 512)
        try BootstrapWire.keys(fields, ["v", "p", "id", "k", "t"])
        guard fields["v"] == .number("2"), fields["p"] == .string("bootstrap") else {
            throw BootstrapWireError.invalidRequest
        }
        return try Self(identity: FrameIdentity(id: BootstrapWire.uuid(fields["id"]),
            spkiSHA256: BootstrapWire.token(fields["k"])), claimToken: BootstrapWire.token(fields["t"]))
    }
}

enum FrameQRCode: Equatable, Sendable {
    case normal(FrameAdoptionCode), bootstrap(BootstrapAdoptionCode)
    static func parse(_ bytes: Data) throws -> Self {
        let fields = try BootstrapWire.object(bytes, maximum: 512)
        if fields["v"] == .number("1") {
            guard let text = String(data: bytes, encoding: .utf8) else { throw BootstrapWireError.invalidEncoding }
            do { return .normal(try FrameAdoptionCode.parse(text)) }
            catch { throw BootstrapWireError.invalidRequest }
        }
        return .bootstrap(try BootstrapAdoptionCode.parse(bytes))
    }
}

struct BootstrapPublicIdentity: Equatable, Sendable {
    let frameID: UUID
    let certificateLength: Int
    static func parse(_ data: Data) throws -> Self {
        let fields = try BootstrapWire.object(data, maximum: 128)
        try BootstrapWire.keys(fields, ["v", "p", "id", "cert_length"])
        guard fields["v"] == .number("2"), fields["p"] == .string("bootstrap"),
              case let .number(length)? = fields["cert_length"],
              length.utf8.allSatisfy({ (48...57).contains($0) }),
              let count = Int(length), (1...960).contains(count) else { throw BootstrapWireError.invalidRequest }
        return try Self(frameID: BootstrapWire.uuid(fields["id"]), certificateLength: count)
    }
}

/// Only the two lot A operations exist in this type; there is no arbitrary operation API.
struct BootstrapRequest: Equatable, Sendable {
    enum Operation: String, Sendable { case claim = "bootstrap.claim", status = "bootstrap.status" }
    let operation: Operation
    let id: UUID
    let ownerID: UUID
    let ownerToken: Data
    let proof: Data?
    let claimRequestID: UUID?

    static func parse(_ bytes: Data, operation: Operation) throws -> Self {
        let fields = try BootstrapWire.object(bytes)
        let extra = operation == .claim ? "claim_token" : "claim_request_id"
        try BootstrapWire.keys(fields, ["v", "id", "op", "owner_id", "owner_token", extra])
        guard fields["v"] == .number("1"), fields["op"] == .string(operation.rawValue) else {
            throw BootstrapWireError.invalidRequest
        }
        return try Self(operation: operation, id: BootstrapWire.uuid(fields["id"]),
            ownerID: BootstrapWire.uuid(fields["owner_id"]), ownerToken: BootstrapWire.token(fields["owner_token"]),
            proof: operation == .claim ? BootstrapWire.token(fields[extra]) : nil,
            claimRequestID: operation == .status ? BootstrapWire.uuid(fields[extra]) : nil)
    }

    func encoded() throws -> Data {
        var fields: [String: Any] = ["v": 1, "id": id.canonical, "op": operation.rawValue,
            "owner_id": ownerID.canonical, "owner_token": ownerToken.bootstrapHex]
        switch operation {
        case .claim:
            guard let proof else { throw BootstrapWireError.invalidRequest }
            fields["claim_token"] = proof.bootstrapHex
        case .status:
            guard let claimRequestID else { throw BootstrapWireError.invalidRequest }
            fields["claim_request_id"] = claimRequestID.canonical
        }
        let bytes = try JSONSerialization.data(withJSONObject: fields, options: [.sortedKeys])
        _ = try Self.parse(bytes, operation: operation)
        return bytes
    }
}

struct BootstrapResponseContext: Sendable {
    let rpcID: UUID?
    let frameID: UUID
    let ownerID: UUID
    let claimRequestID: UUID
}

enum BootstrapResponse: Equatable, Sendable {
    /// The association is durable; system preparation is still unavailable.
    case adoptedAwaitingPreparation
    case failure(BootstrapPublicError, correlated: Bool)
    static func parse(_ bytes: Data, context: BootstrapResponseContext) throws -> Self {
        let fields = try BootstrapWire.object(bytes)
        guard fields["v"] == .number("1") else { throw BootstrapWireError.invalidRequest }
        if fields["ok"] == .bool(true) {
            try BootstrapWire.keys(fields, ["v", "id", "ok", "result"])
            guard let rpc = context.rpcID, try BootstrapWire.uuid(fields["id"]) == rpc,
                  case let .object(result)? = fields["result"] else { throw BootstrapWireError.invalidRequest }
            try BootstrapWire.keys(result, ["frame_id", "owner_id", "claim_request_id", "factory_state", "next_step"])
            guard try BootstrapWire.uuid(result["frame_id"]) == context.frameID else {
                throw BootstrapWireError.identityMismatch
            }
            guard try BootstrapWire.uuid(result["owner_id"]) == context.ownerID,
                  try BootstrapWire.uuid(result["claim_request_id"]) == context.claimRequestID,
                  result["factory_state"] == .string("adopted"), result["next_step"] == .string("system_setup") else {
                throw BootstrapWireError.invalidRequest
            }
            return .adoptedAwaitingPreparation
        }
        try BootstrapWire.keys(fields, ["v", "id", "ok", "error"])
        guard fields["ok"] == .bool(false), case let .string(raw)? = fields["error"],
              let code = BootstrapPublicError(rawValue: raw) else { throw BootstrapWireError.invalidRequest }
        if fields["id"] == .null { return .failure(code, correlated: false) }
        guard let rpc = context.rpcID, try BootstrapWire.uuid(fields["id"]) == rpc else {
            throw BootstrapWireError.invalidRequest
        }
        return .failure(code, correlated: true)
    }
}

enum BootstrapPublicError: String, Error, Sendable, CaseIterable {
    case invalidRequest = "invalid_request", unauthorized, qrUnavailable = "qr_unavailable"
    case requestConflict = "request_conflict", requestNotFound = "request_not_found", epochChanged = "epoch_changed"
    case ownerCapacity = "owner_capacity", rateLimited = "rate_limited", serviceStopping = "service_stopping"
    case recoveryRequired = "recovery_required", unavailable
}

enum BootstrapWireError: String, Error, Equatable, Sendable {
    case invalidRequest = "invalid_request", invalidEncoding = "invalid_encoding", sizeLimit = "size_limit"
    case identityMismatch = "identity_mismatch"
}

extension UUID { fileprivate var canonical: String { uuidString.lowercased() } }
extension Data {
    var bootstrapHex: String { map { String(format: "%02x", $0) }.joined() }
    static func bootstrapHexBytes(_ text: String) -> Data? {
        let bytes = Array(text.utf8)
        guard bytes.count.isMultiple(of: 2), bytes.allSatisfy({ (48...57).contains($0) || (97...102).contains($0) }) else { return nil }
        func digit(_ byte: UInt8) -> UInt8 { byte <= 57 ? byte - 48 : byte - 87 }
        return Data(stride(from: 0, to: bytes.count, by: 2).map { digit(bytes[$0]) * 16 + digit(bytes[$0 + 1]) })
    }
}

/// Preserve number lexemes and reject duplicates (including escaped names) before
/// schema decoding. Input bytes, depth and strings are bounded by the input cap.
/// No Foundation dictionary roundtrip can erase security-relevant raw grammar.
enum BootstrapWire {
    indirect enum Value: Equatable {
        case object([String: Value]), array([Value]), string(String), number(String), bool(Bool), null
    }
    static func object(_ bytes: Data, maximum: Int = 16_384) throws -> [String: Value] {
        guard (1...maximum).contains(bytes.count) else { throw BootstrapWireError.sizeLimit }
        guard String(data: bytes, encoding: .utf8) != nil else { throw BootstrapWireError.invalidEncoding }
        var parser = Parser(bytes: Array(bytes))
        let value = try parser.parse()
        guard case let .object(fields) = value else { throw BootstrapWireError.invalidRequest }
        return fields
    }
    static func keys(_ fields: [String: Value], _ keys: Set<String>) throws {
        guard Set(fields.keys) == keys else { throw BootstrapWireError.invalidRequest }
    }
    static func uuid(_ value: Value?) throws -> UUID {
        guard case let .string(text)? = value, text.utf8.count == 36,
              let identifier = UUID(uuidString: text), identifier.canonical == text else { throw BootstrapWireError.invalidRequest }
        return identifier
    }
    static func token(_ value: Value?) throws -> Data {
        guard case let .string(text)? = value, text.utf8.count == 64,
              let data = Data.bootstrapHexBytes(text) else { throw BootstrapWireError.invalidRequest }
        return data
    }

    private struct Parser {
        let bytes: [UInt8]
        var index = 0
        var current: UInt8? { index < bytes.count ? bytes[index] : nil }
        mutating func whitespace() { while let byte = current, [9, 10, 13, 32].contains(byte) { index += 1 } }
        mutating func consume(_ byte: UInt8) throws {
            guard current == byte else { throw BootstrapWireError.invalidRequest }
            index += 1
        }
        mutating func parse() throws -> Value {
            whitespace()
            let result = try value(depth: 1)
            whitespace()
            guard index == bytes.count else { throw BootstrapWireError.invalidRequest }
            return result
        }
        mutating func value(depth: Int) throws -> Value {
            whitespace()
            switch current {
            case 123:
                guard depth <= 32 else { throw BootstrapWireError.invalidRequest }
                index += 1; whitespace()
                var fields: [String: Value] = [:]
                if current == 125 { index += 1; return .object(fields) }
                while true {
                    whitespace()
                    let key = try string()
                    guard fields[key] == nil else { throw BootstrapWireError.invalidRequest }
                    whitespace(); try consume(58)
                    fields[key] = try value(depth: depth + 1)
                    whitespace()
                    if current == 125 { index += 1; return .object(fields) }
                    try consume(44)
                }
            case 91:
                guard depth <= 32 else { throw BootstrapWireError.invalidRequest }
                index += 1; whitespace()
                var items: [Value] = []
                if current == 93 { index += 1; return .array(items) }
                while true {
                    items.append(try value(depth: depth + 1)); whitespace()
                    if current == 93 { index += 1; return .array(items) }
                    try consume(44)
                }
            case 34: return .string(try string())
            case 116: try literal("true"); return .bool(true)
            case 102: try literal("false"); return .bool(false)
            case 110: try literal("null"); return .null
            default: return .number(try number())
            }
        }
        mutating func literal(_ text: String) throws { for byte in text.utf8 { try consume(byte) } }
        mutating func string() throws -> String {
            let start = index
            try consume(34)
            while let byte = current {
                guard byte >= 32 else { throw BootstrapWireError.invalidRequest }
                index += 1
                if byte == 92 {
                    guard current != nil else { throw BootstrapWireError.invalidRequest }
                    index += 1
                } else if byte == 34 {
                    guard let result = try? JSONDecoder().decode(String.self, from: Data(bytes[start..<index])) else {
                        throw BootstrapWireError.invalidRequest
                    }
                    return result
                }
            }
            throw BootstrapWireError.invalidRequest
        }
        mutating func number() throws -> String {
            let start = index
            if current == 45 { index += 1 }
            guard let first = current, (48...57).contains(first) else { throw BootstrapWireError.invalidRequest }
            index += 1
            if first != 48 { while let byte = current, (48...57).contains(byte) { index += 1 } }
            if current == 46 { index += 1; try digits() }
            if current == 101 || current == 69 {
                index += 1
                if current == 43 || current == 45 { index += 1 }
                try digits()
            }
            return String(decoding: bytes[start..<index], as: UTF8.self)
        }
        mutating func digits() throws {
            let start = index
            while let byte = current, (48...57).contains(byte) { index += 1 }
            guard index > start else { throw BootstrapWireError.invalidRequest }
        }
    }
}
