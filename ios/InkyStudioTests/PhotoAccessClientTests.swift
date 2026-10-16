import Foundation
import XCTest
@testable import InkyStudio

/// Wire tests use synthetic credentials and intercept URLSession before networking.
/// They verify trust preconditions and request/response contracts, not a TLS handshake.
@MainActor
final class PhotoAccessClientTests: XCTestCase {
    private let endpoint = URL(string: "https://frame.local:8443")!
    private let frameID = UUID(uuidString: "11111111-2222-4333-8444-555555555555")!
    private let deviceID = UUID(uuidString: "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee")!
    private let requestID = UUID(uuidString: "12345678-1234-4234-8234-123456789abc")!
    private let invitationID = UUID(uuidString: "87654321-4321-4321-8321-cba987654321")!
    private let deviceToken = String(repeating: "a1", count: 32)
    private let invitationToken = String(repeating: "b2", count: 32)

    private var identity: FrameIdentity {
        get throws { try FrameIdentity(id: frameID, spkiSHA256: Data(repeating: 0x17, count: 32)) }
    }

    func testRejectsHTTPBeforeCredentialRequests() throws {
        let stub = PhotoAccessWireStub { _ in
            XCTFail("An HTTP origin must be rejected before sending any request or secret.")
            return try .json([:])
        }
        let api = InkyAPI(baseURL: URL(string: "http://frame.local:8000")!,
                          configuration: stub.configuration(), trustedIdentity: try identity)
        defer { api.clearSession(); stub.dispose() }
        XCTAssertThrowsError(try PhotoAccessClient(api: api, identity: identity))
        XCTAssertTrue(stub.requests.isEmpty)
    }

    func testRequiresPinnedIdentityBeforeCredentialRequests() throws {
        let stub = PhotoAccessWireStub { _ in
            XCTFail("An ordinary system-trusted HTTPS connection is insufficient for PHOTO credentials.")
            return try .json([:])
        }
        let api = InkyAPI(baseURL: endpoint, configuration: stub.configuration())
        defer { api.clearSession(); stub.dispose() }
        XCTAssertThrowsError(try PhotoAccessClient(api: api, identity: identity))
        XCTAssertTrue(stub.requests.isEmpty)
    }

    func testRejectsDifferentPinnedFrameIDOrSPKIBeforeCredentialRequests() throws {
        let trusted = try identity
        let mismatches = [
            try FrameIdentity(id: UUID(), spkiSHA256: trusted.spkiSHA256),
            try FrameIdentity(id: trusted.id, spkiSHA256: Data(repeating: 0x28, count: 32)),
        ]
        for mismatch in mismatches {
            let stub = PhotoAccessWireStub { _ in
                XCTFail("A client bound to another frame must never receive this frame's token.")
                return try .json([:])
            }
            let api = InkyAPI(baseURL: endpoint, configuration: stub.configuration(), trustedIdentity: trusted)
            defer { api.clearSession(); stub.dispose() }
            XCTAssertThrowsError(try PhotoAccessClient(api: api, identity: mismatch))
            XCTAssertTrue(stub.requests.isEmpty)
        }
    }

    func testEnrollmentUsesExactBodyAndPreservesLegacyCookieUntilDeviceSession() async throws {
        let credential = try credential()
        let reply = wireSessionReply(credential, authenticated: false)
        let expected = ["device_id": deviceID.uuidString.lowercased(), "device_token": deviceToken,
                        "request_id": requestID.uuidString.lowercased()]
        let stub = PhotoAccessWireStub { request in
            if request.url?.path == "/api/auth/login" {
                return try .json(["authenticated": true, "auth_required": true],
                                 headers: ["Set-Cookie": "inky_session=legacy-fixture; Path=/; Secure; HttpOnly"])
            }
            try assertPhotoAccessRequest(request, method: "POST", path: "/api/auth/devices/enroll", body: expected)
            XCTAssertEqual(request.value(forHTTPHeaderField: "Cookie"), "inky_session=legacy-fixture")
            return try .json(reply)
        }
        let (api, client) = try boundClient(stub)
        defer { api.clearSession(); stub.dispose() }
        _ = try await api.login(password: "synthetic-legacy-password")
        let enrolled = try await client.enroll(credential)
        XCTAssertEqual(enrolled.deviceID, credential.deviceID)
        XCTAssertEqual(enrolled.role, .owner)
        XCTAssertEqual(enrolled.identity.frameIdentity, credential.identity)
        XCTAssertEqual(try api.eventRequest().value(forHTTPHeaderField: "Cookie"), "inky_session=legacy-fixture")
        XCTAssertEqual(stub.requests.count, 2, "Enrollment must not silently open or replay another session.")
    }

