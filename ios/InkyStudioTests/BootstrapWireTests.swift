import XCTest
@testable import InkyStudio

final class BootstrapWireTests: XCTestCase {
    func testSharedRawCorpusPreservesBytesGrammarAndResponseCorrelation() throws {
        #if SWIFT_PACKAGE
        let resource = Bundle.module.url(forResource: "vectors", withExtension: "json")
        #else
        let resource = Bundle(for: Self.self).url(forResource: "vectors", withExtension: "json")
        #endif
        let url = try XCTUnwrap(resource)
        let corpus = try JSONDecoder().decode(Corpus.self, from: Data(contentsOf: url))
        XCTAssertEqual(corpus.rawCases.count, 78)
        for item in corpus.rawCases {
            let bytes = try XCTUnwrap(Data.bootstrapHexBytes(item.inputHex), item.name)
            do {
                var profile: String?
                var correlated: Bool?
                switch item.stage {
                case "qr":
                    switch try FrameQRCode.parse(bytes) {
                    case .normal: profile = "normal-v1"
                    case .bootstrap: profile = "bootstrap"
                    }
                case "metadata": _ = try BootstrapPublicIdentity.parse(bytes); profile = "bootstrap"
                case "claim": _ = try BootstrapRequest.parse(bytes, operation: .claim)
                case "status": _ = try BootstrapRequest.parse(bytes, operation: .status)
                case "success", "error":
                    let context = try XCTUnwrap(item.context, item.name)
                    let decoded = try BootstrapResponse.parse(bytes, context: BootstrapResponseContext(
                        rpcID: context.rpcID.flatMap(UUID.init(uuidString:)), frameID: try XCTUnwrap(UUID(uuidString: context.frameID)),
                        ownerID: try XCTUnwrap(UUID(uuidString: context.ownerID)),
                        claimRequestID: try XCTUnwrap(UUID(uuidString: context.claimID))))
                    if case .failure(_, let value) = decoded { correlated = value }
                default: XCTFail("Unknown shared stage: \(item.stage)"); continue
                }
                XCTAssertTrue(item.expected.accept, item.name)
                if let expected = item.expected.profile { XCTAssertEqual(profile, expected, item.name) }
                if let expected = item.expected.correlated { XCTAssertEqual(correlated, expected, item.name) }
            } catch let error as BootstrapWireError {
                XCTAssertFalse(item.expected.accept, item.name)
                XCTAssertEqual(error.rawValue, item.expected.reason, item.name)
            } catch { XCTFail("\(item.name): unexpected decoder failure \(error)") }
            if let framed = item.framedHex {
                XCTAssertEqual(try BluetoothMessageBuffer.encode(bytes), Data.bootstrapHexBytes(framed), item.name)
            }
        }
    }
    func testNormalQRIsNotAcceptedByBootstrapAndViceVersa() throws {
        let pin = String(repeating: "1", count: 64), token = String(repeating: "a", count: 64)
        let id = "00000000-0000-4000-8000-000000000001"
        let normal = "{\"v\":1,\"id\":\"\(id)\",\"k\":\"\(pin)\",\"t\":\"\(token)\"}"
        let bootstrap = "{\"v\":2,\"p\":\"bootstrap\",\"id\":\"\(id)\",\"k\":\"\(pin)\",\"t\":\"\(token)\"}"
        XCTAssertThrowsError(try BootstrapAdoptionCode.parse(Data(normal.utf8)))
        XCTAssertThrowsError(try FrameAdoptionCode.parse(bootstrap))
    }
    func testClosedResponseRejectsDuplicateNestedKeysOwnerClaimAndFalseCompletion() throws {
        let rpc = UUID(), frame = UUID(), owner = UUID(), claim = UUID()
        let context = BootstrapResponseContext(rpcID: rpc, frameID: frame, ownerID: owner, claimRequestID: claim)
        let fields = "\"frame_id\":\"\(frame.uuidString.lowercased())\",\"owner_id\":\"\(owner.uuidString.lowercased())\",\"claim_request_id\":\"\(claim.uuidString.lowercased())\",\"factory_state\":\"adopted\",\"next_step\":\"system_setup\""
        let response = "{\"v\":1,\"id\":\"\(rpc.uuidString.lowercased())\",\"ok\":true,\"result\":{\(fields)}}"
        XCTAssertEqual(try BootstrapResponse.parse(Data(response.utf8), context: context), .adoptedAwaitingPreparation)
        for invalid in [response.replacingOccurrences(of: "\"next_step\":", with: "\"next_step\":\"system_setup\",\"next_\\u0073tep\":"),
            response.replacingOccurrences(of: owner.uuidString.lowercased(), with: UUID().uuidString.lowercased()),
            response.replacingOccurrences(of: claim.uuidString.lowercased(), with: UUID().uuidString.lowercased()),
            response.replacingOccurrences(of: "system_setup", with: "completed"),
            response.dropLast() + ",\"https_port\":8443}"] {
            XCTAssertThrowsError(try BootstrapResponse.parse(Data(invalid.utf8), context: context))
        }
    }
    func testStrictJSONRejectsInvalidNumbersSurrogatesAndDepthWithoutLosingLexemes() throws {
        for raw in ["{\"v\":01}", "{\"v\":NaN}", "{\"v\":Infinity}", "{\"v\":-}",
                    "{\"v\":1.}", "{\"v\":1e}", "{\"v\":\"\\ud800\"}", "{\"v\":true,}"] {
            XCTAssertThrowsError(try BootstrapWire.object(Data(raw.utf8)), raw)
        }
        let depth32Empty = "{\"a\":" + String(repeating: "[", count: 31) + String(repeating: "]", count: 31) + "}"
        let depth33Empty = "{\"a\":" + String(repeating: "[", count: 32) + String(repeating: "]", count: 32) + "}"
        XCTAssertNoThrow(try BootstrapWire.object(Data(depth32Empty.utf8)))
        XCTAssertThrowsError(try BootstrapWire.object(Data(depth33Empty.utf8)))
        let nested = "{\"a\":" + String(repeating: "[", count: 33) + "0" + String(repeating: "]", count: 33) + "}"
        XCTAssertThrowsError(try BootstrapWire.object(Data(nested.utf8)))
    }
    func testCertificateAssemblyChecksExactLengthsAndProfile() throws {
        for count in [1, 479, 480, 481, 960] {
            var assembly = BootstrapIdentityAssembly()
            let metadata = "{\"v\":2,\"p\":\"bootstrap\",\"id\":\"00000000-0000-4000-8000-000000000001\",\"cert_length\":\(count)}"
            try assembly.readMetadata(Data(metadata.utf8))
            try assembly.readFirstCertificatePart(Data(repeating: 0x30, count: min(480, count)))
            let second = Data(repeating: 0x31, count: max(0, count - 480))
            let object = try BootstrapWire.object(assembly.finish(secondCertificatePart: second), maximum: 4096)
            XCTAssertEqual(object["v"], .number("2"))
            XCTAssertEqual(object["p"], .string("bootstrap"))
            XCTAssertThrowsError(try assembly.finish(secondCertificatePart: second + Data([0])))
        }
        var assembly = BootstrapIdentityAssembly()
        XCTAssertThrowsError(try assembly.readMetadata(Data("{\"v\":1,\"id\":\"00000000-0000-4000-8000-000000000001\",\"cert_length\":480}".utf8)))
    }
}

private struct Corpus: Decodable {
    let rawCases: [RawCase]
    private enum CodingKeys: String, CodingKey { case rawCases = "raw_cases" }
}
private struct RawCase: Decodable {
    let name: String
    let stage: String
    let inputHex: String
    let framedHex: String?
    let expected: Expected
    let context: Context?
    struct Expected: Decodable { let accept: Bool; let profile: String?; let reason: String?; let correlated: Bool? }
    struct Context: Decodable {
        let rpcID: String?; let frameID: String; let ownerID: String; let claimID: String
        private enum CodingKeys: String, CodingKey {
            case rpcID = "rpc_id", frameID = "frame_id", ownerID = "owner_id", claimID = "claim_request_id"
        }
    }
    private enum CodingKeys: String, CodingKey {
        case name, stage, expected, context, inputHex = "input_utf8_hex", framedHex = "framed_plaintext_hex"
    }
}
