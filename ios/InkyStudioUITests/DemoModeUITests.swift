import XCTest

/// Runs without the Python fixture, a Raspberry, credentials or hidden demo flags.
@MainActor
final class DemoModeUITests: XCTestCase {
    private var app: XCUIApplication!

    private func launch(largeText: Bool = false) {
        continueAfterFailure = false
        app = XCUIApplication()
        app.launchArguments = ["-AppleLanguages", "(fr)", "-AppleLocale", "fr_FR"]
        if largeText {
            app.launchArguments += ["-UIPreferredContentSizeCategoryName", "UICTContentSizeCategoryAccessibilityXXXL"]
        }
        app.launch()
        addTeardownBlock { @MainActor [weak self] in
            guard let self else { return }
            if (self.testRun?.failureCount ?? 0) > 0 { self.capture("Failure") }
            self.app.terminate()
        }
    }

    func testPublicDemoCropQueueHistorySettingsAndReset() {
        launch()
        XCTAssertTrue(app.buttons["connection.demo"].waitForExistence(timeout: 10))
        capture("01 Accueil")
        scrollTo(app.buttons["connection.guide"])
        app.buttons["connection.guide"].tap()
        XCTAssertTrue(app.buttons["guide.close"].waitForExistence(timeout: 5))
        capture("01b Premiers pas")
        app.buttons["guide.close"].tap()
        scrollTo(app.buttons["connection.demo"], up: true)
        app.buttons["connection.demo"].tap()
        XCTAssertTrue(app.buttons["demo.exit"].waitForExistence(timeout: 10))
        XCTAssertTrue(app.staticTexts["Cadre simulé · aucune connexion"].exists)
        capture("02 Cadre démo")
        app.buttons["frame.next"].tap()
        selectTab("File")
        XCTAssertTrue(app.staticTexts["1 photo dans la file"].waitForExistence(timeout: 5))
        capture("03 File")
        selectTab("Historique")
        XCTAssertTrue(app.buttons.matching(NSPredicate(format: "identifier BEGINSWITH %@", "history.requeue.")).firstMatch.waitForExistence(timeout: 5))
        capture("04 Historique")
        selectTab("Cadre")
        scrollTo(app.buttons["frame.add"])
        app.buttons["frame.add"].tap()
        scrollTo(app.buttons["photo.demoSample"])
        app.buttons["photo.demoSample"].tap()
        let upload = app.buttons["upload-photo"]
        XCTAssertTrue(upload.waitForExistence(timeout: 5))
        app.sliders["Zoom de la photo"].adjust(toNormalizedSliderPosition: 0.16)
        capture("05 Cadrage local")
        upload.tap()
        XCTAssertTrue(upload.waitForNonExistence(timeout: 10))
        selectTab("File")
        XCTAssertTrue(app.staticTexts["2 photos dans la file"].waitForExistence(timeout: 5))
        selectTab("Réglages")
        XCTAssertTrue(app.buttons["demo.reset"].waitForExistence(timeout: 5))
        XCTAssertFalse(app.switches["settings.biometric"].exists)
        XCTAssertFalse(app.buttons["settings.bluetooth"].exists)
        XCTAssertFalse(app.buttons["settings.password"].exists)
        capture("06 Réglages démo")
        app.buttons["Quotidien"].tap()
        let saveSettings = app.buttons["settings.save"]
        scrollTo(saveSettings)
        XCTAssertTrue(saveSettings.isEnabled)
        saveSettings.tap()
        XCTAssertTrue(app.staticTexts["Réglages enregistrés pour cette démo uniquement."].waitForExistence(timeout: 5))
        selectTab("Cadre")
        selectTab("Réglages")
        scrollTo(app.buttons["Quotidien"], up: true)
        XCTAssertTrue(app.buttons["Quotidien"].isSelected)
        scrollTo(app.buttons["demo.reset"], up: true)
        app.buttons["demo.reset"].tap()
        app.buttons["Effacer les essais"].tap()
        XCTAssertTrue(app.buttons["frame.add"].waitForExistence(timeout: 5))
        selectTab("Réglages")
        XCTAssertTrue(app.buttons["Manuel"].isSelected)
        app.buttons["demo.exit"].tap()
        XCTAssertTrue(app.buttons["connection.demo"].waitForExistence(timeout: 5))
        XCTAssertFalse(app.tabBars.firstMatch.exists)
        app.terminate()
        app.launch()
        XCTAssertTrue(app.buttons["connection.demo"].waitForExistence(timeout: 10))
        XCTAssertFalse(app.buttons["demo.exit"].exists)
    }

    func testGuideAndDemoWithAccessibilityText() {
        launch(largeText: true)
        scrollTo(app.buttons["connection.guide"])
        app.buttons["connection.guide"].tap()
        XCTAssertTrue(app.buttons["guide.close"].waitForExistence(timeout: 5))
        capture("07 Premiers pas grand texte")
        scrollTo(app.buttons["guide.connect"], maxGestures: 60)
        capture("08 Guide et aide grand texte")
        app.buttons["guide.connect"].tap()
        scrollTo(app.buttons["connection.demo"], up: true)
        app.buttons["connection.demo"].tap()
        XCTAssertTrue(app.buttons["demo.exit"].waitForExistence(timeout: 5))
        capture("09 Cadre grand texte")
        selectTab("Réglages")
        scrollTo(app.buttons["settings.mode"])
        app.buttons["settings.mode"].tap()
        app.buttons["Intervalle"].tap()
        scrollTo(app.buttons["settings.save"])
        XCTAssertTrue(app.buttons["settings.save"].isEnabled)
        capture("10 Réglages grand texte")
        app.buttons["demo.exit"].tap()
        XCTAssertTrue(app.buttons["connection.demo"].waitForExistence(timeout: 5))
    }

    private func selectTab(_ label: String) {
        let tab = app.tabBars.buttons[label]
        XCTAssertTrue(tab.waitForExistence(timeout: 5))
        tab.tap()
    }
    private func scrollTo(_ element: XCUIElement, up: Bool = false, maxGestures: Int = 20) {
        let identifier = element.identifier.isEmpty ? element.label : element.identifier
        let scrollView = app.scrollViews.containing(element.elementType, identifier: identifier).firstMatch
        XCTAssertTrue(scrollView.waitForExistence(timeout: 5))
        for _ in 0..<maxGestures {
            if element.exists && element.isHittable { return }
            var towardsTop = up
            if element.exists && !element.frame.isEmpty {
                if element.frame.midY < scrollView.frame.minY { towardsTop = true }
                else if element.frame.midY > scrollView.frame.maxY { towardsTop = false }
            }
            // Short, slow drags settle before the next query and avoid skipping the target.
            let start = scrollView.coordinate(withNormalizedOffset: CGVector(dx: 0.95, dy: towardsTop ? 0.45 : 0.70))
            let end = scrollView.coordinate(withNormalizedOffset: CGVector(dx: 0.95, dy: towardsTop ? 0.70 : 0.45))
            start.press(forDuration: 0.05, thenDragTo: end, withVelocity: .slow, thenHoldForDuration: 0.2)
        }
        XCTAssertTrue(element.exists, "Element absent: \(element)")
        XCTAssertTrue(element.isHittable, "Element inaccessible: \(element)")
    }
    private func capture(_ name: String) {
        let attachment = XCTAttachment(screenshot: app.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }
}
