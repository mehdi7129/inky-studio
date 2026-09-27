import XCTest
@testable import InkyStudio

@MainActor
final class DemoModeTests: XCTestCase {
    func testDemoDoesNotCreateNetworkClientOrModifySavedConnection() async throws {
        let suite = "InkyDemoTests.\(UUID())"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        defaults.set("http://saved-frame.local:8000", forKey: "frameAddress")
        defaults.set(true, forKey: "biometricEnabled")
        defaults.set(UUID().uuidString, forKey: "frameOwnerID")
        let before = defaults.dictionaryRepresentation()
        let store = AppStore(defaults: defaults, makeAPI: { _ in
            XCTFail("A demo must never construct a network client")
            return InkyAPI(baseURL: URL(string: "http://127.0.0.1:1")!)
        }, vault: BiometricVault(service: "InkyDemoTests.\(UUID())"))
        store.address = "unsaved-edit.local:8000"
        await store.enterDemo()
        XCTAssertTrue(store.isDemo)
        XCTAssertTrue(store.canMutate)
        XCTAssertNil(store.api)
        XCTAssertEqual(store.queue.count, 2)
        XCTAssertEqual(store.history.count, 2)
        let image = await store.image(for: try XCTUnwrap(store.state?.current?.photo))
        XCTAssertNotNil(image)

        // These guards must hold even if an old view invokes a sensitive method.
        await store.login(password: "unused", rememberBiometric: false)
        await store.loginWithBiometrics()
        await store.enableBiometrics(password: "unused")
        store.disableBiometrics()
        let changed = await store.changePassword(current: "unused", new: "unused")
        guard case .failure = changed else { return XCTFail("No credential change in demo") }
        do { try await store.beginBluetoothAdoption(); XCTFail("No adoption in demo") }
        catch { XCTAssertEqual(error as? APIError, .unauthorized) }
        await store.checkUpdate()
        await store.startUpdate()
        XCTAssertFalse(store.updating)
        XCTAssertNil(store.availableUpdate)
        XCTAssertTrue(try XCTUnwrap(store.updateMessage).contains("Démonstration"))
        store.sceneActive(false)
        store.sceneActive(true)
        await store.refresh()
        XCTAssertTrue(store.isDemo)
        // Even the generic forget action is only an exit for a demo session.
        await store.logout(forget: true)
        XCTAssertFalse(store.isDemo)
        XCTAssertFalse(store.authenticated)
        XCTAssertNil(store.demoSampleData)
        XCTAssertEqual(store.address, "unsaved-edit.local:8000")
        XCTAssertTrue(store.biometricEnabled)
        XCTAssertEqual(defaults.dictionaryRepresentation() as NSDictionary, before as NSDictionary)
    }

    func testDemoMutationsResetAndExitDiscardSession() async throws {
        let suite = "InkyDemoTests.\(UUID())"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        let store = AppStore(defaults: defaults)
        await store.enterDemo()
        let originalSession = store.sessionIdentity
        let initial = store.queue.map { $0.photo.id }
        await store.reorder(Array(initial.reversed()))
        XCTAssertEqual(store.queue.map { $0.photo.id }, Array(initial.reversed()))
        let first = try XCTUnwrap(store.queue.first)
        await store.display(previous: false)
        XCTAssertEqual(store.state?.current?.photo.id, first.photo.id)
        XCTAssertEqual(store.queue.count, 1)
        XCTAssertTrue(try XCTUnwrap(store.notice).contains("simulé"))
        let displayed = try XCTUnwrap(store.history.first)
        await store.requeue(displayed)
        XCTAssertEqual(store.queue.count, 2)
        await store.requeue(displayed)
        XCTAssertEqual(store.queue.count, 2, "Requeue must deduplicate")
        await store.remove(try XCTUnwrap(store.queue.first))
        XCTAssertEqual(store.queue.count, 1)
        await store.saveSettings(FrameSettings(changeMode: .interval, changeIntervalMinutes: 30, saturation: 0.5))
        XCTAssertEqual(store.settings?.changeIntervalMinutes, 30)
        try await store.upload(try XCTUnwrap(store.demoSampleData), filename: "never-shown.png")
        XCTAssertEqual(store.queue.count, 2)
        await store.clearHistory()
        XCTAssertTrue(store.history.isEmpty)
        XCTAssertEqual(store.state?.current?.photo.id, first.photo.id, "Clearing history keeps the displayed image")
        await store.resetDemo()
        XCTAssertNotEqual(store.sessionIdentity, originalSession)
        XCTAssertEqual(store.queue.count, 2)
        XCTAssertEqual(store.history.count, 2)
        XCTAssertEqual(store.settings?.changeMode, .manual)
        store.exitDemo()
        XCTAssertNil(store.state)
        XCTAssertTrue(store.queue.isEmpty)
        XCTAssertTrue(store.history.isEmpty)
        XCTAssertNil(store.settings)
        XCTAssertNil(store.demoSampleData)
        let relaunched = AppStore(defaults: defaults)
        XCTAssertFalse(relaunched.isDemo)
        XCTAssertFalse(relaunched.authenticated)
    }

    func testDemoEntryCannotReplaceAnActiveOrConnectingSession() async {
        let store = AppStore()
        store.authenticated = true
        await store.enterDemo()
        XCTAssertFalse(store.isDemo)
        store.authenticated = false
        store.connecting = true
        await store.enterDemo()
        XCTAssertFalse(store.isDemo)
    }

    func testRetiredDemoClientRejectsLateOperationsAndPrunesRemovedImages() async throws {
        let client = DemoFrameClient()
        let entries = try await client.queue()
        let removed = try XCTUnwrap(entries.first)
        try await client.removeFromQueue(photoID: removed.photo.id)
        do { _ = try await client.photoData(id: removed.photo.id); XCTFail("Unreferenced images must be removed") }
        catch { XCTAssertEqual(error as? APIError, .invalidData) }
        let data = try XCTUnwrap(client.sampleData)
        client.clear()
        XCTAssertNil(client.sampleData)
        do { _ = try await client.upload(png: data, filename: "late.png"); XCTFail("Retired client accepted an upload") }
        catch { XCTAssertTrue(error is CancellationError) }
    }

    func testPreviousWalksHistoryWithoutBouncingBetweenRecentPhotos() async throws {
        let client = DemoFrameClient()
        let initial = try await client.history(limit: 100, offset: 0)
        try await client.next()
        try await client.previous()
        let firstPrevious = try await client.state()
        XCTAssertEqual(firstPrevious.current?.photo.id, initial[0].photo.id)
        try await client.previous()
        let secondPrevious = try await client.state()
        XCTAssertEqual(secondPrevious.current?.photo.id, initial[1].photo.id)
        do { try await client.previous(); XCTFail("Reached the beginning of history") }
        catch { XCTAssertTrue(error is APIError) }
    }
}
