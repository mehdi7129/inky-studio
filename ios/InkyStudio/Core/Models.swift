import Foundation

enum ChangeMode: String, Codable, CaseIterable, Sendable {
    case daily, interval, manual
}

struct Photo: Codable, Identifiable, Hashable, Sendable {
    var id: String
    var sha256: String
    var originalFilename: String
    var mime: String
    var width: Int
    var height: Int
    var sizeBytes: Int
    var createdAt: Double
}

struct QueueEntry: Codable, Identifiable, Equatable, Sendable {
    var id: Int
    var position: Int
    var addedAt: Double
    var photo: Photo
}

struct HistoryEntry: Codable, Identifiable, Equatable, Sendable {
    var id: Int
    var displayedAt: Double
    var source: String
    var photo: Photo
}

struct FrameSettings: Codable, Equatable, Sendable {
    var changeMode: ChangeMode = .daily
    var changeHour: Int = 5
    var changeIntervalMinutes: Int = 60
    var saturation: Double = 1
}

struct DisplayInfo: Codable, Equatable, Sendable {
    var model: String
    var width: Int
    var height: Int
    var colors: Int
    var isMock: Bool
}

struct DisplayState: Codable, Equatable, Sendable {
    var display: DisplayInfo
    var current: HistoryEntry?
    var queueCount: Int
    var nextChangeAt: Double?
}

struct AuthStatus: Codable, Equatable, Sendable {
    var authenticated: Bool
    var authRequired: Bool
    // Absent on older frame versions; never infer support from a version string.
    var passwordChangeSupported: Bool?
}

struct HealthResponse: Codable, Equatable, Sendable {
    var status: String
    var version: String
}

struct UpdateStatus: Codable, Equatable, Sendable {
    var current: String
    var latest: String?
    var updateAvailable: Bool
}

struct UploadResponse: Codable, Equatable, Sendable {
    var photo: Photo
    var queueEntry: QueueEntry
    var alreadyExisted: Bool
}

/// Event payloads differ by event type and may acquire fields in future releases.
enum JSONValue: Codable, Equatable, Sendable {
    case string(String), number(Double), bool(Bool)
    case object([String: JSONValue]), array([JSONValue]), null

    init(from decoder: Decoder) throws {
        let value = try decoder.singleValueContainer()
        if value.decodeNil() { self = .null }
        else if let decoded = try? value.decode(Bool.self) { self = .bool(decoded) }
        else if let decoded = try? value.decode(Double.self) { self = .number(decoded) }
        else if let decoded = try? value.decode(String.self) { self = .string(decoded) }
        else if let decoded = try? value.decode([String: JSONValue].self) { self = .object(decoded) }
        else { self = .array(try value.decode([JSONValue].self)) }
    }

    func encode(to encoder: Encoder) throws {
        var value = encoder.singleValueContainer()
        switch self {
        case .string(let string): try value.encode(string)
        case .number(let number): try value.encode(number)
        case .bool(let bool): try value.encode(bool)
        case .object(let object): try value.encode(object)
        case .array(let array): try value.encode(array)
        case .null: try value.encodeNil()
        }
    }

    var stringValue: String? {
        guard case .string(let value) = self else { return nil }
        return value
    }

    var boolValue: Bool? {
        guard case .bool(let value) = self else { return nil }
        return value
    }
}

struct ServerEvent: Codable, Equatable, Sendable {
    var type: String
    var payload: [String: JSONValue] = [:]
}
