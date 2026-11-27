import Foundation
import Security
import CryptoKit

/// Immutable trust established from a physical QR, never from a BLE advertisement.
/// This freshly received BLE certificate is verified before use. HTTPS derives
/// policy from the identity so a same-key certificate can renew independently.
struct PinnedFrameTrust: Equatable, Sendable {
    let identity: FrameIdentity
    let certificateDER: Data

    var expectedServerName: String { identity.expectedServerName }
    var policy: FrameTrustPolicy { FrameTrustPolicy(identity: identity) }

    init(identity: FrameIdentity, certificateDER: Data, at date: Date = Date()) throws {
        guard try Self.spkiSHA256(certificateDER: certificateDER) == identity.spkiSHA256 else {
            throw FrameIdentityError.pinMismatch
        }
        self.identity = identity
        self.certificateDER = certificateDER
        let certificate = try Self.certificate(certificateDER)
        var trust: SecTrust?
        guard SecTrustCreateWithCertificates(certificate,
            SecPolicyCreateSSL(true, identity.expectedServerName as CFString), &trust) == errSecSuccess,
            let trust else { throw FrameIdentityError.invalidCertificate }
        try policy.validate(serverTrust: trust, at: date)
    }

    /// P-256's public Security representation is X9.63, not SPKI. Prefix it with
    /// canonical DER for id-ecPublicKey + prime256v1, then hash the complete SPKI.
    static func spkiSHA256(certificateDER: Data) throws -> Data {
        let certificate = try certificate(certificateDER)
        guard let key = SecCertificateCopyKey(certificate),
              let attributes = SecKeyCopyAttributes(key) as? [String: Any],
              attributes[kSecAttrKeyType as String] as? String == kSecAttrKeyTypeECSECPrimeRandom as String,
              attributes[kSecAttrKeySizeInBits as String] as? Int == 256,
              let raw = SecKeyCopyExternalRepresentation(key, nil) as Data?,
              raw.count == 65, raw.first == 4 else { throw FrameIdentityError.unsupportedKey }
        // CryptoKit additionally checks that the point is on the P-256 curve.
        guard (try? P256.Signing.PublicKey(x963Representation: raw)) != nil else {
            throw FrameIdentityError.unsupportedKey
        }
        let prefix = Data([0x30, 0x59, 0x30, 0x13, 0x06, 0x07, 0x2A, 0x86,
                           0x48, 0xCE, 0x3D, 0x02, 0x01, 0x06, 0x08, 0x2A,
                           0x86, 0x48, 0xCE, 0x3D, 0x03, 0x01, 0x07, 0x03, 0x42, 0x00])
        let spki = prefix + raw
        // Require the certificate's algorithm OIDs and encoding to say P-256,
        // rather than inferring the curve from an EC key's size alone.
        guard try encodedSPKI(in: certificateDER) == spki else { throw FrameIdentityError.unsupportedKey }
        return Data(SHA256.hash(data: spki))
    }

    func validate(serverTrust: SecTrust, at date: Date = Date()) throws { try policy.validate(serverTrust: serverTrust, at: date) }
    func credential(for challenge: URLAuthenticationChallenge) -> URLCredential? { policy.credential(for: challenge) }
    func validateHTTPS(_ endpoint: URL) throws { try policy.validateHTTPS(endpoint) }

