import XCTest
@testable import InkyStudio

final class FrameIdentityTests: XCTestCase {
    private let id = "11111111-2222-3333-4444-555555555555"
    private var qr: String {
        "{\"v\":1,\"id\":\"\(id)\",\"k\":\"\(String(repeating: "a", count: 64))\",\"t\":\"\(String(repeating: "b", count: 64))\"}"
    }

    func testParsesPhysicalQRAndDerivesStableDNSIdentity() throws {
        let result = try FrameAdoptionCode.parse(qr)
        XCTAssertEqual(result.identity.id, UUID(uuidString: id))
        XCTAssertEqual(result.identity.expectedServerName, "frame-\(id).inky.invalid")
        XCTAssertEqual(result.identity.spkiSHA256, Data(repeating: 0xaa, count: 32))
        XCTAssertEqual(result.adoptionToken, Data(repeating: 0xbb, count: 32))
    }

    func testRejectsDuplicateAndEscapedDuplicateFields() {
        for duplicate in ["\"v\":1", "\"\\u0076\":1", "\"id\":\"\(id)\""] {
            XCTAssertThrowsError(try FrameAdoptionCode.parse(qr.replacingOccurrences(of: "{", with: "{\(duplicate),")))
        }
    }

    func testRejectsUnknownFieldsWrongTypesAndNoncanonicalHex() {
        let invalid = [
            qr.replacingOccurrences(of: "{", with: "{\"url\":\"https://example.com\","),
            qr.replacingOccurrences(of: "\"v\":1", with: "\"v\":\"1\""),
            qr.replacingOccurrences(of: "\"v\":1", with: "\"v\":true"),
            qr.replacingOccurrences(of: "\"v\":1", with: "\"v\":1.0"),
            qr.replacingOccurrences(of: "\"v\":1", with: "\"v\":01"),
            qr.replacingOccurrences(of: String(repeating: "a", count: 64), with: String(repeating: "A", count: 64)),
            qr.replacingOccurrences(of: String(repeating: "b", count: 64), with: String(repeating: "b", count: 62)),
            qr.replacingOccurrences(of: id, with: "invalid"),
            qr + "{}", "https://example.com/" + qr,
            String(repeating: " ", count: 513) + qr,
            qr.replacingOccurrences(of: "}", with: ",}")
        ]
        for text in invalid { XCTAssertThrowsError(try FrameAdoptionCode.parse(text)) }
    }

    func testVersionIsExplicitAndMissingFieldsAreRejected() {
        XCTAssertThrowsError(try FrameAdoptionCode.parse(qr.replacingOccurrences(of: "\"v\":1", with: "\"v\":2"))) {
            XCTAssertEqual($0 as? FrameIdentityError, .unsupportedVersion)
        }
        XCTAssertThrowsError(try FrameAdoptionCode.parse(qr.replacingOccurrences(of: "\"v\":1,", with: "")))
    }

    func testDecodedPersistedIdentityCannotBypassPinLength() {
        let data = Data("{\"id\":\"\(id)\",\"spkiSHA256\":\"AA==\"}".utf8)
        XCTAssertThrowsError(try JSONDecoder().decode(FrameIdentity.self, from: data))
    }
}
