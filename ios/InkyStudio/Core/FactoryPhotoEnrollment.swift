import Foundation

@MainActor
enum FactoryPhotoEnrollment {
    static func enroll(_ credential: PhotoAccessCredential, api: InkyAPI,
                       owner: OwnershipRecord, setupOperationID: UUID) async throws {
        _ = try credential.validated()
        _ = try FactorySetupValidation.origin(credential.endpoint.absoluteString)
        guard credential.identity == owner.identity, api.pinnedIdentity == owner.identity,
              OriginRedirectDelegate.sameOrigin(credential.endpoint, api.baseURL),
              owner.factoryProfile == .normalV1, credential.expectedRole == .owner, credential.invitationID == nil,
              credential.requestID == owner.claimRequestID, credential.deviceID != owner.ownerID,
              credential.deviceToken != owner.ownerTokenHex else { throw PhotoAccessError.identityMismatch }
        struct Body: Encodable {
            let device_id: String
            let device_token: String
            let request_id: String
            let claim_request_id: String
            let setup_op_id: String
        }
        let body = Body(device_id: credential.deviceID.uuidString.lowercased(), device_token: credential.deviceToken,
                        request_id: owner.claimRequestID.uuidString.lowercased(),
                        claim_request_id: owner.claimRequestID.uuidString.lowercased(),
                        setup_op_id: setupOperationID.uuidString.lowercased())
        let data = try await api.factoryPhotoEnrollment(JSONEncoder().encode(body), owner: owner)
        try FactorySetupWire.validateClosedJSON(data)
        guard let fields = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              Set(fields.keys) == ["device_id", "role", "identity"],
              let device = fields["device_id"] as? String,
              try PhotoAccessValidation.uuid(device) == credential.deviceID,
              fields["role"] as? String == "owner",
              let identity = fields["identity"] as? [String: Any],
              Set(identity.keys) == ["frame_id", "spki_sha256"],
              let frame = identity["frame_id"] as? String,
              try PhotoAccessValidation.uuid(frame) == credential.identity.id,
              let pin = identity["spki_sha256"] as? String,
              PhotoAccessValidation.bytes(pin) == credential.identity.spkiSHA256 else {
            throw PhotoAccessError.identityMismatch
        }
    }
}
