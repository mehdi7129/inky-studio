import Foundation
import Combine
import Darwin

@MainActor
protocol ProvisioningConnection: AnyObject {
    func connect(peripheralID: UUID, identity: FrameIdentity) async throws -> PinnedFrameTrust
    func request(_ data: Data, timeout: TimeInterval) async throws -> Data
    func connectBootstrap(peripheralID: UUID, identity: FrameIdentity) async throws -> BootstrapFrameTrust
    func requestBootstrap(_ data: Data, timeout: TimeInterval) async throws -> Data
    func disconnect()
}

extension ProvisioningConnection {
    func connectBootstrap(peripheralID: UUID, identity: FrameIdentity) async throws -> BootstrapFrameTrust { throw BluetoothTransportError.unsupportedFrame }
    func requestBootstrap(_ data: Data, timeout: TimeInterval) async throws -> Data { throw BluetoothTransportError.unsupportedFrame }
}
extension SecureBluetoothChannel: ProvisioningConnection {}

@MainActor
protocol OwnershipStorage {
    func allRecords() throws -> [OwnershipRecord]
    func load(id: UUID) throws -> OwnershipRecord?
    func prepare(identity: FrameIdentity, certificateDER: Data, endpoint: URL?) throws -> OwnershipRecord
    func markClaimed(id: UUID, endpoint: URL?) throws -> OwnershipRecord
    func refreshCertificate(id: UUID, certificateDER: Data) throws -> OwnershipRecord
    func replaceUnauthorizedOwner(id: UUID, certificateDER: Data) throws -> OwnershipRecord
    func beginWiFiTransaction(id: UUID, transactionID: UUID, ssid: String) throws -> OwnershipRecord
    func finishWiFiTransaction(id: UUID, transactionID: UUID) throws -> OwnershipRecord
    func prepareBootstrap(identity: FrameIdentity, certificateDER: Data) throws -> OwnershipRecord
    func refreshBootstrapCertificate(id: UUID, certificateDER: Data) throws -> OwnershipRecord
    func promoteFactoryNormal(id: UUID, certificateDER: Data) throws -> OwnershipRecord
    func setFactoryOperation(id: UUID, operationID: UUID) throws -> OwnershipRecord
    func expectFactoryNormal(id: UUID) throws -> OwnershipRecord
    func markFactoryPhotoCompleted(id: UUID) throws -> OwnershipRecord
}

extension OwnershipStorage {
    func prepareBootstrap(identity: FrameIdentity, certificateDER: Data) throws -> OwnershipRecord { throw OwnershipVaultError.unavailable }
    func refreshBootstrapCertificate(id: UUID, certificateDER: Data) throws -> OwnershipRecord { throw OwnershipVaultError.unavailable }
    func promoteFactoryNormal(id: UUID, certificateDER: Data) throws -> OwnershipRecord { throw OwnershipVaultError.unavailable }
    func setFactoryOperation(id: UUID, operationID: UUID) throws -> OwnershipRecord { throw OwnershipVaultError.unavailable }
    func expectFactoryNormal(id: UUID) throws -> OwnershipRecord { throw OwnershipVaultError.unavailable }
    func markFactoryPhotoCompleted(id: UUID) throws -> OwnershipRecord { throw OwnershipVaultError.unavailable }
}
extension OwnershipVault: OwnershipStorage {}

struct ProvisioningNetwork: Decodable, Equatable, Identifiable, Sendable {
    let ssid: String
    let security: String
    let strength: Int
    var id: String { ssid + "\u{0}" + security }
    var supported: Bool { security == "wpa2" && !ssid.isEmpty && ssid.utf8.count <= 32 }
}

@MainActor
final class BluetoothSetupCoordinator: ObservableObject {
    enum Stage: Equatable {
        case introduction, preparingQR, scanQR, nearby, connecting, claiming
        case networks, credentials, applying, confirming, suspended, completed, rolledBack
        case factoryCountry, factoryApplying, factoryContinue, factoryHandoff, factoryWaitingOrigin, factoryRecovery, factoryPhotoAccess
    }

    @Published private(set) var stage: Stage = .introduction
    @Published private(set) var savedFrames: [OwnershipRecord] = []
    @Published private(set) var networks: [ProvisioningNetwork] = []
    @Published private(set) var currentSSID: String?
    @Published private(set) var selectedSSID = ""
    @Published private(set) var remainingSeconds: Int?
    @Published private(set) var errorMessage: String?
    @Published private(set) var owner: OwnershipRecord?
    @Published private(set) var scanningNetworks = false
    @Published private(set) var completedEndpoint: URL?
    @Published private(set) var discoveryProfile: BluetoothProfile = .normalV1
    @Published private(set) var selectedCountry = ""
    @Published private(set) var factoryStatus: FactorySetupStatus?
    private let factoryCheckpoints: any FactorySetupCheckpointStorage
    private let authorizeFactory: (() async -> Bool)?
    private let didFinishFactory: ((URL, OwnershipRecord, FactorySetupStatus) async -> Bool)?
    private let factoryUTCNow: () -> UInt64
    private let factoryPollDelay: () async throws -> Void
    private var bootstrapCode: FrameBootstrapCode?
    private var factoryClient: FactorySetupClient?
    private var factoryOperationID: UUID?

