import Foundation
import Security

/// The old LAN connection supplies only a locator. Its cookies and credentials
/// are never copied into this transport; the bootstrap secret is used locally only.
@MainActor
final class LegacyTLSProofClient {
    private let configuration: URLSessionConfiguration
    private let nonceGenerator: @Sendable () throws -> Data
    private let timeout: TimeInterval

    init(configuration: URLSessionConfiguration = .ephemeral, timeout: TimeInterval = 12,
         nonceGenerator: @escaping @Sendable () throws -> Data = LegacyTLSProofClient.randomNonce) {
        // Preserve only protocol classes for isolated test injection, never caller headers/storage/proxy configuration.
        let sterile = URLSessionConfiguration.ephemeral
        sterile.protocolClasses = configuration.protocolClasses
        sterile.httpAdditionalHeaders = nil
        sterile.httpShouldSetCookies = false
        sterile.httpCookieStorage = nil
        sterile.urlCredentialStorage = nil
        sterile.urlCache = nil
        sterile.requestCachePolicy = .reloadIgnoringLocalCacheData
        sterile.waitsForConnectivity = false
        let boundedTimeout = timeout.isFinite && timeout > 0 ? min(timeout, 12) : 12
        sterile.timeoutIntervalForRequest = boundedTimeout
        sterile.timeoutIntervalForResource = boundedTimeout
        self.configuration = sterile
        self.timeout = boundedTimeout
        self.nonceGenerator = nonceGenerator
    }

    func prove(endpoint: URL, bootstrapPassword: String) async throws -> VerifiedLegacyTLSEndpoint {
        do {
            try Task.checkCancellation()
            guard LegacyTLSProofVerifier.validBootstrapPassword(bootstrapPassword), Self.isLegacyLANOrigin(endpoint) else {
                throw LegacyTLSProofError.unavailable
            }
            let nonce = try nonceGenerator()
            guard nonce.count == 32 else { throw LegacyTLSProofError.unavailable }
            var parts = URLComponents(url: endpoint, resolvingAgainstBaseURL: false)!
            parts.path = "/api/auth/legacy-tls-proof"
            guard let url = parts.url else { throw LegacyTLSProofError.unavailable }
            var request = URLRequest(url: url, cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: timeout)
            request.httpMethod = "POST"
            request.httpShouldHandleCookies = false
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.setValue("application/json", forHTTPHeaderField: "Accept")
            request.setValue("no-store", forHTTPHeaderField: "Cache-Control")
            let nonceText = nonce.map { String(format: "%02x", $0) }.joined()
            request.httpBody = try JSONSerialization.data(withJSONObject: ["v": 1, "nonce": nonceText], options: [.sortedKeys])
            let transfer = LegacyTLSProofTransfer(expectedURL: url)
            let response = try await transfer.data(for: request, configuration: configuration)
            try Task.checkCancellation()
            let verified = try LegacyTLSProofVerifier.verify(response: response, expectedNonce: nonce,
                                                              bootstrapPassword: bootstrapPassword)
            try Task.checkCancellation()
            return verified
        } catch is CancellationError { throw CancellationError() }
        catch { throw LegacyTLSProofError.unavailable }
    }

    nonisolated static func randomNonce() throws -> Data {
        var nonce = Data(count: 32)
        let result = nonce.withUnsafeMutableBytes { SecRandomCopyBytes(kSecRandomDefault, $0.count, $0.baseAddress!) }
        guard result == errSecSuccess else { throw LegacyTLSProofError.unavailable }
        return nonce
    }

    private static func isLegacyLANOrigin(_ endpoint: URL) -> Bool {
        guard let parts = URLComponents(url: endpoint, resolvingAgainstBaseURL: false), parts.scheme == "http",
              parts.user == nil, parts.password == nil, parts.path.isEmpty,
              parts.query == nil, parts.fragment == nil,
              let normalized = try? FrameAddress.parse(endpoint.absoluteString), normalized == endpoint else { return false }
        return true
    }
}

/// One operation/session per attempt. The buffer never exceeds the protocol bound.
/// All continuation and cancellation transitions are protected by the same lock.
final class LegacyTLSProofTransfer: NSObject, URLSessionDataDelegate, @unchecked Sendable {
    private let expectedURL: URL
    private let lock = NSLock()
    private var continuation: CheckedContinuation<Data, Error>?
    private var completed: Result<Data, Error>?
    private var buffer = Data()
    private var responseAccepted = false
    private var session: URLSession?
    private var task: URLSessionDataTask?

