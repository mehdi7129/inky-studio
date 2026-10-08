import Combine
import XCTest
@testable import InkyStudio

@MainActor
final class AppStoreTests: XCTestCase {
    func testCancelledRefreshPreservesConnectionAndLoadedState() async throws {
        let fixture = StoreFixture(totals: ["frame.local": 1])
        defer { fixture.dispose() }
        let store = fixture.store
        await fixture.login("frame.local")
        let gate = fixture.stub.hold(host: "frame.local", path: "/api/state")
        let refresh = Task { await store.refresh() }
        await fulfillment(of: [gate.started], timeout: 3)

        refresh.cancel()
        await refresh.value

        XCTAssertTrue(store.authenticated)
        XCTAssertTrue(store.connected, "Cancelling a refresh does not establish that the frame is offline.")
        XCTAssertFalse(store.refreshing)
        XCTAssertEqual(store.state?.display.model, "frame.local")
        XCTAssertEqual(store.history.count, 1)
        XCTAssertNil(store.errorMessage)
    }

    func testRequestedRefreshRunsAfterInFlightRefreshFails() async throws {
        let fixture = StoreFixture()
        defer { fixture.dispose() }
        let store = fixture.store
        await fixture.login("frame.local")
        let before = fixture.stub.requests.filter { $0.url?.path == "/api/state" }.count
        let gate = fixture.stub.hold(host: "frame.local", path: "/api/state")
        let refresh = Task { await store.refresh() }
        await fulfillment(of: [gate.started], timeout: 3)

        // A foreground return or explicit retry arrives before the old failure.
        await store.refresh()
        gate.release(status: 503)
        await refresh.value

        let after = fixture.stub.requests.filter { $0.url?.path == "/api/state" }.count
        XCTAssertEqual(after - before, 2, "The explicitly requested retry must survive the in-flight failure.")
        XCTAssertTrue(store.authenticated)
        XCTAssertTrue(store.connected)
        XCTAssertFalse(store.refreshing)
        XCTAssertNil(store.errorMessage, "A recovered refresh must clear its transient failure message.")
    }

    func testRecoveredRefreshPreservesNewerOperationError() async throws {
        let fixture = StoreFixture()
        defer { fixture.dispose() }
        let store = fixture.store
        await fixture.login("frame.local")
        let updateGate = fixture.stub.hold(host: "frame.local", path: "/api/system/update")
        let update = Task { await store.checkUpdate() }
        await fulfillment(of: [updateGate.started], timeout: 3)
        let refreshGate = fixture.stub.hold(host: "frame.local", path: "/api/state")
        let refresh = Task { await store.refresh() }
        await fulfillment(of: [refreshGate.started], timeout: 3)
        refreshGate.release(status: 503)
        await refresh.value
        XCTAssertFalse(store.connected)
        XCTAssertNotNil(store.errorMessage)

        updateGate.release(status: 422)
        await update.value
        let operationError = try XCTUnwrap(store.errorMessage)
        await store.refresh()

        XCTAssertTrue(store.connected)
        XCTAssertTrue(store.authenticated)
        XCTAssertEqual(store.errorMessage, operationError,
                       "Recovering the connection must not erase a newer operation error.")
    }

    func testRequestedRefreshRunsInNewTaskAfterCancellation() async throws {
        let fixture = StoreFixture()
        defer { fixture.dispose() }
        let store = fixture.store
        await fixture.login("frame.local")
        fixture.enterForegroundWithoutMonitoring()
        let before = fixture.stub.requests.filter { $0.url?.path == "/api/state" }.count
        let cancelledGate = fixture.stub.hold(host: "frame.local", path: "/api/state")
        let refresh = Task { await store.refresh() }
        await fulfillment(of: [cancelledGate.started], timeout: 3)
        await store.refresh()
        let retryGate = fixture.stub.hold(host: "frame.local", path: "/api/state")

        refresh.cancel()
        await refresh.value
        await fulfillment(of: [retryGate.started], timeout: 3)
        XCTAssertTrue(store.refreshing)
        let finished = expectation(description: "Pending refresh completed")
        let observation = store.$refreshing.dropFirst().filter { !$0 }.sink { _ in finished.fulfill() }
        defer { observation.cancel() }
        retryGate.release()
        await fulfillment(of: [finished], timeout: 3)

        let after = fixture.stub.requests.filter { $0.url?.path == "/api/state" }.count
        XCTAssertEqual(after - before, 2, "Cancellation must hand the requested refresh to a non-cancelled task exactly once.")
        XCTAssertFalse(store.refreshing)
        XCTAssertTrue(store.connected)
        XCTAssertTrue(store.authenticated)
        XCTAssertNil(store.errorMessage)
    }

