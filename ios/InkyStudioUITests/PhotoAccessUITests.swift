import UIKit
import CoreImage
import XCTest

/// Explicit DEBUG fixtures only. No backend, real frame, camera, Photos library
/// or actual credential is used. QR screenshots contain synthetic fixture data.
@MainActor
final class PhotoAccessUITests: XCTestCase {
    private var app: XCUIApplication!
    private let expectedFrameID = "11111111-2222-4333-8444-555555555555"
    private let expectedPin = String(repeating: "1", count: 64)
    private let expectedEndpoint = "https://192.168.1.120:8443"

    func testOwnerCreatesScannablePhotoInvitationAndCancellationRemovesIt() throws {
        launch("owner")
        selectTab("settings", label: "Réglages", title: "Réglages")
        // Same backend capabilities as the media fixture: role controls visibility.
        XCTAssertTrue(app.sliders["settings.saturation"].exists)
        XCTAssertTrue(app.buttons["settings.bluetooth"].exists)
        XCTAssertTrue(app.buttons["settings.checkUpdate"].exists)
        openSharing()
        let create = app.buttons["access.createInvitation"]
        XCTAssertTrue(create.waitForExistence(timeout: 5))
        XCTAssertTrue(create.isEnabled)
        scrollTo(create, in: accessScroll)
        create.tap()
        let revoke = app.buttons["access.revokeInvitation"]
        XCTAssertTrue(revoke.waitForExistence(timeout: 5))
        scrollTo(revoke, in: accessScroll)
        _ = try requireScannableInvitation()
        XCTAssertTrue(app.staticTexts["access.invitationExpiry"].exists)
        capture("Accès 01 — QR propriétaire décodable")
        revoke.tap()
        XCTAssertTrue(create.waitForExistence(timeout: 5))
        XCTAssertTrue(revoke.waitForNonExistence(timeout: 5))
        scrollTo(create, in: accessScroll)
        XCTAssertTrue(try detectedQRs().isEmpty, "Cancelling must remove the rendered invitation QR.")
        capture("Accès 02 — Invitation annulée")
    }