    private let channel: any ProvisioningConnection
    private let vault: any OwnershipStorage
    private let confirmHTTPS: (URL, OwnershipRecord, UUID) async throws -> String
    private let didFinish: (URL, OwnershipRecord) async -> Void
    private var adoptionCode: FrameAdoptionCode?
    private var identity: FrameIdentity?
    private var peripheralID: UUID?
    private var httpsPort = 8443
    private var hostname: String?
    private var generation = UUID()
    private var monitor: Task<Void, Never>?
    #if DEBUG
    private var uiTestFixture = false
    private var uiTestFactoryFixture = false
    #endif

    init(channel: any ProvisioningConnection, vault: any OwnershipStorage,
         confirmHTTPS: @escaping (URL, OwnershipRecord, UUID) async throws -> String,
         authorizeFactory: (() async -> Bool)? = nil,
         factoryCheckpoints: any FactorySetupCheckpointStorage = FactorySetupKeychainCheckpointStore(),
         factoryUTCNow: @escaping () -> UInt64 = { UInt64(max(0, Date().timeIntervalSince1970.rounded(.down))) },
         factoryPollDelay: @escaping () async throws -> Void = { try await Task.sleep(for: .seconds(2)) },
         didFinishFactory: ((URL, OwnershipRecord, FactorySetupStatus) async -> Bool)? = nil,
         didFinish: @escaping (URL, OwnershipRecord) async -> Void) {
        self.channel = channel
        self.vault = vault
        self.confirmHTTPS = confirmHTTPS
        self.didFinish = didFinish
        self.authorizeFactory = authorizeFactory
        self.factoryCheckpoints = factoryCheckpoints
        self.factoryUTCNow = factoryUTCNow
        self.factoryPollDelay = factoryPollDelay
        self.didFinishFactory = didFinishFactory
    }

    var isWorking: Bool { [.preparingQR, .connecting, .claiming, .applying, .factoryApplying, .factoryHandoff].contains(stage) }
    var isFactory: Bool {
        #if DEBUG
        if uiTestFactoryFixture { return true }
        #endif
        return bootstrapCode != nil || owner?.isFactory == true
    }
    var hasTransaction: Bool { owner?.wifiTransactionID != nil }
    var isUITestFixture: Bool {
        #if DEBUG
        return uiTestFixture
        #else
        return false
        #endif
    }

    #if DEBUG
    /// Visual fixture only. It never creates ownership, a TLS connection, a Wi-Fi
    /// transaction or a success result, and is absent from Release builds.
    @discardableResult
    func installUITestFixture(named name: String) -> Bool {
        guard ProcessInfo.processInfo.arguments.contains("--uitesting"),
              ["networks", "credentials", "confirming", "rolledback", "factory-country", "factory-recovery", "factory-waiting"].contains(name) else { return false }
        uiTestFixture = true
        uiTestFactoryFixture = name.hasPrefix("factory-")
        networks = [ProvisioningNetwork(ssid: "Atelier", security: "wpa2", strength: 90),
                    ProvisioningNetwork(ssid: "Maison", security: "wpa2", strength: 72),
                    ProvisioningNetwork(ssid: "Réseau invités", security: "open", strength: 58)]
        currentSSID = "Maison"
        selectedSSID = "Atelier"
        remainingSeconds = 150
        errorMessage = nil
        selectedCountry = ""
        switch name {
        case "credentials": stage = .credentials
        case "confirming": stage = .confirming
        case "rolledback": stage = .rolledBack
        case "factory-country": stage = .factoryCountry
        case "factory-recovery": stage = .factoryRecovery
        case "factory-waiting": stage = .factoryWaitingOrigin
        default: stage = .networks
        }
        return true
    }
    #endif

    func loadSavedFrames() {
        do { savedFrames = try vault.allRecords() }
        catch { show(error) }
    }

    func showScanner() { errorMessage = nil; stage = .scanQR }
    func scannerFailed(_ error: Error) { show(error); stage = .scanQR }

    func displayQR(using beginWindow: () async throws -> Void) async {
        guard !isWorking else { return }
        let epoch = generation
        stage = .preparingQR
        errorMessage = nil
        do {
            try await beginWindow()
            try check(epoch)
            stage = .scanQR
        } catch { if epoch == generation { show(error); stage = .introduction } }
    }

    func acceptQRCode(_ text: String) {
        if let code = try? FrameBootstrapCode.parse(text) { acceptBootstrapCode(code); return }
        do {
            let code = try FrameAdoptionCode.parse(text)
            let saved = try vault.load(id: code.identity.id)
            if let saved, saved.identity != code.identity { throw OwnershipVaultError.identityChanged }
            resetChannel()
            identity = code.identity
            adoptionCode = code
            bootstrapCode = nil
            discoveryProfile = .normalV1
            factoryStatus = nil
            owner = saved
            errorMessage = nil
            stage = .nearby
        } catch { show(error); stage = .scanQR }
    }

