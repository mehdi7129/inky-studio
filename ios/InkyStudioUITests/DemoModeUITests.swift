import XCTest

/// Runs without the Python fixture, a Raspberry, credentials or hidden demo flags.
@MainActor
final class DemoModeUITests: XCTestCase {
    private var app: XCUIApplication!

    private func launch(largeText: Bool = false) {
        continueAfterFailure = false
        app = XCUIApplication()
        // Clear the frame left by other UI tests; enter the demo through its public button.
        app.launchArguments = ["--uitesting", "-AppleLanguages", "(fr)", "-AppleLocale", "fr_FR"]
        if largeText {
            app.launchArguments += ["-UIPreferredContentSizeCategoryName", "UICTContentSizeCategoryAccessibilityXXXL"]
        }
        app.launch()
        let teardown: @MainActor @Sendable () -> Void = { [weak self] in
            guard let self else { return }
            if (self.testRun?.failureCount ?? 0) > 0 { self.capture("Failure") }
            self.app.terminate()
        }
        addTeardownBlock(teardown)
    }

    func testPublicDemoCropQueueHistorySettingsAndReset() {
        launch()
        XCTAssertTrue(app.buttons["connection.demo"].waitForExistence(timeout: 10))
        capture("01 Accueil")
        scrollTo(app.buttons["connection.guide"], in: app.scrollViews["connection.scroll"])
        app.buttons["connection.guide"].tap()
        XCTAssertTrue(app.buttons["guide.close"].waitForExistence(timeout: 5))
        capture("01b Premiers pas")
        app.buttons["guide.close"].tap()
        scrollTo(app.buttons["connection.demo"], in: app.scrollViews["connection.scroll"], up: true)
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
        scrollTo(app.buttons["frame.add"], in: app.scrollViews["frame.scroll"])
        app.buttons["frame.add"].tap()
        scrollTo(app.buttons["photo.demoSample"], in: app.scrollViews["photo.scroll"])
        XCTAssertTrue(app.buttons["choose-photo"].exists)
        XCTAssertTrue(app.buttons["take-photo"].exists)
        capture("04b Choisir une photo")
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
        scrollTo(saveSettings, in: app.scrollViews["settings.scroll"])
        XCTAssertTrue(saveSettings.isEnabled)
        saveSettings.tap()
        XCTAssertTrue(app.staticTexts["Réglages enregistrés pour cette démo uniquement."].waitForExistence(timeout: 5))
        scrollTo(app.buttons["settings.guide"], in: app.scrollViews["settings.scroll"])
        capture("06b Réglages démo et aide")
        selectTab("Cadre")
        selectTab("Réglages")
        scrollTo(app.buttons["Quotidien"], in: app.scrollViews["settings.scroll"], up: true)
        XCTAssertTrue(app.buttons["Quotidien"].isSelected)
        scrollTo(app.buttons["demo.reset"], in: app.scrollViews["settings.scroll"], up: true)
        app.buttons["demo.reset"].tap()
        let erase = app.buttons["Effacer les essais"]
        XCTAssertTrue(erase.waitForExistence(timeout: 5), "Reset must present its confirmation before erasing the demo.")
        erase.tap()
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
        scrollTo(app.buttons["connection.guide"], in: app.scrollViews["connection.scroll"])
        app.buttons["connection.guide"].tap()
        XCTAssertTrue(app.buttons["guide.close"].waitForExistence(timeout: 5))
        capture("07 Premiers pas grand texte")
        scrollTo(app.buttons["guide.connect"], in: app.scrollViews["guide.scroll"], maxGestures: 60)
        capture("08 Guide et aide grand texte")
        app.buttons["guide.connect"].tap()
        scrollTo(app.buttons["connection.demo"], in: app.scrollViews["connection.scroll"], up: true)
        app.buttons["connection.demo"].tap()
        XCTAssertTrue(app.buttons["demo.exit"].waitForExistence(timeout: 5))
        capture("09 Cadre grand texte")
        selectTab("Réglages")
        scrollTo(app.buttons["settings.mode"], in: app.scrollViews["settings.scroll"])
        app.buttons["settings.mode"].tap()
        app.buttons["Intervalle"].tap()
        scrollTo(app.buttons["settings.save"], in: app.scrollViews["settings.scroll"])
        XCTAssertTrue(app.buttons["settings.save"].isEnabled)
        capture("10 Réglages grand texte")
        app.buttons["demo.exit"].tap()
        XCTAssertTrue(app.buttons["connection.demo"].waitForExistence(timeout: 5))
    }