    func testDeviceSessionUsesOnlyDeviceCredentialAndSharesCookieWithPhotoAndWebSocket() async throws {
        let credential = try credential(role: .media)
        let reply = wireSessionReply(credential)
        let expected = ["device_id": deviceID.uuidString.lowercased(), "device_token": deviceToken]
        let stub = PhotoAccessWireStub { request in
            if request.url?.path == "/api/auth/device-session" {
                try assertPhotoAccessRequest(request, method: "POST", path: "/api/auth/device-session", body: expected)
                return try .json(reply, headers: ["Set-Cookie": "inky_session=media-fixture; Path=/; Secure; HttpOnly; SameSite=Strict"])
            }
            XCTAssertEqual(request.url?.path, "/api/photos/synthetic-image")
            XCTAssertEqual(request.value(forHTTPHeaderField: "Cookie"), "inky_session=media-fixture")
            return PhotoAccessWireStub.Response(data: Data([137, 80, 78, 71]))
        }
        let (api, client) = try boundClient(stub)
        defer { api.clearSession(); stub.dispose() }
        let session = try await client.openSession(credential)
        XCTAssertTrue(session.authenticated)
        XCTAssertEqual(session.role, .media)
        let photo = try await api.photoData(id: "synthetic-image")
        XCTAssertEqual(photo, Data([137, 80, 78, 71]))
        let socket = try api.eventRequest()
        XCTAssertEqual(socket.url?.scheme, "wss")
        XCTAssertEqual(socket.value(forHTTPHeaderField: "Cookie"), "inky_session=media-fixture")
        let independent = InkyAPI(baseURL: endpoint, configuration: stub.configuration(), trustedIdentity: try identity)
        defer { independent.clearSession() }
        XCTAssertNil(try independent.eventRequest().value(forHTTPHeaderField: "Cookie"))
        XCTAssertFalse(HTTPCookieStorage.shared.cookies?.contains(where: { $0.value == "media-fixture" }) ?? false)
        XCTAssertEqual(stub.requests.count, 2)
    }

    func testInvitationCreationUsesExactBodyAndReturnedCanonicalHTTPSOrigin() async throws {
        let draft = try draft()
        let advertised = URL(string: "https://192.168.1.120:8443")!
        let expires = Date().addingTimeInterval(120).timeIntervalSince1970
        let response: [String: Any] = ["invitation_id": invitationID.uuidString.lowercased(),
                                       "expires_at": expires, "role": "media",
                                       "identity": wireIdentity(try identity, endpoint: advertised)]
        let expected: [String: Any] = ["invitation_id": invitationID.uuidString.lowercased(),
                                       "invitation_token": invitationToken,
                                       "request_id": requestID.uuidString.lowercased(), "ttl_seconds": 300]
        let stub = PhotoAccessWireStub { request in
            try assertPhotoAccessRequest(request, method: "POST", path: "/api/auth/invitations", body: expected)
            XCTAssertEqual(request.url?.host, "frame.local")
            XCTAssertEqual(request.url?.port, 8443)
            return try .json(response)
        }
        let (api, client) = try boundClient(stub)
        defer { api.clearSession(); stub.dispose() }
        let invitation = try await client.createInvitation(draft)
        XCTAssertEqual(invitation.invitationID, draft.invitationID)
        XCTAssertEqual(invitation.expiresAt, expires)
        XCTAssertEqual(invitation.code.endpoint, advertised)
        XCTAssertEqual(invitation.code.identity, draft.identity)
        XCTAssertEqual(invitation.code.invitationToken, draft.invitationToken)
        let qr = try JSONSerialization.jsonObject(with: Data(invitation.code.encodedPayload().utf8)) as! [String: Any]
        XCTAssertEqual(Set(qr.keys), ["v", "p", "id", "k", "url", "i", "t"])
        XCTAssertNil(qr["password"])
        XCTAssertNil(qr["device_token"])
        XCTAssertEqual(stub.requests.count, 1, "The advertised origin is only encoded in the QR; no issuer request or credential is forwarded to it.")
    }