    func selectSavedFrame(_ record: OwnershipRecord) {
        resetChannel()
        identity = record.identity
        owner = record
        adoptionCode = nil
        bootstrapCode = nil
        factoryStatus = nil
        factoryOperationID = record.factorySetupOperationID
        discoveryProfile = record.isFactory && record.factoryProfile == .bootstrap && record.factoryExpectedNormal != true ? .bootstrap : .normalV1
        selectedSSID = record.wifiSSID ?? ""
        errorMessage = nil
        stage = .nearby
    }

    func connect(peripheralID: UUID) async {
        guard !isUITestFixture else { return }
        guard let identity, !isWorking else { return }
        if isFactory { await connectFactory(peripheralID: peripheralID); return }
        self.peripheralID = peripheralID
        let epoch = generation
        errorMessage = nil
        stage = .connecting
        do {
            let fresh = try await channel.connect(peripheralID: peripheralID, identity: identity)
            try check(epoch)
            guard fresh.identity == identity else { throw FrameIdentityError.pinMismatch }
            if let existing = owner {
                owner = try vault.refreshCertificate(id: existing.id, certificateDER: fresh.certificateDER)
            } else {
                // A failed save must prevent the claim from being sent.
                owner = try vault.prepare(identity: identity, certificateDER: fresh.certificateDER, endpoint: nil)
            }
            guard let owner else { throw OwnershipVaultError.missing }
            stage = .claiming
            let status: FrameStatus
            if owner.state == .claimed {
                do { status = try await command("status") }
                catch ProvisioningFailure.server("unauthorized") {
                    guard let code = adoptionCode else {
                        channel.disconnect()
                        stage = .scanQR
                        errorMessage = "Ce téléphone n’est plus autorisé. Affichez puis scannez un nouveau QR sur le cadre."
                        return
                    }
                    // A new physical QR authorizes a fresh owner after revocation;
                    // a timeout alone must never replace the durable credential.
                    let replacement = try vault.replaceUnauthorizedOwner(id: owner.id, certificateDER: fresh.certificateDER)
                    self.owner = replacement
                    status = try await command("claim", requestID: replacement.claimRequestID,
                        fields: ["claim_token": code.adoptionToken.hexString], timeout: 90)
                }
            } else {
                do {
                    // A previous claim may have committed while its reply was lost.
                    status = try await command("status")
                } catch ProvisioningFailure.server("unauthorized") {
                    guard let code = adoptionCode else {
                        channel.disconnect()
                        stage = .scanQR
                        errorMessage = "Scannez le QR affiché sur le cadre pour terminer son association."
                        return
                    }
                    do {
                        status = try await command("claim", requestID: owner.claimRequestID,
                            fields: ["claim_token": code.adoptionToken.hexString], timeout: 90)
                    } catch ProvisioningFailure.server("unauthorized") {
                        // A lost claim reply can leave a local pending owner that
                        // was later revoked. Only an explicit authenticated refusal
                        // plus the scanned physical QR permits a new credential.
                        let replacement = try vault.replaceUnauthorizedOwner(id: owner.id, certificateDER: fresh.certificateDER)
                        self.owner = replacement
                        status = try await command("claim", requestID: replacement.claimRequestID,
                            fields: ["claim_token": code.adoptionToken.hexString], timeout: 90)
                    }
                }
            }
            try check(epoch)
            guard status.frameID == identity.id, (1...65535).contains(status.httpsPort) else {
                throw ProvisioningFailure.invalidResponse
            }
            httpsPort = status.httpsPort
            hostname = status.hostname
            self.owner = try vault.markClaimed(id: identity.id, endpoint: nil)
            adoptionCode = nil
            if self.owner?.wifiTransactionID != nil {
                selectedSSID = self.owner?.wifiSSID ?? ""
                startMonitoring()
            } else { await scanNetworks() }
        } catch {
            guard epoch == generation else { return }
            channel.disconnect()
            show(error)
            stage = hasTransaction ? .suspended : .nearby
        }
    }

    func scanNetworks() async {
        #if DEBUG
        if uiTestFixture { stage = .networks; return }
        #endif
        guard owner?.state == .claimed, !scanningNetworks, !hasTransaction,
              !isFactory || discoveryProfile == .normalV1 else { return }
        monitor?.cancel(); monitor = nil
        let epoch = generation
        stage = .networks
        scanningNetworks = true
        errorMessage = nil
        defer { if epoch == generation { scanningNetworks = false } }
        do {
            let result: NetworkScan = try await command("wifi.scan")
            try check(epoch)
            guard result.networks.count <= 128 else { throw ProvisioningFailure.invalidResponse }
            var seen = Set<String>()
            networks = result.networks.filter { !$0.ssid.isEmpty && $0.ssid.utf8.count <= 32 && seen.insert($0.id).inserted }
                .sorted { $0.strength > $1.strength }
            currentSSID = result.currentSSID
        } catch { if epoch == generation { show(error) } }
    }

    func chooseNetwork(_ network: ProvisioningNetwork?) {
        guard !isWorking, !hasTransaction else { return }
        guard network == nil || network?.supported == true else { return }
        selectedSSID = network?.ssid ?? ""
        errorMessage = nil
        stage = .credentials
    }

