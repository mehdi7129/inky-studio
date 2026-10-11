import Foundation
import Combine

@MainActor protocol BootstrapConnection: AnyObject {
    func connect(peripheralID: UUID, identity: FrameIdentity) async throws -> BootstrapFrameTrust
    func request(_ data: Data, timeout: TimeInterval) async throws -> Data
    func disconnect()
}
extension BootstrapBluetoothChannel: BootstrapConnection {}

/// Closed association-only coordinator. No network, clock, certificate publication,
/// normal owner replacement, photo authentication or finishBluetoothSetup callback.
@MainActor final class BootstrapSetupCoordinator: ObservableObject {
    enum Stage: Equatable {
        case introduction, scanQR, nearby, connecting, checking, claiming
        case suspended, uncertain, recoveryRequired, adoptedAwaitingPreparation
    }
    @Published private(set) var stage: Stage = .introduction
    @Published private(set) var errorMessage: String?
    @Published private(set) var savedFrames: [BootstrapOwnershipRecord] = []
    @Published private(set) var owner: BootstrapOwnershipRecord?
    @Published private(set) var hasSavedIntention = false
    #if DEBUG
    private var uiTestFixture = false
    #endif
    var isUITestFixture: Bool {
        #if DEBUG
        return uiTestFixture
        #else
        return false
        #endif
    }
    #if DEBUG
    func installUITestFixture(named name: String) -> Bool {
        guard ProcessInfo.processInfo.arguments.contains("--uitesting") else { return false }
        switch name {
        case "introduction": stage = .introduction
        case "pending": stage = .adoptedAwaitingPreparation
        case "uncertain": stage = .uncertain
        case "recovery": stage = .recoveryRequired
        default: return false
        }
        uiTestFixture = true
        hasSavedIntention = name == "pending" || name == "uncertain"
        if name == "uncertain" || name == "recovery" { errorMessage = "L’association n’a pas pu être vérifiée. Votre autorisation est conservée." }
        if name == "recovery" { errorMessage = "Le trousseau sécurisé est indisponible. Déverrouillez l’iPhone puis réessayez." }
        return true
    }
    #endif
    private let channel: any BootstrapConnection
    private let vault: any BootstrapOwnershipStorage
    private var code: BootstrapAdoptionCode?
    private var identity: FrameIdentity?
    private var peripheralID: UUID?
    private var generation = UUID()
    // Once this process has seen a durable intention, local loss is recovery,
    // never permission to create another owner. This is a bounded memory guard,
    // not a second persistence/ownership ledger.
    private var knownIntentions: [UUID: BootstrapOwnershipRecord] = [:]
    var isWorking: Bool { [.connecting, .checking, .claiming].contains(stage) }

