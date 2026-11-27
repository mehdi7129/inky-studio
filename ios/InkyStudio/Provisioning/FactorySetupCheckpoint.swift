import Foundation
import Security

struct FactorySetupApplyIntent: Codable, Equatable, Sendable {
    let requestID: UUID
    let utcSeconds: UInt64
    let country: String
    let challenge: FactorySetupChallenge
}

struct FactorySetupCheckpoint: Codable, Equatable, Sendable {
    let binding: FactorySetupBinding
    let operationID: UUID
    let country: String
    let supersedesOperationID: UUID?
    let challengeRequestID: UUID
    var challenge: FactorySetupChallenge?
    var applyIntent: FactorySetupApplyIntent?

    func validate(binding expected: FactorySetupBinding) throws {
        guard binding == expected, binding.identity.spkiSHA256.count == 32,
              binding.ownerID != binding.identity.id,
              FactorySetupValidation.country(country), supersedesOperationID != operationID else {
            throw FactorySetupError.checkpointConflict
        }
        if let challenge {
            guard challenge.operationID == operationID, FactorySetupValidation.challenge(challenge) else {
                throw FactorySetupError.checkpointConflict
            }
        }
        if let applyIntent {
            guard let challenge, applyIntent.challenge == challenge, applyIntent.country == country,
                  FactorySetupValidation.utc(applyIntent.utcSeconds) else { throw FactorySetupError.checkpointConflict }
        }
    }
}

@MainActor
protocol FactorySetupCheckpointStorage {
    func load(binding: FactorySetupBinding) throws -> FactorySetupCheckpoint?
    func save(_ checkpoint: FactorySetupCheckpoint) throws
    func remove(binding: FactorySetupBinding) throws
}

/// Independent from BLE ownership and PHOTO credentials. A failed write never deletes the previous intent.
@MainActor
struct FactorySetupKeychainCheckpointStore: FactorySetupCheckpointStorage {
    private let service: String
    init(service: String = "fr.mehdiguiard.inkystudio.factory-system-setup") { self.service = service }

    func load(binding: FactorySetupBinding) throws -> FactorySetupCheckpoint? {
        var query = query(binding)
        query[kSecReturnData as String] = true
        query[kSecMatchLimit as String] = kSecMatchLimitOne
        var value: CFTypeRef?
        let status = SecItemCopyMatching(query as CFDictionary, &value)
        if status == errSecItemNotFound { return nil }
        guard status == errSecSuccess, let data = value as? Data, data.count <= 16_384,
              let checkpoint = try? JSONDecoder().decode(FactorySetupCheckpoint.self, from: data) else {
            throw FactorySetupError.storageUnavailable
        }
        try checkpoint.validate(binding: binding)
        return checkpoint
    }

    func save(_ checkpoint: FactorySetupCheckpoint) throws {
        try checkpoint.validate(binding: checkpoint.binding)
        let data = try JSONEncoder().encode(checkpoint)
        guard data.count <= 16_384 else { throw FactorySetupError.storageUnavailable }
        let base = query(checkpoint.binding)
        let changed = SecItemUpdate(base as CFDictionary, [kSecValueData as String: data] as CFDictionary)
        if changed == errSecSuccess { return }
        guard changed == errSecItemNotFound else { throw FactorySetupError.storageUnavailable }
        var item = base
        item[kSecValueData as String] = data
        item[kSecAttrAccessible as String] = kSecAttrAccessibleWhenUnlockedThisDeviceOnly
        // All access is serialized on MainActor. Do not overwrite an unexpected concurrent insertion.
        guard SecItemAdd(item as CFDictionary, nil) == errSecSuccess else { throw FactorySetupError.storageUnavailable }
    }

    func remove(binding: FactorySetupBinding) throws {
        let status = SecItemDelete(query(binding) as CFDictionary)
        guard status == errSecSuccess || status == errSecItemNotFound else { throw FactorySetupError.storageUnavailable }
    }

    private func query(_ binding: FactorySetupBinding) -> [String: Any] {
        let account = [binding.identity.id.uuidString.lowercased(), FactorySetupValidation.hex(binding.identity.spkiSHA256),
                       binding.ownerID.uuidString.lowercased(), binding.claimRequestID.uuidString.lowercased()].joined(separator: ":")
        return [kSecClass as String: kSecClassGenericPassword,
                kSecAttrService as String: service, kSecAttrAccount as String: account,
                kSecAttrSynchronizable as String: false]
    }
}