    static func validWiFiInput(ssid: String, password: String) -> Bool {
        guard !ssid.isEmpty, ssid.utf8.count <= 32, !ssid.contains("\0") else { return false }
        let bytes = Array(password.utf8)
        return (8...63).contains(bytes.count) ||
            (bytes.count == 64 && bytes.allSatisfy { (48...57).contains($0) || (65...70).contains($0) || (97...102).contains($0) })
    }

    func applyNetwork(ssid: String, password: String) async {
        #if DEBUG
        if uiTestFixture {
            guard stage == .credentials, Self.validWiFiInput(ssid: ssid, password: password) else { return }
            selectedSSID = ssid
            stage = .confirming
            return
        }
        #endif
        guard stage == .credentials, let owner, !hasTransaction else { return }
        guard Self.validWiFiInput(ssid: ssid, password: password) else {
            errorMessage = "Vérifiez le nom du réseau et son mot de passe WPA2."
            return
        }
        let epoch = generation
        let transactionID = UUID()
        errorMessage = nil
        stage = .applying
        if owner.isFactory {
            guard await authorizeFactory?() == true, epoch == generation else { if epoch == generation { stage = .credentials }; return }
        }
        do {
            self.owner = try vault.beginWiFiTransaction(id: owner.id, transactionID: transactionID, ssid: ssid)
            selectedSSID = ssid
            let result: WiFiStatus = try await command("wifi.begin", requestID: transactionID,
                fields: ["ssid": ssid, "security": "wpa2", "password": password])
            try check(epoch)
            guard result.id == transactionID else { throw ProvisioningFailure.invalidResponse }
            startMonitoring()
        } catch {
            guard epoch == generation else { return }
            show(error)
            // Never repeat begin after an ambiguous response. Query the saved ID.
            if hasTransaction { startMonitoring() } else { stage = .credentials }
        }
    }

    func cancelWiFi() async {
        #if DEBUG
        if uiTestFixture { stage = .rolledBack; return }
        #endif
        guard let owner, let transactionID = owner.wifiTransactionID, let peripheralID else { return }
        // Cancelling an in-flight TLS read closes that session. Reconnect before
        // issuing the explicit cancellation instead of overlapping two commands.
        resetChannel()
        let epoch = generation
        stage = .applying
        do {
            let fresh = try await channel.connect(peripheralID: peripheralID, identity: owner.identity)
            try check(epoch)
            guard fresh.identity == owner.identity else { throw FrameIdentityError.pinMismatch }
            self.owner = try vault.refreshCertificate(id: owner.id, certificateDER: fresh.certificateDER)
            if owner.isFactory {
                guard await authorizeFactory?() == true else { throw FactorySetupError.invalidated }
                try check(epoch)
                let client = makeFactoryClient(owner: owner, bootstrap: false)
                factoryClient = client
                let negotiated = try await client.negotiate()
                try check(epoch)
                guard let latest = negotiated.latestOperationID else { throw FactorySetupError.missingCheckpoint }
                factoryOperationID = latest
            }
            let result: WiFiStatus = try await command("wifi.cancel", fields: ["transaction_id": transactionID.uuidString.lowercased()])
            try check(epoch)
            guard result.id == transactionID else { throw ProvisioningFailure.invalidResponse }
            if result.state == .rolledBack || result.state == .failed {
                try finishRollback(transactionID: transactionID)
            } else { startMonitoring() }
        } catch { if epoch == generation { show(error); stage = .suspended } }
    }

    func suspend() {
        let needsBootstrapRescan = bootstrapCode != nil && owner == nil && discoveryProfile == .bootstrap
        bootstrapCode = nil
        guard !isUITestFixture else { return }
        guard ![.introduction, .scanQR, .completed, .rolledBack].contains(stage) else { return }
        resetChannel()
        scanningNetworks = false
        if needsBootstrapRescan {
            // The physical QR secret was purged. Do not resume as a normal
            // connection when no durable bootstrap owner exists yet.
            errorMessage = "Scannez à nouveau le QR du cadre pour reprendre la configuration."
            stage = .scanQR
            return
        }
        // Preparing the e-ink QR may take long enough for the phone to lock.
        // Without a scanned identity, discovery cannot safely select a frame.
        stage = identity == nil ? .scanQR : .suspended
    }

    func resume() async {
        guard stage == .suspended else { return }
        if let peripheralID { await connect(peripheralID: peripheralID) }
        else { stage = .nearby }
    }

    func close() { resetChannel(); adoptionCode = nil; bootstrapCode = nil }

    private func startMonitoring() {
        monitor?.cancel()
        stage = .confirming
        let epoch = generation
        monitor = Task { [weak self] in await self?.monitorWiFi(epoch: epoch) }
    }

