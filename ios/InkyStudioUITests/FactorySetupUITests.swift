import XCTest

/// Inert DEBUG screens: no ownership, BLE/TLS connection or setup success is fabricated.
@MainActor
final class FactorySetupUITests: XCTestCase {
    override func setUpWithError() throws { continueAfterFailure = false }

    func testCountryRequiresAnExplicitChoice() {
        let app = launchFixture("factory-country")
        XCTAssertTrue(app.staticTexts["Dans quel pays est le cadre ?"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.buttons["factory.country"].exists)
        XCTAssertFalse(app.buttons["factory.apply"].isEnabled)
        assertNoTechnicalInput(app)
        capture(app, name: "factory-country-explicit-choice")
    }

    func testRecoveryRequiresAnExplicitNewAttempt() {
        let app = launchFixture("factory-recovery")
        XCTAssertTrue(app.staticTexts["Reprendre cette étape"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.buttons["factory.apply"].exists)
        XCTAssertFalse(app.buttons["factory.apply"].isEnabled)
        XCTAssertFalse(app.buttons["factory.finish"].exists)
        assertNoTechnicalInput(app)
        capture(app, name: "factory-recovery-explicit-attempt")
    }

    func testWaitingForOriginStillOffersBluetoothWiFi() {
        let app = launchFixture("factory-waiting")
        XCTAssertTrue(app.staticTexts["Retrouver le cadre sur le réseau"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.buttons["factory.configureWiFi"].isEnabled)
        XCTAssertFalse(app.buttons["factory.finish"].exists)
        assertNoTechnicalInput(app)
        capture(app, name: "factory-waiting-origin-wifi-available")
    }

    func testMainBootstrapQRRoutesToGlobalFactorySheetAndClosesToHome() {
        let app = XCUIApplication()
        app.launchArguments = ["--uitesting", "--qr-input-fixture", "--local-auth-fixture", "success",
                               "--bluetooth-fixture", "factory-country", "-AppleInterfaceStyle", "Light"]
        app.launch()
        let scan = app.buttons["connection.scanLANQR"]
        XCTAssertTrue(scan.waitForExistence(timeout: 5))
        scan.tap()
        let input = app.textFields["connection.testQR"]
        XCTAssertTrue(input.waitForExistence(timeout: 5))
        // Synthetic QR only. The global fixture stops before BLE, ownership or mutation.
        let token = String(repeating: "ab", count: 32)
        let qr = "{\"v\":2,\"p\":\"bootstrap\",\"id\":\"11111111-2222-3333-4444-555555555555\",\"k\":\"f2f84e202379f0b31a408b6959692ba0509af4d1ad6f7e15feaa4c2b0aed1315\",\"t\":\"\(token)\"}"
        input.tap()
        input.typeText(qr)
        app.buttons["connection.acceptTestQR"].tap()

        XCTAssertTrue(app.navigationBars["Configurer le cadre"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.buttons["factory.country"].waitForExistence(timeout: 5))
        XCTAssertFalse(app.navigationBars["Scanner un QR code"].exists)
        XCTAssertFalse(app.buttons["factory.apply"].isEnabled)
        assertNoTechnicalInput(app)
        capture(app, name: "factory-main-qr-routing")

        app.buttons["bluetooth.close"].tap()
        XCTAssertTrue(scan.waitForExistence(timeout: 5))
        XCTAssertFalse(app.navigationBars["Configurer le cadre"].exists)
        XCTAssertFalse(app.textFields["connection.testQR"].exists)
        XCTAssertFalse(app.buttons["frame.add"].exists)
    }

    private func launchFixture(_ state: String) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = ["--uitesting", "--bluetooth-fixture", state,
                               "-AppleInterfaceStyle", "Light"]
        app.launch()
        let entry = app.buttons["connection.bluetooth"]
        XCTAssertTrue(entry.waitForExistence(timeout: 5))
        if !entry.isHittable { app.swipeUp() }
        entry.tap()
        return app
    }

    private func assertNoTechnicalInput(_ app: XCUIApplication) {
        XCTAssertEqual(app.textFields.count, 0)
        XCTAssertEqual(app.secureTextFields.count, 0)
        XCTAssertEqual(app.datePickers.count, 0)
    }

    private func capture(_ app: XCUIApplication, name: String) {
        let attachment = XCTAttachment(screenshot: app.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }
}
