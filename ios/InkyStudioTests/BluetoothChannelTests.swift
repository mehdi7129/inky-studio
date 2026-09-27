import Foundation
import XCTest
@testable import InkyStudio

final class BluetoothRecordTests: XCTestCase {
    func testFragmentSizesAcknowledgementsAndNonzeroDataIndices() throws {
        for maximum in [20, 244] {
            var state = BluetoothRecordState()
            let payload = Data(repeating: 7, count: maximum - 5)
            XCTAssertEqual(try state.encode(payload, maximum: maximum).count, maximum)
            XCTAssertThrowsError(try state.encode(payload + Data([0]), maximum: maximum))
            var response = Data([99, 1, 0, 1, 0, 1]) + payload
            response.removeFirst() // Data's startIndex need not be zero.
            XCTAssertEqual(try state.accept(response, maximum: maximum), payload)
            XCTAssertEqual(state.acknowledged, 1)
            XCTAssertEqual(Array(try state.encode(Data(), maximum: maximum)), [1, 0, 2, 0, 1])
            XCTAssertThrowsError(try state.accept(response, maximum: maximum))
            XCTAssertEqual(state.acknowledged, 1)
        }
    }

    func testPublicIdentityUsesTwoExactATTValues() throws {
        for count in [1, 479, 480, 481, 600, 960] {
            var assembly = BluetoothIdentityAssembly()
            let id = UUID()
            let metadata = try JSONSerialization.data(withJSONObject: ["v": 1, "id": id.uuidString, "cert_length": count])
            XCTAssertLessThanOrEqual(metadata.count, 128)
            let certificate = Data((0..<count).map { UInt8($0 % 251) })
            try assembly.readMetadata(metadata)
            try assembly.readFirstCertificatePart(Data(certificate.prefix(480)))
            let result = try assembly.finish(secondCertificatePart: Data(certificate.dropFirst(min(480, count))))
            let decoded = try XCTUnwrap(JSONSerialization.jsonObject(with: result) as? [String: Any])
            XCTAssertEqual(decoded["id"] as? String, id.uuidString.lowercased())
            XCTAssertEqual(Data(base64Encoded: try XCTUnwrap(decoded["cert"] as? String)), certificate)
        }
    }

    func testMissingOversizedAndOutOfOrderIdentityPartsAreRejected() throws {
        for count in [0, 961] {
            var assembly = BluetoothIdentityAssembly()
            let metadata = try JSONSerialization.data(withJSONObject: ["v": 1, "id": UUID().uuidString, "cert_length": count])
            XCTAssertThrowsError(try assembly.readMetadata(metadata))
        }
        var assembly = BluetoothIdentityAssembly()
        XCTAssertThrowsError(try assembly.finish(secondCertificatePart: Data()))
        XCTAssertThrowsError(try assembly.readFirstCertificatePart(Data([1])))
        try assembly.readMetadata(JSONSerialization.data(withJSONObject: ["v": 1, "id": UUID().uuidString, "cert_length": 600]))
        XCTAssertThrowsError(try assembly.readFirstCertificatePart(Data(repeating: 1, count: 479)))
        try assembly.readFirstCertificatePart(Data(repeating: 1, count: 480))
        XCTAssertThrowsError(try assembly.finish(secondCertificatePart: Data(repeating: 2, count: 119)))
        XCTAssertThrowsError(try assembly.finish(secondCertificatePart: Data(repeating: 2, count: 121)))
    }

    func testMalformedAndOutOfOrderResponsesDoNotAdvanceState() {
        for bytes: [UInt8] in [[0, 0, 1, 0, 1], [1, 0, 2, 0, 1], [1, 0, 1, 0, 2], [1, 0, 1]] {
            var state = BluetoothRecordState()
            XCTAssertThrowsError(try state.accept(Data(bytes), maximum: 20))
            XCTAssertEqual(state.acknowledged, 0)
        }
    }

