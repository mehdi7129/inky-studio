import Foundation
import LocalAuthentication
import Security

/// One context per local unlock; reused for the protected Keychain read.
@MainActor
final class LocalDeviceAuthentication {
    private(set) var context = LAContext()

    var name: String {
        let probe = LAContext()
        _ = probe.canEvaluatePolicy(.deviceOwnerAuthentication, error: nil)
        switch probe.biometryType {
        case .faceID: return "Face ID"
        case .touchID: return "Touch ID"
        default: return "code iPhone"
        }
    }

    func authenticate() async throws {
        context.invalidate()
        let candidate = LAContext()
        candidate.localizedCancelTitle = "Annuler"
        candidate.localizedFallbackTitle = "Utiliser le code de l’iPhone"
        var error: NSError?
        guard candidate.canEvaluatePolicy(.deviceOwnerAuthentication, error: &error) else {
            throw VaultError.passcodeRequired
        }
        context = candidate
        do {
            guard try await candidate.evaluatePolicy(.deviceOwnerAuthentication,
                localizedReason: "Déverrouiller Inky Studio") else { throw VaultError.cancelled }
        } catch {
            if (error as? LAError)?.code == .passcodeNotSet { throw VaultError.passcodeRequired }
            throw VaultError.cancelled
        }
    }

    func invalidate() { context.invalidate() }
}

/// Versioned storage keeps old biometric-only items intact until migration succeeds.
struct BiometricVault: Sendable {
    private let legacyService: String
    private let coordinator = VaultCoordinator()
    private var service: String { legacyService + ".local-auth-v2" }

    init(service: String = "fr.mehdiguiard.inkystudio.frame-password") { legacyService = service }

    func contains(address: String) -> Bool {
        [service, legacyService].contains { selected in
            var query = query(service: selected, address: address)
            query[kSecReturnAttributes as String] = true
            let context = LAContext()
            context.interactionNotAllowed = true
            query[kSecUseAuthenticationContext as String] = context
            let status = SecItemCopyMatching(query as CFDictionary, nil)
            return status == errSecSuccess || status == errSecInteractionNotAllowed || status == errSecAuthFailed
        }
    }

    func save(password: String, address: String, context: LAContext? = nil) throws {
        try coordinator.lock.withLock {
            coordinator.advance(address)
            let result = try add(password: password, address: address, context: context)
            if result == errSecDuplicateItem {
                // Only v2 items live here; retain their userPresence ACL and update atomically.
                var base = query(service: service, address: address)
                if let context { base[kSecUseAuthenticationContext as String] = context }
                let status = SecItemUpdate(base as CFDictionary,
                    [kSecValueData as String: Data(password.utf8)] as CFDictionary)
                guard status == errSecSuccess else { throw VaultError.unavailable }
            } else if result != errSecSuccess { throw VaultError.unavailable }
        }
    }

    private func add(password: String, address: String, context: LAContext?) throws -> OSStatus {
        var error: Unmanaged<CFError>?
        guard let access = SecAccessControlCreateWithFlags(nil, kSecAttrAccessibleWhenPasscodeSetThisDeviceOnly,
                                                          .userPresence, &error) else { throw VaultError.unavailable }
        var addition = query(service: service, address: address)
        if let context { addition[kSecUseAuthenticationContext as String] = context }
        addition[kSecAttrAccessControl as String] = access
        addition[kSecValueData as String] = Data(password.utf8)
        return SecItemAdd(addition as CFDictionary, nil)
    }

    @MainActor
    func load(address: String, context: LAContext? = nil) async throws -> String {
        // Capture on the context's owner actor, then hand one serial operation to the worker.
        try await load(address: address, authentication: AuthenticationContext(context ?? LAContext()))
    }

