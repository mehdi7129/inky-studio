import XCTest
import UIKit

@MainActor final class BootstrapSetupUITests: XCTestCase {
    override func setUpWithError() throws { continueAfterFailure = false }

    func testAssociationScreensKeepBentoLightAndDarkWithoutPhotoOrWiFiCompletion() {
        for appearance in ["Light", "Dark"] {
            for state in ["introduction", "pending", "recovery"] {
                let app = XCUIApplication()
                app.launchArguments = ["--uitesting", "-factoryBootstrapEnabled", "YES",
                    "--bootstrap-fixture", state, "-AppleInterfaceStyle", appearance]
                app.launch()
                let entry = app.buttons["connection.factoryAssociation"]
                XCTAssertTrue(entry.waitForExistence(timeout: 5))
                if !entry.isHittable { app.swipeUp() }
                entry.tap()
                XCTAssertTrue(app.scrollViews["bootstrap.scroll"].waitForExistence(timeout: 5))
                switch state {
                case "introduction": XCTAssertTrue(app.buttons["bootstrap.scanQR"].exists)
                case "pending":
                    XCTAssertTrue(app.staticTexts["Préparation du cadre en attente"].exists)
                    XCTAssertTrue(app.staticTexts["Cet iPhone est associé"].exists)
                default:
                    XCTAssertTrue(app.buttons["bootstrap.resume"].exists)
                    XCTAssertTrue(app.staticTexts["bootstrap.error"].exists)
                }
                XCTAssertFalse(app.staticTexts["Votre cadre est connecté"].exists)
                XCTAssertFalse(app.buttons["bluetooth.apply"].exists)
                XCTAssertFalse(app.secureTextFields["bluetooth.password"].exists)
                capture(app, title: "bootstrap-\(state)-\(appearance.lowercased())", appearance: appearance)
                app.buttons["bootstrap.close"].tap()
                XCTAssertTrue(app.buttons["connection.factoryAssociation"].waitForExistence(timeout: 5))
                app.terminate()
            }
        }
    }
    func testCandidateFeatureRemainsClosedWithoutExplicitOptIn() {
        let app = XCUIApplication()
        app.launchArguments = ["--uitesting", "-factoryBootstrapEnabled", "NO"]
        app.launch()
        XCTAssertTrue(app.buttons["connection.demo"].waitForExistence(timeout: 5))
        XCTAssertFalse(app.buttons["connection.factoryAssociation"].exists)
    }
    private func capture(_ app: XCUIApplication, title: String, appearance: String) {
        let screenshot = app.screenshot()
        guard let image = screenshot.image.cgImage else { XCTFail("Missing screenshot pixels"); return }
        let sample = CGRect(x: CGFloat(image.width) * 0.01, y: CGFloat(image.height) * 0.5, width: 4, height: 4).integral
        guard let patch = image.cropping(to: sample), let space = CGColorSpace(name: CGColorSpace.sRGB) else {
            XCTFail("Cannot sample palette"); return
        }
        var pixel = [UInt8](repeating: 0, count: 4)
        let drawn = pixel.withUnsafeMutableBytes { bytes -> Bool in
            guard let context = CGContext(data: bytes.baseAddress, width: 1, height: 1,
                bitsPerComponent: 8, bytesPerRow: 4, space: space,
                bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue | CGBitmapInfo.byteOrder32Big.rawValue) else { return false }
            context.draw(patch, in: CGRect(x: 0, y: 0, width: 1, height: 1)); return true
        }
        XCTAssertTrue(drawn)
        let brightness = (0.2126 * Double(pixel[0]) + 0.7152 * Double(pixel[1]) + 0.0722 * Double(pixel[2])) / 255
        if appearance == "Dark" { XCTAssertLessThan(brightness, 0.25, "Rendered Dark palette: \(pixel)") }
        else { XCTAssertGreaterThan(brightness, 0.75, "Rendered Light palette: \(pixel)") }
        let attachment = XCTAttachment(screenshot: screenshot)
        attachment.name = title; attachment.lifetime = .keepAlways; add(attachment)
    }
}
