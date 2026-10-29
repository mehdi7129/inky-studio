import Foundation
import Security

struct OwnershipRecord: Codable, Equatable, Sendable {
    enum State: String, Codable, Sendable { case pending, claimed }
    enum FactoryProfile: String, Codable, Sendable { case bootstrap, normalV1 }
    let identity: FrameIdentity
    var certificateDER: Data
    let ownerID: UUID
    let claimRequestID: UUID
    let ownerToken: Data
    var endpoints: [URL]
    var state: State
    var wifiTransactionID: UUID?
    var wifiSSID: String?
    // Missing fields decode as nil for existing v1 records; no destructive migration.
    var factoryProfile: FactoryProfile? = nil
    var factorySetupOperationID: UUID? = nil
    var factoryExpectedNormal: Bool? = nil
    var factoryPhotoAccessComplete: Bool? = nil
    var isFactory: Bool { factoryProfile != nil }
    var isFactoryBootstrap: Bool { factoryProfile == .bootstrap }
    var isFactorySetupPending: Bool { isFactory && factoryPhotoAccessComplete != true }

    var id: UUID { identity.id }
    var expectedServerName: String { identity.expectedServerName }
    var ownerTokenHex: String { ownerToken.map { String(format: "%02x", $0) }.joined() }
    var trustPolicy: FrameTrustPolicy { FrameTrustPolicy(identity: identity) }
    func trust() throws -> PinnedFrameTrust {
        guard factoryProfile != .bootstrap else { throw OwnershipVaultError.invalidRecord }
        return try PinnedFrameTrust(identity: identity, certificateDER: certificateDER)
    }
}

/// Independent from Face ID's frame-password vault. Callers must successfully
/// prepare a durable pending record before sending any adoption mutation.
@MainActor
struct OwnershipVault: Sendable {
    private let service: String
    init(service: String = "fr.mehdiguiard.inkystudio.owner") { self.service = service }

    /// A retry reuses the same pending credential, allowing a lost claim response
    /// to be recovered. A claimed identity is never silently replaced.
    func prepare(identity: FrameIdentity, certificateDER: Data, endpoint: URL? = nil) throws -> OwnershipRecord {
        let trust = try PinnedFrameTrust(identity: identity, certificateDER: certificateDER)
        if let endpoint { try trust.validateHTTPS(endpoint) }
        if let existing = try load(id: identity.id) {
            guard existing.identity == identity else {
                throw OwnershipVaultError.identityChanged
            }
            guard existing.factoryProfile == nil, existing.state == .pending else { throw OwnershipVaultError.alreadyClaimed }
            return try refreshPendingCertificate(existing, certificateDER: certificateDER)
        }
        guard try allRecords().count < 8 else { throw OwnershipVaultError.capacityReached }
        var token = Data(count: 32)
        let status = token.withUnsafeMutableBytes { bytes in
            SecRandomCopyBytes(kSecRandomDefault, bytes.count, bytes.baseAddress!)
        }
        guard status == errSecSuccess else { throw OwnershipVaultError.unavailable }
        let record = OwnershipRecord(identity: identity, certificateDER: certificateDER,
                                     ownerID: UUID(), claimRequestID: UUID(), ownerToken: token,
                                     endpoints: endpoint.map { [$0] } ?? [], state: .pending)
        var query = baseQuery(id: identity.id)
        query[kSecAttrAccessible as String] = kSecAttrAccessibleWhenUnlockedThisDeviceOnly
        query[kSecValueData as String] = try JSONEncoder().encode(record)
        let result = SecItemAdd(query as CFDictionary, nil)
        if result == errSecDuplicateItem {
            // Another caller may have prepared the same record. Never return our
            // unsaved random token or overwrite the one already persisted.
            guard let existing = try load(id: identity.id), existing.identity == identity,
                  existing.state == .pending else {
                throw OwnershipVaultError.identityChanged
            }
            return try refreshPendingCertificate(existing, certificateDER: certificateDER)
        }
        guard result == errSecSuccess else { throw OwnershipVaultError.unavailable }
        return record
    }

