import Foundation
import Security

/// Bootstrap credentials cannot authorize HTTPS or normal BLE and have no endpoint.
/// The physical-window token is deliberately absent from this durable record.
struct BootstrapOwnershipRecord: Codable, Equatable, Sendable, Identifiable {
    enum Provenance: String, Codable, Sendable { case physicalBootstrapQRV2 }
    enum State: String, Codable, Sendable { case pending, adoptedAwaitingPreparation }
    let provenance: Provenance
    let identity: FrameIdentity
    let certificateDER: Data
    let ownerID: UUID
    let ownerToken: Data
    let claimRequestID: UUID
    let state: State
    var id: UUID { identity.id }

    func validate() throws {
        guard provenance == .physicalBootstrapQRV2, ownerToken.count == 32, ownerID != id,
              (1...960).contains(certificateDER.count) else { throw OwnershipVaultError.invalidRecord }
        _ = try BootstrapFrameTrust(identity: identity, certificateDER: certificateDER)
    }
}

@MainActor protocol BootstrapOwnershipStorage {
    func allRecords() throws -> [BootstrapOwnershipRecord]
    func load(id: UUID) throws -> BootstrapOwnershipRecord?
    func prepare(identity: FrameIdentity, certificateDER: Data) throws -> BootstrapOwnershipRecord
    func refreshCertificate(id: UUID, certificateDER: Data) throws -> BootstrapOwnershipRecord
    func markAdopted(record: BootstrapOwnershipRecord) throws -> BootstrapOwnershipRecord
}

/// A separate service/provenance prevents bootstrap date exceptions from entering
/// normal ownership, photo-password storage or endpoint trust.
@MainActor struct BootstrapOwnershipVault: BootstrapOwnershipStorage {
    private let service: String
    init(service: String = "fr.mehdiguiard.inkystudio.bootstrap-owner") { self.service = service }

    func prepare(identity: FrameIdentity, certificateDER: Data) throws -> BootstrapOwnershipRecord {
        _ = try BootstrapFrameTrust(identity: identity, certificateDER: certificateDER)
        if let existing = try load(id: identity.id) {
            guard existing.identity == identity else { throw OwnershipVaultError.identityChanged }
            // Pending and adopted records both retain the one durable intention.
            return try refreshCertificate(id: existing.id, certificateDER: certificateDER)
        }
        guard try allRecords().count < 8 else { throw OwnershipVaultError.capacityReached }
        var token = Data(count: 32)
        let status = token.withUnsafeMutableBytes { SecRandomCopyBytes(kSecRandomDefault, $0.count, $0.baseAddress!) }
        guard status == errSecSuccess else { throw OwnershipVaultError.unavailable }
        let record = BootstrapOwnershipRecord(provenance: .physicalBootstrapQRV2, identity: identity,
            certificateDER: certificateDER, ownerID: UUID(), ownerToken: token, claimRequestID: UUID(), state: .pending)
        try record.validate()
        var query = baseQuery(id: identity.id)
        query[kSecAttrAccessible as String] = kSecAttrAccessibleWhenUnlockedThisDeviceOnly
        query[kSecValueData as String] = try JSONEncoder().encode(record)
        let result = SecItemAdd(query as CFDictionary, nil)
        if result == errSecDuplicateItem {
            guard let existing = try load(id: identity.id), existing.identity == identity else {
                throw OwnershipVaultError.identityChanged
            }
            return try refreshCertificate(id: existing.id, certificateDER: certificateDER)
        }
        guard result == errSecSuccess, let saved = try load(id: identity.id), saved == record else {
            throw OwnershipVaultError.unavailable
        }
        return saved
    }

    func refreshCertificate(id: UUID, certificateDER: Data) throws -> BootstrapOwnershipRecord {
        guard let old = try load(id: id) else { throw OwnershipVaultError.missing }
        _ = try BootstrapFrameTrust(identity: old.identity, certificateDER: certificateDER)
        let refreshed = copy(old, certificate: certificateDER, state: old.state)
        if old != refreshed { try update(refreshed) }
        return refreshed
    }

