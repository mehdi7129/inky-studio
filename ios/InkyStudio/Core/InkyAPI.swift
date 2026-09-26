import Foundation

/// Foundation's default cookie store does not isolate ports. Keep an in-memory
/// jar per frame connection instead, shared by this client's HTTP and WS calls.
@MainActor
final class InkyAPI {
    let baseURL: URL
    private let configuration: URLSessionConfiguration
    private let redirectDelegate: OriginRedirectDelegate
    private var session: URLSession
    private var cookies: [HTTPCookie] = []
    private var sessionGeneration = UUID()
    private var eventGeneration: UUID?
    private var eventTask: Task<Void, Never>?
    private var socket: URLSessionWebSocketTask?
    private var eventContinuation: AsyncThrowingStream<ServerEvent, Error>.Continuation?
    private let decoder: JSONDecoder
    private let encoder: JSONEncoder

    init(baseURL: URL, configuration: URLSessionConfiguration = .ephemeral) {
        self.baseURL = baseURL
        let isolated = configuration.copy() as! URLSessionConfiguration
        isolated.httpShouldSetCookies = false
        isolated.httpCookieStorage = nil
        isolated.urlCredentialStorage = nil
        isolated.urlCache = nil
        isolated.requestCachePolicy = .reloadIgnoringLocalCacheData
        // The first LAN request can wait for the system's Local Network prompt.
        // The resource timeout still bounds requests while connectivity waits.
        isolated.waitsForConnectivity = true
        isolated.timeoutIntervalForRequest = 30
        isolated.timeoutIntervalForResource = 120
        self.configuration = isolated
        let delegate = OriginRedirectDelegate(origin: baseURL)
        redirectDelegate = delegate
        session = URLSession(configuration: isolated, delegate: delegate, delegateQueue: nil)
        decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        encoder = JSONEncoder()
        encoder.keyEncodingStrategy = .convertToSnakeCase
    }

    deinit { session.invalidateAndCancel() }

    func authStatus() async throws -> AuthStatus { try await get("/api/auth/status", timeout: 12) }
    func health() async throws -> HealthResponse { try await get("/api/health", timeout: 12) }
    func state() async throws -> DisplayState { try await get("/api/state") }
    func queue() async throws -> [QueueEntry] { try await get("/api/queue") }
    func settings() async throws -> FrameSettings { try await get("/api/settings") }

    func login(password: String) async throws -> AuthStatus {
        struct Login: Encodable { var password: String }
        return try await send("POST", path: "/api/auth/login", body: Login(password: password), timeout: 12)
    }

    func logout() async throws -> AuthStatus {
        defer { clearSession() }
        let data = try await perform(request("POST", path: "/api/auth/logout"))
        return try decodeResponse(data)
    }

    func history(limit: Int = 100, offset: Int = 0) async throws -> [HistoryEntry] {
        try await get("/api/history", query: [
            URLQueryItem(name: "limit", value: String(limit)),
            URLQueryItem(name: "offset", value: String(offset)),
        ])
    }

    func updateSettings(_ settings: FrameSettings) async throws -> FrameSettings {
        try await send("POST", path: "/api/settings", body: settings)
    }

    func updateStatus(refresh: Bool = false) async throws -> UpdateStatus {
        try await get("/api/system/update", query: refresh ? [URLQueryItem(name: "refresh", value: "1")] : [])
    }

    @discardableResult
    func startUpdate() async throws -> Bool {
        struct Started: Decodable { var started: Bool }
        let data = try await perform(request("POST", path: "/api/system/update"))
        let result: Started = try decodeResponse(data)
        return result.started
    }

    func reorderQueue(photoIDs: [String]) async throws -> [QueueEntry] {
        // Use photoIds (not photoIDs) so convertToSnakeCase emits photo_ids.
        struct Order: Encodable { var photoIds: [String] }
        return try await send("POST", path: "/api/queue/reorder", body: Order(photoIds: photoIDs))
    }