    init(expectedURL: URL) { self.expectedURL = expectedURL }

    func data(for request: URLRequest, configuration: URLSessionConfiguration) async throws -> Data {
        try await withTaskCancellationHandler(operation: {
            try Task.checkCancellation()
            return try await withCheckedThrowingContinuation { continuation in
                let start: (URLSessionDataTask?, Result<Data, Error>?) = lock.withLock {
                    if let completed { return (nil, completed) }
                    self.continuation = continuation
                    let session = URLSession(configuration: configuration, delegate: self, delegateQueue: nil)
                    self.session = session
                    let task = session.dataTask(with: request)
                    self.task = task
                    return (task, nil)
                }
                if let result = start.1 { continuation.resume(with: result) }
                else { start.0?.resume() }
            }
        }, onCancel: { self.finish(.failure(CancellationError())) })
    }

    func urlSession(_ session: URLSession, dataTask: URLSessionDataTask, didReceive response: URLResponse,
                    completionHandler: @escaping @Sendable (URLSession.ResponseDisposition) -> Void) {
        guard let response = response as? HTTPURLResponse, response.url == expectedURL,
              response.statusCode == 200, response.mimeType?.lowercased() == "application/json",
              response.value(forHTTPHeaderField: "Set-Cookie") == nil,
              response.value(forHTTPHeaderField: "Cache-Control")?.lowercased().split(separator: ",")
                .contains(where: { $0.trimmingCharacters(in: .whitespaces) == "no-store" }) == true,
              response.expectedContentLength <= Int64(LegacyTLSProofVerifier.maximumResponseBytes) else {
            completionHandler(.cancel)
            finish(.failure(LegacyTLSProofError.unavailable))
            return
        }
        let accept = lock.withLock { () -> Bool in
            guard completed == nil else { return false }
            responseAccepted = true
            return true
        }
        completionHandler(accept ? .allow : .cancel)
    }

    func urlSession(_ session: URLSession, dataTask: URLSessionDataTask, didReceive data: Data) {
        let overflow = lock.withLock { () -> Bool in
            guard completed == nil else { return false }
            guard data.count <= LegacyTLSProofVerifier.maximumResponseBytes - buffer.count else { return true }
            buffer.append(data)
            return false
        }
        if overflow { finish(.failure(LegacyTLSProofError.unavailable)) }
    }

    func urlSession(_ session: URLSession, task: URLSessionTask, didCompleteWithError error: Error?) {
        guard error == nil else { finish(.failure(LegacyTLSProofError.unavailable)); return }
        let result = lock.withLock { responseAccepted ? buffer : nil }
        if let result { finish(.success(result)) }
        else { finish(.failure(LegacyTLSProofError.unavailable)) }
    }

    func urlSession(_ session: URLSession, task: URLSessionTask, willPerformHTTPRedirection response: HTTPURLResponse,
                    newRequest request: URLRequest, completionHandler: @escaping @Sendable (URLRequest?) -> Void) {
        completionHandler(nil)
        finish(.failure(LegacyTLSProofError.unavailable))
    }

    func urlSession(_ session: URLSession, didReceive challenge: URLAuthenticationChallenge,
                    completionHandler: @escaping @Sendable (URLSession.AuthChallengeDisposition, URLCredential?) -> Void) {
        completionHandler(.cancelAuthenticationChallenge, nil)
        finish(.failure(LegacyTLSProofError.unavailable))
    }

    func urlSession(_ session: URLSession, task: URLSessionTask, didReceive challenge: URLAuthenticationChallenge,
                    completionHandler: @escaping @Sendable (URLSession.AuthChallengeDisposition, URLCredential?) -> Void) {
        completionHandler(.cancelAuthenticationChallenge, nil)
        finish(.failure(LegacyTLSProofError.unavailable))
    }

    private func finish(_ result: Result<Data, Error>) {
        let released: (CheckedContinuation<Data, Error>?, URLSessionDataTask?, URLSession?)? = lock.withLock {
            guard completed == nil else { return nil }
            completed = result
            let released = (continuation, task, session)
            continuation = nil; task = nil; session = nil
            buffer.removeAll(keepingCapacity: false)
            return released
        }
        guard let released else { return }
        released.1?.cancel()
        released.2?.invalidateAndCancel()
        released.0?.resume(with: result)
    }
}
