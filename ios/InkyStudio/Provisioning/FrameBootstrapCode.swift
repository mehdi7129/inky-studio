import Foundation

/// Factory bootstrap authority is distinct from the normal v1 adoption QR.
/// Keep the token in memory only; never log it or interpret this object as a URL.
struct FrameBootstrapCode: Equatable, Sendable {
    let identity: FrameIdentity
    let adoptionToken: Data

    init(identity: FrameIdentity, adoptionToken: Data) throws {
        guard adoptionToken.count == 32 else { throw FrameIdentityError.invalidQRCode }
        self.identity = identity
        self.adoptionToken = adoptionToken
    }

    static func parse(_ text: String) throws -> Self {
        guard text.utf8.count <= 512 else { throw FrameIdentityError.invalidQRCode }
        let fields = try BootstrapFlatObject.parse(Data(text.utf8), maximum: 512,
                                                   keys: ["v", "p", "id", "k", "t"])
        guard case .integer("2") = fields["v"], case .string("bootstrap") = fields["p"],
              case let .string(identifier) = fields["id"], let id = BootstrapFlatObject.uuid(identifier),
              case let .string(pin) = fields["k"], let pinBytes = BootstrapFlatObject.hex(pin),
              case let .string(token) = fields["t"], let tokenBytes = BootstrapFlatObject.hex(token) else {
            throw FrameIdentityError.invalidQRCode
        }
        return try Self(identity: FrameIdentity(id: id, spkiSHA256: pinBytes), adoptionToken: tokenBytes)
    }
}

/// A closed flat envelope, bounded before parsing. Preserve integer lexemes and
/// reject duplicate decoded names, including escaped duplicates.
enum BootstrapFlatObject {
    enum Value { case string(String), integer(String) }

    static func parse(_ data: Data, maximum: Int, keys: Set<String>) throws -> [String: Value] {
        guard !data.isEmpty, data.count <= maximum else { throw FrameIdentityError.invalidQRCode }
        var parser = Parser(bytes: Array(data), keys: keys)
        return try parser.parse()
    }

    static func uuid(_ text: String) -> UUID? {
        guard text.utf8.count == 36, let id = UUID(uuidString: text), id.uuidString.lowercased() == text else { return nil }
        return id
    }

    static func hex(_ text: String) -> Data? {
        let bytes = Array(text.utf8)
        guard bytes.count == 64, bytes.allSatisfy({ (48...57).contains($0) || (97...102).contains($0) }) else { return nil }
        func digit(_ byte: UInt8) -> UInt8 { byte <= 57 ? byte - 48 : byte - 87 }
        return Data(stride(from: 0, to: bytes.count, by: 2).map { digit(bytes[$0]) * 16 + digit(bytes[$0 + 1]) })
    }

    private struct Parser {
        let bytes: [UInt8]
        let keys: Set<String>
        private var index = 0

        init(bytes: [UInt8], keys: Set<String>) { self.bytes = bytes; self.keys = keys }
        private var current: UInt8? { index < bytes.count ? bytes[index] : nil }
        private mutating func whitespace() { while let byte = current, [9, 10, 13, 32].contains(byte) { index += 1 } }
        private mutating func consume(_ byte: UInt8) throws {
            guard current == byte else { throw FrameIdentityError.invalidQRCode }
            index += 1
        }
        mutating func parse() throws -> [String: Value] {
            whitespace()
            try consume(123)
            var fields: [String: Value] = [:]
            while true {
                whitespace()
                let name = try string()
                guard keys.contains(name), fields[name] == nil else { throw FrameIdentityError.invalidQRCode }
                whitespace(); try consume(58); whitespace()
                if current == 34 { fields[name] = .string(try string()) }
                else {
                    let start = index
                    while let byte = current, (48...57).contains(byte) { index += 1 }
                    guard index > start else { throw FrameIdentityError.invalidQRCode }
                    let integer = String(decoding: bytes[start..<index], as: UTF8.self)
                    guard integer.count == 1 || !integer.hasPrefix("0") else { throw FrameIdentityError.invalidQRCode }
                    fields[name] = .integer(integer)
                }
                whitespace()
                if current == 125 { index += 1; break }
                try consume(44)
            }
            whitespace()
            guard index == bytes.count, Set(fields.keys) == keys else { throw FrameIdentityError.invalidQRCode }
            return fields
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
                    guard let value = try? JSONDecoder().decode(String.self, from: Data(bytes[start..<index])) else {
                        throw FrameIdentityError.invalidQRCode
                    }
                    return value
                }
            }
            throw FrameIdentityError.invalidQRCode
        }
    }
}
