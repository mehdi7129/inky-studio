import Foundation

/// Only photo workflows can be simulated. Authentication, credentials, Bluetooth,
/// network events and software updates remain exclusive to the real InkyAPI.
@MainActor
protocol FramePhotoClient: AnyObject, Sendable {
    func health() async throws -> HealthResponse
    func state() async throws -> DisplayState
    func queue() async throws -> [QueueEntry]
    func history(limit: Int, offset: Int) async throws -> [HistoryEntry]
    func settings() async throws -> FrameSettings
    func updateSettings(_ settings: FrameSettings) async throws -> FrameSettings
    func photoData(id: String) async throws -> Data
    func upload(png: Data, filename: String) async throws -> UploadResponse
    func reorderQueue(photoIDs: [String]) async throws -> [QueueEntry]
    func removeFromQueue(photoID: String) async throws
    func deleteHistoryEntry(id: Int) async throws
    func clearHistory() async throws
    func next() async throws
    func previous() async throws
}
