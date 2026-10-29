import Foundation
import XCTest
@testable import InkyStudio

/// Opt-in nonce-only HTTP proof, then strict pinned HTTPS against the exact Python bridge backend.
/// No URLProtocol, trust bypass, real frame, local-auth fixture or Keychain claim.
@MainActor
final class PhotoAccessBackendInteropTests: XCTestCase {
    func testLegacyNonceProofPinnedHTTPSOwnerEnrollmentInvitationMediaClaimAndRevocation() async throws {
        let environment = ProcessInfo.processInfo.environment
        guard let endpointText = environment["INKY_PHOTO_INTEROP_ENDPOINT"], !endpointText.isEmpty else {
            throw XCTSkip("Real backend fixture absent; start photo-access-backend-fixture.py and inject its four public environment values.")
        }
        let endpoint = try XCTUnwrap(URL(string: endpointText))
        XCTAssertEqual(endpoint.scheme, "https")
        XCTAssertEqual(endpoint.host, "127.0.0.1", "This opt-in test may only contact its private Mac loopback fixture.")
        guard endpoint.scheme == "https", endpoint.host == "127.0.0.1", endpoint.port != nil,
              endpoint.user == nil, endpoint.password == nil, endpoint.query == nil,
              endpoint.fragment == nil, endpoint.path.isEmpty else {
            XCTFail("Invalid real-backend fixture endpoint."); return
        }
        let httpText = try XCTUnwrap(environment["INKY_PHOTO_INTEROP_HTTP_ENDPOINT"])
        let httpEndpoint = try XCTUnwrap(URL(string: httpText))
        guard httpEndpoint.scheme == "http", httpEndpoint.host == "127.0.0.1", httpEndpoint.port != nil,
              httpEndpoint.user == nil, httpEndpoint.password == nil, httpEndpoint.query == nil,
              httpEndpoint.fragment == nil, httpEndpoint.path.isEmpty, httpEndpoint.port != endpoint.port else {
            XCTFail("Invalid nonce-only loopback listener."); return
        }
        let id = try XCTUnwrap(environment["INKY_PHOTO_INTEROP_FRAME_ID"].flatMap(UUID.init(uuidString:)))
        let pin = try XCTUnwrap(environment["INKY_PHOTO_INTEROP_SPKI_SHA256"].flatMap(PhotoAccessValidation.bytes))
        let identity = try FrameIdentity(id: id, spkiSHA256: pin)
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = nil
        let fixturePassword = "Abcdef0123456789" // Public synthetic16alnum bootstrap, identical to the fixture script.
        // The actual proof client discards injected headers/storage. The backend wrapper
        // independently asserts that every HTTP request contains only v + a fresh nonce.
        let proofConfiguration = URLSessionConfiguration.ephemeral
        proofConfiguration.protocolClasses = nil
        proofConfiguration.httpAdditionalHeaders = [
            "Cookie": "inky_session=synthetic-must-not-forward",
            "Authorization": "Synthetic-must-not-forward",
            "Proxy-Authorization": "synthetic-must-not-forward",
            "X-Inky-Owner-ID": "synthetic-must-not-forward",
            "X-Inky-Owner-Token": "synthetic-must-not-forward",
            "X-Device-Token": "synthetic-must-not-forward",
        ]
        let proofClient = LegacyTLSProofClient(configuration: proofConfiguration)
        let verified = try await proofClient.prove(endpoint: httpEndpoint, bootstrapPassword: fixturePassword)
        XCTAssertEqual(verified.identity, identity)
        XCTAssertEqual(verified.endpoint, endpoint)
        // The real backend observes two independently generated nonces; receipts expose only their count.
        let verifiedAgain = try await proofClient.prove(endpoint: httpEndpoint, bootstrapPassword: fixturePassword)
        XCTAssertEqual(verifiedAgain, verified)

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

        let ownerAPI = InkyAPI(baseURL: verified.endpoint, configuration: configuration, trustedIdentity: verified.identity)
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
            "transport": "real Foundation nonce-only HTTP proof then pinned HTTPS to unchanged Python backend on Mac loopback",
            "backend_commit": "79050e25cb749d03b65592e81f1dd89bffa44472",
            "http_endpoint": httpEndpoint.absoluteString, "nonce_proof_verified": true,
            "proof_attempts": 2, "proof_transport_has_no_cookie_password_or_device_token": true,
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
        attachment.name = "PHOTO real backend legacy proof + HTTPS interop — no secrets"
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
