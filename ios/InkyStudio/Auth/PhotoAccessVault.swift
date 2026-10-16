import Foundation
import LocalAuthentication

/// Separate protected namespace: PHOTO access never grants Bluetooth ownership.
@MainActor
final class PhotoAccessVault {
    private let saveValue: (String, String) throws -> Void
    private let loadValue: (String) async throws -> String
    private let containsValue: (String) -> Bool
    private let removeValue: (String) throws -> Void

    init(vault: BiometricVault = BiometricVault(service: "fr.mehdiguiard.inkystudio.photo-access"),
         context: @escaping @MainActor () -> LAContext? = { nil },
         saveValue: ((String, String) throws -> Void)? = nil,
         loadValue: ((String) async throws -> String)? = nil,
         containsValue: ((String) -> Bool)? = nil,
         removeValue: ((String) throws -> Void)? = nil) {
        self.saveValue = saveValue ?? { try vault.save(password: $0, address: $1, context: context()) }
        self.loadValue = loadValue ?? { try await vault.load(address: $0, context: context()) }
        self.containsValue = containsValue ?? { vault.contains(address: $0) }
        self.removeValue = removeValue ?? { try vault.remove(address: $0) }
    }

    func save(_ credential: PhotoAccessCredential, account: String) throws {
        try write(credential.validated(), account: account)
    }
    func loadCredential(account: String) async throws -> PhotoAccessCredential {
        let credential: PhotoAccessCredential = try await read(account: account)
        return try credential.validated()
    }
    func save(_ draft: PhotoInvitationDraft, account: String) throws { try write(draft.validated(), account: account) }
    func loadDraft(account: String) async throws -> PhotoInvitationDraft {
        let draft: PhotoInvitationDraft = try await read(account: account)
        return try draft.validated()
    }
    func contains(account: String) -> Bool { containsValue(account) }
    func remove(account: String) throws { try removeValue(account) }
    private func write<T: Encodable>(_ value: T, account: String) throws {
        let data = try JSONEncoder().encode(value)
        guard let text = String(data: data, encoding: .utf8) else { throw PhotoAccessError.invalidData }
        try saveValue(text, account)
    }
    private func read<T: Decodable>(account: String) async throws -> T {
        let text = try await loadValue(account)
        try Task.checkCancellation()
        guard let data = text.data(using: .utf8), data.count <= 8192 else { throw PhotoAccessError.invalidData }
        do { return try JSONDecoder().decode(T.self, from: data) }
        catch { throw PhotoAccessError.invalidData }
    }
}

/// Nonsecret locator only. Tokens and request IDs remain in protected storage.
struct PhotoAccessSelection: Codable, Equatable, Sendable {
    let identity: FrameIdentity
    let endpoint: URL
    let deviceID: UUID
    let role: PhotoAccessRole
    let invitationID: UUID?
    let account: String

    init(_ credential: PhotoAccessCredential) {
        identity = credential.identity; endpoint = credential.endpoint; deviceID = credential.deviceID
        role = credential.expectedRole; invitationID = credential.invitationID
        account = Self.account(identity: identity, invitationID: invitationID)
    }
    static func account(identity: FrameIdentity, invitationID: UUID?) -> String {
        "photo:" + identity.id.uuidString.lowercased() + ":" + (invitationID?.uuidString.lowercased() ?? "owner")
    }
    func validates(_ credential: PhotoAccessCredential) -> Bool {
        identity == credential.identity && endpoint == credential.endpoint && deviceID == credential.deviceID &&
        role == credential.expectedRole && invitationID == credential.invitationID &&
        account == Self.account(identity: identity, invitationID: invitationID)
    }
}