    func removeFromQueue(photoID: String) async throws {
        _ = try await perform(request("DELETE", path: "/api/queue/" + pathComponent(photoID)))
    }

    func deleteHistoryEntry(id: Int) async throws {
        _ = try await perform(request("DELETE", path: "/api/history/\(id)"))
    }

    func clearHistory() async throws {
        _ = try await perform(request("DELETE", path: "/api/history"))
    }

    func next() async throws {
        _ = try await perform(request("POST", path: "/api/display/next", timeout: 120))
    }

    func previous() async throws {
        _ = try await perform(request("POST", path: "/api/display/previous", timeout: 120))
    }

    func upload(png: Data, filename: String) async throws -> UploadResponse {
        let boundary = "InkyStudio-" + UUID().uuidString
        // Quotes and CR/LF must not become multipart headers supplied by a filename.
        let safeName = filename.replacingOccurrences(of: "\r", with: "_")
            .replacingOccurrences(of: "\n", with: "_")
            .replacingOccurrences(of: "\"", with: "_")
            .replacingOccurrences(of: "\\", with: "_")
        var body = Data("--\(boundary)\r\nContent-Disposition: form-data; name=\"file\"; filename=\"\(safeName)\"\r\nContent-Type: image/png\r\n\r\n".utf8)
        body.append(png)
        body.append(Data("\r\n--\(boundary)--\r\n".utf8))
        var upload = try request("POST", path: "/api/queue", timeout: 60)
        upload.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        upload.httpBody = body
        let data = try await perform(upload)
        return try decodeResponse(data)
    }

    func photoData(id: String) async throws -> Data {
        try await perform(request("GET", path: "/api/photos/" + pathComponent(id)))
    }

    /// Disconnect and forget only this connection's session. No cookies touch
    /// HTTPCookieStorage.shared, another frame, Safari, or persistent storage.
    func clearSession() {
        stopEvents()
        cookies.removeAll()
        sessionGeneration = UUID()
        session.invalidateAndCancel()
        session = URLSession(configuration: configuration, delegate: redirectDelegate, delegateQueue: nil)
    }

    /// Network reconnects only resubscribe; mutations are never replayed.
    /// Each server `hello` tells the caller to reload current state.
    func events() -> AsyncThrowingStream<ServerEvent, Error> {
        stopEvents()
        let generation = UUID()
        eventGeneration = generation
        return AsyncThrowingStream(bufferingPolicy: .bufferingNewest(32)) { continuation in
            eventContinuation = continuation
            continuation.onTermination = { [weak self] _ in
                Task { @MainActor [weak self] in
                    guard self?.eventGeneration == generation else { return }
                    self?.stopEvents()
                }
            }
            eventTask = Task { [weak self] in
                await self?.receiveEvents(generation: generation, continuation: continuation)
            }
        }
    }

    func stopEvents() {
        eventGeneration = nil
        eventTask?.cancel()
        eventTask = nil
        socket?.cancel(with: .goingAway, reason: nil)
        socket = nil
        eventContinuation?.finish()
        eventContinuation = nil
    }

