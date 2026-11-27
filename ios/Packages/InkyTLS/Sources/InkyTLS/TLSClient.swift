import CInkyTLS
import Foundation

public struct TLSConfiguration: Sendable {
    public let serverName: String
    public let trustedCertificatesDER: [Data]
    public let pinnedSPKISHA256: Data
    public let bufferCapacity: Int

    /// Trust must be established outside this package (e.g. physical QR pin comparison).
    /// Each anchor is a DER certificate, not a PEM string. No system trust or trust-all mode.
    public init(serverName: String, trustedCertificatesDER: [Data],
                pinnedSPKISHA256: Data, bufferCapacity: Int = 65_536) throws {
        guard !serverName.isEmpty, serverName.utf8.count <= 253,
              serverName.utf8.allSatisfy({ $0 > 32 && $0 < 127 }),
              (1...8).contains(trustedCertificatesDER.count),
              trustedCertificatesDER.allSatisfy({ !$0.isEmpty && $0.count <= 65_536 }),
              pinnedSPKISHA256.count == 32, (1_024...262_144).contains(bufferCapacity) else {
            throw TLSError.invalidConfiguration
        }
        self.serverName = serverName
        self.trustedCertificatesDER = trustedCertificatesDER
        self.pinnedSPKISHA256 = pinnedSPKISHA256
        self.bufferCapacity = bufferCapacity
    }
}

/// Explicit pinned-key bootstrap policy, separate from normal date-valid TLS.
/// The pin must originate in a physical QR or an already trusted ownership record.
/// This type does not authenticate the phone or authorize any frame mutation.
public struct BootstrapTLSConfiguration: Sendable {
    public let serverName: String
    public let trustedCertificateDER: Data
    public let pinnedSPKISHA256: Data
    public let bufferCapacity: Int

    public init(serverName: String, trustedCertificateDER: Data,
                pinnedSPKISHA256: Data, bufferCapacity: Int = 65_536) throws {
        let prefix = "frame-", suffix = ".inky.invalid"
        guard serverName.hasPrefix(prefix), serverName.hasSuffix(suffix),
              serverName.utf8.count == 55 else { throw TLSError.invalidConfiguration }
        let identifier = String(serverName.dropFirst(prefix.count).dropLast(suffix.count))
        guard let frameID = UUID(uuidString: identifier), frameID.uuidString.lowercased() == identifier,
              !trustedCertificateDER.isEmpty, trustedCertificateDER.count <= 65_536,
              pinnedSPKISHA256.count == 32, (1_024...262_144).contains(bufferCapacity) else {
            throw TLSError.invalidConfiguration
        }
        self.serverName = serverName
        self.trustedCertificateDER = trustedCertificateDER
        self.pinnedSPKISHA256 = pinnedSPKISHA256
        self.bufferCapacity = bufferCapacity
    }
}

public enum TLSState: Sendable, Equatable { case handshaking, open, closing, closed, failed }
public enum TLSProgress: Sendable, Equatable { case complete, needsRead, needsWrite }
public enum TLSReadResult: Sendable, Equatable { case bytes(Data), needsRead, needsWrite, closed }
public enum TLSError: Error, Sendable, Equatable {
    case invalidConfiguration
    case invalidArgument
    case invalidState
    /// No bytes were consumed: retain the input and retry after making room.
    case backpressure
    case pinMismatch
    case bootstrapPolicyRejected
    case allocationFailed
    case truncatedTransport
    case failure(code: Int32, description: String)
}

// All C calls, including destruction, hold the bridge's process-wide mutex.
// The actor is the only API owner; this holder makes nonisolated deinit safe.
private final class TLSHandle: @unchecked Sendable {
    let pointer: OpaquePointer
    init(_ pointer: OpaquePointer) { self.pointer = pointer }
    deinit { inky_tls_destroy(pointer) }
}

