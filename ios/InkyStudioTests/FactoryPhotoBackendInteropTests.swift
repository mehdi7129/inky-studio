import Foundation
import XCTest
@testable import InkyStudio

/// Actual HTTPS/main/routes/stores; the private synthetic fixture explicitly injects
/// OS completion authority. This test claims neither BLE adoption nor physical OS effects.
@MainActor
final class FactoryPhotoBackendInteropTests: XCTestCase {
    func testRealFactoryOwnerEnrollmentRetryDeviceSessionAndInvitation() async throws {
        let env = ProcessInfo.processInfo.environment
        guard let endpointText = env["INKY_FACTORY_INTEROP_ENDPOINT"], !endpointText.isEmpty else {
            throw XCTSkip("Factory backend fixture absent; inject its private test environment.")
        }
        let endpoint = try FactorySetupValidation.origin(endpointText)
        func value(_ key: String) throws -> String { try XCTUnwrap(env["INKY_FACTORY_INTEROP_" + key]) }
        let identity = try FrameIdentity(id: PhotoAccessValidation.uuid(value("FRAME_ID")),
            spkiSHA256: XCTUnwrap(PhotoAccessValidation.bytes(value("SPKI_SHA256"))))
        let certificate = try XCTUnwrap(Data(base64Encoded: value("CERT_DER")))
        _ = try PinnedFrameTrust(identity: identity, certificateDER: certificate)
        let ownerID = try PhotoAccessValidation.uuid(value("OWNER_ID"))
        let claimID = try PhotoAccessValidation.uuid(value("CLAIM_REQUEST_ID"))
        let setupID = try PhotoAccessValidation.uuid(value("SETUP_OP_ID"))
        _ = try PhotoAccessValidation.uuid(value("COMPLETION_ID"))
        let ownerToken = try XCTUnwrap(PhotoAccessValidation.bytes(value("OWNER_TOKEN")))
        var owner = OwnershipRecord(identity: identity, certificateDER: certificate, ownerID: ownerID,
            claimRequestID: claimID, ownerToken: ownerToken, endpoints: [endpoint], state: .claimed)
        owner.factoryProfile = .normalV1
        owner.factorySetupOperationID = setupID
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = nil

        // A real transport trust failure is required; preflight input rejection,
        // timeout and offline errors cannot pass this negative control.
        let wrongIdentity = try FrameIdentity(id: identity.id, spkiSHA256: Data(repeating: 0, count: 32))
        let rejected = InkyAPI(baseURL: endpoint, configuration: configuration, trustedIdentity: wrongIdentity)
        defer { rejected.clearSession() }
        do { _ = try await rejected.health(); XCTFail("Wrong pin accepted by real HTTPS."); return }
        catch {
            let code = try XCTUnwrap((error as? URLError)?.code)
            let failures: Set<URLError.Code> = [.serverCertificateUntrusted, .serverCertificateHasUnknownRoot,
                .secureConnectionFailed, .cancelled, .userCancelledAuthentication, .userAuthenticationRequired]
            guard failures.contains(code) else { XCTFail("Wrong-pin control failed for an unrelated transport reason."); return }
        }
        let api = InkyAPI(baseURL: endpoint, configuration: configuration, trustedIdentity: identity)
        defer { api.clearSession() }
        let health = try await api.health()
        XCTAssertEqual(health.status, "ok")
        let credential = try PhotoAccessCredential(identity: identity, endpoint: endpoint, deviceID: UUID(),
            deviceToken: PhotoAccessValidation.randomToken(), requestID: claimID, expectedRole: .owner)
        XCTAssertNotEqual(credential.deviceID, ownerID)
        XCTAssertFalse(credential.deviceToken == owner.ownerTokenHex)

        var badOwner = OwnershipRecord(identity: identity, certificateDER: certificate, ownerID: ownerID,
            claimRequestID: claimID, ownerToken: Data(repeating: 0, count: 32), endpoints: [endpoint], state: .claimed)
        badOwner.factoryProfile = .normalV1
        let ownerRefusal = try await refused {
            try await FactoryPhotoEnrollment.enroll(credential, api: api, owner: badOwner, setupOperationID: setupID)
        }
        let badClaimID = UUID()
        var badClaim = OwnershipRecord(identity: identity, certificateDER: certificate, ownerID: ownerID,
            claimRequestID: badClaimID, ownerToken: ownerToken, endpoints: [endpoint], state: .claimed)
        badClaim.factoryProfile = .normalV1
        let badClaimCredential = try PhotoAccessCredential(identity: identity, endpoint: endpoint,
            deviceID: credential.deviceID, deviceToken: credential.deviceToken, requestID: badClaimID, expectedRole: .owner)
        let claimRefusal = try await refused {
            try await FactoryPhotoEnrollment.enroll(badClaimCredential, api: api, owner: badClaim, setupOperationID: setupID)
        }
        let setupRefusal = try await refused {
            try await FactoryPhotoEnrollment.enroll(credential, api: api, owner: owner, setupOperationID: UUID())
        }
        let client = try PhotoAccessClient(api: api, identity: identity)
        let prematureSession = try await refused { _ = try await client.openSession(credential) }
        XCTAssertEqual(prematureSession, 401, "Rejected enrollment must not create a usable PHOTO credential.")

        try await FactoryPhotoEnrollment.enroll(credential, api: api, owner: owner, setupOperationID: setupID)
        XCTAssertNil(try api.eventRequest().value(forHTTPHeaderField: "Cookie"))
        try await FactoryPhotoEnrollment.enroll(credential, api: api, owner: owner, setupOperationID: setupID)
        XCTAssertNil(try api.eventRequest().value(forHTTPHeaderField: "Cookie"))
        let session = try await client.openSession(credential)
        XCTAssertTrue(session.authenticated)
        XCTAssertEqual(session.role, .owner)
        XCTAssertEqual(session.deviceID, credential.deviceID)
        XCTAssertNotNil(try api.eventRequest().value(forHTTPHeaderField: "Cookie"))
        XCTAssertNil(try api.eventRequest().value(forHTTPHeaderField: "X-Inky-Owner-Token"))
        let devices = try await client.devices()
        XCTAssertEqual(devices.filter { $0.deviceID == credential.deviceID }.count, 1)
        let invitation = try await client.createInvitation(PhotoInvitationDraft.make(identity: identity, endpoint: endpoint))
        let decoded = try FrameInvitationCode.parse(invitation.code.encodedPayload())
        XCTAssertEqual(decoded.identity, identity)
        XCTAssertEqual(decoded.endpoint, endpoint)

        let receipt: [String: Any] = ["transport": "Actual Foundation HTTPS to real factory main/routes/stores",
            "wrong_pin_rejected": true, "owner_refusal": ownerRefusal, "claim_refusal": claimRefusal,
            "setup_refusal": setupRefusal, "premature_device_session": prematureSession,
            "enrollment_retry_count": 2, "enrollment_cookie_absent": true, "owner_device_session": true,
            "photo_requests_without_ble_headers": true, "invitation_roundtrip": true,
            "limits": "OS completion authority injected explicitly; no hardware, BLE claim or physical protected Keychain qualification."]
        let attachment = XCTAttachment(data: try JSONSerialization.data(withJSONObject: receipt, options: [.sortedKeys, .prettyPrinted]), uniformTypeIdentifier: "public.json")
        attachment.name = "Factory PHOTO real backend interop — no secrets"
        attachment.lifetime = .keepAlways
        add(attachment)
    }

    private enum Failure: Error { case unexpectedlyAccepted, unrelatedFailure }
    private func refused(_ action: () async throws -> Void) async throws -> Int {
        do { try await action() }
        catch APIError.unauthorized { return 401 }
        catch APIError.http(let status, _) where (400..<500).contains(status) { return status }
        catch { throw Failure.unrelatedFailure }
        throw Failure.unexpectedlyAccepted
    }
}
