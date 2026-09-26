import XCTest
@testable import InkyStudio

@MainActor
final class AppStoreTests: XCTestCase {
    func testBiometricPreferenceIsPreservedUnlessExplicitlyDisabledAfterSuccessfulLogin() async throws {
        let fixture = StoreFixture()
        defer { fixture.dispose() }
        let store = fixture.store
        await fixture.login("saved-frame.local")
        store.biometricEnabled = true
        await store.login(password: "synthetic-test-password")
        XCTAssertTrue(store.biometricEnabled, "A biometric reconnect preserves the opted-in credential.")
        let gate = fixture.stub.hold(host: "saved-frame.local", path: "/api/auth/login", method: "POST")
        let rejected = Task { await store.login(password: "wrong", rememberBiometric: false) }
        await fulfillment(of: [gate.started], timeout: 3)
        gate.release(status: 401)
        await rejected.value
        XCTAssertTrue(store.biometricEnabled, "A rejected password must not replace the saved preference.")
        await store.login(password: "synthetic-test-password", rememberBiometric: false)
        XCTAssertTrue(store.authenticated)
        XCTAssertFalse(store.biometricEnabled)
    }

    func testCancelledLoginCannotRestoreSessionAfterNewConnection() async throws {
        let fixture = StoreFixture()
        defer { fixture.dispose() }
        let store = fixture.store
        store.address = "old-frame.local"
        let gate = fixture.stub.hold(host: "old-frame.local", path: "/api/auth/status")
        let login = Task { await store.login(password: "synthetic-test-password") }
        await fulfillment(of: [gate.started], timeout: 3)
        store.cancelLogin()
        XCTAssertFalse(store.connecting)
        XCTAssertFalse(store.authenticated)
        XCTAssertNil(store.api)
        XCTAssertFalse(store.hasSavedFrame)
        await fixture.login("new-frame.local")
        gate.release()
        await login.value
        XCTAssertTrue(store.authenticated)
        XCTAssertEqual(store.address, "http://new-frame.local:8000")
        XCTAssertNil(store.errorMessage)
    }

    func testForgetIsLocalAndDelayedLogoutCannotEraseNewConnection() async throws {
        let fixture = StoreFixture()
        defer { fixture.dispose() }
        let store = fixture.store
        await fixture.login("old-frame.local")
        store.availableUpdate = UpdateStatus(current: "0.4.2", latest: "0.4.3", updateAvailable: true)
        store.busy = true
        store.displayBusy = true
        store.loadingHistory = true
        let gate = fixture.stub.hold(host: "old-frame.local", path: "/api/auth/logout")
        let logout = Task { await store.logout(forget: true) }
        await fulfillment(of: [gate.started], timeout: 3)
        XCTAssertFalse(store.hasSavedFrame)
        XCTAssertEqual(store.address, "")
        XCTAssertNil(store.api)
        XCTAssertNil(store.state)
        XCTAssertNil(store.availableUpdate)
        XCTAssertFalse(store.busy)
        XCTAssertFalse(store.displayBusy)
        XCTAssertFalse(store.loadingHistory)
        await fixture.login("new-frame.local")
        gate.release()
        await logout.value
        XCTAssertTrue(store.authenticated)
        XCTAssertTrue(store.hasSavedFrame)
        XCTAssertEqual(store.address, "http://new-frame.local:8000")
        XCTAssertEqual(store.state?.display.model, "new-frame.local")
    }

