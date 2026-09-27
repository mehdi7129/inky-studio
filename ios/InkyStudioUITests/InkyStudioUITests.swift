import XCTest

/// End-to-end coverage against ios/scripts/mock-server.py, never a real frame.
/// The fixture must be running on the host's loopback port 8765 before xcodebuild.
@MainActor
final class InkyStudioUITests: XCTestCase {
    private var app: XCUIApplication!
    private let fixtureURL = URL(string: "http://127.0.0.1:8765")!

    private func launchFixtureApp(resetCamera: Bool = false) {
        continueAfterFailure = false
        resetFixture()
        app = XCUIApplication()
        // Resetting a protected resource terminates an already-running app.
        if resetCamera { app.resetAuthorizationStatus(for: .camera) }
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
        selectTab("settings", fallback: "Réglages")
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
        selectTab("settings", fallback: "Réglages")
        scrollTo(logout)
        logout.tap()
        XCTAssertTrue(faceID.waitForExistence(timeout: 10))
        app.buttons["Utiliser le mot de passe"].tap()
        XCTAssertTrue(app.secureTextFields["connection.password"].waitForExistence(timeout: 5))
        login()
        selectTab("settings", fallback: "Réglages")
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
        let choosePhoto = app.buttons["choose-photo"]
        XCTAssertTrue(choosePhoto.waitForExistence(timeout: 5))
        choosePhoto.tap()
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
        selectTab("queue", fallback: "File")
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
        dismissPasswordSavePrompt()
        capture("01 Cadre")

        selectTab("queue", fallback: "File")
        XCTAssertTrue(element("queue.row.a11050000002").waitForExistence(timeout: 5))
        capture("02 File")
        selectTab("history", fallback: "Historique")
        XCTAssertTrue(app.buttons["history.requeue.2"].waitForExistence(timeout: 5))
        capture("03 Historique")
        selectTab("settings", fallback: "Réglages")
        XCTAssertTrue(element("settings.save").waitForExistence(timeout: 5))
        capture("06 Réglages")
    }

    func testQueueRemovalAndHistoryRequeue() {
        launchFixtureApp()
        login()
        selectTab("queue", fallback: "File")
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
        selectTab("history", fallback: "Historique")
        let requeue = app.buttons["history.requeue.2"]
        XCTAssertTrue(requeue.waitForExistence(timeout: 5))
        requeue.tap()
        selectTab("queue", fallback: "File")
        XCTAssertTrue(element("queue.row.c0a570000001").waitForExistence(timeout: 10), "A displayed photo can be put back in the queue.")
    }

    func testSettingsSaveAndLogout() {
        launchFixtureApp()
        login()
        selectTab("settings", fallback: "Réglages")
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
        XCTAssertTrue(app.staticTexts["Le cadre est à jour."].waitForExistence(timeout: 10))
        selectTab("queue", fallback: "File")
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
        dismissPasswordSavePrompt()
    }