    func markAdopted(record: BootstrapOwnershipRecord) throws -> BootstrapOwnershipRecord {
        guard let saved = try load(id: record.id), saved.identity == record.identity,
              saved.ownerID == record.ownerID, saved.ownerToken == record.ownerToken,
              saved.claimRequestID == record.claimRequestID else { throw OwnershipVaultError.identityChanged }
        let adopted = copy(saved, certificate: saved.certificateDER, state: .adoptedAwaitingPreparation)
        try update(adopted)
        return adopted
    }

    func load(id: UUID) throws -> BootstrapOwnershipRecord? {
        var query = baseQuery(id: id)
        query[kSecReturnData as String] = true
        query[kSecMatchLimit as String] = kSecMatchLimitOne
        var value: CFTypeRef?
        let status = SecItemCopyMatching(query as CFDictionary, &value)
        if status == errSecItemNotFound { return nil }
        guard status == errSecSuccess, let bytes = value as? Data else { throw OwnershipVaultError.unavailable }
        let record = try decode(bytes)
        guard record.id == id else { throw OwnershipVaultError.invalidRecord }
        return record
    }

    func allRecords() throws -> [BootstrapOwnershipRecord] {
        var query = baseQuery()
        query[kSecReturnData as String] = true
        query[kSecMatchLimit as String] = kSecMatchLimitAll
        var value: CFTypeRef?
        let status = SecItemCopyMatching(query as CFDictionary, &value)
        if status == errSecItemNotFound { return [] }
        guard status == errSecSuccess, let bytes = value as? [Data], bytes.count <= 8 else {
            throw OwnershipVaultError.unavailable
        }
        return try bytes.map(decode)
    }

    /// Test/local forgetting only; never revokes or reopens the factory frame.
    func remove(id: UUID) throws {
        let status = SecItemDelete(baseQuery(id: id) as CFDictionary)
        guard status == errSecSuccess || status == errSecItemNotFound else { throw OwnershipVaultError.unavailable }
    }
    private func baseQuery(id: UUID? = nil) -> [String: Any] {
        var query: [String: Any] = [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service]
        if let id { query[kSecAttrAccount as String] = id.uuidString.lowercased() }
        return query
    }
    private func copy(_ old: BootstrapOwnershipRecord, certificate: Data,
                      state: BootstrapOwnershipRecord.State) -> BootstrapOwnershipRecord {
        BootstrapOwnershipRecord(provenance: old.provenance, identity: old.identity, certificateDER: certificate,
            ownerID: old.ownerID, ownerToken: old.ownerToken, claimRequestID: old.claimRequestID, state: state)
    }
    private func update(_ record: BootstrapOwnershipRecord) throws {
        try record.validate()
        let status = SecItemUpdate(baseQuery(id: record.id) as CFDictionary,
            [kSecValueData as String: try JSONEncoder().encode(record)] as CFDictionary)
        guard status == errSecSuccess, try load(id: record.id) == record else { throw OwnershipVaultError.unavailable }
    }
    private func decode(_ bytes: Data) throws -> BootstrapOwnershipRecord {
        guard bytes.count <= 8192, let record = try? JSONDecoder().decode(BootstrapOwnershipRecord.self, from: bytes) else {
            throw OwnershipVaultError.invalidRecord
        }
        do {
            let fields = try BootstrapWire.object(bytes, maximum: 8192)
            try BootstrapWire.keys(fields, ["provenance", "identity", "certificateDER", "ownerID", "ownerToken", "claimRequestID", "state"])
            guard case let .object(identity)? = fields["identity"] else { throw OwnershipVaultError.invalidRecord }
            try BootstrapWire.keys(identity, ["id", "spkiSHA256"])
            try record.validate()
            return record
        } catch { throw OwnershipVaultError.invalidRecord }
    }
}
