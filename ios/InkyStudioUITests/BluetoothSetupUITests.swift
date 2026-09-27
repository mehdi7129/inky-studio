import XCTest

@MainActor
final class BluetoothSetupUITests: XCTestCase {
    override func setUpWithError() throws { continueAfterFailure = false }

    func testWiFiNetworksLightAndDark() {
        for appearance in ["Light", "Dark"] {
            let app = launchFixture("networks", appearance: appearance)
            XCTAssertTrue(app.staticTexts["Choisir un réseau Wi-Fi"].waitForExistence(timeout: 5))
            XCTAssertTrue(app.staticTexts["Atelier"].exists)
            XCTAssertTrue(app.staticTexts["Non compatible"].exists)
            capture(app, name: "bluetooth-networks-\(appearance.lowercased())")
            app.terminate()
        }
    }

    func testWiFiCredentialAndConfirmationFixtureNeverConnectsToAFrame() {
        let app = launchFixture("credentials", appearance: "Light")
        let ssid = app.textFields["bluetooth.ssid"]
        XCTAssertTrue(ssid.waitForExistence(timeout: 5))
        XCTAssertEqual(ssid.value as? String, "Atelier")
        let apply = app.buttons["bluetooth.apply"]
        XCTAssertFalse(apply.isEnabled)
        capture(app, name: "bluetooth-credentials-light")
        let password = app.secureTextFields["bluetooth.password"]
        password.tap()
        password.typeText("synthetic-password")
        XCTAssertTrue(apply.isEnabled)
        apply.tap()
        XCTAssertTrue(app.staticTexts["Vérifier la connexion"].waitForExistence(timeout: 5))
        capture(app, name: "bluetooth-confirmation-light")
        app.buttons["Annuler l’essai Wi-Fi"].tap()
        XCTAssertTrue(app.staticTexts["L’essai Wi-Fi est terminé"].waitForExistence(timeout: 5))
        XCTAssertFalse(app.buttons["Retrouver mon cadre"].exists)
        capture(app, name: "bluetooth-rollback-light")
    }

    private func launchFixture(_ state: String, appearance: String) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = ["--uitesting", "--bluetooth-fixture", state, "-AppleInterfaceStyle", appearance]
        app.launch()
        let entry = app.buttons["connection.bluetooth"]
        XCTAssertTrue(entry.waitForExistence(timeout: 5))
        if !entry.isHittable { app.swipeUp() }
        entry.tap()
        return app
    }
    private func capture(_ app: XCUIApplication, name: String) {
        let image = XCTAttachment(screenshot: app.screenshot())
        image.name = name
        image.lifetime = .keepAlways
        add(image)
    }
}