    func testClaimUsesExactInvitationAndDeviceBodyWithoutBootstrapOrLegacyCookie() async throws {
        let credential = try credential(role: .media, invitation: invitationID)
        let code = try invitationCode()
        let response = wireSessionReply(credential)
        let expected = ["invitation_id": invitationID.uuidString.lowercased(), "invitation_token": invitationToken,
                        "device_id": deviceID.uuidString.lowercased(), "device_token": deviceToken,
                        "request_id": requestID.uuidString.lowercased()]
        let stub = PhotoAccessWireStub { request in
            try assertPhotoAccessRequest(request, method: "POST", path: "/api/auth/invitations/claim", body: expected)
            XCTAssertNil(request.value(forHTTPHeaderField: "Cookie"))
            return try .json(response, headers: ["Set-Cookie": "inky_session=claimed-fixture; Path=/; Secure; HttpOnly"])
        }
        let (api, client) = try boundClient(stub)
        defer { api.clearSession(); stub.dispose() }
        let session = try await client.claim(code, credential: credential)
        XCTAssertEqual(session.deviceID, credential.deviceID)
        XCTAssertEqual(session.role, .media)
        XCTAssertEqual(try api.eventRequest().value(forHTTPHeaderField: "Cookie"), "inky_session=claimed-fixture")
        XCTAssertEqual(stub.requests.count, 1)
    }

    func testCredentialOrInvitationBoundToAnotherFrameOrOriginNeverSendsItsToken() async throws {
        let otherIdentity = try FrameIdentity(id: UUID(), spkiSHA256: Data(repeating: 0x28, count: 32))
        let otherOrigin = URL(string: "https://other-frame.local:8443")!
        let foreignCredentials = [try credential(identity: otherIdentity), try credential(endpoint: otherOrigin)]
        let stub = PhotoAccessWireStub { _ in
            XCTFail("Mismatched identity or endpoint must fail before a request is emitted.")
            return try .json([:])
        }
        let (api, client) = try boundClient(stub)
        defer { api.clearSession(); stub.dispose() }
        for credential in foreignCredentials {
            await expectFailure { _ = try await client.openSession(credential) }
            await expectFailure { _ = try await client.enroll(credential) }
        }
        let media = try credential(role: .media, invitation: invitationID)
        for code in [try invitationCode(identity: otherIdentity), try invitationCode(endpoint: otherOrigin)] {
            await expectFailure { _ = try await client.claim(code, credential: media) }
        }
        let foreignDraft = try draft(identity: otherIdentity)
        await expectFailure { _ = try await client.createInvitation(foreignDraft) }
        XCTAssertTrue(stub.requests.isEmpty)
    }

    func testSessionRejectsMismatchedIdentityDeviceRoleAndFalseAuthentication() async throws {
        let credential = try credential(role: .media)
        let good = wireSessionReply(credential)
        var badFrame = good
        badFrame["identity"] = wireIdentity(try FrameIdentity(id: UUID(), spkiSHA256: credential.identity.spkiSHA256))
        var badPin = good
        badPin["identity"] = wireIdentity(try FrameIdentity(id: credential.identity.id, spkiSHA256: Data(repeating: 0, count: 32)))
        var badDevice = good; badDevice["device_id"] = UUID().uuidString.lowercased()
        var badRole = good; badRole["role"] = "owner"
        var unknownRole = good; unknownRole["role"] = "administrator"
        var unauthenticated = good; unauthenticated["authenticated"] = false
        for response in [badFrame, badPin, badDevice, badRole, unknownRole, unauthenticated] {
            let stub = PhotoAccessWireStub { _ in try .json(response) }
            let (api, client) = try boundClient(stub)
            defer { api.clearSession(); stub.dispose() }
            await expectFailure { _ = try await client.openSession(credential) }
            XCTAssertEqual(stub.requests.count, 1, "Malformed replies must not cause retries or password fallback.")
        }
    }

