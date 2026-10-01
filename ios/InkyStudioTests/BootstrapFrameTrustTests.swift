import Foundation
import Security
import XCTest
@testable import InkyStudio

@available(iOS 18.0, macOS 15.0, *)
final class BootstrapFrameTrustTests: XCTestCase {
    private let certificate = FrameTrustTestFixtures.certificate
    private let renewedCertificate = FrameTrustTestFixtures.renewedCertificate

    private var identity: FrameIdentity {
        get throws {
            try FrameIdentity(id: FrameTrustTestFixtures.id,
                              spkiSHA256: PinnedFrameTrust.spkiSHA256(certificateDER: certificate))
        }
    }

    func testBootstrapPrevalidationRetainsOnlyTheExpectedIdentityAndCertificate() throws {
        let expected = try identity
        let bootstrap = try BootstrapFrameTrust(identity: expected, certificateDER: certificate)
        XCTAssertEqual(bootstrap.identity, expected)
        XCTAssertEqual(bootstrap.certificateDER, certificate)
        XCTAssertEqual(bootstrap.expectedServerName, expected.expectedServerName)
        XCTAssertNoThrow(try PinnedFrameTrust(identity: expected, certificateDER: certificate,
                                              at: FrameTrustTestFixtures.date))
    }

    func testExpiredAndFutureCertificatesPassOnlyBootstrapAtThoseCurrentDates() throws {
        let expected = try identity
        // The same public fixtures are future leaves in 1970 and expired in
        // 2100. No system clock changes or fixtures with expiring tests are used.
        for currentDate in [Date(timeIntervalSince1970: 0), Date(timeIntervalSince1970: 4_102_444_800)] {
            for der in [certificate, renewedCertificate] {
                XCTAssertThrowsError(try PinnedFrameTrust(identity: expected, certificateDER: der,
                                                          at: currentDate)) {
                    XCTAssertEqual($0 as? FrameIdentityError, .certificateRejected)
                }
                XCTAssertNoThrow(try BootstrapFrameTrust(identity: expected, certificateDER: der))
            }
        }
    }

    func testWrongPinIsRejectedByBootstrap() throws {
        let wrongPin = try FrameIdentity(id: FrameTrustTestFixtures.id,
                                         spkiSHA256: Data(repeating: 0, count: 32))
        XCTAssertThrowsError(try BootstrapFrameTrust(identity: wrongPin, certificateDER: certificate)) {
            XCTAssertEqual($0 as? FrameIdentityError, .pinMismatch)
        }
    }

    func testWrongFrameNameIsRejectedEvenWithTheCorrectPin() throws {
        let wrongName = try FrameIdentity(id: UUID(), spkiSHA256: identity.spkiSHA256)
        XCTAssertThrowsError(try BootstrapFrameTrust(identity: wrongName, certificateDER: certificate)) {
            XCTAssertEqual($0 as? FrameIdentityError, .certificateRejected)
        }
    }

    func testPinnedBootstrapAnchorStillRequiresItsValidSelfSignature() throws {
        let expected = try identity
        var altered = certificate
        altered[altered.count - 1] ^= 1
        XCTAssertEqual(try PinnedFrameTrust.spkiSHA256(certificateDER: altered), expected.spkiSHA256)
        XCTAssertThrowsError(try BootstrapFrameTrust(identity: expected, certificateDER: altered)) {
            XCTAssertEqual($0 as? FrameIdentityError, .certificateRejected)
        }
    }

    func testMalformedOversizedAndMultipleCertificateDERAreRejected() throws {
        let expected = try identity
        let invalidCertificates = [Data(), Data(certificate.dropLast()), certificate + Data([0]),
                                   certificate + renewedCertificate, Data([0x30, 0x80, 0, 0]),
                                   Data(repeating: 0, count: 8193)]
        for der in invalidCertificates {
            XCTAssertThrowsError(try BootstrapFrameTrust(identity: expected, certificateDER: der))
        }
    }

    func testSameKeyRenewalRequiresSeparateNormalValidationAfterRepair() throws {
        let expected = try identity
        let original = try BootstrapFrameTrust(identity: expected, certificateDER: certificate)
        let renewed = try BootstrapFrameTrust(identity: expected, certificateDER: renewedCertificate)
        XCTAssertEqual(original.identity, renewed.identity)
        XCTAssertNotEqual(original.certificateDER, renewed.certificateDER)
        let repairedDate = Date(timeIntervalSince1970: 1_814_400_000) // 2027-07-01 UTC
        XCTAssertThrowsError(try PinnedFrameTrust(identity: expected, certificateDER: certificate,
                                                  at: repairedDate))
        XCTAssertNoThrow(try PinnedFrameTrust(identity: expected, certificateDER: renewedCertificate,
                                              at: repairedDate))
    }