    /// Audit semantic accessibility on real rendered screens. This does not
    /// replace listening to VoiceOver or testing every scrolled/offscreen item.
    func testPublicScreensHaveAccessibleDescriptionsAndTraits() throws {
        launch()
        XCTAssertTrue(app.buttons["connection.demo"].waitForExistence(timeout: 10))
        try app.performAccessibilityAudit(for: [.sufficientElementDescription, .trait])
        scrollTo(app.buttons["connection.demo"], in: app.scrollViews["connection.scroll"])
        app.buttons["connection.demo"].tap()
        XCTAssertTrue(app.buttons["demo.exit"].waitForExistence(timeout: 5))
        for name in ["Cadre", "File", "Historique", "Réglages"] {
            selectTab(name)
            try app.performAccessibilityAudit(for: [.sufficientElementDescription, .trait])
        }
        selectTab("Cadre")
        scrollTo(app.buttons["frame.add"], in: app.scrollViews["frame.scroll"])
        app.buttons["frame.add"].tap()
        scrollTo(app.buttons["photo.demoSample"], in: app.scrollViews["photo.scroll"])
        try app.performAccessibilityAudit(for: [.sufficientElementDescription, .trait])
        app.buttons["photo.demoSample"].tap()
        XCTAssertTrue(app.buttons["upload-photo"].waitForExistence(timeout: 5))
        try app.performAccessibilityAudit(for: [.sufficientElementDescription, .trait])
    }

    /// Follows the Simulator's current appearance so the same journey can be
    /// inspected in light and dark without adding a production launch override.
    func testAllTabsAndPhotoImportWithAccessibilityText() {
        launch(largeText: true)
        scrollTo(app.buttons["connection.demo"], in: app.scrollViews["connection.scroll"])
        app.buttons["connection.demo"].tap()
        XCTAssertTrue(app.buttons["demo.exit"].waitForExistence(timeout: 5))
        capture("11 Cadre grand texte")
        scrollTo(app.buttons["frame.add"], in: app.scrollViews["frame.scroll"])
        XCTAssertTrue(app.buttons["frame.add"].isHittable)

        selectTab("File")
        XCTAssertTrue(app.staticTexts["2 photos dans la file"].waitForExistence(timeout: 5))
        capture("12 File grand texte")
        let edit = app.buttons["queue.edit"]
        scrollTo(edit, in: app.collectionViews["queue.list"])
        XCTAssertTrue(edit.isEnabled)
        edit.tap()
        XCTAssertEqual(edit.label, "Terminer")
        edit.tap()

        selectTab("Historique")
        let requeue = app.buttons.matching(NSPredicate(format: "identifier BEGINSWITH %@", "history.requeue.")).firstMatch
        XCTAssertTrue(requeue.waitForExistence(timeout: 5))
        scrollTo(requeue, in: app.collectionViews["history.list"])
        XCTAssertTrue(requeue.isEnabled)
        capture("13 Historique grand texte")
        requeue.tap()
        selectTab("File")
        scrollTo(app.staticTexts["3 photos dans la file"], in: app.collectionViews["queue.list"], up: true)
        XCTAssertTrue(app.staticTexts["3 photos dans la file"].waitForExistence(timeout: 5))

        selectTab("Réglages")
        XCTAssertTrue(app.buttons["demo.reset"].waitForExistence(timeout: 5))
        capture("14 Réglages grand texte")
        scrollTo(app.buttons["settings.guide"], in: app.scrollViews["settings.scroll"], maxGestures: 60)
        capture("14b Aide grand texte")

        selectTab("Cadre")
        scrollTo(app.buttons["frame.add"], in: app.scrollViews["frame.scroll"])
        app.buttons["frame.add"].tap()
        XCTAssertTrue(app.buttons["photo.demoSample"].waitForExistence(timeout: 5))
        capture("15 Ajouter une photo grand texte")
        // All sources must remain reachable, without opening Photos or a camera.
        scrollTo(app.buttons["take-photo"], in: app.scrollViews["photo.scroll"])
        XCTAssertTrue(app.buttons["take-photo"].isEnabled)
        scrollTo(app.buttons["choose-photo"], in: app.scrollViews["photo.scroll"])
        XCTAssertTrue(app.buttons["choose-photo"].isEnabled)
        capture("15b Sources photo grand texte")
        scrollTo(app.buttons["photo.demoSample"], in: app.scrollViews["photo.scroll"], up: true)
        app.buttons["photo.demoSample"].tap()

        let zoom = app.sliders["Zoom de la photo"]
        XCTAssertTrue(zoom.waitForExistence(timeout: 5))
        let crop = app.descendants(matching: .any)["photo.crop"].firstMatch
        XCTAssertTrue(crop.waitForExistence(timeout: 5))
        let cropViewport = unobscuredViewport(of: app.scrollViews["photo.scroll"])
        XCTAssertTrue(crop.isHittable, "A newly selected photo must open at its preview.")
        XCTAssertGreaterThanOrEqual(crop.frame.minY, cropViewport.minY - 1)
        XCTAssertLessThanOrEqual(crop.frame.maxY, cropViewport.maxY + 1)
        capture("16a Aperçu du cadrage grand texte")
        scrollTo(zoom, in: app.scrollViews["photo.scroll"])
        zoom.adjust(toNormalizedSliderPosition: 0.15)
        capture("16b Réglages du cadrage grand texte")
        scrollTo(app.buttons["Réinitialiser"], in: app.scrollViews["photo.scroll"])
        app.buttons["Réinitialiser"].tap()
        let upload = app.buttons["upload-photo"]
        scrollTo(upload, in: app.scrollViews["photo.scroll"])
        XCTAssertTrue(upload.isHittable)
        XCTAssertTrue(upload.isEnabled)
        capture("16c Ajouter à la file grand texte")
        upload.tap()
        XCTAssertTrue(upload.waitForNonExistence(timeout: 10))
        selectTab("File")
        scrollTo(app.staticTexts["4 photos dans la file"], in: app.collectionViews["queue.list"], up: true)
        XCTAssertTrue(app.staticTexts["4 photos dans la file"].waitForExistence(timeout: 5))
    }

