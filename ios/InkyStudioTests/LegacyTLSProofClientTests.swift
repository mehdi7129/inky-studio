import Foundation
import XCTest
@testable import InkyStudio

@MainActor
final class LegacyTLSProofClientTests: XCTestCase {
    private let endpoint = URL(string: "http://192.168.1.120:8000")!

    func testAnonymousRequestContainsOnlyVersionAndFreshNonceDespiteContaminatedConfiguration() async throws {
        let vector = LegacyTLSProofFixtures.first
        let stub = LegacyProofWireStub { request in
            XCTAssertEqual(request.url?.absoluteString, "http://192.168.1.120:8000/api/auth/legacy-tls-proof")
            XCTAssertEqual(request.httpMethod, "POST")
            XCTAssertFalse(request.httpShouldHandleCookies)
            let body = try JSONSerialization.jsonObject(with: request.legacyProofBody) as! [String: Any]
            XCTAssertEqual(Set(body.keys), ["v", "nonce"])
            XCTAssertEqual(body["v"] as? Int, 1)
            XCTAssertEqual(body["nonce"] as? String, vector.nonceHex)
            for header in ["Cookie", "Authorization", "Proxy-Authorization", "X-Inky-Owner-ID", "X-Inky-Owner-Token", "X-Device-Token"] {
                XCTAssertNil(request.value(forHTTPHeaderField: header))
            }
            XCTAssertFalse(String(decoding: request.legacyProofBody, as: UTF8.self).contains(vector.secret))
            return .valid(vector.response)
        }
        defer { stub.dispose() }
        let configuration = stub.configuration()
        configuration.httpAdditionalHeaders = ["Cookie": "fixture-session", "Authorization": "fixture-auth",
            "Proxy-Authorization": "fixture-proxy-auth", "X-Inky-Owner-Token": "fixture-owner"]
        configuration.httpShouldSetCookies = true
        if let cookie = HTTPCookie(properties: [.domain: "192.168.1.120", .path: "/", .name: "inky_session", .value: "fixture-cookie"]) {
            configuration.httpCookieStorage?.setCookie(cookie)
        }
        let client = LegacyTLSProofClient(configuration: configuration, nonceGenerator: { vector.nonce })
        let result = try await client.prove(endpoint: endpoint, bootstrapPassword: vector.secret)
        XCTAssertEqual(result.identity.id, vector.frameID)
        XCTAssertEqual(result.endpoint.absoluteString, vector.url)
        XCTAssertEqual(stub.requests.count, 1, "The HTTPS identity is returned only; the anonymous client must not log in or follow it.")
    }

    func testEveryAttemptGeneratesItsOwnNonceWithoutRetries() async {
        let stub = LegacyProofWireStub { _ in LegacyProofWireStub.Response(status: 404) }
        defer { stub.dispose() }
        let client = LegacyTLSProofClient(configuration: stub.configuration())
        for _ in 0..<2 { await unavailable { _ = try await client.prove(endpoint: self.endpoint, bootstrapPassword: LegacyTLSProofFixtures.first.secret) } }
        let nonces = stub.requests.compactMap { request -> String? in
            let body = try? JSONSerialization.jsonObject(with: request.legacyProofBody) as? [String: Any]
            return body?["nonce"] as? String
        }
        XCTAssertEqual(nonces.count, 2)
        XCTAssertEqual(Set(nonces).count, 2)
        XCTAssertTrue(nonces.allSatisfy { LegacyTLSProofVerifier.hex($0)?.count == 32 })
    }

    func testInvalidSecretOrSelectedOriginNeverStartsARequest() async {
        let stub = LegacyProofWireStub { _ in XCTFail("Invalid inputs must fail before networking."); return .valid(Data()) }
        defer { stub.dispose() }
        let client = LegacyTLSProofClient(configuration: stub.configuration())
        for text in ["https://192.168.1.120:8000", "http://user:secret@192.168.1.120:8000",
                     "http://192.168.1.120:8000/path", "http://192.168.1.120:8000?token=x", "http://192.168.1.120:8000#x"] {
            await unavailable { _ = try await client.prove(endpoint: URL(string: text)!, bootstrapPassword: LegacyTLSProofFixtures.first.secret) }
        }
        await unavailable { _ = try await client.prove(endpoint: self.endpoint, bootstrapPassword: "custom-password") }
        XCTAssertTrue(stub.requests.isEmpty)
    }

    func testWrongMACOrStaleNonceNeverReturnsAPromotedIdentity() async {
        let vector = LegacyTLSProofFixtures.first
        for nonce in [vector.nonce, Data(repeating: 255, count: 32)] {
            let stub = LegacyProofWireStub { _ in .valid(vector.response) }
            defer { stub.dispose() }
            let client = LegacyTLSProofClient(configuration: stub.configuration(), nonceGenerator: { nonce })
            await unavailable { _ = try await client.prove(endpoint: self.endpoint, bootstrapPassword: "Abcdef0123456780") }
            XCTAssertEqual(stub.requests.count, 1)
        }
    }