    /// SecTrust does not verify a trust anchor's own signature. Protocol v1 has
    /// exactly self-signed P-256 / ECDSA-SHA256 certificates, verified here using
    /// Security's signature implementation before approving the pinned anchor.
    fileprivate static func verifySelfSignature(_ der: Data) throws {
        let certificate = try certificate(der)
        guard let key = SecCertificateCopyKey(certificate) else { throw FrameIdentityError.invalidCertificate }
        var outer = CertificateDERReader(der)
        var fields = CertificateDERReader(try outer.read(tag: 0x30).content)
        guard outer.isAtEnd else { throw FrameIdentityError.invalidCertificate }
        let tbs = try fields.read(tag: 0x30)
        let signatureAlgorithm = try fields.read(tag: 0x30).encoded
        let signature = try fields.read(tag: 0x03).content
        let ecdsaSHA256 = Data([0x30, 0x0a, 0x06, 0x08, 0x2a, 0x86, 0x48, 0xce, 0x3d, 0x04, 0x03, 0x02])
        guard fields.isAtEnd, signatureAlgorithm == ecdsaSHA256,
              signature.first == 0, (9...73).contains(signature.count) else { throw FrameIdentityError.certificateRejected }
        var body = CertificateDERReader(tbs.content)
        if body.nextTag == 0xa0 { _ = try body.read(tag: 0xa0) }
        _ = try body.read(tag: 0x02)
        let innerAlgorithm = try body.read(tag: 0x30).encoded
        let issuer = try body.read(tag: 0x30).encoded
        _ = try body.read(tag: 0x30) // validity is evaluated by SecTrust
        let subject = try body.read(tag: 0x30).encoded
        guard innerAlgorithm == ecdsaSHA256, issuer == subject,
              SecKeyIsAlgorithmSupported(key, .verify, .ecdsaSignatureMessageX962SHA256),
              SecKeyVerifySignature(key, .ecdsaSignatureMessageX962SHA256, tbs.encoded as CFData,
                                    Data(signature.dropFirst()) as CFData, nil) else {
            throw FrameIdentityError.certificateRejected
        }
        // Security may treat a self-signed CA's keyCertSign as sufficient when
        // it is the explicit anchor. Our frame leaf must also authorize TLS
        // signatures; the generated v1 certificate always carries this usage.
        try requireDigitalSignatureUsage(in: &body)
    }

    private static func requireDigitalSignatureUsage(in body: inout CertificateDERReader) throws {
        _ = try body.read(tag: 0x30) // SubjectPublicKeyInfo
        if body.nextTag == 0x81 { _ = try body.read(tag: 0x81) } // issuerUniqueID
        if body.nextTag == 0x82 { _ = try body.read(tag: 0x82) } // subjectUniqueID
        var wrapper = CertificateDERReader(try body.read(tag: 0xa3).content)
        var extensions = CertificateDERReader(try wrapper.read(tag: 0x30).content)
        guard body.isAtEnd, wrapper.isAtEnd else { throw FrameIdentityError.invalidCertificate }
        var foundUsage = false
        while !extensions.isAtEnd {
            var item = CertificateDERReader(try extensions.read(tag: 0x30).content)
            let oid = try item.read(tag: 0x06).content
            if item.nextTag == 0x01 {
                let critical = try item.read(tag: 0x01).content
                guard critical.count == 1, critical.first == 0 || critical.first == 0xff else {
                    throw FrameIdentityError.invalidCertificate
                }
            }
            let value = try item.read(tag: 0x04).content
            guard item.isAtEnd else { throw FrameIdentityError.invalidCertificate }
            guard oid == Data([0x55, 0x1d, 0x0f]) else { continue }
            guard !foundUsage else { throw FrameIdentityError.invalidCertificate }
            foundUsage = true
            var encodedUsage = CertificateDERReader(value)
            let bits = try encodedUsage.read(tag: 0x03).content
            guard encodedUsage.isAtEnd, (2...3).contains(bits.count),
                  let unused = bits.first, unused < 8,
                  (bits.count - 1) * 8 - Int(unused) <= 9,
                  bits[bits.index(after: bits.startIndex)] & 0x80 != 0,
                  let last = bits.last, last & UInt8((1 << Int(unused)) - 1) == 0 else {
                throw FrameIdentityError.certificateRejected
            }
        }
        guard foundUsage else { throw FrameIdentityError.certificateRejected }
    }

    private static func certificate(_ der: Data) throws -> SecCertificate {
        guard !der.isEmpty, der.count <= 8192,
              let certificate = SecCertificateCreateWithData(nil, der as CFData) else {
            throw FrameIdentityError.invalidCertificate
        }
        return certificate
    }

    private static func encodedSPKI(in certificate: Data) throws -> Data {
        var outer = CertificateDERReader(certificate)
        let sequence = try outer.read(tag: 0x30)
        guard outer.isAtEnd else { throw FrameIdentityError.invalidCertificate }
        var body = CertificateDERReader(sequence.content)
        var tbs = CertificateDERReader(try body.read(tag: 0x30).content)
        if tbs.nextTag == 0xa0 { _ = try tbs.read(tag: 0xa0) }
        _ = try tbs.read(tag: 0x02) // serialNumber
        _ = try tbs.read(tag: 0x30) // signature
        _ = try tbs.read(tag: 0x30) // issuer
        _ = try tbs.read(tag: 0x30) // validity
        _ = try tbs.read(tag: 0x30) // subject
        return try tbs.read(tag: 0x30).encoded
    }
}

