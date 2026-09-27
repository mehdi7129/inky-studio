import SwiftUI
import AVFoundation

enum QRScannerFailure: Error, LocalizedError, Sendable {
    case permissionDenied, unavailable
    var errorDescription: String? {
        switch self {
        case .permissionDenied: return "Autorisez la caméra dans les réglages iOS pour scanner le QR du cadre."
        case .unavailable: return "La caméra n’est pas disponible. Réessayez sur votre iPhone."
        }
    }
}

struct QRScannerView: UIViewControllerRepresentable {
    let onResult: (Result<String, QRScannerFailure>) -> Void
    func makeUIViewController(context: Context) -> QRScannerController {
        QRScannerController(onResult: onResult)
    }
    func updateUIViewController(_ controller: QRScannerController, context: Context) {}
    static func dismantleUIViewController(_ controller: QRScannerController, coordinator: ()) { controller.stop() }
}

@MainActor
final class QRScannerController: UIViewController {
    private let capture = QRCaptureSession()
    private var preview: AVCaptureVideoPreviewLayer?
    private var completed = false
    private let onResult: (Result<String, QRScannerFailure>) -> Void

    init(onResult: @escaping (Result<String, QRScannerFailure>) -> Void) {
        self.onResult = onResult
        super.init(nibName: nil, bundle: nil)
    }
    required init?(coder: NSCoder) { nil }

    override func viewDidLoad() {
        super.viewDidLoad()
        view.backgroundColor = .black
        let layer = AVCaptureVideoPreviewLayer(session: capture.session)
        layer.videoGravity = .resizeAspectFill
        view.layer.addSublayer(layer)
        preview = layer
        switch AVCaptureDevice.authorizationStatus(for: .video) {
        case .authorized: start()
        case .notDetermined:
            AVCaptureDevice.requestAccess(for: .video) { [weak self] granted in
                Task { @MainActor in
                    if granted { self?.start() } else { self?.finish(.failure(.permissionDenied)) }
                }
            }
        default: finish(.failure(.permissionDenied))
        }
    }
    override func viewDidLayoutSubviews() { super.viewDidLayoutSubviews(); preview?.frame = view.bounds }
    func stop() { completed = true; capture.stop() }

    private func start() {
        guard !completed else { return }
        capture.start(onCode: { [weak self] text in
            Task { @MainActor in self?.finish(.success(text)) }
        }, onError: { [weak self] error in
            Task { @MainActor in self?.finish(.failure(error)) }
        })
    }
    private func finish(_ result: Result<String, QRScannerFailure>) {
        guard !completed else { return }
        completed = true
        capture.stop()
        onResult(result)
    }
}

/// AVCapture's configuration and running state are confined to this serial queue.
/// The preview layer only references its immutable session from the main thread.
private final class QRCaptureSession: @unchecked Sendable {
    let session = AVCaptureSession()
    private let queue = DispatchQueue(label: "fr.mehdiguiard.inkystudio.qr-camera")
    private var metadataDelegate: QRMetadataDelegate?

    func start(onCode: @escaping @Sendable (String) -> Void,
               onError: @escaping @Sendable (QRScannerFailure) -> Void) {
        queue.async { [self] in
            guard session.inputs.isEmpty,
                  let camera = AVCaptureDevice.default(for: .video),
                  let input = try? AVCaptureDeviceInput(device: camera) else { onError(.unavailable); return }
            session.beginConfiguration()
            let output = AVCaptureMetadataOutput()
            guard session.canAddInput(input), session.canAddOutput(output) else {
                session.commitConfiguration()
                onError(.unavailable)
                return
            }
            session.addInput(input)
            session.addOutput(output)
            guard output.availableMetadataObjectTypes.contains(.qr) else {
                session.commitConfiguration()
                onError(.unavailable)
                return
            }
            let delegate = QRMetadataDelegate(onCode: onCode)
            metadataDelegate = delegate
            output.setMetadataObjectsDelegate(delegate, queue: queue)
            output.metadataObjectTypes = [.qr]
            session.commitConfiguration()
            session.startRunning()
        }
    }
    func stop() { queue.async { [self] in if session.isRunning { session.stopRunning() } } }
}

private final class QRMetadataDelegate: NSObject, AVCaptureMetadataOutputObjectsDelegate {
    private let onCode: @Sendable (String) -> Void
    private var delivered = false
    init(onCode: @escaping @Sendable (String) -> Void) { self.onCode = onCode }
    func metadataOutput(_ output: AVCaptureMetadataOutput, didOutput metadataObjects: [AVMetadataObject],
                        from connection: AVCaptureConnection) {
        guard !delivered, let value = metadataObjects.compactMap({ ($0 as? AVMetadataMachineReadableCodeObject)?.stringValue }).first else { return }
        delivered = true
        onCode(value)
    }
}
