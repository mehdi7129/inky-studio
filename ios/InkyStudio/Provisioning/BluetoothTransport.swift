import Foundation
import Combine
@preconcurrency import CoreBluetooth

struct BluetoothFrame: Identifiable, Equatable, Sendable {
    let id: UUID
    let name: String
    let rssi: Int?
}

enum BluetoothTransportError: Error, LocalizedError, Equatable {
    case unavailable, unauthorized, poweredOff, busy, disconnected, timeout
    case invalidFrame, unsupportedFrame, operationFailed, cancelled

    var errorDescription: String? {
        switch self {
        case .unavailable: "Le Bluetooth n’est pas disponible."
        case .unauthorized: "Autorisez le Bluetooth dans les réglages de l’app."
        case .poweredOff: "Activez le Bluetooth pour chercher le cadre."
        case .busy: "Une opération Bluetooth est déjà en cours."
        case .disconnected: "La connexion Bluetooth a été interrompue."
        case .timeout: "Le cadre n’a pas répondu à temps."
        case .invalidFrame, .unsupportedFrame: "Ce cadre utilise un protocole incompatible."
        case .operationFailed: "La communication Bluetooth a échoué."
        case .cancelled: "La connexion Bluetooth a été annulée."
        }
    }
}

/// One ordered write/read exchange. Neither advertisements nor identity bytes establish trust.
@MainActor protocol BluetoothExchanging: AnyObject {
    var maxFrameLength: Int { get }
    func connect(peripheralID: UUID) async throws -> Data
    func exchange(_ frame: Data) async throws -> Data
    func cancel()
}

