import AppKit
import CoreBluetooth

private let serviceID = CBUUID(string: "713A0001-8890-4CC9-A2BF-26F32C43DB22")
private let versionID = CBUUID(string: "713A0002-8890-4CC9-A2BF-26F32C43DB22")
private let rxID = CBUUID(string: "713A0003-8890-4CC9-A2BF-26F32C43DB22")
private let txID = CBUUID(string: "713A0004-8890-4CC9-A2BF-26F32C43DB22")

final class Bench: NSObject, NSApplicationDelegate, CBCentralManagerDelegate, CBPeripheralDelegate {
    private var central: CBCentralManager!
    private var peripheral: CBPeripheral?
    private var rx: CBCharacteristic?
    private var tx: CBCharacteristic?
    private var window: NSWindow!
    private var status: NSTextField!
    private var completed = false
    private var testIndex = 0
    private var outgoing: [Data] = []
    private var incoming: [Data] = []
    private var expected = Data()
    private var receivedCount = 0
    private var waitingForReconnect = false
    private var checkingRead = false
    private var lastFrame = Data()
    private var started = Date()
    private var writes = 0
    private let logURL: URL = {
        let args = CommandLine.arguments
        if let index = args.firstIndex(of: "--log"), index + 1 < args.count {
            return URL(fileURLWithPath: args[index + 1])
        }
        return URL(fileURLWithPath: NSTemporaryDirectory()).appendingPathComponent("inky-ble-bench-mac.jsonl")
    }()

