import SwiftUI
import Combine

@MainActor
final class AppStore: ObservableObject {
    @Published private(set) var sessionIdentity = UUID()
    @Published var address = ""
    @Published var authenticated = false
    @Published var connecting = false
    @Published var connected = false
    @Published var refreshing = false
    @Published var busy = false
    @Published var displayBusy = false
    @Published private(set) var localUnlocked = false
    @Published private(set) var unlocking = false
    @Published private(set) var localAuthenticationError: String?
    @Published private(set) var credentialStored = false
    @Published private(set) var credentialStorageError: String?
    @Published private(set) var pairingNeedsCompletion = false
    @Published private(set) var recoveringConnection = false
    @Published private(set) var photoAccessRole: PhotoAccessRole?
    @Published private(set) var photoAccessCanInvite = false
    @Published private(set) var activeInvitation: PhotoAccessInvitation?
    @Published private(set) var accessDevices: [PhotoAccessDeviceSummary] = []
    @Published private(set) var photoAccessBusy = false
    @Published private(set) var photoAccessError: String?
    @Published var factorySetupPresentation: FactorySetupPresentation?
    private var factoryAuthorizationGeneration: UUID?
    private var factoryAttemptGeneration = UUID()
    private var queuedFactoryPresentation: FactorySetupPresentation?
    private enum QueuedConnection {
        case photo(FrameInvitationCode)
        case lan(String)
    }
    private var queuedConnection: QueuedConnection?
    private var connectionDismissalComplete = false
    private var queuedConnectionTask: Task<Void, Never>?
    private var queuedConnectionTaskID = UUID()
    private struct ActiveSceneWaiter {
        let authentication: UUID
        let continuation: CheckedContinuation<Bool, Never>
    }
    private var activeSceneWaiters: [UUID: ActiveSceneWaiter] = [:]
    private let photoAccessVault: PhotoAccessVault
    private let legacyHTTPFixture: Bool
    private let uploadDrafts: PhotoUploadDraftStore
    private let bootstrapRetirementFromLaunch: String?
    private let makePinnedAPI: @MainActor (URL, FrameIdentity) -> InkyAPI
    private let proveLegacyTLS: @MainActor (URL, String) async throws -> VerifiedLegacyTLSEndpoint
    private var legacySharingUpgradeTask: Task<Bool, Never>?
    private var legacySharingUpgradeID = UUID()
    private var selectedPhotoAccess: PhotoAccessSelection?
    private var pendingPhotoAccess: PhotoAccessSelection?
    private var photoAccessOperation = UUID()
    private var fixturePhotoAccess: String?
    @Published var passwordChangeSupported = false
    @Published var bluetoothSupported = false
    @Published var errorMessage: String?
    @Published var notice: String?
    @Published var state: DisplayState?
    @Published private(set) var displayDiagnostics: DisplayDiagnostics?
    private var displayReadError: String?
    @Published var queue: [QueueEntry] = []
    @Published var history: [HistoryEntry] = []
    @Published var settings: FrameSettings?
    @Published var version = "—"
    @Published var availableUpdate: UpdateStatus?
    @Published var updateMessage: String?
    @Published var updating = false
    @Published var hasMoreHistory = false
    @Published var loadingHistory = false
    private(set) var api: InkyAPI?
    private var photoClient: (any FramePhotoClient)? { api }
    let vault: BiometricVault
    private let defaults: UserDefaults
    private let makeAPI: @MainActor (URL) -> InkyAPI
    private let authenticateLocal: @MainActor () async throws -> Void
    private let invalidateAuthentication: @MainActor () -> Void
    private let saveCredential: @MainActor (String, String) throws -> Void
    private let loadCredential: @MainActor (String) async throws -> String
    private let containsCredential: @MainActor (String) -> Bool
    private let authenticationName: @MainActor () -> String
    private let monitorsEvents: Bool
    private var localAuthenticationGeneration = UUID()
    private var credentialTask: Task<String, Error>?
    private var credentialTaskID = UUID()
    private var pendingPairingCredential: (password: String, account: String, generation: UUID)?
    private struct ForgetAuthorization {
        let account: String
        let ownerID: String?
        let generation: UUID
        let authentication: UUID
        let issuedAt: TimeInterval
    }
    private var forgetAuthorization: ForgetAuthorization?
    private let imageCache = NSCache<NSString, UIImage>()
    private var eventsTask: Task<Void, Never>?
    private var pollingTask: Task<Void, Never>?
    private var generation = UUID()
    private var monitoringID: UUID?
    private var refreshID: UUID?
    private var historyRevision = UUID()
    private var pendingClient: InkyAPI?
    @Published private var active = true
    private var requestedRefresh = false
    private var connectionError = false
    private var passwordRotating = false
    private let ownershipVault: OwnershipVault
    private var requestedAdoptionFrameID: UUID?

    init(defaults: UserDefaults = .standard,
         makeAPI: @escaping @MainActor (URL) -> InkyAPI = { InkyAPI(baseURL: $0) },
         vault: BiometricVault = BiometricVault(),
         photoAccessVault: PhotoAccessVault? = nil,
         ownershipVault: OwnershipVault = OwnershipVault(),
         makePinnedAPI: @escaping @MainActor (URL, FrameIdentity) -> InkyAPI = { InkyAPI(baseURL: $0, trustedIdentity: $1) },
         proveLegacyTLS: (@MainActor (URL, String) async throws -> VerifiedLegacyTLSEndpoint)? = nil,
         authenticateLocal: (@MainActor () async throws -> Void)? = nil,
         invalidateAuthentication: (@MainActor () -> Void)? = nil,
         saveCredential: (@MainActor (String, String) throws -> Void)? = nil,
         loadCredential: (@MainActor (String) async throws -> String)? = nil,
         containsCredential: (@MainActor (String) -> Bool)? = nil,
         authenticationName: (@MainActor () -> String)? = nil,
         monitorsEvents: Bool = true, testingLegacyHTTP: Bool = false,
         uploadDrafts: PhotoUploadDraftStore = PhotoUploadDraftStore()) {
        self.defaults = defaults
        self.makeAPI = makeAPI
        self.vault = vault
        self.ownershipVault = ownershipVault
        let deviceAuthentication = LocalDeviceAuthentication()
        self.photoAccessVault = photoAccessVault ?? PhotoAccessVault(context: { deviceAuthentication.context })
        self.makePinnedAPI = makePinnedAPI
        self.proveLegacyTLS = proveLegacyTLS ?? { try await LegacyTLSProofClient().prove(endpoint: $0, bootstrapPassword: $1) }
        self.authenticateLocal = authenticateLocal ?? { try await deviceAuthentication.authenticate() }
        self.invalidateAuthentication = invalidateAuthentication ?? { deviceAuthentication.invalidate() }
        self.saveCredential = saveCredential ?? { try vault.save(password: $0, address: $1, context: deviceAuthentication.context) }
        self.loadCredential = loadCredential ?? { try await vault.load(address: $0, context: deviceAuthentication.context) }
        self.containsCredential = containsCredential ?? { vault.contains(address: $0) }
        self.authenticationName = authenticationName ?? { deviceAuthentication.name }
        self.monitorsEvents = monitorsEvents
        self.uploadDrafts = uploadDrafts
        // Retire only after a later launch observes the persisted selection and
        // reopens its protected device session. Pairing itself leaves the old QR usable.
        bootstrapRetirementFromLaunch = defaults.string(forKey: "pendingBootstrapRetirement")
        #if DEBUG
        let arguments = ProcessInfo.processInfo.arguments
        legacyHTTPFixture = testingLegacyHTTP || (arguments.contains("--uitesting") && arguments.contains("--legacy-login-fixture"))
        #else
        legacyHTTPFixture = false
        #endif
        #if DEBUG
        let args = ProcessInfo.processInfo.arguments
        if args.contains("--uitesting") {
            defaults.removeObject(forKey: "frameAddress")
            defaults.removeObject(forKey: "biometricEnabled")
            defaults.removeObject(forKey: "frameOwnerID")
        }
        #endif
        address = defaults.string(forKey: "frameAddress") ?? ""
        #if DEBUG
        if let index = args.firstIndex(of: "--frame-address"), args.indices.contains(index + 1) { address = args[index + 1] }
        if args.contains("--uitesting"), let index = args.firstIndex(of: "--local-auth-fixture"),
           args.indices.contains(index + 1), ["locked", "failure", "recoverable"].contains(args[index + 1]) {
            // Explicit inert UI fixture: represents a locked saved frame, without a credential or network request.
            credentialStored = true
            if args[index + 1] == "recoverable" {
                address = "http://192.168.1.120:8000"
                defaults.set(address, forKey: "frameAddress")
            }
        } else { credentialStored = self.containsCredential(credentialAccount) }
        #else
        credentialStored = self.containsCredential(credentialAccount)
        #endif
        if defaults.string(forKey: "credentialStorageFailedAccount") == credentialAccount {
            credentialStored = false
            pairingNeedsCompletion = true
            credentialStorageError = String(localized: "L’association n’est pas finalisée : aucun identifiant de cette connexion n’a été confirmé. Scannez à nouveau le QR du cadre pour terminer l’association.")
        }
        if let data = defaults.data(forKey: "photoAccessSelection"),
           let selection = try? JSONDecoder().decode(PhotoAccessSelection.self, from: data),
           (try? PhotoAccessValidation.origin(selection.endpoint)) != nil {
            selectedPhotoAccess = selection
            photoAccessRole = selection.role
            credentialStored = self.photoAccessVault.contains(account: selection.account)
        }
        if let data = defaults.data(forKey: "photoAccessPending"),
           let selection = try? JSONDecoder().decode(PhotoAccessSelection.self, from: data) {
            pendingPhotoAccess = selection
            if !hasSavedFrame && selectedPhotoAccess == nil { credentialStored = self.photoAccessVault.contains(account: selection.account) }
        }
        #if DEBUG
        if args.contains("--uitesting"), let index = args.firstIndex(of: "--photo-access-fixture"), args.indices.contains(index + 1) {
            configurePhotoAccessFixture(args[index + 1])
        }
        #endif
        imageCache.totalCostLimit = 24 * 1024 * 1024
    }

    var hasSavedFrame: Bool { defaults.string(forKey: "frameAddress") != nil }
    var localAuthenticationName: String { authenticationName() }
    var hasAdoptedFrame: Bool { defaults.string(forKey: "frameOwnerID") != nil }
    var panelWidth: Int { state?.display.width ?? 800 }
    var panelHeight: Int { state?.display.height ?? 480 }
    var canMutate: Bool { localUnlocked && active && !unlocking && !connecting && !recoveringConnection && !pairingNeedsCompletion && !photoAccessBusy && authenticated && connected && !busy && !updating }
    var photoAccessDeviceID: UUID? { selectedPhotoAccess?.deviceID ?? (fixturePhotoAccess != nil ? UUID(uuidString: fixturePhotoAccess?.hasPrefix("media") == true ? "bbbbbbbb-cccc-4ddd-8eee-ffffffffffff" : "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee") : nil) }
    var isMediaPhotoAccess: Bool { selectedPhotoAccess?.role == .media || photoAccessRole == .media }
    var hasIndividualPhotoAccess: Bool { selectedPhotoAccess != nil }
    var canAdminister: Bool { authenticated && photoAccessRole != .media }
    var needsSecureSharingUpgrade: Bool {
        selectedPhotoAccess == nil && photoAccessRole == nil && !hasAdoptedFrame && api?.pinnedIdentity == nil &&
        api?.baseURL.scheme == "http"
    }
    var canShareAccess: Bool {
        localUnlocked && active && authenticated && connected && !pairingNeedsCompletion && (photoAccessRole != .media || photoAccessCanInvite) &&
        (api?.pinnedIdentity != nil || (needsSecureSharingUpgrade && credentialStored &&
            api?.baseURL.absoluteString == address && defaults.string(forKey: "frameAddress") == address))
    }
    var displayIssue: String? { displayDiagnostics?.issue ?? displayReadError }
    var canDisplay: Bool { canMutate && state != nil && displayIssue == nil }