/// A nonblocking TLS 1.3 client over caller-provided ordered ciphertext bytes.
/// No network/Bluetooth I/O or ownership decisions occur here. Create a new instance
/// after disconnect; never mix fragments across transports or reuse a failed session.
public actor TLSClient {
    private let handle: TLSHandle

    public init(configuration: TLSConfiguration) throws {
        var code: Int32 = 0
        let context = configuration.pinnedSPKISHA256.withUnsafeBytes { pin in
            configuration.serverName.withCString { name in
                inky_tls_create(name, pin.bindMemory(to: UInt8.self).baseAddress,
                                pin.count, configuration.bufferCapacity, &code)
            }
        }
        guard let context else { throw Self.error(code) }
        let handle = TLSHandle(context)
        for certificate in configuration.trustedCertificatesDER {
            let result = certificate.withUnsafeBytes { bytes in
                inky_tls_add_trust_der(context, bytes.bindMemory(to: UInt8.self).baseAddress, bytes.count)
            }
            guard result == 0 else { throw Self.error(result) }
        }
        self.handle = handle
    }

    /// The C bridge rechecks exact anchor/pin, P-256, self-signature, usages and
    /// canonical identity. Only date errors are relaxed, and only in this profile.
    /// No plaintext is available until TLS 1.3 and inky-bootstrap/1 ALPN succeed.
    public init(bootstrapConfiguration configuration: BootstrapTLSConfiguration) throws {
        var code: Int32 = 0
        let context = configuration.pinnedSPKISHA256.withUnsafeBytes { pin in
            configuration.serverName.withCString { name in
                inky_tls_create_bootstrap(name, pin.bindMemory(to: UInt8.self).baseAddress,
                                          pin.count, configuration.bufferCapacity, &code)
            }
        }
        guard let context else { throw Self.error(code) }
        let handle = TLSHandle(context)
        let result = configuration.trustedCertificateDER.withUnsafeBytes { bytes in
            inky_tls_add_trust_der(context, bytes.bindMemory(to: UInt8.self).baseAddress, bytes.count)
        }
        guard result == 0 else { throw Self.error(result) }
        self.handle = handle
    }

    public var state: TLSState {
        switch Int(inky_tls_state(handle.pointer)) {
        case INKY_TLS_HANDSHAKING: .handshaking
        case INKY_TLS_OPEN: .open
        case INKY_TLS_CLOSING: .closing
        case INKY_TLS_CLOSED_STATE: .closed
        default: .failed
        }
    }
    public var pendingPlaintextByteCount: Int { inky_tls_pending_plaintext(handle.pointer) }
    public var availableReceiveCapacity: Int { inky_tls_receive_capacity(handle.pointer) }

    /// All-or-nothing enqueue; backpressure leaves the input entirely with the caller.
    public func receiveCiphertext(_ data: Data) throws {
        let result = data.withUnsafeBytes { bytes in
            inky_tls_feed(handle.pointer, bytes.bindMemory(to: UInt8.self).baseAddress, bytes.count)
        }
        try Self.check(result)
    }

    public func drainCiphertext(maxBytes: Int) throws -> Data {
        guard (1...262_144).contains(maxBytes) else { throw TLSError.invalidArgument }
        var output = Data(count: maxBytes)
        let count = output.withUnsafeMutableBytes { bytes in
            inky_tls_take(handle.pointer, bytes.bindMemory(to: UInt8.self).baseAddress, bytes.count)
        }
        guard count >= 0 else { throw Self.error(count) }
        output.count = Int(count)
        return output
    }

    public func advanceHandshake() throws -> TLSProgress {
        try Self.progress(inky_tls_handshake(handle.pointer))
    }

    /// One owned plaintext buffer, up to 16 KiB. Cannot be queued before authenticated TLS.
    /// Once queued, call flushPlaintext and drainCiphertext until pending count is zero.
    public func queuePlaintext(_ data: Data) throws {
        let result = data.withUnsafeBytes { bytes in
            inky_tls_queue_plaintext(handle.pointer, bytes.bindMemory(to: UInt8.self).baseAddress, bytes.count)
        }
        try Self.check(result)
    }

    /// WANT_WRITE retries retain identical owned bytes; caller buffers may be released.
    public func flushPlaintext() throws -> TLSProgress {
        try Self.progress(inky_tls_flush_plaintext(handle.pointer))
    }

    public func readPlaintext(maxBytes: Int = 16_384) throws -> TLSReadResult {
        guard (1...16_384).contains(maxBytes) else { throw TLSError.invalidArgument }
        var output = Data(count: maxBytes)
        let count = output.withUnsafeMutableBytes { bytes in
            inky_tls_read_plaintext(handle.pointer, bytes.bindMemory(to: UInt8.self).baseAddress, bytes.count)
        }
        switch Int(count) {
        case -INKY_TLS_WANT_READ: return .needsRead
        case -INKY_TLS_WANT_WRITE: return .needsWrite
        case -INKY_TLS_CLOSED: return .closed
        case 1...:
            output.count = Int(count)
            return .bytes(output)
        default: throw Self.error(count)
        }
    }

    /// Flush pending plaintext first, then drain the close_notify ciphertext.
    public func close() throws -> TLSProgress { try Self.progress(inky_tls_close(handle.pointer)) }

    /// Signal actual transport EOF; subsequent handshake/read diagnoses missing close_notify.
    public func transportDidEnd() { inky_tls_transport_ended(handle.pointer) }

    private static func check(_ code: Int32) throws {
        guard code == 0 else { throw error(code) }
    }
    private static func progress(_ code: Int32) throws -> TLSProgress {
        switch Int(code) {
        case INKY_TLS_OK: .complete
        case INKY_TLS_WANT_READ: .needsRead
        case INKY_TLS_WANT_WRITE: .needsWrite
        default: throw error(code)
        }
    }
    private static func error(_ code: Int32) -> TLSError {
        switch Int(code) {
        case INKY_TLS_INVALID_ARGUMENT: return .invalidArgument
        case INKY_TLS_INVALID_STATE: return .invalidState
        case INKY_TLS_BACKPRESSURE: return .backpressure
        case INKY_TLS_PIN_MISMATCH: return .pinMismatch
        case INKY_TLS_BOOTSTRAP_POLICY: return .bootstrapPolicyRejected
        case INKY_TLS_ALLOCATION_FAILED: return .allocationFailed
        case INKY_TLS_TRUNCATED: return .truncatedTransport
        default:
            var bytes = [CChar](repeating: 0, count: 256)
            inky_tls_error_description(code, &bytes, bytes.count)
            let description = String(decoding: bytes.prefix { $0 != 0 }.map { UInt8(bitPattern: $0) }, as: UTF8.self)
            return .failure(code: code, description: description)
        }
    }
}