    private func monitorWiFi(epoch: UUID) async {
        guard let owner, let transactionID = owner.wifiTransactionID else { return }
        while !Task.isCancelled, epoch == generation {
            do {
                let status: WiFiStatus = try await command("wifi.status", fields: ["transaction_id": transactionID.uuidString.lowercased()])
                try check(epoch)
                guard status.id == transactionID else { throw ProvisioningFailure.invalidResponse }
                remainingSeconds = max(0, min(status.remainingSeconds, 180))
                if status.state == .rolledBack || status.state == .failed {
                    try finishRollback(transactionID: transactionID)
                    return
                }
                if status.state == .awaitingConfirmation || status.state == .committed {
                    let candidates: [URL]
                    if owner.isFactory {
                        guard let client = factoryClient, let operationID = factoryOperationID else { throw FactorySetupError.missingCheckpoint }
                        let setup = try await client.status(operationID: operationID)
                        try check(epoch)
                        guard setup.normalIdentity?.identity == owner.identity else { throw FactorySetupError.identityMismatch }
                        factoryStatus = setup
                        candidates = setup.httpsOrigin.map { [$0] } ?? []
                    } else { candidates = endpoints(addresses: status.addresses) }
                    for endpoint in candidates {
                        let state: String
                        do {
                            state = try await confirmHTTPS(endpoint, owner, transactionID)
                            try check(epoch)
                        } catch is CancellationError { return }
                        catch { continue /* This iPhone may still be moving onto the new LAN. */ }
                        if state == "committed" {
                            _ = try vault.markClaimed(id: owner.id, endpoint: endpoint)
                            let finished = try vault.finishWiFiTransaction(id: owner.id, transactionID: transactionID)
                            self.owner = finished
                            errorMessage = nil
                            if finished.isFactory && finished.factoryPhotoAccessComplete != true {
                                stage = .factoryContinue
                                return
                            }
                            completedEndpoint = endpoint
                            stage = .completed
                            channel.disconnect()
                            await didFinish(endpoint, finished)
                            return
                        }
                    }
                }
                try await Task.sleep(for: .seconds(2))
            } catch ProvisioningFailure.server("not_found") {
                guard epoch == generation else { return }
                do { self.owner = try vault.finishWiFiTransaction(id: owner.id, transactionID: transactionID) }
                catch { show(error); stage = .suspended; return }
                errorMessage = "Cet essai Wi-Fi n’est plus actif. Vous pouvez choisir un réseau et recommencer."
                stage = .rolledBack
                return
            } catch {
                guard epoch == generation, !Task.isCancelled else { return }
                show(error)
                stage = .suspended
                return
            }
        }
    }

    private func finishRollback(transactionID: UUID) throws {
        guard let owner else { throw OwnershipVaultError.missing }
        self.owner = try vault.finishWiFiTransaction(id: owner.id, transactionID: transactionID)
        remainingSeconds = nil
        errorMessage = nil
        stage = .rolledBack
    }

    private func endpoints(addresses: [String]) -> [URL] {
        var hosts = addresses.prefix(8).filter { value in
            var address = in_addr()
            return value.withCString { inet_pton(AF_INET, $0, &address) } == 1
        }
        if let hostname, hostname.hasSuffix(".local"), hostname.utf8.count <= 253,
           hostname.utf8.allSatisfy({ (45...46).contains($0) || (48...57).contains($0) || (65...90).contains($0) || (97...122).contains($0) }) {
            hosts.append(hostname)
        }
        return hosts.compactMap { host in
            var parts = URLComponents()
            parts.scheme = "https"
            parts.host = host
            parts.port = httpsPort
            return parts.url
        }
    }

    private func command<Result: Decodable>(_ operation: String, requestID: UUID = UUID(),
                                           fields: [String: String] = [:], timeout: TimeInterval = 20) async throws -> Result {
        guard let owner else { throw OwnershipVaultError.missing }
        let epoch = generation
        var body: [String: Any] = ["v": 1, "id": requestID.uuidString.lowercased(), "op": operation,
                                  "owner_id": owner.ownerID.uuidString.lowercased(), "owner_token": owner.ownerTokenHex]
        for (key, value) in fields { body[key] = value }
        let data = try JSONSerialization.data(withJSONObject: body, options: [.sortedKeys])
        guard data.count <= 16384 else { throw ProvisioningFailure.invalidResponse }
        let received = try await channel.request(data, timeout: timeout)
        try check(epoch)
        guard received.count <= 16384,
              let response = try? JSONDecoder().decode(CommandResponse<Result>.self, from: received),
              response.v == 1, response.id == requestID else { throw ProvisioningFailure.invalidResponse }
        guard response.ok else { throw ProvisioningFailure.server(response.error ?? "unavailable") }
        guard let result = response.result else { throw ProvisioningFailure.invalidResponse }
        return result
    }

    private func check(_ epoch: UUID) throws {
        guard epoch == generation, !Task.isCancelled else { throw CancellationError() }
    }
    private func resetChannel() {
        generation = UUID()
        monitor?.cancel()
        monitor = nil
        channel.disconnect()
        factoryClient?.invalidate()
        factoryClient = nil
    }
    private func show(_ error: Error) {
        guard !(error is CancellationError) else { return }
        if error is FrameIdentityError || error is OwnershipVaultError || error is ProvisioningFailure || error is QRScannerFailure || error is FactorySetupError {
            errorMessage = error.localizedDescription
        } else { errorMessage = "La connexion au cadre a été interrompue. Rapprochez l’iPhone du cadre puis réessayez." }
    }
}