    private func authorizeLocally(force: Bool = false, grantContent: Bool = true) async -> Bool {
        if localUnlocked && !force { return true }
        let attempt = localAuthenticationGeneration
        localAuthenticationError = nil
        do {
            #if DEBUG
            let args = ProcessInfo.processInfo.arguments
            if args.contains("--uitesting"), let index = args.firstIndex(of: "--local-auth-fixture"), args.indices.contains(index + 1) {
                guard ["success", "recoverable"].contains(args[index + 1]) else { throw VaultError.cancelled }
            } else { try await authenticateLocal() }
            #else
            try await authenticateLocal()
            #endif
            guard attempt == localAuthenticationGeneration, !Task.isCancelled else { return false }
            localUnlocked = grantContent
            return true
        } catch {
            guard attempt == localAuthenticationGeneration else { return false }
            localUnlocked = false
            localAuthenticationError = error.localizedDescription
            return false
        }
    }

    /// A successful system prompt can precede the window's activation notification.
    /// Keep its authorization while inactive, but never admit work on a timer.
    private func waitForActiveScene(authentication: UUID) async -> Bool {
        guard authentication == localAuthenticationGeneration, !Task.isCancelled else { return false }
        while !active {
            let id = UUID()
            let admitted = await withTaskCancellationHandler(operation: {
                await withCheckedContinuation { continuation in
                    guard authentication == localAuthenticationGeneration, !Task.isCancelled else {
                        continuation.resume(returning: false)
                        return
                    }
                    if active { continuation.resume(returning: true) }
                    else { activeSceneWaiters[id] = ActiveSceneWaiter(authentication: authentication, continuation: continuation) }
                }
            }, onCancel: { [weak self] in
                Task { @MainActor in self?.finishActiveSceneWaiter(id, admitted: false) }
            })
            guard admitted, authentication == localAuthenticationGeneration, !Task.isCancelled else { return false }
        }
        return authentication == localAuthenticationGeneration && !Task.isCancelled
    }

    private func finishActiveSceneWaiter(_ id: UUID, admitted: Bool) {
        guard let waiter = activeSceneWaiters.removeValue(forKey: id) else { return }
        waiter.continuation.resume(returning: admitted && waiter.authentication == localAuthenticationGeneration)
    }

    private func finishActiveSceneWaiters(admitted: Bool) {
        for id in Array(activeSceneWaiters.keys) { finishActiveSceneWaiter(id, admitted: admitted) }
    }

    /// A local lock never logs out or discards a usable in-memory network session.
    func lock() {
        queuedConnection = nil
        connectionDismissalComplete = false
        queuedConnectionTaskID = UUID()
        queuedConnectionTask?.cancel()
        queuedConnectionTask = nil
        factoryAuthorizationGeneration = nil
        factoryAttemptGeneration = UUID()
        queuedFactoryPresentation = nil
        if var presentation = factorySetupPresentation {
            presentation.code = nil
            factorySetupPresentation = presentation
        }
        legacySharingUpgradeTask?.cancel()
        legacySharingUpgradeTask = nil
        legacySharingUpgradeID = UUID()
        recoveringConnection = false
        activeInvitation = nil
        accessDevices = []
        photoAccessOperation = UUID()
        photoAccessBusy = false
        forgetAuthorization = nil
        localAuthenticationGeneration = UUID()
        finishActiveSceneWaiters(admitted: false)
        invalidateAuthentication()
        credentialTask?.cancel()
        credentialTask = nil
        credentialTaskID = UUID()
        pendingPairingCredential = nil
        if pairingNeedsCompletion {
            credentialStorageError = String(localized: "L’association n’est pas finalisée et son identifiant temporaire n’est plus disponible. Scannez à nouveau le QR pour terminer l’association.")
        }
        localUnlocked = false
        unlocking = false
        localAuthenticationError = nil
        generation = UUID()
        stopMonitoring()
        refreshing = false
        refreshID = nil
        requestedRefresh = false
        loadingHistory = false
        busy = false
        displayBusy = false
        imageCache.removeAllObjects()
        pendingClient?.clearSession()
        pendingClient = nil
        connecting = false
    }

    func unlock() async {
        guard !unlocking, !connecting else { return }
        let attempt = localAuthenticationGeneration
        unlocking = true
        defer {
            if attempt == localAuthenticationGeneration {
                if Task.isCancelled { lock() }
                else { unlocking = false }
            }
        }
        guard await authorizeLocally() else { return }
        // Face ID/passcode can finish before UIKit reactivates this window.
        // Resume this same unlock on activation instead of requiring another tap.
        guard await waitForActiveScene(authentication: attempt), localUnlocked else { return }
        if !legacyHTTPFixture, selectedPhotoAccess == nil, hasSavedFrame,
           let endpoint = try? FrameAddress.parse(address), endpoint.scheme == "http" {
            do {
                let password = try await readCredential(credentialAccount)
                guard await waitForActiveScene(authentication: attempt), localUnlocked else { return }
                guard await pairOverVerifiedHTTPS(endpoint: endpoint, password: password, attempt: attempt) else {
                    if attempt == localAuthenticationGeneration {
                        localUnlocked = false
                        localAuthenticationError = errorMessage
                        invalidateAuthentication()
                    }
                    return
                }
            } catch {
                guard attempt == localAuthenticationGeneration, !Task.isCancelled else { return }
                localUnlocked = false
                localAuthenticationError = error.localizedDescription
                invalidateAuthentication()
            }
            return
        }
        if authenticated, api != nil {
            // Cookie-only sessions remain usable. Do not require a lost QR or force logout.
            credentialStored = selectedPhotoAccess.map { photoAccessVault.contains(account: $0.account) } ??
                (containsCredential(credentialAccount) && defaults.string(forKey: "credentialStorageFailedAccount") != credentialAccount)
            if !credentialStored && credentialStorageError == nil {
                credentialStorageError = String(localized: "La connexion actuelle est conservée. Cet iPhone n’a pas encore d’identifiant enregistré pour les prochaines connexions.")
            }
            startMonitoring()
            await refresh()
            if let api { await retireBootstrapIfPending(on: api) }
            return
        }
        if let selection = selectedPhotoAccess ?? (!hasSavedFrame ? pendingPhotoAccess : nil) {
            await restorePhotoAccess(selection, attempt: attempt)
            return
        }
        guard hasSavedFrame || credentialStored else { return }
        do {
            let password = try await readCredential(credentialAccount)
            guard await waitForActiveScene(authentication: attempt), localUnlocked else { return }
            credentialStored = true
            await connect(password: password, at: nil, savePassword: false)
        } catch {
            guard attempt == localAuthenticationGeneration else { return }
            localUnlocked = false
            invalidateAuthentication()
            credentialStored = containsCredential(credentialAccount)
            localAuthenticationError = error.localizedDescription
        }
    }

    /// Voluntary legacy-LAN recovery never reads, removes, or logs out the old credential.
    func beginConnectionRecovery() async {
        guard !hasAdoptedFrame, selectedPhotoAccess == nil, !pairingNeedsCompletion, !unlocking, !connecting, !busy, !displayBusy, !updating else { return }
        let attempt = localAuthenticationGeneration
        unlocking = true
        defer { if attempt == localAuthenticationGeneration { unlocking = false } }
        guard await authorizeLocally(force: true) else { return }
        guard attempt == localAuthenticationGeneration, !Task.isCancelled else { return }
        generation = UUID()
        forgetAuthorization = nil
        stopMonitoring()
        refreshing = false
        refreshID = nil
        requestedRefresh = false
        loadingHistory = false
        recoveringConnection = true
        errorMessage = nil
    }

    func cancelConnectionRecovery() {
        guard recoveringConnection else { return }
        // lock() cancels only the candidate. The current api, cookie and selected account remain intact.
        lock()
    }

    /// An adopted frame can be forgotten only after a fresh local authorization and an explicit UI confirmation.
    func authorizeForgetCurrentFrame() async -> Bool {
        guard hasSavedFrame, !recoveringConnection, !unlocking, !connecting, !busy, !displayBusy, !updating else { return false }
        let account = credentialAccount
        let selectedOwner = defaults.string(forKey: "frameOwnerID")
        let epoch = generation
        let attempt = localAuthenticationGeneration
        forgetAuthorization = nil
        unlocking = true
        defer { if attempt == localAuthenticationGeneration { unlocking = false } }
        guard await authorizeLocally(force: true, grantContent: false) else { return false }
        guard epoch == generation, attempt == localAuthenticationGeneration,
              account == credentialAccount, selectedOwner == defaults.string(forKey: "frameOwnerID"),
              !Task.isCancelled else { return false }
        forgetAuthorization = ForgetAuthorization(account: account, ownerID: selectedOwner,
            generation: epoch, authentication: attempt, issuedAt: ProcessInfo.processInfo.systemUptime)
        return true
    }

    func cancelForgetCurrentFrame() {
        guard forgetAuthorization != nil else { return }
        forgetAuthorization = nil
        lock()
    }

    func forgetCurrentFrameAfterConfirmation() async {
        guard let authorization = forgetAuthorization else { return }
        forgetAuthorization = nil
        guard active, !unlocking, !connecting,
              authorization.generation == generation,
              authorization.authentication == localAuthenticationGeneration,
              authorization.account == credentialAccount,
              authorization.ownerID == defaults.string(forKey: "frameOwnerID"),
              ProcessInfo.processInfo.systemUptime - authorization.issuedAt < 60 else { return }
        await finishLogout(forget: true)
    }

    private func readCredential(_ account: String) async throws -> String {
        let identifier = UUID()
        let task = Task { try Task.checkCancellation(); return try await loadCredential(account) }
        credentialTaskID = identifier
        credentialTask = task
        defer { if credentialTaskID == identifier { credentialTask = nil } }
        return try await withTaskCancellationHandler(operation: { try await task.value }, onCancel: { task.cancel() })
    }

    private var credentialAccount: String {
        if let selection = selectedPhotoAccess { return selection.account }
        if let id = defaults.string(forKey: "frameOwnerID") { return "inky-frame:" + id }
        return address
    }

    private func connectionClient(_ url: URL) throws -> InkyAPI {
        guard let selected = defaults.string(forKey: "frameOwnerID") else { return makeAPI(url) }
        guard let id = UUID(uuidString: selected), let owner = try ownershipVault.load(id: id), owner.state == .claimed else {
            throw OwnershipVaultError.missing
        }
        // An adopted frame never falls back to a password sent over HTTP, even
        // when the user manually edits its locator or the LAN changes.
        try FrameTrustPolicy(identity: owner.identity).validateHTTPS(url)
        return InkyAPI(baseURL: url, owner: owner)
    }

    func beginBluetoothAdoption() async throws {
        guard canAdminister, canMutate, let api else { throw APIError.unauthorized }
        let epoch = generation
        let id = try await api.beginBluetoothAdoption()
        guard epoch == generation else { throw CancellationError() }
        requestedAdoptionFrameID = id
    }

    func finishBluetoothSetup(endpoint: URL, owner: OwnershipRecord) async {
        guard !isMediaPhotoAccess, localUnlocked, !pairingNeedsCompletion else { return }
        if let selected = selectedPhotoAccess {
            await finishPhotoAccessWiFi(endpoint: endpoint, owner: owner, selected: selected)
            return
        }
        let epoch = generation
        do {
            try FrameTrustPolicy(identity: owner.identity).validateHTTPS(endpoint)
            let oldAccount = credentialAccount
            let password: String
            do { password = try await readCredential(oldAccount) }
            catch {
                guard epoch == generation, localUnlocked else { return }
                notice = String(localized: "Le Wi-Fi est configuré. L’accès actuel à vos photos est conservé ; son transfert sécurisé n’a pas été effectué.")
                return
            }
            guard epoch == generation, localUnlocked, !Task.isCancelled else { return }
            // Validate the new photo connection before changing the current cookie, pin or locator.
            let candidate = InkyAPI(baseURL: endpoint, owner: owner)
            let status = try await candidate.authStatus()
            guard epoch == generation, localUnlocked, !Task.isCancelled else { candidate.clearSession(); return }
            if !status.authenticated {
                let reply = try await candidate.login(password: password)
                guard reply.authenticated else { candidate.clearSession(); throw APIError.unauthorized }
            }
            guard epoch == generation, localUnlocked, !Task.isCancelled else { candidate.clearSession(); return }
            let newAccount = "inky-frame:" + owner.id.uuidString.lowercased()
            do { try saveCredential(password, newAccount) }
            catch {
                candidate.clearSession()
                credentialStorageError = String(localized: "Le Wi-Fi est configuré, mais l’identifiant sécurisé n’a pas pu être transféré. L’accès actuel à vos photos est conservé.")
                return
            }
            _ = try ownershipVault.markClaimed(id: owner.id, endpoint: endpoint)
            resetSession()
            let committedEpoch = generation
            defaults.set(owner.id.uuidString.lowercased(), forKey: "frameOwnerID")
            address = endpoint.absoluteString
            defaults.set(address, forKey: "frameAddress")
            api = candidate
            authenticated = true
            credentialStored = true
            credentialStorageError = nil
            defaults.removeObject(forKey: "credentialStorageFailedAccount")
            passwordChangeSupported = status.authRequired && status.passwordChangeSupported == true
            await refresh()
            guard committedEpoch == generation, localUnlocked, authenticated, credentialStored, credentialAccount == newAccount else { return }
            startMonitoring()
            if oldAccount != newAccount { try? vault.remove(address: oldAccount) }
        } catch {
            guard epoch == generation, localUnlocked else { return }
            // A failed candidate must never sign the established photo session out.
            errorMessage = String(localized: "Le Wi-Fi est configuré. La nouvelle connexion photo n’a pas pu être vérifiée ; la connexion précédente est conservée.")
        }
    }

