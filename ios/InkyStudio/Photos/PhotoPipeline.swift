import CoreTransferable
import Foundation
import ImageIO
import UniformTypeIdentifiers

enum PhotoPipelineError: LocalizedError, Equatable {
    case unreadable
    case sourceTooLarge
    case invalidPanel
    case invalidCrop
    case encodingFailed
    case uploadTooLarge

    var errorDescription: String? {
        switch self {
        case .unreadable:
            return "Cette photo n’a pas pu être ouverte. Essayez une autre photo au format HEIC, JPEG ou PNG."
        case .sourceTooLarge:
            return "Cette photo est trop volumineuse. Choisissez une version de moins de 128 Mo."
        case .invalidPanel:
            return "Le format du cadre est indisponible. Reconnectez le cadre, puis réessayez."
        case .invalidCrop:
            return "Le cadrage n’est pas encore prêt. Réessayez dans un instant."
        case .encodingFailed:
            return "Impossible de préparer cette photo pour le cadre. Essayez une autre photo."
        case .uploadTooLarge:
            return "La photo préparée dépasse la limite de 10 Mo du cadre. Choisissez une autre photo."
        }
    }
}

/// CGImage is immutable; a decoded photo can safely move from the decoding task to the UI.
struct PreparedPhoto: @unchecked Sendable {
    let image: CGImage
    var size: CGSize { CGSize(width: image.width, height: image.height) }
}

/// Photos grants access only to the selected item. Keep our own temporary copy because
/// the transferred file's lifetime ends as soon as the importing closure returns.
struct ImportedPhotoFile: Transferable, Sendable {
    let url: URL

    static var transferRepresentation: some TransferRepresentation {
        FileRepresentation(importedContentType: .image) { received in
            try Task.checkCancellation()
            let attributes = try FileManager.default.attributesOfItem(atPath: received.file.path)
            guard let size = attributes[.size] as? NSNumber,
                  size.int64Value > 0,
                  size.int64Value <= Int64(PhotoPipeline.maximumSourceBytes) else {
                throw PhotoPipelineError.sourceTooLarge
            }
            let destination = FileManager.default.temporaryDirectory
                .appendingPathComponent("inky-import-\(UUID().uuidString)")
                .appendingPathExtension(received.file.pathExtension)
            do {
                try FileManager.default.copyItem(at: received.file, to: destination)
                try Task.checkCancellation()
                return ImportedPhotoFile(url: destination)
            } catch {
                try? FileManager.default.removeItem(at: destination)
                throw error
            }
        }
    }
}

enum PhotoPipeline {
    static let maximumSourceBytes = 128 * 1_024 * 1_024
    static let maximumPNGBytes = 10 * 1_024 * 1_024
    static let maximumDecodeDimension = 4_096

    static func validatePanel(width: Int, height: Int) throws {
        // Bound memory even if a server advertises an invalid or malicious panel size.
        guard width > 0, height > 0, width <= 4_096, height <= 4_096,
              width * height <= 4_194_304 else { throw PhotoPipelineError.invalidPanel }
    }

    static func decode(url: URL, maximumDimension: Int = maximumDecodeDimension) throws -> PreparedPhoto {
        try Task.checkCancellation()
        let fileSize = try url.resourceValues(forKeys: [.fileSizeKey]).fileSize ?? 0
        guard fileSize > 0, fileSize <= maximumSourceBytes else { throw PhotoPipelineError.sourceTooLarge }
        guard let source = CGImageSourceCreateWithURL(url as CFURL, [kCGImageSourceShouldCache: false] as CFDictionary),
              CGImageSourceGetCount(source) > 0 else { throw PhotoPipelineError.unreadable }
        let options: [CFString: Any] = [
            kCGImageSourceCreateThumbnailFromImageAlways: true,
            kCGImageSourceCreateThumbnailWithTransform: true,
            kCGImageSourceThumbnailMaxPixelSize: max(1, min(maximumDecodeDimension, maximumDimension)),
            kCGImageSourceShouldCacheImmediately: true,
            kCGImageSourceShouldAllowFloat: false,
            kCGImageSourceDecodeRequest: kCGImageSourceDecodeToSDR,
        ]
        guard let thumbnail = CGImageSourceCreateThumbnailAtIndex(source, 0, options as CFDictionary) else {
            throw PhotoPipelineError.unreadable
        }
        try Task.checkCancellation()
        // Convert Display P3 / HDR input once to an opaque, 8-bit sRGB working image.
        // A white matte keeps transparent PNGs predictable on the physical display.
        let context = try makeContext(width: thumbnail.width, height: thumbnail.height)
        context.draw(thumbnail, in: CGRect(x: 0, y: 0, width: thumbnail.width, height: thumbnail.height))
        guard let normalized = context.makeImage() else { throw PhotoPipelineError.unreadable }
        return PreparedPhoto(image: normalized)
    }

    static func encodePNG(photo: PreparedPhoto, crop: CGRect, width: Int, height: Int) throws -> Data {
        try Task.checkCancellation()
        try validatePanel(width: width, height: height)
        let imageBounds = CGRect(origin: .zero, size: photo.size)
        guard [crop.minX, crop.minY, crop.width, crop.height].allSatisfy({ $0.isFinite }),
              crop.width > 0, crop.height > 0,
              crop.minX >= 0, crop.minY >= 0,
              crop.maxX <= imageBounds.maxX + 0.001, crop.maxY <= imageBounds.maxY + 0.001,
              abs(crop.width / crop.height - CGFloat(width) / CGFloat(height)) < 0.001 else {
            throw PhotoPipelineError.invalidCrop
        }
        let context = try makeContext(width: width, height: height)
        context.interpolationQuality = .high
        let scaleX = CGFloat(width) / crop.width
        let scaleY = CGFloat(height) / crop.height
        // CGImage's top-left source rect is mapped into Quartz's bottom-left context.
        // Drawing the full image avoids rounding a fractional crop to integer pixels.
        context.draw(photo.image, in: CGRect(
            x: -crop.minX * scaleX,
            y: -(photo.size.height - crop.maxY) * scaleY,
            width: photo.size.width * scaleX,
            height: photo.size.height * scaleY
        ))
        guard let rendered = context.makeImage() else { throw PhotoPipelineError.encodingFailed }
        let buffer = NSMutableData()
        guard let destination = CGImageDestinationCreateWithData(buffer, UTType.png.identifier as CFString, 1, nil) else {
            throw PhotoPipelineError.encodingFailed
        }
        // No source EXIF/GPS metadata is copied. The Pi alone performs palette conversion.
        CGImageDestinationAddImage(destination, rendered, [kCGImagePropertyOrientation: 1] as CFDictionary)
        guard CGImageDestinationFinalize(destination) else { throw PhotoPipelineError.encodingFailed }
        try Task.checkCancellation()
        guard buffer.length <= maximumPNGBytes else { throw PhotoPipelineError.uploadTooLarge }
        return buffer as Data
    }

    private static func makeContext(width: Int, height: Int) throws -> CGContext {
        guard let colorSpace = CGColorSpace(name: CGColorSpace.sRGB),
              let context = CGContext(data: nil, width: width, height: height,
                                      bitsPerComponent: 8, bytesPerRow: width * 4,
                                      space: colorSpace,
                                      bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue) else {
            throw PhotoPipelineError.encodingFailed
        }
        context.setFillColor(CGColor(red: 1, green: 1, blue: 1, alpha: 1))
        context.fill(CGRect(x: 0, y: 0, width: width, height: height))
        return context
    }
}