    func testNewKeyCannotReplaceThePinnedIdentityInBootstrap() throws {
        let expected = try identity
        XCTAssertThrowsError(try BootstrapFrameTrust(identity: expected,
                                                    certificateDER: FrameTrustTestFixtures.newKeyCertificate)) {
            XCTAssertEqual($0 as? FrameIdentityError, .pinMismatch)
        }
    }

    private func syntheticIdentity() throws -> FrameIdentity {
        try FrameIdentity(id: FrameTrustTestFixtures.id,
                          spkiSHA256: PinnedFrameTrust.spkiSHA256(certificateDER: BootstrapNegativeCertificates.valid))
    }

    func testSyntheticProfileControlPassesNormalAndBootstrapValidation() throws {
        let expected = try syntheticIdentity()
        XCTAssertNoThrow(try PinnedFrameTrust(identity: expected, certificateDER: BootstrapNegativeCertificates.valid,
                                              at: FrameTrustTestFixtures.date))
        XCTAssertNoThrow(try BootstrapFrameTrust(identity: expected,
                                                 certificateDER: BootstrapNegativeCertificates.valid))
    }

    func testWrongKeyUsageFailsNormalAndBootstrapDespiteMatchingPin() throws {
        try assertUsageRejected(BootstrapNegativeCertificates.wrongKeyUsage)
    }

    func testWrongExtendedKeyUsageFailsNormalAndBootstrapDespiteMatchingPin() throws {
        try assertUsageRejected(BootstrapNegativeCertificates.wrongExtendedKeyUsage)
    }

    private func assertUsageRejected(_ der: Data, file: StaticString = #filePath, line: UInt = #line) throws {
        let expected = try syntheticIdentity()
        XCTAssertEqual(try PinnedFrameTrust.spkiSHA256(certificateDER: der), expected.spkiSHA256,
                       file: file, line: line)
        XCTAssertThrowsError(try PinnedFrameTrust(identity: expected, certificateDER: der,
                                                  at: FrameTrustTestFixtures.date), file: file, line: line) {
            XCTAssertEqual($0 as? FrameIdentityError, .certificateRejected, file: file, line: line)
        }
        XCTAssertThrowsError(try BootstrapFrameTrust(identity: expected, certificateDER: der),
                             file: file, line: line) {
            XCTAssertEqual($0 as? FrameIdentityError, .certificateRejected, file: file, line: line)
        }
    }

    func testEqualValidityHasNoInteriorDateAndFailsBootstrap() throws {
        try assertInvalidValidityRejected(BootstrapNegativeCertificates.equalValidity, equal: true)
    }

    func testInvertedValidityHasNoInteriorDateAndFailsBootstrap() throws {
        try assertInvalidValidityRejected(BootstrapNegativeCertificates.invertedValidity, equal: false)
    }

    private func assertInvalidValidityRejected(_ der: Data, equal: Bool,
                                               file: StaticString = #filePath, line: UInt = #line) throws {
        let expected = try syntheticIdentity()
        XCTAssertEqual(try PinnedFrameTrust.spkiSHA256(certificateDER: der), expected.spkiSHA256,
                       file: file, line: line)
        let certificate = try XCTUnwrap(SecCertificateCreateWithData(nil, der as CFData), file: file, line: line)
        let start = try XCTUnwrap(SecCertificateCopyNotValidBeforeDate(certificate), file: file, line: line) as Date
        let end = try XCTUnwrap(SecCertificateCopyNotValidAfterDate(certificate), file: file, line: line) as Date
        if equal {
            XCTAssertEqual(start, end, file: file, line: line)
        } else {
            XCTAssertGreaterThan(start, end, file: file, line: line)
        }
        XCTAssertThrowsError(try BootstrapFrameTrust(identity: expected, certificateDER: der),
                             file: file, line: line) {
            XCTAssertEqual($0 as? FrameIdentityError, .certificateRejected, file: file, line: line)
        }
    }
}