extension BluetoothSetupCoordinator {
    func acceptBootstrapCode(_ code: FrameBootstrapCode) {
        do {
            let saved = try vault.load(id: code.identity.id)
            if let saved {
                guard saved.identity == code.identity, saved.isFactory else { throw OwnershipVaultError.identityChanged }
            }
            resetChannel()
            identity = code.identity
            bootstrapCode = code
            adoptionCode = nil
            owner = saved
            factoryStatus = nil
            factoryOperationID = saved?.factorySetupOperationID
            selectedCountry = ""
            discoveryProfile = saved?.factoryProfile == .normalV1 || saved?.factoryExpectedNormal == true ? .normalV1 : .bootstrap
            errorMessage = nil
            stage = .nearby
        } catch { show(error); stage = .scanQR }
    }

    func chooseCountry(_ value: String) {
        guard [.factoryCountry, .factoryRecovery].contains(stage), FactorySetupValidation.country(value) else { return }
        selectedCountry = value
        errorMessage = nil
    }

    /// The only clock/country mutation entry point. Resume and polling never call it.
    func beginFactorySystemSetup() async {
        guard [.factoryCountry, .factoryRecovery].contains(stage), FactorySetupValidation.country(selectedCountry),
              let client = factoryClient, let owner, owner.isFactory else { return }
        let epoch = generation
        let previousStage = stage
        stage = .factoryApplying
        guard await authorizeFactory?() == true else { if epoch == generation { stage = previousStage }; return }
        guard epoch == generation else { return }
        let supersedes = factoryOperationID
        errorMessage = nil
        do {
            let checkpoint = try client.prepareOperation(country: selectedCountry, supersedesOperationID: supersedes)
            self.owner = try vault.setFactoryOperation(id: owner.id, operationID: checkpoint.operationID)
            factoryOperationID = checkpoint.operationID
            _ = try await client.challenge()
            try check(epoch)
            // Sample once after the real challenge; the client persists exact UTC/country before sending apply.
            _ = try await client.apply(utcSeconds: factoryUTCNow())
            try check(epoch)
            startFactoryPolling(operationID: checkpoint.operationID)
        } catch {
            guard epoch == generation else { return }
            show(error)
            stage = .factoryRecovery
        }
    }

    /// Explicit DATA-ONLY continuation, never admitted from status/next_step or scene activation.
    func continueFactorySetup() async {
        guard [.factoryContinue, .networks].contains(stage), !scanningNetworks, let client = factoryClient,
              let owner, let operationID = factoryOperationID else { return }
        let epoch = generation
        let previousStage = stage
        stage = .factoryApplying
        guard await authorizeFactory?() == true else { if epoch == generation { stage = previousStage }; return }
        guard epoch == generation else { return }
        monitor?.cancel(); monitor = nil
        errorMessage = nil
        do {
            if discoveryProfile == .bootstrap {
                // Intention only: a lost reply may mean the bootstrap listener has already handed off.
                self.owner = try vault.expectFactoryNormal(id: owner.id)
            }
            let result = try await client.continueSetup(operationID: operationID)
            try check(epoch)
            await presentFactoryStatus(result.status, epoch: epoch)
            try check(epoch)
            if stage == .factoryPhotoAccess { await finishFactoryPhotoAccess() }
        } catch {
            guard epoch == generation else { return }
            show(error)
            stage = .suspended
        }
    }

    func refreshFactoryStatus() async {
        guard let client = factoryClient, let operationID = factoryOperationID else { return }
        let epoch = generation
        do {
            let status = try await client.status(operationID: operationID)
            try check(epoch)
            await presentFactoryStatus(status, epoch: epoch)
        } catch { if epoch == generation { show(error); stage = .suspended } }
    }

    func configureFactoryWiFi() async {
        guard isFactory, discoveryProfile == .normalV1, !isWorking else { return }
        // End a readonly origin poll before starting the existing serialized Wi-Fi operations.
        monitor?.cancel(); monitor = nil
        if let peripheralID { await connectFactory(peripheralID: peripheralID, preferWiFi: true) }
    }

    func finishFactoryPhotoAccess() async {
        guard stage == .factoryPhotoAccess, let owner, let status = factoryStatus,
              status.state == .complete, status.nextStep == .photoEnroll,
              status.normalIdentity?.identity == owner.identity, let origin = status.httpsOrigin,
              status.completionID != nil, discoveryProfile == .normalV1 else { return }
        let epoch = generation
        stage = .factoryApplying
        guard await authorizeFactory?() == true, epoch == generation else { if epoch == generation { stage = .factoryPhotoAccess }; return }
        guard let didFinishFactory else {
            errorMessage = "La configuration du cadre est conservée. Rouvrez-la pour terminer l’accès aux photos."
            stage = .factoryPhotoAccess
            return
        }
        let completed = await didFinishFactory(origin, owner, status)
        guard epoch == generation else { return }
        guard completed else {
            errorMessage = "L’accès photo n’a pas pu être finalisé. Vos accès précédents sont conservés ; vous pouvez réessayer."
            stage = .factoryPhotoAccess
            return
        }
        do { self.owner = try vault.markFactoryPhotoCompleted(id: owner.id) }
        catch {
            errorMessage = "L’accès photo est prêt. Sa dernière étape locale n’a pas pu être enregistrée ; elle pourra être vérifiée à la reprise."
        }
        completedEndpoint = origin
        stage = .completed
        channel.disconnect()
        factoryClient?.invalidate(); factoryClient = nil
    }
}