    func testOldHistoryPageCannotAppendToNewFrame() async throws {
        let fixture = StoreFixture(totals: ["old-frame.local": 200, "new-frame.local": 1])
        defer { fixture.dispose() }
        let store = fixture.store
        await fixture.login("old-frame.local")
        let history = fixture.stub.hold(host: "old-frame.local", path: "/api/history")
        let loading = Task { await store.loadMoreHistory() }
        await fulfillment(of: [history.started], timeout: 3)
        let logoutGate = fixture.stub.hold(host: "old-frame.local", path: "/api/auth/logout")
        let logout = Task { await store.logout() }
        await fulfillment(of: [logoutGate.started], timeout: 3)
        await fixture.login("new-frame.local")
        history.release()
        await loading.value
        XCTAssertEqual(store.history.count, 1)
        XCTAssertEqual(store.history.first?.photo.originalFilename, "new-frame.local.png")
        XCTAssertFalse(store.loadingHistory)
        XCTAssertTrue(store.authenticated)
        logoutGate.release()
        await logout.value
    }

    func testUnauthorizedOldThumbnailCannotSignOutNewFrame() async throws {
        let fixture = StoreFixture(totals: ["old-frame.local": 1])
        defer { fixture.dispose() }
        let store = fixture.store
        await fixture.login("old-frame.local")
        let photo = try XCTUnwrap(store.history.first?.photo)
        let imageGate = fixture.stub.hold(host: "old-frame.local", path: "/api/photos/\(photo.id)")
        let image = Task { await store.image(for: photo) }
        await fulfillment(of: [imageGate.started], timeout: 3)
        let logoutGate = fixture.stub.hold(host: "old-frame.local", path: "/api/auth/logout")
        let logout = Task { await store.logout() }
        await fulfillment(of: [logoutGate.started], timeout: 3)
        await fixture.login("new-frame.local")
        imageGate.release(status: 401)
        _ = await image.value
        XCTAssertTrue(store.authenticated)
        XCTAssertTrue(store.connected)
        XCTAssertNil(store.errorMessage)
        logoutGate.release()
        await logout.value
    }

    func testOldOperationCannotClearNewBusyFlagOrPublishOldUpdate() async throws {
        let fixture = StoreFixture()
        defer { fixture.dispose() }
        let store = fixture.store
        await fixture.login("old-frame.local")
        let oldUpdate = fixture.stub.hold(host: "old-frame.local", path: "/api/system/update")
        let updateTask = Task { await store.checkUpdate() }
        await fulfillment(of: [oldUpdate.started], timeout: 3)
        let logoutGate = fixture.stub.hold(host: "old-frame.local", path: "/api/auth/logout")
        let logout = Task { await store.logout() }
        await fulfillment(of: [logoutGate.started], timeout: 3)
        await fixture.login("new-frame.local")
        let newSettings = fixture.stub.hold(host: "new-frame.local", path: "/api/settings", method: "POST")
        let settingsTask = Task { await store.saveSettings(FrameSettings()) }
        await fulfillment(of: [newSettings.started], timeout: 3)
        oldUpdate.release()
        await updateTask.value
        XCTAssertTrue(store.busy)
        XCTAssertNil(store.availableUpdate)
        newSettings.release()
        await settingsTask.value
        XCTAssertFalse(store.busy)
        logoutGate.release()
        await logout.value
    }

    func testOldRefreshCannotBlockOrOverwriteNewFrameRefresh() async throws {
        let fixture = StoreFixture()
        defer { fixture.dispose() }
        let store = fixture.store
        await fixture.login("old-frame.local")
        let stateGate = fixture.stub.hold(host: "old-frame.local", path: "/api/state")
        let refresh = Task { await store.refresh() }
        await fulfillment(of: [stateGate.started], timeout: 3)
        let logoutGate = fixture.stub.hold(host: "old-frame.local", path: "/api/auth/logout")
        let logout = Task { await store.logout() }
        await fulfillment(of: [logoutGate.started], timeout: 3)
        await fixture.login("new-frame.local")
        XCTAssertEqual(store.state?.display.model, "new-frame.local")
        XCTAssertFalse(store.refreshing)
        stateGate.release()
        await refresh.value
        XCTAssertEqual(store.state?.display.model, "new-frame.local")
        XCTAssertFalse(store.refreshing)
        logoutGate.release()
        await logout.value
    }

