import Foundation

/// A legacy LAN login, not an adoption or factory QR. The password stays in memory.
struct FrameLANLoginCode: Sendable {
    let endpoint: URL
    let password: String

    private init(endpoint: URL, password: String) {
        self.endpoint = endpoint
        self.password = password
    }

    static func parse(_ text: String) throws -> FrameLANLoginCode {
        guard text.utf8.count <= 512 else { throw LANLoginCodeError.invalidCode }
        var parser = LANLoginObjectParser(bytes: Array(text.utf8))
        let fields = try parser.parse()
        guard Set(fields.keys) == ["v", "p", "url", "password"],
              case .number("1") = fields["v"],
              case .string("lan-login") = fields["p"],
              case let .string(address) = fields["url"],
              case let .string(password) = fields["password"],
              (1...128).contains(password.utf8.count),
              password.utf8.allSatisfy({ (33...126).contains($0) }),
              let endpoint = localEndpoint(address) else { throw LANLoginCodeError.invalidCode }
        return FrameLANLoginCode(endpoint: endpoint, password: password)
    }

    private static func localEndpoint(_ address: String) -> URL? {
        // Version 1 is emitted only for this backend's HTTP listener on a private
        // IPv4 LAN. Do not expand manual FrameAddress parsing or follow QR URLs.
        guard let parts = URLComponents(string: address), parts.scheme == "http",
              parts.port == 8000, parts.user == nil, parts.password == nil,
              parts.path.isEmpty, parts.query == nil, parts.fragment == nil,
              let host = parts.host else { return nil }
        let labels = host.split(separator: ".", omittingEmptySubsequences: false)
        guard labels.count == 4 else { return nil }
        var octets: [UInt8] = []
        for label in labels {
            guard !label.isEmpty, label.utf8.allSatisfy({ (48...57).contains($0) }),
                  let value = UInt8(label), String(value) == label else { return nil }
            octets.append(value)
        }
        let privateLAN = octets[0] == 10 ||
            (octets[0] == 172 && (16...31).contains(octets[1])) ||
            (octets[0] == 192 && octets[1] == 168)
        guard privateLAN, address == "http://\(host):8000" else { return nil }
        return parts.url
    }
}

enum LANLoginCodeError: Error, LocalizedError, Equatable, Sendable {
    case invalidCode, adoptedFrame

    var errorDescription: String? {
        switch self {
        case .invalidCode:
            return "Ce QR de connexion n’est pas valide. Scannez le QR de l’écran d’accueil du cadre."
        case .adoptedFrame:
            return "Ce cadre est déjà associé à cet iPhone. Utilisez sa connexion sécurisée habituelle."
        }
    }
}

/// Reject duplicate keys, including escaped spellings, before decoding values.
/// Keep this envelope separate from the adoption QR parser and its trust inputs.
private struct LANLoginObjectParser {
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
            guard ["v", "p", "url", "password"].contains(key), fields[key] == nil else {
                throw LANLoginCodeError.invalidCode
            }
            skipWhitespace()
            try consume(58)
            skipWhitespace()
            if current == 34 {
                fields[key] = .string(try string())
            } else {
                let start = index
                while let byte = current, (48...57).contains(byte) { index += 1 }
                guard index > start else { throw LANLoginCodeError.invalidCode }
                let number = String(decoding: bytes[start..<index], as: UTF8.self)
                guard number.count == 1 || !number.hasPrefix("0") else { throw LANLoginCodeError.invalidCode }
                fields[key] = .number(number)
            }
            skipWhitespace()
            if current == 125 { index += 1; break }
            try consume(44)
        } while true
        skipWhitespace()
        guard index == bytes.count else { throw LANLoginCodeError.invalidCode }
        return fields
    }

    private var current: UInt8? { index < bytes.count ? bytes[index] : nil }
    private mutating func skipWhitespace() {
        while let byte = current, [9, 10, 13, 32].contains(byte) { index += 1 }
    }
    private mutating func consume(_ expected: UInt8) throws {
        guard current == expected else { throw LANLoginCodeError.invalidCode }
        index += 1
    }
    private mutating func string() throws -> String {
        let start = index
        try consume(34)
        while let byte = current {
            index += 1
            if byte == 92 {
                guard current != nil else { throw LANLoginCodeError.invalidCode }
                index += 1
            } else if byte == 34 {
                guard let value = try? JSONDecoder().decode(String.self, from: Data(bytes[start..<index])) else {
                    throw LANLoginCodeError.invalidCode
                }
                return value
            }
        }
        throw LANLoginCodeError.invalidCode
    }
}
