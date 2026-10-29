import XCTest
@testable import InkyStudio

final class FrameLANLoginCodeTests: XCTestCase {
    private func qr(url: String = "http://192.168.1.120:8000", password: String = "DemoPass12345678") -> String {
        let data = try! JSONSerialization.data(withJSONObject: ["v": 1, "p": "lan-login", "url": url, "password": password], options: [.sortedKeys, .withoutEscapingSlashes])
        return String(decoding: data, as: UTF8.self)
    }

    func testParsesOnlyPrivateIPv4ListenerOrigins() throws {
        for host in ["10.0.0.2", "172.16.0.2", "172.31.255.254", "192.168.1.120"] {
            let code = try FrameLANLoginCode.parse(qr(url: "http://\(host):8000"))
            XCTAssertEqual(code.endpoint.absoluteString, "http://\(host):8000")
            XCTAssertEqual(code.password, "DemoPass12345678")
        }
    }

    func testRejectsPublicAmbiguousAndNonListenerURLs() {
        for url in [
            "http://8.8.8.8:8000", "http://127.0.0.1:8000", "http://0.0.0.0:8000",
            "http://169.254.1.2:8000", "http://224.0.0.1:8000", "http://100.64.0.2:8000",
            "http://172.15.1.2:8000", "http://172.32.1.2:8000", "http://192.169.1.2:8000",
            "http://frame.local:8000", "http://[fd00::2]:8000", "http://[::ffff:192.168.1.2]:8000",
            "192.168.1.2:8000", "https://192.168.1.2:8443", "http://192.168.1.2",
            "http://192.168.1.2:8443", "http://192.168.1.2:08000", "HTTP://192.168.1.2:8000",
            "http://192.168.1.2:8000/", "http://192.168.1.2:8000/api/auth/login",
            "http://192.168.1.2:8000?", "http://192.168.1.2:8000#",
            "http://user@192.168.1.2:8000", "http://user:pass@192.168.1.2:8000",
            "http://192.168.001.2:8000", "http://3232235778:8000", "http://0xc0a80102:8000",
            "http://192.168.1.%32:8000", "http://192.168.1.2.:8000",
            " http://192.168.1.2:8000", "http://192.168.1.2:8000\n"
        ] { XCTAssertThrowsError(try FrameLANLoginCode.parse(qr(url: url)), "Unexpected URL acceptance") }
    }

    func testRejectsAmbiguousJSONAndOtherQRProtocols() {
        let valid = qr()
        for text in [
            valid.replacingOccurrences(of: "{", with: "{\"v\":1,"),
            valid.replacingOccurrences(of: "{", with: "{\"\\u0076\":1,"),
            valid.replacingOccurrences(of: "{", with: "{\"\\u0070assword\":\"other\","),
            valid.replacingOccurrences(of: "{", with: "{\"extra\":\"field\","),
            valid.replacingOccurrences(of: "\"v\":1", with: "\"v\":\"1\""),
            valid.replacingOccurrences(of: "\"v\":1", with: "\"v\":1.0"),
            valid.replacingOccurrences(of: "\"v\":1", with: "\"v\":01"),
            valid.replacingOccurrences(of: "\"v\":1", with: "\"v\":true"),
            valid.replacingOccurrences(of: "\"v\":1", with: "\"v\":2"),
            valid.replacingOccurrences(of: "\"v\":1", with: "\"v\":null"),
            valid.replacingOccurrences(of: "\"p\":\"lan-login\",", with: ""),
            valid.replacingOccurrences(of: "lan-login", with: "factory-claim"),
            valid.replacingOccurrences(of: "}", with: ",}"), valid + "{}",
            "{\"v\":1,\"id\":\"11111111-2222-3333-4444-555555555555\",\"k\":\"pin\",\"t\":\"token\"}",
            "{\"v\":2,\"p\":\"bootstrap\",\"id\":\"frame\"}"
        ] { XCTAssertThrowsError(try FrameLANLoginCode.parse(text)) }
    }

    func testBoundsSecretAndWholeEnvelopeWithoutEchoingInputInErrors() throws {
        _ = try FrameLANLoginCode.parse(qr(password: "a"))
        _ = try FrameLANLoginCode.parse(qr(password: String(repeating: "z", count: 128)))
        for password in ["", "has space", "line\nbreak", "tab\tvalue", "\0", "é", String(repeating: "x", count: 129)] {
            XCTAssertThrowsError(try FrameLANLoginCode.parse(qr(password: password))) { error in
                XCTAssertEqual(error as? LANLoginCodeError, .invalidCode)
                XCTAssertFalse(error.localizedDescription.contains("DemoPass"))
            }
        }
        let valid = qr()
        let padding = 512 - valid.utf8.count
        _ = try FrameLANLoginCode.parse(String(repeating: " ", count: padding) + valid)
        XCTAssertThrowsError(try FrameLANLoginCode.parse(String(repeating: " ", count: padding + 1) + valid))
    }

    func testLANCodeDoesNotBecomeAnAdoptionCode() {
        XCTAssertThrowsError(try FrameAdoptionCode.parse(qr()))
    }
}
