import Foundation
import LocalAuthentication
import Security

/// The credential never enters UserDefaults, logs, URLs, or a shared cookie store.
struct BiometricVault: Sendable {
    private let service: String

    init(service: String = "fr.mehdiguiard.inkystudio.frame-password") {
        self.service = service
    }

    var capability: String? {
        let context = LAContext()
        guard context.canEvaluatePolicy(.deviceOwnerAuthenticationWithBiometrics, error: nil) else { return nil }
        return context.biometryType == .faceID ? "Face ID" : "Touch ID"
    }

    func save(password: String, address: String) throws {
        var error: Unmanaged<CFError>?
        guard let access = SecAccessControlCreateWithFlags(nil, kSecAttrAccessibleWhenPasscodeSetThisDeviceOnly,
                                                          .biometryCurrentSet, &error) else {
            throw VaultError.unavailable
        }
        // Deletion happens only after successful Pi authentication and explicit opt-in.
        try remove(address: address)
        let query: [String: Any] = [kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service, kSecAttrAccount as String: address,
            kSecAttrAccessControl as String: access, kSecValueData as String: Data(password.utf8)]
        guard SecItemAdd(query as CFDictionary, nil) == errSecSuccess else { throw VaultError.unavailable }
    }

    func load(address: String) async throws -> String {
        try await Task.detached(priority: .userInitiated) {
            let context = LAContext()
            context.localizedCancelTitle = "Utiliser le mot de passe"
            context.localizedReason = "Se connecter à votre cadre Inky Studio"
            let query: [String: Any] = [kSecClass as String: kSecClassGenericPassword,
                kSecAttrService as String: service, kSecAttrAccount as String: address,
                kSecReturnData as String: true, kSecMatchLimit as String: kSecMatchLimitOne,
                kSecUseAuthenticationContext as String: context]
            var result: CFTypeRef?
            let status = SecItemCopyMatching(query as CFDictionary, &result)
            if status == errSecUserCanceled || status == errSecAuthFailed { throw VaultError.cancelled }
            guard status == errSecSuccess, let data = result as? Data,
                  let password = String(data: data, encoding: .utf8) else { throw VaultError.missing }
            return password
        }.value
    }

    func remove(address: String) throws {
        let status = SecItemDelete([kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service, kSecAttrAccount as String: address] as CFDictionary)
        guard status == errSecSuccess || status == errSecItemNotFound else { throw VaultError.unavailable }
    }
}

enum VaultError: LocalizedError {
    case unavailable, cancelled, missing
    var errorDescription: String? {
        switch self {
        case .unavailable: return "L’enregistrement sécurisé est indisponible. Vous pouvez utiliser votre mot de passe."
        case .cancelled: return "Authentification annulée. Vous pouvez utiliser votre mot de passe."
        case .missing: return "Le mot de passe enregistré n’est plus accessible. Connectez-vous avec votre mot de passe."
        }
    }
}