    private func dismissPasswordSavePrompt() {
        if #available(iOS 27, *) {
            let later = app.buttons["Plus tard"]
            if later.waitForExistence(timeout: 6) {
                later.tap()
                XCTAssertTrue(later.waitForNonExistence(timeout: 5))
                return
            }
            let systemLater = XCUIApplication(bundleIdentifier: "com.apple.springboard").buttons["Plus tard"]
            if systemLater.waitForExistence(timeout: 2) {
                systemLater.tap()
                XCTAssertTrue(systemLater.waitForNonExistence(timeout: 5))
            }
        }
    }

    func testPhotoSourceCameraPermissionAndCancel() {
        launchFixtureApp(resetCamera: true)
        login()
        let addPhoto = app.buttons["frame.add"]
        scrollTo(addPhoto)
        addPhoto.tap()
        let camera = app.buttons["take-photo"]
        XCTAssertTrue(camera.waitForExistence(timeout: 5))
        XCTAssertTrue(app.buttons["choose-photo"].exists)
        camera.tap()
        let springboard = XCUIApplication(bundleIdentifier: "com.apple.springboard")
        // Some Simulator runtimes expose a camera. Permission belongs to the
        // system application; never assume the source is universally absent.
        if springboard.alerts.firstMatch.waitForExistence(timeout: 3) {
            let deny = springboard.alerts.buttons.matching(NSPredicate(format: "label IN %@", ["Ne pas autoriser", "Don’t Allow", "Don't Allow"])).firstMatch
            XCTAssertTrue(deny.exists)
            deny.tap()
        }
        XCTAssertTrue(app.alerts.firstMatch.waitForExistence(timeout: 5))
        capture("07 Appareil photo — permission ou indisponibilité")
        let later = app.alerts.buttons["Plus tard"]
        if later.exists { later.tap() } else { app.alerts.buttons["Annuler"].tap() }
        app.buttons["cancel-photo-import"].tap()
        XCTAssertTrue(addPhoto.waitForExistence(timeout: 5))
    }

    func testRoundedTabsWithoutFilenamesAndPortrait() {
        XCUIDevice.shared.orientation = .portrait
        launchFixtureApp()
        login()
        for (identifier, label, title) in [("frame", "Cadre", "Inky Studio"), ("queue", "File", "À suivre"), ("history", "Historique", "Historique"), ("settings", "Réglages", "Réglages")] {
            selectTab(identifier, fallback: label)
            XCTAssertTrue(app.navigationBars[title].waitForExistence(timeout: 5), "A compact visible title must identify each tab.")
            for name in ["Un matin à Cassis", "Lac d'Allos", "Ombres d'été"] {
                XCTAssertFalse(app.staticTexts.matching(NSPredicate(format: "label CONTAINS %@", name)).firstMatch.exists, "Photo filenames must not clutter the interface.")
            }
            capture("Bento arrondi — \(label)")
            XCUIDevice.shared.orientation = .landscapeLeft
            XCTAssertTrue(app.navigationBars[title].waitForExistence(timeout: 3))
            XCTAssertLessThan(app.windows.firstMatch.frame.width, app.windows.firstMatch.frame.height, "The app must remain in portrait.")
            XCUIDevice.shared.orientation = .portrait
        }
        selectTab("frame", fallback: "Cadre")
        let add = app.buttons["frame.add"]
        scrollTo(add)
        XCTAssertTrue(add.isHittable)
        XCTAssertLessThanOrEqual(add.frame.maxY, app.tabBars.firstMatch.frame.minY + 1, "The main action must not be covered by the tab bar.")
    }

    func testChangeFramePasswordAndReconnect() {
        launchFixtureApp()
        login()
        selectTab("settings", fallback: "Réglages")
        let change = app.buttons["settings.password"]
        scrollTo(change)
        XCTAssertTrue(change.isHittable)
        change.tap()
        for (field, value) in [("current", "test-password"), ("new", "my-new-frame-password"), ("confirmation", "my-new-frame-password")] {
            let input = app.secureTextFields["password.\(field)"]
            XCTAssertTrue(input.waitForExistence(timeout: 5))
            input.tap(); input.typeText(value)
        }
        let save = app.buttons["password.save"]
        scrollTo(save)
        save.tap()
        XCTAssertTrue(app.staticTexts["password.success"].waitForExistence(timeout: 10))
        capture("08 Mot de passe personnalisé")
        app.buttons["Terminer"].tap()
        let logout = app.buttons["settings.logout"]
        scrollTo(logout)
        logout.tap()
        let password = app.secureTextFields["connection.password"]
        XCTAssertTrue(password.waitForExistence(timeout: 5))
        password.tap(); password.typeText("my-new-frame-password")
        app.buttons["connection.submit"].tap()
        XCTAssertTrue(element("frame.add").waitForExistence(timeout: 10))
    }

    private func element(_ identifier: String) -> XCUIElement {
        app.descendants(matching: .any).matching(identifier: identifier).firstMatch
    }

    private func tab(_ identifier: String, fallback: String) -> XCUIElement {
        let identified = app.buttons["tab.\(identifier)"]
        return identified.exists ? identified : app.tabBars.buttons[fallback]
    }

    private func selectTab(_ identifier: String, fallback: String) {
        let target = tab(identifier, fallback: fallback)
        XCTAssertTrue(target.waitForExistence(timeout: 5))
        if #available(iOS 27, *) {
            // The floating native tab bar reports a valid AX frame but XCTest's
            // automatic hit point can be {-1,-1}. Use its observed frame and
            // verify the actual selection; no model-specific coordinates.
            let window = app.windows.firstMatch
            let rect = target.frame
            XCTAssertTrue(window.frame.contains(rect))
            XCTAssertGreaterThan(rect.width, 0)
            window.coordinate(withNormalizedOffset: .zero)
                .withOffset(CGVector(dx: rect.midX - window.frame.minX, dy: rect.midY - window.frame.minY)).tap()
        } else { target.tap() }
        XCTAssertTrue(waitForSelected(target), "The tab must actually become selected.")
    }

    private func waitForSelected(_ element: XCUIElement) -> Bool {
        let expectation = XCTNSPredicateExpectation(predicate: NSPredicate(format: "selected == true"), object: element)
        return XCTWaiter.wait(for: [expectation], timeout: 5) == .completed
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