private extension BluetoothSetupCoordinator {
    func makeFactoryClient(owner: OwnershipRecord, bootstrap: Bool) -> FactorySetupClient {
        let channel = self.channel
        return FactorySetupClient(request: { data, timeout in
            if bootstrap { return try await channel.requestBootstrap(data, timeout: timeout) }
            return try await channel.request(data, timeout: timeout)
        }, owner: owner, checkpoints: factoryCheckpoints)
    }

    func normalServiceUnavailable(_ error: Error) -> Bool {
        // Never relax trust after a TLS, pin, name, certificate, identity or malformed-record failure.
        if let error = error as? BluetoothTransportError {
            return [.disconnected, .timeout, .unsupportedFrame].contains(error)
        }
        if let error = error as? SecureBluetoothError { return [.notConnected, .timeout].contains(error) }
        return false
    }

    func connectFactory(peripheralID: UUID, preferWiFi: Bool = false) async {
        guard !isUITestFixture, let identity, !isWorking else { return }
        let epoch = generation
        let previousStage = stage
        stage = .connecting
        guard await authorizeFactory?() == true else { if epoch == generation { stage = previousStage }; return }
        guard epoch == generation else { return }
        self.peripheralID = peripheralID
        if owner?.factoryExpectedNormal == true || owner?.factoryProfile == .normalV1 { discoveryProfile = .normalV1 }
        monitor?.cancel(); monitor = nil
        factoryClient?.invalidate(); factoryClient = nil
        channel.disconnect()
        stage = .connecting
        errorMessage = nil
        do {
            var usingBootstrap = discoveryProfile == .bootstrap
            if !usingBootstrap {
                do {
                    let normal = try await channel.connect(peripheralID: peripheralID, identity: identity)
                    try check(epoch)
                    guard normal.identity == identity else { throw FrameIdentityError.pinMismatch }
                    guard let saved = owner, saved.isFactory else { throw OwnershipVaultError.missing }
                    self.owner = try vault.promoteFactoryNormal(id: saved.id, certificateDER: normal.certificateDER)
                } catch {
                    guard owner?.factoryProfile == .bootstrap, owner?.factoryExpectedNormal == true,
                          normalServiceUnavailable(error) else { throw error }
                    // Before normal has ever been verified, an explicit resume may discover
                    // that publication never happened. Reconnect only to the same persisted pin.
                    channel.disconnect()
                    usingBootstrap = true
                }
            }
            if usingBootstrap {
                let bootstrap = try await channel.connectBootstrap(peripheralID: peripheralID, identity: identity)
                try check(epoch)
                guard bootstrap.identity == identity else { throw FrameIdentityError.pinMismatch }
                if let saved = owner {
                    guard saved.factoryProfile == .bootstrap else { throw OwnershipVaultError.identityChanged }
                    self.owner = try vault.refreshBootstrapCertificate(id: saved.id, certificateDER: bootstrap.certificateDER)
                } else {
                    self.owner = try vault.prepareBootstrap(identity: identity, certificateDER: bootstrap.certificateDER)
                }
                guard let owner else { throw OwnershipVaultError.missing }
                discoveryProfile = .bootstrap
                let client = makeFactoryClient(owner: owner, bootstrap: true)
                factoryClient = client
                stage = .claiming
                do { _ = try await client.bootstrapStatus() }
                catch FactorySetupError.remote("unauthorized") {
                    guard owner.state == .pending, let code = bootstrapCode else {
                        throw FactorySetupError.remote("unauthorized")
                    }
                    _ = try await client.bootstrapClaim(claimToken: code.adoptionToken)
                }
                try check(epoch)
                bootstrapCode = nil
                self.owner = try vault.markClaimed(id: owner.id, endpoint: nil)
            } else { discoveryProfile = .normalV1 }
            guard let owner, owner.state == .claimed else { throw OwnershipVaultError.missing }
            let client = makeFactoryClient(owner: owner, bootstrap: usingBootstrap)
            factoryClient = client
            let negotiation = try await client.negotiate()
            try check(epoch)
            if let checkpoint = try client.checkpoint() { selectedCountry = checkpoint.country }
            if let latest = negotiation.latestOperationID {
                factoryOperationID = latest
                self.owner = try vault.setFactoryOperation(id: owner.id, operationID: latest)
                let status = try await client.status(operationID: latest)
                try check(epoch)
                if preferWiFi || owner.factoryPhotoAccessComplete == true {
                    guard discoveryProfile == .normalV1 else { throw FactorySetupError.invalidMessage }
                    factoryStatus = status
                    if self.owner?.wifiTransactionID != nil { startMonitoring() }
                    else { await scanNetworks() }
                } else { await presentFactoryStatus(status, epoch: epoch) }
            } else {
                factoryOperationID = nil
                factoryStatus = nil
                stage = .factoryCountry
            }
        } catch {
            guard epoch == generation else { return }
            channel.disconnect()
            factoryClient?.invalidate(); factoryClient = nil
            show(error)
            stage = .suspended
        }
    }