    var hasPendingFactorySetup: Bool {
        ((try? ownershipVault.allRecords()) ?? []).contains { $0.isFactorySetupPending }
    }

    func presentFactorySetup(_ code: FrameBootstrapCode) {
        guard !connecting, !unlocking, !photoAccessBusy, !busy, !displayBusy, !updating else { return }
        factorySetupPresentation = FactorySetupPresentation(code: code, owner: nil)
    }

    func queueFactorySetup(_ code: FrameBootstrapCode) {
        queuedConnection = nil
        connectionDismissalComplete = false
        queuedFactoryPresentation = FactorySetupPresentation(code: code, owner: nil)
    }

    func queueFactoryOwner(_ owner: OwnershipRecord) {
        guard owner.isFactory else { return }
        queuedConnection = nil
        connectionDismissalComplete = false
        queuedFactoryPresentation = FactorySetupPresentation(code: nil, owner: owner)
    }

    /// Scanned secrets stay in RAM until every presenting sheet has dismissed.
    func queuePhotoInvitation(_ code: FrameInvitationCode) {
        queuedFactoryPresentation = nil
        queuedConnection = .photo(code)
        connectionDismissalComplete = false
        localAuthenticationError = nil
        photoAccessError = nil
        errorMessage = nil
    }

    func queueLANLoginCode(_ text: String) {
        queuedFactoryPresentation = nil
        queuedConnection = .lan(text)
        connectionDismissalComplete = false
    }

    /// Only the final scanner/guide dismissal is allowed to release a queued scan.
    func completeQueuedConnection() {
        connectionDismissalComplete = true
        startQueuedConnectionIfReady()
    }

    private func startQueuedConnectionIfReady() {
        guard active, connectionDismissalComplete, queuedConnectionTask == nil else { return }
        guard let queued = queuedConnection else {
            connectionDismissalComplete = false
            presentQueuedFactorySetup()
            return
        }
        guard !connecting, !unlocking, !photoAccessBusy, !busy, !displayBusy, !updating else { return }
        // Consume before scheduling so repeated onDismiss/activation callbacks cannot replay it.
        queuedConnection = nil
        connectionDismissalComplete = false
        let id = UUID()
        let authentication = localAuthenticationGeneration
        queuedConnectionTaskID = id
        queuedConnectionTask = Task { [weak self] in
            guard let self else { return }
            defer { if self.queuedConnectionTaskID == id { self.queuedConnectionTask = nil } }
            guard self.queuedConnectionTaskID == id, authentication == self.localAuthenticationGeneration,
                  !Task.isCancelled else { return }
            guard await self.waitForActiveScene(authentication: authentication) else { return }
            switch queued {
            case .photo(let code): await self.claimInvitation(code)
            case .lan(let text): await self.loginFromLANQRCode(text)
            }
        }
    }

    func presentQueuedFactorySetup() {
        guard active, let queued = queuedFactoryPresentation else { return }
        queuedFactoryPresentation = nil
        factorySetupPresentation = queued
    }

    func resumeFactorySetup() {
        guard !connecting, !unlocking, !photoAccessBusy, !busy, !displayBusy, !updating else { return }
        let pending = ((try? ownershipVault.allRecords()) ?? []).filter { $0.isFactorySetupPending }
        guard !pending.isEmpty else { return }
        factorySetupPresentation = FactorySetupPresentation(code: nil, owner: pending.count == 1 ? pending[0] : nil)
    }

    func authorizeFactorySetup() async -> Bool {
        if factoryAuthorizationGeneration == localAuthenticationGeneration, localUnlocked, active { return true }
        guard !connecting, !unlocking, !photoAccessBusy, !busy, !displayBusy, !updating else { return false }
        let attempt = localAuthenticationGeneration
        let factoryAttempt = factoryAttemptGeneration
        unlocking = true
        defer { if attempt == localAuthenticationGeneration { unlocking = false } }
        guard await authorizeLocally(force: true), attempt == localAuthenticationGeneration,
              factoryAttempt == factoryAttemptGeneration else { return false }
        let deadline = ProcessInfo.processInfo.systemUptime + 2
        while !active {
            guard attempt == localAuthenticationGeneration, factoryAttempt == factoryAttemptGeneration, !Task.isCancelled,
                  ProcessInfo.processInfo.systemUptime < deadline else { return false }
            do { try await Task.sleep(nanoseconds: 50_000_000) } catch { return false }
        }
        guard attempt == localAuthenticationGeneration, factoryAttempt == factoryAttemptGeneration,
              localUnlocked, !Task.isCancelled else { return false }
        factoryAuthorizationGeneration = attempt
        return true
    }

    func cancelFactorySetup() {
        factoryAuthorizationGeneration = nil
        factoryAttemptGeneration = UUID()
        cancelPhotoAccessOperation()
    }

    /// The candidate never changes the selected frame until protected PHOTO
    /// storage, enrollment and a device-session have all succeeded.
    func finishFactorySetup(endpoint: URL, owner: OwnershipRecord, status: FactorySetupStatus) async -> Bool {
        guard factoryAuthorizationGeneration == localAuthenticationGeneration, localUnlocked, active,
              !photoAccessBusy, !connecting, !busy, !displayBusy, !updating else { return false }
        let epoch = generation
        let authentication = localAuthenticationGeneration
        let operation = UUID()
        photoAccessOperation = operation
        photoAccessBusy = true
        photoAccessError = nil
        var candidate: InkyAPI?
        var committed = false
        defer {
            if !committed { candidate?.clearSession() }
            if photoAccessOperation == operation { photoAccessBusy = false; pendingClient = nil }
        }
        func current() -> Bool {
            photoOperationValid(epoch, operation) && authentication == localAuthenticationGeneration &&
                factoryAuthorizationGeneration == authentication
        }
        do {
            guard owner.isFactory, owner.state == .claimed, status.state == .complete,
                  status.nextStep == .photoEnroll, status.completionID != nil,
                  status.frameID == owner.identity.id, status.ownerID == owner.ownerID,
                  status.claimRequestID == owner.claimRequestID,
                  status.normalIdentity?.identity == owner.identity,
                  status.httpsOrigin?.absoluteString == endpoint.absoluteString else { throw PhotoAccessError.identityMismatch }
            try FrameTrustPolicy(identity: owner.identity).validateHTTPS(endpoint)
            let draftAccount = "factory:" + owner.id.uuidString.lowercased() + ":" + owner.claimRequestID.uuidString.lowercased()
            let canonicalAccount = PhotoAccessSelection.account(identity: owner.identity, invitationID: nil)
            let saved: PhotoAccessCredential?
            if photoAccessVault.contains(account: draftAccount) {
                saved = try await photoAccessVault.loadCredential(account: draftAccount)
            } else if photoAccessVault.contains(account: canonicalAccount) {
                let existing = try await photoAccessVault.loadCredential(account: canonicalAccount)
                saved = existing.requestID == owner.claimRequestID ? existing : nil
            } else { saved = nil }
            guard await waitForLegacySharingForeground(epoch: epoch, operation: operation), current() else { return false }
            let credential: PhotoAccessCredential
            if let saved {
                guard saved.identity == owner.identity, saved.expectedRole == .owner, saved.invitationID == nil,
                      saved.requestID == owner.claimRequestID, saved.deviceID != owner.ownerID,
                      saved.deviceToken != owner.ownerTokenHex else { throw PhotoAccessError.identityMismatch }
                credential = try PhotoAccessCredential(identity: saved.identity, endpoint: endpoint,
                    deviceID: saved.deviceID, deviceToken: saved.deviceToken, requestID: saved.requestID, expectedRole: .owner)
            } else {
                credential = try PhotoAccessCredential(identity: owner.identity, endpoint: endpoint, deviceID: UUID(),
                    deviceToken: PhotoAccessValidation.randomToken(), requestID: owner.claimRequestID, expectedRole: .owner)
            }
            // Separate protected draft: never overwrite an older selected PHOTO credential here.
            try photoAccessVault.save(credential, account: draftAccount)
            guard current() else { return false }
            let pinned = makePinnedAPI(endpoint, owner.identity)
            candidate = pinned; pendingClient = pinned
            try await FactoryPhotoEnrollment.enroll(credential, api: pinned, owner: owner, setupOperationID: status.operationID)
            guard current() else { return false }
            let session = try await PhotoAccessClient(api: pinned, identity: owner.identity).openSession(credential)
            guard current() else { return false }
            pendingClient = nil
            try commitPhotoAccess(credential, client: pinned, canInvite: session.canInvite)
            defaults.set(owner.id.uuidString.lowercased(), forKey: "frameOwnerID")
            committed = true
            photoAccessBusy = false
            try? photoAccessVault.remove(account: draftAccount)
            let committedEpoch = generation
            await refresh()
            guard committedEpoch == generation, localUnlocked, active, authenticated, api === pinned else { return false }
            startMonitoring()
            return true
        } catch {
            guard current(), !(error is CancellationError), (error as? URLError)?.code != .cancelled else { return false }
            photoAccessError = String(localized: "La configuration du cadre est conservée. L’accès photo n’a pas pu être confirmé ; votre accès précédent est conservé.")
            return false
        }
    }

    var canScanLANLoginCode: Bool {
        (recoveringConnection || !authenticated || (pairingNeedsCompletion && pendingPairingCredential == nil)) && !connecting && !unlocking && !busy && defaults.string(forKey: "frameOwnerID") == nil
    }

    /// The QR is the only public login input. Local authentication precedes use and protected storage.
    func loginFromLANQRCode(_ text: String) async {
        guard (recoveringConnection || !authenticated || (pairingNeedsCompletion && pendingPairingCredential == nil)), !connecting, !unlocking, !busy else { return }
        guard defaults.string(forKey: "frameOwnerID") == nil else {
            errorMessage = LANLoginCodeError.adoptedFrame.localizedDescription
            return
        }
        let code: FrameLANLoginCode
        do { code = try FrameLANLoginCode.parse(text) }
        catch { errorMessage = LANLoginCodeError.invalidCode.localizedDescription; return }
        if authenticated && pairingNeedsCompletion && code.endpoint.absoluteString != address {
            errorMessage = String(localized: "Scannez le QR du cadre dont l’association est en cours.")
            return
        }
        let attempt = localAuthenticationGeneration
        unlocking = true
        defer { if attempt == localAuthenticationGeneration { unlocking = false } }
        guard await authorizeLocally() else { return }
        guard await waitForActiveScene(authentication: attempt), localUnlocked else {
            if attempt == localAuthenticationGeneration {
                localUnlocked = false
                invalidateAuthentication()
            }
            return
        }
        #if DEBUG
        if legacyHTTPFixture {
            if recoveringConnection { await connectRecovery(code) }
            else { await connect(password: code.password, at: code.endpoint, savePassword: true) }
            return
        }
        #endif
        _ = await pairOverVerifiedHTTPS(endpoint: code.endpoint, password: code.password, attempt: attempt)
    }