    /// Bootstrap storage never invokes normal certificate date validation or creates LAN authority.
    func prepareBootstrap(identity: FrameIdentity, certificateDER: Data) throws -> OwnershipRecord {
        _ = try BootstrapFrameTrust(identity: identity, certificateDER: certificateDER)
        if let existing = try load(id: identity.id) {
            guard existing.identity == identity else { throw OwnershipVaultError.identityChanged }
            guard existing.factoryProfile == .bootstrap else { throw OwnershipVaultError.alreadyClaimed }
            return try refreshBootstrapCertificate(id: existing.id, certificateDER: certificateDER)
        }
        guard try allRecords().count < 8 else { throw OwnershipVaultError.capacityReached }
        var token = Data(count: 32)
        let status = token.withUnsafeMutableBytes { SecRandomCopyBytes(kSecRandomDefault, $0.count, $0.baseAddress!) }
        guard status == errSecSuccess else { throw OwnershipVaultError.unavailable }
        let record = OwnershipRecord(identity: identity, certificateDER: certificateDER, ownerID: UUID(),
            claimRequestID: UUID(), ownerToken: token, endpoints: [], state: .pending, factoryProfile: .bootstrap)
        var query = baseQuery(id: identity.id)
        query[kSecAttrAccessible as String] = kSecAttrAccessibleWhenUnlockedThisDeviceOnly
        query[kSecValueData as String] = try JSONEncoder().encode(record)
        let added = SecItemAdd(query as CFDictionary, nil)
        if added == errSecDuplicateItem {
            guard let existing = try load(id: identity.id), existing.identity == identity,
                  existing.factoryProfile == .bootstrap else { throw OwnershipVaultError.identityChanged }
            return existing
        }
        guard added == errSecSuccess else { throw OwnershipVaultError.unavailable }
        return record
    }

    func refreshBootstrapCertificate(id: UUID, certificateDER: Data) throws -> OwnershipRecord {
        guard var record = try load(id: id), record.factoryProfile == .bootstrap else { throw OwnershipVaultError.invalidRecord }
        _ = try BootstrapFrameTrust(identity: record.identity, certificateDER: certificateDER)
        record.certificateDER = certificateDER
        try update(record)
        return record
    }

    /// Only call after a fresh, strictly date-valid normal TLS connection on the persisted UUID/SPKI.
    func promoteFactoryNormal(id: UUID, certificateDER: Data) throws -> OwnershipRecord {
        guard var record = try load(id: id), record.factoryProfile != nil else { throw OwnershipVaultError.invalidRecord }
        _ = try PinnedFrameTrust(identity: record.identity, certificateDER: certificateDER)
        record.certificateDER = certificateDER
        record.factoryProfile = .normalV1
        record.factoryExpectedNormal = nil
        try update(record)
        return record
    }

    func setFactoryOperation(id: UUID, operationID: UUID) throws -> OwnershipRecord {
        guard var record = try load(id: id), record.factoryProfile != nil, record.state == .claimed else {
            throw OwnershipVaultError.invalidRecord
        }
        record.factorySetupOperationID = operationID
        try update(record)
        return record
    }

    func expectFactoryNormal(id: UUID) throws -> OwnershipRecord {
        guard var record = try load(id: id), record.isFactory else { throw OwnershipVaultError.invalidRecord }
        record.factoryExpectedNormal = true
        try update(record)
        return record
    }

    func markFactoryPhotoCompleted(id: UUID) throws -> OwnershipRecord {
        guard var record = try load(id: id), record.factoryProfile == .normalV1 else { throw OwnershipVaultError.invalidRecord }
        record.factoryPhotoAccessComplete = true
        try update(record)
        return record
    }