// Public synthetic DER only, signed with one ephemeral P-256 key that was never
// serialized. All use the canonical frame name, ECDSA-SHA256 and CA=true, matching
// the normal fixtures. wrongKeyUsage has only keyCertSign/cRLSign; wrongExtendedKeyUsage
// has only clientAuth. The control is valid 2026-01-01...2027-02-01; equalValidity
// has both bounds at 2026-01-01. invertedValidity is freshly signed with bounds
// 2028-02-01...2027-02-01. Generation independently verified every self-signature.
private enum BootstrapNegativeCertificates {
    static let valid = Data(base64Encoded: "MIICMzCCAdigAwIBAgICG70wCgYIKoZIzj0EAwIwQjFAMD4GA1UEAww3ZnJhbWUtMTExMTExMTEtMjIyMi0zMzMzLTQ0NDQtNTU1NTU1NTU1NTU1Lmlua3kuaW52YWxpZDAeFw0yNjAxMDEwMDAwMDBaFw0yNzAyMDEwMDAwMDBaMEIxQDA+BgNVBAMMN2ZyYW1lLTExMTExMTExLTIyMjItMzMzMy00NDQ0LTU1NTU1NTU1NTU1NS5pbmt5LmludmFsaWQwWTATBgcqhkjOPQIBBggqhkjOPQMBBwNCAAQe6dMk0/2P+Tys8n7zH0U7aa7v6Ezx53lW4YRkiVrpWWrAwxSpVrHBRUfDZ2hLncBF2r+fb4MOngDQj9hv09Soo4G9MIG6MA8GA1UdEwEB/wQFMAMBAf8wDgYDVR0PAQH/BAQDAgGGMBMGA1UdJQQMMAoGCCsGAQUFBwMBMEIGA1UdEQQ7MDmCN2ZyYW1lLTExMTExMTExLTIyMjItMzMzMy00NDQ0LTU1NTU1NTU1NTU1NS5pbmt5LmludmFsaWQwHQYDVR0OBBYEFAn1Te9UEmEPUZ/IV6jFf2KtmUCpMB8GA1UdIwQYMBaAFAn1Te9UEmEPUZ/IV6jFf2KtmUCpMAoGCCqGSM49BAMCA0kAMEYCIQDiDxm/UrNMblGHzj9EiX9QAx+F3/Lwsn2C4olaQmZ6xAIhAIMd5GFWZ0hgVIqZf3DGsaHDm3uojtLrocZ/PR5Ry5N1")!
    static let wrongKeyUsage = Data(base64Encoded: "MIICMjCCAdigAwIBAgICG74wCgYIKoZIzj0EAwIwQjFAMD4GA1UEAww3ZnJhbWUtMTExMTExMTEtMjIyMi0zMzMzLTQ0NDQtNTU1NTU1NTU1NTU1Lmlua3kuaW52YWxpZDAeFw0yNjAxMDEwMDAwMDBaFw0yNzAyMDEwMDAwMDBaMEIxQDA+BgNVBAMMN2ZyYW1lLTExMTExMTExLTIyMjItMzMzMy00NDQ0LTU1NTU1NTU1NTU1NS5pbmt5LmludmFsaWQwWTATBgcqhkjOPQIBBggqhkjOPQMBBwNCAAQe6dMk0/2P+Tys8n7zH0U7aa7v6Ezx53lW4YRkiVrpWWrAwxSpVrHBRUfDZ2hLncBF2r+fb4MOngDQj9hv09Soo4G9MIG6MA8GA1UdEwEB/wQFMAMBAf8wDgYDVR0PAQH/BAQDAgEGMBMGA1UdJQQMMAoGCCsGAQUFBwMBMEIGA1UdEQQ7MDmCN2ZyYW1lLTExMTExMTExLTIyMjItMzMzMy00NDQ0LTU1NTU1NTU1NTU1NS5pbmt5LmludmFsaWQwHQYDVR0OBBYEFAn1Te9UEmEPUZ/IV6jFf2KtmUCpMB8GA1UdIwQYMBaAFAn1Te9UEmEPUZ/IV6jFf2KtmUCpMAoGCCqGSM49BAMCA0gAMEUCIED3eg4IJslrjicWcKfjTwrbuDWHvnevTqBSHpJkOiApAiEAuDxwcQlYOQPo1rkkpEu9+JnzoC85REfmpePcfEZT9Oo=")!
    static let wrongExtendedKeyUsage = Data(base64Encoded: "MIICMTCCAdigAwIBAgICG78wCgYIKoZIzj0EAwIwQjFAMD4GA1UEAww3ZnJhbWUtMTExMTExMTEtMjIyMi0zMzMzLTQ0NDQtNTU1NTU1NTU1NTU1Lmlua3kuaW52YWxpZDAeFw0yNjAxMDEwMDAwMDBaFw0yNzAyMDEwMDAwMDBaMEIxQDA+BgNVBAMMN2ZyYW1lLTExMTExMTExLTIyMjItMzMzMy00NDQ0LTU1NTU1NTU1NTU1NS5pbmt5LmludmFsaWQwWTATBgcqhkjOPQIBBggqhkjOPQMBBwNCAAQe6dMk0/2P+Tys8n7zH0U7aa7v6Ezx53lW4YRkiVrpWWrAwxSpVrHBRUfDZ2hLncBF2r+fb4MOngDQj9hv09Soo4G9MIG6MA8GA1UdEwEB/wQFMAMBAf8wDgYDVR0PAQH/BAQDAgGGMBMGA1UdJQQMMAoGCCsGAQUFBwMCMEIGA1UdEQQ7MDmCN2ZyYW1lLTExMTExMTExLTIyMjItMzMzMy00NDQ0LTU1NTU1NTU1NTU1NS5pbmt5LmludmFsaWQwHQYDVR0OBBYEFAn1Te9UEmEPUZ/IV6jFf2KtmUCpMB8GA1UdIwQYMBaAFAn1Te9UEmEPUZ/IV6jFf2KtmUCpMAoGCCqGSM49BAMCA0cAMEQCIEyev0ZIDNKVWH/mmDBZQsU/5UTuHP4lvqt6JQ1cHXmTAiBIuazY1GTdNOGaan/FLMzwCqxPgg5k11eOxQTM4vz4oQ==")!
    static let equalValidity = Data(base64Encoded: "MIICMjCCAdigAwIBAgICG8AwCgYIKoZIzj0EAwIwQjFAMD4GA1UEAww3ZnJhbWUtMTExMTExMTEtMjIyMi0zMzMzLTQ0NDQtNTU1NTU1NTU1NTU1Lmlua3kuaW52YWxpZDAeFw0yNjAxMDEwMDAwMDBaFw0yNjAxMDEwMDAwMDBaMEIxQDA+BgNVBAMMN2ZyYW1lLTExMTExMTExLTIyMjItMzMzMy00NDQ0LTU1NTU1NTU1NTU1NS5pbmt5LmludmFsaWQwWTATBgcqhkjOPQIBBggqhkjOPQMBBwNCAAQe6dMk0/2P+Tys8n7zH0U7aa7v6Ezx53lW4YRkiVrpWWrAwxSpVrHBRUfDZ2hLncBF2r+fb4MOngDQj9hv09Soo4G9MIG6MA8GA1UdEwEB/wQFMAMBAf8wDgYDVR0PAQH/BAQDAgGGMBMGA1UdJQQMMAoGCCsGAQUFBwMBMEIGA1UdEQQ7MDmCN2ZyYW1lLTExMTExMTExLTIyMjItMzMzMy00NDQ0LTU1NTU1NTU1NTU1NS5pbmt5LmludmFsaWQwHQYDVR0OBBYEFAn1Te9UEmEPUZ/IV6jFf2KtmUCpMB8GA1UdIwQYMBaAFAn1Te9UEmEPUZ/IV6jFf2KtmUCpMAoGCCqGSM49BAMCA0gAMEUCIGfQcFkg6Ao7pS6Yu0aP4uxhu/ZTettBlDYBKpjcJ/yxAiEAul0HB5voYqsNvO3zBkK+afrt3gBo74n1FVm+ZD/7w/E=")!
    static let invertedValidity = Data(base64Encoded: "MIICMzCCAdigAwIBAgICG8EwCgYIKoZIzj0EAwIwQjFAMD4GA1UEAww3ZnJhbWUtMTExMTExMTEtMjIyMi0zMzMzLTQ0NDQtNTU1NTU1NTU1NTU1Lmlua3kuaW52YWxpZDAeFw0yODAyMDEwMDAwMDBaFw0yNzAyMDEwMDAwMDBaMEIxQDA+BgNVBAMMN2ZyYW1lLTExMTExMTExLTIyMjItMzMzMy00NDQ0LTU1NTU1NTU1NTU1NS5pbmt5LmludmFsaWQwWTATBgcqhkjOPQIBBggqhkjOPQMBBwNCAAQe6dMk0/2P+Tys8n7zH0U7aa7v6Ezx53lW4YRkiVrpWWrAwxSpVrHBRUfDZ2hLncBF2r+fb4MOngDQj9hv09Soo4G9MIG6MA8GA1UdEwEB/wQFMAMBAf8wDgYDVR0PAQH/BAQDAgGGMBMGA1UdJQQMMAoGCCsGAQUFBwMBMEIGA1UdEQQ7MDmCN2ZyYW1lLTExMTExMTExLTIyMjItMzMzMy00NDQ0LTU1NTU1NTU1NTU1NS5pbmt5LmludmFsaWQwHQYDVR0OBBYEFAn1Te9UEmEPUZ/IV6jFf2KtmUCpMB8GA1UdIwQYMBaAFAn1Te9UEmEPUZ/IV6jFf2KtmUCpMAoGCCqGSM49BAMCA0kAMEYCIQDOMR2/B0QsSgsWhWQBpmDzpd2OuCPwAEvrULC4iqlQUQIhAO+9Lt9FXl4/UWbCAMINa6N55TgfCTeA3lebMSRMkbRA")!
}
