import Foundation
@preconcurrency import Network
import InkyTLS

@MainActor protocol ProvisioningByteStream: AnyObject {
    func connect() async throws
    func read(maximum: Int) async throws -> Data
    func write(_ bytes: Data) async throws
    func cancel()
}

@MainActor protocol SoftAPProvisioningConnection: ProvisioningConnection {
    func configure(_ descriptor: SoftAPDescriptor)
    func useLAN(origin: URL) throws
    func useAccessPoint()
    func leaveAccessPoint()
}

@MainActor final class NetworkProvisioningByteStream: ProvisioningByteStream {
    private let connection: NWConnection
    private var connecting: CheckedContinuation<Void, Error>?
    private var cancelled = false

    init(host: String = "192.168.4.1") {
        let parameters = NWParameters.tcp
        parameters.requiredInterfaceType = .wifi
        parameters.prohibitExpensivePaths = true
        connection = NWConnection(host: NWEndpoint.Host(host), port: 9443, using: parameters)
    }

    func connect() async throws {
        guard !cancelled, connecting == nil else { throw SoftAPError.disconnected }
        try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
            connecting = continuation
            connection.stateUpdateHandler = { [weak self] state in
                Task { @MainActor in
                    guard let self else { return }
                    switch state {
                    case .ready: self.finishConnecting(nil)
                    case .failed: self.finishConnecting(SoftAPError.disconnected)
                    case .cancelled: self.finishConnecting(SoftAPError.cancelled)
                    default: break
                    }
                }
            }
            connection.start(queue: .main)
        }
    }

    func read(maximum: Int) async throws -> Data {
        guard !cancelled, (1...16_384).contains(maximum) else { throw SoftAPError.disconnected }
        return try await withCheckedThrowingContinuation { continuation in
            connection.receive(minimumIncompleteLength: 1, maximumLength: maximum) { data, _, complete, error in
                if error != nil { continuation.resume(throwing: SoftAPError.disconnected) }
                else if let data, !data.isEmpty { continuation.resume(returning: data) }
                else { continuation.resume(throwing: complete ? SoftAPError.disconnected : SoftAPError.invalidManifest) }
            }
        }
    }

    func write(_ bytes: Data) async throws {
        guard !cancelled, !bytes.isEmpty, bytes.count <= 16_384 else { throw SoftAPError.disconnected }
        try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
            connection.send(content: bytes, completion: .contentProcessed { error in
                if error != nil { continuation.resume(throwing: SoftAPError.disconnected) }
                else { continuation.resume() }
            })
        }
    }

    func cancel() {
        cancelled = true
        finishConnecting(SoftAPError.cancelled)
        connection.cancel()
    }

    private func finishConnecting(_ error: Error?) {
        guard let continuation = connecting else { return }
        connecting = nil
        if let error { continuation.resume(throwing: error) } else { continuation.resume() }
    }
}

/// TLS 1.3 over raw TCP; no GATT records, reset nonce, BLE discovery or BLE
/// identity reads. Both profiles use the same physical pin and existing codecs.
@MainActor final class TCPProvisioningConnection: SoftAPProvisioningConnection {
    private let hotspot: any SoftAPJoining
    private let makeStream: @MainActor (String) -> any ProvisioningByteStream
    private var descriptor: SoftAPDescriptor?
    private var descriptorExpiry: Task<Void, Never>?
    private var lanOrigin: URL?
    private var stream: (any ProvisioningByteStream)?
    private var tls: TLSClient?
    private var profile: SoftAPManifest.Profile?
    private var operation: UUID?
    private var deadline: Task<Void, Never>?
    private var timedOut = false
    private var interrupted = false
    private var joined = false

    init(hotspot: (any SoftAPJoining)? = nil,
         makeStream: (@MainActor (String) -> any ProvisioningByteStream)? = nil) {
        self.hotspot = hotspot ?? SoftAPHotspot()
        self.makeStream = makeStream ?? { NetworkProvisioningByteStream(host: $0) }
    }

    func configure(_ descriptor: SoftAPDescriptor) {
        disconnect()
        if self.descriptor != descriptor, let previous = self.descriptor { hotspot.leave(previous) }
        self.descriptor = descriptor
        lanOrigin = nil
        joined = false
        descriptorExpiry?.cancel()
        descriptorExpiry = Task { [weak self] in
            do { try await Task.sleep(for: .seconds(1800)) } catch { return }
            guard let self else { return }
            if let descriptor = self.descriptor { self.hotspot.leave(descriptor) }
            self.descriptor = nil
        }
    }

