import XCTest

/// End-to-end coverage against ios/scripts/mock-server.py, never a real frame.
/// The fixture must be running on the host's loopback port 8765 before xcodebuild.
@MainActor
final class InkyStudioUITests: XCTestCase {
    private var app: XCUIApplication!
    private let fixtureURL = URL(string: "http://127.0.0.1:8765")!

    private func launchFixtureApp() {
        continueAfterFailure = false
        resetFixture()
        app = XCUIApplication()
        app.launchArguments = ["--uitesting", "--frame-address", fixtureURL.absoluteString]
        app.launch()
        addTeardownBlock { @MainActor [weak self] () async throws in
            self?.finish()
        }
    }

    private func finish() {
        if let app, (testRun?.failureCount ?? 0) > 0 {
            let screenshot = XCTAttachment(screenshot: app.screenshot())
            screenshot.name = "Failure — \(name)"
            screenshot.lifetime = .keepAlways
            add(screenshot)
        }
        app?.terminate()
        app = nil
    }

    /// Requires Xcode 27 and the fixture's opt-in --biometric-device mode.
    func testFaceIDReconnectAndPasswordFallback() throws {
        let configuration = try Data(contentsOf: fixtureURL.appendingPathComponent("__test/biometrics"))
        let enabled = (try JSONSerialization.jsonObject(with: configuration) as? [String: Bool])?["enabled"] == true
        try XCTSkipUnless(enabled, "Use mock-server.py --biometric-device <booted-simulator-UDID> for Face ID.")
        launchFixtureApp()
        let remember = app.switches["Activer Face ID"]
        XCTAssertTrue(remember.waitForExistence(timeout: 10), "Enrolled Face ID must be offered during the first connection.")
        remember.tap()
        XCTAssertEqual(remember.value as? String, "1")
        login()
        tab("settings", fallback: "Réglages").tap()
        let biometric = app.switches["settings.biometric"]
        scrollTo(biometric)
        XCTAssertEqual(biometric.value as? String, "1", "The opted-in password must be saved in the biometric Keychain.")
        let logout = app.buttons["settings.logout"]
        scrollTo(logout)
        logout.tap()
        let faceID = app.buttons["connection.biometric"]
        XCTAssertTrue(faceID.waitForExistence(timeout: 10))
        capture("04 Connexion Face ID")
        faceID.tap()
        // First Keychain access may ask for the app's Face ID permission.
        let springboard = XCUIApplication(bundleIdentifier: "com.apple.springboard")
        let permission = springboard.alerts.buttons["OK"]
        if permission.waitForExistence(timeout: 3) { permission.tap() }
        var request = URLRequest(url: fixtureURL.appendingPathComponent("__test/biometrics"))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = Data(#"{"event":"success"}"#.utf8)
        let matched = expectation(description: "Simulated Face ID match")
        URLSession.shared.dataTask(with: request) { _, response, error in
            XCTAssertNil(error)
            XCTAssertEqual((response as? HTTPURLResponse)?.statusCode, 200)
            matched.fulfill()
        }.resume()
        wait(for: [matched], timeout: 15)
        XCTAssertTrue(element("frame.add").waitForExistence(timeout: 10), "A matching simulated face must retrieve the Keychain password and reconnect to the frame.")
        tab("settings", fallback: "Réglages").tap()
        scrollTo(logout)
        logout.tap()
        XCTAssertTrue(faceID.waitForExistence(timeout: 10))
        app.buttons["Utiliser le mot de passe"].tap()
        XCTAssertTrue(app.secureTextFields["connection.password"].waitForExistence(timeout: 5))
        login()
        tab("settings", fallback: "Réglages").tap()
        scrollTo(biometric)
        biometric.tap()
        XCTAssertEqual(biometric.value as? String, "0")
        scrollTo(logout)
        logout.tap()
        XCTAssertTrue(app.secureTextFields["connection.password"].waitForExistence(timeout: 10))
        XCTAssertFalse(faceID.exists, "Disabling Face ID must remove the saved login action.")
    }

    func testImportPhotoCropAndUpload() {
        launchFixtureApp()
        login()
        let addPhoto = app.buttons["frame.add"]
        scrollTo(addPhoto)
        addPhoto.tap()
        // Seed the simulator with scripts/seed-simulator-photo.py before this suite.
        let selectedPhoto = app.images.matching(identifier: "PXGGridLayout-Info").firstMatch
        XCTAssertTrue(selectedPhoto.waitForExistence(timeout: 15), "PhotosPicker needs a seeded simulator photo.\n\(app.debugDescription)")
        selectedPhoto.tap()
        let upload = app.buttons["upload-photo"]
        XCTAssertTrue(upload.waitForExistence(timeout: 15), "Selecting a native Photos item must open the crop view.")
        let zoom = app.sliders["Zoom de la photo"]
        XCTAssertTrue(zoom.waitForExistence(timeout: 5))
        zoom.adjust(toNormalizedSliderPosition: 0.18)
        app.buttons["Réinitialiser"].tap()
        capture("05 Cadrage")
        upload.tap()
        XCTAssertTrue(upload.waitForNonExistence(timeout: 15), "A successful upload must dismiss the crop sheet.")
        tab("queue", fallback: "File").tap()
        XCTAssertTrue(app.staticTexts["3 photos dans la file"].waitForExistence(timeout: 10), "The newly cropped PNG must join the queue.")
    }

    func testInvalidPasswordThenConnectAndVisitAllTabs() {
        launchFixtureApp()
        let password = app.secureTextFields["connection.password"]
        XCTAssertTrue(password.waitForExistence(timeout: 10))
        password.tap()
        password.typeText("wrong-password")
        app.buttons["connection.submit"].tap()
        let error = app.staticTexts.matching(NSPredicate(format: "label CONTAINS[cd] %@", "incorrect")).firstMatch
        XCTAssertTrue(error.waitForExistence(timeout: 10), "An invalid password must show a readable error.")
        XCTAssertTrue(password.exists, "Authentication errors must keep the login screen available.")
        password.tap()
        password.typeText(String(repeating: XCUIKeyboardKey.delete.rawValue, count: "wrong-password".count))
        password.typeText("test-password")
        app.buttons["connection.submit"].tap()
        XCTAssertTrue(element("frame.add").waitForExistence(timeout: 10))
        capture("01 Cadre")

        tab("queue", fallback: "File").tap()
        XCTAssertTrue(element("queue.row.a11050000002").waitForExistence(timeout: 5))
        capture("02 File")
        tab("history", fallback: "Historique").tap()
        XCTAssertTrue(app.buttons["history.requeue.2"].waitForExistence(timeout: 5))
        capture("03 Historique")
        tab("settings", fallback: "Réglages").tap()
        XCTAssertTrue(element("settings.save").waitForExistence(timeout: 5))
        capture("06 Réglages")
    }

    func testQueueRemovalAndHistoryRequeue() {
        launchFixtureApp()
        login()
        tab("queue", fallback: "File").tap()
        let row = element("queue.row.a11050000002")
        XCTAssertTrue(row.waitForExistence(timeout: 5))
        app.buttons["queue.edit"].tap()
        XCTAssertEqual(app.buttons["queue.edit"].label, "Terminer")
        app.buttons["queue.edit"].tap()
        row.swipeLeft()
        let remove = app.buttons["queue.remove.a11050000002"]
        XCTAssertTrue(remove.waitForExistence(timeout: 5))
        remove.tap()
        // Support a confirmation if the interface asks before removing a photo.
        let confirmation = app.sheets.buttons["Retirer"]
        if confirmation.waitForExistence(timeout: 2) { confirmation.tap() }
        XCTAssertTrue(row.waitForNonExistence(timeout: 5), "Removing a queued photo must update the list.")
        tab("history", fallback: "Historique").tap()
        let requeue = app.buttons["history.requeue.2"]
        XCTAssertTrue(requeue.waitForExistence(timeout: 5))
        requeue.tap()
        tab("queue", fallback: "File").tap()
        XCTAssertTrue(element("queue.row.c0a570000001").waitForExistence(timeout: 10), "A displayed photo can be put back in the queue.")
    }

    func testSettingsSaveAndLogout() {
        launchFixtureApp()
        login()
        tab("settings", fallback: "Réglages").tap()
        let manual = app.segmentedControls["settings.mode"].buttons["Manuel"]
        XCTAssertTrue(manual.waitForExistence(timeout: 5))
        manual.tap()
        let save = app.buttons["settings.save"]
        scrollTo(save)
        XCTAssertTrue(save.isHittable)
        save.tap()
        XCTAssertTrue(app.staticTexts["Réglages enregistrés."].waitForExistence(timeout: 10))
        let logout = app.buttons["settings.logout"]
        scrollTo(logout)
        XCTAssertTrue(logout.isHittable)
        logout.tap()
        if app.alerts.firstMatch.waitForExistence(timeout: 1) {
            let confirm = app.alerts.buttons.matching(NSPredicate(format: "label CONTAINS[cd] %@", "déconnecter")).firstMatch
            if confirm.exists { confirm.tap() }
        }
        XCTAssertTrue(app.secureTextFields["connection.password"].waitForExistence(timeout: 10))
        XCTAssertFalse(element("frame.next").exists, "Authenticated actions must disappear after logout.")
    }

    func testNextPhotoConsumesQueueAndUpdatesFrame() {
        launchFixtureApp()
        login()
        let next = app.buttons["frame.next"]
        scrollTo(next)
        XCTAssertTrue(next.isHittable)
        next.tap()
        XCTAssertTrue(app.staticTexts.matching(NSPredicate(format: "label CONTAINS %@", "Lac d'Allos")).firstMatch.waitForExistence(timeout: 10))
        tab("queue", fallback: "File").tap()
        XCTAssertTrue(element("queue.row.a11050000002").waitForNonExistence(timeout: 5))
        XCTAssertTrue(element("queue.row.5ad000000003").exists)
    }

    func testUnavailableFrameShowsRecoverableError() {
        launchFixtureApp()
        app.terminate()
        app.launchArguments = ["--uitesting", "--frame-address", "http://127.0.0.1:8766"]
        app.launch()
        let password = app.secureTextFields["connection.password"]
        XCTAssertTrue(password.waitForExistence(timeout: 10))
        password.tap()
        password.typeText("test-password")
        app.buttons["connection.submit"].tap()
        let error = app.staticTexts.matching(NSPredicate(format: "label CONTAINS[cd] %@", "injoignable")).firstMatch
        let foundError = error.waitForExistence(timeout: 40)
        capture("Offline connection result")
        XCTAssertTrue(foundError, "An unreachable frame needs an actionable connection error.\n\(app.debugDescription)")
        XCTAssertTrue(app.buttons["connection.submit"].isEnabled, "The user must be able to retry.")
    }

    private func login() {
        let password = app.secureTextFields["connection.password"]
        XCTAssertTrue(password.waitForExistence(timeout: 10))
        password.tap()
        password.typeText("test-password")
        app.buttons["connection.submit"].tap()
        XCTAssertTrue(element("frame.add").waitForExistence(timeout: 10), "Login must reveal the frame dashboard.")
    }

    private func element(_ identifier: String) -> XCUIElement {
        app.descendants(matching: .any).matching(identifier: identifier).firstMatch
    }

    private func tab(_ identifier: String, fallback: String) -> XCUIElement {
        let identified = app.buttons["tab.\(identifier)"]
        return identified.exists ? identified : app.tabBars.buttons[fallback]
    }

    private func scrollTo(_ target: XCUIElement) {
        for _ in 0..<6 {
            if target.isHittable { return }
            app.swipeUp()
        }
    }

    private func capture(_ title: String) {
        let attachment = XCTAttachment(screenshot: app.screenshot())
        attachment.name = title
        attachment.lifetime = .keepAlways
        add(attachment)
    }

    private func resetFixture() {
        let ready = expectation(description: "Local fixture reset")
        var request = URLRequest(url: fixtureURL.appendingPathComponent("__test/reset"))
        request.httpMethod = "POST"
        request.timeoutInterval = 5
        URLSession.shared.dataTask(with: request) { _, response, error in
            XCTAssertNil(error, "Start python3 ios/scripts/mock-server.py before running UI tests.")
            XCTAssertEqual((response as? HTTPURLResponse)?.statusCode, 200)
            ready.fulfill()
        }.resume()
        wait(for: [ready], timeout: 7)
    }
}
