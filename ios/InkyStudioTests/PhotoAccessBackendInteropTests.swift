import Foundation
import XCTest
@testable import InkyStudio

/// Opt-in real HTTPS exchange with the unchanged Python PHOTO backend on this Mac.
/// No URLProtocol, trust bypass, real frame, local-auth fixture or Keychain claim.
@MainActor
final class PhotoAccessBackendInteropTests: XCTestCase {
    func testPinnedHTTPSOwnerEnrollmentInvitationMediaClaimAndRevocation() async throws {
        let environment = ProcessInfo.processInfo.environment
        guard let endpointText = environment["INKY_PHOTO_INTEROP_ENDPOINT"], !endpointText.isEmpty else {
            throw XCTSkip("Real backend fixture absent; start photo-access-backend-fixture.py and inject its three public environment values.")
        }
        let endpoint = try XCTUnwrap(URL(string: endpointText))
        XCTAssertEqual(endpoint.scheme, "https")
        XCTAssertEqual(endpoint.host, "127.0.0.1", "This opt-in test may only contact its private Mac loopback fixture.")
        guard endpoint.scheme == "https", endpoint.host == "127.0.0.1", endpoint.port != nil,
              endpoint.user == nil, endpoint.password == nil, endpoint.query == nil,
              endpoint.fragment == nil, endpoint.path.isEmpty else {
            XCTFail("Invalid real-backend fixture endpoint."); return
        }
        let id = try XCTUnwrap(environment["INKY_PHOTO_INTEROP_FRAME_ID"].flatMap(UUID.init(uuidString:)))
        let pin = try XCTUnwrap(environment["INKY_PHOTO_INTEROP_SPKI_SHA256"].flatMap(PhotoAccessValidation.bytes))
        let identity = try FrameIdentity(id: id, spkiSHA256: pin)
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = nil
        let fixturePassword = "photo-access-interop-password-v1"

        // Negative control: an incorrect pin must fail in the real TLS exchange.
        let wrongIdentity = try FrameIdentity(id: id, spkiSHA256: Data(repeating: 0, count: 32))
        let rejected = InkyAPI(baseURL: endpoint, configuration: configuration, trustedIdentity: wrongIdentity)
        defer { rejected.clearSession() }
        do {
            _ = try await rejected.login(password: fixturePassword)
            XCTFail("The real HTTPS server was accepted with a wrong SPKI pin.")
            return
        } catch {
            let code = try XCTUnwrap((error as? URLError)?.code, "The negative control must report a real transport trust failure.")
            let trustFailures: Set<URLError.Code> = [.serverCertificateUntrusted, .serverCertificateHasUnknownRoot,
                .secureConnectionFailed, .cancelled, .userCancelledAuthentication, .userAuthenticationRequired]
            XCTAssertTrue(trustFailures.contains(code),
                          "An unrelated timeout or offline error cannot qualify the wrong-pin control.")
        }

        let ownerAPI = InkyAPI(baseURL: endpoint, configuration: configuration, trustedIdentity: identity)
        defer { ownerAPI.clearSession() }
        let ownerClient = try PhotoAccessClient(api: ownerAPI, identity: identity)
        let health = try await ownerAPI.health()
        XCTAssertEqual(health.status, "ok")
        let legacy = try await ownerAPI.login(password: fixturePassword)
        XCTAssertTrue(legacy.authenticated)
        let owner = try PhotoAccessCredential.make(identity: identity, endpoint: endpoint, role: .owner)
        let enrollment = try await ownerClient.enroll(owner)
        XCTAssertEqual(enrollment.deviceID, owner.deviceID)
        XCTAssertEqual(enrollment.role, .owner)
        XCTAssertEqual(enrollment.identity.frameIdentity, identity)
        let ownerSession = try await ownerClient.openSession(owner)
        XCTAssertTrue(ownerSession.authenticated)
        XCTAssertEqual(ownerSession.role, .owner)
        XCTAssertNotNil(try ownerAPI.eventRequest().value(forHTTPHeaderField: "Cookie"))

        let draft = try PhotoInvitationDraft.make(identity: identity, endpoint: endpoint)
        let invitation = try await ownerClient.createInvitation(draft)
        XCTAssertGreaterThan(invitation.expiresAt, Date().timeIntervalSince1970)
        let scanned = try FrameInvitationCode.parse(invitation.code.encodedPayload())
        XCTAssertEqual(scanned.identity, identity)
        XCTAssertEqual(scanned.endpoint, endpoint)
        XCTAssertEqual(scanned.invitationID, draft.invitationID)

        let mediaAPI = InkyAPI(baseURL: scanned.endpoint, configuration: configuration, trustedIdentity: scanned.identity)
        defer { mediaAPI.clearSession() }
        XCTAssertNil(try mediaAPI.eventRequest().value(forHTTPHeaderField: "Cookie"))
        let mediaClient = try PhotoAccessClient(api: mediaAPI, identity: scanned.identity)
        let media = try PhotoAccessCredential.make(identity: scanned.identity, endpoint: scanned.endpoint,
                                                    role: .media, invitationID: scanned.invitationID)
        let claimed = try await mediaClient.claim(scanned, credential: media)
        XCTAssertTrue(claimed.authenticated)
        XCTAssertEqual(claimed.deviceID, media.deviceID)
        XCTAssertEqual(claimed.role, .media)
        let mediaSession = try await mediaClient.openSession(media)
        XCTAssertTrue(mediaSession.authenticated)
        XCTAssertEqual(mediaSession.role, .media)
        XCTAssertEqual(try mediaAPI.eventRequest().url?.scheme, "wss")

        // The real closed media role rejects administration and saturation changes.
        await expectHTTP(403) { _ = try await mediaClient.devices() }
        await expectHTTP(403) {
            _ = try await mediaAPI.updateSettings(FrameSettings(changeMode: .manual, saturation: 1.8))
        }
        let schedule = try await mediaAPI.updateSchedule(FrameSettings(changeMode: .manual,
                                                                        changeHour: 8, changeIntervalMinutes: 90,
                                                                        saturation: 1.8))
        XCTAssertEqual(schedule.saturation, 1.0, "Only the three allowed schedule fields may reach the backend.")
        let devices = try await ownerClient.devices()
        XCTAssertEqual(devices.first(where: { $0.deviceID == owner.deviceID })?.role, .owner)
        XCTAssertEqual(devices.first(where: { $0.deviceID == media.deviceID })?.role, .media)
        try await ownerClient.revokeDevice(media.deviceID)
        await expectHTTP(401) { _ = try await mediaClient.openSession(media) }
        await expectHTTP(401) { _ = try await mediaAPI.logout() }
        XCTAssertNil(try mediaAPI.eventRequest().value(forHTTPHeaderField: "Cookie"))

        let evidence: [String: Any] = [
            "transport": "real Foundation HTTPS to unchanged Python backend on Mac loopback",
            "endpoint": endpoint.absoluteString, "frame_id": identity.id.uuidString.lowercased(),
            "wrong_pin_rejected": true, "legacy_owner_enrollment": true, "owner_device_session": true,
            "invitation_qr_roundtrip": true, "media_claim_and_device_session": true,
            "media_admin_status": 403, "media_saturation_status": 403,
            "media_three_field_schedule": true, "revoked_device_status": 401,
            "logout_clears_local_cookie": true,
            "limits": "No physical Pi, camera scan, local authentication or protected Keychain persistence qualified.",
        ]
        let attachment = XCTAttachment(data: try JSONSerialization.data(withJSONObject: evidence, options: [.sortedKeys, .prettyPrinted]),
                                       uniformTypeIdentifier: "public.json")
        attachment.name = "PHOTO real backend HTTPS interop — no secrets"
        attachment.lifetime = .keepAlways
        add(attachment)
    }

    private func expectHTTP(_ expected: Int, file: StaticString = #filePath, line: UInt = #line,
                            _ action: () async throws -> Void) async {
        do { try await action(); XCTFail("Expected the backend to reject this action.", file: file, line: line) }
        catch APIError.unauthorized { XCTAssertEqual(expected, 401, file: file, line: line) }
        catch APIError.http(let status, _) { XCTAssertEqual(status, expected, file: file, line: line) }
        catch { XCTFail("Expected HTTP rejection, received another error type.", file: file, line: line) }
    }
}