    func cancelLogin() {
        if photoAccessBusy && connecting { lock(); return }
        if recoveringConnection { cancelConnectionRecovery(); return }
        guard connecting else { return }
        resetSession()
        lock()
    }

    #if DEBUG
    /// Synthetic tests retain their loopback contract; Release exposes only QR and local unlock.
    func login(password: String, rememberBiometric: Bool? = nil) async {
        guard !unlocking, !connecting else { return }
        let attempt = localAuthenticationGeneration
        unlocking = true
        defer { if attempt == localAuthenticationGeneration { unlocking = false } }
        guard await authorizeLocally() else { return }
        await connect(password: password, at: nil, savePassword: rememberBiometric == true)
    }
    #endif

    private func connect(password: String, at endpoint: URL?, savePassword: Bool) async {
        guard localUnlocked, !connecting, selectedPhotoAccess == nil else { return }
        resetSession()
        let epoch = generation
        connecting = true
        errorMessage = nil
        defer {
            if epoch == generation { connecting = false; pendingClient = nil }
        }
        do {
            let url = try endpoint ?? FrameAddress.parse(address)
            guard url.scheme == "https" || legacyHTTPFixture else { throw PhotoAccessError.trustedHTTPSRequired }
            let normalized = url.absoluteString
            let credentialAddress = defaults.string(forKey: "frameOwnerID").map { "inky-frame:" + $0 } ?? normalized
            let client = try connectionClient(url)
            pendingClient = client
            let status = try await client.authStatus()
            guard epoch == generation, localUnlocked, !Task.isCancelled else { return }
            if !status.authenticated {
                let response = try await client.login(password: password)
                guard epoch == generation, localUnlocked, !Task.isCancelled else { return }
                guard response.authenticated else { throw APIError.unauthorized }
            }
            // Never retain an unvalidated QR, and never represent a failed save as durable pairing.
            if savePassword && status.authRequired {
                do {
                    try saveCredential(password, credentialAddress)
                    credentialStored = true
                    pairingNeedsCompletion = false
                    pendingPairingCredential = nil
                    credentialStorageError = nil
                    defaults.removeObject(forKey: "credentialStorageFailedAccount")
                } catch {
                    credentialStored = false
                    pairingNeedsCompletion = true
                    pendingPairingCredential = (password, credentialAddress, epoch)
                    defaults.set(credentialAddress, forKey: "credentialStorageFailedAccount")
                    credentialStorageError = String(localized: "L’association reste à finaliser : l’identifiant n’a pas pu être enregistré. Réessayez pour pouvoir envoyer vos photos.")
                }
            } else {
                credentialStored = containsCredential(credentialAddress) && defaults.string(forKey: "credentialStorageFailedAccount") != credentialAddress
            }
            stopMonitoring()
            api?.clearSession()
            api = client
            pendingClient = nil
            address = normalized
            defaults.set(address, forKey: "frameAddress")
            authenticated = true
            passwordChangeSupported = status.authRequired && status.passwordChangeSupported == true
            connected = false
            imageCache.removeAllObjects()
            await refresh()
            guard epoch == generation else { return }
            if Task.isCancelled { resetSession(); lock(); return }
            guard localUnlocked else { return }
            // Keep a successfully authenticated session even when its first metadata refresh fails.
            if connected { bluetoothSupported = await client.bluetoothSupported() }
            guard epoch == generation else { return }
            if Task.isCancelled { resetSession(); lock(); return }
            guard localUnlocked else { return }
            startMonitoring()
        } catch { if epoch == generation { handle(error) } }
    }

    #if DEBUG
    private func connectRecovery(_ code: FrameLANLoginCode) async {
        guard recoveringConnection, localUnlocked, !hasAdoptedFrame, !connecting else { return }
        let epoch = generation
        connecting = true
        errorMessage = nil
        let candidate = makeAPI(code.endpoint)
        pendingClient = candidate
        var committed = false
        defer {
            if !committed { candidate.clearSession() }
            if epoch == generation { connecting = false; pendingClient = nil }
        }
        do {
            let status = try await candidate.authStatus()
            guard epoch == generation, recoveringConnection, localUnlocked, !Task.isCancelled else { return }
            if !status.authenticated {
                let response = try await candidate.login(password: code.password)
                guard response.authenticated else { throw APIError.unauthorized }
            }
            guard epoch == generation, recoveringConnection, localUnlocked, !Task.isCancelled else { return }
            let account = code.endpoint.absoluteString
            try saveCredential(code.password, account)
            guard epoch == generation, recoveringConnection, localUnlocked, !Task.isCancelled else { return }
            // Only a validated, protected replacement changes the selected connection.
            pendingClient = nil
            resetSession()
            sessionIdentity = UUID()
            api = candidate
            committed = true
            address = account
            defaults.set(account, forKey: "frameAddress")
            defaults.removeObject(forKey: "credentialStorageFailedAccount")
            authenticated = true
            credentialStored = true
            credentialStorageError = nil
            passwordChangeSupported = status.authRequired && status.passwordChangeSupported == true
            let committedEpoch = generation
            await refresh()
            guard committedEpoch == generation, localUnlocked, authenticated else { return }
            bluetoothSupported = await candidate.bluetoothSupported()
            guard committedEpoch == generation, localUnlocked, authenticated else { return }
            startMonitoring()
        } catch {
            guard epoch == generation, recoveringConnection, localUnlocked else { return }
            // Never route candidate errors through handle(), which could sign the old session out.
            errorMessage = String(localized: "La nouvelle connexion n’a pas pu être finalisée. L’ancien accès est conservé. ") + error.localizedDescription
        }
    }

    #endif

    var canRetryCredentialStorage: Bool {
        localUnlocked && active && authenticated && !unlocking && !busy &&
        pendingPairingCredential?.account == credentialAccount &&
        pendingPairingCredential?.generation == generation
    }

    /// Retry only protected storage. The existing network session is never logged in or replayed.
    func retryCredentialStorage() async {
        guard canRetryCredentialStorage, let credential = pendingPairingCredential else { return }
        busy = true
        defer { busy = false }
        do {
            try saveCredential(credential.password, credential.account)
            credentialStored = true
            pairingNeedsCompletion = false
            pendingPairingCredential = nil
            credentialStorageError = nil
            defaults.removeObject(forKey: "credentialStorageFailedAccount")
        } catch {
            credentialStored = false
            credentialStorageError = String(localized: "L’enregistrement sécurisé n’a pas abouti. L’association reste à finaliser ; vous pouvez réessayer.")
        }
    }

    /// Rotate exactly once. A lost response must not replay this mutation or
    /// silently restore an old Keychain password after the frame has changed it.
    func changePassword(current: String, new: String) async -> PasswordChangeResult {
        guard canMutate, !displayBusy, passwordChangeSupported, let api else {
            return .failure(String(localized: "Reconnectez-vous au cadre avant de modifier son mot de passe."))
        }
        stopMonitoring()
        // Retire in-flight refreshes and thumbnails using the previous session.
        generation = UUID()
        let epoch = generation
        passwordRotating = true
        refreshID = nil
        refreshing = false
        requestedRefresh = false
        historyRevision = UUID()
        loadingHistory = false
        busy = true
        errorMessage = nil
        let credentialAddress = credentialAccount
        let remember = credentialStored
        defer {
            if epoch == generation {
                passwordRotating = false
                busy = false
                startMonitoring()
            }
        }
        do {
            let result = try await api.changePassword(current: current, new: new)
            guard epoch == generation else { return .failure(String(localized: "La connexion au cadre a changé.")) }
            guard result.authenticated else { throw APIError.invalidResponse }
            var message = String(localized: "Le mot de passe du cadre a été modifié. Les autres connexions ont été fermées.")
            if remember {
                do { try saveCredential(new, credentialAddress) }
                catch {
                    credentialStored = false
                    message += String(localized: " L’identifiant sécurisé n’a pas pu être mis à jour sur cet iPhone.")
                }
            }
            connected = true
            return .success(message)
        } catch {
            guard epoch == generation else { return .failure(String(localized: "La connexion au cadre a changé.")) }
            if (error as? APIError)?.isUnauthorized == true {
                handle(error)
                return .failure(String(localized: "Votre session a expiré. Reconnectez-vous au cadre."))
            }
            if let apiError = error as? APIError, case .http(let status, _) = apiError, status < 500 {
                return .failure(apiError.localizedDescription)
            }
            // Success may have reached the Pi without reaching this phone. Do not
            // keep offering an old biometric credential in this ambiguous state.
            if remember {
                try? vault.remove(address: credentialAddress)
                credentialStored = false
            }
            resetSession()
            let message = String(localized: "Le résultat n’a pas pu être confirmé. Essayez de vous reconnecter avec le nouveau mot de passe ; s’il est refusé, utilisez l’ancien.")
            errorMessage = message
            return .failure(message)
        }
    }

    func logout(forget: Bool = false) async {
        guard localUnlocked else { return }
        await finishLogout(forget: forget)
    }

    /// Used by an unlocked session or a separately verified, scoped forget confirmation.
    private func finishLogout(forget: Bool) async {
        let client = api
        let credentialAddress = credentialAccount
        let selectedAccess = selectedPhotoAccess
        // Complete every local change before suspension. The old client is isolated;
        // its eventual logout response must never mutate a newly connected frame.
        resetSession(clearClient: false)
        if forget {
            do {
                if let selectedAccess {
                    try photoAccessVault.remove(account: selectedAccess.account)
                    try photoAccessVault.remove(account: invitationDraftAccount(selectedAccess))
                    recordInvitationRevocation(nil, account: invitationDraftAccount(selectedAccess))
                    if pendingPhotoAccess?.account == selectedAccess.account {
                        defaults.removeObject(forKey: "photoAccessPending")
                        pendingPhotoAccess = nil
                    }
                    selectedPhotoAccess = nil
                    photoAccessRole = nil
                    defaults.removeObject(forKey: "photoAccessSelection")
                } else { try vault.remove(address: credentialAddress) }
                credentialStored = false
                if let selected = defaults.string(forKey: "frameOwnerID"), let id = UUID(uuidString: selected) {
                    try ownershipVault.remove(id: id)
                }
                defaults.removeObject(forKey: "photoAccessPending")
                pendingPhotoAccess = nil
                defaults.removeObject(forKey: "frameAddress")
                defaults.removeObject(forKey: "biometricEnabled")
                defaults.removeObject(forKey: "frameOwnerID")
                defaults.removeObject(forKey: "credentialStorageFailedAccount")
                credentialStorageError = nil
                address = ""
            } catch {
                errorMessage = String(localized: "Les identifiants de ce cadre n’ont pas tous pu être effacés. Déverrouillez l’iPhone puis réessayez Oublier ce cadre.")
            }
        }
        lock()
        if let client { _ = try? await client.logout() }
    }

    private func resetSession(clearClient: Bool = true, cancelLegacyUpgrade: Bool = true) {
        photoAccessCanInvite = false
        if cancelLegacyUpgrade {
            legacySharingUpgradeTask?.cancel()
            legacySharingUpgradeTask = nil
            legacySharingUpgradeID = UUID()
        }
        activeInvitation = nil
        accessDevices = []
        photoAccessOperation = UUID()
        photoAccessBusy = false
        recoveringConnection = false
        forgetAuthorization = nil
        pendingPairingCredential = nil
        pairingNeedsCompletion = false
        stopMonitoring()
        generation = UUID()
        if clearClient { api?.clearSession() }
        pendingClient?.clearSession()
        pendingClient = nil
        api = nil
        authenticated = false
        passwordChangeSupported = false
        bluetoothSupported = false
        requestedAdoptionFrameID = nil
        passwordRotating = false
        connected = false
        connecting = false
        refreshing = false
        refreshID = nil
        requestedRefresh = false
        historyRevision = UUID()
        loadingHistory = false
        hasMoreHistory = false
        busy = false
        displayBusy = false
        state = nil
        displayDiagnostics = nil
        displayReadError = nil
        queue = []
        history = []
        settings = nil
        version = "—"
        availableUpdate = nil
        updating = false
        updateMessage = nil
        errorMessage = nil
        connectionError = false
        notice = nil
        imageCache.removeAllObjects()
    }

