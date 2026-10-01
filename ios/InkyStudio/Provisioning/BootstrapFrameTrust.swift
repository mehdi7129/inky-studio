import Foundation
import Security

/// Certificate prevalidation for the isolated bootstrap profile only.
///
/// The identity must already come from a physical QR or the ownership Keychain,
/// never from the certificate or a BLE advertisement. Validation deliberately
/// uses a date inside this certificate's validity interval: this value therefore
/// proves neither current certificate validity nor the correctness of any clock.
/// The existing normal trust implementation remains unchanged.
///
/// This is not proof of a completed TLS handshake, negotiated bootstrap ALPN,
/// possession of the private key, or authorization of an owner. A future separate
/// bootstrap channel must establish those before transmitting any secret. This
/// type exposes no HTTPS credential, normal trust policy, or conversion to one.
@available(iOS 18.0, macOS 15.0, *)
struct BootstrapFrameTrust: Equatable, Sendable {
    let identity: FrameIdentity
    let certificateDER: Data

    var expectedServerName: String { identity.expectedServerName }

    init(identity: FrameIdentity, certificateDER: Data) throws {
        // The existing bounded DER/SPKI parser also requires canonical P-256
        // encoding and a valid curve point before the pin comparison.
        guard try PinnedFrameTrust.spkiSHA256(certificateDER: certificateDER) == identity.spkiSHA256 else {
            throw FrameIdentityError.pinMismatch
        }
        guard let certificate = SecCertificateCreateWithData(nil, certificateDER as CFData),
              let notBefore = SecCertificateCopyNotValidBeforeDate(certificate),
              let notAfter = SecCertificateCopyNotValidAfterDate(certificate) else {
            throw FrameIdentityError.invalidCertificate
        }
        let start = (notBefore as Date).timeIntervalSinceReferenceDate
        let end = (notAfter as Date).timeIntervalSinceReferenceDate
        let interior = start + (end - start) / 2
        guard start.isFinite, end.isFinite, interior.isFinite,
              start < interior, interior < end else {
            throw FrameIdentityError.certificateRejected
        }

        // Reuse the explicit self-signature check and Security's SSL name,
        // structure and usage evaluation. The temporary normal-trust value is
        // discarded: only this distinct bootstrap prevalidation can escape.
        _ = try PinnedFrameTrust(identity: identity, certificateDER: certificateDER,
                                 at: Date(timeIntervalSinceReferenceDate: interior))
        self.identity = identity
        self.certificateDER = certificateDER
    }
}