    func testCancelledRefreshDoesNotRetryAfterEnteringBackground() async throws {
        let fixture = StoreFixture()
        defer { fixture.dispose() }
        let store = fixture.store
        await fixture.login("frame.local")
        fixture.enterForegroundWithoutMonitoring()
        let cancelledGate = fixture.stub.hold(host: "frame.local", path: "/api/state")
        let refresh = Task { await store.refresh() }
        await fulfillment(of: [cancelledGate.started], timeout: 3)
        await store.refresh()
        let unexpectedRetry = fixture.stub.hold(host: "frame.local", path: "/api/state")
        unexpectedRetry.started.isInverted = true

        store.sceneActive(false)
        refresh.cancel()
        await refresh.value
        await fulfillment(of: [unexpectedRetry.started], timeout: 0.2)

        XCTAssertFalse(store.refreshing)
        XCTAssertTrue(store.authenticated)
        XCTAssertTrue(store.connected)
        XCTAssertNil(store.errorMessage)
    }

    func testCancelledOldRefreshCannotRetryInNewSession() async throws {
        let fixture = StoreFixture()
        defer { fixture.dispose() }
        let store = fixture.store
        await fixture.login("old-frame.local")
        fixture.enterForegroundWithoutMonitoring()
        let cancelledGate = fixture.stub.hold(host: "old-frame.local", path: "/api/state")
        let refresh = Task { await store.refresh() }
        await fulfillment(of: [cancelledGate.started], timeout: 3)
        await store.refresh()

        store.sceneActive(false)
        await fixture.login("new-frame.local")
        fixture.enterForegroundWithoutMonitoring()
        let unexpectedRetry = fixture.stub.hold(host: "new-frame.local", path: "/api/state")
        unexpectedRetry.started.isInverted = true
        refresh.cancel()
        await refresh.value
        await fulfillment(of: [unexpectedRetry.started], timeout: 0.2)

        XCTAssertEqual(store.state?.display.model, "new-frame.local")
        XCTAssertEqual(fixture.stub.requests.filter {
            $0.url?.host == "old-frame.local" && $0.url?.path == "/api/state"
        }.count, 2, "Only the login snapshot and the cancelled refresh may use the old frame.")
        XCTAssertFalse(store.refreshing)
        XCTAssertTrue(store.authenticated)
        XCTAssertTrue(store.connected)
        XCTAssertNil(store.errorMessage)
    }

    func testForegroundAndPhotoReadsWaitForPasswordRotation() async throws {
        let fixture = StoreFixture(totals: ["frame.local": 101])
        defer { fixture.dispose() }
        let store = fixture.store
        await fixture.login("frame.local")
        let photo = try XCTUnwrap(store.history.first?.photo)
        let gate = fixture.stub.hold(host: "frame.local", path: "/api/auth/password", method: "POST")
        let changing = Task { await store.changePassword(current: "previous-test-password", new: "new-test-password") }
        await fulfillment(of: [gate.started], timeout: 3)
        let before = fixture.stub.requests.count
        store.sceneActive(true)
        await store.refresh()
        await store.loadMoreHistory()
        _ = await store.image(for: photo)
        await Task.yield()
        XCTAssertEqual(fixture.stub.requests.count, before, "Foreground refreshes must not use the old cookie during rotation.")
        store.sceneActive(false)
        gate.release()
        guard case .success = await changing.value else { return XCTFail("Expected successful rotation") }
        XCTAssertTrue(store.authenticated)
        XCTAssertTrue(store.connected)
        await store.refresh()
        XCTAssertGreaterThan(fixture.stub.requests.count, before)
    }