    init(channel: any BootstrapConnection, vault: any BootstrapOwnershipStorage) {
        self.channel = channel; self.vault = vault
    }
    func loadSavedFrames() {
        do {
            savedFrames = try vault.allRecords()
            for record in savedFrames { try remember(record) }
        } catch { hasSavedIntention = false; show(error); stage = .recoveryRequired }
    }
    func showScanner() { guard !isWorking else { return }; errorMessage = nil; stage = .scanQR }
    func scannerFailed(_ error: Error) { show(error); stage = .scanQR }
    func acceptQRCode(_ text: String) {
        guard !isWorking else { return }
        do {
            let accepted = try BootstrapAdoptionCode.parse(Data(text.utf8))
            let saved = try vault.load(id: accepted.identity.id)
            if let saved {
                guard saved.identity == accepted.identity else { throw OwnershipVaultError.identityChanged }
                try remember(saved)
            }
            if let known = knownIntentions[accepted.identity.id], known.identity != accepted.identity {
                throw OwnershipVaultError.identityChanged
            }
            resetChannel()
            identity = accepted.identity; code = accepted
            owner = saved ?? knownIntentions[accepted.identity.id]
            hasSavedIntention = saved != nil
            errorMessage = nil; stage = .nearby
        } catch {
            if error is BootstrapWireError { errorMessage = "Ce QR de premier démarrage n’est pas valide. Scannez le QR affiché sur votre nouveau cadre." }
            else { if error is OwnershipVaultError { hasSavedIntention = false }; show(error) }
            stage = .scanQR
        }
    }
    func selectSavedFrame(_ record: BootstrapOwnershipRecord) {
        guard !isWorking else { return }
        do {
            try record.validate()
            // Selection cannot revive a stale credential that disappeared from Keychain.
            guard let saved = try vault.load(id: record.id), saved == record else { throw OwnershipVaultError.missing }
            try remember(saved)
            resetChannel(); identity = saved.identity; owner = saved; code = nil; hasSavedIntention = true
            errorMessage = nil; stage = .nearby
        } catch { hasSavedIntention = false; show(error); stage = .recoveryRequired }
    }
    func connect(peripheralID: UUID) async {
        guard !isUITestFixture else { return }
        guard let identity, !isWorking else { return }
        self.peripheralID = peripheralID
        let generation = self.generation
        errorMessage = nil; stage = .connecting
        do {
            let fresh = try await channel.connect(peripheralID: peripheralID, identity: identity)
            try check(generation)
            guard fresh.identity == identity else { throw BootstrapWireError.identityMismatch }
            // Load/prepare and readback must succeed before *any* claim is emitted.
            if let stored = try vault.load(id: identity.id) {
                guard stored.identity == identity else { throw OwnershipVaultError.identityChanged }
                try remember(stored)
                owner = try vault.refreshCertificate(id: stored.id, certificateDER: fresh.certificateDER)
            } else {
                guard code != nil, knownIntentions[identity.id] == nil else { throw OwnershipVaultError.missing }
                guard knownIntentions.count < 8 else { throw OwnershipVaultError.capacityReached }
                owner = try vault.prepare(identity: identity, certificateDER: fresh.certificateDER)
            }
            guard let owner else { throw OwnershipVaultError.missing }
            try remember(owner)
            hasSavedIntention = true
            stage = .checking
            let status = try await sendStatus(owner, generation: generation)
            switch status {
            case .adoptedAwaitingPreparation: try finish(owner, generation: generation)
            case .failure(.unauthorized, correlated: true):
                // An unauthorized recovery is ambiguous after revocation/epoch change.
                // Only an explicit physical proof permits retrying this SAME intention.
                guard owner.state == .pending, let code, code.identity == identity else {
                    throw BootstrapSetupFailure.recovery(.unauthorized)
                }
                stage = .claiming
                let request = BootstrapRequest(operation: .claim, id: owner.claimRequestID,
                    ownerID: owner.ownerID, ownerToken: owner.ownerToken, proof: code.claimToken, claimRequestID: nil)
                let claim = try await command(request, owner: owner, generation: generation, timeout: 90)
                switch claim {
                case .adoptedAwaitingPreparation: try finish(owner, generation: generation)
                case .failure(.unavailable, correlated: true): throw BootstrapSetupFailure.uncertain
                case .failure(let error, correlated: true): throw BootstrapSetupFailure.recovery(error)
                case .failure(_, correlated: false): throw BootstrapSetupFailure.uncertain
                }
            case .failure(.unavailable, correlated: true): throw BootstrapSetupFailure.uncertain
            case .failure(let error, correlated: true): throw BootstrapSetupFailure.recovery(error)
            case .failure(_, correlated: false): throw BootstrapSetupFailure.uncertain
            }
        } catch {
            guard generation == self.generation else { return }
            channel.disconnect()
            show(error)
            // A saved intention survives all failures, including local acknowledgement failure.
            if let failure = error as? BootstrapSetupFailure, case .recovery = failure { stage = .recoveryRequired }
            else if error is OwnershipVaultError { hasSavedIntention = false; stage = .recoveryRequired }
            else { stage = owner == nil ? .nearby : .uncertain }
        }
    }
    func suspend() {
        guard !isUITestFixture else { return }
        guard ![.introduction, .scanQR].contains(stage) else { return }
        resetChannel()
        // Claimed is terminal locally but recovery still requires the same saved owner.
        if stage != .adoptedAwaitingPreparation { stage = identity == nil ? .scanQR : .suspended }
    }
    func resume() async {
        guard [.suspended, .uncertain, .recoveryRequired].contains(stage) else { return }
        if let peripheralID { await connect(peripheralID: peripheralID) }
        else if identity != nil { stage = .nearby }
        else { stage = .scanQR }
    }
    func close() { resetChannel(); code = nil }
    private func sendStatus(_ owner: BootstrapOwnershipRecord, generation: UUID) async throws -> BootstrapResponse {
        var rpcID = UUID()
        // Correlation and claim id are independently represented, including in recovery.
        while rpcID == owner.claimRequestID { rpcID = UUID() }
        return try await command(BootstrapRequest(operation: .status, id: rpcID, ownerID: owner.ownerID,
            ownerToken: owner.ownerToken, proof: nil, claimRequestID: owner.claimRequestID),
            owner: owner, generation: generation)
    }
    private func command(_ request: BootstrapRequest, owner: BootstrapOwnershipRecord,
                         generation: UUID, timeout: TimeInterval = 20) async throws -> BootstrapResponse {
        let received = try await channel.request(request.encoded(), timeout: timeout)
        try check(generation)
        return try BootstrapResponse.parse(received, context: BootstrapResponseContext(rpcID: request.id,
            frameID: owner.id, ownerID: owner.ownerID, claimRequestID: owner.claimRequestID))
    }
    private func finish(_ record: BootstrapOwnershipRecord, generation: UUID) throws {
        try check(generation)
        owner = try vault.markAdopted(record: record)
        if let owner { try remember(owner) }
        hasSavedIntention = true
        code = nil; errorMessage = nil; stage = .adoptedAwaitingPreparation
        channel.disconnect()
        savedFrames = try vault.allRecords()
    }
    private func remember(_ record: BootstrapOwnershipRecord) throws {
        try record.validate()
        if let known = knownIntentions[record.id] {
            guard known.identity == record.identity, known.ownerID == record.ownerID,
                  known.ownerToken == record.ownerToken, known.claimRequestID == record.claimRequestID,
                  known.state != .adoptedAwaitingPreparation || record.state == .adoptedAwaitingPreparation else {
                throw OwnershipVaultError.identityChanged
            }
        } else {
            guard knownIntentions.count < 8 else { throw OwnershipVaultError.capacityReached }
        }
        knownIntentions[record.id] = record
    }
    private func check(_ generation: UUID) throws {
        guard generation == self.generation, !Task.isCancelled else { throw CancellationError() }
    }
    private func resetChannel() { generation = UUID(); channel.disconnect() }
    private func show(_ error: Error) {
        guard !(error is CancellationError) else { return }
        if let failure = error as? BootstrapSetupFailure { errorMessage = failure.localizedDescription }
        else if error is OwnershipVaultError || error is FrameIdentityError || error is QRScannerFailure {
            errorMessage = error.localizedDescription
        } else if error is BootstrapWireError {
            errorMessage = "La réponse du cadre ne correspond pas à cette association. Votre autorisation enregistrée est conservée."
        } else {
            errorMessage = "L’association n’a pas pu être vérifiée. Reconnectez-vous par Bluetooth pour retrouver son état."
        }
    }
}

private enum BootstrapSetupFailure: Error, LocalizedError {
    case uncertain, recovery(BootstrapPublicError)
    var errorDescription: String? {
        switch self {
        case .uncertain, .recovery(.unavailable):
            return "La réponse du cadre manque. Votre autorisation est conservée ; reprenez la vérification par Bluetooth."
        case .recovery(.unauthorized), .recovery(.epochChanged):
            return "Le cadre n’a pas reconnu cette autorisation. Elle est conservée sur cet iPhone ; vérifiez le cadre avant de reprendre."
        case .recovery(.qrUnavailable): return "Le QR n’est plus disponible. Votre autorisation est conservée. Vérifiez l’écran du cadre."
        case .recovery(.rateLimited): return "Trop de tentatives. Patientez une minute avant de reprendre."
        case .recovery(.serviceStopping): return "Le cadre est en train de s’arrêter. Reprenez la vérification après son redémarrage."
        case .recovery(.recoveryRequired), .recovery(.requestConflict), .recovery(.requestNotFound):
            return "Cette association nécessite une vérification du cadre. L’autorisation existante est conservée sur cet iPhone."
        default: return "Le cadre a refusé cette association. Votre autorisation enregistrée est conservée."
        }
    }
}
