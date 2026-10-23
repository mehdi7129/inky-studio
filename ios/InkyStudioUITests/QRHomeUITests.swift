import XCTest

/// Public QR/lock screens only: no server, saved credential, photo library or frame.
@MainActor
final class QRHomeUITests: XCTestCase {
    private var app: XCUIApplication!

    func testConnectionStartsWithOneQRActionWithoutCredentialsOrDemo() {
        launch()
        assertPublicHome()
        XCTAssertTrue(app.staticTexts["Scannez le QR code affiché sur votre cadre."].exists)
        XCTAssertTrue(app.staticTexts["Accès protégé par l’iPhone."].exists)
        capture("01 Accueil QR Bento")
    }

    func testHomeAndLockInLightAndDark() {
        for appearance in ["Light", "Dark"] {
            launch(appearance: appearance)
            assertPublicHome()
            capture("02 Accueil QR \(appearance)")
            app.terminate()
            launch(appearance: appearance, authenticationFixture: "locked")
            XCTAssertTrue(app.buttons["lock.unlock"].waitForExistence(timeout: 5))
            assertContentIsLocked()
            capture("03 Verrou \(appearance)")
            app.terminate()
        }
    }

    func testCancelledLocalAuthenticationKeepsPrivateContentLocked() {
        launch(authenticationFixture: "failure")
        let unlock = app.buttons["lock.unlock"]
        XCTAssertTrue(unlock.waitForExistence(timeout: 5))
        unlock.tap()
        XCTAssertTrue(app.staticTexts["lock.error"].waitForExistence(timeout: 5))
        XCTAssertTrue(unlock.isEnabled)
        assertContentIsLocked()
        capture("04 Authentification refusée")
    }

    func testMalformedQRReturnsToHomeWithoutOpeningAConnection() {
        launch(extraArguments: ["--qr-input-fixture"])
        let scan = app.buttons["connection.scanLANQR"]
        XCTAssertTrue(scan.waitForExistence(timeout: 5))
        scan.tap()
        let input = app.textFields["connection.testQR"]
        XCTAssertTrue(input.waitForExistence(timeout: 5))
        input.tap()
        input.typeText("ceci-n-est-pas-un-qr-inky")
        app.buttons["connection.acceptTestQR"].tap()
        XCTAssertTrue(app.staticTexts["connection.error"].waitForExistence(timeout: 5))
        assertPublicHome()
        XCTAssertFalse(app.buttons["frame.add"].exists)
        capture("05 QR invalide")
    }

