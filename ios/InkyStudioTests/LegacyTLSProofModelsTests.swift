import Foundation
import XCTest
@testable import InkyStudio

final class LegacyTLSProofModelsTests: XCTestCase {
    func testBothPythonVectorsMatchExactBytesAndVerifyWithCryptoKit() throws {
        for vector in [LegacyTLSProofFixtures.first, LegacyTLSProofFixtures.second] {
            let message = try LegacyTLSProofVerifier.authenticationMessage(nonce: vector.nonce,
                frameID: vector.frameID, spki: vector.pin, exactURL: vector.url)
            XCTAssertEqual(message.map { String(format: "%02x", $0) }.joined(), vector.messageHex)
            let verified = try LegacyTLSProofVerifier.verify(response: vector.response,
                expectedNonce: vector.nonce, bootstrapPassword: vector.secret)
            XCTAssertEqual(verified.identity.id, vector.frameID)
            XCTAssertEqual(verified.identity.spkiSHA256, vector.pin)
            XCTAssertEqual(verified.endpoint.absoluteString, vector.url)
        }
    }

    func testNonceUUIDPinURLAndMACMutationsNeverProduceVerifiedIdentity() throws {
        let vector = LegacyTLSProofFixtures.first
        let variants = [
            vector.text.replacingOccurrences(of: vector.nonceHex, with: String(repeating: "12", count: 32)),
            vector.text.replacingOccurrences(of: vector.frameID.uuidString.lowercased(), with: "22222222-2222-4222-8222-222222222222"),
            vector.text.replacingOccurrences(of: vector.pinHex, with: String(repeating: "cd", count: 32)),
            vector.text.replacingOccurrences(of: vector.url, with: "https://INKY-FIXTURE.local:8443"),
            vector.text.replacingOccurrences(of: vector.proofHex, with: String(repeating: "0", count: 64)),
        ]
        for text in variants { assertUnavailable(Data(text.utf8)) }
        XCTAssertThrowsError(try LegacyTLSProofVerifier.verify(response: vector.response,
            expectedNonce: vector.nonce, bootstrapPassword: "Abcdef0123456780"))
        XCTAssertThrowsError(try LegacyTLSProofVerifier.verify(response: vector.response,
            expectedNonce: Data(repeating: 255, count: 32), bootstrapPassword: vector.secret))
    }

    func testVersionMustBeLiteralIntegerOne() {
        for value in ["true", "false", "1.0", "1e0", "\"1\"", "01", "2", "null"] {
            assertUnavailable(Data(LegacyTLSProofFixtures.first.text.replacingOccurrences(of: "\"v\":1", with: "\"v\":\(value)").utf8))
        }
    }

    func testDuplicateEscapedAndUnknownKeysAreRejectedAtBothObjectLevels() {
        let vector = LegacyTLSProofFixtures.first
        let variants = [
            vector.text.replacingOccurrences(of: "\"v\":1", with: "\"v\":1,\"v\":1"),
            vector.text.replacingOccurrences(of: "\"v\":1", with: "\"v\":1,\"\\u0076\":1"),
            vector.text.replacingOccurrences(of: "\"v\":1", with: "\"v\":1,\"password\":\"ignored\""),
            vector.text.replacingOccurrences(of: "\"frame_id\":", with: "\"frame_id\":\"\(vector.frameID.uuidString.lowercased())\",\"\\u0066rame_id\":"),
            vector.text.replacingOccurrences(of: "\"identity\":{", with: "\"identity\":{\"owner\":\"ignored\","),
            vector.text.replacingOccurrences(of: "\"url\":\"", with: "\"url\":{\"nested\":\""),
            vector.text + "{}", String(vector.text.dropLast()) + ",}",
        ]
        for text in variants { assertUnavailable(Data(text.utf8)) }
    }

    func testMissingFieldsNoncanonicalHexAndInvalidOriginsAreRejected() {
        let vector = LegacyTLSProofFixtures.first
        for replacement in ["https://user:secret@frame.local", "http://frame.local:8443", "https://frame.local/",
                            "https://frame.local/path", "https://frame.local?token=x", "https://frame.local#x",
                            "https://frame.local:0", "https://frame.local:65536", "https://frame.local:",
                            "https://fráme.local", "https://frame.local%2fpath"] {
            assertUnavailable(Data(vector.text.replacingOccurrences(of: vector.url, with: replacement).utf8))
        }
        assertUnavailable(Data(vector.text.replacingOccurrences(of: vector.pinHex, with: vector.pinHex.uppercased()).utf8))
        assertUnavailable(Data(vector.text.replacingOccurrences(of: vector.proofHex, with: vector.proofHex.uppercased()).utf8))
        assertUnavailable(Data(vector.text.replacingOccurrences(of: ",\"proof\":\"\(vector.proofHex)\"", with: "").utf8))
    }