    private func receiveEvents(
        generation: UUID,
        continuation: AsyncThrowingStream<ServerEvent, Error>.Continuation
    ) async {
        var backoff: UInt64 = 500_000_000
        while !Task.isCancelled, eventGeneration == generation {
            let connection: URLSessionWebSocketTask
            do {
                connection = session.webSocketTask(with: try eventRequest())
            } catch {
                continuation.finish(throwing: error)
                return
            }
            socket = connection
            connection.maximumMessageSize = 512 * 1024
            connection.resume()
            do {
                while !Task.isCancelled, eventGeneration == generation {
                    let message = try await connection.receive()
                    let data: Data
                    switch message {
                    case .string(let string): data = Data(string.utf8)
                    case .data(let bytes): data = bytes
                    @unknown default: continue
                    }
                    guard let event = try? decoder.decode(ServerEvent.self, from: data) else { continue }
                    backoff = 500_000_000
                    continuation.yield(event)
                }
            } catch {
                let closeCode = connection.closeCode
                connection.cancel(with: .goingAway, reason: nil)
                guard !Task.isCancelled, eventGeneration == generation else { break }
                if closeCode == .policyViolation ||
                    (connection.response as? HTTPURLResponse)?.statusCode == 401 {
                    continuation.finish(throwing: APIError.unauthorized)
                    return
                }
                continuation.yield(ServerEvent(type: "connection_lost"))
                // A failed handshake may hide the server's 1008 close code.
                do {
                    let auth = try await authStatus()
                    if auth.authRequired && !auth.authenticated {
                        continuation.finish(throwing: APIError.unauthorized)
                        return
                    }
                } catch let error as APIError where error.isUnauthorized {
                    continuation.finish(throwing: error)
                    return
                } catch {
                    // Offline/restarting: preserve the bounded reconnect loop.
                }
                guard !Task.isCancelled, eventGeneration == generation else { break }
                continuation.yield(ServerEvent(type: "reconnecting"))
                do { try await Task.sleep(nanoseconds: backoff) }
                catch { break }
                backoff = min(backoff * 2, 30_000_000_000)
            }
        }
        continuation.finish()
    }

    /// Internal for protocol-level tests; uses the same jar as JSON and photos.
    func eventRequest() throws -> URLRequest {
        var result = try request("GET", path: "/api/ws", timeout: 15)
        guard var parts = URLComponents(url: result.url!, resolvingAgainstBaseURL: false) else {
            throw APIError.invalidResponse
        }
        parts.scheme = baseURL.scheme == "https" ? "wss" : "ws"
        result.url = parts.url
        return result
    }

    private func get<T: Decodable>(_ path: String, query: [URLQueryItem] = [], timeout: TimeInterval = 30) async throws -> T {
        let data = try await perform(request("GET", path: path, query: query, timeout: timeout))
        return try decodeResponse(data)
    }

    private func send<T: Decodable, Body: Encodable>(
        _ method: String, path: String, body: Body, timeout: TimeInterval = 30
    ) async throws -> T {
        var call = try request(method, path: path, timeout: timeout)
        call.setValue("application/json", forHTTPHeaderField: "Content-Type")
        call.httpBody = try encoder.encode(body)
        let data = try await perform(call)
        return try decodeResponse(data)
    }

    private func decodeResponse<T: Decodable>(_ data: Data) throws -> T {
        do { return try decoder.decode(T.self, from: data) }
        catch { throw APIError.invalidData }
    }

    private func request(
        _ method: String, path: String, query: [URLQueryItem] = [], timeout: TimeInterval = 30
    ) throws -> URLRequest {
        guard var parts = URLComponents(url: baseURL, resolvingAgainstBaseURL: false),
              ["http", "https"].contains(parts.scheme?.lowercased() ?? ""),
              parts.user == nil, parts.password == nil else { throw APIError.invalidResponse }
        parts.percentEncodedPath = path
        parts.queryItems = query.isEmpty ? nil : query
        parts.fragment = nil
        guard let url = parts.url else { throw APIError.invalidResponse }
        var request = URLRequest(url: url, cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: timeout)
        request.httpMethod = method
        request.httpShouldHandleCookies = false
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        let matching = cookies.filter { matches($0, url: url) }
        for (key, value) in HTTPCookie.requestHeaderFields(with: matching) {
            request.setValue(value, forHTTPHeaderField: key)
        }
        return request
    }

