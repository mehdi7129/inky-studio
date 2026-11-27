import XCTest
@testable import InkyStudio

final class FrameInvitationCodeTests: XCTestCase {
    private let frameID = "11111111-2222-3333-aaaa-555555555555"
    private let invitationID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    private func payload(url: String = "https://inky.local:8443") -> String {
        "{\"v\":1,\"p\":\"invite\",\"id\":\"\(frameID)\",\"k\":\"\(String(repeating: "a", count: 64))\",\"url\":\"\(url)\",\"i\":\"\(invitationID)\",\"t\":\"\(String(repeating: "b", count: 64))\"}"
    }

    func testRoundTripPreservesInvitationIdentityAndExactOrigin() throws {
        for address in ["https://inky.local:8443", "https://192.168.1.166:8443", "https://[fd00::2]:8443", "https://frame.local:443"] {
            let code = try FrameInvitationCode.parse(payload(url: address))
            XCTAssertEqual(code.identity.id, UUID(uuidString: frameID))
            XCTAssertEqual(code.identity.spkiSHA256, Data(repeating: 0xaa, count: 32))
            XCTAssertEqual(code.endpoint.absoluteString, address)
            XCTAssertEqual(code.invitationID, UUID(uuidString: invitationID))
            XCTAssertEqual(code.invitationToken, String(repeating: "b", count: 64))
            XCTAssertEqual(try FrameInvitationCode.parse(code.encodedPayload()), code)
        }
    }

    func testRejectsHTTPAndAmbiguousOrNonOriginAddresses() {
        for address in ["http://inky.local:8000", "HTTPS://inky.local:8443", "https://inky.local:8443/", "https://inky.local/api", "https://inky.local?", "https://inky.local#", "https://user@inky.local", "https://user:pass@inky.local", "https://inky.local:", "https://inky.local:0", "https://inky.local:65536", "https://inky.local:abc", "https://inky.local%2e", "https://inky_.local", "https://inky.local\\\\@attacker.local", "https://[::1", "https://", "https://inky..local", " https://inky.local"] {
            XCTAssertThrowsError(try FrameInvitationCode.parse(payload(url: address)), "Unexpected origin acceptance")
        }
    }

    func testRejectsDuplicateKeysEscapedDuplicatesAndUnknownFields() {
        for extra in ["\"v\":1", "\"\\u0076\":1", "\"\\u0074\":\"other\"", "\"url\":\"https://other.local\"", "\"password\":\"bootstrap\"", "\"role\":\"owner\""] {
            XCTAssertThrowsError(try FrameInvitationCode.parse(payload().replacingOccurrences(of: "{", with: "{\(extra),")))
        }
    }

    func testRejectsNonCanonicalTypesIDsAndHex() {
        let text = payload()
        for invalid in [
            text.replacingOccurrences(of: "\"v\":1", with: "\"v\":2"),
            text.replacingOccurrences(of: "\"v\":1", with: "\"v\":true"),
            text.replacingOccurrences(of: "\"v\":1", with: "\"v\":1.0"),
            text.replacingOccurrences(of: "\"v\":1", with: "\"v\":01"),
            text.replacingOccurrences(of: "\"v\":1", with: "\"v\":\"1\""),
            text.replacingOccurrences(of: frameID, with: frameID.uppercased()),
            text.replacingOccurrences(of: invitationID, with: invitationID.uppercased()),
            text.replacingOccurrences(of: String(repeating: "a", count: 64), with: String(repeating: "A", count: 64)),
            text.replacingOccurrences(of: String(repeating: "b", count: 64), with: String(repeating: "b", count: 62)),
            text.replacingOccurrences(of: "\"p\":\"invite\",", with: ""),
            text.replacingOccurrences(of: "invite", with: "lan-login"),
            text + "{}", text.replacingOccurrences(of: "}", with: ",}")
        ] { XCTAssertThrowsError(try FrameInvitationCode.parse(invalid)) }
    }

    func testCannotBeMisreadAsLegacyLoginOrBLEAdoption() {
        XCTAssertThrowsError(try FrameLANLoginCode.parse(payload()))
        XCTAssertThrowsError(try FrameAdoptionCode.parse(payload()))
    }

    func testBoundsEnvelopeAndErrorsDoNotEchoItsSecrets() throws {
        let text = payload()
        _ = try FrameInvitationCode.parse(String(repeating: " ", count: 1024 - text.utf8.count) + text)
        XCTAssertThrowsError(try FrameInvitationCode.parse(String(repeating: " ", count: 1025 - text.utf8.count) + text)) { error in
            XCTAssertEqual(error as? InvitationCodeError, .invalidCode)
            XCTAssertFalse(error.localizedDescription.contains(String(repeating: "b", count: 64)))
        }
    }
}
