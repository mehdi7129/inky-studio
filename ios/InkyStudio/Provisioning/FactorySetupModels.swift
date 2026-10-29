import Foundation

enum FactorySetupError: Error, Equatable, LocalizedError, Sendable {
    case invalidMessage, identityMismatch, negotiationRequired, missingCheckpoint, checkpointConflict
    case storageUnavailable, requestInProgress, invalidated
    case remote(String)

    var errorDescription: String? {
        switch self {
        case .storageUnavailable: return "L’étape de configuration n’a pas pu être enregistrée. Déverrouillez l’iPhone puis réessayez."
        case .checkpointConflict: return "Cette tentative est déjà enregistrée avec d’autres paramètres. Reprenez-la ou lancez explicitement une nouvelle tentative."
        case .missingCheckpoint: return "La tentative doit être retrouvée sur le cadre avant de poursuivre."
        default: return "La configuration du cadre n’a pas pu être confirmée. Reconnectez-vous pour vérifier son état."
        }
    }
}

struct FactorySetupBinding: Codable, Equatable, Sendable {
    let identity: FrameIdentity
    let ownerID: UUID
    let claimRequestID: UUID

    init(owner: OwnershipRecord) {
        identity = owner.identity
        ownerID = owner.ownerID
        claimRequestID = owner.claimRequestID
    }
}

struct FactoryBootstrapStatus: Equatable, Sendable {
    let frameID: UUID
    let ownerID: UUID
    let claimRequestID: UUID
}

struct FactorySetupNegotiation: Equatable, Sendable {
    let latestOperationID: UUID?
    let selectedVersion = 2
}

struct FactorySetupChallenge: Codable, Equatable, Sendable {
    let operationID: UUID
    let challengeID: UUID
    let nonce: Data
    let bootID: UUID
    let issuedBoottimeNS: UInt64
    let expiresBoottimeNS: UInt64
}

struct FactorySetupApplyAcknowledgement: Equatable, Sendable {
    let operationID: UUID
    let frameID: UUID
    let ownerID: UUID
    let claimRequestID: UUID
    // Registered is an in-memory acknowledgement, never durable completion.
    let state = FactorySetupState.applying
    let nextStep = FactorySetupNextStep.status
}

enum FactorySetupState: String, Codable, Sendable {
    case challengeIssued = "challenge_issued", applying, uncertain
    case setupReady = "setup_ready", tlsReady = "tls_ready", wifiPending = "wifi_pending"
    case complete, refused
}

enum FactorySetupNextStep: String, Codable, Sendable {
    case apply, status, recoverExplicit = "recover_explicit", continueSetup = "continue"
    case wifi, waitOrigin = "wait_origin", photoEnroll = "photo_enroll"
}

struct FactorySetupNormalIdentity: Equatable, Sendable {
    let identity: FrameIdentity
    let publicationOperationID: UUID
}

struct FactorySetupStatus: Equatable, Sendable {
    let operationID: UUID
    let state: FactorySetupState
    let frameID: UUID
    let ownerID: UUID
    let claimRequestID: UUID
    let normalIdentity: FactorySetupNormalIdentity?
    let httpsOrigin: URL?
    let completionID: UUID?
    let nextStep: FactorySetupNextStep
}

enum FactorySetupContinueAction: String, Sendable {
    case publicationFinalized = "publication_finalized", completionFinalized = "completion_finalized"
    case alreadyComplete = "already_complete", wifiPending = "wifi_pending"
}

struct FactorySetupContinuation: Equatable, Sendable {
    let status: FactorySetupStatus
    let action: FactorySetupContinueAction
}

enum FactorySetupValidation {
    static func country(_ value: String) -> Bool {
        value.utf8.count == 2 && value.utf8.allSatisfy { (65...90).contains($0) }
    }

    // Exact accepted clock policy from the frozen IPC contract, inside the wire's JSON-safe bound.
    static func utc(_ value: UInt64) -> Bool { (1_767_225_600...4_102_444_799).contains(value) }

    static func challenge(_ value: FactorySetupChallenge) -> Bool {
        value.nonce.count == 32 && value.issuedBoottimeNS <= UInt64(Int64.max)
        && value.expiresBoottimeNS <= UInt64(Int64.max)
        && value.expiresBoottimeNS >= value.issuedBoottimeNS
        && value.expiresBoottimeNS - value.issuedBoottimeNS == 30_000_000_000
    }

    static func hex(_ data: Data) -> String { data.map { String(format: "%02x", $0) }.joined() }

    static func origin(_ string: String) throws -> URL {
        // This is the explicit OS-observed factory origin, never an inferred SAN or host.
        let prefix = "https://inky-", suffix = ".local:8443"
        guard string.utf8.count <= 267, string.hasPrefix(prefix), string.hasSuffix(suffix) else {
            throw FactorySetupError.invalidMessage
        }
        let hostID = string.dropFirst(prefix.count).dropLast(suffix.count)
        guard hostID.utf8.count == 32, hostID.utf8.allSatisfy({ (48...57).contains($0) || (97...102).contains($0) }),
              let url = URL(string: string), url.absoluteString == string,
              url.scheme == "https", url.port == 8443, url.user == nil, url.password == nil,
              url.path.isEmpty, url.query == nil, url.fragment == nil else { throw FactorySetupError.invalidMessage }
        return url
    }
}