    func testUnexpectedStatusMIMEOriginCookieOrCachePolicyIsRejected() async {
        let vector = LegacyTLSProofFixtures.first
        var badMIME = LegacyProofWireStub.Response.valid(vector.response); badMIME.headers["Content-Type"] = "text/html"
        var badOrigin = LegacyProofWireStub.Response.valid(vector.response); badOrigin.url = URL(string: "http://other.local:8000/api/auth/legacy-tls-proof")!
        var cookie = LegacyProofWireStub.Response.valid(vector.response); cookie.headers["Set-Cookie"] = "inky_session=untrusted; Path=/"
        var caching = LegacyProofWireStub.Response.valid(vector.response); caching.headers.removeValue(forKey: "Cache-Control")
        let variants = [LegacyProofWireStub.Response(status: 503), badMIME, badOrigin, cookie, caching]
        for response in variants {
            let stub = LegacyProofWireStub { _ in response }
            defer { stub.dispose() }
            let client = LegacyTLSProofClient(configuration: stub.configuration(), nonceGenerator: { vector.nonce })
            await unavailable { _ = try await client.prove(endpoint: self.endpoint, bootstrapPassword: vector.secret) }
            XCTAssertEqual(stub.requests.count, 1)
        }
    }

    func testOversizedDeclaredOrChunkedBodiesAreCancelledWithoutVerifiedResult() async {
        let vector = LegacyTLSProofFixtures.first
        var declared = LegacyProofWireStub.Response.valid(vector.response)
        declared.headers["Content-Length"] = "2049"
        let chunked = LegacyProofWireStub.Response(chunks: [Data(repeating: 32, count: 1024), Data(repeating: 32, count: 1025)])
        for response in [declared, chunked] {
            let stub = LegacyProofWireStub { _ in response }
            defer { stub.dispose() }
            let client = LegacyTLSProofClient(configuration: stub.configuration(), nonceGenerator: { vector.nonce })
            await unavailable { _ = try await client.prove(endpoint: self.endpoint, bootstrapPassword: vector.secret) }
            XCTAssertEqual(stub.requests.count, 1)
        }
    }

    func testExactResponseBoundMayBeStreamedAcrossChunks() async throws {
        let vector = LegacyTLSProofFixtures.first
        let padded = vector.response + Data(repeating: 32, count: 2048 - vector.response.count)
        let stub = LegacyProofWireStub { _ in
            LegacyProofWireStub.Response(chunks: [Data(padded.prefix(1000)), Data(padded.dropFirst(1000))])
        }
        defer { stub.dispose() }
        let client = LegacyTLSProofClient(configuration: stub.configuration(), nonceGenerator: { vector.nonce })
        let verified = try await client.prove(endpoint: endpoint, bootstrapPassword: vector.secret)
        XCTAssertEqual(verified.identity.id, vector.frameID)
    }

    func testCancellationStopsTheTransportAndCannotPublishALateProof() async throws {
        let vector = LegacyTLSProofFixtures.first
        let started = expectation(description: "Public nonce request started")
        let stopped = expectation(description: "Cancelled transport stopped")
        let stub = LegacyProofWireStub { _ in
            LegacyProofWireStub.Response(holdOpen: true, onStart: { started.fulfill() }, onStop: { stopped.fulfill() })
        }
        defer { stub.dispose() }
        let client = LegacyTLSProofClient(configuration: stub.configuration(), nonceGenerator: { vector.nonce })
        let pending = Task { try await client.prove(endpoint: endpoint, bootstrapPassword: vector.secret) }
        await fulfillment(of: [started], timeout: 2)
        pending.cancel()
        do { _ = try await pending.value; XCTFail("Cancelled proof must not return a verified endpoint.") }
        catch { XCTAssertTrue(error is CancellationError) }
        await fulfillment(of: [stopped], timeout: 2)
        XCTAssertEqual(stub.requests.count, 1)
    }

    func testAllRedirectsAreRejectedIncludingSameOrigin() async throws {
        let original = endpoint.appendingPathComponent("api/auth/legacy-tls-proof")
        for text in [original.absoluteString + "/", "http://other.local:8000/", "https://192.168.1.120:8443/"] {
            let transfer = LegacyTLSProofTransfer(expectedURL: original)
            let session = URLSession(configuration: .ephemeral)
            defer { session.invalidateAndCancel() }
            let task = session.dataTask(with: original)
            let response = HTTPURLResponse(url: original, statusCode: 307, httpVersion: nil, headerFields: nil)!
            transfer.urlSession(session, task: task, willPerformHTTPRedirection: response,
                newRequest: URLRequest(url: URL(string: text)!)) { redirected in XCTAssertNil(redirected) }
            let stub = LegacyProofWireStub { _ in XCTFail("Redirect rejection must prevent another request."); return .valid(Data()) }
            defer { stub.dispose() }
            await unavailable { _ = try await transfer.data(for: URLRequest(url: original), configuration: stub.configuration()) }
            XCTAssertTrue(stub.requests.isEmpty)
        }
    }