    private func perform(_ request: URLRequest) async throws -> Data {
        let generation = sessionGeneration
        let (data, response) = try await HTTPDeadline.data(for: request, using: session)
        try Task.checkCancellation()
        guard generation == sessionGeneration else { throw CancellationError() }
        guard let response = response as? HTTPURLResponse,
              let responseURL = response.url,
              OriginRedirectDelegate.sameOrigin(responseURL, baseURL) else { throw APIError.invalidResponse }
        saveCookies(response)
        guard (200..<300).contains(response.statusCode) else {
            throw APIError.response(status: response.statusCode, data: data)
        }
        return data
    }

    private func saveCookies(_ response: HTTPURLResponse) {
        guard let url = response.url else { return }
        let headers = response.allHeaderFields.reduce(into: [String: String]()) { result, field in
            guard let name = field.key as? String else { return }
            result[name] = String(describing: field.value)
        }
        for cookie in HTTPCookie.cookies(withResponseHeaderFields: headers, for: url) {
            cookies.removeAll { $0.name == cookie.name && $0.domain == cookie.domain && $0.path == cookie.path }
            if cookie.expiresDate.map({ $0 > Date() }) ?? true { cookies.append(cookie) }
        }
    }

    private func matches(_ cookie: HTTPCookie, url: URL) -> Bool {
        guard let host = url.host?.lowercased(), cookie.expiresDate.map({ $0 > Date() }) ?? true else { return false }
        let domain = cookie.domain.lowercased().trimmingCharacters(in: CharacterSet(charactersIn: "."))
        guard host == domain || host.hasSuffix("." + domain) else { return false }
        if cookie.isSecure && url.scheme != "https" { return false }
        let path = url.path.isEmpty ? "/" : url.path
        return path == cookie.path || path.hasPrefix(cookie.path.hasSuffix("/") ? cookie.path : cookie.path + "/")
    }

    private func pathComponent(_ input: String) -> String {
        input.addingPercentEncoding(withAllowedCharacters: CharacterSet(charactersIn: "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-._~")) ?? ""
    }
}

/// URLRequest.timeoutInterval alone does not bound waitsForConnectivity. Race
/// the complete transfer against a deadline and cancel the losing child task.
/// There is exactly one network request, including for non-idempotent commands.
enum HTTPDeadline {
    static func data(for request: URLRequest, using session: URLSession) async throws -> (Data, URLResponse) {
        try await withThrowingTaskGroup(of: (Data, URLResponse).self) { group in
            group.addTask { try await session.data(for: request) }
            group.addTask {
                try await Task.sleep(nanoseconds: UInt64(max(0, request.timeoutInterval) * 1_000_000_000))
                throw URLError(.timedOut)
            }
            defer { group.cancelAll() }
            guard let response = try await group.next() else { throw CancellationError() }
            return response
        }
    }
}

/// Reject cross-origin redirects before Foundation can resend a login body or
/// session header. Never bypass certificate validation or HTTP auth challenges.
final class OriginRedirectDelegate: NSObject, URLSessionTaskDelegate, @unchecked Sendable {
    private let origin: URL

    init(origin: URL) { self.origin = origin }

    static func sameOrigin(_ lhs: URL, _ rhs: URL) -> Bool {
        func scheme(_ url: URL) -> String {
            switch url.scheme?.lowercased() {
            case "wss": return "https"
            case "ws": return "http"
            default: return url.scheme?.lowercased() ?? ""
            }
        }
        func port(_ url: URL) -> Int { url.port ?? (scheme(url) == "https" ? 443 : 80) }
        return scheme(lhs) == scheme(rhs) && lhs.host?.lowercased() == rhs.host?.lowercased() && port(lhs) == port(rhs)
    }

    func urlSession(
        _ session: URLSession, task: URLSessionTask,
        willPerformHTTPRedirection response: HTTPURLResponse,
        newRequest request: URLRequest,
        completionHandler: @escaping @Sendable (URLRequest?) -> Void
    ) {
        guard let url = request.url, Self.sameOrigin(url, origin), url.user == nil, url.password == nil else {
            completionHandler(nil)
            return
        }
        completionHandler(request)
    }
}
