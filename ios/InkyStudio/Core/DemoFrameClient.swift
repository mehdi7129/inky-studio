import CryptoKit
import UIKit

/// A disposable in-memory frame. No URLSession, files, defaults or Keychain.
@MainActor
final class DemoFrameClient: FramePhotoClient {
    private var images: [String: Data] = [:]
    private var entries: [QueueEntry] = []
    private var displayed: [HistoryEntry] = []
    private var current: HistoryEntry?
    private var configuration = FrameSettings(changeMode: .manual)
    private var nextID = 3
    private var navigationHistoryID = 2
    private var closed = false
    private(set) var sampleData: Data?
    // Bound imports so an exploratory session cannot grow indefinitely.
    private let byteLimit = 32 * 1024 * 1024

    init() {
        let now = Date().timeIntervalSince1970
        for index in 0..<3 {
            guard let data = DemoArtwork.image(index: index).pngData() else { continue }
            if index == 0 { sampleData = data }
            let photo = makePhoto(data, filename: "exemple.png")
            images[photo.id] = data
            if index == 0 {
                let item = HistoryEntry(id: 2, displayedAt: now - 3600, source: "demo", photo: photo)
                current = item
                displayed.append(item)
            } else {
                entries.append(QueueEntry(id: identifier(), position: entries.count, addedAt: now, photo: photo))
                if index == 2 {
                    displayed.append(HistoryEntry(id: 1, displayedAt: now - 86400, source: "demo", photo: photo))
                }
            }
        }
    }

    func clear() {
        closed = true
        images.removeAll()
        entries.removeAll()
        displayed.removeAll()
        current = nil
        sampleData = nil
    }

    private func checkOpen() throws { if closed { throw CancellationError() } }
    private func identifier() -> Int { defer { nextID += 1 }; return nextID }
    private func makePhoto(_ data: Data, filename: String) -> Photo {
        let hash = SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
        return Photo(id: "demo-" + hash, sha256: hash, originalFilename: filename,
                     mime: "image/png", width: 800, height: 480, sizeBytes: data.count,
                     createdAt: Date().timeIntervalSince1970)
    }

    func health() async throws -> HealthResponse {
        try checkOpen()
        return HealthResponse(status: "ok", version: "Démo locale")
    }
    func state() async throws -> DisplayState {
        try checkOpen()
        // Scheduling is editable but never triggers a background simulation.
        return DisplayState(display: DisplayInfo(model: "Cadre de démonstration", width: 800, height: 480, colors: 7, isMock: true),
                            current: current, queueCount: entries.count, nextChangeAt: nil)
    }
    func queue() async throws -> [QueueEntry] { try checkOpen(); return entries }
    func history(limit: Int, offset: Int) async throws -> [HistoryEntry] {
        try checkOpen()
        return Array(displayed.dropFirst(max(0, offset)).prefix(max(0, limit)))
    }
    func settings() async throws -> FrameSettings { try checkOpen(); return configuration }
    func updateSettings(_ settings: FrameSettings) async throws -> FrameSettings {
        try checkOpen()
        configuration = settings
        return configuration
    }
    func photoData(id: String) async throws -> Data {
        try checkOpen()
        guard let data = images[id] else { throw APIError.invalidData }
        return data
    }
    func upload(png: Data, filename: String) async throws -> UploadResponse {
        try checkOpen()
        guard png.count <= 10 * 1024 * 1024,
              png.starts(with: [137, 80, 78, 71, 13, 10, 26, 10]),
              let image = UIImage(data: png)?.cgImage, image.width == 800, image.height == 480 else {
            throw APIError.invalidData
        }
        let photo = makePhoto(png, filename: filename)
        if let entry = entries.first(where: { $0.photo.id == photo.id }) {
            return UploadResponse(photo: entry.photo, queueEntry: entry, alreadyExisted: true)
        }
        guard entries.count < 30,
              images[photo.id] != nil || images.values.reduce(0, { $0 + $1.count }) + png.count <= byteLimit else {
            throw APIError.http(statusCode: 413, message: "La démo est pleine. Réinitialisez-la dans Réglages pour continuer.")
        }
        images[photo.id] = png
        let entry = QueueEntry(id: identifier(), position: entries.count, addedAt: Date().timeIntervalSince1970, photo: photo)
        entries.append(entry)
        return UploadResponse(photo: photo, queueEntry: entry, alreadyExisted: false)
    }
    func reorderQueue(photoIDs: [String]) async throws -> [QueueEntry] {
        try checkOpen()
        guard photoIDs.count == entries.count, Set(photoIDs) == Set(entries.map { $0.photo.id }) else { throw APIError.invalidData }
        let byID = Dictionary(uniqueKeysWithValues: entries.map { ($0.photo.id, $0) })
        entries = photoIDs.compactMap { byID[$0] }
        normalize()
        return entries
    }
    func removeFromQueue(photoID: String) async throws {
        try checkOpen()
        entries.removeAll { $0.photo.id == photoID }
        normalize()
        pruneImages()
    }
    func deleteHistoryEntry(id: Int) async throws {
        try checkOpen()
        displayed.removeAll { $0.id == id }
        pruneImages()
    }
    func clearHistory() async throws { try checkOpen(); displayed.removeAll(); pruneImages() }
    func next() async throws {
        try checkOpen()
        guard !entries.isEmpty else { throw APIError.http(statusCode: 409, message: "Ajoutez une photo à la file pour essayer l’affichage.") }
        let entry = entries.removeFirst()
        show(entry.photo)
        normalize()
    }
    func previous() async throws {
        try checkOpen()
        guard let entry = displayed.first(where: { $0.id < navigationHistoryID }) else {
            throw APIError.http(statusCode: 409, message: "Aucune photo précédente dans la démo.")
        }
        show(entry.photo, navigationID: entry.id)
    }
    private func show(_ photo: Photo, navigationID: Int? = nil) {
        let entry = HistoryEntry(id: identifier(), displayedAt: Date().timeIntervalSince1970, source: "demo", photo: photo)
        navigationHistoryID = navigationID ?? entry.id
        current = entry
        displayed.insert(entry, at: 0)
        displayed = Array(displayed.prefix(100))
        pruneImages()
    }
    private func normalize() { for index in entries.indices { entries[index].position = index } }
    private func pruneImages() {
        var retained = Set(entries.map { $0.photo.id } + displayed.map { $0.photo.id })
        if let current { retained.insert(current.photo.id) }
        images = images.filter { retained.contains($0.key) }
    }
}

