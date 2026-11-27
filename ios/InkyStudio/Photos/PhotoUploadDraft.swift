import CryptoKit
import Foundation

struct PhotoUploadBinding: Codable, Hashable {
    let frameID: UUID
    let spki: Data
    let deviceID: UUID
}

struct PhotoUploadDraft: Codable {
    enum Delivery: String, Codable { case ready, receiptBacked, receiptUnavailable }

    let id: UUID
    let binding: PhotoUploadBinding
    let filename: String
    let png: Data
    let hash: String
    // Drafts saved before this field existed may already have reached a frame.
    var delivery: Delivery?

    init(binding: PhotoUploadBinding, filename: String, png: Data) {
        id = UUID()
        self.binding = binding
        self.filename = filename
        self.png = png
        hash = Self.digest(png)
        delivery = .ready
    }

    static func digest(_ data: Data) -> String {
        SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
    }
}

struct PhotoUploadDraftStore {
    private let directory: URL

    init(directory: URL = URL.applicationSupportDirectory.appendingPathComponent("PendingFrameUploads", isDirectory: true)) {
        self.directory = directory
    }

    func load(_ binding: PhotoUploadBinding) throws -> PhotoUploadDraft? {
        let url = path(binding)
        do {
            let values = try url.resourceValues(forKeys: [.isRegularFileKey, .fileSizeKey])
            guard values.isRegularFile == true, let size = values.fileSize, size <= 15 * 1024 * 1024 else {
                throw PhotoAccessError.invalidData
            }
            let saved = try JSONDecoder().decode(PhotoUploadDraft.self, from: Data(contentsOf: url))
            guard saved.binding == binding, saved.hash == PhotoUploadDraft.digest(saved.png) else {
                throw PhotoAccessError.invalidData
            }
            return saved
        } catch let error as CocoaError where [.fileNoSuchFile, .fileReadNoSuchFile].contains(error.code) {
            return nil
        }
    }

    func save(_ draft: PhotoUploadDraft) throws {
        guard draft.png.count <= 10 * 1024 * 1024 else { throw PhotoAccessError.invalidData }
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        var excluded = directory
        var attributes = URLResourceValues()
        attributes.isExcludedFromBackup = true
        try excluded.setResourceValues(attributes)
        try JSONEncoder().encode(draft).write(to: path(draft.binding), options: [.atomic, .completeFileProtection])
    }

    func remove(_ draft: PhotoUploadDraft) throws {
        guard try load(draft.binding)?.id == draft.id else { return }
        try FileManager.default.removeItem(at: path(draft.binding))
    }

    private func path(_ binding: PhotoUploadBinding) -> URL {
        let identity = binding.frameID.uuidString + binding.deviceID.uuidString
        let filename = PhotoUploadDraft.digest(Data(identity.utf8) + binding.spki)
        return directory.appendingPathComponent(filename, isDirectory: false)
    }
}

enum PhotoUploadRecoveryError: Error, LocalizedError {
    case unconfirmed

    var errorDescription: String? {
        String(localized: "Le cadre n’a pas pu confirmer cet envoi. Le brouillon est conservé. Vérifiez l’historique du cadre avant tout nouvel envoi.")
    }
}