    func testPhotoAccessRoutesRejectProvisioningEnvelopeInsteadOfAcceptingWrappedSuccess() async throws {
        let credential = try credential()
        let response: [String: Any] = ["ok": true, "result": wireSessionReply(credential)]
        let stub = PhotoAccessWireStub { _ in try .json(response) }
        let (api, client) = try boundClient(stub)
        defer { api.clearSession(); stub.dispose() }
        await expectFailure { _ = try await client.openSession(credential) }
        XCTAssertEqual(stub.requests.count, 1)
    }

    func testInvitationReplyRejectsWrongInvitationFrameRoleAndInsecureOrigin() async throws {
        let draft = try draft()
        let good: [String: Any] = ["invitation_id": invitationID.uuidString.lowercased(),
                                  "expires_at": Date().addingTimeInterval(120).timeIntervalSince1970,
                                  "role": "media", "identity": wireIdentity(try identity, endpoint: endpoint)]
        var badID = good; badID["invitation_id"] = UUID().uuidString.lowercased()
        var badFrame = good
        badFrame["identity"] = wireIdentity(try FrameIdentity(id: UUID(), spkiSHA256: draft.identity.spkiSHA256), endpoint: endpoint)
        var badPin = good
        badPin["identity"] = wireIdentity(try FrameIdentity(id: draft.identity.id, spkiSHA256: Data(repeating: 0x28, count: 32)), endpoint: endpoint)
        var badRole = good; badRole["role"] = "owner"
        var invalidReplies = [badID, badFrame, badPin, badRole]
        for url in ["http://frame.local:8000", "https://user:secret@frame.local", "https://frame.local/api", "https://frame.local?token=synthetic", "https://frame.local#fragment"] {
            var invalid = good; var invalidIdentity = wireIdentity(try identity)
            invalidIdentity["url"] = url; invalid["identity"] = invalidIdentity
            invalidReplies.append(invalid)
        }
        for response in invalidReplies {
            let stub = PhotoAccessWireStub { _ in try .json(response) }
            let (api, client) = try boundClient(stub)
            defer { api.clearSession(); stub.dispose() }
            await expectFailure { _ = try await client.createInvitation(draft) }
            XCTAssertEqual(stub.requests.count, 1)
        }
    }

    func testDevicesEnvelopeAndRevocationsUseExactPathsWithoutBodiesOrTokenHeaders() async throws {
        let device = deviceID.uuidString.lowercased()
        let invite = invitationID.uuidString.lowercased()
        let stub = PhotoAccessWireStub { request in
            switch request.url?.path {
            case "/api/auth/devices":
                try assertPhotoAccessRequest(request, method: "GET", path: "/api/auth/devices")
                return try .json(["devices": [["device_id": device, "role": "media", "created_at": 1_780_000_000.5, "revoked": true]]])
            case "/api/auth/devices/" + device:
                try assertPhotoAccessRequest(request, method: "DELETE", path: "/api/auth/devices/" + device)
            default:
                try assertPhotoAccessRequest(request, method: "DELETE", path: "/api/auth/invitations/" + invite)
            }
            return try .json(["revoked": true])
        }
        let (api, client) = try boundClient(stub)
        defer { api.clearSession(); stub.dispose() }
        let devices = try await client.devices()
        XCTAssertEqual(devices.count, 1)
        XCTAssertEqual(devices.first?.deviceID, deviceID)
        XCTAssertEqual(devices.first?.role, .media)
        XCTAssertEqual(devices.first?.createdAt, 1_780_000_000.5)
        XCTAssertEqual(devices.first?.revoked, true)
        try await client.revokeDevice(deviceID)
        try await client.revokeInvitation(invitationID)
        XCTAssertEqual(stub.requests.count, 3)
    }