    func testVoluntaryRecoveryCanBeCancelledWithoutReplacingSavedAccess() {
        launch(authenticationFixture: "recoverable", extraArguments: ["--qr-input-fixture"])
        let recover = app.buttons["lock.recover"]
        XCTAssertTrue(recover.waitForExistence(timeout: 5))
        scrollTo(recover, in: app.scrollViews["lock.scroll"])
        recover.tap()
        let scan = app.buttons["connection.scanLANQR"]
        XCTAssertTrue(scan.waitForExistence(timeout: 5))
        XCTAssertTrue(app.buttons["connection.cancelRecovery"].exists)
        scan.tap()
        let cancel = app.buttons["connection.cancelScanner"]
        XCTAssertTrue(cancel.waitForExistence(timeout: 5))
        cancel.tap()
        XCTAssertTrue(app.buttons["lock.unlock"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.buttons["lock.recover"].exists)
        assertContentIsLocked()
        capture("08 Récupération annulée")
    }

    func testPhotoInvitationReturnsFromScannerToLocalAuthenticationWithoutWiFiSetup() throws {
        // This inert auth fixture cancels locally and never reaches the network.
        launch(authenticationFixture: "photo-cancelled", extraArguments: ["--qr-input-fixture"])
        app.buttons["connection.scanLANQR"].tap()
        try enterSyntheticPhotoInvitation()
        XCTAssertTrue(app.staticTexts["connection.error"].waitForExistence(timeout: 5))
        XCTAssertFalse(app.textFields["connection.testQR"].exists)
        XCTAssertFalse(app.navigationBars["Wi-Fi du cadre"].exists)
        XCTAssertFalse(app.staticTexts["connection.error"].label.contains("QR"))
        assertPublicHome()
        capture("09 Invitation PHOTO — annulation locale après fermeture du scanner")
    }

    func testPhotoInvitationFromWiFiScannerClosesBothSheetsBeforeLocalAuthentication() throws {
        launch(authenticationFixture: "photo-cancelled",
               extraArguments: ["--qr-input-fixture", "--bluetooth-fixture", "introduction"])
        let entry = app.buttons["connection.bluetooth"]
        XCTAssertTrue(entry.waitForExistence(timeout: 5))
        scrollTo(entry, in: app.scrollViews["connection.scroll"])
        entry.tap()
        let scan = app.buttons["bluetooth.scanQR"]
        XCTAssertTrue(scan.waitForExistence(timeout: 5))
        scan.tap()
        try enterSyntheticPhotoInvitation(inputID: "bluetooth.testQR", acceptID: "bluetooth.acceptTestQR")
        XCTAssertTrue(app.staticTexts["connection.error"].waitForExistence(timeout: 5))
        XCTAssertFalse(app.staticTexts["bluetooth.error"].exists)
        XCTAssertFalse(app.navigationBars["Wi-Fi du cadre"].exists)
        XCTAssertFalse(app.navigationBars["Scanner le cadre"].exists)
        XCTAssertFalse(app.textFields["bluetooth.testQR"].exists)
        XCTAssertFalse(app.staticTexts["connection.error"].label.contains("QR"))
        assertPublicHome()
        capture("10 Invitation PHOTO — sortie de la reprise Wi-Fi")
    }

    private func enterSyntheticPhotoInvitation(inputID: String = "connection.testQR", acceptID: String = "connection.acceptTestQR") throws {
        let payload: [String: Any] = [
            "v": 1, "p": "invite", "id": "11111111-2222-4333-8444-555555555555",
            "k": String(repeating: "1", count: 64), "url": "https://fixture.invalid:8443",
            "i": "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee", "t": String(repeating: "2", count: 64),
        ]
        let text = String(decoding: try JSONSerialization.data(withJSONObject: payload, options: [.sortedKeys, .withoutEscapingSlashes]), as: UTF8.self)
        let input = app.textFields[inputID]
        XCTAssertTrue(input.waitForExistence(timeout: 5))
        input.tap()
        input.typeText(text)
        app.buttons[acceptID].tap()
    }

    func testQRGuideAndPrimaryActionRemainReachableWithAccessibilityText() throws {
        launch(largeText: true)
        let scan = app.buttons["connection.scanLANQR"]
        XCTAssertTrue(scan.waitForExistence(timeout: 5))
        scrollTo(scan, in: app.scrollViews["connection.scroll"])
        XCTAssertTrue(scan.isHittable)
        capture("06 Accueil grand texte")
        let guide = app.buttons["connection.guide"]
        scrollTo(guide, in: app.scrollViews["connection.scroll"])
        guide.tap()
        XCTAssertTrue(app.buttons["guide.close"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.staticTexts["Le QR du cadre suffit pour commencer."].exists)
        let close = app.buttons["guide.connect"]
        scrollTo(close, in: app.scrollViews["guide.scroll"], maximum: 35)
        XCTAssertTrue(close.isHittable)
        capture("07 Aide grand texte")
        close.tap()
        XCTAssertTrue(scan.waitForExistence(timeout: 5))
    }

    func testHomeHasAccessibleDescriptionsAndTraits() throws {
        launch()
        assertPublicHome()
        try app.performAccessibilityAudit(for: [.sufficientElementDescription, .trait])
    }

    private func assertPublicHome() {
        let scan = app.buttons["connection.scanLANQR"]
        XCTAssertTrue(scan.waitForExistence(timeout: 5))
        XCTAssertEqual(scan.label, "Scanner un QR code")
        XCTAssertFalse(app.textFields["connection.address"].exists)
        XCTAssertFalse(app.secureTextFields["connection.password"].exists)
        XCTAssertFalse(app.buttons["connection.submit"].exists)
        XCTAssertFalse(app.buttons["connection.demo"].exists)
        XCTAssertFalse(app.buttons["demo.exit"].exists)
        XCTAssertFalse(app.buttons["connection.enableLANBiometrics"].exists)
        XCTAssertFalse(app.buttons["connection.skipLANBiometrics"].exists)
        XCTAssertFalse(app.tabBars.firstMatch.exists)
    }

    private func assertContentIsLocked() {
        XCTAssertFalse(app.tabBars.firstMatch.exists)
        XCTAssertFalse(app.buttons["frame.add"].exists)
        XCTAssertFalse(app.buttons["frame.next"].exists)
        XCTAssertFalse(app.collectionViews["queue.list"].exists)
        XCTAssertFalse(app.collectionViews["history.list"].exists)
        XCTAssertFalse(app.secureTextFields["connection.password"].exists)
        XCTAssertFalse(app.buttons["connection.scanLANQR"].exists)
    }

    private func launch(appearance: String = "Light", largeText: Bool = false,
                        authenticationFixture: String? = nil, extraArguments: [String] = []) {
        continueAfterFailure = false
        app = XCUIApplication()
        app.launchArguments = ["--uitesting", "-AppleLanguages", "(fr)", "-AppleLocale", "fr_FR",
                               "-AppleInterfaceStyle", appearance] + extraArguments
        if largeText {
            app.launchArguments += ["-UIPreferredContentSizeCategoryName", "UICTContentSizeCategoryAccessibilityXXXL"]
        }
        if let authenticationFixture {
            app.launchArguments += ["--local-auth-fixture", authenticationFixture]
        }
        app.launch()
        let teardown: @MainActor @Sendable () -> Void = { [weak self] in
            guard let self else { return }
            if (self.testRun?.failureCount ?? 0) > 0 { self.capture("Failure") }
            self.app.terminate()
        }
        addTeardownBlock(teardown)
    }

    private func scrollTo(_ target: XCUIElement, in scrollView: XCUIElement, maximum: Int = 20) {
        XCTAssertTrue(scrollView.waitForExistence(timeout: 5))
        for _ in 0..<maximum {
            if target.isHittable { return }
            scrollView.swipeUp()
        }
        XCTAssertTrue(target.isHittable, "The control must remain reachable at the requested text size.")
    }

    private func capture(_ title: String) {
        let attachment = XCTAttachment(screenshot: app.screenshot())
        attachment.name = title
        attachment.lifetime = .keepAlways
        add(attachment)
    }
}