    /// Call only after an authenticated claim result (or ownership recovery).
    @discardableResult
    func markClaimed(id: UUID, endpoint: URL? = nil) throws -> OwnershipRecord {
        guard let old = try load(id: id) else { throw OwnershipVaultError.missing }
        let trust = old.trustPolicy
        if let endpoint {
            guard old.factoryProfile != .bootstrap else { throw OwnershipVaultError.invalidRecord }
            try trust.validateHTTPS(endpoint)
        }
        // Keep the most recent occurrence of each endpoint, oldest first. A
        // new network must not block finishing an authenticated Wi-Fi transaction.
        var endpoints: [URL] = []
        for knownEndpoint in old.endpoints + (endpoint.map { [$0] } ?? []) {
            endpoints.removeAll { $0 == knownEndpoint }
            endpoints.append(knownEndpoint)
        }
        endpoints = Array(endpoints.suffix(16))
        var record = old
        record.endpoints = endpoints
        record.state = .claimed
        try update(record)
        return record
    }

    @discardableResult
    func refreshCertificate(id: UUID, certificateDER: Data) throws -> OwnershipRecord {
        guard let old = try load(id: id) else { throw OwnershipVaultError.missing }
        guard old.factoryProfile != .bootstrap else { throw OwnershipVaultError.invalidRecord }
        _ = try PinnedFrameTrust(identity: old.identity, certificateDER: certificateDER)
        var record = old
        record.certificateDER = certificateDER
        try update(record)
        return record
    }

    /// Explicit physical re-adoption after the pinned server rejected an existing
    /// owner. Replacing the one Keychain blob preserves all-or-nothing storage.
    func replaceUnauthorizedOwner(id: UUID, certificateDER: Data) throws -> OwnershipRecord {
        guard let old = try load(id: id), old.factoryProfile == nil else { throw OwnershipVaultError.invalidRecord }
        _ = try PinnedFrameTrust(identity: old.identity, certificateDER: certificateDER)
        var token = Data(count: 32)
        let result = token.withUnsafeMutableBytes { SecRandomCopyBytes(kSecRandomDefault, $0.count, $0.baseAddress!) }
        guard result == errSecSuccess else { throw OwnershipVaultError.unavailable }
        let record = OwnershipRecord(identity: old.identity, certificateDER: certificateDER,
                                     ownerID: UUID(), claimRequestID: UUID(), ownerToken: token,
                                     endpoints: old.endpoints, state: .pending)
        try update(record)
        return record
    }

    /// Persist the request ID before wifi.begin, without retaining its password.
    @discardableResult
    func beginWiFiTransaction(id: UUID, transactionID: UUID, ssid: String) throws -> OwnershipRecord {
        guard var record = try load(id: id), record.state == .claimed,
              !ssid.isEmpty, ssid.utf8.count <= 32 else { throw OwnershipVaultError.invalidRecord }
        guard record.wifiTransactionID == nil else { throw OwnershipVaultError.transactionPending }
        record.wifiTransactionID = transactionID
        record.wifiSSID = ssid
        try update(record)
        return record
    }

    @discardableResult
    func finishWiFiTransaction(id: UUID, transactionID: UUID) throws -> OwnershipRecord {
        guard var record = try load(id: id), record.wifiTransactionID == transactionID else {
            throw OwnershipVaultError.invalidRecord
        }
        record.wifiTransactionID = nil
        record.wifiSSID = nil
        try update(record)
        return record
    }

    func load(id: UUID) throws -> OwnershipRecord? {
        var query = baseQuery(id: id)
        query[kSecReturnData as String] = true
        query[kSecMatchLimit as String] = kSecMatchLimitOne
        var result: CFTypeRef?
        let status = SecItemCopyMatching(query as CFDictionary, &result)
        if status == errSecItemNotFound { return nil }
        guard status == errSecSuccess, let data = result as? Data else { throw OwnershipVaultError.unavailable }
        let record = try decode(data)
        guard record.id == id else { throw OwnershipVaultError.invalidRecord }
        return record
    }