    func testRawResponseLimitIncludesWhitespaceAndInvalidUTF8() throws {
        let vector = LegacyTLSProofFixtures.first
        let exact = vector.response + Data(repeating: 32, count: 2048 - vector.response.count)
        XCTAssertNoThrow(try LegacyTLSProofVerifier.verify(response: exact,
            expectedNonce: vector.nonce, bootstrapPassword: vector.secret))
        assertUnavailable(exact + Data([32]))
        assertUnavailable(Data([255]) + vector.response)
    }

    func testOnlyExistingSixteenASCIIAlphanumericSecretsAreEligible() {
        let vector = LegacyTLSProofFixtures.first
        for secret in ["", "short", String(repeating: "a", count: 15), String(repeating: "a", count: 17),
                       "Abcdef012345678!", "Abcdef012345678é", "Abcdef012345678 "] {
            XCTAssertFalse(LegacyTLSProofVerifier.validBootstrapPassword(secret))
            XCTAssertThrowsError(try LegacyTLSProofVerifier.verify(response: vector.response,
                expectedNonce: vector.nonce, bootstrapPassword: secret))
        }
    }

    private func assertUnavailable(_ data: Data, file: StaticString = #filePath, line: UInt = #line) {
        let vector = LegacyTLSProofFixtures.first
        XCTAssertThrowsError(try LegacyTLSProofVerifier.verify(response: data, expectedNonce: vector.nonce,
            bootstrapPassword: vector.secret), file: file, line: line) {
            XCTAssertEqual($0 as? LegacyTLSProofError, .unavailable, file: file, line: line)
        }
    }
}

/// Public, synthetic Python vectors from legacy-tls-proof-contract.json (c2e589…bd628).
enum LegacyTLSProofFixtures {
    struct Vector: Sendable {
        let secret: String
        let id: String
        let nonceHex: String
        let pinHex: String
        let url: String
        let proofHex: String
        let messageHex: String
        var frameID: UUID { UUID(uuidString: id)! }
        var nonce: Data { LegacyTLSProofVerifier.hex(nonceHex)! }
        var pin: Data { LegacyTLSProofVerifier.hex(pinHex)! }
        var text: String {
            "{\"v\":1,\"nonce\":\"\(nonceHex)\",\"identity\":{\"frame_id\":\"\(id)\",\"spki_sha256\":\"\(pinHex)\",\"url\":\"\(url)\"},\"proof\":\"\(proofHex)\"}"
        }
        var response: Data { Data(text.utf8) }
    }

    static let first = Vector(secret: "Abcdef0123456789", id: "11111111-1111-4111-8111-111111111111",
        nonceHex: String(repeating: "0", count: 64), pinHex: String(repeating: "ab", count: 32),
        url: "https://inky-fixture.local:8443", proofHex: "f2bd35f28b36c364a9b2447e89a2158195e4f4b506d3f993e26cd2804fc8456d",
        messageHex: "696e6b792d6c65676163792d746c732d70726f6f662d763100000000000000000000000000000000000000000000000000000000000000000011111111111141118111111111111111abababababababababababababababababababababababababababababababab001f68747470733a2f2f696e6b792d666978747572652e6c6f63616c3a38343433")
    static let second = Vector(secret: "Zyxwv9876543210A", id: "22222222-2222-4222-8222-222222222222",
        nonceHex: String(repeating: "f", count: 64), pinHex: String(repeating: "cd", count: 32),
        url: "https://[::1]:8443", proofHex: "25f160a10af95cd5c1fafe9c2787c83c6446f80d9a62cc4857bb4f9dde4b8cca",
        messageHex: "696e6b792d6c65676163792d746c732d70726f6f662d763100ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff22222222222242228222222222222222cdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcd001268747470733a2f2f5b3a3a315d3a38343433")
}
