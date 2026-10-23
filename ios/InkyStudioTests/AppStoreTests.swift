import Combine
import Security
import SwiftUI
import UIKit
import XCTest
@testable import InkyStudio

@MainActor
final class AppStoreTests: XCTestCase {
    private let lanQR = "{\"v\":1,\"p\":\"lan-login\",\"url\":\"http://192.168.1.120:8000\",\"password\":\"DemoPass12345678\"}"

    func testWindowSceneAnchorClosesAdmissionSynchronouslyAndIgnoresDetachedCallbacks() throws {
        let scene = try XCTUnwrap(UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }.first)
        let window = UIWindow(windowScene: scene)
        var phases: [ScenePhase] = []
        let anchor = ScenePrivacyAnchorView { phases.append($0) }
        window.addSubview(anchor)
        defer {
            anchor.detach()
            // Restore the host's existing anchor after scoped synthetic notifications.
            NotificationCenter.default.post(name: UIScene.didActivateNotification, object: scene)
        }
        NotificationCenter.default.post(name: UIScene.willDeactivateNotification, object: scene)
        XCTAssertEqual(phases, [.inactive], "No next-run-loop admission window may remain after native deactivation.")
        NotificationCenter.default.post(name: UIScene.didEnterBackgroundNotification, object: scene)
        XCTAssertEqual(phases, [.inactive, .background])
        anchor.detach()
        NotificationCenter.default.post(name: UIScene.willDeactivateNotification, object: scene)
        XCTAssertEqual(phases, [.inactive, .background])
    }

    func testRecoveryCancellationPreservesOldSessionWithoutReadingItsCredential() async throws {
        var localChecks = 0
        var credentialReads = 0
        let fixture = StoreFixture(authenticateLocal: { localChecks += 1 }, loadCredential: { _ in
            credentialReads += 1
            throw VaultError.missing
        })
        defer { fixture.dispose() }
        await fixture.login("old-frame.local")
        let oldClient = try XCTUnwrap(fixture.store.api)
        let oldAddress = fixture.store.address
        fixture.credentials.passwords[oldAddress] = "old-protected-credential"
        fixture.store.lock()
        let requests = fixture.stub.requests.count
        await fixture.store.beginConnectionRecovery()
        XCTAssertEqual(localChecks, 2, "Recovery authorizes locally without trying the irreparable old item")
        XCTAssertEqual(credentialReads, 0)
        XCTAssertTrue(fixture.store.recoveringConnection)
        XCTAssertFalse(fixture.store.canMutate)
        fixture.store.cancelConnectionRecovery()
        XCTAssertFalse(fixture.store.recoveringConnection)
        XCTAssertFalse(fixture.store.localUnlocked)
        XCTAssertTrue(fixture.store.api === oldClient)
        XCTAssertEqual(fixture.store.address, oldAddress)
        XCTAssertEqual(fixture.defaults.string(forKey: "frameAddress"), oldAddress)
        XCTAssertEqual(fixture.credentials.passwords[oldAddress], "old-protected-credential")
        XCTAssertEqual(fixture.stub.requests.count, requests)
    }

    func testRecoveryMalformedOrRejectedQRPreservesOldSelectedAccess() async throws {
        let fixture = StoreFixture()
        defer { fixture.dispose() }
        await fixture.login("old-frame.local")
        let oldClient = try XCTUnwrap(fixture.store.api)
        let oldAddress = fixture.store.address
        fixture.credentials.passwords[oldAddress] = "old-protected-credential"
        await fixture.store.beginConnectionRecovery()
        let before = fixture.stub.requests.count
        await fixture.store.loginFromLANQRCode("invalid-qr")
        XCTAssertEqual(fixture.stub.requests.count, before)
        fixture.stub.respondNextJSON(host: "192.168.1.120", path: "/api/auth/login", method: "POST", status: 401,
                                     body: ["detail": "Synthetic rejection"])
        await fixture.store.loginFromLANQRCode(lanQR)
        XCTAssertTrue(fixture.store.api === oldClient)
        XCTAssertTrue(fixture.store.authenticated)
        XCTAssertTrue(fixture.store.recoveringConnection)
        XCTAssertEqual(fixture.store.address, oldAddress)
        XCTAssertEqual(fixture.defaults.string(forKey: "frameAddress"), oldAddress)
        XCTAssertEqual(fixture.credentials.passwords[oldAddress], "old-protected-credential")
        XCTAssertNil(fixture.credentials.passwords["http://192.168.1.120:8000"])
        XCTAssertNotNil(fixture.store.errorMessage)
    }

    func testRecoveryFailedProtectedSaveDoesNotReplaceOldConnection() async throws {
        let fixture = StoreFixture(saveCredential: { _, _ in throw VaultError.unavailable })
        defer { fixture.dispose() }
        await fixture.login("old-frame.local")
        let oldClient = try XCTUnwrap(fixture.store.api)
        let oldAddress = fixture.store.address
        fixture.credentials.passwords[oldAddress] = "old-protected-credential"
        await fixture.store.beginConnectionRecovery()
        await fixture.store.loginFromLANQRCode(lanQR)
        XCTAssertTrue(fixture.store.api === oldClient)
        XCTAssertTrue(fixture.store.authenticated)
        XCTAssertTrue(fixture.store.recoveringConnection)
        XCTAssertEqual(fixture.defaults.string(forKey: "frameAddress"), oldAddress)
        XCTAssertEqual(fixture.credentials.passwords[oldAddress], "old-protected-credential")
        XCTAssertNil(fixture.credentials.passwords["http://192.168.1.120:8000"])
    }

    func testRecoveryCommitsOnlyAfterCandidateLoginAndProtectedSave() async throws {
        let fixture = StoreFixture()
        defer { fixture.dispose() }
        await fixture.login("old-frame.local")
        let oldClient = try XCTUnwrap(fixture.store.api)
        let oldAddress = fixture.store.address
        fixture.credentials.passwords[oldAddress] = "old-protected-credential"
        await fixture.store.beginConnectionRecovery()
        let gate = fixture.stub.hold(host: "192.168.1.120", path: "/api/auth/login", method: "POST")
        let replacement = Task { await fixture.store.loginFromLANQRCode(lanQR) }
        await fulfillment(of: [gate.started], timeout: 3)
        XCTAssertTrue(fixture.store.api === oldClient)
        XCTAssertEqual(fixture.defaults.string(forKey: "frameAddress"), oldAddress)
        XCTAssertNil(fixture.credentials.passwords["http://192.168.1.120:8000"])
        gate.release()
        await replacement.value
        XCTAssertFalse(fixture.store.api === oldClient)
        XCTAssertEqual(fixture.store.address, "http://192.168.1.120:8000")
        XCTAssertEqual(fixture.defaults.string(forKey: "frameAddress"), fixture.store.address)
        XCTAssertEqual(fixture.credentials.passwords[fixture.store.address], "DemoPass12345678")
        XCTAssertEqual(fixture.credentials.passwords[oldAddress], "old-protected-credential")
        XCTAssertFalse(fixture.store.recoveringConnection)
        XCTAssertTrue(fixture.store.credentialStored)
        XCTAssertTrue(fixture.store.canMutate)
        XCTAssertFalse(fixture.stub.requests.contains { $0.url?.host == "old-frame.local" && $0.url?.path == "/api/auth/logout" })
    }

    func testRecoveryCancelledDuringCandidateAuthenticationCannotCommitLate() async throws {
        let fixture = StoreFixture()
        defer { fixture.dispose() }
        await fixture.login("old-frame.local")
        let oldClient = try XCTUnwrap(fixture.store.api)
        let oldAddress = fixture.store.address
        fixture.credentials.passwords[oldAddress] = "old-protected-credential"
        await fixture.store.beginConnectionRecovery()
        let gate = fixture.stub.hold(host: "192.168.1.120", path: "/api/auth/login", method: "POST")
        let replacement = Task { await fixture.store.loginFromLANQRCode(lanQR) }
        await fulfillment(of: [gate.started], timeout: 3)
        fixture.store.cancelLogin()
        gate.release()
        await replacement.value
        XCTAssertTrue(fixture.store.api === oldClient)
        XCTAssertTrue(fixture.store.authenticated)
        XCTAssertFalse(fixture.store.localUnlocked)
        XCTAssertEqual(fixture.store.address, oldAddress)
        XCTAssertEqual(fixture.credentials.passwords[oldAddress], "old-protected-credential")
        XCTAssertNil(fixture.credentials.passwords["http://192.168.1.120:8000"])
    }

    func testRecoveryNeverDowngradesAnAdoptedFrameToHTTP() async {
        let fixture = StoreFixture()
        defer { fixture.dispose() }
        let selectedOwner = UUID().uuidString.lowercased()
        fixture.defaults.set(selectedOwner, forKey: "frameOwnerID")
        fixture.defaults.set("https://192.168.1.120:8443", forKey: "frameAddress")
        fixture.store.address = "https://192.168.1.120:8443"
        fixture.credentials.passwords["inky-frame:" + selectedOwner] = "selected-owner-credential"
        await fixture.store.beginConnectionRecovery()
        XCTAssertFalse(fixture.store.recoveringConnection)
        XCTAssertFalse(fixture.store.canScanLANLoginCode)
        await fixture.store.loginFromLANQRCode(lanQR)
        XCTAssertTrue(fixture.stub.requests.isEmpty)
        XCTAssertEqual(fixture.defaults.string(forKey: "frameOwnerID"), selectedOwner)
        XCTAssertEqual(fixture.store.address, "https://192.168.1.120:8443")
        XCTAssertEqual(fixture.credentials.passwords["inky-frame:" + selectedOwner], "selected-owner-credential")
    }

    func testForgetAuthorizationCancellationAndBackgroundPreserveSelectedAccess() async throws {
        let fixture = StoreFixture()
        defer { fixture.dispose() }
        await fixture.login("old-frame.local")
        let oldClient = try XCTUnwrap(fixture.store.api)
        let oldAddress = fixture.store.address
        fixture.credentials.passwords[oldAddress] = "old-protected-credential"
        let requests = fixture.stub.requests.count
        let authorized = await fixture.store.authorizeForgetCurrentFrame()
        XCTAssertTrue(authorized)
        XCTAssertFalse(fixture.store.localUnlocked)
        XCTAssertFalse(fixture.store.canMutate)
        fixture.store.cancelForgetCurrentFrame()
        await fixture.store.forgetCurrentFrameAfterConfirmation()
        XCTAssertTrue(fixture.store.api === oldClient)
        XCTAssertEqual(fixture.defaults.string(forKey: "frameAddress"), oldAddress)
        let again = await fixture.store.authorizeForgetCurrentFrame()
        XCTAssertTrue(again)
        fixture.store.sceneChanged(.background)
        await fixture.store.forgetCurrentFrameAfterConfirmation()
        XCTAssertTrue(fixture.store.api === oldClient)
        XCTAssertEqual(fixture.defaults.string(forKey: "frameAddress"), oldAddress)
        XCTAssertEqual(fixture.credentials.passwords[oldAddress], "old-protected-credential")
        XCTAssertEqual(fixture.stub.requests.count, requests)
    }

    func testForgetAuthorizationDoesNotUnlockContentForAnAdoptedLiveSession() async throws {
        let fixture = StoreFixture()
        defer { fixture.dispose() }
        await fixture.login("old-frame.local")
        let client = try XCTUnwrap(fixture.store.api)
        let owner = UUID().uuidString.lowercased()
        let locator = "https://192.168.1.120:8443"
        fixture.defaults.set(owner, forKey: "frameOwnerID")
        fixture.defaults.set(locator, forKey: "frameAddress")
        fixture.store.address = locator
        fixture.store.lock()
        let requests = fixture.stub.requests.count
        let authorized = await fixture.store.authorizeForgetCurrentFrame()
        XCTAssertTrue(authorized)
        XCTAssertTrue(fixture.store.authenticated)
        XCTAssertFalse(fixture.store.localUnlocked, "Authorization to forget is not authorization to expose the dashboard")
        XCTAssertFalse(fixture.store.canMutate)
        fixture.store.cancelForgetCurrentFrame()
        await fixture.store.forgetCurrentFrameAfterConfirmation()
        XCTAssertTrue(fixture.store.api === client)
        XCTAssertEqual(fixture.defaults.string(forKey: "frameOwnerID"), owner)
        XCTAssertEqual(fixture.defaults.string(forKey: "frameAddress"), locator)
        XCTAssertFalse(fixture.store.localUnlocked)
        XCTAssertEqual(fixture.stub.requests.count, requests)
    }

    func testForgetConfirmationIsScopedToTheFreshlyAuthorizedSelectedAccount() async throws {
        let fixture = StoreFixture()
        defer { fixture.dispose() }
        let selected = UUID().uuidString.lowercased()
        let other = UUID().uuidString.lowercased()
        fixture.defaults.set(selected, forKey: "frameOwnerID")
        fixture.defaults.set("https://192.168.1.120:8443", forKey: "frameAddress")
        fixture.store.address = "https://192.168.1.120:8443"
        let selectedAccount = "inky-frame:" + selected
        let otherAccount = "inky-frame:" + other
        func query(_ account: String) -> [String: Any] {
            [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: fixture.vaultService,
             kSecAttrAccount as String: account]
        }
        for account in [selectedAccount, otherAccount] {
            var item = query(account)
            item[kSecValueData as String] = Data("synthetic-test-credential".utf8)
            XCTAssertEqual(SecItemAdd(item as CFDictionary, nil), errSecSuccess)
        }
        // These are synthetic, unprotected legacy items solely to check deletion scope, not biometric behavior.
        let authorized = await fixture.store.authorizeForgetCurrentFrame()
        XCTAssertTrue(authorized)
        XCTAssertFalse(fixture.store.localUnlocked)
        XCTAssertFalse(fixture.store.canMutate)
        fixture.store.cancelForgetCurrentFrame()
        await fixture.store.forgetCurrentFrameAfterConfirmation()
        XCTAssertEqual(SecItemCopyMatching(query(selectedAccount) as CFDictionary, nil), errSecSuccess)
        let again = await fixture.store.authorizeForgetCurrentFrame()
        XCTAssertTrue(again)
        await fixture.store.forgetCurrentFrameAfterConfirmation()
        XCTAssertEqual(SecItemCopyMatching(query(selectedAccount) as CFDictionary, nil), errSecItemNotFound)
        XCTAssertEqual(SecItemCopyMatching(query(otherAccount) as CFDictionary, nil), errSecSuccess)
        XCTAssertNil(fixture.defaults.string(forKey: "frameOwnerID"))
        XCTAssertNil(fixture.defaults.string(forKey: "frameAddress"))
        XCTAssertFalse(fixture.store.localUnlocked)
    }

    func testFirstQRAuthenticatesLocallyBeforeNetworkingAndStoresValidatedCredential() async {
        let gate = LocalAuthGate()
        let fixture = StoreFixture(authenticateLocal: { try await gate.wait() })
        defer { fixture.dispose() }
        let login = Task { await fixture.store.loginFromLANQRCode(lanQR) }
        await fulfillment(of: [gate.started], timeout: 3)
        XCTAssertFalse(fixture.store.localUnlocked)
        XCTAssertTrue(fixture.store.unlocking)
        XCTAssertTrue(fixture.stub.requests.isEmpty)
        gate.release()
        await login.value
        XCTAssertTrue(fixture.store.localUnlocked)
        XCTAssertTrue(fixture.store.authenticated)
        XCTAssertTrue(fixture.store.credentialStored)
        XCTAssertEqual(fixture.credentials.passwords["http://192.168.1.120:8000"], "DemoPass12345678")
        XCTAssertFalse(fixture.defaults.dictionaryRepresentation().description.contains("DemoPass12345678"))
    }

    func testMissingPasscodeOrCancelledLocalAuthenticationCannotSendTheQRSecret() async {
        for error in [VaultError.passcodeRequired, .cancelled] {
            let fixture = StoreFixture(authenticateLocal: { throw error })
            defer { fixture.dispose() }
            await fixture.store.loginFromLANQRCode(lanQR)
            XCTAssertFalse(fixture.store.localUnlocked)
            XCTAssertFalse(fixture.store.authenticated)
            XCTAssertFalse(fixture.store.unlocking)
            XCTAssertNotNil(fixture.store.localAuthenticationError)
            XCTAssertTrue(fixture.stub.requests.isEmpty)
            XCTAssertTrue(fixture.credentials.passwords.isEmpty)
        }
    }

    func testBackgroundInvalidatesLateLocalAuthenticationButInactiveDoesNot() async {
        let gate = LocalAuthGate()
        let fixture = StoreFixture(authenticateLocal: { try await gate.wait() })
        defer { fixture.dispose() }
        let login = Task { await fixture.store.loginFromLANQRCode(lanQR) }
        await fulfillment(of: [gate.started], timeout: 3)
        fixture.store.sceneChanged(.inactive)
        XCTAssertTrue(fixture.store.unlocking)
        fixture.store.sceneChanged(.active)
        gate.release()
        await login.value
        XCTAssertTrue(fixture.store.authenticated)
        await fixture.store.logout()
        XCTAssertFalse(fixture.store.localUnlocked)

        let lateGate = LocalAuthGate()
        let late = StoreFixture(authenticateLocal: { try await lateGate.wait() })
        defer { late.dispose() }
        let oldLogin = Task { await late.store.loginFromLANQRCode(lanQR) }
        await fulfillment(of: [lateGate.started], timeout: 3)
        late.store.sceneChanged(.background)
        late.store.sceneChanged(.active)
        lateGate.release()
        await oldLogin.value
        XCTAssertFalse(late.store.localUnlocked)
        XCTAssertFalse(late.store.authenticated)
        XCTAssertTrue(late.stub.requests.isEmpty)
    }

    func testCancelledQRTaskDuringInitialRefreshDoesNotPublishPartialSession() async {
        for path in ["/api/state", "/api/provisioning/capabilities"] {
            let fixture = StoreFixture()
            defer { fixture.dispose() }
            let gate = fixture.stub.hold(host: "192.168.1.120", path: path)
            let login = Task { await fixture.store.loginFromLANQRCode(lanQR) }
            await fulfillment(of: [gate.started], timeout: 3)
            login.cancel()
            gate.release()
            await login.value
            XCTAssertFalse(fixture.store.authenticated)
            XCTAssertFalse(fixture.store.connected)
            XCTAssertFalse(fixture.store.connecting)
            XCTAssertFalse(fixture.store.localUnlocked)
            XCTAssertTrue(fixture.store.canScanLANLoginCode)
        }
    }

    func testCookieOnlySessionUnlockPreservesClientAndDoesNotRelogin() async throws {
        var localChecks = 0
        let fixture = StoreFixture(totals: ["frame.local": 1], authenticateLocal: { localChecks += 1 })
        defer { fixture.dispose() }
        await fixture.login("frame.local")
        let client = try XCTUnwrap(fixture.store.api)
        let logins = fixture.stub.requests.filter { $0.url?.path == "/api/auth/login" }.count
        fixture.store.sceneChanged(.background)
        XCTAssertTrue(fixture.store.authenticated)
        XCTAssertTrue(fixture.store.api === client)
        fixture.store.sceneChanged(.active)
        await fixture.store.unlock()
        XCTAssertTrue(fixture.store.api === client)
        XCTAssertEqual(fixture.stub.requests.filter { $0.url?.path == "/api/auth/login" }.count, logins)
        XCTAssertEqual(localChecks, 2)
        XCTAssertTrue(fixture.store.canMutate)
        XCTAssertFalse(fixture.store.pairingNeedsCompletion)
        XCTAssertFalse(fixture.store.credentialStored)
        XCTAssertNotNil(fixture.store.credentialStorageError)
    }

    func testLockedSessionRejectsPhotoReadsMutationsRefreshAndEvents() async throws {
        let fixture = StoreFixture(totals: ["frame.local": 1])
        defer { fixture.dispose() }
        await fixture.login("frame.local")
        let photo = try XCTUnwrap(fixture.store.history.first?.photo)
        fixture.store.lock()
        let before = fixture.stub.requests.count
        await fixture.store.refresh()
        await fixture.store.loadMoreHistory()
        await fixture.store.display(previous: false)
        await fixture.store.saveSettings(FrameSettings())
        await fixture.store.checkUpdate()
        await fixture.store.startUpdate()
        await fixture.store.receiveServerEvent(ServerEvent(type: "system_update", payload: ["message": .string("late")]))
        let image = await fixture.store.image(for: photo)
        XCTAssertNil(image)
        do { try await fixture.store.upload(Data(), filename: "blocked.png"); XCTFail("Upload must be denied") }
        catch { }
        XCTAssertEqual(fixture.stub.requests.count, before)
        XCTAssertNil(fixture.store.updateMessage)
        XCTAssertFalse(fixture.store.canMutate)
    }

    func testBackgroundRejectsLateThumbnailAndUploadCompletionsWithoutReplay() async throws {
        let fixture = StoreFixture(totals: ["frame.local": 1])
        defer { fixture.dispose() }
        await fixture.login("frame.local")
        let photo = try XCTUnwrap(fixture.store.history.first?.photo)
        let gate = fixture.stub.hold(host: "frame.local", path: "/api/photos/\(photo.id)")
        let image = Task { await fixture.store.image(for: photo) }
        await fulfillment(of: [gate.started], timeout: 3)
        fixture.store.sceneChanged(.background)
        gate.release()
        let late = await image.value
        XCTAssertNil(late)
        XCTAssertTrue(fixture.store.authenticated)
        XCTAssertFalse(fixture.store.localUnlocked)
    }

    func testBackgroundDropsLateSuccessfulUploadWithoutRefreshingOrReplaying() async throws {
        let fixture = StoreFixture()
        defer { fixture.dispose() }
        await fixture.login("frame.local")
        let photo: [String: Any] = ["id": "new-photo", "sha256": "new-digest", "original_filename": "new.png",
            "mime": "image/png", "width": 800, "height": 480, "size_bytes": 10, "created_at": 1780000000]
        fixture.stub.respondNextJSON(host: "frame.local", path: "/api/queue", method: "POST", status: 201,
            body: ["photo": photo, "queue_entry": ["id": 1, "position": 0, "added_at": 1780000000, "photo": photo], "already_existed": false])
        let gate = fixture.stub.hold(host: "frame.local", path: "/api/queue", method: "POST")
        let upload = Task { try await fixture.store.upload(Data([0]), filename: "new.png") }
        await fulfillment(of: [gate.started], timeout: 3)
        fixture.store.sceneChanged(.background)
        let requests = fixture.stub.requests.count
        gate.release()
        do { try await upload.value; XCTFail("A late completion cannot publish into a locked session") }
        catch { XCTAssertTrue(error is CancellationError) }
        XCTAssertEqual(fixture.stub.requests.count, requests)
        XCTAssertNil(fixture.store.notice)
        XCTAssertTrue(fixture.store.authenticated)
        XCTAssertFalse(fixture.store.localUnlocked)
    }

    func testLockedPhotoCacheCannotReturnAThumbnailAndIsClearedForTheNextUnlock() async throws {
        let fixture = StoreFixture(totals: ["frame.local": 1])
        defer { fixture.dispose() }
        await fixture.login("frame.local")
        let photo = try XCTUnwrap(fixture.store.history.first?.photo)
        let bytes = try XCTUnwrap(Data(base64Encoded: "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aWWQAAAAASUVORK5CYII="))
        fixture.stub.setResponse(host: "frame.local", path: "/api/photos/\(photo.id)", data: bytes)
        let before = fixture.stub.requests.count
        let first = await fixture.store.image(for: photo)
        XCTAssertNotNil(first)
        fixture.store.lock()
        let locked = await fixture.store.image(for: photo)
        XCTAssertNil(locked)
        await fixture.store.unlock()
        let second = await fixture.store.image(for: photo)
        XCTAssertNotNil(second)
        let reads = fixture.stub.requests.dropFirst(before).filter { $0.url?.path == "/api/photos/\(photo.id)" }
        XCTAssertEqual(reads.count, 2, "The next unlock must not reuse an image cached before the lock")
    }

    func testNewPairingSaveFailureBlocksWritesAndRetryOnlySavesWithoutRelogin() async {
        var saves = 0
        let fixture = StoreFixture(saveCredential: { _, _ in
            saves += 1
            if saves == 1 { throw VaultError.unavailable }
        })
        defer { fixture.dispose() }
        fixture.credentials.passwords["http://192.168.1.120:8000"] = "older-protected-password"
        await fixture.store.loginFromLANQRCode(lanQR)
        XCTAssertTrue(fixture.store.authenticated)
        XCTAssertTrue(fixture.store.localUnlocked)
        XCTAssertFalse(fixture.store.credentialStored, "An older item cannot prove the new QR password was saved")
        XCTAssertTrue(fixture.store.pairingNeedsCompletion)
        XCTAssertFalse(fixture.store.canMutate)
        XCTAssertTrue(fixture.store.canRetryCredentialStorage)
        XCTAssertNotNil(fixture.store.credentialStorageError)
        XCTAssertEqual(fixture.credentials.passwords["http://192.168.1.120:8000"], "older-protected-password")
        let requests = fixture.stub.requests.count
        await fixture.store.display(previous: false)
        do { try await fixture.store.upload(Data(), filename: "blocked.png"); XCTFail("Unfinished pairing must block uploads") }
        catch { }
        await fixture.store.retryCredentialStorage()
        XCTAssertEqual(fixture.stub.requests.count, requests)
        XCTAssertEqual(saves, 2)
        XCTAssertTrue(fixture.store.credentialStored)
        XCTAssertTrue(fixture.store.canMutate)
        XCTAssertFalse(fixture.store.pairingNeedsCompletion)
        XCTAssertNil(fixture.store.credentialStorageError)
    }

    func testBackgroundDiscardsFailedPairingSecretAndForbidsStorageRetry() async {
        var saves = 0
        let fixture = StoreFixture(saveCredential: { _, _ in saves += 1; throw VaultError.unavailable })
        defer { fixture.dispose() }
        await fixture.store.loginFromLANQRCode(lanQR)
        fixture.store.sceneChanged(.background)
        fixture.store.sceneChanged(.active)
        await fixture.store.unlock()
        XCTAssertTrue(fixture.store.authenticated)
        XCTAssertTrue(fixture.store.pairingNeedsCompletion)
        XCTAssertFalse(fixture.store.canMutate)
        XCTAssertFalse(fixture.store.canRetryCredentialStorage)
        XCTAssertTrue(fixture.store.canScanLANLoginCode)
        let requests = fixture.stub.requests.count
        await fixture.store.retryCredentialStorage()
        XCTAssertEqual(saves, 1)
        await fixture.store.loginFromLANQRCode(lanQR.replacingOccurrences(of: "192.168.1.120", with: "192.168.1.121"))
        XCTAssertEqual(fixture.stub.requests.count, requests)
        await fixture.store.loginFromLANQRCode(lanQR)
        XCTAssertEqual(saves, 2, "The explicit same-frame QR path can complete an unfinished pairing without an intermediate logout")
    }

    func testColdSavedCredentialLoadFailureStaysLockedAndDoesNotRequestAnotherQR() async {
        let fixture = StoreFixture(loadCredential: { _ in throw VaultError.cancelled })
        defer { fixture.dispose() }
        fixture.defaults.set("http://192.168.1.120:8000", forKey: "frameAddress")
        fixture.store.address = "http://192.168.1.120:8000"
        fixture.credentials.passwords[fixture.store.address] = "protected-password"
        await fixture.store.unlock()
        XCTAssertFalse(fixture.store.localUnlocked)
        XCTAssertFalse(fixture.store.unlocking)
        XCTAssertTrue(fixture.store.credentialStored)
        XCTAssertNotNil(fixture.store.localAuthenticationError)
        XCTAssertTrue(fixture.stub.requests.isEmpty)
    }

    func testConcurrentColdUnlockAndBackgroundCannotPublishLateCredentialRead() async {
        let gate = LocalAuthGate()
        var checks = 0
        let fixture = StoreFixture(authenticateLocal: { checks += 1 }, loadCredential: { _ in
            try await gate.wait()
            return "protected-password"
        })
        defer { fixture.dispose() }
        let address = "http://192.168.1.120:8000"
        fixture.defaults.set(address, forKey: "frameAddress")
        fixture.store.address = address
        fixture.credentials.passwords[address] = "protected-password"
        let unlock = Task { await fixture.store.unlock() }
        await fulfillment(of: [gate.started], timeout: 3)
        XCTAssertTrue(fixture.store.unlocking)
        await fixture.store.unlock()
        XCTAssertEqual(checks, 1)
        XCTAssertTrue(fixture.stub.requests.isEmpty)
        fixture.store.sceneChanged(.background)
        gate.release()
        await unlock.value
        XCTAssertFalse(fixture.store.localUnlocked)
        XCTAssertFalse(fixture.store.authenticated)
        XCTAssertTrue(fixture.stub.requests.isEmpty)
    }

    func testBluetoothMissingOrCancelledCredentialPreservesCurrentPhotoSession() async throws {
        for error in [VaultError.missing, .cancelled] {
            let fixture = StoreFixture(loadCredential: { _ in throw error })
            defer { fixture.dispose() }
            await fixture.login("frame.local")
            let client = try XCTUnwrap(fixture.store.api)
            let address = fixture.store.address
            let identity = try FrameIdentity(id: UUID(), spkiSHA256: Data(repeating: 7, count: 32))
            let endpoint = try XCTUnwrap(URL(string: "https://192.168.1.120:8443"))
            let owner = OwnershipRecord(identity: identity, certificateDER: Data(), ownerID: UUID(),
                claimRequestID: UUID(), ownerToken: Data(repeating: 8, count: 32), endpoints: [endpoint], state: .claimed)
            let requests = fixture.stub.requests.count
            await fixture.store.finishBluetoothSetup(endpoint: endpoint, owner: owner)
            XCTAssertTrue(fixture.store.api === client)
            XCTAssertTrue(fixture.store.authenticated)
            XCTAssertEqual(fixture.store.address, address)
            XCTAssertNil(fixture.defaults.string(forKey: "frameOwnerID"))
            XCTAssertEqual(fixture.stub.requests.count, requests)
            XCTAssertTrue(fixture.store.canMutate)
        }
    }

    func testLogoutRequiresFreshLocalAuthenticationBeforeAnotherQR() async {
        var checks = 0
        let fixture = StoreFixture(authenticateLocal: { checks += 1; if checks > 1 { throw VaultError.cancelled } })
        defer { fixture.dispose() }
        await fixture.store.loginFromLANQRCode(lanQR)
        await fixture.store.logout()
        XCTAssertFalse(fixture.store.localUnlocked)
        let requests = fixture.stub.requests.count
        await fixture.store.loginFromLANQRCode(lanQR)
        XCTAssertEqual(checks, 2)
        XCTAssertFalse(fixture.store.authenticated)
        XCTAssertEqual(fixture.stub.requests.count, requests)
    }

    func testDisplayState503KeepsOtherFrameDataAvailableWithoutClaimingScreenReady() async {
        let fixture = StoreFixture(totals: ["192.168.1.120": 2])
        defer { fixture.dispose() }
        let gate = fixture.stub.hold(host: "192.168.1.120", path: "/api/state")
        let login = Task { await fixture.store.loginFromLANQRCode(lanQR) }
        await fulfillment(of: [gate.started], timeout: 3)
        gate.release(status: 503)
        await login.value
        XCTAssertTrue(fixture.store.authenticated)
        XCTAssertTrue(fixture.store.connected, "An HTTP 503 display response is not loss of network access.")
        XCTAssertEqual(fixture.store.history.count, 2)
        XCTAssertNotNil(fixture.store.settings)
        XCTAssertNil(fixture.store.state)
        XCTAssertNotNil(fixture.store.displayIssue)
        XCTAssertFalse(fixture.store.canDisplay)
        XCTAssertTrue(fixture.store.canMutate, "Queue/settings access is independent of display readiness.")
        let writes = fixture.stub.requests.filter { $0.httpMethod == "POST" }.count
        await fixture.store.display(previous: false)
        XCTAssertEqual(fixture.stub.requests.filter { $0.httpMethod == "POST" }.count, writes)
        await fixture.store.refresh()
        XCTAssertTrue(fixture.store.connected)
        XCTAssertNil(fixture.store.displayIssue)
        XCTAssertTrue(fixture.store.canDisplay, "Legacy diagnostics 404 falls back to a successful state snapshot.")
    }

    func testDisplayDiagnosticsErrorAndBusyBlockScreenCommandsEvenWithState200() async {
        let fixture = StoreFixture()
        defer { fixture.dispose() }
        fixture.stub.setDisplayStatus(state: "error", error: "display_busy_unverified")
        await fixture.store.loginFromLANQRCode(lanQR)
        XCTAssertTrue(fixture.store.connected)
        XCTAssertNotNil(fixture.store.state)
        XCTAssertEqual(fixture.store.displayDiagnostics?.error?.code, "display_busy_unverified")
        XCTAssertNotNil(fixture.store.displayIssue)
        XCTAssertFalse(fixture.store.canDisplay)
        fixture.stub.setDisplayStatus(state: "busy")
        await fixture.store.refresh()
        XCTAssertFalse(fixture.store.canDisplay)
        fixture.stub.setDisplayStatus(state: "ready")
        await fixture.store.refresh()
        XCTAssertTrue(fixture.store.canDisplay)
        XCTAssertNil(fixture.store.displayIssue)
    }

    func testUnconfirmedDisplayPreservesPhotoAndRequiresANewManualCommand() async throws {
        let fixture = StoreFixture(totals: ["192.168.1.120": 2])
        defer { fixture.dispose() }
        let host = "192.168.1.120"
        let photo: [String: Any] = ["id": "pending-photo", "sha256": "pending-digest",
            "original_filename": "retained-photo.png", "mime": "image/png", "width": 800,
            "height": 480, "size_bytes": 68, "created_at": 1780000001]
        let current: [String: Any] = ["id": 1, "displayed_at": 1780000000, "source": "test",
            "photo": ["id": "photo-0", "sha256": "digest-0", "original_filename": "\(host).png",
                "mime": "image/png", "width": 800, "height": 480, "size_bytes": 10,
                "created_at": 1780000000]]
        fixture.stub.setJSONResponse(host: host, path: "/api/state", body: [
            "display": ["model": "ac073-800x480", "width": 800, "height": 480, "colors": 7, "is_mock": false],
            "current": current, "queue_count": 1, "next_change_at": NSNull(),
        ])
        fixture.stub.setJSONResponse(host: host, path: "/api/queue", body: [[
            "id": 9, "position": 0, "added_at": 1780000001, "photo": photo,
        ]])
        let photoBytes = try XCTUnwrap(Data(base64Encoded:
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aWWQAAAAASUVORK5CYII="))
        fixture.stub.setResponse(host: host, path: "/api/photos/pending-photo", data: photoBytes)
        fixture.stub.setDisplayStatus(state: "ready")
        await fixture.store.loginFromLANQRCode(lanQR)
        let api = try XCTUnwrap(fixture.store.api)
        let stateBefore = try XCTUnwrap(fixture.store.state)
        let queueBefore = fixture.store.queue
        let historyBefore = fixture.store.history
        let bytesBefore = try await api.photoData(id: "pending-photo")
        XCTAssertEqual(bytesBefore, photoBytes)
        XCTAssertEqual(queueBefore.count, 1)
        XCTAssertEqual(historyBefore.count, 2)

        // This is the backend wire contract, including fields unknown to iOS v11.
        fixture.stub.setPendingDisplayConfirmation()
        fixture.stub.respondNextJSON(host: host, path: "/api/display/next", method: "POST", status: 503,
                                     body: StoreStub.pendingDisplayFailure)
        await fixture.store.display(previous: false)
        XCTAssertTrue(fixture.store.authenticated)
        XCTAssertTrue(fixture.store.connected, "An unconfirmed refresh is still a reachable frame.")
        XCTAssertEqual(fixture.store.state, stateBefore, "An unconfirmed photo must not replace the confirmed current photo.")
        XCTAssertEqual(fixture.store.queue, queueBefore)
        XCTAssertEqual(fixture.store.history, historyBefore)
        let bytesAfter = try await api.photoData(id: "pending-photo")
        XCTAssertEqual(bytesAfter, bytesBefore, "The retained queued photo remains readable through the app's HTTP client.")
        XCTAssertNotEqual(fixture.store.notice, "Le cadre est à jour.")
        XCTAssertEqual(fixture.store.errorMessage, StoreStub.pendingDisplayDetail)
        XCTAssertEqual(fixture.store.displayDiagnostics?.state, "ready")
        XCTAssertNil(fixture.store.displayDiagnostics?.error)
        XCTAssertTrue(fixture.store.canDisplay, "Ready diagnostics permit another explicit command after the refresh finishes.")
        XCTAssertFalse(fixture.store.displayBusy)
        let displayWrites = {
            fixture.stub.requests.filter { $0.httpMethod == "POST" && $0.url?.path.hasPrefix("/api/display/") == true }
        }
        XCTAssertEqual(displayWrites().map { $0.url!.path }, ["/api/display/next"])

        await fixture.store.refresh()
        await fixture.store.receiveServerEvent(ServerEvent(type: "hello"))
        XCTAssertEqual(displayWrites().count, 1, "Polling and event-stream reconnection must not replay the failed command.")
        XCTAssertTrue(fixture.store.canDisplay)
        XCTAssertNotEqual(fixture.store.notice, "Le cadre est à jour.")

        fixture.stub.respondNextJSON(host: host, path: "/api/display/previous", method: "POST", status: 503,
                                     body: StoreStub.pendingDisplayFailure)
        await fixture.store.display(previous: true)
        XCTAssertEqual(displayWrites().map { $0.url!.path }, ["/api/display/next", "/api/display/previous"],
                       "A second request is allowed only when the user explicitly makes a new command.")
        XCTAssertTrue(fixture.store.connected)
        XCTAssertTrue(fixture.store.canDisplay)
        XCTAssertEqual(fixture.store.state, stateBefore)
        XCTAssertEqual(fixture.store.queue, queueBefore)
        XCTAssertEqual(fixture.store.history, historyBefore)
        XCTAssertNotEqual(fixture.store.notice, "Le cadre est à jour.")
    }

    func testPendingConfirmationNeverOverridesBusyOrFailedDisplayDiagnostics() async {
        let fixture = StoreFixture()
        defer { fixture.dispose() }
        fixture.stub.setPendingDisplayConfirmation()
        await fixture.store.loginFromLANQRCode(lanQR)
        XCTAssertTrue(fixture.store.canDisplay)
        for (state, error) in [("busy", nil), ("error", "display_busy_timeout"), ("error", "display_refresh_failed")] as [(String, String?)] {
            fixture.stub.setPendingDisplayConfirmation(state: state, error: error)
            await fixture.store.refresh()
            XCTAssertTrue(fixture.store.connected)
            XCTAssertNotNil(fixture.store.state)
            XCTAssertNotNil(fixture.store.displayIssue)
            XCTAssertFalse(fixture.store.canDisplay, "Pending confirmation cannot override \(state)/\(error ?? "no error").")
            let requestCount = fixture.stub.requests.count
            await fixture.store.display(previous: false)
            await fixture.store.display(previous: true)
            XCTAssertEqual(fixture.stub.requests.count, requestCount, "Unavailable display commands must not reach the server.")
        }
    }

    func testEventStreamFailureUsesHTTPReachabilityInsteadOfMarkingFrameOffline() async {
        let fixture = StoreFixture()
        defer { fixture.dispose() }
        await fixture.store.loginFromLANQRCode(lanQR)
        await fixture.store.receiveServerEvent(ServerEvent(type: "connection_lost"))
        XCTAssertTrue(fixture.store.connected)
        await fixture.store.receiveServerEvent(ServerEvent(type: "reconnecting"))
        XCTAssertTrue(fixture.store.connected)
        for path in ["/api/state", "/api/queue", "/api/history", "/api/settings", "/api/health", "/api/display/status"] {
            fixture.stub.failNext(host: "192.168.1.120", path: path, error: URLError(.cannotConnectToHost))
        }
        await fixture.store.receiveServerEvent(ServerEvent(type: "connection_lost"))
        XCTAssertFalse(fixture.store.connected, "Actual HTTP transport failure must still show offline.")
    }

    func testLANQRStoresOnlyInProtectedCredentialStoreAndNeverUserDefaults() async throws {
        let fixture = StoreFixture()
        defer { fixture.dispose() }
        await fixture.store.loginFromLANQRCode(lanQR)
        XCTAssertTrue(fixture.store.credentialStored)
        XCTAssertEqual(fixture.credentials.passwords[fixture.store.address], "DemoPass12345678")
        XCTAssertFalse(fixture.defaults.dictionaryRepresentation().description.contains("DemoPass12345678"))
        let request = try XCTUnwrap(fixture.stub.requests.first { $0.url?.path == "/api/auth/login" })
        XCTAssertEqual(request.url?.host, "192.168.1.120")
    }

    func testLANQRDoesNotPersistBeforeAuthenticationAndFailureKeepsItEphemeral() async {
        let fixture = StoreFixture()
        defer { fixture.dispose() }
        let gate = fixture.stub.hold(host: "192.168.1.120", path: "/api/auth/login", method: "POST")
        let login = Task { await fixture.store.loginFromLANQRCode(lanQR) }
        await fulfillment(of: [gate.started], timeout: 3)
        XCTAssertTrue(fixture.store.connecting)
        XCTAssertNil(fixture.defaults.string(forKey: "frameAddress"))
        XCTAssertFalse(fixture.store.authenticated)
        XCTAssertFalse(fixture.store.canScanLANLoginCode)
        let count = fixture.stub.requests.count
        await fixture.store.loginFromLANQRCode(lanQR.replacingOccurrences(of: "192.168.1.120", with: "10.0.0.2"))
        XCTAssertEqual(fixture.stub.requests.count, count)
        XCTAssertEqual(fixture.store.address, "")
        gate.release(status: 401)
        await login.value
        XCTAssertFalse(fixture.store.authenticated)
        XCTAssertFalse(fixture.store.connecting)
        XCTAssertNil(fixture.defaults.string(forKey: "frameAddress"))
        XCTAssertFalse(fixture.defaults.dictionaryRepresentation().description.contains("DemoPass12345678"))
    }

    func testFailedLANQRPreservesSavedFrameAddressAndProtectedCredential() async {
        let fixture = StoreFixture()
        defer { fixture.dispose() }
        let saved = "http://192.168.1.100:8000"
        fixture.defaults.set(saved, forKey: "frameAddress")
        fixture.store.address = saved
        fixture.credentials.passwords[saved] = "previous-credential"
        let gate = fixture.stub.hold(host: "192.168.1.120", path: "/api/auth/login", method: "POST")
        let login = Task { await fixture.store.loginFromLANQRCode(lanQR) }
        await fulfillment(of: [gate.started], timeout: 3)
        gate.release(status: 401)
        await login.value
        XCTAssertFalse(fixture.store.authenticated)
        XCTAssertEqual(fixture.defaults.string(forKey: "frameAddress"), saved)
        XCTAssertEqual(fixture.credentials.passwords[saved], "previous-credential")
        XCTAssertNil(fixture.credentials.passwords["http://192.168.1.120:8000"])
    }

    func testCancelledLANQRPreservesSavedFrameAndCannotOverwriteANewerLogin() async {
        let fixture = StoreFixture()
        defer { fixture.dispose() }
        let saved = "http://192.168.1.100:8000"
        fixture.defaults.set(saved, forKey: "frameAddress")
        fixture.store.address = saved
        let gate = fixture.stub.hold(host: "192.168.1.120", path: "/api/auth/login", method: "POST")
        let login = Task { await fixture.store.loginFromLANQRCode(lanQR) }
        await fulfillment(of: [gate.started], timeout: 3)
        fixture.store.cancelLogin()
        XCTAssertFalse(fixture.store.connecting)
        XCTAssertEqual(fixture.store.address, saved)
        XCTAssertEqual(fixture.defaults.string(forKey: "frameAddress"), saved)
        // A late response from B must not roll a subsequent manual login back.
        await fixture.login("new-frame.local")
        gate.release()
        await login.value
        XCTAssertTrue(fixture.store.authenticated)
        XCTAssertEqual(fixture.store.address, "http://new-frame.local:8000")
        XCTAssertEqual(fixture.defaults.string(forKey: "frameAddress"), fixture.store.address)
    }

    func testSuccessfulLANQRUpdatesOnlyItsOwnProtectedAccount() async throws {
        let fixture = StoreFixture()
        defer { fixture.dispose() }
        let saved = "http://192.168.1.120:8000", other = "http://192.168.1.222:8000"
        fixture.credentials.passwords[saved] = "previous"
        fixture.credentials.passwords[other] = "other-frame-secret"
        await fixture.store.loginFromLANQRCode(lanQR)
        XCTAssertTrue(fixture.store.credentialStored)
        XCTAssertEqual(fixture.credentials.passwords[saved], "DemoPass12345678")
        XCTAssertEqual(fixture.credentials.passwords[other], "other-frame-secret")
    }

    func testLANQRRejectsInvalidInputBeforeChangingAddressOrMakingRequests() async {
        let fixture = StoreFixture()
        defer { fixture.dispose() }
        fixture.store.address = "previous.local"
        await fixture.store.loginFromLANQRCode(lanQR.replacingOccurrences(of: "192.168.1.120", with: "8.8.8.8"))
        XCTAssertEqual(fixture.store.address, "previous.local")
        XCTAssertFalse(fixture.store.authenticated)
        XCTAssertFalse(fixture.store.hasSavedFrame)
        XCTAssertTrue(fixture.stub.requests.isEmpty)
        XCTAssertNotNil(fixture.store.errorMessage)
    }

    func testLANQRNeverReplacesAdoptedTrustOrUsesItsSavedPassword() async {
        let fixture = StoreFixture()
        defer { fixture.dispose() }
        let ownerID = UUID().uuidString.lowercased()
        fixture.defaults.set(ownerID, forKey: "frameOwnerID")
        fixture.defaults.set("https://192.168.1.120:8443", forKey: "frameAddress")
        fixture.store.address = "https://192.168.1.120:8443"
        XCTAssertFalse(fixture.store.canScanLANLoginCode)
        await fixture.store.loginFromLANQRCode(lanQR)
        XCTAssertEqual(fixture.defaults.string(forKey: "frameOwnerID"), ownerID)
        XCTAssertEqual(fixture.defaults.string(forKey: "frameAddress"), "https://192.168.1.120:8443")
        XCTAssertEqual(fixture.store.address, "https://192.168.1.120:8443")
        XCTAssertTrue(fixture.stub.requests.isEmpty)
        XCTAssertEqual(fixture.store.errorMessage, LANLoginCodeError.adoptedFrame.localizedDescription)
    }

    func testLANQRDoesNotInterruptAnExistingSession() async {
        let fixture = StoreFixture()
        defer { fixture.dispose() }
        await fixture.login("frame.local")
        let count = fixture.stub.requests.count
        await fixture.store.loginFromLANQRCode(lanQR)
        XCTAssertEqual(fixture.store.address, "http://frame.local:8000")
        XCTAssertEqual(fixture.stub.requests.count, count)
    }

    func testCancelledRefreshPreservesConnectionAndLoadedState() async throws {
        let fixture = StoreFixture(totals: ["frame.local": 1])
        defer { fixture.dispose() }
        let store = fixture.store
        await fixture.login("frame.local")
        let gate = fixture.stub.hold(host: "frame.local", path: "/api/state")
        let refresh = Task { await store.refresh() }
        await fulfillment(of: [gate.started], timeout: 3)

        refresh.cancel()
        await refresh.value

        XCTAssertTrue(store.authenticated)
        XCTAssertTrue(store.connected, "Cancelling a refresh does not establish that the frame is offline.")
        XCTAssertFalse(store.refreshing)
        XCTAssertEqual(store.state?.display.model, "frame.local")
        XCTAssertEqual(store.history.count, 1)
        XCTAssertNil(store.errorMessage)
    }

    func testRequestedRefreshRunsAfterInFlightRefreshFails() async throws {
        let fixture = StoreFixture()
        defer { fixture.dispose() }
        let store = fixture.store
        await fixture.login("frame.local")
        let before = fixture.stub.requests.filter { $0.url?.path == "/api/state" }.count
        let gate = fixture.stub.hold(host: "frame.local", path: "/api/state")
        let refresh = Task { await store.refresh() }
        await fulfillment(of: [gate.started], timeout: 3)

        // A foreground return or explicit retry arrives before the old failure.
        await store.refresh()
        gate.release(status: 503)
        await refresh.value

        let after = fixture.stub.requests.filter { $0.url?.path == "/api/state" }.count
        XCTAssertEqual(after - before, 2, "The explicitly requested retry must survive the in-flight failure.")
        XCTAssertTrue(store.authenticated)
        XCTAssertTrue(store.connected)
        XCTAssertFalse(store.refreshing)
        XCTAssertNil(store.errorMessage, "A recovered refresh must clear its transient failure message.")
    }

    func testRecoveredRefreshPreservesNewerOperationError() async throws {
        let fixture = StoreFixture()
        defer { fixture.dispose() }
        let store = fixture.store
        await fixture.login("frame.local")
        let updateGate = fixture.stub.hold(host: "frame.local", path: "/api/system/update")
        let update = Task { await store.checkUpdate() }
        await fulfillment(of: [updateGate.started], timeout: 3)
        let refreshGate = fixture.stub.hold(host: "frame.local", path: "/api/state")
        let refresh = Task { await store.refresh() }
        await fulfillment(of: [refreshGate.started], timeout: 3)
        refreshGate.release(status: 503)
        await refresh.value
        XCTAssertTrue(store.connected)
        XCTAssertNotNil(store.displayIssue)

        updateGate.release(status: 422)
        await update.value
        let operationError = try XCTUnwrap(store.errorMessage)
        await store.refresh()

        XCTAssertTrue(store.connected)
        XCTAssertTrue(store.authenticated)
        XCTAssertEqual(store.errorMessage, operationError,
                       "Recovering the connection must not erase a newer operation error.")
    }

    func testRequestedRefreshRunsInNewTaskAfterCancellation() async throws {
        let fixture = StoreFixture()
        defer { fixture.dispose() }
        let store = fixture.store
        await fixture.login("frame.local")
        fixture.enterForegroundWithoutMonitoring()
        let before = fixture.stub.requests.filter { $0.url?.path == "/api/state" }.count
        let cancelledGate = fixture.stub.hold(host: "frame.local", path: "/api/state")
        let refresh = Task { await store.refresh() }
        await fulfillment(of: [cancelledGate.started], timeout: 3)
        await store.refresh()
        let retryGate = fixture.stub.hold(host: "frame.local", path: "/api/state")

        refresh.cancel()
        await refresh.value
        await fulfillment(of: [retryGate.started], timeout: 3)
        XCTAssertTrue(store.refreshing)
        let finished = expectation(description: "Pending refresh completed")
        let observation = store.$refreshing.dropFirst().filter { !$0 }.sink { _ in finished.fulfill() }
        defer { observation.cancel() }
        retryGate.release()
        await fulfillment(of: [finished], timeout: 3)

        let after = fixture.stub.requests.filter { $0.url?.path == "/api/state" }.count
        XCTAssertEqual(after - before, 2, "Cancellation must hand the requested refresh to a non-cancelled task exactly once.")
        XCTAssertFalse(store.refreshing)
        XCTAssertTrue(store.connected)
        XCTAssertTrue(store.authenticated)
        XCTAssertNil(store.errorMessage)
    }

    func testCancelledRefreshDoesNotRetryAfterEnteringBackground() async throws {
        let fixture = StoreFixture()
        defer { fixture.dispose() }
        let store = fixture.store
        await fixture.login("frame.local")
        fixture.enterForegroundWithoutMonitoring()
        let cancelledGate = fixture.stub.hold(host: "frame.local", path: "/api/state")
        let refresh = Task { await store.refresh() }
        await fulfillment(of: [cancelledGate.started], timeout: 3)
        await store.refresh()
        let unexpectedRetry = fixture.stub.hold(host: "frame.local", path: "/api/state")
        unexpectedRetry.started.isInverted = true

        store.sceneChanged(.background)
        refresh.cancel()
        await refresh.value
        await fulfillment(of: [unexpectedRetry.started], timeout: 0.2)

        XCTAssertFalse(store.refreshing)
        XCTAssertTrue(store.authenticated)
        XCTAssertTrue(store.connected)
        XCTAssertNil(store.errorMessage)
    }

    func testCancelledOldRefreshCannotRetryInNewSession() async throws {
        let fixture = StoreFixture()
        defer { fixture.dispose() }
        let store = fixture.store
        await fixture.login("old-frame.local")
        fixture.enterForegroundWithoutMonitoring()
        let cancelledGate = fixture.stub.hold(host: "old-frame.local", path: "/api/state")
        let refresh = Task { await store.refresh() }
        await fulfillment(of: [cancelledGate.started], timeout: 3)
        await store.refresh()

        await fixture.login("new-frame.local")
        fixture.enterForegroundWithoutMonitoring()
        let unexpectedRetry = fixture.stub.hold(host: "new-frame.local", path: "/api/state")
        unexpectedRetry.started.isInverted = true
        refresh.cancel()
        await refresh.value
        await fulfillment(of: [unexpectedRetry.started], timeout: 0.2)

        XCTAssertEqual(store.state?.display.model, "new-frame.local")
        XCTAssertEqual(fixture.stub.requests.filter {
            $0.url?.host == "old-frame.local" && $0.url?.path == "/api/state"
        }.count, 2, "Only the login snapshot and the cancelled refresh may use the old frame.")
        XCTAssertFalse(store.refreshing)
        XCTAssertTrue(store.authenticated)
        XCTAssertTrue(store.connected)
        XCTAssertNil(store.errorMessage)
    }

    func testForegroundAndPhotoReadsWaitForPasswordRotation() async throws {
        let fixture = StoreFixture(totals: ["frame.local": 101])
        defer { fixture.dispose() }
        let store = fixture.store
        await fixture.login("frame.local")
        let photo = try XCTUnwrap(store.history.first?.photo)
        let gate = fixture.stub.hold(host: "frame.local", path: "/api/auth/password", method: "POST")
        let changing = Task { await store.changePassword(current: "previous-test-password", new: "new-test-password") }
        await fulfillment(of: [gate.started], timeout: 3)
        let before = fixture.stub.requests.count
        store.sceneActive(true)
        await store.refresh()
        await store.loadMoreHistory()
        _ = await store.image(for: photo)
        await Task.yield()
        XCTAssertEqual(fixture.stub.requests.count, before, "Foreground refreshes must not use the old cookie during rotation.")
        gate.release()
        guard case .success = await changing.value else { return XCTFail("Expected successful rotation") }
        XCTAssertTrue(store.authenticated)
        XCTAssertTrue(store.connected)
        await store.refresh()
        XCTAssertGreaterThan(fixture.stub.requests.count, before)
    }

    func testPasswordRotationKeepsSessionAndRejectsOldRefresh() async throws {
        let fixture = StoreFixture()
        defer { fixture.dispose() }
        let store = fixture.store
        await fixture.login("frame.local")
        XCTAssertTrue(store.passwordChangeSupported)
        let gate = fixture.stub.hold(host: "frame.local", path: "/api/state")
        let refresh = Task { await store.refresh() }
        await fulfillment(of: [gate.started], timeout: 3)
        let result = await store.changePassword(current: "previous-test-password", new: "new-test-password")
        guard case .success = result else { return XCTFail("Expected successful rotation") }
        gate.release(status: 401)
        await refresh.value
        XCTAssertTrue(store.authenticated, "A refresh sent before rotation must not revoke the new session.")
        XCTAssertTrue(store.connected)
        XCTAssertFalse(store.busy)
        XCTAssertNil(store.errorMessage)
        XCTAssertEqual(fixture.stub.requests.filter { $0.url?.path == "/api/auth/password" }.count, 1)
    }

    func testWrongCurrentPasswordDoesNotSignOut() async throws {
        let fixture = StoreFixture()
        defer { fixture.dispose() }
        await fixture.login("frame.local")
        let gate = fixture.stub.hold(host: "frame.local", path: "/api/auth/password", method: "POST")
        let changing = Task { await fixture.store.changePassword(current: "wrong", new: "new-test-password") }
        await fulfillment(of: [gate.started], timeout: 3)
        gate.release(status: 403)
        guard case .failure = await changing.value else { return XCTFail("Expected rejection") }
        XCTAssertTrue(fixture.store.authenticated)
        XCTAssertTrue(fixture.store.connected)
        XCTAssertFalse(fixture.store.busy)
    }

    func testUnconfirmedPasswordRotationRequiresExplicitReconnect() async throws {
        let fixture = StoreFixture()
        defer { fixture.dispose() }
        await fixture.login("frame.local")
        await fixture.store.login(password: "synthetic-test-password", rememberBiometric: true)
        let gate = fixture.stub.hold(host: "frame.local", path: "/api/auth/password", method: "POST")
        let changing = Task { await fixture.store.changePassword(current: "previous-test-password", new: "new-test-password") }
        await fulfillment(of: [gate.started], timeout: 3)
        gate.release(status: 502)
        guard case .failure(let message) = await changing.value else { return XCTFail("Expected uncertain result") }
        XCTAssertTrue(message.contains("nouveau mot de passe"))
        XCTAssertFalse(fixture.store.authenticated)
        XCTAssertFalse(fixture.store.credentialStored)
        XCTAssertEqual(fixture.stub.requests.filter { $0.url?.path == "/api/auth/password" }.count, 1)
    }

    func testLegacyFrameDoesNotOfferOrSendPasswordRotation() async throws {
        let fixture = StoreFixture()
        defer { fixture.dispose() }
        await fixture.login("legacy-frame.local")
        XCTAssertFalse(fixture.store.passwordChangeSupported)
        guard case .failure = await fixture.store.changePassword(current: "old", new: "new-test-password") else { return XCTFail("Expected unsupported operation") }
        XCTAssertFalse(fixture.stub.requests.contains { $0.url?.path == "/api/auth/password" })
    }

    func testSyntheticReconnectCannotDisableOrEraseAnExistingProtectedCredential() async {
        let fixture = StoreFixture()
        defer { fixture.dispose() }
        fixture.credentials.passwords["http://saved-frame.local:8000"] = "saved-secret"
        await fixture.login("saved-frame.local")
        await fixture.store.login(password: "synthetic-test-password", rememberBiometric: false)
        XCTAssertTrue(fixture.store.authenticated)
        XCTAssertTrue(fixture.store.credentialStored)
        XCTAssertEqual(fixture.credentials.passwords["http://saved-frame.local:8000"], "saved-secret")
    }

    func testCancelledLoginCannotRestoreSessionAfterNewConnection() async throws {
        let fixture = StoreFixture()
        defer { fixture.dispose() }
        let store = fixture.store
        store.address = "old-frame.local"
        let gate = fixture.stub.hold(host: "old-frame.local", path: "/api/auth/status")
        let login = Task { await store.login(password: "synthetic-test-password") }
        await fulfillment(of: [gate.started], timeout: 3)
        store.cancelLogin()
        XCTAssertFalse(store.connecting)
        XCTAssertFalse(store.authenticated)
        XCTAssertNil(store.api)
        XCTAssertFalse(store.hasSavedFrame)
        await fixture.login("new-frame.local")
        gate.release()
        await login.value
        XCTAssertTrue(store.authenticated)
        XCTAssertEqual(store.address, "http://new-frame.local:8000")
        XCTAssertNil(store.errorMessage)
    }

    func testForgetIsLocalAndDelayedLogoutCannotEraseNewConnection() async throws {
        let fixture = StoreFixture()
        defer { fixture.dispose() }
        let store = fixture.store
        await fixture.login("old-frame.local")
        store.availableUpdate = UpdateStatus(current: "0.4.2", latest: "0.4.3", updateAvailable: true)
        store.busy = true
        store.displayBusy = true
        store.loadingHistory = true
        let gate = fixture.stub.hold(host: "old-frame.local", path: "/api/auth/logout")
        let logout = Task { await store.logout(forget: true) }
        await fulfillment(of: [gate.started], timeout: 3)
        XCTAssertFalse(store.hasSavedFrame)
        XCTAssertEqual(store.address, "")
        XCTAssertNil(store.api)
        XCTAssertNil(store.state)
        XCTAssertNil(store.availableUpdate)
        XCTAssertFalse(store.busy)
        XCTAssertFalse(store.displayBusy)
        XCTAssertFalse(store.loadingHistory)
        await fixture.login("new-frame.local")
        gate.release()
        await logout.value
        XCTAssertTrue(store.authenticated)
        XCTAssertTrue(store.hasSavedFrame)
        XCTAssertEqual(store.address, "http://new-frame.local:8000")
        XCTAssertEqual(store.state?.display.model, "new-frame.local")
    }

    func testOldHistoryPageCannotAppendToNewFrame() async throws {
        let fixture = StoreFixture(totals: ["old-frame.local": 200, "new-frame.local": 1])
        defer { fixture.dispose() }
        let store = fixture.store
        await fixture.login("old-frame.local")
        let history = fixture.stub.hold(host: "old-frame.local", path: "/api/history")
        let loading = Task { await store.loadMoreHistory() }
        await fulfillment(of: [history.started], timeout: 3)
        let logoutGate = fixture.stub.hold(host: "old-frame.local", path: "/api/auth/logout")
        let logout = Task { await store.logout() }
        await fulfillment(of: [logoutGate.started], timeout: 3)
        await fixture.login("new-frame.local")
        history.release()
        await loading.value
        XCTAssertEqual(store.history.count, 1)
        XCTAssertEqual(store.history.first?.photo.originalFilename, "new-frame.local.png")
        XCTAssertFalse(store.loadingHistory)
        XCTAssertTrue(store.authenticated)
        logoutGate.release()
        await logout.value
    }

    func testUnauthorizedOldThumbnailCannotSignOutNewFrame() async throws {
        let fixture = StoreFixture(totals: ["old-frame.local": 1])
        defer { fixture.dispose() }
        let store = fixture.store
        await fixture.login("old-frame.local")
        let photo = try XCTUnwrap(store.history.first?.photo)
        let imageGate = fixture.stub.hold(host: "old-frame.local", path: "/api/photos/\(photo.id)")
        let image = Task { await store.image(for: photo) }
        await fulfillment(of: [imageGate.started], timeout: 3)
        let logoutGate = fixture.stub.hold(host: "old-frame.local", path: "/api/auth/logout")
        let logout = Task { await store.logout() }
        await fulfillment(of: [logoutGate.started], timeout: 3)
        await fixture.login("new-frame.local")
        imageGate.release(status: 401)
        _ = await image.value
        XCTAssertTrue(store.authenticated)
        XCTAssertTrue(store.connected)
        XCTAssertNil(store.errorMessage)
        logoutGate.release()
        await logout.value
    }

    func testOldOperationCannotClearNewBusyFlagOrPublishOldUpdate() async throws {
        let fixture = StoreFixture()
        defer { fixture.dispose() }
        let store = fixture.store
        await fixture.login("old-frame.local")
        let oldUpdate = fixture.stub.hold(host: "old-frame.local", path: "/api/system/update")
        let updateTask = Task { await store.checkUpdate() }
        await fulfillment(of: [oldUpdate.started], timeout: 3)
        let logoutGate = fixture.stub.hold(host: "old-frame.local", path: "/api/auth/logout")
        let logout = Task { await store.logout() }
        await fulfillment(of: [logoutGate.started], timeout: 3)
        await fixture.login("new-frame.local")
        let newSettings = fixture.stub.hold(host: "new-frame.local", path: "/api/settings", method: "POST")
        let settingsTask = Task { await store.saveSettings(FrameSettings()) }
        await fulfillment(of: [newSettings.started], timeout: 3)
        oldUpdate.release()
        await updateTask.value
        XCTAssertTrue(store.busy)
        XCTAssertNil(store.availableUpdate)
        newSettings.release()
        await settingsTask.value
        XCTAssertFalse(store.busy)
        logoutGate.release()
        await logout.value
    }

    func testOldRefreshCannotBlockOrOverwriteNewFrameRefresh() async throws {
        let fixture = StoreFixture()
        defer { fixture.dispose() }
        let store = fixture.store
        await fixture.login("old-frame.local")
        let stateGate = fixture.stub.hold(host: "old-frame.local", path: "/api/state")
        let refresh = Task { await store.refresh() }
        await fulfillment(of: [stateGate.started], timeout: 3)
        let logoutGate = fixture.stub.hold(host: "old-frame.local", path: "/api/auth/logout")
        let logout = Task { await store.logout() }
        await fulfillment(of: [logoutGate.started], timeout: 3)
        await fixture.login("new-frame.local")
        XCTAssertEqual(store.state?.display.model, "new-frame.local")
        XCTAssertFalse(store.refreshing)
        stateGate.release()
        await refresh.value
        XCTAssertEqual(store.state?.display.model, "new-frame.local")
        XCTAssertFalse(store.refreshing)
        logoutGate.release()
        await logout.value
    }

    func testRefreshPreservesMoreThanFiveHundredLoadedHistoryRowsUsingBoundedPages() async throws {
        let fixture = StoreFixture(totals: ["large-frame.local": 650])
        defer { fixture.dispose() }
        let store = fixture.store
        await fixture.login("large-frame.local")
        for _ in 0..<6 { await store.loadMoreHistory() }
        XCTAssertEqual(store.history.count, 650)
        XCTAssertFalse(store.hasMoreHistory)
        await store.refresh()
        XCTAssertEqual(store.history.count, 650)
        XCTAssertEqual(Set(store.history.map(\.id)).count, 650)
        XCTAssertFalse(store.hasMoreHistory)
        XCTAssertNil(store.errorMessage)
        let limits = fixture.stub.requests.filter { $0.url?.path == "/api/history" }.compactMap {
            URLComponents(url: $0.url!, resolvingAgainstBaseURL: false)?.queryItems?.first { $0.name == "limit" }?.value
        }.compactMap(Int.init)
        XCTAssertFalse(limits.isEmpty)
        XCTAssertTrue(limits.allSatisfy { $0 > 0 && $0 <= 500 })
    }

    func testHistoryPageStartedBeforeRefreshCannotCorruptRefreshedList() async throws {
        let fixture = StoreFixture(totals: ["frame.local": 250])
        defer { fixture.dispose() }
        let store = fixture.store
        await fixture.login("frame.local")
        let gate = fixture.stub.hold(host: "frame.local", path: "/api/history")
        let pagination = Task { await store.loadMoreHistory() }
        await fulfillment(of: [gate.started], timeout: 3)
        await store.refresh()
        gate.release()
        await pagination.value
        XCTAssertEqual(store.history.count, 100)
        XCTAssertTrue(store.hasMoreHistory)
        XCTAssertFalse(store.loadingHistory)
    }
    private func invitationIdentity() throws -> FrameIdentity {
        try FrameIdentity(id: UUID(uuidString: "11111111-2222-4333-8444-555555555555")!, spkiSHA256: Data(repeating: 0x19, count: 32))
    }
    private func invitationCode(id: UUID = UUID()) throws -> FrameInvitationCode {
        try FrameInvitationCode(identity: invitationIdentity(), endpoint: URL(string: "https://invited-frame.local:8443")!,
                                invitationID: id, invitationToken: String(repeating: "3", count: 64))
    }
    private func requestJSON(_ request: URLRequest) throws -> [String: Any] {
        try XCTUnwrap(try JSONSerialization.jsonObject(with: XCTUnwrap(request.httpBody)) as? [String: Any])
    }

    func testQueuedConnectionWaitsForFinalDismissalAndIsConsumedOnce() async throws {
        for isPhoto in [false, true] {
            var localChecks = 0
            let fixture = StoreFixture(authenticateLocal: { localChecks += 1 })
            defer { fixture.dispose() }
            let code = try invitationCode()
            fixture.stub.enablePhotoAccess(code.identity)
            let host = isPhoto ? "invited-frame.local" : "192.168.1.120"
            let path = isPhoto ? "/api/auth/invitations/claim" : "/api/auth/login"
            let gate = fixture.stub.hold(host: host, path: path, method: "POST")
            if isPhoto {
                fixture.store.errorMessage = "Synthetic previous scanner error"
                fixture.store.queuePhotoInvitation(code)
                XCTAssertNil(fixture.store.errorMessage)
            } else { fixture.store.queueLANLoginCode(lanQR) }
            // Activation alone cannot release a scan while its sheets remain presented.
            fixture.store.sceneChanged(.inactive)
            fixture.store.sceneChanged(.active)
            for _ in 0..<8 { await Task.yield() }
            XCTAssertEqual(localChecks, 0)
            XCTAssertTrue(fixture.stub.requests.isEmpty)
            XCTAssertTrue(fixture.photoCredentials.passwords.isEmpty)
            XCTAssertTrue(fixture.credentials.passwords.isEmpty)
            // Dismissal while inactive also waits; duplicate callbacks must not replay it.
            fixture.store.sceneChanged(.inactive)
            fixture.store.completeQueuedConnection()
            fixture.store.completeQueuedConnection()
            for _ in 0..<8 { await Task.yield() }
            XCTAssertEqual(localChecks, 0)
            XCTAssertTrue(fixture.stub.requests.isEmpty)
            fixture.store.sceneChanged(.active)
            await fulfillment(of: [gate.started], timeout: 3)
            XCTAssertEqual(localChecks, 1)
            fixture.store.completeQueuedConnection()
            fixture.store.sceneChanged(.active)
            XCTAssertEqual(fixture.stub.requests.filter { $0.url?.path == path }.count, 1)
            let committed = expectation(description: "Queued connection committed")
            let subscription = fixture.store.$authenticated.filter { $0 }.sink { _ in committed.fulfill() }
            defer { subscription.cancel() }
            gate.release()
            await fulfillment(of: [committed], timeout: 3)
            fixture.store.completeQueuedConnection()
            for _ in 0..<8 { await Task.yield() }
            XCTAssertEqual(localChecks, 1)
            XCTAssertEqual(fixture.stub.requests.filter { $0.url?.path == path }.count, 1)
        }
    }

    func testQueuedInvitationBackgroundPurgesBeforeAuthentication() async throws {
        for dismissalComplete in [false, true] {
            var localChecks = 0
            let fixture = StoreFixture(authenticateLocal: { localChecks += 1 })
            defer { fixture.dispose() }
            let code = try invitationCode()
            fixture.stub.enablePhotoAccess(code.identity)
            fixture.store.sceneChanged(.inactive)
            fixture.store.queuePhotoInvitation(code)
            if dismissalComplete { fixture.store.completeQueuedConnection() }
            fixture.store.sceneChanged(.background)
            fixture.store.sceneChanged(.active)
            fixture.store.completeQueuedConnection()
            for _ in 0..<8 { await Task.yield() }
            XCTAssertEqual(localChecks, 0)
            XCTAssertTrue(fixture.stub.requests.isEmpty)
            XCTAssertTrue(fixture.photoCredentials.passwords.isEmpty)
            XCTAssertNil(fixture.defaults.data(forKey: "photoAccessPending"))
            XCTAssertFalse(fixture.store.authenticated)
        }
    }

    func testQueuedInvitationKeepsPreviousAccessUntilVerifiedCommit() async throws {
        let fixture = StoreFixture()
        defer { fixture.dispose() }
        await fixture.login("old-frame.local")
        let previous = try XCTUnwrap(fixture.store.api)
        let oldAddress = fixture.store.address
        try fixture.seedStoredPassword(account: oldAddress)
        let oldCredentials = fixture.credentials.passwords
        let code = try invitationCode()
        fixture.stub.enablePhotoAccess(code.identity)
        let gate = fixture.stub.hold(host: "invited-frame.local", path: "/api/auth/invitations/claim", method: "POST")
        fixture.store.queuePhotoInvitation(code)
        fixture.store.completeQueuedConnection()
        await fulfillment(of: [gate.started], timeout: 3)
        XCTAssertTrue(fixture.store.api === previous)
        XCTAssertTrue(fixture.store.authenticated)
        XCTAssertEqual(fixture.store.address, oldAddress)
        XCTAssertEqual(fixture.credentials.passwords, oldCredentials)
        XCTAssertNil(fixture.defaults.data(forKey: "photoAccessSelection"))
        // A rejected candidate also leaves the selected connection intact.
        let rejected = expectation(description: "Queued invitation rejected")
        let subscription = fixture.store.$photoAccessError.compactMap { $0 }.sink { _ in rejected.fulfill() }
        defer { subscription.cancel() }
        gate.release(status: 401)
        await fulfillment(of: [rejected], timeout: 3)
        XCTAssertTrue(fixture.store.api === previous)
        XCTAssertTrue(fixture.store.authenticated)
        XCTAssertEqual(fixture.store.address, oldAddress)
        XCTAssertEqual(fixture.credentials.passwords, oldCredentials)
        XCTAssertNil(fixture.defaults.data(forKey: "photoAccessSelection"))
    }

    func testInvitationClaimPersistsDeviceBeforePOSTAndPreservesOldClientUntilCommit() async throws {
        let fixture = StoreFixture()
        defer { fixture.dispose() }
        await fixture.login("old-frame.local")
        let previous = try XCTUnwrap(fixture.store.api)
        let code = try invitationCode()
        fixture.stub.enablePhotoAccess(code.identity)
        let gate = fixture.stub.hold(host: "invited-frame.local", path: "/api/auth/invitations/claim", method: "POST")
        let claim = Task { await fixture.store.claimInvitation(code) }
        await fulfillment(of: [gate.started], timeout: 3)
        let request = try XCTUnwrap(fixture.stub.requests.last { $0.url?.path == "/api/auth/invitations/claim" })
        let fields = try requestJSON(request)
        let savedText = try XCTUnwrap(fixture.photoCredentials.passwords.values.first)
        let saved = try JSONDecoder().decode(PhotoAccessCredential.self, from: Data(savedText.utf8))
        XCTAssertEqual(fields["device_id"] as? String, saved.deviceID.uuidString.lowercased())
        XCTAssertEqual(fields["device_token"] as? String, saved.deviceToken)
        XCTAssertEqual(saved.state, .pending)
        XCTAssertFalse(savedText.contains(code.invitationToken), "Recipient invitation token is RAM-only")
        XCTAssertTrue(fixture.store.api === previous)
        XCTAssertEqual(fixture.defaults.string(forKey: "frameAddress"), "http://old-frame.local:8000")
        XCTAssertFalse(fixture.store.canMutate)
        gate.release(); await claim.value
        XCTAssertEqual(fixture.store.photoAccessRole, .media)
        XCTAssertEqual(fixture.store.address, code.endpoint.absoluteString)
        XCTAssertFalse(fixture.store.hasAdoptedFrame)
        XCTAssertFalse(fixture.store.canAdminister)
        XCTAssertTrue(fixture.store.canMutate)
    }

    func testInvitationStorageFailureSendsNoCredentialAndKeepsOldAccess() async throws {
        let fixture = StoreFixture(savePhotoValue: { _, _ in throw VaultError.unavailable })
        defer { fixture.dispose() }
        await fixture.login("old-frame.local")
        let previous = fixture.store.api
        let code = try invitationCode()
        fixture.stub.enablePhotoAccess(code.identity)
        await fixture.store.claimInvitation(code)
        XCTAssertTrue(fixture.store.api === previous)
        XCTAssertTrue(fixture.store.authenticated)
        XCTAssertNil(fixture.defaults.data(forKey: "photoAccessSelection"))
        XCTAssertFalse(fixture.stub.requests.contains { $0.url?.path == "/api/auth/invitations/claim" })
        XCTAssertNotNil(fixture.store.photoAccessError)
    }

    func testRejectedInvitationCannotSignOutExistingIndividualAccess() async throws {
        let fixture = StoreFixture()
        defer { fixture.dispose() }
        let first = try invitationCode()
        fixture.stub.enablePhotoAccess(first.identity)
        await fixture.store.claimInvitation(first)
        XCTAssertEqual(fixture.store.photoAccessRole, .media)
        let oldClient = fixture.store.api
        let selected = fixture.defaults.data(forKey: "photoAccessSelection")
        let before = fixture.stub.requests.count
        fixture.stub.respondNextJSON(host: "invited-frame.local", path: "/api/auth/invitations/claim", method: "POST", status: 401, body: ["detail": "Expired invitation"])
        await fixture.store.claimInvitation(try invitationCode())
        XCTAssertTrue(fixture.store.api === oldClient)
        XCTAssertTrue(fixture.store.authenticated)
        XCTAssertEqual(fixture.store.photoAccessRole, .media)
        XCTAssertEqual(fixture.defaults.data(forKey: "photoAccessSelection"), selected)
        XCTAssertFalse(fixture.stub.requests.dropFirst(before).contains { $0.url?.path == "/api/auth/login" })
    }

    func testCancelInvitationAndLateReplyKeepOldConnection() async throws {
        let fixture = StoreFixture()
        defer { fixture.dispose() }
        await fixture.login("old-frame.local")
        let previous = fixture.store.api
        let code = try invitationCode()
        fixture.stub.enablePhotoAccess(code.identity)
        let gate = fixture.stub.hold(host: "invited-frame.local", path: "/api/auth/invitations/claim", method: "POST")
        let claim = Task { await fixture.store.claimInvitation(code) }
        await fulfillment(of: [gate.started], timeout: 3)
        fixture.store.cancelLogin()
        gate.release(); await claim.value
        XCTAssertTrue(fixture.store.api === previous)
        XCTAssertTrue(fixture.store.authenticated)
        XCTAssertFalse(fixture.store.localUnlocked)
        XCTAssertFalse(fixture.store.connecting)
        XCTAssertNil(fixture.defaults.data(forKey: "photoAccessSelection"))
        XCTAssertEqual(fixture.store.address, "http://old-frame.local:8000")
    }

    func testInvitationRetryUsesPersistedDeviceAndRequestIDs() async throws {
        let fixture = StoreFixture()
        defer { fixture.dispose() }
        let code = try invitationCode()
        fixture.stub.enablePhotoAccess(code.identity)
        fixture.stub.respondNextJSON(host: "invited-frame.local", path: "/api/auth/invitations/claim", method: "POST", status: 503, body: ["detail": "Uncertain synthetic response"])
        await fixture.store.claimInvitation(code)
        let first = try requestJSON(XCTUnwrap(fixture.stub.requests.last { $0.url?.path == "/api/auth/invitations/claim" }))
        await fixture.store.claimInvitation(code)
        let second = try requestJSON(XCTUnwrap(fixture.stub.requests.last { $0.url?.path == "/api/auth/invitations/claim" }))
        for key in ["device_id", "device_token", "request_id", "invitation_id", "invitation_token"] {
            XCTAssertEqual(first[key] as? String, second[key] as? String)
        }
        XCTAssertEqual(fixture.store.photoAccessRole, .media)
    }

    func testMediaSettingsSendScheduleOnlyAndAdminEntryPointsSendNothing() async throws {
        let fixture = StoreFixture()
        defer { fixture.dispose() }
        let code = try invitationCode()
        fixture.stub.enablePhotoAccess(code.identity)
        await fixture.store.claimInvitation(code)
        await fixture.store.saveSettings(FrameSettings(changeMode: .interval, changeHour: 6, changeIntervalMinutes: 90, saturation: 2))
        let settings = try requestJSON(XCTUnwrap(fixture.stub.requests.last { $0.url?.path == "/api/settings" && $0.httpMethod == "POST" }))
        XCTAssertEqual(Set(settings.keys), ["change_mode", "change_hour", "change_interval_minutes"])
        let before = fixture.stub.requests.count
        await fixture.store.createInvitation()
        await fixture.store.refreshAccessDevices()
        await fixture.store.checkUpdate()
        await fixture.store.startUpdate()
        do { try await fixture.store.beginBluetoothAdoption(); XCTFail("Media cannot administer Wi-Fi") } catch {}
        XCTAssertEqual(fixture.stub.requests.count, before)
        XCTAssertTrue(fixture.store.canMutate)
    }

    func testColdPhotoRestoreUsesDeviceSessionAnd401NeverFallsBackToLegacy() async throws {
        let fixture = StoreFixture()
        defer { fixture.dispose() }
        let code = try invitationCode()
        fixture.stub.enablePhotoAccess(code.identity)
        await fixture.store.claimInvitation(code)
        await fixture.store.logout()
        fixture.stub.respondNextJSON(host: "invited-frame.local", path: "/api/auth/device-session", method: "POST", status: 401, body: ["detail": "Revoked"])
        let before = fixture.stub.requests.count
        await fixture.store.unlock()
        let requests = Array(fixture.stub.requests.dropFirst(before))
        XCTAssertEqual(requests.map { $0.url!.path }, ["/api/auth/device-session"])
        XCTAssertEqual(fixture.store.photoAccessRole, .media)
        XCTAssertFalse(fixture.store.localUnlocked)
        XCTAssertFalse(fixture.store.authenticated)
        XCTAssertNotNil(fixture.store.localAuthenticationError)
        XCTAssertTrue(fixture.store.credentialStored)
    }

    func testOwnerEnrollmentRequiresPinnedHTTPSAndDurableCredential() async throws {
        let fixture = StoreFixture()
        defer { fixture.dispose() }
        await fixture.login("old-frame.local")
        XCTAssertFalse(fixture.store.canShareAccess)
        let before = fixture.stub.requests.count
        await fixture.store.enrollPhotoAccess()
        await fixture.store.createInvitation()
        XCTAssertEqual(fixture.stub.requests.count, before)
        XCTAssertTrue(fixture.photoCredentials.passwords.isEmpty)
    }

    func testOwnerEnrollmentAndInvitationDraftAreProtectedBeforeCreateAndBackgroundCannotPublishQR() async throws {
        let identity = try invitationIdentity()
        let fixture = StoreFixture(pin: identity)
        defer { fixture.dispose() }
        fixture.stub.enablePhotoAccess(identity)
        await fixture.login("https://owner-frame.local:8443")
        let gate = fixture.stub.hold(host: "owner-frame.local", path: "/api/auth/invitations", method: "POST")
        let creation = Task { await fixture.store.createInvitation() }
        await fulfillment(of: [gate.started], timeout: 3)
        XCTAssertEqual(fixture.store.photoAccessRole, .owner)
        let draftText = try XCTUnwrap(fixture.photoCredentials.passwords.first { $0.key.hasPrefix("invitation:") }?.value)
        let draft = try JSONDecoder().decode(PhotoInvitationDraft.self, from: Data(draftText.utf8))
        let body = try requestJSON(XCTUnwrap(fixture.stub.requests.last { $0.url?.path == "/api/auth/invitations" }))
        XCTAssertEqual(body["invitation_token"] as? String, draft.invitationToken)
        XCTAssertEqual(body["request_id"] as? String, draft.requestID.uuidString.lowercased())
        XCTAssertFalse(String(describing: fixture.defaults.dictionaryRepresentation()).contains(draft.invitationToken))
        fixture.store.sceneChanged(.background)
        gate.release(); await creation.value
        XCTAssertNil(fixture.store.activeInvitation)
        XCTAssertFalse(fixture.store.photoAccessBusy)
        XCTAssertTrue(fixture.store.authenticated)
    }

    func testOwnerInvitationLockPurgesPublishedQRAndReopenRetriesSameDraft() async throws {
        let identity = try invitationIdentity()
        let fixture = StoreFixture(pin: identity)
        defer { fixture.dispose() }
        fixture.stub.enablePhotoAccess(identity)
        await fixture.login("https://owner-frame.local:8443")
        await fixture.store.createInvitation()
        let invitation = try XCTUnwrap(fixture.store.activeInvitation)
        fixture.store.lock()
        XCTAssertNil(fixture.store.activeInvitation)
        await fixture.store.unlock()
        await fixture.store.createInvitation()
        XCTAssertEqual(fixture.store.activeInvitation?.invitationID, invitation.invitationID)
        XCTAssertEqual(fixture.store.activeInvitation?.code.invitationToken, invitation.code.invitationToken)
    }

    func testForgetIndividualAccessDeletesOnlySelectedProtectedCredential() async throws {
        let fixture = StoreFixture()
        defer { fixture.dispose() }
        let code = try invitationCode()
        fixture.stub.enablePhotoAccess(code.identity)
        await fixture.store.claimInvitation(code)
        let selected = try JSONDecoder().decode(PhotoAccessSelection.self, from: XCTUnwrap(fixture.defaults.data(forKey: "photoAccessSelection")))
        fixture.photoCredentials.passwords["photo:unrelated:owner"] = "unrelated protected value"
        await fixture.store.logout(forget: true)
        XCTAssertNil(fixture.photoCredentials.passwords[selected.account])
        XCTAssertEqual(fixture.photoCredentials.passwords["photo:unrelated:owner"], "unrelated protected value")
        XCTAssertNil(fixture.defaults.data(forKey: "photoAccessSelection"))
        XCTAssertNil(fixture.defaults.data(forKey: "photoAccessPending"))
        XCTAssertFalse(fixture.store.hasSavedFrame)
    }
    func testPhotoOwnerWiFiRelocationUsesSameDeviceWithoutLegacyPassword() async throws {
        let certificate = FrameTrustTestFixtures.certificate
        let identity = try FrameIdentity(id: FrameTrustTestFixtures.id, spkiSHA256: PinnedFrameTrust.spkiSHA256(certificateDER: certificate))
        let fixture = StoreFixture(pin: identity)
        defer { fixture.dispose() }
        fixture.stub.enablePhotoAccess(identity)
        await fixture.login("https://owner-frame.local:8443")
        await fixture.store.enrollPhotoAccess()
        let deviceID = fixture.store.photoAccessDeviceID
        let endpoint = URL(string: "https://relocated-frame.local:8443")!
        let owner = OwnershipRecord(identity: identity, certificateDER: certificate, ownerID: UUID(), claimRequestID: UUID(),
            ownerToken: Data(repeating: 0x45, count: 32), endpoints: [endpoint], state: .claimed)
        let insertion: [String: Any] = [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: fixture.ownershipService,
            kSecAttrAccount as String: identity.id.uuidString.lowercased(), kSecAttrAccessible as String: kSecAttrAccessibleWhenUnlockedThisDeviceOnly,
            kSecValueData as String: try JSONEncoder().encode(owner)]
        XCTAssertEqual(SecItemAdd(insertion as CFDictionary, nil), errSecSuccess)
        let before = fixture.stub.requests.count
        await fixture.store.finishBluetoothSetup(endpoint: endpoint, owner: owner)
        XCTAssertEqual(fixture.store.address, endpoint.absoluteString)
        XCTAssertEqual(fixture.store.photoAccessDeviceID, deviceID)
        XCTAssertEqual(fixture.store.photoAccessRole, .owner)
        XCTAssertEqual(fixture.defaults.string(forKey: "frameOwnerID"), identity.id.uuidString.lowercased())
        let requests = fixture.stub.requests.dropFirst(before)
        XCTAssertEqual(requests.filter { $0.url?.path == "/api/auth/device-session" }.count, 1)
        XCTAssertFalse(requests.contains { ["/api/auth/login", "/api/auth/devices/enroll"].contains($0.url!.path) })
        XCTAssertTrue(requests.allSatisfy { $0.url?.scheme == "https" })
        let selection = try JSONDecoder().decode(PhotoAccessSelection.self, from: XCTUnwrap(fixture.defaults.data(forKey: "photoAccessSelection")))
        let durable = try await fixture.photoVault.loadCredential(account: selection.account)
        XCTAssertEqual(durable.endpoint, endpoint)
        XCTAssertTrue(selection.validates(durable))
    }

    func testPhotoWiFiMismatchedIdentityAndLateSessionCannotReplaceOldAccess() async throws {
        let identity = try invitationIdentity()
        let fixture = StoreFixture(pin: identity)
        defer { fixture.dispose() }
        fixture.stub.enablePhotoAccess(identity)
        await fixture.login("https://owner-frame.local:8443")
        await fixture.store.enrollPhotoAccess()
        let previous = fixture.store.api
        let address = fixture.store.address
        let endpoint = URL(string: "https://relocated-frame.local:8443")!
        let wrongIdentity = try FrameIdentity(id: UUID(), spkiSHA256: identity.spkiSHA256)
        func owner(_ identity: FrameIdentity) -> OwnershipRecord {
            OwnershipRecord(identity: identity, certificateDER: Data(), ownerID: UUID(), claimRequestID: UUID(),
                ownerToken: Data(repeating: 5, count: 32), endpoints: [endpoint], state: .claimed)
        }
        let before = fixture.stub.requests.count
        await fixture.store.finishBluetoothSetup(endpoint: endpoint, owner: owner(wrongIdentity))
        XCTAssertEqual(fixture.stub.requests.count, before)
        XCTAssertTrue(fixture.store.api === previous)
        let gate = fixture.stub.hold(host: "relocated-frame.local", path: "/api/auth/device-session", method: "POST")
        let relocation = Task { await fixture.store.finishBluetoothSetup(endpoint: endpoint, owner: owner(identity)) }
        await fulfillment(of: [gate.started], timeout: 3)
        fixture.store.sceneChanged(.background)
        gate.release(); await relocation.value
        XCTAssertTrue(fixture.store.api === previous)
        XCTAssertEqual(fixture.store.address, address)
        XCTAssertTrue(fixture.store.authenticated)
        XCTAssertFalse(fixture.store.localUnlocked)
    }
    func testInvitationLocalPromptInactiveWaitsForActiveAndBackgroundCancelsAdmission() async throws {
        for background in [false, true] {
            let authentication = LocalAuthGate()
            let fixture = StoreFixture(authenticateLocal: { try await authentication.wait() })
            defer { fixture.dispose() }
            let code = try invitationCode()
            fixture.stub.enablePhotoAccess(code.identity)
            let claim = Task { await fixture.store.claimInvitation(code) }
            await fulfillment(of: [authentication.started], timeout: 3)
            fixture.store.sceneChanged(.inactive)
            authentication.release()
            // Allow the authentication continuation to reach its foreground admission gate.
            for _ in 0..<8 { await Task.yield() }
            XCTAssertTrue(fixture.stub.requests.isEmpty)
            XCTAssertTrue(fixture.photoCredentials.passwords.isEmpty)
            if background {
                fixture.store.sceneChanged(.background)
                await claim.value
                XCTAssertFalse(fixture.store.unlocking)
                XCTAssertFalse(fixture.store.localUnlocked)
                XCTAssertFalse(fixture.store.authenticated)
                XCTAssertTrue(fixture.stub.requests.isEmpty)
                XCTAssertTrue(fixture.photoCredentials.passwords.isEmpty)
            } else {
                // Physical Face ID can finish before UIKit reactivates the window.
                // More than the former two-second deadline must not discard its grant.
                try await Task.sleep(for: .milliseconds(2100))
                XCTAssertTrue(fixture.store.unlocking)
                XCTAssertTrue(fixture.store.localUnlocked)
                XCTAssertNil(fixture.store.localAuthenticationError)
                XCTAssertTrue(fixture.stub.requests.isEmpty)
                XCTAssertTrue(fixture.photoCredentials.passwords.isEmpty)
                fixture.store.sceneChanged(.active)
                await claim.value
                XCTAssertFalse(fixture.store.unlocking)
                XCTAssertEqual(fixture.store.photoAccessRole, .media)
                XCTAssertTrue(fixture.store.authenticated)
                XCTAssertEqual(fixture.stub.requests.filter { $0.url?.path == "/api/auth/invitations/claim" }.count, 1)
            }
        }
    }

    func testCancelledInvitationForegroundWaitReleasesAuthorizationWithoutPOST() async throws {
        let authentication = LocalAuthGate()
        let fixture = StoreFixture(authenticateLocal: { try await authentication.wait() })
        defer { fixture.dispose() }
        let code = try invitationCode()
        fixture.stub.enablePhotoAccess(code.identity)
        let claim = Task { await fixture.store.claimInvitation(code) }
        await fulfillment(of: [authentication.started], timeout: 3)
        fixture.store.sceneChanged(.inactive)
        authentication.release()
        for _ in 0..<8 { await Task.yield() }
        claim.cancel()
        await claim.value
        fixture.store.sceneChanged(.active)
        XCTAssertFalse(fixture.store.unlocking)
        XCTAssertFalse(fixture.store.localUnlocked)
        XCTAssertFalse(fixture.store.authenticated)
        XCTAssertTrue(fixture.stub.requests.isEmpty)
        XCTAssertTrue(fixture.photoCredentials.passwords.isEmpty)
        XCTAssertNil(fixture.defaults.data(forKey: "photoAccessPending"))
    }

    func testLANQRCodeLocalPromptWaitsForWindowActivationBeforeLogin() async throws {
        let authentication = LocalAuthGate()
        let fixture = StoreFixture(authenticateLocal: { try await authentication.wait() })
        defer { fixture.dispose() }
        let login = Task { await fixture.store.loginFromLANQRCode(lanQR) }
        await fulfillment(of: [authentication.started], timeout: 3)
        fixture.store.sceneChanged(.inactive)
        authentication.release()
        for _ in 0..<8 { await Task.yield() }
        XCTAssertTrue(fixture.stub.requests.isEmpty)
        XCTAssertTrue(fixture.credentials.passwords.isEmpty)
        fixture.store.sceneChanged(.active)
        await login.value
        XCTAssertTrue(fixture.store.authenticated)
        XCTAssertEqual(fixture.stub.requests.filter { $0.url?.path == "/api/auth/login" }.count, 1)
    }

    func testCancelledInvitationNeverReappearsAfterLostDELETEOrProtectedStorageFailure() async throws {
        for failure in ["delete", "mark", "purge"] {
            let identity = try invitationIdentity()
            let fixture = StoreFixture(pin: identity)
            defer { fixture.dispose() }
            fixture.stub.enablePhotoAccess(identity)
            await fixture.login("https://owner-frame.local:8443")
            await fixture.store.createInvitation()
            let cancelled = try XCTUnwrap(fixture.store.activeInvitation)
            let path = "/api/auth/invitations/" + cancelled.invitationID.uuidString.lowercased()
            if failure == "delete" {
                fixture.stub.respondNextJSON(host: "owner-frame.local", path: path, method: "DELETE", status: 503,
                    body: ["detail": "Synthetic lost revocation response"])
            }
            fixture.photoCredentials.rejectWrites = failure == "mark"
            fixture.photoCredentials.rejectRemoval = failure == "purge"
            await fixture.store.revokeActiveInvitation()
            XCTAssertNil(fixture.store.activeInvitation)
            XCTAssertNotNil(fixture.store.photoAccessError)
            let intent = fixture.defaults.dictionary(forKey: "photoInvitationRevocations") as? [String: String]
            XCTAssertTrue(intent?.values.contains(cancelled.invitationID.uuidString.lowercased()) == true)
            if failure != "mark" {
                let text = try XCTUnwrap(fixture.photoCredentials.passwords.first { $0.key.hasPrefix("invitation:") }?.value)
                let draft = try JSONDecoder().decode(PhotoInvitationDraft.self, from: Data(text.utf8))
                XCTAssertTrue(draft.revocationPending)
            }
            fixture.photoCredentials.rejectWrites = false
            fixture.photoCredentials.rejectRemoval = false
            let before = fixture.stub.requests.count
            await fixture.store.createInvitation()
            let replacement = try XCTUnwrap(fixture.store.activeInvitation)
            XCTAssertNotEqual(replacement.invitationID, cancelled.invitationID)
            XCTAssertNotEqual(replacement.code.invitationToken, cancelled.code.invitationToken)
            let calls = Array(fixture.stub.requests.dropFirst(before))
            XCTAssertEqual(calls.first?.httpMethod, "DELETE")
            XCTAssertEqual(calls.first?.url?.path, path)
            XCTAssertEqual(calls.filter { $0.httpMethod == "POST" && $0.url?.path == "/api/auth/invitations" }.count, 1)
            XCTAssertTrue((fixture.defaults.dictionary(forKey: "photoInvitationRevocations") ?? [:]).isEmpty)
        }
    }
    private var legacyBootstrapSecret: String { "Abcdef0123456789" }
    private func verifiedLegacyFixture() throws -> VerifiedLegacyTLSEndpoint {
        // Public cross-language contract vector. A valid result comes through the real verifier, never a bypass initializer.
        let response = Data("""
        {"v":1,"nonce":"0000000000000000000000000000000000000000000000000000000000000000","identity":{"frame_id":"11111111-1111-4111-8111-111111111111","spki_sha256":"abababababababababababababababababababababababababababababababab","url":"https://inky-fixture.local:8443"},"proof":"f2bd35f28b36c364a9b2447e89a2158195e4f4b506d3f993e26cd2804fc8456d"}
        """.utf8)
        return try LegacyTLSProofVerifier.verify(response: response, expectedNonce: Data(repeating: 0, count: 32),
                                                 bootstrapPassword: legacyBootstrapSecret)
    }
    private func prepareLegacySharing(_ fixture: StoreFixture) async {
        fixture.store.address = "old-frame.local"
        await fixture.store.login(password: legacyBootstrapSecret, rememberBiometric: true)
        XCTAssertTrue(fixture.store.authenticated)
        XCTAssertTrue(fixture.store.credentialStored)
        XCTAssertTrue(fixture.store.needsSecureSharingUpgrade)
        XCTAssertTrue(fixture.store.canShareAccess)
    }

    func testLegacyShareSheetRefreshDoesNotProveOrPromoteAnHTTPConnection() async throws {
        let verified = try verifiedLegacyFixture()
        var proofs = 0
        let fixture = StoreFixture(proveLegacyTLS: { _, _ in proofs += 1; return verified })
        defer { fixture.dispose() }
        await prepareLegacySharing(fixture)
        let previous = fixture.store.api
        let before = fixture.stub.requests.count
        await fixture.store.refreshAccessDevices()
        XCTAssertEqual(proofs, 0)
        XCTAssertEqual(fixture.stub.requests.count, before)
        XCTAssertTrue(fixture.store.api === previous)
        XCTAssertNil(fixture.store.photoAccessRole)
    }

    func testExplicitLegacySharingUpgradeCommitsPinnedOwnerAndCreatesQRInOneAction() async throws {
        let verified = try verifiedLegacyFixture()
        var proofs = 0
        let fixture = StoreFixture(proveLegacyTLS: { endpoint, password in
            proofs += 1
            XCTAssertEqual(endpoint.absoluteString, "http://old-frame.local:8000")
            XCTAssertEqual(password, "Abcdef0123456789")
            return verified
        })
        defer { fixture.dispose() }
        fixture.stub.enablePhotoAccess(verified.identity)
        await prepareLegacySharing(fixture)
        let previous = fixture.store.api
        let previousID = fixture.store.sessionIdentity
        let before = fixture.stub.requests.count
        let gate = fixture.stub.hold(host: "inky-fixture.local", path: "/api/auth/devices/enroll", method: "POST")
        let creation = Task { await fixture.store.createInvitation() }
        await fulfillment(of: [gate.started], timeout: 3)
        XCTAssertEqual(proofs, 1)
        XCTAssertTrue(fixture.store.api === previous)
        XCTAssertEqual(fixture.store.sessionIdentity, previousID)
        XCTAssertEqual(fixture.defaults.string(forKey: "frameAddress"), "http://old-frame.local:8000")
        XCTAssertTrue(fixture.store.photoAccessBusy)
        XCTAssertFalse(fixture.store.connecting, "The live dashboard and Share sheet remain mounted during the bridge")
        XCTAssertFalse(fixture.store.canMutate)
        let pending = try XCTUnwrap(fixture.photoCredentials.passwords.first { $0.key.hasPrefix("photo:") }?.value)
        let credential = try JSONDecoder().decode(PhotoAccessCredential.self, from: Data(pending.utf8))
        XCTAssertEqual(credential.state, .pending)
        let enrollment = try requestJSON(XCTUnwrap(fixture.stub.requests.last { $0.url?.path == "/api/auth/devices/enroll" }))
        XCTAssertEqual(enrollment["device_token"] as? String, credential.deviceToken)
        gate.release(); await creation.value
        XCTAssertEqual(fixture.store.photoAccessRole, .owner)
        XCTAssertEqual(fixture.store.api?.pinnedIdentity, verified.identity)
        XCTAssertEqual(fixture.store.address, verified.endpoint.absoluteString)
        XCTAssertNotEqual(fixture.store.sessionIdentity, previousID)
        XCTAssertFalse(fixture.store.hasAdoptedFrame)
        XCTAssertFalse(fixture.store.needsSecureSharingUpgrade)
        XCTAssertNotNil(fixture.store.activeInvitation, "The same explicit action continues after the new session identity commit")
        XCTAssertEqual(fixture.credentials.passwords["http://old-frame.local:8000"], legacyBootstrapSecret)
        let calls = Array(fixture.stub.requests.dropFirst(before))
        XCTAssertTrue(calls.allSatisfy { $0.url?.scheme == "https" })
        XCTAssertEqual(calls.filter { $0.url?.path == "/api/auth/login" }.count, 1)
        XCTAssertEqual(calls.filter { $0.url?.path == "/api/auth/devices/enroll" }.count, 1)
        XCTAssertEqual(calls.filter { $0.url?.path == "/api/auth/device-session" }.count, 1)
        XCTAssertEqual(calls.filter { $0.url?.path == "/api/auth/invitations" }.count, 1)
        XCTAssertTrue(fixture.store.canMutate)
    }

    func testLegacyUpgradeFailureAtEveryStagePreservesOldHTTPAndProtectedSecret() async throws {
        let verified = try verifiedLegacyFixture()
        for stage in ["proof", "login", "enroll", "session", "pending-save", "final-save"] {
            var writes = 0
            let fixture = StoreFixture(savePhotoValue: { _, _ in
                writes += 1
                if stage == "pending-save" || (stage == "final-save" && writes == 2) { throw VaultError.unavailable }
            }, proveLegacyTLS: { _, _ in
                if stage == "proof" { throw PhotoAccessError.unavailable }
                return verified
            })
            defer { fixture.dispose() }
            fixture.stub.enablePhotoAccess(verified.identity)
            await prepareLegacySharing(fixture)
            let previous = fixture.store.api
            let previousID = fixture.store.sessionIdentity
            let path: String?
            switch stage {
            case "login": path = "/api/auth/login"
            case "enroll": path = "/api/auth/devices/enroll"
            case "session": path = "/api/auth/device-session"
            default: path = nil
            }
            if let path {
                fixture.stub.respondNextJSON(host: "inky-fixture.local", path: path, method: "POST", status: 503,
                    body: ["detail": "Synthetic unavailable capability"])
            }
            await fixture.store.createInvitation()
            XCTAssertTrue(fixture.store.api === previous, stage)
            XCTAssertEqual(fixture.store.sessionIdentity, previousID, stage)
            XCTAssertEqual(fixture.store.address, "http://old-frame.local:8000", stage)
            XCTAssertEqual(fixture.defaults.string(forKey: "frameAddress"), "http://old-frame.local:8000", stage)
            XCTAssertEqual(fixture.credentials.passwords["http://old-frame.local:8000"], legacyBootstrapSecret, stage)
            XCTAssertNil(fixture.defaults.data(forKey: "photoAccessSelection"), stage)
            XCTAssertNil(fixture.store.photoAccessRole, stage)
            XCTAssertTrue(fixture.store.authenticated, stage)
            XCTAssertTrue(fixture.store.canMutate, stage)
            XCTAssertFalse(fixture.store.photoAccessBusy, stage)
            XCTAssertNil(fixture.store.activeInvitation, stage)
            XCTAssertNotNil(fixture.store.photoAccessError, stage)
            if ["proof", "login", "enroll", "session"].contains(stage) {
                XCTAssertEqual(fixture.store.photoAccessError, "Le partage nécessite une mise à jour du cadre.")
            }
        }
    }

    func testLegacyUpgradeCancelAndBackgroundRejectLateProofOrTLSReply() async throws {
        let verified = try verifiedLegacyFixture()
        for stage in ["proof", "login", "enroll", "session"] {
            for background in [false, true] {
                let proofGate = LegacySharingProofGate(verified)
                let fixture = StoreFixture(proveLegacyTLS: { _, _ in
                    stage == "proof" ? await proofGate.wait() : verified
                })
                defer { fixture.dispose() }
                fixture.stub.enablePhotoAccess(verified.identity)
                await prepareLegacySharing(fixture)
                let previous = fixture.store.api
                let previousID = fixture.store.sessionIdentity
                let path: String
                switch stage {
                case "login": path = "/api/auth/login"
                case "enroll": path = "/api/auth/devices/enroll"
                default: path = "/api/auth/device-session"
                }
                let gate = stage == "proof" ? nil : fixture.stub.hold(host: "inky-fixture.local", path: path, method: "POST")
                let before = fixture.stub.requests.count
                let creation = Task { await fixture.store.createInvitation() }
                await fulfillment(of: [gate?.started ?? proofGate.started], timeout: 3)
                if background { fixture.store.sceneChanged(.background) }
                else { fixture.store.cancelPhotoAccessOperation() }
                gate?.release(); proofGate.release()
                await creation.value
                XCTAssertTrue(fixture.store.api === previous, stage)
                XCTAssertEqual(fixture.store.sessionIdentity, previousID, stage)
                XCTAssertEqual(fixture.store.address, "http://old-frame.local:8000", stage)
                XCTAssertTrue(fixture.store.authenticated, stage)
                XCTAssertNil(fixture.store.photoAccessRole, stage)
                XCTAssertNil(fixture.store.activeInvitation, stage)
                XCTAssertFalse(fixture.store.photoAccessBusy, stage)
                XCTAssertFalse(fixture.store.connecting, stage)
                XCTAssertEqual(fixture.store.localUnlocked, !background, stage)
                XCTAssertEqual(fixture.credentials.passwords["http://old-frame.local:8000"], legacyBootstrapSecret, stage)
                if stage == "proof" { XCTAssertEqual(fixture.stub.requests.count, before) }
            }
        }
    }

    func testLegacyUpgradeLostEnrollmentResponseReusesProtectedDeviceAndRequestIDs() async throws {
        let verified = try verifiedLegacyFixture()
        let fixture = StoreFixture(proveLegacyTLS: { _, _ in verified })
        defer { fixture.dispose() }
        fixture.stub.enablePhotoAccess(verified.identity)
        await prepareLegacySharing(fixture)
        fixture.stub.respondNextJSON(host: "inky-fixture.local", path: "/api/auth/devices/enroll", method: "POST", status: 503,
            body: ["detail": "Uncertain enrollment response"])
        await fixture.store.createInvitation()
        XCTAssertTrue(fixture.store.needsSecureSharingUpgrade)
        let first = try requestJSON(XCTUnwrap(fixture.stub.requests.last { $0.url?.path == "/api/auth/devices/enroll" }))
        await fixture.store.createInvitation()
        let second = try requestJSON(XCTUnwrap(fixture.stub.requests.last { $0.url?.path == "/api/auth/devices/enroll" }))
        for field in ["device_id", "device_token", "request_id"] { XCTAssertEqual(first[field] as? String, second[field] as? String) }
        XCTAssertNotNil(fixture.store.activeInvitation)
        XCTAssertEqual(fixture.store.photoAccessRole, .owner)
    }

    func testLegacyCookieOnlyCannotUpgradeButKeepsWorkingWithoutRescan() async throws {
        var proofs = 0
        let verified = try verifiedLegacyFixture()
        let fixture = StoreFixture(proveLegacyTLS: { _, _ in proofs += 1; return verified })
        defer { fixture.dispose() }
        await fixture.login("old-frame.local")
        let previous = fixture.store.api
        XCTAssertTrue(fixture.store.needsSecureSharingUpgrade)
        XCTAssertFalse(fixture.store.canShareAccess)
        let before = fixture.stub.requests.count
        await fixture.store.createInvitation()
        await fixture.store.enrollPhotoAccess()
        XCTAssertEqual(proofs, 0)
        XCTAssertEqual(fixture.stub.requests.count, before)
        XCTAssertTrue(fixture.store.api === previous)
        XCTAssertTrue(fixture.store.authenticated)
        XCTAssertTrue(fixture.store.canMutate)
    }

    func testLegacyUpgradeNeverSendsPasswordWhenCandidateDoesNotHaveVerifiedPin() async throws {
        let verified = try verifiedLegacyFixture()
        let wrong = try FrameIdentity(id: UUID(), spkiSHA256: verified.identity.spkiSHA256)
        let fixture = StoreFixture(candidatePin: wrong, proveLegacyTLS: { _, _ in verified })
        defer { fixture.dispose() }
        await prepareLegacySharing(fixture)
        let previous = fixture.store.api
        let before = fixture.stub.requests.count
        await fixture.store.createInvitation()
        XCTAssertEqual(fixture.stub.requests.count, before)
        XCTAssertTrue(fixture.store.api === previous)
        XCTAssertTrue(fixture.store.authenticated)
        XCTAssertNil(fixture.store.photoAccessRole)
    }

    func testUpgradedOwner401DoesNotUseRetainedLegacyPasswordOrRepeatProof() async throws {
        let verified = try verifiedLegacyFixture()
        var proofs = 0
        let fixture = StoreFixture(proveLegacyTLS: { _, _ in proofs += 1; return verified })
        defer { fixture.dispose() }
        fixture.stub.enablePhotoAccess(verified.identity)
        await prepareLegacySharing(fixture)
        await fixture.store.enrollPhotoAccess()
        XCTAssertEqual(fixture.store.photoAccessRole, .owner)
        await fixture.store.logout()
        fixture.stub.respondNextJSON(host: "inky-fixture.local", path: "/api/auth/device-session", method: "POST", status: 401,
            body: ["detail": "Revoked device"])
        let before = fixture.stub.requests.count
        await fixture.store.unlock()
        XCTAssertEqual(fixture.stub.requests.dropFirst(before).map { $0.url!.path }, ["/api/auth/device-session"])
        XCTAssertEqual(proofs, 1)
        XCTAssertFalse(fixture.store.authenticated)
        XCTAssertFalse(fixture.store.localUnlocked)
        XCTAssertEqual(fixture.store.photoAccessRole, .owner)
        XCTAssertEqual(fixture.credentials.passwords["http://old-frame.local:8000"], legacyBootstrapSecret)
    }

    func testForgetDuringLegacyProofCannotReviveOldOrPendingAccess() async throws {
        let verified = try verifiedLegacyFixture()
        let gate = LegacySharingProofGate(verified)
        let fixture = StoreFixture(proveLegacyTLS: { _, _ in await gate.wait() })
        defer { fixture.dispose() }
        await prepareLegacySharing(fixture)
        let creation = Task { await fixture.store.createInvitation() }
        await fulfillment(of: [gate.started], timeout: 3)
        await fixture.store.logout(forget: true)
        gate.release(); await creation.value
        XCTAssertFalse(fixture.store.hasSavedFrame)
        XCTAssertNil(fixture.store.api)
        XCTAssertNil(fixture.store.photoAccessRole)
        XCTAssertNil(fixture.defaults.data(forKey: "photoAccessSelection"))
        XCTAssertNil(fixture.defaults.data(forKey: "photoAccessPending"))
        XCTAssertFalse(fixture.stub.requests.contains { $0.url?.host == "inky-fixture.local" })
    }

    private func factoryCompletion() throws -> (OwnershipRecord, FactorySetupStatus, URL) {
        let identity = try FrameIdentity(id: UUID(uuidString: "aaaaaaaa-1111-4222-8333-bbbbbbbbbbbb")!,
                                         spkiSHA256: Data(repeating: 0x42, count: 32))
        let endpoint = URL(string: "https://inky-0123456789abcdef0123456789abcdef.local:8443")!
        var owner = OwnershipRecord(identity: identity, certificateDER: Data(), ownerID: UUID(),
            claimRequestID: UUID(), ownerToken: Data(repeating: 0x73, count: 32), endpoints: [], state: .claimed)
        owner.factoryProfile = .normalV1
        let operation = UUID()
        owner.factorySetupOperationID = operation
        let status = FactorySetupStatus(operationID: operation, state: .complete, frameID: identity.id,
            ownerID: owner.ownerID, claimRequestID: owner.claimRequestID,
            normalIdentity: FactorySetupNormalIdentity(identity: identity, publicationOperationID: UUID()),
            httpsOrigin: endpoint, completionID: UUID(), nextStep: .photoEnroll)
        return (owner, status, endpoint)
    }

    func testFactoryEnrollmentRequiresItsLocalAuthenticationGrant() async throws {
        let fixture = StoreFixture(authenticateLocal: { throw VaultError.cancelled })
        defer { fixture.dispose() }
        let (owner, status, endpoint) = try factoryCompletion()
        let unauthorized = await fixture.store.finishFactorySetup(endpoint: endpoint, owner: owner, status: status)
        XCTAssertFalse(unauthorized)
        let authorized = await fixture.store.authorizeFactorySetup()
        XCTAssertFalse(authorized)
        XCTAssertTrue(fixture.stub.requests.isEmpty)
        XCTAssertTrue(fixture.photoCredentials.passwords.isEmpty)
    }

    func testFactoryClosedDuringLocalAuthenticationCannotGrantLateAuthority() async throws {
        let gate = LocalAuthGate()
        let fixture = StoreFixture(authenticateLocal: { try await gate.wait() })
        defer { fixture.dispose() }
        let pending = Task { await fixture.store.authorizeFactorySetup() }
        await fulfillment(of: [gate.started], timeout: 3)
        fixture.store.cancelFactorySetup()
        gate.release()
        let authorized = await pending.value
        XCTAssertFalse(authorized)
        let (owner, status, endpoint) = try factoryCompletion()
        let completed = await fixture.store.finishFactorySetup(endpoint: endpoint, owner: owner, status: status)
        XCTAssertFalse(completed)
        XCTAssertTrue(fixture.stub.requests.isEmpty)
        XCTAssertTrue(fixture.photoCredentials.passwords.isEmpty)
    }

    func testFactoryPreservesOldCredentialUntilEnrollmentAndDeviceSessionThenCommits() async throws {
        var checks = 0
        let fixture = StoreFixture(authenticateLocal: { checks += 1 })
        defer { fixture.dispose() }
        await fixture.login("old-frame.local")
        fixture.credentials.passwords[fixture.store.address] = "factory-previous-protected"
        let old = try XCTUnwrap(fixture.store.api)
        let oldAddress = fixture.store.address
        let (owner, status, endpoint) = try factoryCompletion()
        fixture.stub.enablePhotoAccess(owner.identity)
        let canonical = PhotoAccessSelection.account(identity: owner.identity, invitationID: nil)
        let previousCredential = try PhotoAccessCredential.make(identity: owner.identity, endpoint: endpoint, role: .owner)
        try fixture.photoVault.save(previousCredential, account: canonical)
        let canonicalBefore = fixture.photoCredentials.passwords[canonical]
        let authorized = await fixture.store.authorizeFactorySetup()
        XCTAssertTrue(authorized)
        XCTAssertEqual(checks, 2, "The existing app unlock is followed by a factory-specific local authorization.")
        let before = fixture.stub.requests.count
        let gate = fixture.stub.hold(host: endpoint.host!, path: "/api/auth/factory-device-enroll", method: "POST")
        let task = Task { await fixture.store.finishFactorySetup(endpoint: endpoint, owner: owner, status: status) }
        await fulfillment(of: [gate.started], timeout: 3)
        XCTAssertTrue(fixture.store.api === old)
        XCTAssertEqual(fixture.store.address, oldAddress)
        XCTAssertEqual(fixture.photoCredentials.passwords[canonical], canonicalBefore)
        XCTAssertFalse(fixture.store.connecting)
        XCTAssertTrue(fixture.store.photoAccessBusy)
        let draftText = try XCTUnwrap(fixture.photoCredentials.passwords.first { $0.key.hasPrefix("factory:") }?.value)
        let draft = try JSONDecoder().decode(PhotoAccessCredential.self, from: Data(draftText.utf8))
        XCTAssertEqual(draft.requestID, owner.claimRequestID)
        XCTAssertNotEqual(draft.deviceID, owner.ownerID)
        XCTAssertFalse(draft.deviceToken == owner.ownerTokenHex, "PHOTO and BLE tokens must be independent.")
        gate.release()
        let completed = await task.value
        XCTAssertTrue(completed)
        XCTAssertFalse(fixture.store.api === old)
        XCTAssertEqual(fixture.store.address, endpoint.absoluteString)
        XCTAssertEqual(fixture.store.api?.pinnedIdentity, owner.identity)
        XCTAssertEqual(fixture.store.photoAccessRole, .owner)
        XCTAssertEqual(fixture.defaults.string(forKey: "frameOwnerID"), owner.id.uuidString.lowercased())
        XCTAssertEqual(fixture.credentials.passwords[oldAddress], "factory-previous-protected")
        XCTAssertFalse(fixture.photoCredentials.passwords.keys.contains { $0.hasPrefix("factory:") })
        let calls = Array(fixture.stub.requests.dropFirst(before))
        XCTAssertFalse(calls.contains { $0.url?.path == "/api/auth/login" })
        let enrollment = try XCTUnwrap(calls.first { $0.url?.path == "/api/auth/factory-device-enroll" })
        let body = try requestJSON(enrollment)
        XCTAssertEqual(Set(body.keys), ["device_id", "device_token", "request_id", "claim_request_id", "setup_op_id"])
        XCTAssertEqual(body["request_id"] as? String, owner.claimRequestID.uuidString.lowercased())
        XCTAssertEqual(body["claim_request_id"] as? String, owner.claimRequestID.uuidString.lowercased())
        XCTAssertEqual(body["setup_op_id"] as? String, status.operationID.uuidString.lowercased())
        XCTAssertTrue(enrollment.value(forHTTPHeaderField: "X-Inky-Owner-Token") == owner.ownerTokenHex)
        XCTAssertNil(enrollment.value(forHTTPHeaderField: "Cookie"))
        for call in calls where call.url?.path != "/api/auth/factory-device-enroll" {
            XCTAssertNil(call.value(forHTTPHeaderField: "X-Inky-Owner-Token"))
            XCTAssertNil(call.value(forHTTPHeaderField: "X-Inky-Owner-Id"))
        }
    }

    func testFactoryFailuresAtProtectedStorageEnrollmentOrSessionKeepPreviousSelection() async throws {
        for stage in ["draft-save", "enroll", "session", "final-save", "reply"] {
            let fixture = StoreFixture(savePhotoValue: { _, account in
                if stage == "draft-save" && account.hasPrefix("factory:") { throw VaultError.unavailable }
                if stage == "final-save" && account.hasPrefix("photo:") { throw VaultError.unavailable }
            })
            defer { fixture.dispose() }
            await fixture.login("old-frame.local")
        fixture.credentials.passwords[fixture.store.address] = "factory-previous-protected"
            let old = fixture.store.api
            let oldAddress = fixture.store.address
            let (owner, status, endpoint) = try factoryCompletion()
            fixture.stub.enablePhotoAccess(owner.identity)
            if stage == "enroll" || stage == "reply" {
                fixture.stub.respondNextJSON(host: endpoint.host!, path: "/api/auth/factory-device-enroll", method: "POST",
                    status: stage == "enroll" ? 503 : 200, body: ["unexpected": "fixture"])
            } else if stage == "session" {
                fixture.stub.respondNextJSON(host: endpoint.host!, path: "/api/auth/device-session", method: "POST",
                    status: 401, body: ["detail": "Synthetic removal"])
            }
            let authorized = await fixture.store.authorizeFactorySetup()
            XCTAssertTrue(authorized)
            let completed = await fixture.store.finishFactorySetup(endpoint: endpoint, owner: owner, status: status)
            XCTAssertFalse(completed, stage)
            XCTAssertTrue(fixture.store.api === old, stage)
            XCTAssertTrue(fixture.store.authenticated, stage)
            XCTAssertEqual(fixture.defaults.string(forKey: "frameAddress"), oldAddress, stage)
            XCTAssertNil(fixture.defaults.string(forKey: "photoAccessSelection"), stage)
            XCTAssertEqual(fixture.credentials.passwords[oldAddress], "factory-previous-protected", stage)
        }
    }

    func testFactoryCancellationOrBackgroundRejectsLateEnrollmentAndSession() async throws {
        for route in ["/api/auth/factory-device-enroll", "/api/auth/device-session"] {
            for background in [false, true] {
                let fixture = StoreFixture()
                defer { fixture.dispose() }
                await fixture.login("old-frame.local")
        fixture.credentials.passwords[fixture.store.address] = "factory-previous-protected"
                let old = fixture.store.api
                let oldAddress = fixture.store.address
                let (owner, status, endpoint) = try factoryCompletion()
                fixture.stub.enablePhotoAccess(owner.identity)
                let authorized = await fixture.store.authorizeFactorySetup()
                XCTAssertTrue(authorized)
                let gate = fixture.stub.hold(host: endpoint.host!, path: route, method: "POST")
                let task = Task { await fixture.store.finishFactorySetup(endpoint: endpoint, owner: owner, status: status) }
                await fulfillment(of: [gate.started], timeout: 3)
                if background { fixture.store.sceneChanged(.background) }
                else { fixture.store.cancelPhotoAccessOperation() }
                gate.release()
                let completed = await task.value
                XCTAssertFalse(completed)
                XCTAssertTrue(fixture.store.api === old)
                XCTAssertEqual(fixture.store.address, oldAddress)
                XCTAssertNil(fixture.defaults.string(forKey: "photoAccessSelection"))
            }
        }
    }

    func testFactoryUncertainEnrollmentRetryKeepsProtectedDeviceAndClaimRequest() async throws {
        let fixture = StoreFixture()
        defer { fixture.dispose() }
        await fixture.login("old-frame.local")
        fixture.credentials.passwords[fixture.store.address] = "factory-previous-protected"
        let (owner, status, endpoint) = try factoryCompletion()
        fixture.stub.enablePhotoAccess(owner.identity)
        let authorized = await fixture.store.authorizeFactorySetup()
        XCTAssertTrue(authorized)
        fixture.stub.respondNextJSON(host: endpoint.host!, path: "/api/auth/factory-device-enroll", method: "POST",
                                    status: 503, body: ["detail": "Synthetic response lost"])
        let first = await fixture.store.finishFactorySetup(endpoint: endpoint, owner: owner, status: status)
        XCTAssertFalse(first)
        let second = await fixture.store.finishFactorySetup(endpoint: endpoint, owner: owner, status: status)
        XCTAssertTrue(second)
        let calls = fixture.stub.requests.filter { $0.url?.path == "/api/auth/factory-device-enroll" }
        XCTAssertEqual(calls.count, 2)
        let firstBody = try requestJSON(XCTUnwrap(calls.first))
        let secondBody = try requestJSON(XCTUnwrap(calls.last))
        for key in ["device_id", "device_token", "request_id", "claim_request_id", "setup_op_id"] {
            XCTAssertTrue(firstBody[key] as? String == secondBody[key] as? String, "Exact enrollment intent must survive a lost response.")
        }
    }

}

@MainActor
private final class StoreFixture {
    let suite = "InkyStoreTests.\(UUID().uuidString)"
    let defaults: UserDefaults
    let vaultService = "fr.mehdiguiard.inkystudio.tests.\(UUID().uuidString)"
    let ownershipService = "InkyStoreOwnershipTests.\(UUID().uuidString)"
    let stub: StoreStub
    let store: AppStore

    let credentials = TestCredentials()
    let photoCredentials = TestCredentials()
    let photoVault: PhotoAccessVault

    init(totals: [String: Int] = [:], authenticateLocal: (@MainActor () async throws -> Void)? = nil,
         saveCredential: (@MainActor (String, String) throws -> Void)? = nil,
         loadCredential: (@MainActor (String) async throws -> String)? = nil,
         savePhotoValue: (@MainActor (String, String) throws -> Void)? = nil,
         pin: FrameIdentity? = nil,
         candidatePin: FrameIdentity? = nil,
         proveLegacyTLS: (@MainActor (URL, String) async throws -> VerifiedLegacyTLSEndpoint)? = nil) {
        let defaults = UserDefaults(suiteName: suite)!
        self.defaults = defaults
        let stub = StoreStub(totals: totals)
        self.stub = stub
        let credentialMemory = self.credentials
        let photoMemory = self.photoCredentials
        let protectedAccess = PhotoAccessVault(saveValue: { value, account in
            try savePhotoValue?(value, account)
            guard !photoMemory.rejectWrites else { throw VaultError.unavailable }
            photoMemory.passwords[account] = value
        }, loadValue: { account in
            guard let value = photoMemory.passwords[account] else { throw VaultError.missing }
            return value
        }, containsValue: { photoMemory.passwords[$0] != nil }, removeValue: { account in
            guard !photoMemory.rejectRemoval else { throw VaultError.unavailable }
            photoMemory.passwords.removeValue(forKey: account)
        })
        photoVault = protectedAccess
        store = AppStore(defaults: defaults,
                         makeAPI: { InkyAPI(baseURL: $0, configuration: stub.configuration(), trustedIdentity: pin) },
                         vault: BiometricVault(service: vaultService),
                         photoAccessVault: protectedAccess,
                         ownershipVault: OwnershipVault(service: ownershipService),
                         makePinnedAPI: { InkyAPI(baseURL: $0, configuration: stub.configuration(), trustedIdentity: candidatePin ?? $1) },
                         proveLegacyTLS: proveLegacyTLS,
                         authenticateLocal: authenticateLocal ?? {},
                         invalidateAuthentication: {},
                         saveCredential: { password, address in
                             try saveCredential?(password, address)
                             credentialMemory.passwords[address] = password
                         },
                         loadCredential: loadCredential ?? { address in
                             guard let password = credentialMemory.passwords[address] else { throw VaultError.missing }
                             return password
                         },
                         containsCredential: { credentialMemory.passwords[$0] != nil },
                         authenticationName: { "code iPhone" },
                         monitorsEvents: false)
    }

    func login(_ host: String) async {
        store.address = host
        await store.login(password: "synthetic-test-password")
        XCTAssertTrue(store.authenticated)
        XCTAssertTrue(store.connected)
    }

    func enterForegroundWithoutMonitoring() {
        // Exercise foreground-only refresh behavior without opening a real WebSocket.
        let authenticated = store.authenticated
        store.authenticated = false
        store.sceneActive(true)
        store.authenticated = authenticated
    }

    func seedStoredPassword(account: String) throws { credentials.passwords[account] = "SyntheticOldPassword" }
    func storedPasswordStatus(account: String) -> OSStatus { credentials.passwords[account] == nil ? errSecItemNotFound : errSecSuccess }

    func dispose() {
        store.lock()
        store.api?.clearSession()
        defaults.removePersistentDomain(forName: suite)
        SecItemDelete([kSecClass as String: kSecClassGenericPassword,
                       kSecAttrService as String: vaultService] as CFDictionary)
        SecItemDelete([kSecClass as String: kSecClassGenericPassword,
                       kSecAttrService as String: ownershipService] as CFDictionary)
        stub.dispose()
    }
}

@MainActor
private final class TestCredentials {
    var passwords: [String: String] = [:]
    var rejectWrites = false
    var rejectRemoval = false
}

@MainActor
private final class LocalAuthGate {
    let started = XCTestExpectation(description: "Local authentication started")
    private var continuation: CheckedContinuation<Void, Error>?
    func wait() async throws {
        try await withCheckedThrowingContinuation { continuation in
            self.continuation = continuation
            started.fulfill()
        }
    }
    func release() { continuation?.resume(); continuation = nil }
}

private final class StoreGate: @unchecked Sendable {
    let started = XCTestExpectation(description: "Held request started")
    private let lock = NSLock()
    private var completion: ((Int?) -> Void)?
    func hold(_ callback: @escaping (Int?) -> Void) {
        lock.withLock { completion = callback }
        started.fulfill()
    }
    func release(status: Int? = nil) {
        let callback = lock.withLock { let result = completion; completion = nil; return result }
        callback?(status)
    }
}

private final class StoreStub: @unchecked Sendable {
    static let pendingDisplayDetail = "La fin de l’affichage n’a pas pu être confirmée. La photo est conservée. L’affichage automatique est suspendu ; vous pouvez réessayer manuellement."
    static var pendingDisplayFailure: [String: Any] {
        ["code": "display_confirmation_pending", "detail": pendingDisplayDetail]
    }
    private let id = UUID().uuidString
    private let lock = NSLock()
    private let totals: [String: Int]
    private var gates: [String: StoreGate] = [:]
    private var calls: [URLRequest] = []
    private var accessIdentity: FrameIdentity?
    private var accessDeviceRoles: [String: String] = [:]
    private var responseErrors: [String: URLError] = [:]
    private var displayStatus: [String: Any]?
    private var customResponses: [String: (Data, Int)] = [:]
    private var nextResponses: [String: (Data, Int)] = [:]
    var requests: [URLRequest] { lock.withLock { calls } }
    init(totals: [String: Int]) { self.totals = totals }

    func enablePhotoAccess(_ identity: FrameIdentity) { lock.withLock { accessIdentity = identity } }

    func failNext(host: String, path: String, error: URLError) {
        lock.withLock { responseErrors["\(host)|GET|\(path)"] = error }
    }

    func setDisplayStatus(state: String, error: String? = nil) {
        lock.withLock {
            displayStatus = ["mode": "hardware", "profile": "ac073-800x480", "state": state, "is_mock": false,
                "error": error.map { ["code": $0, "detail": "Synthetic display diagnostic"] } as Any? ?? NSNull()]
        }
    }

    func setPendingDisplayConfirmation(state: String = "ready", error: String? = nil) {
        lock.withLock {
            displayStatus = ["mode": "hardware", "profile": "ac073-800x480", "state": state, "is_mock": false,
                "error": error.map { ["code": $0, "detail": "Synthetic display failure"] } as Any? ?? NSNull(),
                "confirmation": "pending", "warning": Self.pendingDisplayFailure, "automatic_rotation_paused": true,
                "driver": [String: String](), "busy_monitor": "ac073_2.3.0", "observations": [
                    ["phase": "setup", "timeout": 1.0, "outcome": "held_high_unverified", "sequence": 1, "error_type": NSNull()],
                    ["phase": "power_on", "timeout": 0.4, "outcome": "held_high_unverified", "sequence": 2, "error_type": NSNull()],
                    ["phase": "refresh", "timeout": 45.0, "outcome": "held_high_unverified", "sequence": 3, "error_type": NSNull()],
                    ["phase": "power_off", "timeout": 0.4, "outcome": "held_high_unverified", "sequence": 4, "error_type": NSNull()],
                ]]
        }
    }

    func setJSONResponse(host: String, path: String, body: Any) {
        setResponse(host: host, path: path, data: try! JSONSerialization.data(withJSONObject: body))
    }

    func setResponse(host: String, path: String, data: Data) {
        lock.withLock { customResponses["\(host)|GET|\(path)"] = (data, 200) }
    }

    func respondNextJSON(host: String, path: String, method: String, status: Int, body: Any) {
        let data = try! JSONSerialization.data(withJSONObject: body)
        lock.withLock { nextResponses["\(host)|\(method)|\(path)"] = (data, status) }
    }

    func hold(host: String, path: String, method: String = "GET") -> StoreGate {
        let gate = StoreGate()
        let verb = path == "/api/auth/logout" ? "POST" : method
        lock.withLock { gates["\(host)|\(verb)|\(path)"] = gate }
        return gate
    }

    func configuration() -> URLSessionConfiguration {
        StoreURLProtocol.register(self, id: id)
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [StoreURLProtocol.self]
        configuration.httpAdditionalHeaders = ["X-Inky-Store-Test": id]
        return configuration
    }

    func dispose() { StoreURLProtocol.remove(id: id) }

    func respond(_ original: URLRequest, completion: @escaping (Data, Int, URLError?) -> Void) {
        var request = original
        if request.httpBody == nil, let stream = request.httpBodyStream {
            stream.open(); defer { stream.close() }
            var bytes = Data(); var buffer = [UInt8](repeating: 0, count: 2048)
            while stream.hasBytesAvailable {
                let count = stream.read(&buffer, maxLength: buffer.count)
                if count <= 0 { break }
                bytes.append(contentsOf: buffer.prefix(count))
            }
            request.httpBody = bytes
        }
        let host = request.url!.host!
        let path = request.url!.path
        let key = "\(host)|\(request.httpMethod ?? "GET")|\(path)"
        let gate = lock.withLock { calls.append(request); return gates.removeValue(forKey: key) }
        if let error = lock.withLock({ responseErrors.removeValue(forKey: key) }) {
            completion(Data(), 0, error)
            return
        }
        if let response = lock.withLock({ nextResponses.removeValue(forKey: key) ?? customResponses[key] }) {
            if let gate { gate.hold { status in completion(response.0, status ?? response.1, nil) } }
            else { completion(response.0, response.1, nil) }
            return
        }
        let body: Any
        var defaultStatus = 200
        switch path {
        case "/api/auth/invitations/claim", "/api/auth/device-session", "/api/auth/devices/enroll", "/api/auth/factory-device-enroll":
            let fields = (try? JSONSerialization.jsonObject(with: request.httpBody ?? Data())) as? [String: Any] ?? [:]
            let identity = lock.withLock { accessIdentity }!
            let deviceID = fields["device_id"] as? String ?? ""
            let role: String = lock.withLock {
                if path == "/api/auth/devices/enroll" || path == "/api/auth/factory-device-enroll" { accessDeviceRoles[deviceID] = "owner" }
                if path == "/api/auth/invitations/claim" { accessDeviceRoles[deviceID] = "media" }
                return accessDeviceRoles[deviceID] ?? "media"
            }
            var reply: [String: Any] = ["device_id": deviceID, "role": role,
                "identity": ["frame_id": identity.id.uuidString.lowercased(), "spki_sha256": identity.spkiSHA256.map { String(format: "%02x", $0) }.joined()]]
            if path != "/api/auth/factory-device-enroll" { reply["authenticated"] = true }
            body = reply
        case "/api/auth/invitations":
            let fields = (try? JSONSerialization.jsonObject(with: request.httpBody ?? Data())) as? [String: Any] ?? [:]
            let identity = lock.withLock { accessIdentity }!
            body = ["invitation_id": fields["invitation_id"] ?? "", "expires_at": Date().timeIntervalSince1970 + 300, "role": "media",
                "identity": ["frame_id": identity.id.uuidString.lowercased(), "spki_sha256": identity.spkiSHA256.map { String(format: "%02x", $0) }.joined(), "url": "https://\(host):8443"]]
        case "/api/auth/devices": body = ["devices": []]
        case let value where value.hasPrefix("/api/auth/invitations/") || value.hasPrefix("/api/auth/devices/"):
            body = ["revoked": true]
        case "/api/auth/status", "/api/auth/logout": body = ["authenticated": false, "auth_required": true, "password_change_supported": host != "legacy-frame.local"]
        case "/api/auth/login", "/api/auth/password": body = ["authenticated": true, "auth_required": true, "password_change_supported": host != "legacy-frame.local"]
        case "/api/health": body = ["status": "ok", "version": "0.4.2"]
        case "/api/state": body = ["display": ["model": host, "width": 800, "height": 480, "colors": 6, "is_mock": true], "current": NSNull(), "queue_count": 0, "next_change_at": NSNull()]
        case "/api/display/status":
            let diagnostics = lock.withLock { displayStatus }
            body = diagnostics ?? [:]
            if diagnostics == nil { defaultStatus = 404 }
        case "/api/settings": body = ["change_mode": "daily", "change_hour": 5, "change_interval_minutes": 60, "saturation": 1]
        case "/api/system/update": body = ["current": "0.4.2", "latest": "0.4.3", "update_available": true]
        case "/api/history":
            let query = URLComponents(url: request.url!, resolvingAgainstBaseURL: false)!.queryItems ?? []
            let limit = Int(query.first { $0.name == "limit" }?.value ?? "100")!
            let offset = Int(query.first { $0.name == "offset" }?.value ?? "0")!
            let total = totals[host] ?? 0
            let end = min(total, offset + limit)
            body = offset < end ? (offset..<end).map { index -> [String: Any] in
                ["id": index + 1, "displayed_at": 1780000000, "source": "test", "photo": [
                    "id": "photo-\(index)", "sha256": "digest-\(index)", "original_filename": "\(host).png", "mime": "image/png",
                    "width": 800, "height": 480, "size_bytes": 10, "created_at": 1780000000,
                ]]
            } : []
        default: body = []
        }
        let data = try! JSONSerialization.data(withJSONObject: body)
        if let gate { gate.hold { status in completion(data, status ?? defaultStatus, nil) } }
        else { completion(data, defaultStatus, nil) }
    }
}

private final class StoreURLProtocol: URLProtocol, @unchecked Sendable {
    private static let lock = NSLock()
    nonisolated(unsafe) private static var stubs: [String: StoreStub] = [:]
    private let responseLock = NSLock()
    private var stopped = false
    static func register(_ stub: StoreStub, id: String) { lock.withLock { stubs[id] = stub } }
    static func remove(id: String) { _ = lock.withLock { stubs.removeValue(forKey: id) } }
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        let id = request.value(forHTTPHeaderField: "X-Inky-Store-Test") ?? ""
        guard let stub = Self.lock.withLock({ Self.stubs[id] }) else {
            client?.urlProtocol(self, didFailWithError: URLError(.resourceUnavailable))
            return
        }
        stub.respond(request) { [weak self] data, status, error in
            guard let self, !self.responseLock.withLock({ self.stopped }) else { return }
            if let error { self.client?.urlProtocol(self, didFailWithError: error); return }
            let response = HTTPURLResponse(url: self.request.url!, statusCode: status, httpVersion: "HTTP/1.1",
                                           headerFields: ["Content-Type": "application/json"])!
            self.client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
            self.client?.urlProtocol(self, didLoad: data)
            self.client?.urlProtocolDidFinishLoading(self)
        }
    }

    override func stopLoading() { responseLock.withLock { stopped = true } }
}

@MainActor
private final class LegacySharingProofGate {
    let started = XCTestExpectation(description: "Public proof requested")
    private let verified: VerifiedLegacyTLSEndpoint
    private var continuation: CheckedContinuation<VerifiedLegacyTLSEndpoint, Never>?
    init(_ verified: VerifiedLegacyTLSEndpoint) { self.verified = verified }
    func wait() async -> VerifiedLegacyTLSEndpoint {
        await withCheckedContinuation { continuation in
            self.continuation = continuation
            started.fulfill()
        }
    }
    func release() { continuation?.resume(returning: verified); continuation = nil }
}