    private func selectTab(_ label: String) {
        let tab = app.tabBars.buttons[label]
        XCTAssertTrue(tab.waitForExistence(timeout: 5))
        tab.tap()
    }
    private func scrollTo(_ element: XCUIElement, in scrollView: XCUIElement,
                          up: Bool = false, maxGestures: Int = 20) {
        // Each screen owns a stable container identifier. A modal can leave
        // other scroll views in the tree, so never choose a container heuristically.
        XCTAssertTrue(scrollView.waitForExistence(timeout: 5))
        let isList = scrollView.elementType == .collectionView || scrollView.elementType == .table
        for _ in 0..<maxGestures {
            XCTAssertTrue(scrollView.exists, "Scrolling must keep its original screen or sheet open.")
            let viewport = unobscuredViewport(of: scrollView)
            XCTAssertGreaterThan(viewport.height, 0, "The scroll container must have a visible gesture area.")
            if readyToTap(element, in: viewport) { return }
            var towardsTop = up
            if element.exists && !element.frame.isEmpty {
                if element.frame.minY < viewport.minY { towardsTop = true }
                else if element.frame.maxY > viewport.maxY { towardsTop = false }
            }
            // In iOS 18.5 a slow drag starting over a SwiftUI button/link can
            // activate it. CI recordings showed example selection, upload and
            // iOS Settings opening during scrollTo. These screens have at least
            // 16 pt of content padding: use the scroll view's empty right margin.
            // Native lists retain their central scrolling lane.
            let x = isList ? viewport.midX : viewport.maxX - min(12, viewport.width * 0.05)
            // Freeze the observed points in window coordinates before the
            // gesture; XCTest must not resolve the scrolling element mid-drag.
            let window = app.windows.firstMatch
            let windowFrame = window.frame
            let origin = window.coordinate(withNormalizedOffset: .zero)
            let start = origin.withOffset(CGVector(dx: x - windowFrame.minX,
                dy: viewport.minY + viewport.height * (towardsTop ? 0.25 : 0.75) - windowFrame.minY))
            let end = origin.withOffset(CGVector(dx: x - windowFrame.minX,
                dy: viewport.minY + viewport.height * (towardsTop ? 0.75 : 0.25) - windowFrame.minY))
            start.press(forDuration: 0.05, thenDragTo: end, withVelocity: .slow, thenHoldForDuration: 0.2)
        }
        XCTAssertTrue(element.exists, "Element absent: \(element)")
        XCTAssertTrue(readyToTap(element, in: unobscuredViewport(of: scrollView)), "Element inaccessible or covered by navigation: \(element)")
    }

    private func unobscuredViewport(of scrollView: XCUIElement) -> CGRect {
        let bounds = scrollView.frame.intersection(app.windows.firstMatch.frame)
        var top = bounds.minY
        var bottom = bounds.maxY
        let navigation = app.navigationBars.firstMatch
        if navigation.exists && navigation.isHittable && navigation.frame.intersects(bounds) {
            top = max(top, navigation.frame.maxY)
        }
        let tabs = app.tabBars.firstMatch
        if tabs.exists && tabs.isHittable && tabs.frame.intersects(bounds) {
            bottom = min(bottom, tabs.frame.minY)
        }
        return CGRect(x: bounds.minX, y: top, width: bounds.width, height: max(0, bottom - top))
    }

    private func readyToTap(_ element: XCUIElement, in viewport: CGRect) -> Bool {
        guard element.exists && element.isHittable else { return false }
        let frame = element.frame
        let visible = frame.intersection(viewport)
        guard !visible.isNull && !visible.isEmpty else { return false }
        // Ordinary controls must be fully clear of native bars. An oversized
        // accessibility label can instead expose a useful portion of its area.
        if frame.height > viewport.height { return visible.height >= min(88, viewport.height / 2) }
        return visible.height >= frame.height - 1 && viewport.contains(CGPoint(x: frame.midX, y: frame.midY))
    }
    private func capture(_ name: String) {
        let attachment = XCTAttachment(screenshot: app.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }
}
