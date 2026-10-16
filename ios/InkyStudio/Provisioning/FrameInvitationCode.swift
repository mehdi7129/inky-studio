import Foundation

/// An expiring PHOTO invitation. Its pin is scanned from the owner's iPhone;
/// it grants no Bluetooth ownership or permission to configure the frame.
/// Never log the payload or open it as a URL. A recipient keeps its invitation
/// token in RAM only; an issuer's separate pending operation may retain the
/// token briefly in protected Keychain storage for an identical request retry.
struct FrameInvitationCode: Equatable, Sendable {
    let identity: FrameIdentity
    let endpoint: URL
    let invitationID: UUID
    let invitationToken: String

    init(identity: FrameIdentity, endpoint: URL, invitationID: UUID, invitationToken: String) throws {
        guard Self.hex(invitationToken) != nil,
              let checkedEndpoint = Self.httpsOrigin(endpoint.absoluteString) else {
            throw InvitationCodeError.invalidCode
        }
        self.identity = identity
        self.endpoint = checkedEndpoint
        self.invitationID = invitationID
        self.invitationToken = invitationToken
    }

    static func parse(_ text: String) throws -> FrameInvitationCode {
        guard text.utf8.count <= 1024 else { throw InvitationCodeError.invalidCode }
        var parser = InvitationObjectParser(bytes: Array(text.utf8))
        let fields = try parser.parse()
        guard Set(fields.keys) == ["v", "p", "id", "k", "url", "i", "t"],
              case .number("1") = fields["v"], case .string("invite") = fields["p"],
              case let .string(frameID) = fields["id"], let id = canonicalUUID(frameID),
              case let .string(pin) = fields["k"], let pinBytes = hex(pin),
              case let .string(address) = fields["url"], let endpoint = httpsOrigin(address),
              case let .string(invitationID) = fields["i"], let invitation = canonicalUUID(invitationID),
              case let .string(token) = fields["t"], hex(token) != nil else {
            throw InvitationCodeError.invalidCode
        }
        return try FrameInvitationCode(identity: FrameIdentity(id: id, spkiSHA256: pinBytes),
                                       endpoint: endpoint, invitationID: invitation, invitationToken: token)
    }

    func encodedPayload() throws -> String {
        let object: [String: Any] = [
            "v": 1, "p": "invite", "id": identity.id.uuidString.lowercased(),
            "k": identity.spkiSHA256.map { String(format: "%02x", $0) }.joined(),
            "url": endpoint.absoluteString, "i": invitationID.uuidString.lowercased(), "t": invitationToken
        ]
        let data = try JSONSerialization.data(withJSONObject: object, options: [.sortedKeys, .withoutEscapingSlashes])
        guard data.count <= 1024 else { throw InvitationCodeError.invalidCode }
        return String(decoding: data, as: UTF8.self)
    }

    private static func canonicalUUID(_ text: String) -> UUID? {
        guard text.utf8.count == 36, let value = UUID(uuidString: text),
              value.uuidString.lowercased() == text else { return nil }
        return value
    }

    private static func hex(_ text: String) -> Data? {
        let bytes = Array(text.utf8)
        guard bytes.count == 64, bytes.allSatisfy({ (48...57).contains($0) || (97...102).contains($0) }) else { return nil }
        var result = Data(capacity: 32)
        for index in stride(from: 0, to: bytes.count, by: 2) {
            func digit(_ byte: UInt8) -> UInt8 { byte <= 57 ? byte - 48 : byte - 87 }
            result.append(digit(bytes[index]) * 16 + digit(bytes[index + 1]))
        }
        return result
    }

    private static func httpsOrigin(_ text: String) -> URL? {
        guard text.hasPrefix("https://") else { return nil }
        let authority = text.dropFirst(8)
        let allowed = Set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.[]:-".utf8)
        guard (1...259).contains(authority.utf8.count),
              authority.utf8.allSatisfy({ allowed.contains($0) }), !authority.hasSuffix(":"),
              let endpoint = URL(string: text),
              let parts = URLComponents(string: text), let host = parts.host, !host.isEmpty,
              parts.user == nil, parts.password == nil, parts.path.isEmpty,
              parts.query == nil, parts.fragment == nil,
              parts.port.map({ (1...65535).contains($0) }) ?? true,
              (try? FrameAddress.parse(text)) != nil else { return nil }
        return endpoint
    }
}

enum InvitationCodeError: Error, LocalizedError, Equatable, Sendable {
    case invalidCode
    var errorDescription: String? {
        "Ce QR d’invitation n’est pas valide. Demandez au propriétaire de générer une nouvelle invitation."
    }
}

/// Keep the invitation envelope independent from legacy login and adoption.
/// Decode strings only after rejecting duplicate keys, including escaped names.
private struct InvitationObjectParser {
    enum Value { case string(String), number(String) }
    let bytes: [UInt8]
    private var index = 0
    init(bytes: [UInt8]) { self.bytes = bytes }

    mutating func parse() throws -> [String: Value] {
        skipWhitespace()
        try consume(123)
        var fields: [String: Value] = [:]
        repeat {
            skipWhitespace()
            let key = try string()
            guard ["v", "p", "id", "k", "url", "i", "t"].contains(key), fields[key] == nil else { throw InvitationCodeError.invalidCode }
            skipWhitespace()
            try consume(58)
            skipWhitespace()
            if current == 34 { fields[key] = .string(try string()) }
            else {
                let start = index
                while let byte = current, (48...57).contains(byte) { index += 1 }
                guard index > start else { throw InvitationCodeError.invalidCode }
                let number = String(decoding: bytes[start..<index], as: UTF8.self)
                guard number.count == 1 || !number.hasPrefix("0") else { throw InvitationCodeError.invalidCode }
                fields[key] = .number(number)
            }
            skipWhitespace()
            if current == 125 { index += 1; break }
            try consume(44)
        } while true
        skipWhitespace()
        guard index == bytes.count else { throw InvitationCodeError.invalidCode }
        return fields
    }

    private var current: UInt8? { index < bytes.count ? bytes[index] : nil }
    private mutating func skipWhitespace() { while let byte = current, [9, 10, 13, 32].contains(byte) { index += 1 } }
    private mutating func consume(_ byte: UInt8) throws {
        guard current == byte else { throw InvitationCodeError.invalidCode }
        index += 1
    }
    private mutating func string() throws -> String {
        let start = index
        try consume(34)
        while let byte = current {
            index += 1
            if byte == 92 {
                guard current != nil else { throw InvitationCodeError.invalidCode }
                index += 1
            } else if byte == 34 {
                guard let value = try? JSONDecoder().decode(String.self, from: Data(bytes[start..<index])) else { throw InvitationCodeError.invalidCode }
                return value
            }
        }
        throw InvitationCodeError.invalidCode
    }
}