    private func load(address: String, authentication boxed: AuthenticationContext) async throws -> String {
        let services = (service, legacyService)
        let ticket = coordinator.lock.withLock { coordinator.ticket(address) }
        let read = Task.detached(priority: .userInitiated) {
            try Task.checkCancellation()
            let result: (String, Bool)
            do { result = (try Self.read(service: services.0, address: address, context: boxed.value), false) }
            catch VaultError.missing { result = (try Self.read(service: services.1, address: address, context: boxed.value), true) }
            try Task.checkCancellation()
            return result
        }
        let result = try await withTaskCancellationHandler(operation: { try await read.value }, onCancel: { read.cancel() })
        try Task.checkCancellation()
        return try coordinator.lock.withLock {
            guard coordinator.ticket(address) == ticket else { throw CancellationError() }
            try Task.checkCancellation()
            guard result.1 else { return result.0 }
            // Migration is insert-only. A newer v2 save must never be replaced by the legacy value.
            let added = try add(password: result.0, address: address, context: boxed.value)
            guard added == errSecSuccess || added == errSecDuplicateItem else { throw VaultError.unavailable }
            try Task.checkCancellation()
            let verified = try Self.read(service: services.0, address: address, context: boxed.value)
            guard added == errSecDuplicateItem || verified == result.0 else { throw VaultError.unavailable }
            try Task.checkCancellation()
            try remove(service: legacyService, address: address)
            return verified
        }
    }

    func remove(address: String) throws {
        try coordinator.lock.withLock {
            coordinator.advance(address)
            try remove(service: service, address: address)
            try remove(service: legacyService, address: address)
        }
    }

    private func remove(service: String, address: String) throws {
        let status = SecItemDelete(query(service: service, address: address) as CFDictionary)
        guard status == errSecSuccess || status == errSecItemNotFound else { throw VaultError.unavailable }
    }

    private func query(service: String, address: String) -> [String: Any] {
        [kSecClass as String: kSecClassGenericPassword,
         kSecAttrService as String: service, kSecAttrAccount as String: address]
    }

    private static func read(service: String, address: String, context: LAContext) throws -> String {
        context.localizedCancelTitle = "Annuler"
        context.localizedReason = "Déverrouiller Inky Studio"
        let query: [String: Any] = [kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service, kSecAttrAccount as String: address,
            kSecReturnData as String: true, kSecMatchLimit as String: kSecMatchLimitOne,
            kSecUseAuthenticationContext as String: context]
        var result: CFTypeRef?
        let status = SecItemCopyMatching(query as CFDictionary, &result)
        if status == errSecUserCanceled || status == errSecAuthFailed { throw VaultError.cancelled }
        if status == errSecItemNotFound { throw VaultError.missing }
        guard status == errSecSuccess, let data = result as? Data,
              let password = String(data: data, encoding: .utf8) else { throw VaultError.unavailable }
        return password
    }
}

/// Keychain work uses the context serially while its caller awaits the result.
private final class AuthenticationContext: @unchecked Sendable {
    let value: LAContext
    init(_ value: LAContext) { self.value = value }
}

enum VaultError: LocalizedError {
    case unavailable, cancelled, missing, passcodeRequired
    var errorDescription: String? {
        switch self {
        case .unavailable: return "L’enregistrement sécurisé est indisponible. Votre connexion actuelle est conservée."
        case .cancelled: return "Déverrouillage annulé. Réessayez avec Face ID ou le code de l’iPhone."
        case .missing: return "Cet iPhone n’a pas d’identifiant enregistré pour ce cadre."
        case .passcodeRequired: return "Configurez un code de verrouillage dans les réglages de l’iPhone pour utiliser Inky Studio."
        }
    }
}

/// Serializes mutations and prevents a late read/migration from resurrecting forgotten credentials.
private final class VaultCoordinator: @unchecked Sendable {
    let lock = NSRecursiveLock()
    private var versions: [String: UInt64] = [:]
    func ticket(_ account: String) -> UInt64 { versions[account, default: 0] }
    func advance(_ account: String) { versions[account, default: 0] &+= 1 }
}