    func testMediaRoleKeepsPhotosAndSchedulingWithoutAdministrativeControls() {
        launch("media")
        selectTab("settings", label: "Réglages", title: "Réglages")
        let mode = app.segmentedControls["settings.mode"]
        XCTAssertTrue(mode.waitForExistence(timeout: 5))
        let interval = mode.buttons["Intervalle"]
        XCTAssertTrue(interval.isEnabled)
        interval.tap()
        let save = app.buttons["settings.save"]
        scrollTo(save, in: app.scrollViews["settings.scroll"])
        XCTAssertTrue(save.isEnabled, "A photo member must be allowed to change scheduling.")
        XCTAssertTrue(app.steppers["settings.interval"].exists)
        for identifier in ["settings.bluetooth", "settings.checkUpdate", "settings.shareAccess"] {
            XCTAssertFalse(app.buttons[identifier].exists, "A photo member must not receive the administrative action \(identifier).")
        }
        XCTAssertFalse(app.sliders["settings.saturation"].exists)
        XCTAssertFalse(app.buttons["access.createInvitation"].exists)
        capture("Accès 03 — Programmation membre photos")

        selectTab("frame", label: "Cadre", title: "Inky Studio")
        let add = app.buttons["frame.add"]
        scrollTo(add, in: app.scrollViews["frame.scroll"])
        XCTAssertTrue(add.isEnabled, "Photo access must retain the import action.")
        add.tap()
        XCTAssertTrue(app.buttons["choose-photo"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.buttons["choose-photo"].isEnabled)
        XCTAssertTrue(app.buttons["take-photo"].isEnabled)
        capture("Accès 04 — Sources photo membre")
        app.buttons["cancel-photo-import"].tap()
        XCTAssertTrue(add.waitForExistence(timeout: 5))
        selectTab("queue", label: "File", title: "À suivre")
        XCTAssertTrue(app.collectionViews["queue.list"].waitForExistence(timeout: 5))
        selectTab("history", label: "Historique", title: "Historique")
        XCTAssertTrue(app.collectionViews["history.list"].waitForExistence(timeout: 5))
    }

    func testPhotoMemberCanDisplayAndCancelAScannableQRWithoutDeviceAdministration() throws {
        launch("mediasharing")
        selectTab("settings", label: "Réglages", title: "Réglages")
        for identifier in ["settings.bluetooth", "settings.checkUpdate"] {
            XCTAssertFalse(app.buttons[identifier].exists)
        }
        XCTAssertFalse(app.sliders["settings.saturation"].exists)
        openSharing()
        XCTAssertTrue(app.staticTexts["Chaque personne autorisée peut aussi partager cet accès photos."].exists)
        XCTAssertFalse(app.staticTexts["Appareils autorisés"].exists)
        let create = app.buttons["access.createInvitation"]
        XCTAssertTrue(create.waitForExistence(timeout: 5))
        scrollTo(create, in: accessScroll)
        XCTAssertTrue(create.isEnabled)
        create.tap()
        let revoke = app.buttons["access.revokeInvitation"]
        XCTAssertTrue(revoke.waitForExistence(timeout: 5))
        scrollTo(revoke, in: accessScroll)
        _ = try requireScannableInvitation()
        XCTAssertTrue(app.staticTexts["access.invitationExpiry"].exists)
        XCTAssertFalse(app.staticTexts["Appareils autorisés"].exists)
        capture("Accès 08 — QR partage membre photos décodable")
        revoke.tap()
        XCTAssertTrue(create.waitForExistence(timeout: 5))
        scrollTo(create, in: accessScroll)
        XCTAssertTrue(try detectedQRs().isEmpty)
        app.buttons["access.close"].tap()
        selectTab("frame", label: "Cadre", title: "Inky Studio")
        XCTAssertTrue(app.buttons["frame.add"].isEnabled)
    }

    func testPhotoMemberCanRenewAnExpiredInvitationWithoutDeviceAdministration() throws {
        launch("mediasharingexpired")
        selectTab("settings", label: "Réglages", title: "Réglages")
        openSharing()
        let renew = app.buttons["access.renewInvitation"]
        XCTAssertTrue(renew.waitForExistence(timeout: 5))
        scrollTo(renew, in: accessScroll)
        XCTAssertTrue(app.staticTexts["Invitation expirée"].exists)
        XCTAssertTrue(try detectedQRs().isEmpty)
        XCTAssertFalse(app.staticTexts["Appareils autorisés"].exists)
        renew.tap()
        let revoke = app.buttons["access.revokeInvitation"]
        XCTAssertTrue(revoke.waitForExistence(timeout: 5))
        scrollTo(revoke, in: accessScroll)
        _ = try requireScannableInvitation()
        XCTAssertFalse(renew.exists)
        XCTAssertFalse(app.staticTexts["Appareils autorisés"].exists)
        capture("Accès 09 — QR membre photos renouvelé")
    }

    func testExpiredInvitationHasNoRenderedQRAndCanBeRenewed() throws {
        launch("invitationexpired")
        selectTab("settings", label: "Réglages", title: "Réglages")
        openSharing()
        let renew = app.buttons["access.renewInvitation"]
        XCTAssertTrue(renew.waitForExistence(timeout: 5))
        scrollTo(renew, in: accessScroll)
        XCTAssertTrue(app.staticTexts["Invitation expirée"].exists)
        XCTAssertFalse(app.buttons["access.revokeInvitation"].exists)
        XCTAssertFalse(app.staticTexts["access.invitationExpiry"].exists)
        XCTAssertTrue(try detectedQRs().isEmpty, "An expired invitation must not remain visually scannable.")
        capture("Accès 05 — Invitation expirée sans QR")
        XCTAssertTrue(renew.isEnabled)
        renew.tap()
        let revoke = app.buttons["access.revokeInvitation"]
        XCTAssertTrue(revoke.waitForExistence(timeout: 5))
        scrollTo(revoke, in: accessScroll)
        _ = try requireScannableInvitation()
        XCTAssertFalse(renew.exists)
        XCTAssertFalse(app.staticTexts["Invitation expirée"].exists)
        capture("Accès 06 — Nouvelle invitation décodable")
    }

    func testClosingSharingPreservesTheSameActiveInvitationUntilExplicitCancellation() throws {
        launch("owner")
        selectTab("settings", label: "Réglages", title: "Réglages")
        openSharing()
        let create = app.buttons["access.createInvitation"]
        XCTAssertTrue(create.waitForExistence(timeout: 5))
        scrollTo(create, in: accessScroll)
        create.tap()
        let revoke = app.buttons["access.revokeInvitation"]
        XCTAssertTrue(revoke.waitForExistence(timeout: 5))
        scrollTo(revoke, in: accessScroll)
        let original = try requireScannableInvitation()
        app.buttons["access.close"].tap()
        XCTAssertTrue(app.buttons["settings.shareAccess"].waitForExistence(timeout: 5))
        openSharing()
        XCTAssertTrue(revoke.waitForExistence(timeout: 5))
        scrollTo(revoke, in: accessScroll)
        let reopened = try requireScannableInvitation()
        // Boolean assertions prevent XCTest from printing an invitation token.
        XCTAssertTrue(original.invitationID == reopened.invitationID,
                      "Closing the sheet must not silently create a different invitation.")
        XCTAssertTrue(original.token == reopened.token,
                      "Reopening must preserve the active invitation rather than silently rotate its authorization.")
        XCTAssertFalse(create.exists)
        capture("Accès 07 — Invitation conservée après fermeture")
    }

    private var accessScroll: XCUIElement { app.scrollViews["access.scroll"] }

    private func launch(_ fixture: String) {
        continueAfterFailure = false
        app = XCUIApplication()
        app.launchArguments = ["--uitesting", "--photo-access-fixture", fixture,
                               "-AppleLanguages", "(fr)", "-AppleLocale", "fr_FR"]
        app.launch()
        XCTAssertTrue(app.buttons["frame.add"].waitForExistence(timeout: 10),
                      "The scoped photo-access fixture must start locally unlocked and connected.")
        let teardown: @MainActor @Sendable () -> Void = { [weak self] in
            guard let self else { return }
            if (self.testRun?.failureCount ?? 0) > 0 { self.capture("Accès — Échec \(self.name)") }
            self.app.terminate()
        }
        addTeardownBlock(teardown)
    }

    private func openSharing() {
        let share = app.buttons["settings.shareAccess"]
        XCTAssertTrue(share.waitForExistence(timeout: 5))
        scrollTo(share, in: app.scrollViews["settings.scroll"])
        XCTAssertTrue(share.isEnabled)
        share.tap()
        XCTAssertTrue(accessScroll.waitForExistence(timeout: 5))
        XCTAssertTrue(app.navigationBars["Partager l’accès"].exists)
    }

    private func selectTab(_ identifier: String, label: String, title: String) {
        let identified = app.buttons["tab.\(identifier)"]
        let tab = identified.exists ? identified : app.tabBars.buttons[label]
        XCTAssertTrue(tab.waitForExistence(timeout: 5))
        if #available(iOS 27, *) {
            // Native floating tabs can report an invalid automatic hit point.
            // Use only their observed window-relative geometry, then verify destination.
            let window = app.windows.firstMatch
            let frame = tab.frame
            XCTAssertTrue(window.frame.contains(frame))
            XCTAssertGreaterThan(frame.width, 0)
            window.coordinate(withNormalizedOffset: .zero)
                .withOffset(CGVector(dx: frame.midX - window.frame.minX,
                                     dy: frame.midY - window.frame.minY)).tap()
        } else { tab.tap() }
        XCTAssertTrue(app.navigationBars[title].waitForExistence(timeout: 5))
    }

