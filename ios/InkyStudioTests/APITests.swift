import Foundation
import XCTest
@testable import InkyStudio

@MainActor
final class APITests: XCTestCase {
    private static let photoJSON = #"{"id":"abc123","sha256":"digest","original_filename":"été.png","mime":"image/png","width":800,"height":480,"size_bytes":728175,"created_at":1780000000.25}"#
    private static let settingsJSON = #"{"change_mode":"interval","change_hour":8,"change_interval_minutes":90,"saturation":1.25}"#
    private static let authJSON = #"{"authenticated":true,"auth_required":true}"#

    func testAddressNormalizationAndDefaultPorts() throws {
        let examples = [
            " inkyold.local \n": "http://inkyold.local:8000",
            "192.168.1.166": "http://192.168.1.166:8000",
            "localhost:5273": "http://localhost:5273",
            "http://Frame.local/": "http://frame.local:8000",
            "HTTP://frame.local:80": "http://frame.local:80",
            "https://frame.local": "https://frame.local",
            "https://frame.local:443/": "https://frame.local",
            "https://frame.local:8443": "https://frame.local:8443",
            "::1": "http://[::1]:8000",
            "[2001:db8::1]:9000": "http://[2001:db8::1]:9000",
        ]
        for (input, output) in examples {
            XCTAssertEqual(try FrameAddress.parse(input).absoluteString, output, input)
        }
    }

    func testRejectsAmbiguousOrUnsafeFrameAddresses() {
        for input in [
            "", "   ", "ftp://frame.local", "http://user:secret@frame.local", "frame.local/api",
            "http://frame.local?password=secret", "http://frame.local#part", "frame .local",
            "http://frame.local:0", "http://frame.local:65536", "http://frame.local:",
            "frame.local:abc", "http://[bad::ipv6]", "999.999.999.999", "http://.local", "http://foo..local",
        ] {
            XCTAssertThrowsError(try FrameAddress.parse(input), input)
        }
    }

