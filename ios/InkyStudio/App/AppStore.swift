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
    private var active = true
    private var requestedRefresh = false
    private var connectionError = false
    private var passwordRotating = false
    private let ownershipVault = OwnershipVault()
    private var requestedAdoptionFrameID: UUID?

    init(defaults: UserDefaults = .standard,
         makeAPI: @escaping @MainActor (URL) -> InkyAPI = { InkyAPI(baseURL: $0) },
         vault: BiometricVault = BiometricVault(),
         authenticateLocal: (@MainActor () async throws -> Void)? = nil,
         invalidateAuthentication: (@MainActor () -> Void)? = nil,
         saveCredential: (@MainActor (String, String) throws -> Void)? = nil,
         loadCredential: (@MainActor (String) async throws -> String)? = nil,
         containsCredential: (@MainActor (String) -> Bool)? = nil,
         authenticationName: (@MainActor () -> String)? = nil,
         monitorsEvents: Bool = true) {
        self.defaults = defaults
        self.makeAPI = makeAPI
        self.vault = vault
        let deviceAuthentication = LocalDeviceAuthentication()
        self.authenticateLocal = authenticateLocal ?? { try await deviceAuthentication.authenticate() }
        self.invalidateAuthentication = invalidateAuthentication ?? { deviceAuthentication.invalidate() }
        self.saveCredential = saveCredential ?? { try vault.save(password: $0, address: $1, context: deviceAuthentication.context) }
        self.loadCredential = loadCredential ?? { try await vault.load(address: $0, context: deviceAuthentication.context) }
        self.containsCredential = containsCredential ?? { vault.contains(address: $0) }
        self.authenticationName = authenticationName ?? { deviceAuthentication.name }
        self.monitorsEvents = monitorsEvents
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
            credentialStorageError = "L’association n’est pas finalisée : aucun identifiant de cette connexion n’a été confirmé. Scannez à nouveau le QR du cadre pour terminer l’association."
        }
        imageCache.totalCostLimit = 24 * 1024 * 1024
    }

    var hasSavedFrame: Bool { defaults.string(forKey: "frameAddress") != nil }
    var localAuthenticationName: String { authenticationName() }
    var hasAdoptedFrame: Bool { defaults.string(forKey: "frameOwnerID") != nil }
    var panelWidth: Int { state?.display.width ?? 800 }
    var panelHeight: Int { state?.display.height ?? 480 }
    var canMutate: Bool { localUnlocked && active && !unlocking && !recoveringConnection && !pairingNeedsCompletion && authenticated && connected && !busy && !updating }
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

    /// A local lock never logs out or discards a usable in-memory network session.
    func lock() {
        recoveringConnection = false
        forgetAuthorization = nil
        localAuthenticationGeneration = UUID()
        invalidateAuthentication()
        credentialTask?.cancel()
        credentialTask = nil
        credentialTaskID = UUID()
        pendingPairingCredential = nil
        if pairingNeedsCompletion {
            credentialStorageError = "L’association n’est pas finalisée et son identifiant temporaire n’est plus disponible. Scannez à nouveau le QR pour terminer l’association."
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
        if connecting { pendingClient?.clearSession(); pendingClient = nil; connecting = false }
    }

    func unlock() async {
        guard !unlocking, !connecting else { return }
        let attempt = localAuthenticationGeneration
        unlocking = true
        defer { if attempt == localAuthenticationGeneration { unlocking = false } }
        guard await authorizeLocally() else { return }
        if authenticated, api != nil {
            // Cookie-only sessions remain usable. Do not require a lost QR or force logout.
            credentialStored = containsCredential(credentialAccount) && defaults.string(forKey: "credentialStorageFailedAccount") != credentialAccount
            if !credentialStored && credentialStorageError == nil {
                credentialStorageError = "La connexion actuelle est conservée. Cet iPhone n’a pas encore d’identifiant enregistré pour les prochaines connexions."
            }
            startMonitoring()
            await refresh()
            return
        }
        guard hasSavedFrame || credentialStored else { return }
        do {
            let password = try await readCredential(credentialAccount)
            guard attempt == localAuthenticationGeneration, localUnlocked, !Task.isCancelled else { return }
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
        guard !hasAdoptedFrame, !pairingNeedsCompletion, !unlocking, !connecting, !busy, !displayBusy, !updating else { return }
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
        guard canMutate, let api else { throw APIError.unauthorized }
        let epoch = generation
        let id = try await api.beginBluetoothAdoption()
        guard epoch == generation else { throw CancellationError() }
        requestedAdoptionFrameID = id
    }

    func finishBluetoothSetup(endpoint: URL, owner: OwnershipRecord) async {
        guard localUnlocked, !pairingNeedsCompletion else { return }
        let epoch = generation
        do {
            try FrameTrustPolicy(identity: owner.identity).validateHTTPS(endpoint)
            let oldAccount = credentialAccount
            let password: String
            do { password = try await readCredential(oldAccount) }
            catch {
                guard epoch == generation, localUnlocked else { return }
                notice = "Le Wi-Fi est configuré. L’accès actuel à vos photos est conservé ; son transfert sécurisé n’a pas été effectué."
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
                credentialStorageError = "Le Wi-Fi est configuré, mais l’identifiant sécurisé n’a pas pu être transféré. L’accès actuel à vos photos est conservé."
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
            errorMessage = "Le Wi-Fi est configuré. La nouvelle connexion photo n’a pas pu être vérifiée ; la connexion précédente est conservée."
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
            errorMessage = "Scannez le QR du cadre dont l’association est en cours."
            return
        }
        let attempt = localAuthenticationGeneration
        unlocking = true
        defer { if attempt == localAuthenticationGeneration { unlocking = false } }
        guard await authorizeLocally() else { return }
        if recoveringConnection { await connectRecovery(code) }
        else { await connect(password: code.password, at: code.endpoint, savePassword: true) }
    }

    func cancelLogin() {
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
        guard localUnlocked, !connecting else { return }
        resetSession()
        let epoch = generation
        connecting = true
        errorMessage = nil
        defer {
            if epoch == generation { connecting = false; pendingClient = nil }
        }
        do {
            let url = try endpoint ?? FrameAddress.parse(address)
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
                    credentialStorageError = "L’association reste à finaliser : l’identifiant n’a pas pu être enregistré. Réessayez pour pouvoir envoyer vos photos."
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
            errorMessage = "La nouvelle connexion n’a pas pu être finalisée. L’ancien accès est conservé. " + error.localizedDescription
        }
    }

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
            credentialStorageError = "L’enregistrement sécurisé n’a pas abouti. L’association reste à finaliser ; vous pouvez réessayer."
        }
    }

    /// Rotate exactly once. A lost response must not replay this mutation or
    /// silently restore an old Keychain password after the frame has changed it.
    func changePassword(current: String, new: String) async -> PasswordChangeResult {
        guard canMutate, !displayBusy, passwordChangeSupported, let api else {
            return .failure("Reconnectez-vous au cadre avant de modifier son mot de passe.")
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
            guard epoch == generation else { return .failure("La connexion au cadre a changé.") }
            guard result.authenticated else { throw APIError.invalidResponse }
            var message = "Le mot de passe du cadre a été modifié. Les autres connexions ont été fermées."
            if remember {
                do { try saveCredential(new, credentialAddress) }
                catch {
                    credentialStored = false
                    message += " L’identifiant sécurisé n’a pas pu être mis à jour sur cet iPhone."
                }
            }
            connected = true
            return .success(message)
        } catch {
            guard epoch == generation else { return .failure("La connexion au cadre a changé.") }
            if (error as? APIError)?.isUnauthorized == true {
                handle(error)
                return .failure("Votre session a expiré. Reconnectez-vous au cadre.")
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
            let message = "Le résultat n’a pas pu être confirmé. Essayez de vous reconnecter avec le nouveau mot de passe ; s’il est refusé, utilisez l’ancien."
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
        // Complete every local change before suspension. The old client is isolated;
        // its eventual logout response must never mutate a newly connected frame.
        resetSession(clearClient: false)
        if forget {
            do {
                try vault.remove(address: credentialAddress)
                credentialStored = false
                if let selected = defaults.string(forKey: "frameOwnerID"), let id = UUID(uuidString: selected) {
                    try ownershipVault.remove(id: id)
                }
                defaults.removeObject(forKey: "frameAddress")
                defaults.removeObject(forKey: "biometricEnabled")
                defaults.removeObject(forKey: "frameOwnerID")
                defaults.removeObject(forKey: "credentialStorageFailedAccount")
                credentialStorageError = nil
                address = ""
            } catch {
                errorMessage = "Les identifiants de ce cadre n’ont pas tous pu être effacés. Déverrouillez l’iPhone puis réessayez Oublier ce cadre."
            }
        }
        lock()
        if let client { _ = try? await client.logout() }
    }

    private func resetSession(clearClient: Bool = true) {
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

    func refresh() async {
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
            let otherFailures = [result.1.failure, result.2.failure, result.3.failure, result.4.failure]
                .compactMap { $0 }
            if let failure = otherFailures.first ?? (reachable ? nil : failures.first) {
                handle(failure)
                if epoch == generation { connectionError = true }
            } else if connectionError { errorMessage = nil; connectionError = false }
            connected = reachable
            if updating, let expected = availableUpdate?.latest, version == expected {
                updating = false
                updateMessage = "Mise à jour terminée."
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
            if localUnlocked && authenticated { startMonitoring(); Task { await refresh() } }
        @unknown default:
            active = false
            lock()
        }
    }

    /// Compatibility for protocol tests; UI forwards the actual ScenePhase.
    func sceneActive(_ isActive: Bool) { sceneChanged(isActive ? .active : .background) }

    private func startMonitoring() {
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
                if (error as? APIError)?.isUnauthorized == true { self.handle(error) }
                else { await self.refresh() }
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
            notice = "Le cadre est à jour."
        } catch {
            guard epoch == generation else { return }
            handle(error)
            if (error as? URLError)?.code == .timedOut {
                errorMessage = "Le cadre prend plus de temps que prévu. Son état va être actualisé ; la commande n’a pas été renvoyée."
            }
        }
        if epoch == generation { await refresh() }
    }

    func upload(_ data: Data, filename: String) async throws {
        guard canMutate, let api = photoClient else { throw APIError.invalidResponse }
        let epoch = generation
        busy = true
        defer { if epoch == generation { busy = false } }
        do {
            let response = try await api.upload(png: data, filename: filename)
            guard epoch == generation else { throw CancellationError() }
            notice = response.alreadyExisted ? "Cette photo est dans la file." : "Photo ajoutée à la file."
            await refresh()
        } catch {
            if epoch == generation { handle(error) }
            throw error
        }
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
        guard let api = photoClient else { return }
        if await perform({ _ = try await api.updateSettings(value) }) {
            notice = "Réglages enregistrés."
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
        guard canMutate, let api else { return }
        let epoch = generation
        busy = true
        defer { if epoch == generation { busy = false } }
        do {
            let status = try await api.updateStatus(refresh: true)
            if epoch == generation { availableUpdate = status }
        } catch { if epoch == generation { handle(error) } }
    }
    func startUpdate() async {
        guard canMutate, let api else { return }
        let epoch = generation
        updating = true
        updateMessage = "Préparation de la mise à jour…"
        do { _ = try await api.startUpdate() }
        catch { if epoch == generation { updating = false; handle(error) } }
    }
    private func handle(_ error: Error) {
        if error is CancellationError { return }
        if (error as? APIError)?.isUnauthorized == true {
            resetSession()
            errorMessage = "Votre session a expiré ou le mot de passe est incorrect. Reconnectez-vous à votre cadre."
        } else if let error = error as? URLError {
            switch error.code {
            case .cancelled: return
            case .notConnectedToInternet, .cannotFindHost, .cannotConnectToHost, .networkConnectionLost, .timedOut:
                connectionError = true
                connected = false
                errorMessage = "Le Raspberry est injoignable. Vérifiez son adresse, le Wi-Fi et l’autorisation Réseau local dans Réglages iOS."
            default:
                connectionError = false
                errorMessage = "La connexion a échoué. \(error.localizedDescription)"
            }
        } else {
            connectionError = false
            errorMessage = error.localizedDescription
        }
    }
}

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
