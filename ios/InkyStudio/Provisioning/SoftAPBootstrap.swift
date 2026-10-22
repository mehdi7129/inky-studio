import Foundation

/// The locator and AP credential are transport hints only. The physical SPKI
/// remains the authority, including after the bootstrap certificate is renewed.
struct SoftAPDescriptor: Equatable, Sendable {
    static let endpoint = URL(string: "tcp://192.168.4.1:9443")!
    let ssid: String
    let passphrase: String

    init(ssid: String, passphrase: String) throws {
        guard (1...32).contains(ssid.utf8.count), !ssid.unicodeScalars.contains(where: { $0.value < 32 || $0.value == 127 }),
              (8...63).contains(passphrase.utf8.count), passphrase.utf8.allSatisfy({ (32...126).contains($0) }) else {
            throw FrameIdentityError.invalidQRCode
        }
        self.ssid = ssid
        self.passphrase = passphrase
    }

    static func parse(_ text: String) throws -> FrameBootstrapCode {
        let fields = try BootstrapFlatObject.parse(Data(text.utf8), maximum: 1024,
            keys: ["v", "p", "id", "k", "t", "s", "w", "u"])
        guard case .integer("3") = fields["v"], case .string("softap") = fields["p"],
              case let .string(identifier) = fields["id"], let id = BootstrapFlatObject.uuid(identifier),
              case let .string(pin) = fields["k"], let pinBytes = BootstrapFlatObject.hex(pin),
              case let .string(token) = fields["t"], let tokenBytes = BootstrapFlatObject.hex(token),
              case let .string(ssid) = fields["s"], case let .string(passphrase) = fields["w"],
              case let .string(url) = fields["u"], url == endpoint.absoluteString else { throw FrameIdentityError.invalidQRCode }
        return try FrameBootstrapCode(identity: FrameIdentity(id: id, spkiSHA256: pinBytes), adoptionToken: tokenBytes,
            softAP: SoftAPDescriptor(ssid: ssid, passphrase: passphrase))
    }
}

struct SoftAPManifest: Equatable, Sendable {
    enum Profile: String, Sendable { case bootstrap, normal }
    let profile: Profile
    let frameID: UUID
    let certificateDER: Data

    static func parse(_ data: Data, profile expectedProfile: Profile? = nil, identity: FrameIdentity) throws -> Self {
        let fields = try BootstrapFlatObject.parse(data, maximum: 4096, keys: ["v", "p", "id", "c"])
        guard case .integer("1") = fields["v"], case let .string(rawProfile) = fields["p"], let profile = Profile(rawValue: rawProfile),
              expectedProfile == nil || expectedProfile == profile,
              case let .string(identifier) = fields["id"], BootstrapFlatObject.uuid(identifier) == identity.id,
              case let .string(encoded) = fields["c"], let der = Data(base64Encoded: encoded),
              (1...2048).contains(der.count), der.base64EncodedString() == encoded else {
            throw FrameIdentityError.invalidCertificate
        }
        return Self(profile: profile, frameID: identity.id, certificateDER: der)
    }
}

enum SoftAPError: Error, LocalizedError, Equatable {
    case unavailable, disconnected, timeout, busy, invalidManifest, cancelled
    case normalProfileAvailable, bootstrapProfileAvailable, alreadyOwned
    var errorDescription: String? {
        switch self {
        case .unavailable: return "Le Wi-Fi temporaire du cadre n’a pas pu être rejoint. Restez près du cadre puis réessayez."
        case .timeout: return "Le cadre n’a pas répondu sur son Wi-Fi temporaire. Réessayez ou scannez son QR actuel."
        case .busy: return "Une demande au cadre est déjà en cours."
        case .invalidManifest: return "L’identité reçue sur le Wi-Fi temporaire est invalide. Aucun secret n’a été envoyé."
        case .disconnected, .cancelled: return "La connexion Wi-Fi au cadre a été interrompue. Reprenez la configuration."
        case .normalProfileAvailable, .bootstrapProfileAvailable: return "Le cadre a changé d’étape. Reprenez sa connexion sécurisée."
        case .alreadyOwned: return "Ce cadre est déjà associé. Reprenez depuis l’iPhone propriétaire ou réinitialisez explicitement son association."
        }
    }
}