    func testPasswordRotationKeepsSessionAndRejectsOldRefresh() async throws {
        let fixture = StoreFixture()
        defer { fixture.dispose() }
        let store = fixture.store
        await fixture.login("frame.local")
        XCTAssertTrue(store.passwordChangeSupported)
        let gate = fixture.stub.hold(host: "frame.local", path: "/api/state")
        let refresh = Task { await store.refresh() }
        await fulfillment(of: [gate.started], timeout: 3)
        let result = await store.changePassword(current: "previous-test-password", new: "new-test-password")
        guard case .success = result else { return XCTFail("Expected successful rotation") }
        gate.release(status: 401)
        await refresh.value
        XCTAssertTrue(store.authenticated, "A refresh sent before rotation must not revoke the new session.")
        XCTAssertTrue(store.connected)
        XCTAssertFalse(store.busy)
        XCTAssertNil(store.errorMessage)
        XCTAssertEqual(fixture.stub.requests.filter { $0.url?.path == "/api/auth/password" }.count, 1)
    }

    func testWrongCurrentPasswordDoesNotSignOut() async throws {
        let fixture = StoreFixture()
        defer { fixture.dispose() }
        await fixture.login("frame.local")
        let gate = fixture.stub.hold(host: "frame.local", path: "/api/auth/password", method: "POST")
        let changing = Task { await fixture.store.changePassword(current: "wrong", new: "new-test-password") }
        await fulfillment(of: [gate.started], timeout: 3)
        gate.release(status: 403)
        guard case .failure = await changing.value else { return XCTFail("Expected rejection") }
        XCTAssertTrue(fixture.store.authenticated)
        XCTAssertTrue(fixture.store.connected)
        XCTAssertFalse(fixture.store.busy)
    }

    func testUnconfirmedPasswordRotationRequiresExplicitReconnect() async throws {
        let fixture = StoreFixture()
        defer { fixture.dispose() }
        await fixture.login("frame.local")
        fixture.store.biometricEnabled = true
        let gate = fixture.stub.hold(host: "frame.local", path: "/api/auth/password", method: "POST")
        let changing = Task { await fixture.store.changePassword(current: "previous-test-password", new: "new-test-password") }
        await fulfillment(of: [gate.started], timeout: 3)
        gate.release(status: 502)
        guard case .failure(let message) = await changing.value else { return XCTFail("Expected uncertain result") }
        XCTAssertTrue(message.contains("nouveau mot de passe"))
        XCTAssertFalse(fixture.store.authenticated)
        XCTAssertFalse(fixture.store.biometricEnabled)
        XCTAssertEqual(fixture.stub.requests.filter { $0.url?.path == "/api/auth/password" }.count, 1)
    }

    func testLegacyFrameDoesNotOfferOrSendPasswordRotation() async throws {
        let fixture = StoreFixture()
        defer { fixture.dispose() }
        await fixture.login("legacy-frame.local")
        XCTAssertFalse(fixture.store.passwordChangeSupported)
        guard case .failure = await fixture.store.changePassword(current: "old", new: "new-test-password") else { return XCTFail("Expected unsupported operation") }
        XCTAssertFalse(fixture.stub.requests.contains { $0.url?.path == "/api/auth/password" })
    }

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

    func enterForegroundWithoutMonitoring() {
        // Exercise foreground-only refresh behavior without opening a real WebSocket.
        let authenticated = store.authenticated
        store.authenticated = false
        store.sceneActive(true)
        store.authenticated = authenticated
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
        case "/api/auth/status", "/api/auth/logout": body = ["authenticated": false, "auth_required": true, "password_change_supported": host != "legacy-frame.local"]
        case "/api/auth/login", "/api/auth/password": body = ["authenticated": true, "auth_required": true, "password_change_supported": host != "legacy-frame.local"]
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