    func allRecords() throws -> [OwnershipRecord] {
        var query = baseQuery()
        query[kSecReturnData as String] = true
        query[kSecMatchLimit as String] = kSecMatchLimitAll
        var result: CFTypeRef?
        let status = SecItemCopyMatching(query as CFDictionary, &result)
        if status == errSecItemNotFound { return [] }
        guard status == errSecSuccess, let data = result as? [Data], data.count <= 8 else {
            throw OwnershipVaultError.unavailable
        }
        return try data.map(decode)
    }

    /// Local forgetting does not revoke this phone on the frame.
    func remove(id: UUID) throws {
        let status = SecItemDelete(baseQuery(id: id) as CFDictionary)
        guard status == errSecSuccess || status == errSecItemNotFound else { throw OwnershipVaultError.unavailable }
    }

    private func baseQuery(id: UUID? = nil) -> [String: Any] {
        var query: [String: Any] = [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service]
        if let id { query[kSecAttrAccount as String] = id.uuidString.lowercased() }
        return query
    }
    private func refreshPendingCertificate(_ old: OwnershipRecord, certificateDER: Data) throws -> OwnershipRecord {
        guard old.certificateDER != certificateDER else { return old }
        var refreshed = old
        refreshed.certificateDER = certificateDER
        try update(refreshed)
        return refreshed
    }
    private func update(_ record: OwnershipRecord) throws {
        let status = SecItemUpdate(baseQuery(id: record.id) as CFDictionary,
            [kSecValueData as String: try JSONEncoder().encode(record)] as CFDictionary)
        guard status == errSecSuccess else { throw OwnershipVaultError.unavailable }
    }
    private func decode(_ data: Data) throws -> OwnershipRecord {
        guard data.count <= 32768, let record = try? JSONDecoder().decode(OwnershipRecord.self, from: data),
              record.ownerToken.count == 32, record.ownerID != record.id,
              record.endpoints.count <= 16,
              record.wifiSSID.map({ !$0.isEmpty && $0.utf8.count <= 32 }) ?? true,
              (record.wifiTransactionID == nil) == (record.wifiSSID == nil) else { throw OwnershipVaultError.invalidRecord }
        // A cached certificate may have expired while the frame renewed the same
        // key. Check its pinned identity here; fresh BLE/HTTPS evaluates its dates.
        guard try PinnedFrameTrust.spkiSHA256(certificateDER: record.certificateDER) == record.identity.spkiSHA256 else {
            throw OwnershipVaultError.identityChanged
        }
        if record.factoryProfile == .bootstrap {
            guard record.endpoints.isEmpty else { throw OwnershipVaultError.invalidRecord }
            _ = try BootstrapFrameTrust(identity: record.identity, certificateDER: record.certificateDER)
        }
        let trust = record.trustPolicy
        for endpoint in record.endpoints { try trust.validateHTTPS(endpoint) }
        return record
    }
}

enum OwnershipVaultError: Error, LocalizedError, Equatable, Sendable {
    case unavailable, missing, invalidRecord, identityChanged, alreadyClaimed, capacityReached, transactionPending
    var errorDescription: String? {
        switch self {
        case .unavailable: return "Le trousseau sécurisé est indisponible. Déverrouillez l’iPhone puis réessayez."
        case .missing: return "L’autorisation de ce cadre n’est plus présente sur cet iPhone."
        case .invalidRecord: return "L’autorisation enregistrée de ce cadre est illisible."
        case .identityChanged: return "L’identité de ce cadre a changé. Une nouvelle adoption physique est nécessaire."
        case .alreadyClaimed: return "Ce cadre est déjà adopté sur cet iPhone."
        case .capacityReached: return "Huit cadres sont déjà enregistrés. Oubliez un cadre avant d’en adopter un autre."
        case .transactionPending: return "Une configuration Wi-Fi attend encore une vérification. Reprenez-la avant de changer de réseau."
        }
    }
}