    func refresh(allowSessionRecovery: Bool = true) async {
        #if DEBUG
        if fixturePhotoAccess != nil { return }
        #endif
        guard localUnlocked, active, !recoveringConnection, authenticated, !passwordRotating, let api = photoClient else { return }
        guard !refreshing else { requestedRefresh = true; return }
        refreshing = true
        let epoch = generation
        let identifier = UUID()
        refreshID = identifier
        historyRevision = UUID()
        loadingHistory = false
        var retryAfterCancellation = false
        defer {
            if epoch == generation, refreshID == identifier {
                refreshing = false
                refreshID = nil
                if retryAfterCancellation {
                    let retryRequested = requestedRefresh
                    requestedRefresh = false
                    if retryRequested, authenticated, active {
                        // The cancelled task cannot perform the pending request.
                        // Start after cleanup and recheck the session when scheduled.
                        Task { [weak self] in
                            guard let self, self.generation == epoch,
                                  self.authenticated, self.active else { return }
                            await self.refresh()
                        }
                    }
                }
            }
        }
        repeat {
            requestedRefresh = false
            async let s = snapshotResult { try await api.state() }
            async let q = snapshotResult { try await api.queue() }
            async let h = snapshotResult { try await historySnapshot(api: api, count: max(history.count, 100)) }
            async let f = snapshotResult { try await api.settings() }
            async let v = snapshotResult { try await api.health() }
            async let d = snapshotResult { try await self.api?.displayStatus() }
            let result = await (s, q, h, f, v, d)
            guard epoch == generation else { return }
            let failures: [Error] = [result.0.failure, result.1.failure, result.2.failure,
                                      result.3.failure, result.4.failure, result.5.failure].compactMap { $0 }
            if let unauthorized = failures.first(where: { ($0 as? APIError)?.isUnauthorized == true }) {
                if allowSessionRecovery, schedulePhotoRecovery() { return }
                handle(unauthorized)
                return
            }
            guard !Task.isCancelled, !failures.contains(where: {
                $0 is CancellationError || ($0 as? URLError)?.code == .cancelled
            }) else {
                retryAfterCancellation = true
                return
            }
            if case .success(let value) = result.0 { state = value; displayReadError = nil }
            else if let error = result.0.failure, !(error is URLError) {
                displayReadError = error.localizedDescription
            }
            if case .success(let value) = result.1 { queue = value }
            if case .success(let value) = result.2 {
                history = value.entries
                historyRevision = UUID()
                hasMoreHistory = value.hasMore
            }
            if case .success(let value) = result.3 { settings = value }
            if case .success(let value) = result.4 { version = value.version }
            if case .success(let value) = result.5 { displayDiagnostics = value }
            else if let error = result.5.failure, !(error is URLError) {
                displayReadError = error.localizedDescription
            }
            // A server-side display error is still an HTTP response from a
            // reachable frame. Keep its other data and diagnostics usable.
            let reachable = failures.count < 6 || failures.contains { !($0 is URLError) }
            if !reachable, allowSessionRecovery, schedulePhotoRecovery() { return }
            let otherFailures = [result.1.failure, result.2.failure, result.3.failure, result.4.failure]
                .compactMap { $0 }
            if let failure = otherFailures.first ?? (reachable ? nil : failures.first) {
                handle(failure)
                if epoch == generation { connectionError = true }
            } else if connectionError { errorMessage = nil; connectionError = false }
            connected = reachable
            if updating, let expected = availableUpdate?.latest, version == expected {
                updating = false
                updateMessage = String(localized: "Mise à jour terminée.")
            }
        } while requestedRefresh && authenticated && epoch == generation
    }

    private func snapshotResult<Value>(_ operation: () async throws -> Value) async -> Result<Value, Error> {
        do { return .success(try await operation()) }
        catch { return .failure(error) }
    }

    private func historySnapshot(api: any FramePhotoClient, count: Int) async throws -> (entries: [HistoryEntry], hasMore: Bool) {
        var entries: [HistoryEntry] = []
        // One look-ahead row makes the final page exact even when the existing
        // history length is a multiple of the page size.
        while entries.count <= count {
            guard localUnlocked, active else { throw CancellationError() }
            try Task.checkCancellation()
            let limit = min(500, count + 1 - entries.count)
            let page = try await api.history(limit: limit, offset: entries.count)
            entries.append(contentsOf: page)
            if page.count < limit { return (entries, false) }
        }
        return (Array(entries.prefix(count)), true)
    }

    func loadMoreHistory() async {
        guard localUnlocked, active, !recoveringConnection, authenticated, !passwordRotating, let api = photoClient, !loadingHistory, !refreshing, hasMoreHistory else { return }
        let epoch = generation
        let revision = historyRevision
        loadingHistory = true
        defer { if epoch == generation, revision == historyRevision { loadingHistory = false } }
        do {
            let entries = try await api.history(limit: 100, offset: history.count)
            guard epoch == generation, revision == historyRevision else { return }
            let existing = Set(history.map(\.id))
            history.append(contentsOf: entries.filter { !existing.contains($0.id) })
            hasMoreHistory = entries.count == 100
        } catch { if epoch == generation, revision == historyRevision { handle(error) } }
    }

    func sceneChanged(_ phase: ScenePhase) {
        switch phase {
        case .background:
            active = false
            lock()
        case .inactive:
            // System authentication and permission prompts can make us inactive.
            active = false
            stopMonitoring()
        case .active:
            active = true
            finishActiveSceneWaiters(admitted: true)
            startQueuedConnectionIfReady()
            presentQueuedFactorySetup()
            if localUnlocked && authenticated { startMonitoring(); Task { await refresh() } }
        @unknown default:
            active = false
            lock()
        }
    }

    /// Compatibility for protocol tests; UI forwards the actual ScenePhase.
    func sceneActive(_ isActive: Bool) { sceneChanged(isActive ? .active : .background) }

    private func startMonitoring() {
        #if DEBUG
        if fixturePhotoAccess != nil { return }
        #endif
        guard monitorsEvents, localUnlocked, active, !recoveringConnection, authenticated, !passwordRotating, let api, monitoringID == nil else { return }
        let epoch = generation
        let identifier = UUID()
        monitoringID = identifier
        eventsTask = Task { [weak self] in
            do {
                for try await event in api.events() {
                    guard let self, !Task.isCancelled, self.generation == epoch,
                          self.monitoringID == identifier else { return }
                    await self.receiveServerEvent(event)
                }
            } catch {
                guard let self, !Task.isCancelled, self.generation == epoch,
                      self.monitoringID == identifier else { return }
                await self.refresh()
            }
            if let self, self.generation == epoch, self.monitoringID == identifier {
                self.eventsTask = nil
                // HTTP polling remains available if the event stream alone ends.
            }
        }
        pollingTask = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(20))
                guard let self, !Task.isCancelled, self.generation == epoch,
                      self.monitoringID == identifier else { return }
                await self.refresh()
            }
        }
    }

    func receiveServerEvent(_ event: ServerEvent) async {
        guard localUnlocked, active, !recoveringConnection else { return }
        if event.type == "system_update" {
            if case let .string(message)? = event.payload["message"] { updateMessage = message }
            if case .string("error")? = event.payload["stage"] { updating = false }
        } else {
            // Loss of WebSocket is not proof that the HTTP API is offline.
            await refresh()
        }
    }

    private func stopMonitoring() {
        monitoringID = nil
        eventsTask?.cancel(); eventsTask = nil
        pollingTask?.cancel(); pollingTask = nil
        api?.stopEvents()
    }

    func image(for photo: Photo) async -> UIImage? {
        guard localUnlocked, active, !recoveringConnection, !passwordRotating, let api = photoClient else { return nil }
        if let image = imageCache.object(forKey: photo.id as NSString) { return image }
        let epoch = generation
        do {
            let data = try await api.photoData(id: photo.id)
            guard epoch == generation, let image = UIImage(data: data) else { return nil }
            imageCache.setObject(image, forKey: photo.id as NSString, cost: Int(image.size.width * image.size.height * 4))
            return image
        } catch {
            if epoch == generation, (error as? APIError)?.isUnauthorized == true { handle(error) }
            return nil
        }
    }

    func display(previous: Bool) async {
        guard canDisplay, !displayBusy, let api = photoClient else { return }
        let epoch = generation
        displayBusy = true
        defer { if epoch == generation { displayBusy = false } }
        do {
            if previous { try await api.previous() } else { try await api.next() }
            guard epoch == generation else { return }
            errorMessage = nil
            notice = String(localized: "Le cadre est à jour.")
        } catch {
            guard epoch == generation else { return }
            handle(error)
            if (error as? URLError)?.code == .timedOut {
                errorMessage = String(localized: "Le cadre prend plus de temps que prévu. Son état va être actualisé ; la commande n’a pas été renvoyée.")
            }
        }
        if epoch == generation { await refresh() }
    }

    private var photoUploadBinding: PhotoUploadBinding? {
        guard localUnlocked, active, authenticated, !recoveringConnection,
              let selected = selectedPhotoAccess, api?.pinnedIdentity == selected.identity else { return nil }
        return PhotoUploadBinding(frameID: selected.identity.id, spki: selected.identity.spkiSHA256,
                                  deviceID: selected.deviceID)
    }

    func pendingPhotoUpload() throws -> PhotoUploadDraft? {
        guard let binding = photoUploadBinding else { return nil }
        return try uploadDrafts.load(binding)
    }

    func discardPhotoUpload(_ draft: PhotoUploadDraft) throws {
        guard !busy, photoUploadBinding == draft.binding else { throw CancellationError() }
        try uploadDrafts.remove(draft)
    }

    func upload(_ data: Data, filename: String) async throws {
        guard canMutate, let api else { throw APIError.invalidResponse }
        if let binding = photoUploadBinding {
            if let previous = try uploadDrafts.load(binding) {
                guard previous.hash == PhotoUploadDraft.digest(data) else { throw PhotoAccessError.unavailable }
                return try await sendPhotoDraft(previous, on: api, resuming: true)
            }
            let draft = PhotoUploadDraft(binding: binding, filename: filename, png: data)
            try uploadDrafts.save(draft)
            return try await sendPhotoDraft(draft, on: api, resuming: false)
        }
        // Preserve legacy HTTPS and Simulator callers that have no individual device binding.
        let epoch = generation
        busy = true
        defer { if epoch == generation { busy = false } }
        do {
            let response = try await api.upload(png: data, filename: filename)
            guard epoch == generation else { throw CancellationError() }
            showUploadNotice(response)
            await refresh()
        } catch {
            if epoch == generation { handle(error) }
            throw error
        }
    }

    func resumePhotoUpload(_ draft: PhotoUploadDraft) async throws {
        guard canMutate, photoUploadBinding == draft.binding, let api,
              let saved = try uploadDrafts.load(draft.binding), saved.id == draft.id else { throw CancellationError() }
        try await sendPhotoDraft(saved, on: api, resuming: true)
    }

    private func sendPhotoDraft(_ draft: PhotoUploadDraft, on client: InkyAPI, resuming: Bool) async throws {
        let epoch = generation
        busy = true
        defer { if epoch == generation { busy = false } }
        func checkAdmission() throws {
            try Task.checkCancellation()
            guard epoch == generation, api === client, photoUploadBinding == draft.binding else { throw CancellationError() }
        }
        do {
            let prior: UploadResponse?
            do { prior = try await client.uploadReceipt(draft.id) }
            catch APIError.http(statusCode: 404, message: _) where !resuming { prior = nil }
            try checkAdmission()
            let response: UploadResponse
            if let prior { response = prior }
            else {
                response = try await client.upload(png: draft.png, filename: draft.filename, idempotencyKey: draft.id)
            }
            try checkAdmission()
            guard response.photo.sha256 == draft.hash, response.queueEntry.photo.id == response.photo.id else {
                throw APIError.invalidData
            }
            try uploadDrafts.remove(draft)
            showUploadNotice(response)
            await refresh()
        } catch {
            if epoch == generation { handle(error) }
            throw error
        }
    }

    private func showUploadNotice(_ response: UploadResponse) {
        notice = response.alreadyExisted ? String(localized: "Cette photo est dans la file.") : String(localized: "Photo ajoutée à la file.")
    }

    func requeue(_ entry: HistoryEntry) async {
        guard canMutate, let api = photoClient else { return }
        let epoch = generation
        await perform {
            let data = try await api.photoData(id: entry.photo.id)
            guard epoch == generation else { throw CancellationError() }
            _ = try await api.upload(png: data, filename: entry.photo.originalFilename)
        }
    }
    func remove(_ entry: QueueEntry) async {
        guard let api = photoClient else { return }
        await perform { try await api.removeFromQueue(photoID: entry.photo.id) }
    }
    func reorder(_ ids: [String]) async {
        guard !ids.isEmpty, let api = photoClient else { return }
        await perform { _ = try await api.reorderQueue(photoIDs: ids) }
    }
    func deleteHistory(_ entry: HistoryEntry) async {
        guard let api = photoClient else { return }
        await perform { try await api.deleteHistoryEntry(id: entry.id) }
    }
    func clearHistory() async {
        guard let api = photoClient else { return }
        await perform { try await api.clearHistory() }
    }
    func saveSettings(_ value: FrameSettings) async {
        guard let api else { return }
        if await perform({
            if self.photoAccessRole == .media { _ = try await api.updateSchedule(value) }
            else { _ = try await api.updateSettings(value) }
        }) {
            notice = String(localized: "Réglages enregistrés.")
        }
    }
    @discardableResult
    private func perform(_ action: () async throws -> Void) async -> Bool {
        guard canMutate else { return false }
        let epoch = generation
        busy = true
        errorMessage = nil
        connectionError = false
        defer { if epoch == generation { busy = false } }
        do {
            try await action()
            guard epoch == generation else { return false }
            await refresh()
            return epoch == generation && errorMessage == nil
        } catch {
            guard epoch == generation else { return false }
            handle(error)
            if epoch == generation { await refresh() }
            return false
        }
    }
    func checkUpdate() async {
        guard canAdminister, canMutate, let api else { return }
        let epoch = generation
        busy = true
        defer { if epoch == generation { busy = false } }
        do {
            let status = try await api.updateStatus(refresh: true)
            if epoch == generation { availableUpdate = status }
        } catch { if epoch == generation { handle(error) } }
    }
    func startUpdate() async {
        guard canAdminister, canMutate, let api else { return }
        let epoch = generation
        updating = true
        updateMessage = String(localized: "Préparation de la mise à jour…")
        do { _ = try await api.startUpdate() }
        catch { if epoch == generation { updating = false; handle(error) } }
    }
    private func handle(_ error: Error) {
        if error is CancellationError { return }
        if (error as? APIError)?.isUnauthorized == true {
            let individualAccess = selectedPhotoAccess != nil
            resetSession()
            errorMessage = individualAccess ? PhotoAccessError.accessRemoved.localizedDescription :
                String(localized: "Votre session a expiré ou le mot de passe est incorrect. Reconnectez-vous à votre cadre.")
            if individualAccess { photoAccessError = PhotoAccessError.accessRemoved.localizedDescription }
        } else if let error = error as? URLError {
            switch error.code {
            case .cancelled: return
            case .notConnectedToInternet, .cannotFindHost, .cannotConnectToHost, .networkConnectionLost, .timedOut:
                connectionError = true
                connected = false
                errorMessage = String(localized: "Le Raspberry est injoignable. Vérifiez son adresse, le Wi-Fi et l’autorisation Réseau local dans Réglages iOS.")
            default:
                connectionError = false
                errorMessage = String(localized: "La connexion a échoué. \(error.localizedDescription)")
            }
        } else {
            connectionError = false
            errorMessage = error.localizedDescription
        }
    }
}