/// Original geometric landscapes, drawn locally. No stock-photo license or
/// personal media is needed to explore the app or prepare review screenshots.
@MainActor
enum DemoArtwork {
    static func image(index: Int) -> UIImage {
        let palettes: [[UIColor]] = [
            [UIColor(red: 0.79, green: 0.87, blue: 0.91, alpha: 1), UIColor(red: 0.20, green: 0.46, blue: 0.55, alpha: 1), UIColor(red: 0.88, green: 0.78, blue: 0.61, alpha: 1)],
            [UIColor(red: 0.97, green: 0.87, blue: 0.72, alpha: 1), UIColor(red: 0.70, green: 0.37, blue: 0.28, alpha: 1), UIColor(red: 0.89, green: 0.61, blue: 0.41, alpha: 1)],
            [UIColor(red: 0.85, green: 0.90, blue: 0.81, alpha: 1), UIColor(red: 0.23, green: 0.41, blue: 0.34, alpha: 1), UIColor(red: 0.46, green: 0.61, blue: 0.42, alpha: 1)]
        ]
        let palette = palettes[index % palettes.count]
        let format = UIGraphicsImageRendererFormat()
        format.scale = 1
        format.opaque = true
        return UIGraphicsImageRenderer(size: CGSize(width: 800, height: 480), format: format).image { context in
            palette[0].setFill()
            context.fill(CGRect(x: 0, y: 0, width: 800, height: 480))
            UIColor(red: 1, green: 0.96, blue: 0.83, alpha: 1).setFill()
            UIBezierPath(ovalIn: CGRect(x: 550, y: 60, width: 100, height: 100)).fill()
            for layer in 0..<2 {
                palette[layer + 1].setFill()
                let path = UIBezierPath()
                path.move(to: CGPoint(x: 0, y: 280 + layer * 100))
                path.addCurve(to: CGPoint(x: 800, y: 240 + layer * 100),
                              controlPoint1: CGPoint(x: 260, y: 60 + index * 50 + layer * 170),
                              controlPoint2: CGPoint(x: 450, y: 450 - layer * 180))
                path.addLine(to: CGPoint(x: 800, y: 480))
                path.addLine(to: CGPoint(x: 0, y: 480))
                path.close()
                path.fill()
            }
        }
    }
}
