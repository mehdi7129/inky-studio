import Foundation
import Security

/// PHOTO authority is independent from Bluetooth ownership.
enum PhotoAccessRole: String, Codable, Sendable { case owner, media }

struct PhotoAccessCredential: Codable, Equatable, Sendable {
    enum State: String, Codable, Sendable { case pending, active }
    let identity: FrameIdentity
    let endpoint: URL
    let deviceID: UUID
    let deviceToken: String
    let requestID: UUID
    let expectedRole: PhotoAccessRole
    var state: State
    let invitationID: UUID?

    init(identity: FrameIdentity, endpoint: URL, deviceID: UUID, deviceToken: String,
         requestID: UUID, expectedRole: PhotoAccessRole, state: State = .pending,
         invitationID: UUID? = nil) throws {
        try PhotoAccessValidation.origin(endpoint)
        guard PhotoAccessValidation.token(deviceToken) else { throw PhotoAccessError.invalidData }
        self.identity = identity; self.endpoint = endpoint; self.deviceID = deviceID
        self.deviceToken = deviceToken; self.requestID = requestID; self.expectedRole = expectedRole
        self.state = state; self.invitationID = invitationID
    }

    static func make(identity: FrameIdentity, endpoint: URL, role: PhotoAccessRole, invitationID: UUID? = nil) throws -> Self {
        try Self(identity: identity, endpoint: endpoint, deviceID: UUID(), deviceToken: PhotoAccessValidation.randomToken(),
                 requestID: UUID(), expectedRole: role, invitationID: invitationID)
    }

    func validated() throws -> Self {
        try Self(identity: identity, endpoint: endpoint, deviceID: deviceID, deviceToken: deviceToken,
                 requestID: requestID, expectedRole: expectedRole, state: state, invitationID: invitationID)
    }
}

struct PhotoInvitationDraft: Codable, Equatable, Sendable {
    let identity: FrameIdentity
    let endpoint: URL
    let invitationID: UUID
    let invitationToken: String
    let requestID: UUID
    var expiresAt: Double?
    var revocationPending: Bool

    init(identity: FrameIdentity, endpoint: URL, invitationID: UUID, invitationToken: String, requestID: UUID, expiresAt: Double? = nil, revocationPending: Bool = false) throws {
        try PhotoAccessValidation.origin(endpoint)
        guard PhotoAccessValidation.token(invitationToken) else { throw PhotoAccessError.invalidData }
        self.identity = identity; self.endpoint = endpoint; self.invitationID = invitationID
        self.invitationToken = invitationToken; self.requestID = requestID; self.expiresAt = expiresAt
        self.revocationPending = revocationPending
        guard expiresAt.map({ $0.isFinite && $0 > 0 }) ?? true else { throw PhotoAccessError.invalidData }
    }

    private enum CodingKeys: String, CodingKey { case identity, endpoint, invitationID, invitationToken, requestID, expiresAt, revocationPending }
    init(from decoder: Decoder) throws {
        let fields = try decoder.container(keyedBy: CodingKeys.self)
        try self.init(identity: fields.decode(FrameIdentity.self, forKey: .identity), endpoint: fields.decode(URL.self, forKey: .endpoint),
            invitationID: fields.decode(UUID.self, forKey: .invitationID), invitationToken: fields.decode(String.self, forKey: .invitationToken),
            requestID: fields.decode(UUID.self, forKey: .requestID), expiresAt: fields.decodeIfPresent(Double.self, forKey: .expiresAt),
            revocationPending: fields.decodeIfPresent(Bool.self, forKey: .revocationPending) ?? false)
    }

    static func make(identity: FrameIdentity, endpoint: URL) throws -> Self {
        try Self(identity: identity, endpoint: endpoint, invitationID: UUID(),
                 invitationToken: PhotoAccessValidation.randomToken(), requestID: UUID())
    }

    func validated() throws -> Self {
        try Self(identity: identity, endpoint: endpoint, invitationID: invitationID,
                 invitationToken: invitationToken, requestID: requestID, expiresAt: expiresAt, revocationPending: revocationPending)
    }
}

struct PhotoAccessInvitation: Equatable, Sendable {
    let invitationID: UUID
    let code: FrameInvitationCode
    let expiresAt: Double
}

struct PhotoAccessDeviceSummary: Codable, Equatable, Sendable {
    let deviceID: UUID
    let role: PhotoAccessRole
    let createdAt: Double
    let revoked: Bool
    enum CodingKeys: String, CodingKey { case deviceID = "device_id", role, createdAt = "created_at", revoked }

    init(deviceID: UUID, role: PhotoAccessRole, createdAt: Double, revoked: Bool) {
        self.deviceID = deviceID; self.role = role; self.createdAt = createdAt; self.revoked = revoked
    }

    init(from decoder: Decoder) throws {
        let fields = try decoder.container(keyedBy: CodingKeys.self)
        deviceID = try PhotoAccessValidation.uuid(fields.decode(String.self, forKey: .deviceID))
        role = try fields.decode(PhotoAccessRole.self, forKey: .role)
        createdAt = try fields.decode(Double.self, forKey: .createdAt)
        revoked = try fields.decode(Bool.self, forKey: .revoked)
        guard createdAt.isFinite, createdAt >= 0 else { throw PhotoAccessError.invalidData }
    }
}