/// A URLSession delegate stores this immutable value. The peer's current leaf
/// must match the adopted key before becoming the only trusted anchor. This
/// permits same-key certificate renewal without accepting a new frame identity.
struct FrameTrustPolicy: Equatable, Sendable {
    let identity: FrameIdentity
    var expectedServerName: String { identity.expectedServerName }

    func validate(serverTrust: SecTrust, at date: Date = Date()) throws {
        guard let chain = SecTrustCopyCertificateChain(serverTrust) as? [SecCertificate],
              let leaf = chain.first else { throw FrameIdentityError.invalidCertificate }
        guard try PinnedFrameTrust.spkiSHA256(certificateDER: SecCertificateCopyData(leaf) as Data) == identity.spkiSHA256 else {
            throw FrameIdentityError.pinMismatch
        }
        try PinnedFrameTrust.verifySelfSignature(SecCertificateCopyData(leaf) as Data)
        guard SecTrustSetPolicies(serverTrust, SecPolicyCreateSSL(true, expectedServerName as CFString)) == errSecSuccess,
              SecTrustSetAnchorCertificates(serverTrust, [leaf] as CFArray) == errSecSuccess,
              SecTrustSetAnchorCertificatesOnly(serverTrust, true) == errSecSuccess,
              SecTrustSetNetworkFetchAllowed(serverTrust, false) == errSecSuccess,
              SecTrustSetVerifyDate(serverTrust, date as CFDate) == errSecSuccess else {
            throw FrameIdentityError.certificateRejected
        }
        var error: CFError?
        guard SecTrustEvaluateWithError(serverTrust, &error) else { throw FrameIdentityError.certificateRejected }
    }

    func credential(for challenge: URLAuthenticationChallenge) -> URLCredential? {
        guard challenge.protectionSpace.authenticationMethod == NSURLAuthenticationMethodServerTrust,
              let trust = challenge.protectionSpace.serverTrust,
              (try? validate(serverTrust: trust)) != nil else { return nil }
        return URLCredential(trust: trust)
    }

    func validateHTTPS(_ endpoint: URL) throws {
        guard endpoint.scheme?.lowercased() == "https" else { throw FrameIdentityError.insecureEndpoint }
        guard let parts = URLComponents(url: endpoint, resolvingAgainstBaseURL: false),
              let host = parts.host, !host.isEmpty,
              parts.user == nil, parts.password == nil,
              parts.query == nil, parts.fragment == nil,
              parts.path.isEmpty || parts.path == "/",
              parts.port.map({ (1...65535).contains($0) }) ?? true else {
            throw FrameIdentityError.invalidEndpoint
        }
    }
}

/// Minimal bounded DER navigation. Certificate semantics remain Security's job.
private struct CertificateDERReader {
    private let bytes: [UInt8]
    private var offset = 0
    init(_ data: Data) { bytes = Array(data) }
    var nextTag: UInt8? { offset < bytes.count ? bytes[offset] : nil }
    var isAtEnd: Bool { offset == bytes.count }
    mutating func read(tag: UInt8) throws -> (encoded: Data, content: Data) {
        let start = offset
        guard nextTag == tag, offset + 1 < bytes.count else { throw FrameIdentityError.invalidCertificate }
        offset += 1
        let first = bytes[offset]
        offset += 1
        var count = Int(first)
        if first & 0x80 != 0 {
            let lengthBytes = Int(first & 0x7f)
            guard (1...4).contains(lengthBytes), lengthBytes <= bytes.count - offset,
                  bytes[offset] != 0 else { throw FrameIdentityError.invalidCertificate }
            count = 0
            for byte in bytes[offset..<(offset + lengthBytes)] { count = count * 256 + Int(byte) }
            guard count >= 128 else { throw FrameIdentityError.invalidCertificate }
            offset += lengthBytes
        }
        guard count <= bytes.count - offset else { throw FrameIdentityError.invalidCertificate }
        let content = Data(bytes[offset..<(offset + count)])
        offset += count
        return (Data(bytes[start..<offset]), content)
    }
}
