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
        let teardown: @MainActor @Sendable () -> Void = { [weak self] in
            self?.finish()
        }
        addTeardownBlock(teardown)
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
    func testFaceIDReconnectAndPasswordFallback() async throws {
        let configurationRequest = URLRequest(url: fixtureURL.appendingPathComponent("__test/biometrics"), timeoutInterval: 5)
        let (configuration, configurationResponse) = try await URLSession.shared.data(for: configurationRequest)
        XCTAssertEqual((configurationResponse as? HTTPURLResponse)?.statusCode, 200)
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
        request.timeoutInterval = 15
        let (_, matchResponse) = try await URLSession.shared.data(for: request)
        XCTAssertEqual((matchResponse as? HTTPURLResponse)?.statusCode, 200)
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
        // PhotosPicker's AX tap may attempt scrolling and report {-1,-1} for a
        // visibly present thumbnail. Use its observed frame, as for native tabs.
        let window = app.windows.firstMatch
        let viewport = window.frame
        let photoFrame = selectedPhoto.frame
        let photoCenter = CGPoint(x: photoFrame.midX, y: photoFrame.midY)
        // AX may round an edge a few millionths of a point outside the window.
        // Bound that noise to 0.001 pt; the actual tap must remain strictly inside.
        guard photoFrame.width > 0, photoFrame.height > 0,
              viewport.insetBy(dx: -0.001, dy: -0.001).contains(photoFrame),
              viewport.contains(photoCenter) else {
            let windowFrames = app.windows.allElementsBoundByIndex.prefix(6).map { $0.frame }
            let photoFrames = app.images.matching(identifier: "PXGGridLayout-Info")
                .allElementsBoundByIndex.prefix(8).map { $0.frame }
            XCTFail("The seeded PhotosPicker thumbnail must have a valid frame fully within the viewport. photo=\(photoFrame), viewport=\(viewport), windows=\(windowFrames), thumbnails=\(photoFrames)")
            return
        }
        window.coordinate(withNormalizedOffset: .zero)
            .withOffset(CGVector(dx: photoCenter.x - viewport.minX, dy: photoCenter.y - viewport.minY)).tap()
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

    func testSettingsSaveKeepsAccessibleLabelWhileSaving() {
        launchFixtureApp()
        login()
        selectTab("settings", fallback: "Réglages")
        let manual = app.segmentedControls["settings.mode"].buttons["Manuel"]
        XCTAssertTrue(manual.waitForExistence(timeout: 5))
        manual.tap()
        let save = app.buttons["settings.save"]
        scrollTo(save)
        XCTAssertTrue(save.isEnabled)
        XCTAssertEqual(save.label, "Enregistrer les réglages")
        configureFixture("__test/settings-delay", body: ["seconds": 5])
        defer { configureFixture("__test/settings-delay", body: ["seconds": 0]) }
        save.tap()

        let saving = XCTNSPredicateExpectation(
            predicate: NSPredicate(format: "label == %@ AND value == %@ AND enabled == false",
                                   "Enregistrer les réglages", "Opération en cours"), object: save)
        XCTAssertEqual(XCTWaiter.wait(for: [saving], timeout: 3), .completed,
                       "The disabled save button must retain its action label and expose progress through its value.")
        XCTAssertTrue(app.staticTexts["Réglages enregistrés."].waitForExistence(timeout: 10))
        XCTAssertEqual(save.label, "Enregistrer les réglages")
        XCTAssertNotEqual(save.value as? String, "Opération en cours")
        XCTAssertFalse(save.isEnabled, "A saved draft must no longer be dirty.")
    }

    func testForegroundOfflineKeepsDataAndRecoversWithoutLogin() {
        launchFixtureApp()
        login()
        selectTab("queue", fallback: "File")
        let firstPhoto = element("queue.row.a11050000002")
        let secondPhoto = element("queue.row.5ad000000003")
        XCTAssertTrue(firstPhoto.waitForExistence(timeout: 5))
        XCTAssertTrue(secondPhoto.exists)
        XCTAssertTrue(app.staticTexts["2 photos dans la file"].exists)

        XCUIDevice.shared.press(.home)
        XCTAssertTrue(app.wait(for: .runningBackground, timeout: 5), "The app must enter the background before the outage.")
        configureFixture("__test/availability", body: ["available": false])
        defer { configureFixture("__test/availability", body: ["available": true]) }
        app.activate()
        let offline = app.staticTexts["Raspberry injoignable · données précédentes"]
        XCTAssertTrue(offline.waitForExistence(timeout: 10), "Returning offline must show the cached-data banner.")
        XCTAssertTrue(firstPhoto.exists)
        XCTAssertTrue(secondPhoto.exists)
        XCTAssertTrue(app.staticTexts["2 photos dans la file"].exists)
        XCTAssertFalse(app.buttons["queue.edit"].isEnabled, "Cached data must remain read-only during the outage.")
        XCTAssertFalse(app.secureTextFields["connection.password"].exists, "A transport failure must preserve the session.")
        let offlineBanner = element("connection.offline")
        let errorBanner = element("connection.error")
        XCTAssertTrue(offlineBanner.exists)
        XCTAssertTrue(errorBanner.waitForExistence(timeout: 5))
        XCTAssertLessThanOrEqual(offlineBanner.frame.maxY, errorBanner.frame.minY + 1,
                                 "Connection and error messages must not overlap.")
        XCTAssertLessThanOrEqual(errorBanner.frame.maxY, app.navigationBars.firstMatch.frame.minY + 1,
                                 "The navigation title must stay below both messages.")
        capture("Reprise hors ligne — données conservées")

        let retry = app.buttons["Réessayer"]
        XCTAssertTrue(retry.isHittable)
        retry.tap()
        XCTAssertTrue(offline.exists, "Retrying while the frame is unavailable must keep the recoverable state.")
        configureFixture("__test/availability", body: ["available": true])
        // The WebSocket reconnect and the 20-second polling fallback may recover
        // first. Do not race either against a tap on a disappearing retry button.
        XCTAssertTrue(offline.waitForNonExistence(timeout: 30), "Restoring the frame must clear the offline banner without another login.")
        XCTAssertTrue(firstPhoto.exists)
        XCTAssertTrue(secondPhoto.exists)
        XCTAssertTrue(app.buttons["queue.edit"].isEnabled)
        XCTAssertFalse(app.secureTextFields["connection.password"].exists, "Recovery must use the existing session without logging in again.")
        selectTab("frame", fallback: "Cadre")
        XCTAssertTrue(app.staticTexts["Raspberry connecté"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.buttons["frame.next"].isEnabled)
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
            let title = NSPredicate(format: "label BEGINSWITH %@", "Enregistrer le mot de passe")
            let sheet = app.sheets.matching(title).firstMatch
            let systemSheet = XCUIApplication(bundleIdentifier: "com.apple.springboard").sheets.matching(title).firstMatch
            // The app-owned remote sheet can arrive while we are checking
            // SpringBoard. Finish discovery first, then resolve both owners
            // again so a late app sheet is not skipped.
            _ = sheet.waitForExistence(timeout: 6) || systemSheet.waitForExistence(timeout: 2)
            for prompt in [sheet, systemSheet] {
                guard prompt.exists else { continue }
                // The remote password UI can ignore a tap while it finishes
                // presenting. Resolve the same dismiss button again, once.
                for _ in 0..<2 {
                    let later = prompt.buttons["Plus tard"]
                    let hittable = XCTNSPredicateExpectation(predicate: NSPredicate(format: "hittable == true"), object: later)
                    guard XCTWaiter.wait(for: [hittable], timeout: 3) == .completed else { break }
                    later.tap()
                    if prompt.waitForNonExistence(timeout: 3) { return }
                }
            }
            XCTAssertFalse(sheet.exists || systemSheet.exists, "The password-save sheet must close before testing app controls.")
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
        capture("07a Sources de photo")
        camera.tap()
        let springboard = XCUIApplication(bundleIdentifier: "com.apple.springboard")
        // Some Simulator runtimes expose a camera. Permission belongs to the
        // system application; never assume the source is universally absent.
        let cameraPermission = springboard.alerts.matching(NSPredicate(format: "label CONTAINS[cd] %@", "camera")).firstMatch
        let cameraIssue = app.alerts.firstMatch
        // Camera permission can arrive after several seconds on a busy runtime.
        // Wait for either outcome together so an unavailable-camera alert does
        // not incur the whole system-permission timeout.
        let outcome = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
            cameraIssue.exists || cameraPermission.exists
        }, object: nil)
        XCTAssertEqual(XCTWaiter.wait(for: [outcome], timeout: 20), .completed,
                       "Taking a photo must show either camera permission or an actionable camera alert.")
        if cameraPermission.exists {
            let deny = cameraPermission.buttons.matching(NSPredicate(format: "label IN %@", ["Ne pas autoriser", "Don’t Allow", "Don't Allow"])).firstMatch
            XCTAssertTrue(deny.exists)
            deny.tap()
        }
        XCTAssertTrue(cameraIssue.waitForExistence(timeout: 5))
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
        XCTAssertTrue(app.secureTextFields["password.current"].waitForExistence(timeout: 5))
        capture("08a Changer le mot de passe")
        for field in ["current", "new", "confirmation"] {
            let input = app.secureTextFields["password.\(field)"]
            XCTAssertTrue(input.waitForExistence(timeout: 5))
            input.tap(); input.typeText("test-password")
        }
        let save = app.buttons["password.save"]
        let unchanged = app.staticTexts["password.unchanged"]
        XCTAssertTrue(unchanged.waitForExistence(timeout: 5))
        XCTAssertFalse(save.isEnabled, "Keeping the same password must explain why saving is unavailable.")
        // The keyboard's Done action must obey the same validation as the button.
        app.secureTextFields["password.confirmation"].typeText("\n")
        XCTAssertFalse(app.staticTexts["password.success"].exists)
        XCTAssertFalse(app.staticTexts["password.error"].exists)
        scrollTo(unchanged)
        capture("08b Mot de passe identique expliqué")
        for field in ["new", "confirmation"] {
            let input = app.secureTextFields["password.\(field)"]
            input.tap()
            input.typeText(String(repeating: XCUIKeyboardKey.delete.rawValue, count: "test-password".count))
            input.typeText("my-new-frame-password")
        }
        XCTAssertFalse(unchanged.exists)
        scrollTo(save)
        XCTAssertTrue(save.isEnabled)
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
            // verify the displayed screen; no model-specific coordinates.
            let window = app.windows.firstMatch
            let rect = target.frame
            XCTAssertTrue(window.frame.contains(rect))
            XCTAssertGreaterThan(rect.width, 0)
            window.coordinate(withNormalizedOffset: .zero)
                .withOffset(CGVector(dx: rect.midX - window.frame.minX, dy: rect.midY - window.frame.minY)).tap()
            // iOS 27 can resolve `target` to the tab's SF Symbol child after
            // selection. Its `selected` trait is not the tab's state. Require
            // the unique, visible destination instead of trusting that child.
            let title: String
            switch identifier {
            case "frame": title = "Inky Studio"
            case "queue": title = "À suivre"
            case "history": title = "Historique"
            case "settings": title = "Réglages"
            default: XCTFail("Unknown tab: \(identifier)"); return
            }
            let bars = app.navigationBars.matching(identifier: title)
            XCTAssertTrue(bars.firstMatch.waitForExistence(timeout: 5))
            XCTAssertEqual(bars.count, 1, "The selected tab must have one destination title.")
            let visible = XCTNSPredicateExpectation(
                predicate: NSPredicate(format: "exists == true AND hittable == true"), object: bars.element)
            XCTAssertEqual(XCTWaiter.wait(for: [visible], timeout: 5), .completed,
                           "The selected tab's destination must be visible.")
        } else {
            target.tap()
            XCTAssertTrue(waitForSelected(target), "The tab must actually become selected.")
        }
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
        configureFixture("__test/reset")
    }

    private func configureFixture(_ endpoint: String, body: [String: Any] = [:]) {
        var request = URLRequest(url: fixtureURL.appendingPathComponent(endpoint))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        do { request.httpBody = try JSONSerialization.data(withJSONObject: body) }
        catch { XCTFail("Invalid fixture configuration: \(error)"); return }
        request.timeoutInterval = 5
        let ready = expectation(description: "Local fixture \(endpoint)")
        let result = FixtureRequestResult(ready: ready)
        let task = URLSession.shared.dataTask(with: request) { _, response, error in
            result.complete(response: response, error: error)
        }
        task.resume()
        let waitResult = XCTWaiter.wait(for: [ready], timeout: 7)
        // Close before cancellation and assertions: a late callback must not
        // fulfill an old expectation or record a failure in the next test.
        let outcome = result.close()
        task.cancel()
        guard waitResult == .completed, let outcome else {
            XCTFail("Local fixture \(endpoint) did not complete within 7 seconds (\(waitResult)).")
            return
        }
        XCTAssertNil(outcome.error, "Start python3 ios/scripts/mock-server.py before running UI tests.")
        XCTAssertEqual(outcome.statusCode, 200)
    }
}

private final class FixtureRequestResult: @unchecked Sendable {
    private let lock = NSLock()
    private let ready: XCTestExpectation
    private var pending = true
    private var outcome: (statusCode: Int?, error: Error?)?

    init(ready: XCTestExpectation) { self.ready = ready }

    func complete(response: URLResponse?, error: Error?) {
        lock.withLock {
            guard pending else { return }
            pending = false
            outcome = ((response as? HTTPURLResponse)?.statusCode, error)
            ready.fulfill()
        }
    }

    func close() -> (statusCode: Int?, error: Error?)? {
        lock.withLock {
            pending = false
            return outcome
        }
    }
}
