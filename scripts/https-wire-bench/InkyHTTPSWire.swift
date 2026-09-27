import Foundation

/// Compiled with the production InkyAPI, redirect delegate and trust policy.
/// This harness never calls Keychain, BLE, UIKit, or an external address.
private struct Manifest: Decodable {
    let frameID: UUID
    let originalDER: String
    let expiredDER: String
    let endpoints: [String: URL]
}

private struct CaseResult: Codable {
    let name: String
    let passed: Bool
    var errorDomain: String?
    var errorCode: Int?
}

private enum WireError: Error { case assertion, missingFixture }

@main
private struct InkyHTTPSWire {
    @MainActor
    static func main() async throws {
        guard CommandLine.arguments.count == 3 else { throw WireError.missingFixture }
        let manifest = try JSONDecoder().decode(Manifest.self,
            from: Data(contentsOf: URL(fileURLWithPath: CommandLine.arguments[1])))
        let original = try Data(contentsOf: URL(fileURLWithPath: manifest.originalDER))
        let expired = try Data(contentsOf: URL(fileURLWithPath: manifest.expiredDER))
        let identity = try FrameIdentity(id: manifest.frameID,
            spkiSHA256: PinnedFrameTrust.spkiSHA256(certificateDER: original))
        let ownerID = UUID(uuidString: "11111111-2222-4333-8444-555555555555")!
        let transactionID = UUID(uuidString: "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee")!
        let password = "synthetic-wire-password"
        var results: [CaseResult] = []

        func endpoint(_ name: String) throws -> URL {
            guard let url = manifest.endpoints[name], url.host == "127.0.0.1" else {
                throw WireError.missingFixture
            }
            return url
        }
        func owner(cached: Data, identity override: FrameIdentity? = nil) -> OwnershipRecord {
            OwnershipRecord(identity: override ?? identity, certificateDER: cached,
                ownerID: ownerID, claimRequestID: UUID(), ownerToken: Data(repeating: 0x42, count: 32),
                endpoints: [], state: .claimed)
        }
        func check(_ condition: Bool) throws {
            if !condition { throw WireError.assertion }
        }
        func record(_ name: String, _ body: () async throws -> Void) async {
            do {
                try await body()
                results.append(CaseResult(name: name, passed: true))
            } catch {
                let error = error as NSError
                results.append(CaseResult(name: name, passed: false,
                    errorDomain: error.domain, errorCode: error.code))
            }
        }
        func rejects(_ body: () async throws -> Void) async throws {
            do { try await body() }
            catch { return }
            throw WireError.assertion
        }
        func firstEvent(_ client: InkyAPI) async throws -> ServerEvent? {
            let timer = Task { @MainActor in
                try? await Task.sleep(nanoseconds: 5_000_000_000)
                if !Task.isCancelled { client.stopEvents() }
            }
            defer { timer.cancel(); client.stopEvents() }
            var iterator = client.events().makeAsyncIterator()
            return try await iterator.next()
        }

        await record("expired_cache.fresh_ble_trust_rejected") {
            try await rejects {
                _ = try PinnedFrameTrust(identity: identity, certificateDER: expired)
            }
        }

        // An IP locator is intentional: the certificate has only the stable QR
        // DNS SAN. The production delegate must evaluate that name, not the IP.
        for name in ["original", "renewed", "expired_cache"] {
            let recordOwner = owner(cached: name == "expired_cache" ? expired : original)
            let url = try endpoint(name)
            let client = InkyAPI(baseURL: url, owner: recordOwner)
            await record(name + ".json_login_photo_wss") {
                let before = try await client.authStatus()
                try check(!before.authenticated && before.authRequired)
                let login = try await client.login(password: password)
                try check(login.authenticated)
                let after = try await client.authStatus()
                try check(after.authenticated)
                let png = try await client.photoData(id: "fixture")
                try check(png.starts(with: [137, 80, 78, 71, 13, 10, 26, 10]))
                let event = try await firstEvent(client)
                try check(event?.type == "hello")
            }
            await record(name + ".wifi_confirm") {
                let state = try await InkyAPI.confirmProvisionedWiFi(endpoint: url,
                    owner: recordOwner, transactionID: transactionID)
                try check(state == "committed")
            }
            client.clearSession()
        }

        let wrongPin = try FrameIdentity(id: identity.id, spkiSHA256: Data(repeating: 0, count: 32))
        for name in ["wrong_pin", "changed_key", "wrong_name", "expired", "future", "bad_signature"] {
            let recordOwner = owner(cached: original, identity: name == "wrong_pin" ? wrongPin : nil)
            let url = try endpoint(name)
            let client = InkyAPI(baseURL: url, owner: recordOwner)
            await record(name + ".login_rejected") {
                try await rejects { _ = try await client.login(password: password) }
            }
            await record(name + ".photo_rejected") {
                try await rejects { _ = try await client.photoData(id: "fixture") }
            }
            await record(name + ".wss_rejected") {
                let event = try await firstEvent(client)
                try check(event?.type == "connection_lost")
            }
            await record(name + ".wifi_confirm_rejected") {
                try await rejects {
                    _ = try await InkyAPI.confirmProvisionedWiFi(endpoint: url,
                        owner: recordOwner, transactionID: transactionID)
                }
            }
            client.clearSession()
        }

        for name in ["http", "redirect_http", "redirect_https"] {
            let url = try endpoint(name)
            let client = InkyAPI(baseURL: url, owner: owner(cached: original))
            await record(name + ".login_rejected") {
                try await rejects { _ = try await client.login(password: password) }
            }
            client.clearSession()
        }
        let http = try endpoint("http")
        await record("http.wifi_confirm_rejected") {
            try await rejects {
                _ = try await InkyAPI.confirmProvisionedWiFi(endpoint: http,
                    owner: owner(cached: original), transactionID: transactionID)
            }
        }

        let output = try JSONEncoder().encode(results)
        try output.write(to: URL(fileURLWithPath: CommandLine.arguments[2]), options: .atomic)
        print("Swift URLSession cases: \(results.filter(\.passed).count)/\(results.count) passed")
        if results.contains(where: { !$0.passed }) { exit(1) }
    }
}
