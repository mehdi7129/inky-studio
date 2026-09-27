import Foundation
import XCTest
@testable import InkyTLS

@MainActor
final class ConfigurationTests: XCTestCase {
    func testRejectsMissingTrustMalformedPinAndUnboundedQueues() throws {
        for capacity in [0, 1023, 262_145, Int.max] {
            XCTAssertThrowsError(try TLSConfiguration(serverName: "frame.inky.invalid",
                trustedCertificatesDER: [Data([1])], pinnedSPKISHA256: Data(count: 32), bufferCapacity: capacity))
        }
        XCTAssertThrowsError(try TLSConfiguration(serverName: "frame\0attacker",
            trustedCertificatesDER: [Data([1])], pinnedSPKISHA256: Data(count: 32)))
        XCTAssertThrowsError(try TLSConfiguration(serverName: "frame.inky.invalid",
            trustedCertificatesDER: [], pinnedSPKISHA256: Data(count: 32)))
        XCTAssertThrowsError(try TLSConfiguration(serverName: "frame.inky.invalid",
            trustedCertificatesDER: [Data([1])], pinnedSPKISHA256: Data(count: 31)))
    }

    func testRejectsMalformedDERInsteadOfCreatingTrustAllClient() throws {
        let configuration = try TLSConfiguration(serverName: "frame.inky.invalid",
            trustedCertificatesDER: [Data([1, 2, 3])], pinnedSPKISHA256: Data(count: 32))
        XCTAssertThrowsError(try TLSClient(configuration: configuration))
    }

    func testGeneratesClientHelloOnCurrentAppleRuntime() async throws {
        let certificate = try XCTUnwrap(Bundle.module.url(forResource: "valid", withExtension: "der", subdirectory: "Support/Generated"))
        let pin = try XCTUnwrap(Bundle.module.url(forResource: "pin", withExtension: "bin", subdirectory: "Support/Generated"))
        let tls = try TLSClient(configuration: TLSConfiguration(
            serverName: "frame-00000000-0000-4000-8000-000000000001.inky.invalid",
            trustedCertificatesDER: [Data(contentsOf: certificate)], pinnedSPKISHA256: Data(contentsOf: pin)))
        let progress = try await tls.advanceHandshake()
        XCTAssertEqual(progress, .needsRead)
        let bytes = try await tls.drainCiphertext(maxBytes: 1024)
        XCTAssertFalse(bytes.isEmpty)
        XCTAssertEqual(bytes.first, 22) // TLS handshake record, generated using the runtime entropy source.
    }
}
