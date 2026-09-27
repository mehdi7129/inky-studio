import ImageIO
import SwiftUI
import UIKit
import UniformTypeIdentifiers

/// A camera image carries its orientation separately from its immutable pixels.
/// Only these two values cross to the photo worker; camera metadata is discarded.
struct CapturedPhoto: @unchecked Sendable {
    let image: CGImage
    let orientation: CGImagePropertyOrientation

    init?(image: UIImage) {
        guard let pixels = image.cgImage else { return nil }
        self.image = pixels
        switch image.imageOrientation {
        case .up: orientation = .up
        case .upMirrored: orientation = .upMirrored
        case .down: orientation = .down
        case .downMirrored: orientation = .downMirrored
        case .left: orientation = .left
        case .leftMirrored: orientation = .leftMirrored
        case .right: orientation = .right
        case .rightMirrored: orientation = .rightMirrored
        @unknown default: orientation = .up
        }
    }

    /// The shared ImageIO pipeline handles camera and Photos imports identically.
    /// This private file is never added to Photos and is removed after decoding.
    func prepare() throws -> PreparedPhoto {
        try Task.checkCancellation()
        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent("inky-camera-\(UUID().uuidString).jpg")
        defer { try? FileManager.default.removeItem(at: url) }
        guard let destination = CGImageDestinationCreateWithURL(
            url as CFURL, UTType.jpeg.identifier as CFString, 1, nil
        ) else { throw PhotoPipelineError.encodingFailed }
        CGImageDestinationAddImage(destination, image, [
            kCGImagePropertyOrientation: orientation.rawValue,
            kCGImageDestinationLossyCompressionQuality: 0.98,
        ] as CFDictionary)
        guard CGImageDestinationFinalize(destination) else { throw PhotoPipelineError.encodingFailed }
        try Task.checkCancellation()
        return try PhotoPipeline.decode(url: url)
    }
}

/// UIKit's still-camera UI provides capture, retake and cancellation. It neither
/// records audio nor writes the captured photo into the user's photo library.
struct CameraCaptureView: UIViewControllerRepresentable {
    let onFinish: (Result<CapturedPhoto, Error>?) -> Void

    func makeCoordinator() -> Coordinator { Coordinator(onFinish: onFinish) }

    func makeUIViewController(context: Context) -> UIImagePickerController {
        // UIImagePickerController is portrait-only and must not be subclassed.
        let controller = UIImagePickerController()
        controller.delegate = context.coordinator
        controller.sourceType = .camera
        controller.mediaTypes = [UTType.image.identifier]
        controller.cameraCaptureMode = .photo
        controller.allowsEditing = false
        controller.modalPresentationStyle = .fullScreen
        return controller
    }

    func updateUIViewController(_ controller: UIImagePickerController, context: Context) {}

    final class Coordinator: NSObject, UIImagePickerControllerDelegate, UINavigationControllerDelegate {
        private let onFinish: (Result<CapturedPhoto, Error>?) -> Void
        private var completed = false

        init(onFinish: @escaping (Result<CapturedPhoto, Error>?) -> Void) {
            self.onFinish = onFinish
        }

        func imagePickerControllerDidCancel(_ picker: UIImagePickerController) { finish(nil) }

        func imagePickerController(_ picker: UIImagePickerController,
                                   didFinishPickingMediaWithInfo info: [UIImagePickerController.InfoKey: Any]) {
            guard let image = info[.originalImage] as? UIImage,
                  let photo = CapturedPhoto(image: image) else {
                finish(.failure(PhotoPipelineError.unreadable))
                return
            }
            finish(.success(photo))
        }

        private func finish(_ result: Result<CapturedPhoto, Error>?) {
            guard !completed else { return }
            completed = true
            onFinish(result)
        }
    }
}
