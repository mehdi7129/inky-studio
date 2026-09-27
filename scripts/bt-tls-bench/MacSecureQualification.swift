import AppKit
import CoreBluetooth
import Foundation

/// Synthetic hardware qualification. Trust comes from a public test file copied
/// over known SSH, not from a scanned physical QR. No ownership/Wi-Fi commands.
@MainActor private final class CountingTransport: BluetoothExchanging {
    let base = BluetoothTransport()
    var exchanges = 0
    var maxFrameLength: Int { base.maxFrameLength }
    func connect(peripheralID: UUID) async throws -> Data { try await base.connect(peripheralID: peripheralID) }
    func exchange(_ frame: Data) async throws -> Data { exchanges += 1; return try await base.exchange(frame) }
    func cancel() { base.cancel() }
}

@MainActor private final class QualificationApp: NSObject, NSApplicationDelegate {
    let transport = CountingTransport()
    lazy var channel = SecureBluetoothChannel(transport: transport)
    var task: Task<Void, Never>?
    var timeout: Task<Void, Never>?
    var window: NSWindow!
    var label: NSTextField!
    var logURL: URL?
    var completed = false
    let started = Date()

    func applicationDidFinishLaunching(_ notification: Notification) {
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 580, height: 180),
                          styleMask: [.titled, .closable], backing: .buffered, defer: false)
        window.title = "Inky — qualification Bluetooth sécurisé"
        label = NSTextField(wrappingLabelWithString: "Banc synthétique TLS 1.3. Aucune configuration Wi-Fi.")
        label.frame = NSRect(x: 24, y: 24, width: 532, height: 124)
        label.font = .systemFont(ofSize: 17)
        window.contentView?.addSubview(label)
        window.center(); window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        task = Task {
            do { try await run(); finish(success: true, category: "complete") }
            catch {
                var fields: [String: Any] = ["domain": (error as NSError).domain, "code": (error as NSError).code]
                if let transportError = error as? BluetoothTransportError { fields["reason"] = String(describing: transportError) }
                if let channelError = error as? SecureBluetoothError { fields["reason"] = String(describing: channelError) }
                log("failure_detail", fields)
                finish(success: false, category: String(reflecting: type(of: error)))
            }
        }
        timeout = Task {
            do { try await Task.sleep(nanoseconds: 360_000_000_000) } catch { return }
            finish(success: false, category: "overall_timeout")
        }
    }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
    func applicationWillTerminate(_ notification: Notification) { task?.cancel(); channel.disconnect() }

    private func run() async throws {
        func argument(_ name: String) throws -> String {
            let args = CommandLine.arguments
            guard let i = args.firstIndex(of: name), i + 1 < args.count else { throw SecureBluetoothError.invalidIdentity }
            return args[i + 1]
        }
        logURL = URL(fileURLWithPath: try argument("--log"))
        guard FileManager.default.createFile(atPath: logURL!.path, contents: nil,
                                              attributes: [.posixPermissions: 0o600]) else { throw SecureBluetoothError.invalidIdentity }
        let publicData = try Data(contentsOf: URL(fileURLWithPath: argument("--trust")))
        struct PublicTrust: Decodable { let id: UUID; let k: String }
        guard publicData.count <= 512 else { throw SecureBluetoothError.invalidIdentity }
        let publicTrust = try JSONDecoder().decode(PublicTrust.self, from: publicData)
        guard publicTrust.k.utf8.count == 64,
              publicTrust.k.utf8.allSatisfy({ (48...57).contains($0) || (97...102).contains($0) }) else {
            throw SecureBluetoothError.invalidIdentity
        }
        let hex = Array(publicTrust.k)
        let pin = Data(stride(from: 0, to: 64, by: 2).compactMap { UInt8(String(hex[$0...($0 + 1)]), radix: 16) })
        let identity = try FrameIdentity(id: publicTrust.id, spkiSHA256: pin)
        log("started", ["protocol": 1, "tls": "1.3", "trust_source": "known_ssh_public_test_file", "physical_qr_validated": false])
        transport.base.diagnosticHandler = { [weak self] phase, metadata in
            self?.log("transport_" + phase, metadata)
        }
        transport.base.startScan()
        let permissionDeadline = Date().addingTimeInterval(180)
        var scanDeadline: Date?
        var nextScanReport = Date()
        while transport.base.discoveredFrames.isEmpty {
            if Date() >= nextScanReport {
                logScanState()
                nextScanReport = Date().addingTimeInterval(5)
            }
            if transport.base.isScanning, scanDeadline == nil { scanDeadline = Date().addingTimeInterval(30) }
            if let scanDeadline {
                guard Date() < scanDeadline else { logScanState(); throw BluetoothTransportError.timeout }
            } else {
                guard Date() < permissionDeadline else { logScanState(); throw BluetoothTransportError.timeout }
            }
            if transport.base.state == .unavailable { logScanState(); throw transport.base.lastFailure ?? BluetoothTransportError.unavailable }
            try await Task.sleep(nanoseconds: 100_000_000)
        }
        logScanState()
        try await Task.sleep(nanoseconds: 500_000_000)
        let candidates = transport.base.discoveredFrames
        transport.base.stopScan()
        var selected: UUID?
        struct PublicIdentity: Decodable { let id: UUID }
        for candidate in candidates {
            let data = try await transport.connect(peripheralID: candidate.id)
            let advertised = try? JSONDecoder().decode(PublicIdentity.self, from: data)
            transport.cancel()
            if advertised?.id == identity.id { selected = candidate.id; break }
        }
        guard let peripheral = selected else { throw SecureBluetoothError.invalidIdentity }
        log("selected_expected_test_identity", ["candidate_count": candidates.count])

        let echo = String(repeating: "inky", count: 150)
        let command = try JSONSerialization.data(withJSONObject: ["echo": echo])
        func assertEcho(_ reply: Data) throws {
            guard let value = try JSONSerialization.jsonObject(with: reply) as? [String: String],
                  value == ["echo": echo] else { throw SecureBluetoothError.invalidMessage }
        }
        var began = Date()
        _ = try await channel.connect(peripheralID: peripheral, identity: identity)
        log("handshake_pass", ["duration_ms": elapsed(began), "max_gatt_value": transport.maxFrameLength])
        began = Date()
        try assertEcho(await channel.request(command))
        log("echo_pass", ["synthetic_payload_bytes": 600, "duration_ms": elapsed(began)])
        channel.disconnect()

        var wrongPin = pin
        wrongPin[wrongPin.startIndex] ^= 1
        let wrongIdentity = try FrameIdentity(id: identity.id, spkiSHA256: wrongPin)
        let before = transport.exchanges
        do {
            _ = try await channel.connect(peripheralID: peripheral, identity: wrongIdentity)
            throw SecureBluetoothError.invalidIdentity
        } catch FrameIdentityError.pinMismatch {
            guard transport.exchanges == before else { throw SecureBluetoothError.invalidRecord }
            log("wrong_pin_rejected", ["gatt_writes": 0, "application_payload_sent": false])
        }
        channel.disconnect()

        began = Date()
        _ = try await channel.connect(peripheralID: peripheral, identity: identity)
        try assertEcho(await channel.request(command))
        log("reconnect_new_tls_pass", ["duration_ms": elapsed(began), "synthetic_payload_bytes": 600])
        channel.disconnect()
    }
    private func logScanState() {
        var fields: [String: Any] = ["state": String(describing: transport.base.state),
            "is_scanning": transport.base.isScanning, "frames": transport.base.discoveredFrames.count,
            "authorization": CBManager.authorization.rawValue, "main_thread": Thread.isMainThread]
        if let state = transport.base.bluetoothStateCode { fields["central_state"] = state }
        if let failure = transport.base.lastFailure { fields["last_failure"] = String(describing: failure) }
        log("scan_state", fields)
    }
    private func elapsed(_ start: Date) -> Int { Int(Date().timeIntervalSince(start) * 1000) }
    private func log(_ event: String, _ fields: [String: Any] = [:]) {
        var record = fields
        record["event"] = event
        record["elapsed_ms"] = elapsed(started)
        if let logURL, let encoded = try? JSONSerialization.data(withJSONObject: record, options: [.sortedKeys]),
           let handle = try? FileHandle(forWritingTo: logURL) {
            defer { try? handle.close() }
            try? handle.seekToEnd()
            try? handle.write(contentsOf: encoded + Data([10]))
        }
        label.stringValue = "Banc Bluetooth sécurisé Inky\n\(event)\nPhotos, Wi-Fi et données personnelles inchangés."
    }
    private func finish(success: Bool, category: String) {
        guard !completed else { return }
        completed = true
        timeout?.cancel(); task?.cancel(); channel.disconnect()
        log(success ? "PASS" : "FAIL", ["category": category, "gatt_exchanges": transport.exchanges,
                                      "synthetic": true, "wifi_modified": false])
        Task { try? await Task.sleep(nanoseconds: 500_000_000); NSApp.terminate(nil) }
    }
}

@main private struct SecureQualificationMain {
    @MainActor static func main() {
        let app = NSApplication.shared
        let delegate = QualificationApp()
        app.delegate = delegate
        app.setActivationPolicy(.regular)
        app.run()
        withExtendedLifetime(delegate) {}
    }
}