    func useLAN(origin: URL) throws {
        _ = try FactorySetupValidation.origin(origin.absoluteString)
        disconnect()
        lanOrigin = origin
    }

    func useAccessPoint() {
        disconnect()
        lanOrigin = nil
        joined = false
    }

    func leaveAccessPoint() {
        disconnect()
        if let descriptor { hotspot.leave(descriptor) }
        joined = false
    }

    func connect(peripheralID: UUID, identity: FrameIdentity) async throws -> PinnedFrameTrust {
        let manifest = try await establish(identity: identity, requested: .normal)
        return try PinnedFrameTrust(identity: identity, certificateDER: manifest.certificateDER)
    }

    func connectBootstrap(peripheralID: UUID, identity: FrameIdentity) async throws -> BootstrapFrameTrust {
        let manifest = try await establish(identity: identity, requested: .bootstrap)
        return try BootstrapFrameTrust(identity: identity, certificateDER: manifest.certificateDER)
    }

    private func establish(identity: FrameIdentity, requested: SoftAPManifest.Profile) async throws -> SoftAPManifest {
        guard operation == nil else { throw SoftAPError.busy }
        closeTransport()
        guard descriptor != nil || lanOrigin != nil else { throw SoftAPError.unavailable }
        let id = try begin(timeout: 45)
        defer { finish(id) }
        return try await cancellable(id) {
            if self.lanOrigin == nil, !self.joined {
                guard let descriptor = self.descriptor else { throw SoftAPError.unavailable }
                try await self.hotspot.join(descriptor)
                try self.check(id)
                self.joined = true
            }
            let stream = try await self.openStream(operation: id)
            try self.check(id)
            let prefix = try await self.readExactly(4, stream: stream, operation: id)
            let length = prefix.reduce(UInt32(0)) { ($0 << 8) | UInt32($1) }
            guard (1...4096).contains(length) else { throw SoftAPError.invalidManifest }
            let data = try await self.readExactly(Int(length), stream: stream, operation: id)
            let manifest = try SoftAPManifest.parse(data, identity: identity)
            if manifest.profile != requested {
                // Validate the actual profile, including strict current dates
                // for NORMAL. A redirect never installs ownership or grants RPC
                // authority; the caller must establish a fresh real handshake.
                if manifest.profile == .normal {
                    _ = try PinnedFrameTrust(identity: identity, certificateDER: manifest.certificateDER)
                    throw SoftAPError.normalProfileAvailable
                }
                _ = try BootstrapFrameTrust(identity: identity, certificateDER: manifest.certificateDER)
                throw SoftAPError.bootstrapProfileAvailable
            }
            let client: TLSClient
            if requested == .bootstrap {
                let trust = try BootstrapFrameTrust(identity: identity, certificateDER: manifest.certificateDER)
                client = try TLSClient(bootstrapConfiguration: BootstrapTLSConfiguration(serverName: trust.expectedServerName,
                    trustedCertificateDER: trust.certificateDER, pinnedSPKISHA256: identity.spkiSHA256))
            } else {
                let trust = try PinnedFrameTrust(identity: identity, certificateDER: manifest.certificateDER)
                client = try TLSClient(configuration: TLSConfiguration(serverName: trust.expectedServerName,
                    trustedCertificatesDER: [trust.certificateDER], pinnedSPKISHA256: identity.spkiSHA256))
            }
            self.tls = client
            while true {
                try self.check(id)
                let progress = try await client.advanceHandshake()
                try await self.drain(client, stream: stream, operation: id)
                if progress == .complete { break }
                if progress == .needsRead { try await self.feed(client, stream: stream, operation: id) }
            }
            guard await client.state == .open else { throw SoftAPError.disconnected }
            try self.check(id)
            self.profile = requested
            return manifest
        }
    }

    func request(_ data: Data, timeout: TimeInterval) async throws -> Data {
        try await request(data, timeout: timeout, requested: .normal)
    }
    func requestBootstrap(_ data: Data, timeout: TimeInterval) async throws -> Data {
        try await request(data, timeout: timeout, requested: .bootstrap)
    }