    func testUnauthorizedSessionAndForbiddenInvitationDoNotRetryDowngradeOrUseLegacyPassword() async throws {
        let credential = try credential(role: .media)
        let draft = try draft()
        for status in [401, 403] {
            let stub = PhotoAccessWireStub { request in
                XCTAssertEqual(request.url?.scheme, "https")
                XCTAssertTrue(["/api/auth/device-session", "/api/auth/invitations"].contains(request.url?.path ?? ""))
                return try .json(["detail": "Synthetic denied access"], status: status)
            }
            let (api, client) = try boundClient(stub)
            defer { api.clearSession(); stub.dispose() }
            await expectFailure { _ = try await client.openSession(credential) }
            await expectFailure { _ = try await client.createInvitation(draft) }
            XCTAssertEqual(stub.requests.map(\.url?.path), ["/api/auth/device-session", "/api/auth/invitations"])
        }
    }

    func testFailedRevocationCannotReportSuccessOrReplayMutation() async throws {
        for response in [["revoked": false], ["ok": true]] {
            let stub = PhotoAccessWireStub { _ in try .json(response) }
            let (api, client) = try boundClient(stub)
            defer { api.clearSession(); stub.dispose() }
            await expectFailure { try await client.revokeDevice(self.deviceID) }
            XCTAssertEqual(stub.requests.count, 1)
        }
    }

    func testLogoutClearsIndividualSessionEvenWhenFrameGoesOffline() async throws {
        let credential = try credential(role: .media)
        let response = wireSessionReply(credential)
        let stub = PhotoAccessWireStub { request in
            if request.url?.path == "/api/auth/device-session" {
                return try .json(response, headers: ["Set-Cookie": "inky_session=logout-photo-fixture; Path=/; Secure; HttpOnly"])
            }
            XCTAssertEqual(request.url?.path, "/api/auth/logout")
            XCTAssertEqual(request.httpMethod, "POST")
            XCTAssertEqual(request.value(forHTTPHeaderField: "Cookie"), "inky_session=logout-photo-fixture")
            throw URLError(.notConnectedToInternet)
        }
        let (api, client) = try boundClient(stub)
        defer { api.clearSession(); stub.dispose() }
        _ = try await client.openSession(credential)
        await expectFailure { _ = try await api.logout() }
        XCTAssertNil(try api.eventRequest().value(forHTTPHeaderField: "Cookie"))
        XCTAssertEqual(stub.requests.map(\.url?.path), ["/api/auth/device-session", "/api/auth/logout"])
    }

    func testMediaScheduleSendsOnlyAllowedFieldsWithoutChangingServerSaturation() async throws {
        let credential = try credential(role: .media)
        let sessionReply = wireSessionReply(credential)
        let expected: [String: Any] = ["change_mode": "interval", "change_hour": 8, "change_interval_minutes": 90]
        let stub = PhotoAccessWireStub { request in
            if request.url?.path == "/api/auth/device-session" {
                return try .json(sessionReply, headers: ["Set-Cookie": "inky_session=schedule-media-fixture; Path=/; Secure; HttpOnly"])
            }
            try assertPhotoAccessRequest(request, method: "POST", path: "/api/settings", body: expected)
            XCTAssertEqual(request.value(forHTTPHeaderField: "Cookie"), "inky_session=schedule-media-fixture")
            return try .json(["change_mode": "interval", "change_hour": 8, "change_interval_minutes": 90, "saturation": 1.0])
        }
        let (api, client) = try boundClient(stub)
        defer { api.clearSession(); stub.dispose() }
        _ = try await client.openSession(credential)
        let settings = try await api.updateSchedule(FrameSettings(changeMode: .interval, changeHour: 8,
                                                                   changeIntervalMinutes: 90, saturation: 1.8))
        XCTAssertEqual(settings.saturation, 1.0, "A media schedule change must preserve the saturation controlled by the frame.")
        XCTAssertEqual(stub.requests.count, 2)
    }