// MARK: - Individually revocable photo access
private extension AppStore {
    func upgradeLegacySharing() async -> Bool {
        guard canShareAccess, needsSecureSharingUpgrade, !photoAccessBusy, !connecting, !unlocking, !busy, !displayBusy, !updating else { return false }
        let identifier = UUID()
        legacySharingUpgradeID = identifier
        let task = Task { await performLegacySharingUpgrade() }
        legacySharingUpgradeTask = task
        defer { if legacySharingUpgradeID == identifier { legacySharingUpgradeTask = nil } }
        return await withTaskCancellationHandler(operation: { await task.value }, onCancel: { task.cancel() })
    }

    func waitForLegacySharingForeground(epoch: UUID, operation: UUID) async -> Bool {
        let deadline = ProcessInfo.processInfo.systemUptime + 2
        while !active {
            guard epoch == generation, operation == photoAccessOperation, localUnlocked, !Task.isCancelled,
                  ProcessInfo.processInfo.systemUptime < deadline else { return false }
            do { try await Task.sleep(nanoseconds: 50_000_000) } catch { return false }
        }
        return photoOperationValid(epoch, operation)
    }

    func performLegacySharingUpgrade() async -> Bool {
        guard canShareAccess, needsSecureSharingUpgrade, let previous = api else { return false }
        let previousAccount = credentialAccount
        let previousAddress = address
        let authentication = localAuthenticationGeneration
        // Retire existing metadata callbacks without logging the old HTTP connection out.
        stopMonitoring()
        generation = UUID()
        refreshID = nil
        refreshing = false
        requestedRefresh = false
        historyRevision = UUID()
        loadingHistory = false
        var epoch = generation
        var operation = UUID()
        photoAccessOperation = operation
        photoAccessBusy = true
        photoAccessError = nil
        var candidate: InkyAPI?
        func stillSelected() -> Bool {
            photoOperationValid(epoch, operation) && localAuthenticationGeneration == authentication &&
            api === previous && address == previousAddress && credentialAccount == previousAccount && needsSecureSharingUpgrade
        }
        defer {
            candidate?.clearSession()
            if operation == photoAccessOperation {
                pendingClient = nil
                photoAccessBusy = false
                if api === previous, localUnlocked, active, authenticated { startMonitoring() }
            }
        }
        do {
            var bootstrapPassword = try await readCredential(previousAccount)
            guard await waitForLegacySharingForeground(epoch: epoch, operation: operation), stillSelected() else { return false }
            let prepared = try await prepareVerifiedOwner(endpoint: previous.baseURL, password: bootstrapPassword,
                admitted: stillSelected)
            bootstrapPassword = ""
            let pinned = prepared.client
            candidate = pinned
            guard stillSelected() else { return false }
            pendingClient = nil
            try commitPhotoAccess(prepared.credential, client: pinned, canInvite: prepared.canInvite, preservingLegacyUpgrade: true)
            defaults.set(prepared.credential.identity.id.uuidString, forKey: "pendingBootstrapRetirement")
            candidate = nil
            epoch = generation
            operation = UUID()
            photoAccessOperation = operation
            photoAccessBusy = true
            await refresh()
            guard photoOperationValid(epoch, operation), authenticated, api === pinned else { return false }
            startMonitoring()
            return true
        } catch {
            guard stillSelected(), !(error is CancellationError), (error as? URLError)?.code != .cancelled else { return false }
            if error is VaultError {
                photoAccessError = error.localizedDescription
            } else {
                photoAccessError = String(localized: "Le partage nécessite une mise à jour du cadre.")
            }
            return false
        }
    }

    func pairOverVerifiedHTTPS(endpoint: URL, password: String, attempt: UUID) async -> Bool {
        let epoch = generation
        connecting = true
        errorMessage = nil
        var candidate: InkyAPI?
        func admitted() -> Bool {
            epoch == generation && attempt == localAuthenticationGeneration && localUnlocked && active && !Task.isCancelled
        }
        defer {
            candidate?.clearSession()
            if epoch == generation && attempt == localAuthenticationGeneration {
                connecting = false
                pendingClient = nil
            }
        }
        do {
            let prepared = try await prepareVerifiedOwner(endpoint: endpoint, password: password, admitted: admitted)
            candidate = prepared.client
            guard admitted() else { return false }
            pendingClient = nil
            try commitPhotoAccess(prepared.credential, client: prepared.client, canInvite: prepared.canInvite)
            defaults.set(prepared.credential.identity.id.uuidString, forKey: "pendingBootstrapRetirement")
            candidate = nil
            let committedEpoch = generation
            await refresh()
            if committedEpoch == generation && localUnlocked && authenticated { startMonitoring() }
            return true
        } catch {
            guard admitted(), !(error is CancellationError), (error as? URLError)?.code != .cancelled else { return false }
            errorMessage = error is VaultError ? error.localizedDescription : String(localized: "Mettez à jour le logiciel du cadre, puis réessayez.")
            return false
        }
    }

    func retireBootstrapIfPending(on client: InkyAPI) async {
        guard api === client, localUnlocked, active, !Task.isCancelled, let selected = selectedPhotoAccess,
              selected.role == .owner, bootstrapRetirementFromLaunch == selected.identity.id.uuidString,
              defaults.string(forKey: "pendingBootstrapRetirement") == selected.identity.id.uuidString else { return }
        let epoch = generation
        do {
            try await PhotoAccessClient(api: client, identity: selected.identity).retireBootstrap()
            guard epoch == generation, api === client, localUnlocked, active, !Task.isCancelled else { return }
            defaults.removeObject(forKey: "pendingBootstrapRetirement")
        } catch {
            // Older frames keep their credentials. A later explicit unlock may confirm retirement.
        }
    }

    func prepareVerifiedOwner(endpoint: URL, password: String, admitted: () -> Bool) async throws
        -> (client: InkyAPI, credential: PhotoAccessCredential, canInvite: Bool) {
        let verified = try await proveLegacyTLS(endpoint, password)
        guard admitted() else { throw CancellationError() }
        let pinned = makePinnedAPI(verified.endpoint, verified.identity)
        var ready = false
        defer {
            if !ready { pinned.clearSession() }
        }
        guard OriginRedirectDelegate.sameOrigin(pinned.baseURL, verified.endpoint) else { throw PhotoAccessError.identityMismatch }
        let access = try PhotoAccessClient(api: pinned, identity: verified.identity)
        pendingClient = pinned
        let reply = try await pinned.login(password: password)
        guard admitted() else { throw CancellationError() }
        guard reply.authenticated else { throw APIError.unauthorized }
        let account = PhotoAccessSelection.account(identity: verified.identity, invitationID: nil)
        let credential: PhotoAccessCredential
        if photoAccessVault.contains(account: account) {
            let saved = try await photoAccessVault.loadCredential(account: account)
            guard admitted() else { throw CancellationError() }
            guard saved.identity == verified.identity, saved.expectedRole == .owner, saved.invitationID == nil else {
                throw PhotoAccessError.identityMismatch
            }
            credential = try PhotoAccessCredential(identity: verified.identity, endpoint: verified.endpoint,
                deviceID: saved.deviceID, deviceToken: saved.deviceToken, requestID: saved.requestID,
                expectedRole: .owner, state: .pending)
        } else {
            credential = try PhotoAccessCredential.make(identity: verified.identity, endpoint: verified.endpoint, role: .owner)
        }
        // Save the retry intent before enrollment. The selected access is published only after
        // the server returns the matching device session and protected final save succeeds.
        try rememberPendingPhotoAccess(credential)
        _ = try await access.enroll(credential)
        guard admitted() else { throw CancellationError() }
        let session = try await access.openSession(credential)
        guard admitted() else { throw CancellationError() }
        ready = true
        return (pinned, credential, session.canInvite)
    }

