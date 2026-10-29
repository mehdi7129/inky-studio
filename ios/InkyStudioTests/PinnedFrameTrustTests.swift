import Foundation
import Security
import XCTest
@testable import InkyStudio

final class PinnedFrameTrustTests: XCTestCase {
    // Public synthetic certificate only, generated with OpenSSL; its private key
    // is not part of the repository. Use a fixed date so these tests do not expire.
    private let certificate = FrameTrustTestFixtures.certificate
    private let renewedCertificate = FrameTrustTestFixtures.renewedCertificate
    private let newKeyCertificate = FrameTrustTestFixtures.newKeyCertificate
    private let date = Date(timeIntervalSince1970: 1_791_158_400) // 2026-10-05 UTC
    private var id: UUID { UUID(uuidString: "11111111-2222-3333-4444-555555555555")! }
    private var identity: FrameIdentity {
        get throws { try FrameIdentity(id: id, spkiSHA256: PinnedFrameTrust.spkiSHA256(certificateDER: certificate)) }
    }

    func testSPKIHashMatchesIndependentOpenSSLDER() throws {
        let actual = try PinnedFrameTrust.spkiSHA256(certificateDER: certificate)
        XCTAssertEqual(actual.map { String(format: "%02x", $0) }.joined(),
                       "f2f84e202379f0b31a408b6959692ba0509af4d1ad6f7e15feaa4c2b0aed1315")
        XCTAssertNoThrow(try PinnedFrameTrust(identity: identity, certificateDER: certificate, at: date))
    }

    func testWrongPinAndWrongDNSIdentityFailBeforeTrustIsUsable() throws {
        let wrongPin = try FrameIdentity(id: id, spkiSHA256: Data(repeating: 0, count: 32))
        XCTAssertThrowsError(try PinnedFrameTrust(identity: wrongPin, certificateDER: certificate, at: date)) {
            XCTAssertEqual($0 as? FrameIdentityError, .pinMismatch)
        }
        let wrongName = try FrameIdentity(id: UUID(), spkiSHA256: identity.spkiSHA256)
        XCTAssertThrowsError(try PinnedFrameTrust(identity: wrongName, certificateDER: certificate, at: date)) {
            XCTAssertEqual($0 as? FrameIdentityError, .certificateRejected)
        }
    }

    func testCertificateValidityIsNeverBypassedForPinnedAnchor() throws {
        for date in [Date(timeIntervalSince1970: 0), Date(timeIntervalSince1970: 4_102_444_800)] {
            XCTAssertThrowsError(try PinnedFrameTrust(identity: identity, certificateDER: certificate, at: date)) {
                XCTAssertEqual($0 as? FrameIdentityError, .certificateRejected)
            }
        }
    }

    func testPinnedAnchorStillRequiresValidSelfSignature() throws {
        var altered = certificate
        altered[altered.count - 1] ^= 1
        XCTAssertEqual(try PinnedFrameTrust.spkiSHA256(certificateDER: altered), try identity.spkiSHA256)
        XCTAssertThrowsError(try PinnedFrameTrust(identity: identity, certificateDER: altered, at: date)) {
            XCTAssertEqual($0 as? FrameIdentityError, .certificateRejected)
        }
    }

    func testMalformedAndTrailingDERAreRejected() {
        for invalid in [Data(), certificate.dropLast(), certificate + Data([0]), Data([0x30, 0x80, 0, 0])] {
            XCTAssertThrowsError(try PinnedFrameTrust.spkiSHA256(certificateDER: invalid))
        }
    }

    func testHTTPSCanLocateFrameByIPWithoutChangingDNSIdentity() throws {
        let trust = try PinnedFrameTrust(identity: identity, certificateDER: certificate, at: date)
        try trust.validateHTTPS(URL(string: "https://192.0.2.1:8443")!)
        XCTAssertEqual(trust.expectedServerName, "frame-\(id.uuidString.lowercased()).inky.invalid")
        for address in ["http://192.0.2.1", "https://user:secret@192.0.2.1", "https://192.0.2.1/?token=x", "https://192.0.2.1/api"] {
            XCTAssertThrowsError(try trust.validateHTTPS(URL(string: address)!))
        }
    }

    func testHTTPSChallengeTrustUsesAdoptedIdentityInsteadOfIPHostname() throws {
        let pinned = try PinnedFrameTrust(identity: identity, certificateDER: certificate, at: date)
        let leaf = SecCertificateCreateWithData(nil, certificate as CFData)!
        var serverTrust: SecTrust?
        XCTAssertEqual(SecTrustCreateWithCertificates(leaf, SecPolicyCreateSSL(true, "192.0.2.1" as CFString), &serverTrust), errSecSuccess)
        XCTAssertNoThrow(try pinned.validate(serverTrust: XCTUnwrap(serverTrust), at: date))
    }

    func testSameKeyRenewalWorksAfterCachedCertificateExpires() throws {
        let original = try PinnedFrameTrust(identity: identity, certificateDER: certificate, at: date)
        let renewedDate = Date(timeIntervalSince1970: 1_814_400_000) // 2027-07-01 UTC
        XCTAssertThrowsError(try PinnedFrameTrust(identity: identity, certificateDER: certificate, at: renewedDate))
        let leaf = SecCertificateCreateWithData(nil, renewedCertificate as CFData)!
        var trust: SecTrust?
        XCTAssertEqual(SecTrustCreateWithCertificates(leaf, SecPolicyCreateSSL(true, "192.0.2.1" as CFString), &trust), errSecSuccess)
        XCTAssertNoThrow(try original.policy.validate(serverTrust: XCTUnwrap(trust), at: renewedDate))
        XCTAssertNotEqual(certificate, renewedCertificate)
    }

    func testNewKeyCertificateIsNeverAcceptedAsRenewal() throws {
        let policy = FrameTrustPolicy(identity: try identity)
        let leaf = SecCertificateCreateWithData(nil, newKeyCertificate as CFData)!
        var trust: SecTrust?
        XCTAssertEqual(SecTrustCreateWithCertificates(leaf, SecPolicyCreateSSL(true, "192.0.2.1" as CFString), &trust), errSecSuccess)
        XCTAssertThrowsError(try policy.validate(serverTrust: XCTUnwrap(trust), at: date)) {
            XCTAssertEqual($0 as? FrameIdentityError, .pinMismatch)
        }
    }
}
