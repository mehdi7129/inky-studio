import CryptoKit
import Foundation

/// This capability can only be constructed after the nonce-bound MAC is verified.
/// It conveys TLS identity, never Bluetooth ownership or an authenticated session.
struct VerifiedLegacyTLSEndpoint: Equatable, Sendable {
    let identity: FrameIdentity
    let endpoint: URL

    fileprivate init(identity: FrameIdentity, endpoint: URL) {
        self.identity = identity
        self.endpoint = endpoint
    }
}

enum LegacyTLSProofError: Error, LocalizedError, Equatable, Sendable {
    case unavailable
    var errorDescription: String? {
        "La connexion sécurisée n’est pas disponible pour ce cadre. Votre accès actuel est conservé."
    }
}

enum LegacyTLSProofVerifier {
    static let maximumResponseBytes = 2048

    static func verify(response: Data, expectedNonce: Data,
                       bootstrapPassword: String) throws -> VerifiedLegacyTLSEndpoint {
        guard validBootstrapPassword(bootstrapPassword), expectedNonce.count == 32,
              response.count <= maximumResponseBytes else { throw LegacyTLSProofError.unavailable }
        var parser = LegacyProofObjectParser(bytes: Array(response))
        let fields = try parser.parse()
        guard Set(fields.keys) == ["v", "nonce", "identity", "proof"],
              case .number("1") = fields["v"],
              case let .string(nonceText) = fields["nonce"], let nonce = hex(nonceText), nonce == expectedNonce,
              case let .object(identity) = fields["identity"],
              Set(identity.keys) == ["frame_id", "spki_sha256", "url"],
              case let .string(frameText) = identity["frame_id"],
              frameText.utf8.count == 36, let frameID = UUID(uuidString: frameText),
              frameID.uuidString.lowercased() == frameText,
              case let .string(pinText) = identity["spki_sha256"], let pin = hex(pinText),
              case let .string(rawURL) = identity["url"], let endpoint = strictHTTPSOrigin(rawURL),
              case let .string(proofText) = fields["proof"], let proof = hex(proofText) else {
            throw LegacyTLSProofError.unavailable
        }
        // Use the exact decoded URL string's UTF-8, never endpoint.absoluteString.
        let message = try authenticationMessage(nonce: nonce, frameID: frameID, spki: pin, exactURL: rawURL)
        let key = SymmetricKey(data: Data(bootstrapPassword.utf8))
        guard HMAC<SHA256>.isValidAuthenticationCode(proof, authenticating: message, using: key) else {
            throw LegacyTLSProofError.unavailable
        }
        return try VerifiedLegacyTLSEndpoint(identity: FrameIdentity(id: frameID, spkiSHA256: pin), endpoint: endpoint)
    }

    /// Internal for independent protocol vectors; all bytes are public except the HMAC key.
    static func authenticationMessage(nonce: Data, frameID: UUID, spki: Data, exactURL: String) throws -> Data {
        let url = Data(exactURL.utf8)
        guard nonce.count == 32, spki.count == 32, url.count <= Int(UInt16.max) else {
            throw LegacyTLSProofError.unavailable
        }
        var message = Data("inky-legacy-tls-proof-v1\0".utf8)
        message.append(nonce)
        var rfcUUID = frameID.uuid
        withUnsafeBytes(of: &rfcUUID) { message.append(contentsOf: $0) }
        message.append(spki)
        message.append(UInt8(url.count >> 8))
        message.append(UInt8(url.count & 255))
        message.append(url)
        return message
    }

    static func validBootstrapPassword(_ value: String) -> Bool {
        let bytes = Array(value.utf8)
        return bytes.count == 16 && bytes.allSatisfy {
            (48...57).contains($0) || (65...90).contains($0) || (97...122).contains($0)
        }
    }

    static func hex(_ text: String) -> Data? {
        let bytes = Array(text.utf8)
        guard bytes.count == 64, bytes.allSatisfy({ (48...57).contains($0) || (97...102).contains($0) }) else { return nil }
        var data = Data(capacity: 32)
        for index in stride(from: 0, to: bytes.count, by: 2) {
            func digit(_ byte: UInt8) -> UInt8 { byte <= 57 ? byte - 48 : byte - 87 }
            data.append(digit(bytes[index]) * 16 + digit(bytes[index + 1]))
        }
        return data
    }

    private static func strictHTTPSOrigin(_ text: String) -> URL? {
        guard text.hasPrefix("https://") else { return nil }
        let authority = text.dropFirst(8)
        let allowed = Set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.[]:-".utf8)
        guard (1...259).contains(authority.utf8.count), authority.utf8.allSatisfy({ allowed.contains($0) }),
              !authority.hasSuffix(":"), let parts = URLComponents(string: text),
              let host = parts.host, !host.isEmpty, parts.user == nil, parts.password == nil,
              parts.path.isEmpty, parts.query == nil, parts.fragment == nil,
              parts.port.map({ (1...65535).contains($0) }) ?? true,
              (try? FrameAddress.parse(text)) != nil else { return nil }
        return parts.url
    }
}

/// Closed, bounded grammar rejects duplicates before Foundation can collapse them.
/// Only the root and its one identity object are permitted; values are strings or integer tokens.
private struct LegacyProofObjectParser {
    enum Value { case string(String), number(String), object([String: Value]) }
    let bytes: [UInt8]
    private var index = 0
    init(bytes: [UInt8]) { self.bytes = bytes }

    mutating func parse() throws -> [String: Value] {
        let result = try object(identity: false)
        whitespace()
        guard index == bytes.count else { throw LegacyTLSProofError.unavailable }
        return result
    }

    private mutating func object(identity: Bool) throws -> [String: Value] {
        whitespace()
        try consume(123)
        whitespace()
        var result: [String: Value] = [:]
        let allowed: Set<String> = identity ? ["frame_id", "spki_sha256", "url"] : ["v", "nonce", "identity", "proof"]
        if current == 125 { index += 1; return result }
        while true {
            whitespace()
            let name = try string()
            guard allowed.contains(name), result[name] == nil else { throw LegacyTLSProofError.unavailable }
            whitespace()
            try consume(58)
            whitespace()
            if !identity && name == "identity" {
                result[name] = .object(try object(identity: true))
            } else if current == 34 {
                result[name] = .string(try string())
            } else {
                let start = index
                while let byte = current, (48...57).contains(byte) { index += 1 }
                guard index > start else { throw LegacyTLSProofError.unavailable }
                let value = String(decoding: bytes[start..<index], as: UTF8.self)
                guard value.count == 1 || !value.hasPrefix("0") else { throw LegacyTLSProofError.unavailable }
                result[name] = .number(value)
            }
            whitespace()
            if current == 125 { index += 1; return result }
            try consume(44)
        }
    }

    private var current: UInt8? { index < bytes.count ? bytes[index] : nil }
    private mutating func whitespace() { while let byte = current, [9, 10, 13, 32].contains(byte) { index += 1 } }
    private mutating func consume(_ byte: UInt8) throws {
        guard current == byte else { throw LegacyTLSProofError.unavailable }
        index += 1
    }
    private mutating func string() throws -> String {
        let start = index
        try consume(34)
        while let byte = current {
            index += 1
            if byte == 92 {
                guard current != nil else { throw LegacyTLSProofError.unavailable }
                index += 1
            } else if byte == 34 {
                guard let value = try? JSONDecoder().decode(String.self, from: Data(bytes[start..<index])) else {
                    throw LegacyTLSProofError.unavailable
                }
                return value
            }
        }
        throw LegacyTLSProofError.unavailable
    }
}
