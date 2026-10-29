import Foundation

/// Shares the photo client's isolated cookie jar; never invents Bluetooth ownership.
@MainActor
final class PhotoAccessClient {
    let identity: FrameIdentity
    let endpoint: URL
    private let api: InkyAPI
    private let decoder = JSONDecoder()
    private let encoder = JSONEncoder()

    init(api: InkyAPI, identity: FrameIdentity) throws {
        try PhotoAccessValidation.origin(api.baseURL)
        guard api.pinnedIdentity == identity else { throw PhotoAccessError.trustedHTTPSRequired }
        self.api = api; self.identity = identity; endpoint = api.baseURL
    }

    func enroll(_ credential: PhotoAccessCredential) async throws -> PhotoAccessSessionIdentityReply {
        try validate(credential)
        guard credential.expectedRole == .owner, credential.invitationID == nil else { throw PhotoAccessError.invalidData }
        let data = try await send("POST", "/api/auth/devices/enroll", Enrollment(credential))
        let reply: PhotoAccessSessionIdentityReply = try decode(data)
        try validate(reply.identity, deviceID: reply.deviceID, role: reply.role, credential: credential)
        return reply
    }

    func openSession(_ credential: PhotoAccessCredential) async throws -> PhotoAccessSessionReply {
        try validate(credential)
        let data = try await send("POST", "/api/auth/device-session", DeviceSession(credential))
        let reply: PhotoAccessSessionReply = try decode(data)
        guard reply.authenticated else { throw PhotoAccessError.invalidData }
        try validate(reply.identity, deviceID: reply.deviceID, role: reply.role, credential: credential)
        return reply
    }

    func createInvitation(_ draft: PhotoInvitationDraft) async throws -> PhotoAccessInvitation {
        _ = try draft.validated()
        try validate(identity: draft.identity, endpoint: draft.endpoint)
        struct Body: Encodable {
            let invitation_id: String; let invitation_token: String; let request_id: String; let ttl_seconds = 300
        }
        struct Reply: Decodable {
            let invitation_id: String; let expires_at: Double; let role: PhotoAccessRole; let identity: PhotoAccessIdentityReply
        }
        let data = try await send("POST", "/api/auth/invitations", Body(invitation_id: draft.invitationID.uuidString.lowercased(),
            invitation_token: draft.invitationToken, request_id: draft.requestID.uuidString.lowercased()))
        let reply: Reply = try decode(data)
        guard try PhotoAccessValidation.uuid(reply.invitation_id) == draft.invitationID,
              reply.role == .media, reply.expires_at.isFinite, reply.expires_at > 0,
              let origin = reply.identity.endpoint else { throw PhotoAccessError.invalidData }
        // A pinned frame may advertise its canonical DNS origin instead of this LAN locator.
        // No issuer cookie or credential is sent there; it is encoded for the recipient only.
        guard reply.identity.frameIdentity == identity else { throw PhotoAccessError.identityMismatch }
        try PhotoAccessValidation.origin(origin)
        let code = try FrameInvitationCode(identity: identity, endpoint: origin,
            invitationID: draft.invitationID, invitationToken: draft.invitationToken)
        return PhotoAccessInvitation(invitationID: draft.invitationID, code: code, expiresAt: reply.expires_at)
    }

    func claim(_ code: FrameInvitationCode, credential: PhotoAccessCredential) async throws -> PhotoAccessSessionReply {
        try validate(credential)
        try validate(identity: code.identity, endpoint: code.endpoint)
        guard credential.expectedRole == .media, credential.invitationID == code.invitationID else { throw PhotoAccessError.invalidData }
        struct Body: Encodable {
            let invitation_id: String; let invitation_token: String; let device_id: String; let device_token: String; let request_id: String
        }
        let data = try await send("POST", "/api/auth/invitations/claim", Body(invitation_id: code.invitationID.uuidString.lowercased(),
            invitation_token: code.invitationToken, device_id: credential.deviceID.uuidString.lowercased(),
            device_token: credential.deviceToken, request_id: credential.requestID.uuidString.lowercased()))
        let reply: PhotoAccessSessionReply = try decode(data)
        guard reply.authenticated else { throw PhotoAccessError.invalidData }
        try validate(reply.identity, deviceID: reply.deviceID, role: reply.role, credential: credential)
        return reply
    }

    func revokeInvitation(_ id: UUID) async throws { try await revoke("/api/auth/invitations/" + id.uuidString.lowercased()) }
    func revokeDevice(_ id: UUID) async throws { try await revoke("/api/auth/devices/" + id.uuidString.lowercased()) }
    func devices() async throws -> [PhotoAccessDeviceSummary] {
        struct Reply: Decodable { let devices: [PhotoAccessDeviceSummary] }
        let reply: Reply = try decode(await api.photoAccessRequest("GET", path: "/api/auth/devices"))
        guard Set(reply.devices.map(\.deviceID)).count == reply.devices.count else { throw PhotoAccessError.invalidData }
        return reply.devices
    }

    private func revoke(_ path: String) async throws {
        struct Reply: Decodable { let revoked: Bool }
        let reply: Reply = try decode(await api.photoAccessRequest("DELETE", path: path))
        guard reply.revoked else { throw PhotoAccessError.invalidData }
    }
    private func validate(_ credential: PhotoAccessCredential) throws {
        _ = try credential.validated()
        try validate(identity: credential.identity, endpoint: credential.endpoint)
    }
    private func validate(identity other: FrameIdentity, endpoint otherEndpoint: URL) throws {
        guard other == identity, OriginRedirectDelegate.sameOrigin(endpoint, otherEndpoint) else { throw PhotoAccessError.identityMismatch }
        try PhotoAccessValidation.origin(otherEndpoint)
    }
    private func validate(_ reply: PhotoAccessIdentityReply, deviceID: UUID, role: PhotoAccessRole,
                          credential: PhotoAccessCredential) throws {
        guard reply.frameIdentity == identity, deviceID == credential.deviceID, role == credential.expectedRole else {
            throw PhotoAccessError.identityMismatch
        }
        if let origin = reply.endpoint { try validate(identity: reply.frameIdentity, endpoint: origin) }
    }
    private func decode<T: Decodable>(_ data: Data) throws -> T {
        do { return try decoder.decode(T.self, from: data) }
        catch let error as PhotoAccessError { throw error }
        catch { throw PhotoAccessError.invalidData }
    }
    private func send<T: Encodable>(_ method: String, _ path: String, _ body: T) async throws -> Data {
        try await api.photoAccessRequest(method, path: path, body: encoder.encode(body))
    }
    private struct DeviceSession: Encodable {
        let device_id: String; let device_token: String
        init(_ credential: PhotoAccessCredential) {
            device_id = credential.deviceID.uuidString.lowercased(); device_token = credential.deviceToken
        }
    }
    private struct Enrollment: Encodable {
        let device_id: String; let device_token: String; let request_id: String
        init(_ credential: PhotoAccessCredential) {
            device_id = credential.deviceID.uuidString.lowercased(); device_token = credential.deviceToken
            request_id = credential.requestID.uuidString.lowercased()
        }
    }
}