    func finishPhotoAccessWiFi(endpoint: URL, owner: OwnershipRecord, selected: PhotoAccessSelection) async {
        guard canMutate, !photoAccessBusy, selected.role == .owner else { return }
        let epoch = generation; let operation = UUID(); photoAccessOperation = operation
        photoAccessBusy = true; connecting = true
        var candidate: InkyAPI?
        defer {
            candidate?.clearSession()
            if operation == photoAccessOperation { photoAccessBusy = false; connecting = false; pendingClient = nil }
        }
        do {
            guard owner.identity == selected.identity else { throw PhotoAccessError.identityMismatch }
            try PhotoAccessValidation.origin(endpoint)
            let credential = try await photoAccessVault.loadCredential(account: selected.account)
            guard photoOperationValid(epoch, operation) else { return }
            guard selected.validates(credential) else { throw PhotoAccessError.identityMismatch }
            let relocated = try PhotoAccessCredential(identity: credential.identity, endpoint: endpoint,
                deviceID: credential.deviceID, deviceToken: credential.deviceToken, requestID: credential.requestID,
                expectedRole: .owner, state: .active, invitationID: credential.invitationID)
            let client = makePinnedAPI(endpoint, selected.identity)
            candidate = client; pendingClient = client
            let session = try await PhotoAccessClient(api: client, identity: selected.identity).openSession(relocated)
            guard photoOperationValid(epoch, operation) else { return }
            // BLE ownership stays separate. This only records the verified locator for the same owner.
            _ = try ownershipVault.markClaimed(id: owner.id, endpoint: endpoint)
            pendingClient = nil
            try commitPhotoAccess(relocated, client: client, canInvite: session.canInvite)
            defaults.set(owner.id.uuidString.lowercased(), forKey: "frameOwnerID")
            candidate = nil
            connecting = false; photoAccessBusy = false
            let committedEpoch = generation
            await refresh()
            guard committedEpoch == generation, localUnlocked, authenticated, api === client else { return }
            startMonitoring()
        } catch {
            guard photoOperationValid(epoch, operation) else { return }
            photoAccessError = String(localized: "Le Wi-Fi est configuré. L’accès photo précédent est conservé ; sa nouvelle adresse sécurisée n’a pas pu être confirmée.")
        }
    }
    func invitationDraftAccount(_ selection: PhotoAccessSelection) -> String { "invitation:" + selection.account }
    func invitationRevocationIntent(_ account: String) -> UUID? {
        guard let id = (defaults.dictionary(forKey: "photoInvitationRevocations") as? [String: String])?[account] else { return nil }
        return UUID(uuidString: id)
    }
    func recordInvitationRevocation(_ id: UUID?, account: String) {
        // Nonsecret cancellation intent survives even if protected storage temporarily rejects a write.
        // Tokens and the actual retry draft remain exclusively in the protected vault.
        var intents = defaults.dictionary(forKey: "photoInvitationRevocations") as? [String: String] ?? [:]
        intents[account] = id?.uuidString.lowercased()
        defaults.set(intents, forKey: "photoInvitationRevocations")
    }
    func photoOperationValid(_ epoch: UUID, _ operation: UUID) -> Bool {
        epoch == generation && operation == photoAccessOperation && localUnlocked && active && !Task.isCancelled
    }
    func rememberPendingPhotoAccess(_ credential: PhotoAccessCredential) throws {
        let selection = PhotoAccessSelection(credential)
        // Protected credential first. A marker never stands in for a successfully saved token.
        try photoAccessVault.save(credential, account: selection.account)
        let data = try JSONEncoder().encode(selection)
        pendingPhotoAccess = selection
        defaults.set(data, forKey: "photoAccessPending")
    }
    func commitPhotoAccess(_ credential: PhotoAccessCredential, client: InkyAPI, canInvite: Bool,
                           preservingLegacyUpgrade: Bool = false, preservingLogicalSession: Bool = false) throws {
        var saved = credential
        saved.state = .active
        let selection = PhotoAccessSelection(saved)
        try photoAccessVault.save(saved, account: selection.account)
        let selectionData = try JSONEncoder().encode(selection)
        resetSession(cancelLegacyUpgrade: !preservingLegacyUpgrade)
        selectedPhotoAccess = selection
        photoAccessRole = credential.expectedRole
        photoAccessCanInvite = canInvite
        defaults.set(selectionData, forKey: "photoAccessSelection")
        defaults.removeObject(forKey: "photoAccessPending")
        pendingPhotoAccess = nil
        // An invitation is PHOTO authority only. Old BLE ownership is retained in its own vault,
        // but must not be silently applied to a different selected frame.
        if defaults.string(forKey: "frameOwnerID")?.lowercased() != credential.identity.id.uuidString.lowercased() {
            defaults.removeObject(forKey: "frameOwnerID")
        }
        address = credential.endpoint.absoluteString
        defaults.set(address, forKey: "frameAddress")
        defaults.removeObject(forKey: "credentialStorageFailedAccount")
        api = client
        authenticated = true
        credentialStored = true
        credentialStorageError = nil
        pairingNeedsCompletion = false
        passwordChangeSupported = false
        if !preservingLogicalSession { sessionIdentity = UUID() }
    }
    func schedulePhotoRecovery() -> Bool {
        guard !legacyHTTPFixture, let selected = selectedPhotoAccess, localUnlocked, active,
              !busy, !displayBusy, !photoAccessBusy else { return false }
        if connecting { return true }
        let epoch = generation
        let attempt = localAuthenticationGeneration
        connecting = true
        connected = false
        Task { [weak self] in
            guard let self, self.generation == epoch, self.localAuthenticationGeneration == attempt else { return }
            guard self.active, self.localUnlocked else { self.connecting = false; return }
            await self.restorePhotoAccess(selected, attempt: attempt, recoveringSession: true)
        }
        return true
    }

    func photoRelocationCandidates(_ credential: PhotoAccessCredential) -> [URL] {
        var candidates: [URL] = []
        if let record = try? ownershipVault.load(id: credential.identity.id), record.identity == credential.identity {
            candidates.append(contentsOf: record.endpoints.reversed().prefix(4))
        }
        let compactID = credential.identity.id.uuidString.lowercased().replacingOccurrences(of: "-", with: "")
        if let canonical = try? FactorySetupValidation.origin("https://inky-\(compactID).local:8443") {
            candidates.append(canonical)
        }
        var origins = [credential.endpoint]
        return candidates.filter { candidate in
            guard !origins.contains(where: { OriginRedirectDelegate.sameOrigin($0, candidate) }) else { return false }
            origins.append(candidate)
            return true
        }
    }

    func restorePhotoAccess(_ selection: PhotoAccessSelection, attempt: UUID, recoveringSession: Bool = false) async {
        let epoch = generation
        connecting = true
        var candidate: InkyAPI?
        defer {
            candidate?.clearSession()
            if attempt == localAuthenticationGeneration { connecting = false; pendingClient = nil }
        }
        do {
            let credential = try await photoAccessVault.loadCredential(account: selection.account)
            guard await waitForActiveScene(authentication: attempt), epoch == generation, localUnlocked else { return }
            // A previous save may have persisted the new protected locator before updating
            // its nonsecret mirror. The protected record is authoritative for this device.
            guard selection.matchesDevice(credential) else { throw PhotoAccessError.identityMismatch }
            let alternate = photoRelocationCandidates(credential)
            var lastUnreachable: URLError?
            for endpoint in [credential.endpoint] + alternate {
                candidate?.clearSession()
                let client = makePinnedAPI(endpoint, selection.identity)
                candidate = client
                pendingClient = client
                let relocated = try PhotoAccessCredential(identity: credential.identity, endpoint: endpoint,
                    deviceID: credential.deviceID, deviceToken: credential.deviceToken, requestID: credential.requestID,
                    expectedRole: credential.expectedRole, state: credential.state, invitationID: credential.invitationID)
                let access = try PhotoAccessClient(api: client, identity: selection.identity)
                let session: PhotoAccessSessionReply
                do {
                    if endpoint != credential.endpoint {
                        try await access.verifyLocatorIdentity()
                        guard await waitForActiveScene(authentication: attempt), epoch == generation, localUnlocked else { return }
                    }
                    session = try await access.openSession(relocated)
                } catch let error as URLError where Self.isLocatorUnavailable(error) {
                    guard await waitForActiveScene(authentication: attempt), epoch == generation, localUnlocked else { return }
                    lastUnreachable = error
                    continue
                }
                guard await waitForActiveScene(authentication: attempt), epoch == generation, localUnlocked else { return }
                pendingClient = nil
                try commitPhotoAccess(relocated, client: client, canInvite: session.canInvite,
                                      preservingLogicalSession: recoveringSession)
                candidate = nil
                connecting = false
                await refresh(allowSessionRecovery: false)
                if !recoveringSession { await retireBootstrapIfPending(on: client) }
                guard attempt == localAuthenticationGeneration, localUnlocked, authenticated, api === client else { return }
                startMonitoring()
                return
            }
            throw lastUnreachable ?? URLError(.cannotConnectToHost)
        } catch {
            guard attempt == localAuthenticationGeneration, epoch == generation, !Task.isCancelled else { return }
            let unauthorized = (error as? APIError)?.isUnauthorized == true
            let message = unauthorized ? PhotoAccessError.accessRemoved.localizedDescription : error.localizedDescription
            photoAccessError = message
            if recoveringSession && !unauthorized {
                connected = false
                connectionError = true
                errorMessage = message
                return
            }
            if recoveringSession { resetSession() }
            localUnlocked = false
            localAuthenticationError = message
            credentialStored = photoAccessVault.contains(account: selection.account)
            invalidateAuthentication()
        }
    }

    static func isLocatorUnavailable(_ error: URLError) -> Bool {
        [.cannotFindHost, .dnsLookupFailed, .cannotConnectToHost, .notConnectedToInternet, .networkConnectionLost, .timedOut].contains(error.code)
    }

    func ensurePhotoOwner(epoch: UUID, operation: UUID) async throws -> PhotoAccessClient {
        guard photoOperationValid(epoch, operation), canAdminister, canShareAccess,
              let current = api, let identity = current.pinnedIdentity else {
            throw PhotoAccessError.trustedHTTPSRequired
        }
        if photoAccessRole == .owner { return try PhotoAccessClient(api: current, identity: identity) }
        guard selectedPhotoAccess == nil, photoAccessRole == nil else { throw PhotoAccessError.accessRemoved }
        let account = PhotoAccessSelection.account(identity: identity, invitationID: nil)
        let credential: PhotoAccessCredential
        if photoAccessVault.contains(account: account) {
            credential = try await photoAccessVault.loadCredential(account: account)
            guard photoOperationValid(epoch, operation) else { throw CancellationError() }
            guard credential.expectedRole == .owner, credential.identity == identity,
                  OriginRedirectDelegate.sameOrigin(credential.endpoint, current.baseURL) else { throw PhotoAccessError.identityMismatch }
        } else { credential = try PhotoAccessCredential.make(identity: identity, endpoint: current.baseURL, role: .owner) }
        guard photoOperationValid(epoch, operation) else { throw CancellationError() }
        try rememberPendingPhotoAccess(credential)
        let candidate = try current.photoAccessCandidate()
        var committed = false
        defer { if !committed { candidate.clearSession() } }
        let access = try PhotoAccessClient(api: candidate, identity: identity)
        _ = try await access.enroll(credential)
        guard photoOperationValid(epoch, operation) else { throw CancellationError() }
        let session = try await access.openSession(credential)
        guard photoOperationValid(epoch, operation) else { throw CancellationError() }
        var durable = credential; durable.state = .active
        try photoAccessVault.save(durable, account: account)
        let selection = PhotoAccessSelection(durable)
        defaults.set(try JSONEncoder().encode(selection), forKey: "photoAccessSelection")
        defaults.removeObject(forKey: "photoAccessPending")
        pendingPhotoAccess = nil
        selectedPhotoAccess = selection
        photoAccessRole = .owner
        photoAccessCanInvite = session.canInvite
        try current.commitPhotoAccessSession(from: candidate)
        candidate.clearSession()
        passwordChangeSupported = false
        credentialStored = true
        committed = true
        startMonitoring()
        return try PhotoAccessClient(api: current, identity: identity)
    }
    func ensurePhotoInviter(epoch: UUID, operation: UUID) async throws -> PhotoAccessClient {
        guard photoOperationValid(epoch, operation), canShareAccess else { throw PhotoAccessError.accessRemoved }
        if photoAccessRole == .media {
            guard photoAccessCanInvite, selectedPhotoAccess?.role == .media,
                  let current = api, let identity = current.pinnedIdentity else { throw PhotoAccessError.trustedHTTPSRequired }
            // A PHOTO member uses its own session. Inviting never enrolls an owner.
            return try PhotoAccessClient(api: current, identity: identity)
        }
        return try await ensurePhotoOwner(epoch: epoch, operation: operation)
    }
    func reportPhotoAccessError(_ error: Error, epoch: UUID, operation: UUID, affectsCurrentSession: Bool = true) {
        guard photoOperationValid(epoch, operation), !(error is CancellationError), (error as? URLError)?.code != .cancelled else { return }
        if (error as? APIError)?.isUnauthorized == true {
            activeInvitation = nil
            if affectsCurrentSession && selectedPhotoAccess != nil { handle(error) }
            photoAccessError = PhotoAccessError.accessRemoved.localizedDescription
        } else { photoAccessError = error.localizedDescription }
    }
}