    func testRefreshPreservesMoreThanFiveHundredLoadedHistoryRowsUsingBoundedPages() async throws {
        let fixture = StoreFixture(totals: ["large-frame.local": 650])
        defer { fixture.dispose() }
        let store = fixture.store
        await fixture.login("large-frame.local")
        for _ in 0..<6 { await store.loadMoreHistory() }
        XCTAssertEqual(store.history.count, 650)
        XCTAssertFalse(store.hasMoreHistory)
        await store.refresh()
        XCTAssertEqual(store.history.count, 650)
        XCTAssertEqual(Set(store.history.map(\.id)).count, 650)
        XCTAssertFalse(store.hasMoreHistory)
        XCTAssertNil(store.errorMessage)
        let limits = fixture.stub.requests.filter { $0.url?.path == "/api/history" }.compactMap {
            URLComponents(url: $0.url!, resolvingAgainstBaseURL: false)?.queryItems?.first { $0.name == "limit" }?.value
        }.compactMap(Int.init)
        XCTAssertFalse(limits.isEmpty)
        XCTAssertTrue(limits.allSatisfy { $0 > 0 && $0 <= 500 })
    }

    func testHistoryPageStartedBeforeRefreshCannotCorruptRefreshedList() async throws {
        let fixture = StoreFixture(totals: ["frame.local": 250])
        defer { fixture.dispose() }
        let store = fixture.store
        await fixture.login("frame.local")
        let gate = fixture.stub.hold(host: "frame.local", path: "/api/history")
        let pagination = Task { await store.loadMoreHistory() }
        await fulfillment(of: [gate.started], timeout: 3)
        await store.refresh()
        gate.release()
        await pagination.value
        XCTAssertEqual(store.history.count, 100)
        XCTAssertTrue(store.hasMoreHistory)
        XCTAssertFalse(store.loadingHistory)
    }
}

@MainActor
private final class StoreFixture {
    let suite = "InkyStoreTests.\(UUID().uuidString)"
    let defaults: UserDefaults
    let stub: StoreStub
    let store: AppStore

    init(totals: [String: Int] = [:]) {
        let defaults = UserDefaults(suiteName: suite)!
        self.defaults = defaults
        let stub = StoreStub(totals: totals)
        self.stub = stub
        store = AppStore(defaults: defaults,
                         makeAPI: { InkyAPI(baseURL: $0, configuration: stub.configuration()) },
                         vault: BiometricVault(service: "fr.mehdiguiard.inkystudio.tests.\(UUID().uuidString)"))
        // Monitoring is covered by integration tests; protocol tests control every
        // HTTP completion and must not contact a real WebSocket endpoint.
        store.sceneActive(false)
    }

    func login(_ host: String) async {
        store.address = host
        await store.login(password: "synthetic-test-password")
        XCTAssertTrue(store.authenticated)
        XCTAssertTrue(store.connected)
    }

    func dispose() {
        store.sceneActive(false)
        store.api?.clearSession()
        defaults.removePersistentDomain(forName: suite)
        stub.dispose()
    }
}

private final class StoreGate: @unchecked Sendable {
    let started = XCTestExpectation(description: "Held request started")
    private let lock = NSLock()
    private var completion: ((Int?) -> Void)?
    func hold(_ callback: @escaping (Int?) -> Void) {
        lock.withLock { completion = callback }
        started.fulfill()
    }
    func release(status: Int? = nil) {
        let callback = lock.withLock { let result = completion; completion = nil; return result }
        callback?(status)
    }
}

private final class StoreStub: @unchecked Sendable {
    private let id = UUID().uuidString
    private let lock = NSLock()
    private let totals: [String: Int]
    private var gates: [String: StoreGate] = [:]
    private var calls: [URLRequest] = []
    var requests: [URLRequest] { lock.withLock { calls } }
    init(totals: [String: Int]) { self.totals = totals }