@MainActor final class BluetoothTransport: NSObject, ObservableObject, BluetoothExchanging,
    @preconcurrency CBCentralManagerDelegate {
    enum State: Equatable { case idle, unavailable, scanning, connecting, connected }
    static let serviceUUID = CBUUID(string: "713b0001-8890-4cc9-a2bf-26f32c43db22")
    private static let identityUUID = CBUUID(string: "713b0002-8890-4cc9-a2bf-26f32c43db22")
    private static let streamUUID = CBUUID(string: "713b0003-8890-4cc9-a2bf-26f32c43db22")
    private static let certificate0UUID = CBUUID(string: "713b0004-8890-4cc9-a2bf-26f32c43db22")
    private static let certificate1UUID = CBUUID(string: "713b0005-8890-4cc9-a2bf-26f32c43db22")

    @Published private(set) var discoveredFrames: [BluetoothFrame] = []
    @Published private(set) var isScanning = false
    @Published private(set) var state: State = .idle
    @Published private(set) var error: String?
    // CoreBluetooth may negotiate a larger MTU after didConnect. Query the
    // current single-value limit for every exchange rather than caching 20 bytes.
    var maxFrameLength: Int {
        guard let peripheral, peripheral.state == .connected else { return 20 }
        return min(peripheral.maximumWriteValueLength(for: .withResponse),
                   peripheral.maximumWriteValueLength(for: .withoutResponse), 244)
    }
    private var initialMaxFrameLength = 20
    private(set) var lastFailure: BluetoothTransportError?
    var bluetoothStateCode: Int? { manager?.state.rawValue }
    /// Opt-in bench diagnostics: sizes/state only, never values or peer identifiers.
    var diagnosticHandler: ((String, [String: Int]) -> Void)?

    private enum Phase { case waitingPower, connecting, services, characteristics, identity, certificate0, certificate1, writing, reading }
    private var manager: CBCentralManager?
    private var wantsScan = false
    private var peripherals: [UUID: CBPeripheral] = [:]
    private var peripheral: CBPeripheral?
    private var peripheralDelegate: PeripheralCallbacks?
    private var stream: CBCharacteristic?
    private var identity: CBCharacteristic?
    private var certificate0: CBCharacteristic?
    private var certificate1: CBCharacteristic?
    private var identityAssembly = BluetoothIdentityAssembly()
    private var targetID: UUID?
    private var phase: Phase?
    private var continuation: CheckedContinuation<Data, Error>?
    private var operationID: UUID?
    private var deadline: Task<Void, Never>?
    private var generation = UUID()

    func startScan() {
        guard continuation == nil, peripheral == nil else { return }
        error = nil
        lastFailure = nil
        wantsScan = true
        ensureManager()
        updatePowerState()
    }

    func stopScan() {
        wantsScan = false
        if manager?.state == .poweredOn { manager?.stopScan() }
        isScanning = false
        if state == .scanning { state = .idle }
    }

    func connect(peripheralID: UUID) async throws -> Data {
        guard continuation == nil else { throw BluetoothTransportError.busy }
        try Task.checkCancellation()
        if peripheral != nil { retireConnection() }
        stopScan()
        error = nil
        lastFailure = nil
        state = .connecting
        targetID = peripheralID
        phase = .waitingPower
        let id = UUID()
        return try await withTaskCancellationHandler {
            try await withCheckedThrowingContinuation { pending in
                continuation = pending
                operationID = id
                armDeadline(id: id, seconds: 45)
                ensureManager()
                updatePowerState()
            }
        } onCancel: { [weak self] in
            Task { @MainActor in self?.cancelOperation(id) }
        }
    }

    func exchange(_ frame: Data) async throws -> Data {
        guard continuation == nil else { throw BluetoothTransportError.busy }
        guard state == .connected, let peripheral, let stream else { throw BluetoothTransportError.disconnected }
        guard !frame.isEmpty, frame.count <= maxFrameLength else { throw BluetoothTransportError.invalidFrame }
        try Task.checkCancellation()
        let id = UUID()
        return try await withTaskCancellationHandler {
            try await withCheckedThrowingContinuation { pending in
                continuation = pending
                operationID = id
                phase = .writing
                armDeadline(id: id, seconds: 10)
                diagnose("write_stream", byteCount: frame.count)
                peripheral.writeValue(frame, for: stream, type: .withResponse)
            }
        } onCancel: { [weak self] in
            Task { @MainActor in self?.cancelOperation(id) }
        }
    }

    func cancel() {
        stopScan()
        fail(.cancelled, display: false)
    }

    private func ensureManager() {
        if manager == nil { manager = CBCentralManager(delegate: self, queue: .main) }
    }

    private func updatePowerState() {
        guard let manager else { return }
        switch manager.state {
        case .poweredOn:
            if phase == .waitingPower, let targetID {
                guard let found = peripherals[targetID] ?? manager.retrievePeripherals(withIdentifiers: [targetID]).first else {
                    fail(.disconnected); return
                }
                peripheral = found
                let proxy = PeripheralCallbacks(owner: self, generation: generation)
                peripheralDelegate = proxy
                found.delegate = proxy
                phase = .connecting
                manager.connect(found, options: nil)
            } else if wantsScan, continuation == nil, peripheral == nil {
                manager.scanForPeripherals(withServices: [Self.serviceUUID], options: [CBCentralManagerScanOptionAllowDuplicatesKey: false])
                isScanning = true
                state = .scanning
            }
        case .unknown, .resetting: break // Bounded by the active operation's deadline.
        case .unauthorized: fail(.unauthorized)
        case .poweredOff: fail(.poweredOff)
        default: fail(.unavailable)
        }
    }

    func centralManagerDidUpdateState(_ central: CBCentralManager) {
        guard central === manager else { return }
        updatePowerState()
    }

    func centralManager(_ central: CBCentralManager, didDiscover peripheral: CBPeripheral,
                        advertisementData: [String: Any], rssi RSSI: NSNumber) {
        guard central === manager, isScanning else { return }
        guard peripherals[peripheral.identifier] != nil || peripherals.count < 32 else { return }
        peripherals[peripheral.identifier] = peripheral
        let rawName = (advertisementData[CBAdvertisementDataLocalNameKey] as? String) ?? peripheral.name ?? "Cadre Inky"
        let name = String(rawName.filter { !$0.unicodeScalars.contains(where: CharacterSet.controlCharacters.contains) }.prefix(40))
        let item = BluetoothFrame(id: peripheral.identifier, name: name.isEmpty ? "Cadre Inky" : name,
                                  rssi: RSSI.intValue == 127 ? nil : RSSI.intValue)
        if let index = discoveredFrames.firstIndex(where: { $0.id == item.id }) { discoveredFrames[index] = item }
        else { discoveredFrames.append(item) }
    }

    func centralManager(_ central: CBCentralManager, didConnect peripheral: CBPeripheral) {
        guard central === manager, peripheral === self.peripheral, phase == .connecting else { return }
        // .withResponse may include ATT long writes. Bound by the single-value
        // limit too: the protocol never accepts prepare/reliable writes or offsets.
        let maximum = min(peripheral.maximumWriteValueLength(for: .withResponse),
                          peripheral.maximumWriteValueLength(for: .withoutResponse), 244)
        guard maximum >= 20 else { fail(.unsupportedFrame); return }
        initialMaxFrameLength = maximum
        diagnose("connected")
        phase = .services
        peripheral.discoverServices([Self.serviceUUID])
    }

    func centralManager(_ central: CBCentralManager, didFailToConnect peripheral: CBPeripheral, error: Error?) {
        guard central === manager, peripheral === self.peripheral else { return }
        fail(.disconnected)
    }

    func centralManager(_ central: CBCentralManager, didDisconnectPeripheral peripheral: CBPeripheral, error: Error?) {
        guard central === manager, peripheral === self.peripheral else { return }
        fail(.disconnected)
    }

    fileprivate func discoveredServices(_ peripheral: CBPeripheral, error: Error?, generation: UUID) {
        guard accepts(peripheral, generation), phase == .services else { return }
        guard error == nil, let service = peripheral.services?.first(where: { $0.uuid == Self.serviceUUID }) else {
            fail(.unsupportedFrame); return
        }
        phase = .characteristics
        peripheral.discoverCharacteristics([Self.identityUUID, Self.streamUUID, Self.certificate0UUID, Self.certificate1UUID], for: service)
    }

    fileprivate func discoveredCharacteristics(_ peripheral: CBPeripheral, service: CBService,
                                                error: Error?, generation: UUID) {
        guard accepts(peripheral, generation), phase == .characteristics, service.uuid == Self.serviceUUID else { return }
        guard error == nil,
              let identity = service.characteristics?.first(where: { $0.uuid == Self.identityUUID }), identity.properties.contains(.read),
              let stream = service.characteristics?.first(where: { $0.uuid == Self.streamUUID }),
              stream.properties.contains(.read), stream.properties.contains(.write),
              let certificate0 = service.characteristics?.first(where: { $0.uuid == Self.certificate0UUID }), certificate0.properties.contains(.read),
              let certificate1 = service.characteristics?.first(where: { $0.uuid == Self.certificate1UUID }), certificate1.properties.contains(.read)
        else { fail(.unsupportedFrame); return }
        self.identity = identity
        self.stream = stream
        self.certificate0 = certificate0
        self.certificate1 = certificate1
        phase = .identity
        peripheral.readValue(for: identity)
    }

    fileprivate func readValue(_ peripheral: CBPeripheral, characteristic: CBCharacteristic,
                               error: Error?, generation: UUID) {
        guard accepts(peripheral, generation),
              (phase == .identity && characteristic === identity) ||
              (phase == .certificate0 && characteristic === certificate0) ||
              (phase == .certificate1 && characteristic === certificate1) ||
              (phase == .reading && characteristic === stream) else { return }
        diagnose("read_" + String(describing: phase), byteCount: characteristic.value?.count,
                 errorCode: error.map { ($0 as NSError).code })
        guard error == nil, let data = characteristic.value else { fail(.operationFailed); return }
        do {
            switch phase {
            case .identity:
                try identityAssembly.readMetadata(data)
                guard let certificate0 else { throw BluetoothTransportError.unsupportedFrame }
                phase = .certificate0
                peripheral.readValue(for: certificate0)
            case .certificate0:
                try identityAssembly.readFirstCertificatePart(data)
                guard let certificate1 else { throw BluetoothTransportError.unsupportedFrame }
                phase = .certificate1
                peripheral.readValue(for: certificate1)
            case .certificate1:
                let assembled = try identityAssembly.finish(secondCertificatePart: data)
                state = .connected
                complete(assembled)
            case .reading:
                // Read values have their own protocol cap. A response may be
                // larger than an earlier write during MTU negotiation.
                guard !data.isEmpty, data.count <= 244 else { throw BluetoothTransportError.invalidFrame }
                complete(data)
            default: break
            }
        } catch { fail(.invalidFrame) }
    }

    fileprivate func wroteValue(_ peripheral: CBPeripheral, characteristic: CBCharacteristic,
                                error: Error?, generation: UUID) {
        guard accepts(peripheral, generation), phase == .writing, characteristic === stream else { return }
        guard error == nil else { fail(.operationFailed); return }
        phase = .reading
        peripheral.readValue(for: characteristic)
    }

    private func diagnose(_ event: String, byteCount: Int? = nil, errorCode: Int? = nil) {
        guard let diagnosticHandler else { return }
        var fields = ["initial_max_frame": initialMaxFrameLength, "max_frame": maxFrameLength]
        if let byteCount { fields["byte_count"] = byteCount }
        if let errorCode { fields["error_code"] = errorCode }
        if let peripheral, peripheral.state == .connected {
            fields["current_max_with_response"] = peripheral.maximumWriteValueLength(for: .withResponse)
            fields["current_max_without_response"] = peripheral.maximumWriteValueLength(for: .withoutResponse)
        }
        diagnosticHandler(event, fields)
    }

    private func accepts(_ peripheral: CBPeripheral, _ generation: UUID) -> Bool {
        generation == self.generation && peripheral === self.peripheral && continuation != nil
    }

    private func armDeadline(id: UUID, seconds: UInt64) {
        deadline?.cancel()
        deadline = Task { [weak self] in
            do { try await Task.sleep(nanoseconds: seconds * 1_000_000_000) } catch { return }
            guard self?.operationID == id else { return }
            self?.fail(.timeout)
        }
    }

    private func cancelOperation(_ id: UUID) {
        guard operationID == id else { return }
        fail(.cancelled, display: false)
    }

    private func complete(_ data: Data) {
        let pending = continuation
        continuation = nil
        phase = nil
        operationID = nil
        deadline?.cancel()
        deadline = nil
        pending?.resume(returning: data)
    }

    private func fail(_ reason: BluetoothTransportError, display: Bool = true) {
        let pending = continuation
        continuation = nil
        operationID = nil
        deadline?.cancel()
        deadline = nil
        if display { error = reason.localizedDescription; lastFailure = reason }
        retireConnection()
        state = display ? .unavailable : .idle
        pending?.resume(throwing: reason)
    }

    private func retireConnection() {
        // Retire the manager as well as the per-connection delegate. Old callbacks
        // cannot resume a new operation, even when reconnecting to the same UUID.
        generation = UUID()
        if manager?.state == .poweredOn { manager?.stopScan() }
        manager?.delegate = nil
        peripheral?.delegate = nil
        if let peripheral, manager?.state == .poweredOn { manager?.cancelPeripheralConnection(peripheral) }
        manager = nil
        peripheral = nil
        peripheralDelegate = nil
        identity = nil
        certificate0 = nil
        certificate1 = nil
        identityAssembly = BluetoothIdentityAssembly()
        stream = nil
        phase = nil
        targetID = nil
        peripherals.removeAll()
        discoveredFrames.removeAll()
        isScanning = false
        wantsScan = false
        initialMaxFrameLength = 20
    }
}