extension AppStore {
    func cancelPhotoAccessOperation() {
        guard photoAccessBusy else { return }
        legacySharingUpgradeTask?.cancel()
        legacySharingUpgradeTask = nil
        legacySharingUpgradeID = UUID()
        photoAccessOperation = UUID()
        pendingClient?.clearSession()
        pendingClient = nil
        photoAccessBusy = false
        stopMonitoring()
        generation = UUID()
        refreshID = nil
        refreshing = false
        requestedRefresh = false
        loadingHistory = false
        startMonitoring()
    }

    /// Recipient QR claim is isolated from the currently selected frame until secure commit.
    func claimInvitation(_ code: FrameInvitationCode) async {
        guard !connecting, !unlocking, !photoAccessBusy, !busy, !displayBusy, !updating else { return }
        localAuthenticationError = nil
        photoAccessError = nil
        errorMessage = nil
        let attempt = localAuthenticationGeneration
        unlocking = true
        defer { if attempt == localAuthenticationGeneration { unlocking = false } }
        guard await authorizeLocally() else { return }
        // The system's own authentication prompt may finish just before the active scene notification.
        // Keep that authorization, but admit no network mutation until the app is visible again.
        guard await waitForActiveScene(authentication: attempt), localUnlocked else {
            if attempt == localAuthenticationGeneration {
                localUnlocked = false
                invalidateAuthentication()
            }
            return
        }
        unlocking = false
        let epoch = generation
        let operation = UUID(); photoAccessOperation = operation
        photoAccessBusy = true; connecting = true; photoAccessError = nil; errorMessage = nil
        let candidate = makePinnedAPI(code.endpoint, code.identity)
        pendingClient = candidate
        var committed = false
        defer {
            if !committed { candidate.clearSession() }
            if operation == photoAccessOperation { photoAccessBusy = false; connecting = false; pendingClient = nil }
        }
        do {
            let account = PhotoAccessSelection.account(identity: code.identity, invitationID: code.invitationID)
            let credential: PhotoAccessCredential
            if photoAccessVault.contains(account: account) {
                credential = try await photoAccessVault.loadCredential(account: account)
                guard photoOperationValid(epoch, operation) else { return }
                guard credential.identity == code.identity, credential.invitationID == code.invitationID,
                      credential.expectedRole == .media, OriginRedirectDelegate.sameOrigin(credential.endpoint, code.endpoint) else {
                    throw PhotoAccessError.identityMismatch
                }
            } else {
                credential = try PhotoAccessCredential.make(identity: code.identity, endpoint: code.endpoint, role: .media,
                                                           invitationID: code.invitationID)
            }
            guard photoOperationValid(epoch, operation) else { return }
            try rememberPendingPhotoAccess(credential)
            let client = try PhotoAccessClient(api: candidate, identity: code.identity)
            // Exact claim retry also recovers an uncertain previous response; no mutation is replayed automatically.
            let session = try await client.claim(code, credential: credential)
            guard photoOperationValid(epoch, operation) else { return }
            pendingClient = nil
            try commitPhotoAccess(credential, client: candidate, canInvite: session.canInvite)
            committed = true
            connecting = false
            photoAccessBusy = false
            let committedEpoch = generation
            await refresh()
            guard committedEpoch == generation, localUnlocked, authenticated, api === candidate else { return }
            startMonitoring()
        } catch { reportPhotoAccessError(error, epoch: epoch, operation: operation, affectsCurrentSession: false) }
    }

    func enrollPhotoAccess() async {
        guard canAdminister, canShareAccess, !photoAccessBusy else { return }
        if needsSecureSharingUpgrade { _ = await upgradeLegacySharing(); return }
        let epoch = generation; let operation = UUID(); photoAccessOperation = operation
        photoAccessBusy = true; photoAccessError = nil
        defer { if photoAccessOperation == operation { photoAccessBusy = false } }
        do { _ = try await ensurePhotoOwner(epoch: epoch, operation: operation) }
        catch { reportPhotoAccessError(error, epoch: epoch, operation: operation) }
    }
    func refreshAccessDevices() async {
        // Opening the sheet or its automatic task must never promote a legacy connection.
        guard canAdminister, canShareAccess, !needsSecureSharingUpgrade, !photoAccessBusy else { return }
        #if DEBUG
        if fixturePhotoAccess != nil { return }
        #endif
        let epoch = generation; let operation = UUID(); photoAccessOperation = operation
        photoAccessBusy = true; photoAccessError = nil
        defer { if photoAccessOperation == operation { photoAccessBusy = false } }
        do {
            let client = try await ensurePhotoOwner(epoch: epoch, operation: operation)
            let devices = try await client.devices()
            guard photoOperationValid(epoch, operation) else { return }
            accessDevices = devices
        } catch { reportPhotoAccessError(error, epoch: epoch, operation: operation) }
    }
    func createInvitation() async {
        guard canShareAccess, !photoAccessBusy else { return }
        if needsSecureSharingUpgrade {
            guard await upgradeLegacySharing(), canShareAccess, !photoAccessBusy else { return }
        }
        #if DEBUG
        if fixturePhotoAccess != nil { createFixtureInvitation(expired: false); return }
        #endif
        let oldInvitation = activeInvitation
        activeInvitation = nil
        let epoch = generation; let operation = UUID(); photoAccessOperation = operation
        photoAccessBusy = true; photoAccessError = nil
        defer { if photoAccessOperation == operation { photoAccessBusy = false } }
        do {
            let client = try await ensurePhotoInviter(epoch: epoch, operation: operation)
            guard photoOperationValid(epoch, operation), let selected = selectedPhotoAccess else { return }
            let account = invitationDraftAccount(selected)
            var draft: PhotoInvitationDraft
            if let intent = invitationRevocationIntent(account), !photoAccessVault.contains(account: account) {
                try await client.revokeInvitation(intent)
                guard photoOperationValid(epoch, operation) else { return }
                recordInvitationRevocation(nil, account: account)
            }
            if photoAccessVault.contains(account: account) {
                draft = try await photoAccessVault.loadDraft(account: account)
                guard photoOperationValid(epoch, operation) else { return }
                if oldInvitation != nil || draft.revocationPending || invitationRevocationIntent(account) != nil ||
                    draft.expiresAt.map({ $0 <= Date().timeIntervalSince1970 }) == true {
                    recordInvitationRevocation(draft.invitationID, account: account)
                    draft.revocationPending = true
                    try photoAccessVault.save(draft, account: account)
                    try await client.revokeInvitation(draft.invitationID)
                    guard photoOperationValid(epoch, operation) else { return }
                    try photoAccessVault.remove(account: account)
                    recordInvitationRevocation(nil, account: account)
                    draft = try PhotoInvitationDraft.make(identity: selected.identity, endpoint: selected.endpoint)
                }
            } else { draft = try PhotoInvitationDraft.make(identity: selected.identity, endpoint: selected.endpoint) }
            guard photoOperationValid(epoch, operation) else { return }
            try photoAccessVault.save(draft, account: account)
            let invitation = try await client.createInvitation(draft)
            guard photoOperationValid(epoch, operation) else { return }
            guard invitation.expiresAt > Date().timeIntervalSince1970 else {
                try photoAccessVault.remove(account: account)
                throw PhotoAccessError.unavailable
            }
            draft.expiresAt = invitation.expiresAt
            try photoAccessVault.save(draft, account: account)
            activeInvitation = invitation
        } catch { reportPhotoAccessError(error, epoch: epoch, operation: operation) }
    }
    func revokeActiveInvitation() async {
        guard canShareAccess, !photoAccessBusy, let invitation = activeInvitation else { return }
        activeInvitation = nil
        #if DEBUG
        if fixturePhotoAccess != nil { return }
        #endif
        if let selected = selectedPhotoAccess {
            recordInvitationRevocation(invitation.invitationID, account: invitationDraftAccount(selected))
        }
        let epoch = generation; let operation = UUID(); photoAccessOperation = operation
        photoAccessBusy = true; photoAccessError = nil
        defer { if photoAccessOperation == operation { photoAccessBusy = false } }
        do {
            let client = try await ensurePhotoInviter(epoch: epoch, operation: operation)
            guard photoOperationValid(epoch, operation), let selected = selectedPhotoAccess else { return }
            let account = invitationDraftAccount(selected)
            recordInvitationRevocation(invitation.invitationID, account: account)
            var draft = try await photoAccessVault.loadDraft(account: account)
            guard photoOperationValid(epoch, operation), draft.invitationID == invitation.invitationID else { return }
            draft.revocationPending = true
            try photoAccessVault.save(draft, account: account)
            try await client.revokeInvitation(invitation.invitationID)
            guard photoOperationValid(epoch, operation) else { return }
            try photoAccessVault.remove(account: account)
            recordInvitationRevocation(nil, account: account)
        } catch {
            reportPhotoAccessError(error, epoch: epoch, operation: operation)
            if photoOperationValid(epoch, operation), (error as? APIError)?.isUnauthorized != true {
                photoAccessError = String(localized: "L’annulation n’a pas pu être confirmée. L’invitation peut rester valable jusqu’à son expiration. Réessayez avant de créer un nouveau QR.")
            }
        }
    }
    func revokeAccessDevice(_ id: UUID) async {
        guard canAdminister, canShareAccess, !photoAccessBusy,
              accessDevices.contains(where: { $0.deviceID == id && $0.role == .media && !$0.revoked }) else { return }
        let epoch = generation; let operation = UUID(); photoAccessOperation = operation
        photoAccessBusy = true; photoAccessError = nil
        defer { if photoAccessOperation == operation { photoAccessBusy = false } }
        do {
            let client = try await ensurePhotoOwner(epoch: epoch, operation: operation)
            try await client.revokeDevice(id)
            guard photoOperationValid(epoch, operation) else { return }
            activeInvitation = nil
            let devices = try await client.devices()
            guard photoOperationValid(epoch, operation) else { return }
            accessDevices = devices
        } catch { reportPhotoAccessError(error, epoch: epoch, operation: operation) }
    }
}

#if DEBUG
private extension AppStore {
    func configurePhotoAccessFixture(_ mode: String) {
        guard ["owner", "media", "invitationexpired", "mediasharing", "mediasharingexpired"].contains(mode),
              let identity = try? FrameIdentity(id: UUID(uuidString: "11111111-2222-4333-8444-555555555555")!,
                  spkiSHA256: Data(repeating: 0x11, count: 32)),
              let url = URL(string: "https://192.168.1.120:8443") else { return }
        fixturePhotoAccess = mode
        photoAccessRole = mode.hasPrefix("media") ? .media : .owner
        photoAccessCanInvite = mode != "media"
        localUnlocked = true; authenticated = true; connected = true; credentialStored = true
        address = url.absoluteString
        defaults.set(address, forKey: "frameAddress")
        api = InkyAPI(baseURL: url, trustedIdentity: identity)
        settings = FrameSettings()
        state = DisplayState(display: DisplayInfo(model: "Cadre de test", width: 800, height: 480, colors: 7, isMock: false),
                             current: nil, queueCount: 0, nextChangeAt: nil)
        bluetoothSupported = true
        accessDevices = [PhotoAccessDeviceSummary(deviceID: UUID(uuidString: "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee")!,
            role: .owner, createdAt: 1, revoked: false),
            PhotoAccessDeviceSummary(deviceID: UUID(uuidString: "bbbbbbbb-cccc-4ddd-8eee-ffffffffffff")!, role: .media, createdAt: 1, revoked: false)]
        if mode == "invitationexpired" || mode == "mediasharingexpired" { createFixtureInvitation(expired: true) }
    }
    func createFixtureInvitation(expired: Bool) {
        guard let identity = api?.pinnedIdentity, let endpoint = api?.baseURL,
              let code = try? FrameInvitationCode(identity: identity, endpoint: endpoint, invitationID: UUID(),
                  invitationToken: String(repeating: "2", count: 64)) else { return }
        activeInvitation = PhotoAccessInvitation(invitationID: code.invitationID, code: code,
            expiresAt: Date().timeIntervalSince1970 + (expired ? -5 : 300))
        photoAccessError = nil
    }
}
#endif

enum PasswordChangeResult: Equatable {
    case success(String)
    case failure(String)
}

private extension Result {
    var failure: Failure? {
        guard case .failure(let error) = self else { return nil }
        return error
    }
}
