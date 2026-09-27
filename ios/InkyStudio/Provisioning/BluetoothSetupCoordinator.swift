import Foundation
import Combine
import Darwin

@MainActor
protocol ProvisioningConnection: AnyObject {
    func connect(peripheralID: UUID, identity: FrameIdentity) async throws -> PinnedFrameTrust
    func request(_ data: Data, timeout: TimeInterval) async throws -> Data
    func disconnect()
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
    #endif

    init(channel: any ProvisioningConnection, vault: any OwnershipStorage,
         confirmHTTPS: @escaping (URL, OwnershipRecord, UUID) async throws -> String,
         didFinish: @escaping (URL, OwnershipRecord) async -> Void) {
        self.channel = channel
        self.vault = vault
        self.confirmHTTPS = confirmHTTPS
        self.didFinish = didFinish
    }

    var isWorking: Bool { [.preparingQR, .connecting, .claiming, .applying].contains(stage) }
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
              ["networks", "credentials", "confirming", "rolledback"].contains(name) else { return false }
        uiTestFixture = true
        networks = [ProvisioningNetwork(ssid: "Atelier", security: "wpa2", strength: 90),
                    ProvisioningNetwork(ssid: "Maison", security: "wpa2", strength: 72),
                    ProvisioningNetwork(ssid: "Réseau invités", security: "open", strength: 58)]
        currentSSID = "Maison"
        selectedSSID = "Atelier"
        remainingSeconds = 150
        errorMessage = nil
        switch name {
        case "credentials": stage = .credentials
        case "confirming": stage = .confirming
        case "rolledback": stage = .rolledBack
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
        do {
            let code = try FrameAdoptionCode.parse(text)
            let saved = try vault.load(id: code.identity.id)
            if let saved, saved.identity != code.identity { throw OwnershipVaultError.identityChanged }
            resetChannel()
            identity = code.identity
            adoptionCode = code
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
        selectedSSID = record.wifiSSID ?? ""
        errorMessage = nil
        stage = .nearby
    }

    func connect(peripheralID: UUID) async {
        guard !isUITestFixture else { return }
        guard let identity, !isWorking else { return }
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
        guard owner?.state == .claimed, !scanningNetworks, !hasTransaction else { return }
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
            let result: WiFiStatus = try await command("wifi.cancel", fields: ["transaction_id": transactionID.uuidString.lowercased()])
            try check(epoch)
            guard result.id == transactionID else { throw ProvisioningFailure.invalidResponse }
            if result.state == .rolledBack || result.state == .failed {
                try finishRollback(transactionID: transactionID)
            } else { startMonitoring() }
        } catch { if epoch == generation { show(error); stage = .suspended } }
    }

    func suspend() {
        guard !isUITestFixture else { return }
        guard ![.introduction, .scanQR, .completed, .rolledBack].contains(stage) else { return }
        resetChannel()
        scanningNetworks = false
        // Preparing the e-ink QR may take long enough for the phone to lock.
        // Without a scanned identity, discovery cannot safely select a frame.
        stage = identity == nil ? .scanQR : .suspended
    }

    func resume() async {
        guard stage == .suspended else { return }
        if let peripheralID { await connect(peripheralID: peripheralID) }
        else { stage = .nearby }
    }

    func close() { resetChannel(); adoptionCode = nil }

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
                    for endpoint in endpoints(addresses: status.addresses) {
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
                            completedEndpoint = endpoint
                            errorMessage = nil
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
    }
    private func show(_ error: Error) {
        guard !(error is CancellationError) else { return }
        if error is FrameIdentityError || error is OwnershipVaultError || error is ProvisioningFailure || error is QRScannerFailure {
            errorMessage = error.localizedDescription
        } else { errorMessage = "La connexion au cadre a été interrompue. Rapprochez l’iPhone du cadre puis réessayez." }
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