    func presentFactoryStatus(_ status: FactorySetupStatus, epoch: UUID) async {
        guard epoch == generation, let owner, status.frameID == owner.id,
              status.ownerID == owner.ownerID, status.claimRequestID == owner.claimRequestID else { return }
        factoryStatus = status
        factoryOperationID = status.operationID
        if let normal = status.normalIdentity {
            guard normal.identity == owner.identity else { show(FactorySetupError.identityMismatch); stage = .suspended; return }
            if discoveryProfile == .bootstrap {
                do { self.owner = try vault.expectFactoryNormal(id: owner.id) }
                catch { show(error); stage = .suspended; return }
                discoveryProfile = .normalV1
                stage = .factoryHandoff
                // No bootstrap RPC is replayed. A fresh normal handshake and negotiation
                // retrieve the same operation even when the publication response was lost.
                stage = .nearby
                if let peripheralID {
                    Task { [weak self] in
                        guard let self, self.generation == epoch, self.stage == .nearby else { return }
                        await self.connectFactory(peripheralID: peripheralID)
                    }
                }
                return
            }
        }
        switch status.nextStep {
        case .status:
            stage = .factoryApplying
            startFactoryPolling(operationID: status.operationID)
        case .apply, .recoverExplicit:
            stage = .factoryRecovery
        case .continueSetup:
            stage = .factoryContinue
        case .wifi:
            stage = .networks
            scheduleFactoryWiFiScan(epoch: epoch)
        case .waitOrigin:
            if status.state == .complete {
                stage = .factoryWaitingOrigin
                startFactoryPolling(operationID: status.operationID)
            } else {
                // Null origin does not prevent BLE Wi-Fi scan/begin/status before an IP exists.
                stage = .networks
                scheduleFactoryWiFiScan(epoch: epoch)
            }
        case .photoEnroll:
            stage = .factoryPhotoAccess
        }
    }

    func scheduleFactoryWiFiScan(epoch: UUID) {
        Task { [weak self] in
            guard let self, self.generation == epoch, self.stage == .networks else { return }
            await self.scanNetworks()
        }
    }

    func startFactoryPolling(operationID: UUID) {
        monitor?.cancel()
        let epoch = generation
        monitor = Task { [weak self] in
            guard let self else { return }
            while !Task.isCancelled, self.generation == epoch, let client = self.factoryClient {
                do {
                    let status = try await client.status(operationID: operationID)
                    try self.check(epoch)
                    self.factoryStatus = status
                    if status.nextStep != .status && !(status.nextStep == .waitOrigin && status.state == .complete) {
                        await self.presentFactoryStatus(status, epoch: epoch)
                        return
                    }
                    try await self.factoryPollDelay()
                } catch {
                    guard self.generation == epoch, !Task.isCancelled else { return }
                    self.show(error); self.stage = .suspended
                    return
                }
            }
        }
    }
}

private struct CommandResponse<Result: Decodable>: Decodable {
    let v: Int
    let id: UUID?
    let ok: Bool
    let result: Result?
    let error: String?
}
private struct FrameStatus: Decodable {
    let frameID: UUID
    let httpsPort: Int
    let hostname: String
    private enum CodingKeys: String, CodingKey { case frameID = "frame_id", httpsPort = "https_port", hostname }
}
private struct NetworkScan: Decodable {
    let networks: [ProvisioningNetwork]
    let currentSSID: String?
    private enum CodingKeys: String, CodingKey { case networks, currentSSID = "current_ssid" }
}
private struct WiFiStatus: Decodable {
    enum State: String, Decodable { case connecting, awaitingConfirmation = "awaiting_confirmation", committed, rolledBack = "rolled_back", failed }
    let id: UUID
    let state: State
    let addresses: [String]
    let remainingSeconds: Int
    private enum CodingKeys: String, CodingKey { case id, state, addresses, remainingSeconds = "remaining_seconds" }
}
private enum ProvisioningFailure: Error, LocalizedError {
    case invalidResponse, server(String)
    var errorDescription: String? {
        switch self {
        case .invalidResponse: return "Le cadre a envoyé une réponse inattendue. Reconnectez-vous pour vérifier son état."
        case .server(let code):
            switch code {
            case "unauthorized", "epoch_changed": return "Ce téléphone n’est plus autorisé. Scannez un nouveau QR affiché sur le cadre."
            case "qr_unavailable": return "Ce QR a expiré ou a déjà été utilisé. Affichez un nouveau QR sur le cadre."
            case "busy": return "Le cadre termine une autre configuration. Patientez puis réessayez."
            case "rate_limited": return "Trop de tentatives. Patientez une minute avant de réessayer."
            case "network_failed": return "Le cadre n’a pas pu rejoindre ce réseau. Vérifiez le mot de passe et réessayez."
            case "network_unavailable", "bluetooth_unavailable", "permission_denied": return "La configuration Wi-Fi n’est pas disponible sur ce cadre. Vérifiez sa version."
            case "conflict", "request_conflict": return "Une autre configuration est déjà associée à cet essai. Reprenez sa vérification."
            default: return "Le cadre n’a pas accepté cette opération. Reconnectez-vous pour vérifier son état."
            }
        }
    }
}

private extension Data {
    var hexString: String { map { String(format: "%02x", $0) }.joined() }
}