    func testDirectAuthenticationRedirectsAreRejectedEvenWithinSameHTTPSOrigin() throws {
        let delegate = OriginRedirectDelegate(origin: endpoint, trust: FrameTrustPolicy(identity: try identity))
        let session = URLSession(configuration: .ephemeral)
        defer { session.invalidateAndCancel() }
        var original = URLRequest(url: endpoint.appendingPathComponent("api/auth/device-session"))
        original.httpMethod = "POST"
        original.httpBody = Data("synthetic-body-that-must-not-be-redirected".utf8)
        original.setValue("1", forHTTPHeaderField: "X-Inky-Direct-Auth")
        let task = session.dataTask(with: original)
        let redirect = HTTPURLResponse(url: original.url!, statusCode: 307, httpVersion: nil, headerFields: nil)!
        for destination in ["https://frame.local:8443/api/auth/device-session/", "http://frame.local:8000/", "https://another-frame.local/"] {
            let candidate = URLRequest(url: URL(string: destination)!)
            delegate.urlSession(session, task: task, willPerformHTTPRedirection: redirect, newRequest: candidate) { permitted in
                XCTAssertNil(permitted, "PHOTO authentication must use the exact endpoint, without forwarding secrets through redirects.")
            }
        }
    }

    private func credential(role: PhotoAccessRole = .owner, identity selectedIdentity: FrameIdentity? = nil,
                            endpoint selectedEndpoint: URL? = nil, invitation: UUID? = nil) throws -> PhotoAccessCredential {
        try PhotoAccessCredential(identity: selectedIdentity ?? identity, endpoint: selectedEndpoint ?? endpoint,
                                  deviceID: deviceID, deviceToken: deviceToken, requestID: requestID,
                                  expectedRole: role, invitationID: invitation)
    }

    private func draft(identity selectedIdentity: FrameIdentity? = nil) throws -> PhotoInvitationDraft {
        try PhotoInvitationDraft(identity: selectedIdentity ?? identity, endpoint: endpoint,
                                 invitationID: invitationID, invitationToken: invitationToken, requestID: requestID)
    }

    private func invitationCode(identity selectedIdentity: FrameIdentity? = nil,
                                endpoint selectedEndpoint: URL? = nil) throws -> FrameInvitationCode {
        try FrameInvitationCode(identity: selectedIdentity ?? identity, endpoint: selectedEndpoint ?? endpoint,
                                invitationID: invitationID, invitationToken: invitationToken)
    }

    private func boundClient(_ stub: PhotoAccessWireStub) throws -> (InkyAPI, PhotoAccessClient) {
        let trusted = try identity
        let api = InkyAPI(baseURL: endpoint, configuration: stub.configuration(), trustedIdentity: trusted)
        return (api, try PhotoAccessClient(api: api, identity: trusted))
    }

    private func expectFailure(file: StaticString = #filePath, line: UInt = #line,
                               _ operation: () async throws -> Void) async {
        do { try await operation(); XCTFail("The operation must fail closed.", file: file, line: line) }
        catch {}
    }
}

private func wireIdentity(_ identity: FrameIdentity, endpoint: URL? = nil) -> [String: Any] {
    var result: [String: Any] = ["frame_id": identity.id.uuidString.lowercased(),
                               "spki_sha256": identity.spkiSHA256.map { String(format: "%02x", $0) }.joined()]
    if let endpoint { result["url"] = endpoint.absoluteString }
    return result
}

private func wireSessionReply(_ credential: PhotoAccessCredential, authenticated: Bool = true) -> [String: Any] {
    var result: [String: Any] = ["device_id": credential.deviceID.uuidString.lowercased(),
                               "role": credential.expectedRole.rawValue, "identity": wireIdentity(credential.identity)]
    if authenticated { result["authenticated"] = true }
    return result
}