@MainActor private final class PeripheralCallbacks: NSObject, @preconcurrency CBPeripheralDelegate {
    weak var owner: BluetoothTransport?
    let generation: UUID
    init(owner: BluetoothTransport, generation: UUID) { self.owner = owner; self.generation = generation }
    func peripheral(_ peripheral: CBPeripheral, didDiscoverServices error: Error?) {
        owner?.discoveredServices(peripheral, error: error, generation: generation)
    }
    func peripheral(_ peripheral: CBPeripheral, didDiscoverCharacteristicsFor service: CBService, error: Error?) {
        owner?.discoveredCharacteristics(peripheral, service: service, error: error, generation: generation)
    }
    func peripheral(_ peripheral: CBPeripheral, didUpdateValueFor characteristic: CBCharacteristic, error: Error?) {
        owner?.readValue(peripheral, characteristic: characteristic, error: error, generation: generation)
    }
    func peripheral(_ peripheral: CBPeripheral, didWriteValueFor characteristic: CBCharacteristic, error: Error?) {
        owner?.wroteValue(peripheral, characteristic: characteristic, error: error, generation: generation)
    }
}

/// ATT attributes cannot exceed 512 bytes. The public certificate is split over
/// two read-only attributes, each <=480 bytes; CoreBluetooth performs Read Blob
/// assembly within each value. Exact lengths prevent missing/mixed partial reads.
struct BluetoothIdentityAssembly {
    private struct Metadata: Decodable { let v: Int; let id: UUID; let cert_length: Int }
    private var metadata: Metadata?
    private var first: Data?
    mutating func readMetadata(_ data: Data) throws {
        guard metadata == nil, !data.isEmpty, data.count <= 128,
              let decoded = try? JSONDecoder().decode(Metadata.self, from: data),
              decoded.v == 1, (1...960).contains(decoded.cert_length) else { throw BluetoothTransportError.invalidFrame }
        metadata = decoded
    }
    mutating func readFirstCertificatePart(_ data: Data) throws {
        guard let metadata, first == nil, data.count == min(480, metadata.cert_length) else {
            throw BluetoothTransportError.invalidFrame
        }
        first = data
    }
    func finish(secondCertificatePart: Data) throws -> Data {
        guard let metadata, let first,
              secondCertificatePart.count == max(0, metadata.cert_length - 480) else {
            throw BluetoothTransportError.invalidFrame
        }
        return try JSONSerialization.data(withJSONObject: ["v": 1, "id": metadata.id.uuidString.lowercased(),
            "cert": (first + secondCertificatePart).base64EncodedString()])
    }
}