    func testSequenceCannotWrapOrUseReserved65535() throws {
        var state = BluetoothRecordState()
        for sequence in 1...65_534 {
            let high = UInt8(sequence >> 8), low = UInt8(sequence & 255)
            _ = try state.accept(Data([1, high, low, high, low]), maximum: 20)
        }
        XCTAssertThrowsError(try state.encode(Data(), maximum: 20))
        XCTAssertThrowsError(try state.accept(Data([1, 255, 255, 255, 255]), maximum: 20))
    }

    func testMessageFramingIsBoundedAndHandlesSplitHeader() throws {
        let message = Data(repeating: 42, count: 16_384)
        let encoded = try BluetoothMessageBuffer.encode(message)
        var buffer = BluetoothMessageBuffer()
        for byte in encoded { try buffer.append(Data([byte])) }
        XCTAssertEqual(buffer.message, message)
        XCTAssertThrowsError(try buffer.append(Data([1])))
        XCTAssertThrowsError(try BluetoothMessageBuffer.encode(Data()))
        XCTAssertThrowsError(try BluetoothMessageBuffer.encode(message + Data([1])))
        for header in [Data([0, 0, 0, 0]), Data([0, 0, 64, 1]), Data([255, 255, 255, 255])] {
            var invalid = BluetoothMessageBuffer()
            XCTAssertThrowsError(try invalid.append(header))
        }
    }
}

@MainActor final class BluetoothChannelTests: XCTestCase {
    private final class StubTransport: BluetoothExchanging {
        let maxFrameLength = 20
        var identity = Data()
        var pending: CheckedContinuation<Data, Error>?
        var blockConnect = false
        var exchangeCount = 0
        var cancelCount = 0
        func connect(peripheralID: UUID) async throws -> Data {
            if blockConnect { return try await withCheckedThrowingContinuation { pending = $0 } }
            return identity
        }
        func exchange(_ frame: Data) async throws -> Data { exchangeCount += 1; return frame }
        func cancel() {
            cancelCount += 1
            let old = pending
            pending = nil
            old?.resume(throwing: BluetoothTransportError.cancelled)
        }
    }

    func testInvalidIdentityCannotSendResetOrTLS() async throws {
        let transport = StubTransport()
        let channel = SecureBluetoothChannel(transport: transport)
        let identity = try FrameIdentity(id: UUID(), spkiSHA256: Data(repeating: 0, count: 32))
        for data in [Data(repeating: 0, count: 4097), Data("{}".utf8),
                     Data("{\"v\":1,\"id\":\"\(identity.id)\",\"cert\":\"AA==\"}".utf8)] {
            transport.identity = data
            do { _ = try await channel.connect(peripheralID: UUID(), identity: identity); XCTFail("Invalid identity accepted") }
            catch { }
        }
        XCTAssertEqual(transport.exchangeCount, 0)
        XCTAssertEqual(transport.cancelCount, 3)
    }

    func testConcurrentConnectRejectedAndCancellationCleansPendingOperation() async throws {
        let transport = StubTransport()
        transport.blockConnect = true
        let channel = SecureBluetoothChannel(transport: transport)
        let identity = try FrameIdentity(id: UUID(), spkiSHA256: Data(repeating: 0, count: 32))
        let task = Task { try await channel.connect(peripheralID: UUID(), identity: identity) }
        while transport.pending == nil { await Task.yield() }
        do { _ = try await channel.connect(peripheralID: UUID(), identity: identity); XCTFail("Concurrent connect accepted") }
        catch { XCTAssertEqual(error as? SecureBluetoothError, .busy) }
        task.cancel()
        do { _ = try await task.value; XCTFail("Cancelled connect succeeded") }
        catch { XCTAssertEqual(error as? SecureBluetoothError, .cancelled) }
        XCTAssertNil(transport.pending)
        XCTAssertNil(channel.trust)
        transport.blockConnect = false
        do { _ = try await channel.connect(peripheralID: UUID(), identity: identity); XCTFail("Invalid identity accepted") }
        catch { XCTAssertEqual(error as? SecureBluetoothError, .invalidIdentity) }
    }
}