    func hold(host: String, path: String, method: String = "GET") -> StoreGate {
        let gate = StoreGate()
        let verb = path == "/api/auth/logout" ? "POST" : method
        lock.withLock { gates["\(host)|\(verb)|\(path)"] = gate }
        return gate
    }

    func configuration() -> URLSessionConfiguration {
        StoreURLProtocol.register(self, id: id)
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [StoreURLProtocol.self]
        configuration.httpAdditionalHeaders = ["X-Inky-Store-Test": id]
        return configuration
    }

    func dispose() { StoreURLProtocol.remove(id: id) }

    func respond(_ request: URLRequest, completion: @escaping (Data, Int) -> Void) {
        let host = request.url!.host!
        let path = request.url!.path
        let key = "\(host)|\(request.httpMethod ?? "GET")|\(path)"
        let gate = lock.withLock { calls.append(request); return gates.removeValue(forKey: key) }
        let body: Any
        switch path {
        case "/api/auth/status", "/api/auth/logout": body = ["authenticated": false, "auth_required": true]
        case "/api/auth/login": body = ["authenticated": true, "auth_required": true]
        case "/api/health": body = ["status": "ok", "version": "0.4.2"]
        case "/api/state": body = ["display": ["model": host, "width": 800, "height": 480, "colors": 6, "is_mock": true], "current": NSNull(), "queue_count": 0, "next_change_at": NSNull()]
        case "/api/settings": body = ["change_mode": "daily", "change_hour": 5, "change_interval_minutes": 60, "saturation": 1]
        case "/api/system/update": body = ["current": "0.4.2", "latest": "0.4.3", "update_available": true]
        case "/api/history":
            let query = URLComponents(url: request.url!, resolvingAgainstBaseURL: false)!.queryItems ?? []
            let limit = Int(query.first { $0.name == "limit" }?.value ?? "100")!
            let offset = Int(query.first { $0.name == "offset" }?.value ?? "0")!
            let total = totals[host] ?? 0
            let end = min(total, offset + limit)
            body = offset < end ? (offset..<end).map { index -> [String: Any] in
                ["id": index + 1, "displayed_at": 1780000000, "source": "test", "photo": [
                    "id": "photo-\(index)", "sha256": "digest-\(index)", "original_filename": "\(host).png", "mime": "image/png",
                    "width": 800, "height": 480, "size_bytes": 10, "created_at": 1780000000,
                ]]
            } : []
        default: body = []
        }
        let data = try! JSONSerialization.data(withJSONObject: body)
        if let gate { gate.hold { status in completion(data, status ?? 200) } }
        else { completion(data, 200) }
    }
}

private final class StoreURLProtocol: URLProtocol, @unchecked Sendable {
    private static let lock = NSLock()
    nonisolated(unsafe) private static var stubs: [String: StoreStub] = [:]
    private let responseLock = NSLock()
    private var stopped = false
    static func register(_ stub: StoreStub, id: String) { lock.withLock { stubs[id] = stub } }
    static func remove(id: String) { _ = lock.withLock { stubs.removeValue(forKey: id) } }
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        let id = request.value(forHTTPHeaderField: "X-Inky-Store-Test") ?? ""
        guard let stub = Self.lock.withLock({ Self.stubs[id] }) else {
            client?.urlProtocol(self, didFailWithError: URLError(.resourceUnavailable))
            return
        }
        stub.respond(request) { [weak self] data, status in
            guard let self, !self.responseLock.withLock({ self.stopped }) else { return }
            let response = HTTPURLResponse(url: self.request.url!, statusCode: status, httpVersion: "HTTP/1.1",
                                           headerFields: ["Content-Type": "application/json"])!
            self.client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
            self.client?.urlProtocol(self, didLoad: data)
            self.client?.urlProtocolDidFinishLoading(self)
        }
    }

    override func stopLoading() { responseLock.withLock { stopped = true } }
}