    func testHTTPAuthenticationChallengesNeverReceiveStoredCredentials() {
        let requestURL = endpoint.appendingPathComponent("api/auth/legacy-tls-proof")
        let transfer = LegacyTLSProofTransfer(expectedURL: requestURL)
        let session = URLSession(configuration: .ephemeral)
        defer { session.invalidateAndCancel() }
        let space = URLProtectionSpace(host: "192.168.1.120", port: 8000, protocol: "http", realm: "fixture",
                                       authenticationMethod: NSURLAuthenticationMethodHTTPBasic)
        let sender = LegacyProofChallengeSender()
        let challenge = URLAuthenticationChallenge(protectionSpace: space,
            proposedCredential: URLCredential(user: "fixture-user", password: "fixture-password", persistence: .none),
            previousFailureCount: 0, failureResponse: nil, error: nil, sender: sender)
        transfer.urlSession(session, didReceive: challenge) { action, credential in
            XCTAssertEqual(action, .cancelAuthenticationChallenge)
            XCTAssertNil(credential)
        }
    }

    private func unavailable(file: StaticString = #filePath, line: UInt = #line,
                             _ action: () async throws -> Void) async {
        do { try await action(); XCTFail("Untrusted proof must remain unavailable.", file: file, line: line) }
        catch { XCTAssertEqual(error as? LegacyTLSProofError, .unavailable, file: file, line: line) }
    }
}

private final class LegacyProofWireStub: @unchecked Sendable {
    struct Response {
        var status = 200
        var headers = ["Content-Type": "application/json", "Cache-Control": "no-store"]
        var chunks: [Data] = []
        var url: URL?
        var holdOpen = false
        var onStart: (() -> Void)?
        var onStop: (() -> Void)?
        static func valid(_ data: Data) -> Response { Response(chunks: [data]) }
    }
    private let lock = NSLock()
    private var recorded: [URLRequest] = []
    private let handler: (URLRequest) throws -> Response
    init(_ handler: @escaping (URLRequest) throws -> Response) { self.handler = handler }
    var requests: [URLRequest] { lock.withLock { recorded } }
    func configuration() -> URLSessionConfiguration {
        LegacyProofWireURLProtocol.install(self)
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [LegacyProofWireURLProtocol.self]
        return configuration
    }
    func dispose() { LegacyProofWireURLProtocol.remove(self) }
    func respond(_ request: URLRequest) throws -> Response {
        var copy = request; copy.httpBody = request.legacyProofBody
        lock.withLock { recorded.append(copy) }
        return try handler(copy)
    }
}

private final class LegacyProofWireURLProtocol: URLProtocol, @unchecked Sendable {
    private static let lock = NSLock()
    nonisolated(unsafe) private static var current: LegacyProofWireStub?
    private var onStop: (() -> Void)?
    static func install(_ fixture: LegacyProofWireStub) { lock.withLock { current = fixture } }
    static func remove(_ fixture: LegacyProofWireStub) { lock.withLock { if current === fixture { current = nil } } }
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        do {
            guard let fixture = Self.lock.withLock({ Self.current }) else { throw URLError(.resourceUnavailable) }
            let response = try fixture.respond(request)
            onStop = response.onStop
            response.onStart?()
            if response.holdOpen { return }
            let head = HTTPURLResponse(url: response.url ?? request.url!, statusCode: response.status,
                                        httpVersion: "HTTP/1.1", headerFields: response.headers)!
            client?.urlProtocol(self, didReceive: head, cacheStoragePolicy: .notAllowed)
            for chunk in response.chunks { client?.urlProtocol(self, didLoad: chunk) }
            client?.urlProtocolDidFinishLoading(self)
        } catch { client?.urlProtocol(self, didFailWithError: error) }
    }
    override func stopLoading() { onStop?() }
}

private final class LegacyProofChallengeSender: NSObject, URLAuthenticationChallengeSender {
    func use(_ credential: URLCredential, for challenge: URLAuthenticationChallenge) {}
    func continueWithoutCredential(for challenge: URLAuthenticationChallenge) {}
    func cancel(_ challenge: URLAuthenticationChallenge) {}
    func performDefaultHandling(for challenge: URLAuthenticationChallenge) {}
    func rejectProtectionSpaceAndContinue(with challenge: URLAuthenticationChallenge) {}
}

private extension URLRequest {
    var legacyProofBody: Data {
        if let httpBody { return httpBody }
        guard let stream = httpBodyStream else { return Data() }
        stream.open(); defer { stream.close() }
        var result = Data(); var buffer = [UInt8](repeating: 0, count: 1024)
        while stream.hasBytesAvailable {
            let count = stream.read(&buffer, maxLength: buffer.count)
            guard count > 0 else { break }
            result.append(contentsOf: buffer.prefix(count))
        }
        return result
    }
}
