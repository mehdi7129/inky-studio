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
            let client = makeAPI(url)
            pendingClient = client
            let status = try await client.authStatus()
            guard epoch == generation, !Task.isCancelled else { return }
            if !status.authenticated {
                let response = try await client.login(password: password)
                guard epoch == generation, !Task.isCancelled else { return }
                guard response.authenticated else { throw APIError.unauthorized }
            }
            if previousAddress != normalized {
                if let previousAddress { try? vault.remove(address: previousAddress) }
                biometricEnabled = false
                defaults.set(false, forKey: "biometricEnabled")
            }
            if rememberBiometric == true && status.authRequired && !password.isEmpty {
                do {
                    try vault.save(password: password, address: normalized)
                    biometricEnabled = true
                } catch {
                    biometricEnabled = false
                    notice = error.localizedDescription
                }
                defaults.set(biometricEnabled, forKey: "biometricEnabled")
            } else if rememberBiometric == false && biometricEnabled {
                // An explicit unchecked switch disables the previously opted-in credential.
                // Biometric login passes nil and preserves the existing Keychain item.
                try vault.remove(address: normalized)
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
            connected = false
            imageCache.removeAllObjects()
            await refresh()
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
            let password = try await vault.load(address: normalized)
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
        let credentialAddress = address
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
            try vault.remove(address: address)
            biometricEnabled = false
            defaults.set(false, forKey: "biometricEnabled")
        } catch { handle(error) }
    }

    func logout(forget: Bool = false) async {
        let client = api
        let credentialAddress = address
        // Complete every local change before suspension. The old client is isolated;
        // its eventual logout response must never mutate a newly connected frame.
        resetSession(clearClient: false)
        if forget {
            do { try vault.remove(address: credentialAddress) }
            catch { errorMessage = error.localizedDescription }
            defaults.removeObject(forKey: "frameAddress")
            defaults.removeObject(forKey: "biometricEnabled")
            address = ""
            biometricEnabled = false
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
        guard authenticated, let api else { return }
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
        guard authenticated, let api, !loadingHistory, !refreshing, hasMoreHistory else { return }
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
        guard active, authenticated, let api, monitoringID == nil else { return }
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
        guard let api else { return nil }
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