    private func request(_ data: Data, timeout: TimeInterval, requested: SoftAPManifest.Profile) async throws -> Data {
        guard profile == requested, let client = tls, let stream else { throw SoftAPError.disconnected }
        let framed = try BluetoothMessageBuffer.encode(data)
        let id = try begin(timeout: timeout)
        defer { finish(id) }
        return try await cancellable(id) {
            var remaining = framed
            while !remaining.isEmpty {
                let part = Data(remaining.prefix(16_384))
                remaining.removeFirst(part.count)
                try await client.queuePlaintext(part)
                while true {
                    try self.check(id)
                    let progress = try await client.flushPlaintext()
                    try await self.drain(client, stream: stream, operation: id)
                    if progress == .complete { break }
                    if progress == .needsRead { try await self.feed(client, stream: stream, operation: id) }
                }
            }
            var response = BluetoothMessageBuffer()
            while true {
                try self.check(id)
                switch try await client.readPlaintext() {
                case .bytes(let data):
                    try response.append(data)
                    if let message = response.message { return message }
                case .closed: throw SoftAPError.disconnected
                case .needsRead:
                    try await self.drain(client, stream: stream, operation: id)
                    try await self.feed(client, stream: stream, operation: id)
                case .needsWrite: try await self.drain(client, stream: stream, operation: id)
                }
            }
        }
    }

    func disconnect() {
        interrupted = true
        // joinOnce can disappear after lock/background. Never treat a previous
        // apply completion as a durable association on a new AP connection.
        // A LAN locator still bypasses AP joining in establish().
        joined = false
        closeTransport()
    }

    private func closeTransport() {
        hotspot.cancel()
        stream?.cancel()
        stream = nil
        tls = nil
        profile = nil
    }

    private func openStream(operation: UUID) async throws -> any ProvisioningByteStream {
        for attempt in 0..<10 {
            try check(operation)
            let candidate = makeStream(lanOrigin?.host ?? "192.168.4.1")
            stream = candidate
            do {
                try await candidate.connect()
                try check(operation)
                return candidate
            } catch {
                candidate.cancel()
                try check(operation)
                guard error as? SoftAPError == .disconnected, attempt < 9 else { throw error }
                try await Task.sleep(for: .milliseconds(500))
            }
        }
        throw SoftAPError.disconnected
    }

    private func readExactly(_ count: Int, stream: any ProvisioningByteStream, operation: UUID) async throws -> Data {
        var result = Data()
        while result.count < count {
            try check(operation)
            let data = try await stream.read(maximum: count - result.count)
            guard !data.isEmpty, data.count <= count - result.count else { throw SoftAPError.invalidManifest }
            result.append(data)
        }
        try check(operation)
        return result
    }
    private func drain(_ client: TLSClient, stream: any ProvisioningByteStream, operation: UUID) async throws {
        while true {
            try check(operation)
            let bytes = try await client.drainCiphertext(maxBytes: 16_384)
            if bytes.isEmpty { return }
            try await stream.write(bytes)
            try check(operation)
        }
    }
    private func feed(_ client: TLSClient, stream: any ProvisioningByteStream, operation: UUID) async throws {
        try check(operation)
        let capacity = await client.availableReceiveCapacity
        guard capacity > 0 else { throw SoftAPError.invalidManifest }
        let bytes = try await stream.read(maximum: min(capacity, 16_384))
        guard !bytes.isEmpty, bytes.count <= min(capacity, 16_384) else { throw SoftAPError.invalidManifest }
        try check(operation)
        try await client.receiveCiphertext(bytes)
    }
    private func begin(timeout: TimeInterval) throws -> UUID {
        guard operation == nil else { throw SoftAPError.busy }
        guard timeout.isFinite, timeout > 0, timeout <= 90 else { throw SoftAPError.invalidManifest }
        try Task.checkCancellation()
        let id = UUID()
        operation = id
        timedOut = false
        interrupted = false
        deadline = Task { [weak self] in
            do { try await Task.sleep(for: .seconds(timeout)) } catch { return }
            guard let self, self.operation == id else { return }
            self.timedOut = true
            self.closeTransport()
        }
        return id
    }
    private func check(_ id: UUID) throws {
        guard operation == id else { throw SoftAPError.cancelled }
        if timedOut { throw SoftAPError.timeout }
        if interrupted { throw SoftAPError.cancelled }
        try Task.checkCancellation()
    }
    private func finish(_ id: UUID) {
        guard operation == id else { return }
        deadline?.cancel()
        deadline = nil
        operation = nil
        timedOut = false
    }
    private func cancellable<T>(_ id: UUID, _ action: () async throws -> T) async throws -> T {
        try await withTaskCancellationHandler {
            do { return try await action() }
            catch {
                closeTransport()
                if timedOut { throw SoftAPError.timeout }
                throw error
            }
        } onCancel: { [weak self] in
            Task { @MainActor in if self?.operation == id { self?.disconnect() } }
        }
    }
}