    private func scrollTo(_ element: XCUIElement, in scrollView: XCUIElement) {
        XCTAssertTrue(scrollView.waitForExistence(timeout: 5))
        for _ in 0..<16 {
            let viewport = visibleViewport(of: scrollView)
            guard viewport.width > 24, viewport.height > 88 else {
                XCTFail("The scroll view must expose a valid gesture area.")
                return
            }
            let frame = element.exists ? element.frame : .zero
            if element.exists && element.isHittable && viewport.insetBy(dx: -1, dy: -1).contains(frame) { return }
            let upwards = element.exists && !frame.isEmpty && frame.minY < viewport.minY
            let gap = element.exists && !frame.isEmpty
                ? (upwards ? viewport.minY - frame.minY : frame.maxY - viewport.maxY) : 140
            let distance = min(viewport.height * 0.3, max(70, gap + 14))
            let x = viewport.minX + 12
            let startY = upwards ? viewport.minY + 16 : viewport.maxY - 44
            let endY = startY + (upwards ? distance : -distance)
            let window = app.windows.firstMatch
            let origin = window.coordinate(withNormalizedOffset: .zero)
            let start = origin.withOffset(CGVector(dx: x - window.frame.minX, dy: startY - window.frame.minY))
            let end = origin.withOffset(CGVector(dx: x - window.frame.minX, dy: endY - window.frame.minY))
            start.press(forDuration: 0, thenDragTo: end, withVelocity: .default, thenHoldForDuration: 0)
        }
        XCTFail("The requested control must be visible and clear of native bars.")
    }