struct PhotoAccessIdentityReply: Decodable, Equatable, Sendable {
    let frameIdentity: FrameIdentity
    let endpoint: URL?
    enum CodingKeys: String, CodingKey { case frameID = "frame_id", pin = "spki_sha256", url }
    init(from decoder: Decoder) throws {
        let fields = try decoder.container(keyedBy: CodingKeys.self)
        let id = try PhotoAccessValidation.uuid(fields.decode(String.self, forKey: .frameID))
        let hex = try fields.decode(String.self, forKey: .pin)
        guard let pin = PhotoAccessValidation.bytes(hex) else { throw PhotoAccessError.invalidData }
        frameIdentity = try FrameIdentity(id: id, spkiSHA256: pin)
        endpoint = try fields.decodeIfPresent(URL.self, forKey: .url)
        if let endpoint { try PhotoAccessValidation.origin(endpoint) }
    }
}

struct PhotoAccessSessionIdentityReply: Decodable, Equatable, Sendable {
    let deviceID: UUID
    let role: PhotoAccessRole
    let identity: PhotoAccessIdentityReply
    enum CodingKeys: String, CodingKey { case deviceID = "device_id", role, identity }
    init(from decoder: Decoder) throws {
        let fields = try decoder.container(keyedBy: CodingKeys.self)
        deviceID = try PhotoAccessValidation.uuid(fields.decode(String.self, forKey: .deviceID))
        role = try fields.decode(PhotoAccessRole.self, forKey: .role)
        identity = try fields.decode(PhotoAccessIdentityReply.self, forKey: .identity)
    }
}

struct PhotoAccessSessionReply: Decodable, Equatable, Sendable {
    let authenticated: Bool
    let deviceID: UUID
    let role: PhotoAccessRole
    let canInvite: Bool
    let identity: PhotoAccessIdentityReply
    enum CodingKeys: String, CodingKey { case authenticated, deviceID = "device_id", role, canInvite = "can_invite", identity }
    init(from decoder: Decoder) throws {
        let fields = try decoder.container(keyedBy: CodingKeys.self)
        authenticated = try fields.decode(Bool.self, forKey: .authenticated)
        deviceID = try PhotoAccessValidation.uuid(fields.decode(String.self, forKey: .deviceID))
        role = try fields.decode(PhotoAccessRole.self, forKey: .role)
        // Old frames allow owners to invite; media sharing requires an explicit
        // capability from this frame's authenticated, pinned PHOTO response.
        canInvite = try fields.decodeIfPresent(Bool.self, forKey: .canInvite) ?? (role == .owner)
        identity = try fields.decode(PhotoAccessIdentityReply.self, forKey: .identity)
    }
}

enum PhotoAccessError: Error, LocalizedError, Equatable, Sendable {
    case trustedHTTPSRequired, invalidData, identityMismatch, unavailable, accessRemoved, storageFailed
    var errorDescription: String? {
        switch self {
        case .trustedHTTPSRequired: return "Associez d’abord ce cadre par sa connexion sécurisée pour activer le partage."
        case .invalidData: return "La réponse d’accès du cadre n’est pas valide."
        case .identityMismatch: return "L’identité du cadre ne correspond pas à l’accès attendu. Aucun nouvel accès n’a été conservé."
        case .unavailable: return "Le partage n’est pas disponible sur ce cadre. Vérifiez sa configuration et sa version."
        case .accessRemoved: return "Cet accès au cadre a été retiré ou n’est plus valide. Demandez une nouvelle invitation au propriétaire."
        case .storageFailed: return "L’accès sécurisé n’a pas pu être enregistré sur cet iPhone. Aucune association n’a été finalisée."
        }
    }
}

enum PhotoAccessValidation {
    static func token(_ value: String) -> Bool { bytes(value) != nil }
    static func bytes(_ value: String) -> Data? {
        let chars = Array(value.utf8)
        guard chars.count == 64, chars.allSatisfy({ (48...57).contains($0) || (97...102).contains($0) }) else { return nil }
        var data = Data(capacity: 32)
        for index in stride(from: 0, to: chars.count, by: 2) {
            func nibble(_ byte: UInt8) -> UInt8 { byte <= 57 ? byte - 48 : byte - 87 }
            data.append(nibble(chars[index]) * 16 + nibble(chars[index + 1]))
        }
        return data
    }
    static func uuid(_ value: String) throws -> UUID {
        guard let id = UUID(uuidString: value), id.uuidString.lowercased() == value else { throw PhotoAccessError.invalidData }
        return id
    }
    static func origin(_ endpoint: URL) throws {
        // Reuse the closed invitation-origin grammar without interpreting a URL as a login.
        _ = try FrameInvitationCode(identity: FrameIdentity(id: UUID(), spkiSHA256: Data(repeating: 0, count: 32)),
                                    endpoint: endpoint, invitationID: UUID(), invitationToken: String(repeating: "0", count: 64))
    }
    static func randomToken() throws -> String {
        var data = Data(count: 32)
        let result = data.withUnsafeMutableBytes { SecRandomCopyBytes(kSecRandomDefault, $0.count, $0.baseAddress!) }
        guard result == errSecSuccess else { throw PhotoAccessError.storageFailed }
        return data.map { String(format: "%02x", $0) }.joined()
    }
}