private func assertPhotoAccessRequest(_ request: URLRequest, method: String, path: String,
                                      body: [String: Any]? = nil, file: StaticString = #filePath, line: UInt = #line) throws {
    XCTAssertEqual(request.url?.scheme, "https", file: file, line: line)
    XCTAssertEqual(request.url?.path, path, file: file, line: line)
    XCTAssertEqual(request.httpMethod, method, file: file, line: line)
    XCTAssertNil(request.url?.query, file: file, line: line)
    XCTAssertNil(request.url?.fragment, file: file, line: line)
    XCTAssertNil(request.value(forHTTPHeaderField: "Authorization"), file: file, line: line)
    XCTAssertNil(request.value(forHTTPHeaderField: "X-Inky-Owner-ID"), file: file, line: line)
    XCTAssertNil(request.value(forHTTPHeaderField: "X-Inky-Owner-Token"), file: file, line: line)
    if path.hasPrefix("/api/auth/") {
        XCTAssertEqual(request.value(forHTTPHeaderField: "X-Inky-Direct-Auth"), "1", file: file, line: line)
    }
    if let body {
        XCTAssertEqual(request.value(forHTTPHeaderField: "Content-Type"), "application/json", file: file, line: line)
        let decoded = try JSONSerialization.jsonObject(with: request.photoAccessBodyData) as! [String: Any]
        XCTAssertTrue(NSDictionary(dictionary: decoded).isEqual(to: body), "The wire body must contain exactly the documented keys and values.", file: file, line: line)
        let headers = (request.allHTTPHeaderFields ?? [:]).values.joined(separator: " ")
        for (key, value) in body where key.hasSuffix("_token") {
            if let token = value as? String { XCTAssertFalse(headers.contains(token), "Tokens belong only in the JSON body.", file: file, line: line) }
        }
    } else { XCTAssertTrue(request.photoAccessBodyData.isEmpty, file: file, line: line) }
}

private final class PhotoAccessWireStub: @unchecked Sendable {
    struct Response {
        var status = 200
        var headers: [String: String] = [:]
        var data = Data()

        static func json(_ object: [String: Any], status: Int = 200,
                         headers: [String: String] = [:]) throws -> Response {
            Response(status: status,
                     headers: headers.merging(["Content-Type": "application/json"]) { first, _ in first },
                     data: try JSONSerialization.data(withJSONObject: object, options: [.sortedKeys]))
        }
    }

    private let id = UUID().uuidString
    private let lock = NSLock()
    private var recorded: [URLRequest] = []
    private let handler: (URLRequest) throws -> Response

    init(_ handler: @escaping (URLRequest) throws -> Response) { self.handler = handler }
    var requests: [URLRequest] { lock.withLock { recorded } }

    func configuration() -> URLSessionConfiguration {
        PhotoAccessWireURLProtocol.register(self, id: id)
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [PhotoAccessWireURLProtocol.self]
        configuration.httpAdditionalHeaders = ["X-Inky-Photo-Wire-Test": id]
        return configuration
    }

    func dispose() { PhotoAccessWireURLProtocol.remove(id: id) }

    func respond(to request: URLRequest) throws -> Response {
        var captured = request
        captured.httpBody = request.photoAccessBodyData
        lock.withLock { recorded.append(captured) }
        return try handler(captured)
    }
}

private final class PhotoAccessWireURLProtocol: URLProtocol, @unchecked Sendable {
    private static let lock = NSLock()
    nonisolated(unsafe) private static var handlers: [String: PhotoAccessWireStub] = [:]

    static func register(_ stub: PhotoAccessWireStub, id: String) { lock.withLock { handlers[id] = stub } }
    static func remove(id: String) { _ = lock.withLock { handlers.removeValue(forKey: id) } }

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        do {
            let id = request.value(forHTTPHeaderField: "X-Inky-Photo-Wire-Test") ?? ""
            guard let stub = Self.lock.withLock({ Self.handlers[id] }) else { throw URLError(.resourceUnavailable) }
            let result = try stub.respond(to: request)
            let response = HTTPURLResponse(url: request.url!, statusCode: result.status,
                                           httpVersion: "HTTP/1.1", headerFields: result.headers)!
            client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
            client?.urlProtocol(self, didLoad: result.data)
            client?.urlProtocolDidFinishLoading(self)
        } catch { client?.urlProtocol(self, didFailWithError: error) }
    }

    override func stopLoading() {}
}

private extension URLRequest {
    var photoAccessBodyData: Data {
        if let httpBody { return httpBody }
        guard let stream = httpBodyStream else { return Data() }
        stream.open()
        defer { stream.close() }
        var result = Data()
        var buffer = [UInt8](repeating: 0, count: 4096)
        while stream.hasBytesAvailable {
            let count = stream.read(&buffer, maxLength: buffer.count)
            guard count > 0 else { break }
            result.append(contentsOf: buffer.prefix(count))
        }
        return result
    }
}
