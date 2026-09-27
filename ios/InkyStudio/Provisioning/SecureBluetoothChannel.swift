import Foundation
import Security
import InkyTLS

enum SecureBluetoothError: Error, LocalizedError, Equatable {
    case busy, notConnected, invalidIdentity, invalidRecord, invalidMessage, timeout, cancelled, randomUnavailable
    var errorDescription: String? {
        switch self {
        case .busy: "Une demande au cadre est déjà en cours."
        case .notConnected: "Reconnectez-vous au cadre en Bluetooth."
        case .invalidIdentity: "L’identité du cadre ne correspond pas au QR code."
        case .invalidRecord, .invalidMessage: "Le cadre a envoyé une réponse invalide."
        case .timeout: "Le cadre n’a pas répondu à temps."
        case .cancelled: "La demande a été annulée."
        case .randomUnavailable: "Impossible de créer une connexion sécurisée."
        }
    }
}

/// A connection has one monotonically increasing exchange sequence. Reads/retries
/// never advance it until an exact acknowledgement has been verified.
struct BluetoothRecordState {
    private(set) var acknowledged: UInt16 = 0
    func encode(_ payload: Data, maximum: Int) throws -> Data {
        guard (20...244).contains(maximum), payload.count <= maximum - 5,
              acknowledged < 65_534 else { throw SecureBluetoothError.invalidRecord }
        let next = acknowledged + 1
        return Data([1, UInt8(next >> 8), UInt8(next & 255),
                     UInt8(acknowledged >> 8), UInt8(acknowledged & 255)]) + payload
    }
    mutating func accept(_ frame: Data, maximum: Int) throws -> Data {
        guard frame.count >= 5, frame.count <= maximum, acknowledged < 65_534 else {
            throw SecureBluetoothError.invalidRecord
        }
        let bytes = [UInt8](frame.prefix(5))
        let next = acknowledged + 1
        guard bytes[0] == 1, UInt16(bytes[1]) << 8 | UInt16(bytes[2]) == next,
              UInt16(bytes[3]) << 8 | UInt16(bytes[4]) == next else { throw SecureBluetoothError.invalidRecord }
        acknowledged = next
        return Data(frame.dropFirst(5))
    }
}

/// Bounded, single-message framing. Reject trailing bytes instead of queuing an
/// unsolicited second response for a later request.
struct BluetoothMessageBuffer {
    private var bytes = Data()
    private var expected: Int?
    mutating func append(_ data: Data) throws {
        guard !data.isEmpty, bytes.count + data.count <= 16_388 else { throw SecureBluetoothError.invalidMessage }
        bytes.append(data)
        if expected == nil, bytes.count >= 4 {
            let prefix = [UInt8](bytes.prefix(4))
            let count = prefix.reduce(UInt32(0)) { ($0 << 8) | UInt32($1) }
            guard (1...16_384).contains(count) else { throw SecureBluetoothError.invalidMessage }
            expected = Int(count)
        }
        if let expected, bytes.count > expected + 4 { throw SecureBluetoothError.invalidMessage }
    }
    var message: Data? {
        guard let expected, bytes.count == expected + 4 else { return nil }
        return Data(bytes.dropFirst(4))
    }
    static func encode(_ message: Data) throws -> Data {
        guard (1...16_384).contains(message.count) else { throw SecureBluetoothError.invalidMessage }
        let count = UInt32(message.count)
        return Data([UInt8(count >> 24), UInt8((count >> 16) & 255),
                     UInt8((count >> 8) & 255), UInt8(count & 255)]) + message
    }
}

/// TLS 1.3 over the v1 GATT byte stream, reusable on iOS and macOS. Commands remain
/// opaque JSON bytes: the coordinator owns request IDs, ownership and operations.
/// Each reconnect verifies a fresh certificate against the persisted physical pin.
@MainActor final class SecureBluetoothChannel {
    private let transport: any BluetoothExchanging
    private var tls: TLSClient?
    private(set) var trust: PinnedFrameTrust?
    private var records = BluetoothRecordState()
    private var operation: UUID?
    private var termination: SecureBluetoothError?
    private var deadline: Task<Void, Never>?

    init(transport: any BluetoothExchanging) { self.transport = transport }