    func applicationDidFinishLaunching(_ notification: Notification) {
        FileManager.default.createFile(atPath: logURL.path, contents: nil)
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 560, height: 180), styleMask: [.titled, .closable], backing: .buffered, defer: false)
        window.title = "Inky — banc Bluetooth"
        status = NSTextField(wrappingLabelWithString: "Test diagnostic Bluetooth. Aucune configuration Wi-Fi.")
        status.frame = NSRect(x: 24, y: 24, width: 512, height: 124)
        status.font = .systemFont(ofSize: 17)
        window.contentView?.addSubview(status)
        window.center()
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        log("started", ["protocol": 1, "authenticated": false, "timeout_seconds": 90])
        central = CBCentralManager(delegate: self, queue: .main, options: [CBCentralManagerOptionShowPowerAlertKey: true])
        DispatchQueue.main.asyncAfter(deadline: .now() + 90) { [weak self] in self?.finish(false, "timeout") }
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }

    private func log(_ event: String, _ fields: [String: Any] = [:]) {
        var body = fields
        body["event"] = event
        if let data = try? JSONSerialization.data(withJSONObject: body, options: [.sortedKeys]),
           let handle = try? FileHandle(forWritingTo: logURL) {
            handle.seekToEndOfFile()
            handle.write(data + Data([10]))
            try? handle.close()
        }
        status?.stringValue = "Banc Bluetooth Inky\n\(event)\nAucune configuration Wi-Fi ni donnée personnelle."
    }

    private func finish(_ success: Bool, _ reason: String) {
        guard !completed else { return }
        completed = true
        central?.stopScan()
        if let peripheral { central?.cancelPeripheralConnection(peripheral) }
        log(success ? "PASS" : "FAIL", ["reason": reason, "cases_completed": success ? 3 : testIndex])
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) { NSApp.terminate(nil) }
    }

    func centralManagerDidUpdateState(_ central: CBCentralManager) {
        log("central-state", ["state": central.state.rawValue])
        switch central.state {
        case .poweredOn:
            central.scanForPeripherals(withServices: [serviceID], options: [CBCentralManagerScanOptionAllowDuplicatesKey: false])
            log("scanning-specific-service")
        case .unauthorized: finish(false, "bluetooth-permission-denied")
        case .unsupported: finish(false, "bluetooth-unsupported")
        case .poweredOff: finish(false, "bluetooth-powered-off")
        default: break
        }
    }

    func centralManager(_ central: CBCentralManager, didDiscover found: CBPeripheral, advertisementData: [String: Any], rssi RSSI: NSNumber) {
        guard peripheral == nil, !completed else { return }
        peripheral = found
        found.delegate = self
        central.stopScan()
        log("discovered-specific-service")
        central.connect(found)
    }

    func centralManager(_ central: CBCentralManager, didConnect peripheral: CBPeripheral) {
        log("connected", ["max_write_with_response": peripheral.maximumWriteValueLength(for: .withResponse)])
        peripheral.discoverServices([serviceID])
    }

    func centralManager(_ central: CBCentralManager, didFailToConnect peripheral: CBPeripheral, error: Error?) {
        finish(false, "connect-failed")
    }

    func centralManager(_ central: CBCentralManager, didDisconnectPeripheral peripheral: CBPeripheral, error: Error?) {
        guard !completed else { return }
        self.peripheral = nil
        rx = nil
        tx = nil
        if waitingForReconnect {
            waitingForReconnect = false
            log("intentional-disconnect")
            central.scanForPeripherals(withServices: [serviceID])
        } else { finish(false, "unexpected-disconnect") }
    }

    func peripheral(_ peripheral: CBPeripheral, didDiscoverServices error: Error?) {
        guard error == nil, let service = peripheral.services?.first(where: { $0.uuid == serviceID }) else {
            finish(false, "service-discovery-failed"); return
        }
        peripheral.discoverCharacteristics([versionID, rxID, txID], for: service)
    }

    func peripheral(_ peripheral: CBPeripheral, didDiscoverCharacteristicsFor service: CBService, error: Error?) {
        guard error == nil, let chars = service.characteristics,
              let version = chars.first(where: { $0.uuid == versionID }),
              let input = chars.first(where: { $0.uuid == rxID }),
              let output = chars.first(where: { $0.uuid == txID }) else {
            finish(false, "characteristic-discovery-failed"); return
        }
        rx = input
        tx = output
        peripheral.readValue(for: version)
    }

    func peripheral(_ peripheral: CBPeripheral, didUpdateNotificationStateFor characteristic: CBCharacteristic, error: Error?) {
        guard error == nil, characteristic.isNotifying else { finish(false, "notify-failed"); return }
        log("notifications-enabled")
        startCase()
    }

    private func startCase() {
        guard let peripheral, let rx else { finish(false, "missing-rx"); return }
        let payloads = [Data(UUID().uuidString.utf8), Data((0..<600).map { UInt8($0 % 251) }), Data("Inky reconnect diagnostic".utf8)]
        expected = payloads[testIndex]
        incoming = []
        receivedCount = 0
        writes = 0
        let frameSize = min(20, peripheral.maximumWriteValueLength(for: .withResponse))
        guard frameSize > 8 else { finish(false, "insufficient-write-size"); return }
        let chunk = frameSize - 8
        let count = (expected.count + chunk - 1) / chunk
        outgoing = (0..<count).map { index in
            var bytes = Data([0x49, 0x4b, 1, 0, 1, UInt8(testIndex), UInt8(index), UInt8(count)])
            bytes.append(expected.subdata(in: (index * chunk)..<min((index + 1) * chunk, expected.count)))
            return bytes
        }
        if testIndex == 1 { outgoing.insert(outgoing[0], at: 1) }
        started = Date()
        log("case-start", ["case": testIndex, "payload_bytes": expected.count, "writes_planned": outgoing.count, "frame_size": frameSize])
        peripheral.writeValue(outgoing.removeFirst(), for: rx, type: .withResponse)
    }

    func peripheral(_ peripheral: CBPeripheral, didWriteValueFor characteristic: CBCharacteristic, error: Error?) {
        guard error == nil, let rx else { finish(false, "write-failed"); return }
        writes += 1
        if !outgoing.isEmpty { peripheral.writeValue(outgoing.removeFirst(), for: rx, type: .withResponse) }
    }

    func peripheral(_ peripheral: CBPeripheral, didUpdateValueFor characteristic: CBCharacteristic, error: Error?) {
        guard error == nil, let value = characteristic.value else { finish(false, "read-or-notify-failed"); return }
        if characteristic.uuid == versionID {
            guard value == Data("INKY-BENCH/1".utf8), let tx else { finish(false, "protocol-version-mismatch"); return }
            log("version-read-pass")
            peripheral.setNotifyValue(true, for: tx)
            return
        }
        guard characteristic.uuid == txID else { return }
        if checkingRead {
            guard value == lastFrame else { finish(false, "response-readback-mismatch"); return }
            log("response-readback-pass")
            finish(true, "version-echo-fragmentation-duplicate-reconnect-readback")
            return
        }
        let bytes = [UInt8](value)
        guard bytes.count > 8, bytes[0] == 0x49, bytes[1] == 0x4b, bytes[2] == 1,
              bytes[3] == 0, bytes[4] == 1, bytes[5] == UInt8(testIndex),
              bytes[7] > 0, bytes[7] <= 64, bytes[6] < bytes[7] else {
            finish(false, "response-header-mismatch"); return
        }
        let index = Int(bytes[6])
        let count = Int(bytes[7])
        let body = value.subdata(in: 8..<value.count)
        if index < incoming.count {
            if incoming[index] != body { finish(false, "conflicting-notification") }
            return
        }
        guard index == incoming.count, receivedCount == 0 || receivedCount == count else {
            finish(false, "out-of-order-notification"); return
        }
        receivedCount = count
        incoming.append(body)
        lastFrame = value
        if incoming.count == count {
            guard incoming.reduce(Data(), +) == expected else { finish(false, "echo-content-mismatch"); return }
            log("case-pass", ["case": testIndex, "payload_bytes": expected.count, "notifications": count, "writes_acknowledged": writes, "elapsed_ms": Int(Date().timeIntervalSince(started) * 1000)])
            if testIndex == 0 {
                testIndex = 1
                startCase()
            } else if testIndex == 1 {
                testIndex = 2
                waitingForReconnect = true
                central.cancelPeripheralConnection(peripheral)
            } else {
                checkingRead = true
                if let tx { peripheral.readValue(for: tx) }
            }
        }
    }
}

let application = NSApplication.shared
let bench = Bench()
application.delegate = bench
application.setActivationPolicy(.regular)
application.run()