    private func visibleViewport(of scrollView: XCUIElement) -> CGRect {
        let window = app.windows.firstMatch.frame
        let bounds = scrollView.frame.intersection(window)
        let navigationTitle: String
        switch scrollView.identifier {
        case "access.scroll": navigationTitle = "Partager l’accès"
        case "settings.scroll": navigationTitle = "Réglages"
        default: navigationTitle = "Inky Studio"
        }
        let navigation = app.navigationBars[navigationTitle]
        let top = navigation.exists && navigation.frame.intersects(bounds) ? max(bounds.minY, navigation.frame.maxY) : bounds.minY
        let tabs = app.tabBars.firstMatch
        let bottom = scrollView.identifier != "access.scroll" && tabs.exists && tabs.frame.intersects(bounds)
            ? min(bounds.maxY, tabs.frame.minY) : bounds.maxY
        return CGRect(x: bounds.minX, y: top, width: bounds.width, height: max(0, bottom - top))
    }

    private struct InvitationQR {
        let frameID: String
        let pin: String
        let endpoint: String
        let invitationID: String
        let token: String
    }
    private enum QRReadFailure: Error {
        case missingScreenshotPixels, missingInvitation, coreImageDetectorUnavailable, unreadableQRCode
    }

    private func requireScannableInvitation() throws -> InvitationQR {
        let invitations = try decodedInvitations()
        XCTAssertEqual(invitations.count, 1, "Exactly one photo invitation must be decodable from the rendered screen.")
        guard let invitation = invitations.first else { throw QRReadFailure.missingInvitation }
        XCTAssertTrue(invitation.frameID == expectedFrameID, "The QR must bind the synthetic frame identity.")
        XCTAssertTrue(invitation.pin == expectedPin, "The QR must carry the expected synthetic frame pin.")
        XCTAssertTrue(invitation.endpoint == expectedEndpoint, "The QR must advertise the expected pinned HTTPS origin.")
        return invitation
    }

    private func detectedQRs() throws -> [String] {
        let screenshot = app.screenshot()
        let attachment = XCTAttachment(screenshot: screenshot)
        attachment.name = "Entrée lecture QR"
        attachment.lifetime = .keepAlways
        add(attachment)
        guard let image = screenshot.image.cgImage else { throw QRReadFailure.missingScreenshotPixels }
        // Decode the exact screenshot pixels on the CPU; no payload fixture or detector fallback.
        let context = CIContext(options: [.useSoftwareRenderer: true])
        guard let detector = CIDetector(ofType: CIDetectorTypeQRCode, context: context,
                                        options: [CIDetectorAccuracy: CIDetectorAccuracyHigh]) else {
            // CIDetector exposes no NSError: nil is an explicit unavailable-detector failure.
            throw QRReadFailure.coreImageDetectorUnavailable
        }
        return try detector.features(in: CIImage(cgImage: image)).map { feature in
            guard let qr = feature as? CIQRCodeFeature, let payload = qr.messageString else {
                throw QRReadFailure.unreadableQRCode
            }
            return payload
        }
    }

    private func decodedInvitations() throws -> [InvitationQR] {
        var invitations: [InvitationQR] = []
        for text in try detectedQRs() {
            guard let bytes = text.data(using: .utf8),
                  let object = (try? JSONSerialization.jsonObject(with: bytes)) as? [String: Any],
                  object["p"] as? String == "invite" else { continue }
            // Compare schema and non-secret identity fields, never print payloads/tokens.
            XCTAssertTrue(Set(object.keys) == ["v", "p", "id", "k", "url", "i", "t"],
                          "An invitation QR must not expose a password, cookie or owner credential.")
            XCTAssertTrue(object["v"] as? Int == 1, "The invitation QR must use the agreed wire version.")
            guard let frameID = object["id"] as? String, let pin = object["k"] as? String,
                  let endpoint = object["url"] as? String, let invitationID = object["i"] as? String,
                  let token = object["t"] as? String else {
                XCTFail("The rendered invitation QR must contain all required string fields.")
                continue
            }
            XCTAssertTrue(UUID(uuidString: invitationID) != nil)
            XCTAssertTrue(token.utf8.count == 64 && token.utf8.allSatisfy { (48...57).contains($0) || (97...102).contains($0) },
                          "The invitation credential must have the bounded canonical token shape.")
            invitations.append(InvitationQR(frameID: frameID, pin: pin, endpoint: endpoint,
                                            invitationID: invitationID, token: token))
        }
        return invitations
    }

    private func capture(_ title: String) {
        let attachment = XCTAttachment(screenshot: app.screenshot())
        attachment.name = title
        attachment.lifetime = .keepAlways
        add(attachment)
    }
}
