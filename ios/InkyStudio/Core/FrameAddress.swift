import Foundation
import Darwin

enum FrameAddress {
    /// Normalize a frame origin. An omitted HTTP port means Inky Studio's 8000.
    static func parse(_ address: String) throws -> URL {
        let input = address.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !input.isEmpty, !input.contains(where: { $0.isWhitespace }) else {
            throw APIError.invalidAddress("Saisissez l’adresse du cadre, par exemple inkyold.local.")
        }
        var text = input
        if !text.contains("://") {
            // Bare IPv6 addresses have no unambiguous port. A port requires [host]:port.
            if !text.hasPrefix("["), text.filter({ $0 == ":" }).count > 1 {
                text = "[\(text)]"
            }
            text = "http://" + text
        }
        guard var parts = URLComponents(string: text),
              let scheme = parts.scheme?.lowercased(), ["http", "https"].contains(scheme),
              parts.user == nil, parts.password == nil,
              parts.query == nil, parts.fragment == nil,
              parts.path.isEmpty || parts.path == "/",
              let rawHost = parts.host, !rawHost.isEmpty else {
            throw APIError.invalidAddress("Utilisez une adresse HTTP ou HTTPS sans identifiant, chemin ni paramètres.")
        }
        let host = rawHost.trimmingCharacters(in: CharacterSet(charactersIn: "[]"))
        if host.contains(":") {
            // inet_pton validates IPv6; a scoped link-local address may also have %en0.
            let addressPart = String(host.split(separator: "%", maxSplits: 1)[0])
            var bytes = in6_addr()
            guard addressPart.withCString({ inet_pton(AF_INET6, $0, &bytes) }) == 1 else {
                throw APIError.invalidAddress("L’adresse IPv6 du cadre n’est pas valide.")
            }
        } else {
            let allowed = CharacterSet(charactersIn: "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-_")
            guard host.unicodeScalars.allSatisfy({ allowed.contains($0) }),
                  !host.hasPrefix("."), !host.contains("..") else {
                throw APIError.invalidAddress("Le nom ou l’adresse IP du cadre n’est pas valide.")
            }
            if host.allSatisfy({ $0.isNumber || $0 == "." }) {
                var bytes = in_addr()
                guard host.withCString({ inet_pton(AF_INET, $0, &bytes) }) == 1 else {
                    throw APIError.invalidAddress("L’adresse IPv4 du cadre n’est pas valide.")
                }
            }
        }
        let authority = text.components(separatedBy: "://").last?.split(separator: "/", omittingEmptySubsequences: false).first ?? ""
        guard !authority.hasSuffix(":"), parts.port.map({ (1...65535).contains($0) }) ?? true else {
            throw APIError.invalidAddress("Le port doit être compris entre 1 et 65535.")
        }
        parts.scheme = scheme
        parts.host = rawHost.lowercased()
        parts.path = ""
        if scheme == "http", parts.port == nil { parts.port = 8000 }
        if scheme == "https", parts.port == 443 { parts.port = nil }
        guard let url = parts.url else {
            throw APIError.invalidAddress("L’adresse du cadre n’est pas valide.")
        }
        return url
    }
}
