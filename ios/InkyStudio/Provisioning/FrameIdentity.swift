import Foundation

/// A frame's physical QR establishes this identity independently of its network address.
struct FrameIdentity: Equatable, Codable, Sendable {
    let id: UUID
    let spkiSHA256: Data

    var expectedServerName: String { "frame-\(id.uuidString.lowercased()).inky.invalid" }

    init(id: UUID, spkiSHA256: Data) throws {
        guard spkiSHA256.count == 32 else { throw FrameIdentityError.invalidQRCode }
        self.id = id
        self.spkiSHA256 = spkiSHA256
    }

    private enum CodingKeys: String, CodingKey { case id, spkiSHA256 }
    init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        try self.init(id: values.decode(UUID.self, forKey: .id),
                      spkiSHA256: values.decode(Data.self, forKey: .spkiSHA256))
    }
}

/// The adoption token is secret. Never display, log, persist, or open this code as a URL.
struct FrameAdoptionCode: Equatable, Sendable {
    let identity: FrameIdentity
    let adoptionToken: Data

    static func parse(_ text: String) throws -> FrameAdoptionCode {
        guard text.utf8.count <= 512 else { throw FrameIdentityError.invalidQRCode }
        var parser = QRObjectParser(bytes: Array(text.utf8))
        let fields = try parser.parse()
        guard Set(fields.keys) == ["v", "id", "k", "t"],
              case let .number(version) = fields["v"] else { throw FrameIdentityError.invalidQRCode }
        guard version == "1" else { throw FrameIdentityError.unsupportedVersion }
        guard case let .string(identifier) = fields["id"],
              identifier.count == 36, let id = UUID(uuidString: identifier),
              id.uuidString.lowercased() == identifier.lowercased(),
              case let .string(pin) = fields["k"], let pinBytes = hexBytes(pin),
              case let .string(token) = fields["t"], let tokenBytes = hexBytes(token) else {
            throw FrameIdentityError.invalidQRCode
        }
        return try FrameAdoptionCode(identity: FrameIdentity(id: id, spkiSHA256: pinBytes),
                                     adoptionToken: tokenBytes)
    }

    private static func hexBytes(_ value: String) -> Data? {
        let bytes = Array(value.utf8)
        guard bytes.count == 64 else { return nil }
        func digit(_ value: UInt8) -> UInt8? {
            switch value {
            case 48...57: return value - 48
            case 97...102: return value - 87
            default: return nil
            }
        }
        var result = Data(capacity: 32)
        for index in stride(from: 0, to: bytes.count, by: 2) {
            guard let high = digit(bytes[index]), let low = digit(bytes[index + 1]) else { return nil }
            result.append(high * 16 + low)
        }
        return result
    }
}

/// Foundation's object decoders accept duplicate keys. Parse the small envelope first
/// so duplicate (including escaped) field names cannot overwrite security inputs.
private struct QRObjectParser {
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
            guard ["v", "id", "k", "t"].contains(key), fields[key] == nil else {
                throw FrameIdentityError.invalidQRCode
            }
            skipWhitespace()
            try consume(58)
            skipWhitespace()
            if current == 34 {
                fields[key] = .string(try string())
            } else {
                let start = index
                while let byte = current, (48...57).contains(byte) { index += 1 }
                guard index > start else { throw FrameIdentityError.invalidQRCode }
                let number = String(decoding: bytes[start..<index], as: UTF8.self)
                guard number.count == 1 || !number.hasPrefix("0") else { throw FrameIdentityError.invalidQRCode }
                fields[key] = .number(number)
            }
            skipWhitespace()
            if current == 125 { index += 1; break }
            try consume(44)
        } while true
        skipWhitespace()
        guard index == bytes.count else { throw FrameIdentityError.invalidQRCode }
        return fields
    }

    private var current: UInt8? { index < bytes.count ? bytes[index] : nil }
    private mutating func skipWhitespace() {
        while let byte = current, [9, 10, 13, 32].contains(byte) { index += 1 }
    }
    private mutating func consume(_ expected: UInt8) throws {
        guard current == expected else { throw FrameIdentityError.invalidQRCode }
        index += 1
    }
    private mutating func string() throws -> String {
        let start = index
        try consume(34)
        while let byte = current {
            index += 1
            if byte == 92 {
                guard current != nil else { throw FrameIdentityError.invalidQRCode }
                index += 1
            } else if byte == 34 {
                guard let result = try? JSONDecoder().decode(String.self, from: Data(bytes[start..<index])) else {
                    throw FrameIdentityError.invalidQRCode
                }
                return result
            }
        }
        throw FrameIdentityError.invalidQRCode
    }
}

enum FrameIdentityError: Error, LocalizedError, Equatable, Sendable {
    case invalidQRCode, unsupportedVersion, invalidCertificate, unsupportedKey
    case pinMismatch, certificateRejected, insecureEndpoint, invalidEndpoint

    var errorDescription: String? {
        switch self {
        case .invalidQRCode: return "Ce QR de cadre n’est pas valide. Scannez le code affiché sur le cadre."
        case .unsupportedVersion: return "Ce QR nécessite une autre version d’Inky Studio."
        case .invalidCertificate, .unsupportedKey: return "L’identité reçue du cadre n’est pas compatible."
        case .pinMismatch: return "L’identité du cadre ne correspond pas au QR. Aucun secret n’a été envoyé."
        case .certificateRejected: return "Le certificat du cadre n’est pas valide. Vérifiez la date de l’iPhone puis scannez à nouveau le QR du cadre."
        case .insecureEndpoint: return "Ce cadre adopté nécessite une connexion HTTPS."
        case .invalidEndpoint: return "L’adresse sécurisée du cadre n’est pas valide."
        }
    }
}
