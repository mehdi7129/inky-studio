import SwiftUI
import Combine

@MainActor
final class AppStore: ObservableObject {
    @Published var address = ""
    @Published var authenticated = false
    @Published var connecting = false
    @Published var connected = false
    @Published var refreshing = false
    @Published var busy = false
    @Published var displayBusy = false
    @Published var biometricEnabled = false
    @Published var passwordChangeSupported = false
    @Published var bluetoothSupported = false
    @Published var errorMessage: String?
    @Published var notice: String?
    @Published var state: DisplayState?
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
    let vault: BiometricVault
    private let defaults: UserDefaults
    private let makeAPI: @MainActor (URL) -> InkyAPI
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
         vault: BiometricVault = BiometricVault()) {
        self.defaults = defaults
        self.makeAPI = makeAPI
        self.vault = vault
        #if DEBUG
        if ProcessInfo.processInfo.arguments.contains("--uitesting") {
            defaults.removeObject(forKey: "frameAddress")
            defaults.removeObject(forKey: "biometricEnabled")
            defaults.removeObject(forKey: "frameOwnerID")
        }
        #endif
        address = defaults.string(forKey: "frameAddress") ?? ""
        biometricEnabled = defaults.bool(forKey: "biometricEnabled")
        #if DEBUG
        let args = ProcessInfo.processInfo.arguments
        if let index = args.firstIndex(of: "--frame-address"), args.indices.contains(index + 1) { address = args[index + 1] }
        #endif
        imageCache.totalCostLimit = 24 * 1024 * 1024
    }

    var hasSavedFrame: Bool { defaults.string(forKey: "frameAddress") != nil }
    var biometricName: String { vault.capability ?? "Face ID" }
    var panelWidth: Int { state?.display.width ?? 800 }
    var panelHeight: Int { state?.display.height ?? 480 }
    var canMutate: Bool { authenticated && connected && !busy && !updating }

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
        do {
            try FrameTrustPolicy(identity: owner.identity).validateHTTPS(endpoint)
            let epoch = generation
            let oldAccount = credentialAccount
            let sameAdoptedFrame = defaults.string(forKey: "frameOwnerID").flatMap(UUID.init(uuidString:)) == owner.id
            let upgradingCurrentFrame = authenticated && requestedAdoptionFrameID == owner.id
            let remembered = biometricEnabled && (sameAdoptedFrame || upgradingCurrentFrame)
            // Face ID explicitly unlocks the existing password before moving it
            // to the stable identity. No secret is recovered from the Pi.
            let password = remembered ? try? await vault.load(address: oldAccount) : nil
            guard epoch == generation, !Task.isCancelled else { return }
            _ = try ownershipVault.markClaimed(id: owner.id, endpoint: endpoint)
            resetSession()
            defaults.set(owner.id.uuidString.lowercased(), forKey: "frameOwnerID")
            address = endpoint.absoluteString
            defaults.set(address, forKey: "frameAddress")
            biometricEnabled = false
            defaults.set(false, forKey: "biometricEnabled")
            if let password {
                await login(password: password, rememberBiometric: true)
                if authenticated && biometricEnabled && oldAccount != credentialAccount {
                    try? vault.remove(address: oldAccount)
                }
            } else {
                notice = "Le cadre est connecté. Utilise son mot de passe habituel pour ouvrir tes photos."
            }
        } catch { handle(error) }
    }

    func cancelLogin() {
        guard connecting else { return }
        resetSession()
    }

    func login(password: String, rememberBiometric: Bool? = nil) async {
        guard !connecting else { return }
        resetSession()
        let epoch = generation
        connecting = true
        errorMessage = nil
        defer {
            if epoch == generation {
                connecting = false
                pendingClient = nil
            }
        }
        do {
            let url = try FrameAddress.parse(address)
            let normalized = url.absoluteString
            let previousAddress = defaults.string(forKey: "frameAddress")
            let client = try connectionClient(url)
            pendingClient = client
            let status = try await client.authStatus()
            guard epoch == generation, !Task.isCancelled else { return }
            if !status.authenticated {
                let response = try await client.login(password: password)
                guard epoch == generation, !Task.isCancelled else { return }
                guard response.authenticated else { throw APIError.unauthorized }
            }
            if previousAddress != normalized && defaults.string(forKey: "frameOwnerID") == nil {
                if let previousAddress { try? vault.remove(address: previousAddress) }
                biometricEnabled = false
                defaults.set(false, forKey: "biometricEnabled")
            }
            if rememberBiometric == true && status.authRequired && !password.isEmpty {
                do {
                    try vault.save(password: password, address: defaults.string(forKey: "frameOwnerID").map { "inky-frame:" + $0 } ?? normalized)
                    biometricEnabled = true
                } catch {
                    biometricEnabled = false
                    notice = error.localizedDescription
                }
                defaults.set(biometricEnabled, forKey: "biometricEnabled")
            } else if rememberBiometric == false && biometricEnabled {
                // An explicit unchecked switch disables the previously opted-in credential.
                // Biometric login passes nil and preserves the existing Keychain item.
                try vault.remove(address: credentialAccount)
                biometricEnabled = false
                defaults.set(false, forKey: "biometricEnabled")
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
            let supportsBluetooth = await client.bluetoothSupported()
            if epoch == generation { bluetoothSupported = supportsBluetooth }
            if epoch == generation { startMonitoring() }
        } catch {
            if epoch == generation { handle(error) }
        }
    }

    func loginWithBiometrics() async {
        guard !connecting else { return }
        errorMessage = nil
        connecting = true
        let epoch = generation
        defer { if epoch == generation { connecting = false } }
        do {
            let normalized = try FrameAddress.parse(address).absoluteString
            guard normalized == defaults.string(forKey: "frameAddress"), biometricEnabled else { throw VaultError.missing }
            let password = try await vault.load(address: credentialAccount)
            guard epoch == generation, !Task.isCancelled,
                  normalized == (try? FrameAddress.parse(address).absoluteString) else { return }
            connecting = false
            await login(password: password)
        } catch {
            guard epoch == generation else { return }
            connecting = false
            if let vaultError = error as? VaultError, case .missing = vaultError {
                biometricEnabled = false
                defaults.set(false, forKey: "biometricEnabled")
            }
            handle(error)
        }
    }

    func enableBiometrics(password: String) async {
        guard let api, !busy else { return }
        let epoch = generation
        let credentialAddress = credentialAccount
        busy = true
        defer { if epoch == generation { busy = false } }
        do {
            // Validate before replacing a previously stored credential.
            let status = try await api.login(password: password)
            guard epoch == generation, !Task.isCancelled else { return }
            guard status.authenticated, status.authRequired else { throw VaultError.unavailable }
            try vault.save(password: password, address: credentialAddress)
            biometricEnabled = true
            defaults.set(true, forKey: "biometricEnabled")
            notice = "La connexion avec \(biometricName) est activée."
        } catch { if epoch == generation { handle(error) } }
    }

    func disableBiometrics() {
        do {
            try vault.remove(address: credentialAccount)
            biometricEnabled = false
            defaults.set(false, forKey: "biometricEnabled")
        } catch { handle(error) }
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
        let remember = biometricEnabled
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
                do { try vault.save(password: new, address: credentialAddress) }
                catch {
                    biometricEnabled = false
                    defaults.set(false, forKey: "biometricEnabled")
                    message += " Face ID n’a pas pu être mis à jour. Utilisez votre nouveau mot de passe et réactivez-le dans Réglages."
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
                biometricEnabled = false
                defaults.set(false, forKey: "biometricEnabled")
            }
            resetSession()
            let message = "Le résultat n’a pas pu être confirmé. Essayez de vous reconnecter avec le nouveau mot de passe ; s’il est refusé, utilisez l’ancien."
            errorMessage = message
            return .failure(message)
        }
    }

    func logout(forget: Bool = false) async {
        let client = api
        let credentialAddress = credentialAccount
        // Complete every local change before suspension. The old client is isolated;
        // its eventual logout response must never mutate a newly connected frame.
        resetSession(clearClient: false)
        if forget {
            do {
                try vault.remove(address: credentialAddress)
                biometricEnabled = false
                defaults.set(false, forKey: "biometricEnabled")
                if let selected = defaults.string(forKey: "frameOwnerID"), let id = UUID(uuidString: selected) {
                    try ownershipVault.remove(id: id)
                }
                defaults.removeObject(forKey: "frameAddress")
                defaults.removeObject(forKey: "biometricEnabled")
                defaults.removeObject(forKey: "frameOwnerID")
                address = ""
            } catch {
                errorMessage = "Les identifiants de ce cadre n’ont pas tous pu être effacés. Déverrouillez l’iPhone puis réessayez Oublier ce cadre."
            }
        }
        if let client { _ = try? await client.logout() }
    }

    private func resetSession(clearClient: Bool = true) {
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
        guard authenticated, !passwordRotating, let api else { return }
        guard !refreshing else { requestedRefresh = true; return }
        refreshing = true
        let epoch = generation
        let identifier = UUID()
        refreshID = identifier
        historyRevision = UUID()
        loadingHistory = false
        defer {
            if epoch == generation, refreshID == identifier {
                refreshing = false
                refreshID = nil
            }
        }
        repeat {
            requestedRefresh = false
            do {
                async let s = api.state()
                async let q = api.queue()
                async let h = historySnapshot(api: api, count: max(history.count, 100))
                async let f = api.settings()
                async let v = api.health()
                let result = try await (s, q, h, f, v)
                guard epoch == generation else { return }
                state = result.0
                queue = result.1
                history = result.2.entries
                historyRevision = UUID()
                settings = result.3
                version = result.4.version
                hasMoreHistory = result.2.hasMore
                connected = true
                if connectionError { errorMessage = nil; connectionError = false }
                if updating, let expected = availableUpdate?.latest, version == expected {
                    updating = false
                    updateMessage = "Mise à jour terminée."
                }
            } catch {
                guard epoch == generation else { return }
                connected = false
                handle(error)
                return
            }
        } while requestedRefresh && authenticated && epoch == generation
    }

    private func historySnapshot(api: InkyAPI, count: Int) async throws -> (entries: [HistoryEntry], hasMore: Bool) {
        var entries: [HistoryEntry] = []
        // One look-ahead row makes the final page exact even when the existing
        // history length is a multiple of the page size.
        while entries.count <= count {
            try Task.checkCancellation()
            let limit = min(500, count + 1 - entries.count)
            let page = try await api.history(limit: limit, offset: entries.count)
            entries.append(contentsOf: page)
            if page.count < limit { return (entries, false) }
        }
        return (Array(entries.prefix(count)), true)
    }

    func loadMoreHistory() async {
        guard authenticated, !passwordRotating, let api, !loadingHistory, !refreshing, hasMoreHistory else { return }
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

    func sceneActive(_ isActive: Bool) {
        active = isActive
        if isActive, authenticated {
            startMonitoring()
            Task { await refresh() }
        } else if !isActive { stopMonitoring() }
    }

    private func startMonitoring() {
        guard active, authenticated, !passwordRotating, let api, monitoringID == nil else { return }
        let epoch = generation
        let identifier = UUID()
        monitoringID = identifier
        eventsTask = Task { [weak self] in
            do {
                for try await event in api.events() {
                    guard let self, !Task.isCancelled, self.generation == epoch,
                          self.monitoringID == identifier else { return }
                    if event.type == "connection_lost" || event.type == "reconnecting" {
                        self.connected = false
                    } else if event.type == "system_update" {
                        if case let .string(message)? = event.payload["message"] { self.updateMessage = message }
                        if case .string("error")? = event.payload["stage"] { self.updating = false }
                    } else { await self.refresh() }
                }
            } catch {
                guard let self, !Task.isCancelled, self.generation == epoch,
                      self.monitoringID == identifier else { return }
                self.connected = false
                self.handle(error)
            }
            if let self, self.generation == epoch, self.monitoringID == identifier {
                self.monitoringID = nil
                self.eventsTask = nil
                self.pollingTask?.cancel()
                self.pollingTask = nil
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

    private func stopMonitoring() {
        monitoringID = nil
        eventsTask?.cancel(); eventsTask = nil
        pollingTask?.cancel(); pollingTask = nil
        api?.stopEvents()
    }

    func image(for photo: Photo) async -> UIImage? {
        if let image = imageCache.object(forKey: photo.id as NSString) { return image }
        guard !passwordRotating, let api else { return nil }
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
        guard canMutate, !displayBusy, let api else { return }
        let epoch = generation
        displayBusy = true
        defer { if epoch == generation { displayBusy = false } }
        do {
            if previous { try await api.previous() } else { try await api.next() }
            guard epoch == generation else { return }
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
        guard canMutate, let api else { throw APIError.invalidResponse }
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
        guard canMutate, let api else { return }
        let epoch = generation
        await perform {
            let data = try await api.photoData(id: entry.photo.id)
            guard epoch == generation else { throw CancellationError() }
            _ = try await api.upload(png: data, filename: entry.photo.originalFilename)
        }
    }
    func remove(_ entry: QueueEntry) async {
        guard let api else { return }
        await perform { try await api.removeFromQueue(photoID: entry.photo.id) }
    }
    func reorder(_ ids: [String]) async {
        guard !ids.isEmpty, let api else { return }
        await perform { _ = try await api.reorderQueue(photoIDs: ids) }
    }
    func deleteHistory(_ entry: HistoryEntry) async {
        guard let api else { return }
        await perform { try await api.deleteHistoryEntry(id: entry.id) }
    }
    func clearHistory() async {
        guard let api else { return }
        await perform { try await api.clearHistory() }
    }
    func saveSettings(_ value: FrameSettings) async {
        guard let api else { return }
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
        guard let api, !busy else { return }
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
            default: errorMessage = "La connexion a échoué. \(error.localizedDescription)"
            }
        } else { errorMessage = error.localizedDescription }
    }
}

enum PasswordChangeResult: Equatable {
    case success(String)
    case failure(String)
}