    func connect(peripheralID: UUID, identity: FrameIdentity) async throws -> PinnedFrameTrust {
        let id = try begin(timeout: 45)
        tls = nil
        trust = nil
        records = BluetoothRecordState()
        defer { finish(id) }
        return try await withTaskCancellationHandler {
            do {
                let data = try await transport.connect(peripheralID: peripheralID)
                try check(id)
                struct PublicIdentity: Decodable { let v: Int; let id: UUID; let cert: Data }
                guard data.count <= 4096, let advertised = try? JSONDecoder().decode(PublicIdentity.self, from: data),
                      advertised.v == 1, advertised.id == identity.id else { throw SecureBluetoothError.invalidIdentity }
                // Both SPKI comparison and Security's date/name/usage validation
                // precede RESET/TLS. The TLS bridge independently validates X509.
                let verified = try PinnedFrameTrust(identity: identity, certificateDER: advertised.cert)
                let configuration = try TLSConfiguration(serverName: verified.expectedServerName,
                    trustedCertificatesDER: [verified.certificateDER], pinnedSPKISHA256: identity.spkiSHA256)
                let client = try TLSClient(configuration: configuration)
                var nonce = Data(count: 16)
                let result = nonce.withUnsafeMutableBytes { SecRandomCopyBytes(kSecRandomDefault, $0.count, $0.baseAddress!) }
                guard result == errSecSuccess else { throw SecureBluetoothError.randomUnavailable }
                let reset = Data([0]) + nonce
                let echo = try await transport.exchange(reset)
                try check(id)
                guard echo == reset else { throw SecureBluetoothError.invalidRecord }
                tls = client
                while true {
                    try check(id)
                    let progress = try await client.advanceHandshake()
                    let outbound = try await client.drainCiphertext(maxBytes: payloadCapacity)
                    try check(id)
                    if progress == .complete, outbound.isEmpty { break }
                    try await transfer(outbound, client: client, operation: id)
                }
                trust = verified
                return verified
            } catch {
                let result = termination ?? (error as? SecureBluetoothError)
                abortConnection()
                throw result ?? error
            }
        } onCancel: { [weak self] in
            Task { @MainActor in self?.abort(id, reason: .cancelled) }
        }
    }

    /// Claim may use 90 seconds because its physical e-ink update is slow; other
    /// requests default to 20 seconds. There is no pending-request queue.
    func request(_ data: Data, timeout: TimeInterval = 20) async throws -> Data {
        let framed = try BluetoothMessageBuffer.encode(data)
        guard let client = tls, trust != nil else { throw SecureBluetoothError.notConnected }
        let id = try begin(timeout: timeout)
        defer { finish(id) }
        return try await withTaskCancellationHandler {
            do {
                // A maximum JSON message plus its 4-byte prefix spans two writes.
                var remaining = framed
                while !remaining.isEmpty {
                    let part = Data(remaining.prefix(16_384))
                    remaining.removeFirst(part.count)
                    try await client.queuePlaintext(part)
                    while true {
                        try check(id)
                        let progress = try await client.flushPlaintext()
                        let outbound = try await client.drainCiphertext(maxBytes: payloadCapacity)
                        try check(id)
                        if progress == .complete, outbound.isEmpty { break }
                        try await transfer(outbound, client: client, operation: id)
                    }
                }
                var response = BluetoothMessageBuffer()
                while true {
                    try check(id)
                    switch try await client.readPlaintext() {
                    case .bytes(let bytes): try response.append(bytes)
                    case .closed: throw SecureBluetoothError.notConnected
                    case .needsRead, .needsWrite:
                        try check(id)
                        let outbound = try await client.drainCiphertext(maxBytes: payloadCapacity)
                        try check(id)
                        if let message = response.message, outbound.isEmpty { return message }
                        try await transfer(outbound, client: client, operation: id)
                    }
                }
            } catch {
                let result = termination ?? (error as? SecureBluetoothError)
                abortConnection()
                throw result ?? error
            }
        } onCancel: { [weak self] in
            Task { @MainActor in self?.abort(id, reason: .cancelled) }
        }
    }

    func disconnect() {
        if let operation { abort(operation, reason: .cancelled) }
        else { abortConnection() }
    }

    private var payloadCapacity: Int { min(244, max(20, transport.maxFrameLength)) - 5 }

    private func transfer(_ payload: Data, client: TLSClient, operation: UUID) async throws {
        try check(operation)
        let maximum = transport.maxFrameLength
        let frame = try records.encode(payload, maximum: maximum)
        let response = try await transport.exchange(frame)
        try check(operation)
        // Peer output is bounded independently of a write limit captured before
        // an await; CoreBluetooth can update the MTU while an exchange is in flight.
        let incoming = try records.accept(response, maximum: 244)
        if !incoming.isEmpty { try await client.receiveCiphertext(incoming) }
        // An idle poll needs to let the server's asynchronous operation progress;
        // do not spin at radio speed while it refreshes e-ink or searches Wi-Fi.
        if payload.isEmpty, incoming.isEmpty { try await Task.sleep(nanoseconds: 20_000_000) }
        try check(operation)
    }

    private func begin(timeout: TimeInterval) throws -> UUID {
        guard operation == nil else { throw SecureBluetoothError.busy }
        guard timeout.isFinite, timeout > 0, timeout <= 90 else { throw SecureBluetoothError.invalidMessage }
        try Task.checkCancellation()
        let id = UUID()
        operation = id
        termination = nil
        deadline = Task { [weak self] in
            do { try await Task.sleep(nanoseconds: UInt64(timeout * 1_000_000_000)) } catch { return }
            self?.abort(id, reason: .timeout)
        }
        return id
    }
    private func check(_ id: UUID) throws {
        guard operation == id else { throw SecureBluetoothError.cancelled }
        if let termination { throw termination }
        try Task.checkCancellation()
    }
    private func abort(_ id: UUID, reason: SecureBluetoothError) {
        guard operation == id, termination == nil else { return }
        termination = reason
        abortConnection()
    }
    private func abortConnection() {
        transport.cancel()
        tls = nil
        trust = nil
        records = BluetoothRecordState()
    }
    private func finish(_ id: UUID) {
        guard operation == id else { return }
        deadline?.cancel()
        deadline = nil
        operation = nil
        termination = nil
    }
}