    func testDecodesSnakeCaseModelsAndNullableState() throws {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        let current = #"{"id":3,"displayed_at":1780000001.5,"source":"manual_previous","photo":\#(Self.photoJSON)}"#
        let stateJSON = #"{"display":{"model":"Impression","width":800,"height":480,"colors":6,"is_mock":false},"current":\#(current),"queue_count":2,"next_change_at":null}"#
        let state = try decoder.decode(DisplayState.self, from: Data(stateJSON.utf8))
        XCTAssertEqual(state.current?.photo.originalFilename, "été.png")
        XCTAssertEqual(state.current?.photo.sizeBytes, 728175)
        XCTAssertEqual(state.current?.photo.createdAt, 1780000000.25)
        XCTAssertEqual(state.current?.displayedAt, 1780000001.5)
        XCTAssertEqual(state.current?.source, "manual_previous")
        XCTAssertFalse(state.display.isMock)
        XCTAssertEqual(state.queueCount, 2)
        XCTAssertNil(state.nextChangeAt)

        let settings = try decoder.decode(FrameSettings.self, from: Data(Self.settingsJSON.utf8))
        XCTAssertEqual(settings, FrameSettings(changeMode: .interval, changeHour: 8, changeIntervalMinutes: 90, saturation: 1.25))
        let update = try decoder.decode(UpdateStatus.self, from: Data(#"{"current":"0.4.2","latest":null,"update_available":false}"#.utf8))
        XCTAssertNil(update.latest)
        XCTAssertFalse(update.updateAvailable)
        let event = try decoder.decode(ServerEvent.self, from: Data(#"{"type":"system_update","payload":{"stage":"install","done":false,"progress":0.5,"detail":null}}"#.utf8))
        XCTAssertEqual(event.payload["stage"]?.stringValue, "install")
        XCTAssertEqual(event.payload["done"]?.boolValue, false)
        XCTAssertEqual(event.payload["progress"], .number(0.5))
    }

    func testLoginEncodesPasswordOnceAndUsesExactEndpoint() async throws {
        let stub = APIStub { request in
            XCTAssertEqual(request.url?.path, "/api/auth/login")
            XCTAssertEqual(request.httpMethod, "POST")
            XCTAssertEqual(request.timeoutInterval, 12)
            XCTAssertEqual(request.value(forHTTPHeaderField: "Content-Type"), "application/json")
            let object = try JSONSerialization.jsonObject(with: request.bodyData) as? [String: String]
            XCTAssertEqual(object, ["password": "a+é\"&test"])
            return .json(Self.authJSON)
        }
        let api = client(stub)
        let auth = try await api.login(password: "a+é\"&test")
        XCTAssertTrue(auth.authenticated)
        XCTAssertTrue(auth.authRequired)
        XCTAssertEqual(stub.requests.count, 1)
        api.clearSession()
    }

    func testCookieJarIsSharedByHTTPPhotoAndWSButIsolatedPerConnectionAndPort() async throws {
        let stub = APIStub { request in
            if request.url?.path == "/api/auth/login" {
                return .json(Self.authJSON, headers: ["Set-Cookie": "inky_session=frame-token; Path=/; HttpOnly; Max-Age=3600"])
            }
            if request.url?.path == "/api/photos/abc123" { return APIStub.Response(data: Data([1, 2, 3])) }
            return .json(Self.authJSON)
        }
        let primary = client(stub, origin: "http://frame.local:8000")
        let anotherPort = client(stub, origin: "http://frame.local:8001")
        let anotherConnection = client(stub, origin: "http://frame.local:8000")
        _ = try await primary.login(password: "test")
        _ = try await primary.authStatus()
        let photo = try await primary.photoData(id: "abc123")
        XCTAssertEqual(photo, Data([1, 2, 3]))
        let socket = try primary.eventRequest()
        XCTAssertEqual(socket.url?.absoluteString, "ws://frame.local:8000/api/ws")
        XCTAssertEqual(socket.value(forHTTPHeaderField: "Cookie"), "inky_session=frame-token")
        _ = try await anotherPort.authStatus()
        _ = try await anotherConnection.authStatus()
        let calls = stub.requests
        XCTAssertEqual(calls[1].value(forHTTPHeaderField: "Cookie"), "inky_session=frame-token")
        XCTAssertEqual(calls[2].value(forHTTPHeaderField: "Cookie"), "inky_session=frame-token")
        XCTAssertNil(calls[3].value(forHTTPHeaderField: "Cookie"))
        XCTAssertNil(calls[4].value(forHTTPHeaderField: "Cookie"))
        XCTAssertFalse(HTTPCookieStorage.shared.cookies?.contains(where: { $0.value == "frame-token" }) ?? false)
        primary.clearSession()
        XCTAssertNil(try primary.eventRequest().value(forHTTPHeaderField: "Cookie"))
        _ = try await primary.authStatus()
        XCTAssertNil(stub.requests.last?.value(forHTTPHeaderField: "Cookie"))
        anotherPort.clearSession()
        anotherConnection.clearSession()
    }

    func testServerCookieDeletionAndSecureCookiesAreRespected() async throws {
        let stub = APIStub { request in
            switch request.url?.path {
            case "/api/auth/login":
                return .json(Self.authJSON, headers: ["Set-Cookie": "inky_session=secure-token; Path=/; Secure; HttpOnly; Max-Age=3600"])
            default:
                return .json(Self.authJSON, headers: ["Set-Cookie": "inky_session=; Path=/; Max-Age=0"])
            }
        }
        let insecure = client(stub)
        _ = try await insecure.login(password: "test")
        XCTAssertNil(try insecure.eventRequest().value(forHTTPHeaderField: "Cookie"))
        insecure.clearSession()
        let secure = client(stub, origin: "https://frame.local")
        _ = try await secure.login(password: "test")
        XCTAssertEqual(try secure.eventRequest().url?.scheme, "wss")
        XCTAssertEqual(try secure.eventRequest().value(forHTTPHeaderField: "Cookie"), "inky_session=secure-token")
        _ = try await secure.authStatus()
        XCTAssertNil(try secure.eventRequest().value(forHTTPHeaderField: "Cookie"))
        secure.clearSession()
    }

    func testLogoutForgetsSessionEvenWhenFrameIsUnavailable() async throws {
        let stub = APIStub { request in
            if request.url?.path == "/api/auth/login" {
                return .json(Self.authJSON, headers: ["Set-Cookie": "inky_session=logout-token; Path=/; HttpOnly"])
            }
            throw URLError(.notConnectedToInternet)
        }
        let api = client(stub)
        _ = try await api.login(password: "test")
        do { _ = try await api.logout(); XCTFail("Logout should propagate the connection failure") }
        catch { XCTAssertEqual((error as? URLError)?.code, .notConnectedToInternet) }
        XCTAssertNil(try api.eventRequest().value(forHTTPHeaderField: "Cookie"))
        XCTAssertEqual(stub.requests.last?.url?.path, "/api/auth/logout")
        api.clearSession()
    }

    func testSettingsAndReorderEncodeServerFieldNames() async throws {
        let stub = APIStub { request in
            let body = try JSONSerialization.jsonObject(with: request.bodyData) as! [String: Any]
            if request.url?.path == "/api/settings" {
                XCTAssertEqual(Set(body.keys), ["change_mode", "change_hour", "change_interval_minutes", "saturation"])
                XCTAssertEqual(body["change_mode"] as? String, "interval")
                XCTAssertEqual(body["change_hour"] as? Int, 8)
                XCTAssertEqual(body["change_interval_minutes"] as? Int, 90)
                XCTAssertEqual(body["saturation"] as? Double, 1.25)
                return .json(Self.settingsJSON)
            }
            XCTAssertEqual(request.url?.path, "/api/queue/reorder")
            XCTAssertEqual(Set(body.keys), ["photo_ids"])
            XCTAssertEqual(body["photo_ids"] as? [String], ["b", "a"])
            return .json("[]")
        }
        let api = client(stub)
        let settings = FrameSettings(changeMode: .interval, changeHour: 8, changeIntervalMinutes: 90, saturation: 1.25)
        let saved = try await api.updateSettings(settings)
        XCTAssertEqual(saved, settings)
        let queue = try await api.reorderQueue(photoIDs: ["b", "a"])
        XCTAssertTrue(queue.isEmpty)
        api.clearSession()
    }

    func testEmpty202And204MutationsSucceedWithoutJSONParsingOrReplay() async throws {
        let stub = APIStub { request in
            if request.url?.path.hasPrefix("/api/display/") == true {
                XCTAssertEqual(request.timeoutInterval, 120)
                XCTAssertEqual(request.httpMethod, "POST")
                return APIStub.Response(status: 202)
            }
            XCTAssertEqual(request.httpMethod, "DELETE")
            return APIStub.Response(status: 204)
        }
        let api = client(stub)
        try await api.next()
        try await api.previous()
        try await api.removeFromQueue(photoID: "abc123")
        try await api.deleteHistoryEntry(id: 8)
        try await api.clearHistory()
        XCTAssertEqual(stub.requests.map(\.url?.path), ["/api/display/next", "/api/display/previous", "/api/queue/abc123", "/api/history/8", "/api/history"])
        api.clearSession()
    }

    func testQueriesAndUpdateStartMatchContract() async throws {
        let stub = APIStub { request in
            switch request.url?.path {
            case "/api/history":
                XCTAssertEqual(request.url?.query, "limit=20&offset=40")
                return .json("[]")
            case "/api/system/update" where request.httpMethod == "POST": return .json(#"{"started":true}"#)
            default:
                XCTAssertEqual(request.url?.query, "refresh=1")
                return .json(#"{"current":"0.4.2","latest":"0.4.3","update_available":true}"#)
            }
        }
        let api = client(stub)
        let history = try await api.history(limit: 20, offset: 40)
        XCTAssertTrue(history.isEmpty)
        let update = try await api.updateStatus(refresh: true)
        XCTAssertTrue(update.updateAvailable)
        let started = try await api.startUpdate()
        XCTAssertTrue(started)
        api.clearSession()
    }

    func testMultipartPreservesPNGAndCannotInjectFilenameHeaders() async throws {
        let png = Data([137, 80, 78, 71, 13, 10, 26, 10, 0, 255])
        let responseJSON = #"{"photo":\#(Self.photoJSON),"queue_entry":{"id":4,"position":1,"added_at":1780000000,"photo":\#(Self.photoJSON)},"already_existed":false}"#
        let stub = APIStub { request in
            XCTAssertEqual(request.url?.path, "/api/queue")
            XCTAssertEqual(request.httpMethod, "POST")
            XCTAssertEqual(request.timeoutInterval, 60)
            let contentType = try XCTUnwrap(request.value(forHTTPHeaderField: "Content-Type"))
            XCTAssertTrue(contentType.hasPrefix("multipart/form-data; boundary=InkyStudio-"))
            let boundary = String(contentType.split(separator: "=").last!)
            let body = request.bodyData
            XCTAssertNotNil(body.range(of: png))
            XCTAssertTrue(body.starts(with: Data("--\(boundary)\r\nContent-Disposition: form-data; name=\"file\"; filename=\"été____Injected: yes.png\"\r\nContent-Type: image/png\r\n\r\n".utf8)))
            XCTAssertTrue(body.suffix(Data("\r\n--\(boundary)--\r\n".utf8).count) == Data("\r\n--\(boundary)--\r\n".utf8))
            return .json(responseJSON)
        }
        let api = client(stub)
        let result = try await api.upload(png: png, filename: "été\"\\\r\nInjected: yes.png")
        XCTAssertEqual(result.queueEntry.id, 4)
        XCTAssertFalse(result.alreadyExisted)
        api.clearSession()
    }

    func testHTTPFailuresAreReadableAndMutationsAreNotRetried() async throws {
        let stub = APIStub { _ in
            .json(#"{"detail":[{"loc":["body","password"],"msg":"Field required","input":"never-echo-this-secret"}]}"#, status: 422)
        }
        let api = client(stub)
        do { _ = try await api.login(password: "test"); XCTFail("Expected validation error") }
        catch let error as APIError {
            XCTAssertEqual(error, .http(statusCode: 422, message: "Données non valides : Field required"))
            XCTAssertFalse(error.localizedDescription.contains("never-echo-this-secret"))
        }
        XCTAssertEqual(stub.requests.count, 1)
        XCTAssertEqual(APIError.response(status: 401, data: Data()), .unauthorized)
        XCTAssertTrue(APIError.unauthorized.isUnauthorized)
        XCTAssertEqual(APIError.response(status: 409, data: Data(#"{"detail":"Cadre occupé"}"#.utf8)), .http(statusCode: 409, message: "Cadre occupé"))
        XCTAssertEqual(APIError.response(status: 502, data: Data("<html>secret proxy details</html>".utf8)).localizedDescription, "Le cadre rencontre une erreur (502). Réessayez dans un instant.")
        api.clearSession()
    }

    func testInvalidSuccessJSONDoesNotMasqueradeAsValidState() async throws {
        let stub = APIStub { _ in .json(#"{"status":"ok"}"#) }
        let api = client(stub)
        do { _ = try await api.health(); XCTFail("Missing version must fail decoding") }
        catch { XCTAssertEqual(error as? APIError, .invalidData) }
        api.clearSession()
    }

    func testDeadlineCancelsAHangingRequestWithoutRetrying() async throws {
        let stopped = expectation(description: "Timed-out transfer cancelled")
        let stub = APIStub { _ in
            APIStub.Response(holdOpen: true, onCancel: { stopped.fulfill() })
        }
        let configuration = stub.configuration()
        configuration.waitsForConnectivity = true
        let session = URLSession(configuration: configuration)
        defer { session.invalidateAndCancel() }
        let request = URLRequest(url: URL(string: "http://frame.local:8000/api/auth/status")!, timeoutInterval: 0.05)
        let start = ContinuousClock.now
        do {
            _ = try await HTTPDeadline.data(for: request, using: session)
            XCTFail("A silent connection must not block beyond its deadline")
        } catch {
            XCTAssertEqual((error as? URLError)?.code, .timedOut)
        }
        XCTAssertLessThan(start.duration(to: .now), .seconds(2))
        await fulfillment(of: [stopped], timeout: 1)
        XCTAssertEqual(stub.requests.count, 1)
    }

    func testRedirectDelegateRejectsOriginChangesBeforeForwardingCredentials() {
        let origin = URL(string: "http://frame.local:8000")!
        let delegate = OriginRedirectDelegate(origin: origin)
        let session = URLSession(configuration: .ephemeral)
        defer { session.invalidateAndCancel() }
        let task = session.dataTask(with: origin)
        let response = HTTPURLResponse(url: origin, statusCode: 307, httpVersion: nil, headerFields: nil)!
        for target in ["http://other.local:8000/login", "http://frame.local:8001/login", "https://frame.local:8000/login", "http://user:pass@frame.local:8000/login"] {
            var call = URLRequest(url: URL(string: target)!)
            call.httpMethod = "POST"
            call.httpBody = Data(#"{"password":"secret"}"#.utf8)
            call.setValue("inky_session=secret", forHTTPHeaderField: "Cookie")
            delegate.urlSession(session, task: task, willPerformHTTPRedirection: response, newRequest: call) { allowed in
                XCTAssertNil(allowed, target)
            }
        }
        let same = URLRequest(url: URL(string: "http://frame.local:8000/api/auth/login/")!)
        delegate.urlSession(session, task: task, willPerformHTTPRedirection: response, newRequest: same) { allowed in
            XCTAssertEqual(allowed?.url, same.url)
        }
        XCTAssertTrue(OriginRedirectDelegate.sameOrigin(URL(string: "wss://frame.local/api/ws")!, URL(string: "https://frame.local:443")!))
        XCTAssertFalse(OriginRedirectDelegate.sameOrigin(URL(string: "http://frame.local:8000")!, URL(string: "http://frame.local")!))
    }

    private func client(_ stub: APIStub, origin: String = "http://frame.local:8000") -> InkyAPI {
        InkyAPI(baseURL: URL(string: origin)!, configuration: stub.configuration())
    }
}

/// Requests are routed by a private test header, so different tests and frame
/// clients cannot accidentally consume another test's response handler.
private final class APIStub: @unchecked Sendable {
    struct Response {
        var status = 200
        var headers: [String: String] = [:]
        var data = Data()
        var holdOpen = false
        var onCancel: (() -> Void)?

        static func json(_ text: String, status: Int = 200, headers: [String: String] = [:]) -> Response {
            Response(status: status, headers: headers.merging(["Content-Type": "application/json"]) { first, _ in first }, data: Data(text.utf8))
        }
    }

    private let id = UUID().uuidString
    private let lock = NSLock()
    private var recorded: [URLRequest] = []
    private let handler: (URLRequest) throws -> Response

    init(_ handler: @escaping (URLRequest) throws -> Response) { self.handler = handler }

    var requests: [URLRequest] { lock.withLock { recorded } }

    func configuration() -> URLSessionConfiguration {
        StubURLProtocol.register(self, id: id)
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [StubURLProtocol.self]
        configuration.httpAdditionalHeaders = ["X-Inky-Test": id]
        return configuration
    }

    func respond(to request: URLRequest) throws -> Response {
        lock.withLock { recorded.append(request) }
        return try handler(request)
    }
}

private final class StubURLProtocol: URLProtocol, @unchecked Sendable {
    private static let lock = NSLock()
    // Every access is protected by `lock`; URLProtocol callbacks run off actor.
    nonisolated(unsafe) private static var handlers: [String: APIStub] = [:]
    private var onCancel: (() -> Void)?

    static func register(_ stub: APIStub, id: String) { lock.withLock { handlers[id] = stub } }

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        do {
            let id = request.value(forHTTPHeaderField: "X-Inky-Test") ?? ""
            let stub = Self.lock.withLock { Self.handlers[id] }
            guard let stub else { throw URLError(.resourceUnavailable) }
            let result = try stub.respond(to: request)
            onCancel = result.onCancel
            if result.holdOpen { return }
            let response = HTTPURLResponse(url: request.url!, statusCode: result.status, httpVersion: "HTTP/1.1", headerFields: result.headers)!
            client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
            client?.urlProtocol(self, didLoad: result.data)
            client?.urlProtocolDidFinishLoading(self)
        } catch {
            client?.urlProtocol(self, didFailWithError: error)
        }
    }

    override func stopLoading() { onCancel?() }
}

private extension URLRequest {
    var bodyData: Data {
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
