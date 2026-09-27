import CoreGraphics
import ImageIO
import UniformTypeIdentifiers
import XCTest
@testable import InkyStudio

final class PhotoPipelineTests: XCTestCase {
    func testPortraitPhotoFillsLandscapePanelWithoutStretching() {
        let crop = CropGeometry(sourceSize: CGSize(width: 3_000, height: 4_000),
                                viewportSize: CGSize(width: 350, height: 210))
        XCTAssertEqual(crop.sourceRect.width, 3_000, accuracy: 0.001)
        XCTAssertEqual(crop.sourceRect.height, 1_800, accuracy: 0.001)
        XCTAssertEqual(crop.sourceRect.minY, 1_100, accuracy: 0.001)
        XCTAssertEqual(crop.sourceRect.width / crop.sourceRect.height, 5.0 / 3.0, accuracy: 0.001)
    }

    func testPanAndZoomNeverExposeAnEmptyArea() {
        let source = CGSize(width: 4_032, height: 3_024)
        for zoom: CGFloat in [1, 1.3, 2, 4, 100] {
            for x: CGFloat in [-100_000, 0, 100_000] {
                for y: CGFloat in [-100_000, 0, 100_000] {
                    let crop = CropGeometry(sourceSize: source,
                                            viewportSize: CGSize(width: 333, height: 199.8),
                                            zoom: zoom, offset: CGSize(width: x, height: y))
                    XCTAssertGreaterThanOrEqual(crop.sourceRect.minX, 0)
                    XCTAssertGreaterThanOrEqual(crop.sourceRect.minY, 0)
                    XCTAssertLessThanOrEqual(crop.sourceRect.maxX, source.width + 0.001)
                    XCTAssertLessThanOrEqual(crop.sourceRect.maxY, source.height + 0.001)
                    XCTAssertEqual(crop.sourceRect.width / crop.sourceRect.height, 5.0 / 3.0, accuracy: 0.001)
                }
            }
        }
    }

    func testDraggingImageRightSelectsPixelsFurtherLeft() {
        let crop = CropGeometry(sourceSize: CGSize(width: 800, height: 480),
                                viewportSize: CGSize(width: 400, height: 240),
                                zoom: 2, offset: CGSize(width: 100, height: 0))
        XCTAssertEqual(crop.sourceRect.minX, 100, accuracy: 0.001)
        XCTAssertEqual(crop.sourceRect.minY, 120, accuracy: 0.001)
    }

    func testInvalidGeometryAndUnboundedZoomAreSanitized() {
        XCTAssertFalse(CropGeometry(sourceSize: .zero, viewportSize: CGSize(width: 320, height: 200)).isValid)
        XCTAssertEqual(CropGeometry(sourceSize: .zero, viewportSize: .zero).sourceRect, .zero)
        let crop = CropGeometry(sourceSize: CGSize(width: 800, height: 480),
                                viewportSize: CGSize(width: 400, height: 240),
                                zoom: .infinity, offset: CGSize(width: CGFloat.nan, height: CGFloat.infinity))
        XCTAssertEqual(crop.zoom, 1)
        XCTAssertEqual(crop.clampedOffset, .zero)
    }

    func testViewportSupportsPortraitPanels() {
        let viewport = CropGeometry.viewport(in: CGSize(width: 390, height: 400),
                                             panel: CGSize(width: 480, height: 800))
        XCTAssertEqual(viewport.width / viewport.height, 0.6, accuracy: 0.001)
        XCTAssertLessThanOrEqual(viewport.width, 366)
        XCTAssertLessThanOrEqual(viewport.height, 376)
    }

    func testImageIOAppliesEXIFOrientationBeforeCropping() throws {
        let url = try fixture(type: .jpeg, orientation: 6)
        defer { try? FileManager.default.removeItem(at: url) }
        let photo = try PhotoPipeline.decode(url: url)
        XCTAssertEqual(photo.image.width, 40)
        XCTAssertEqual(photo.image.height, 80)
        // EXIF 6 rotates clockwise: the original bottom-left blue becomes top-left.
        let topLeft = try pixel(photo.image, x: 10, y: 10)
        XCTAssertGreaterThan(topLeft.blue, 180)
        XCTAssertLessThan(topLeft.red, 60)
        let topRight = try pixel(photo.image, x: 30, y: 10)
        XCTAssertGreaterThan(topRight.red, 180)
        XCTAssertLessThan(topRight.blue, 60)
    }

    func testCropUsesTopLeftCoordinatesAndExportsExactPanelPixels() throws {
        let photo = PreparedPhoto(image: try quadrantImage())
        let data = try PhotoPipeline.encodePNG(photo: photo,
                                               crop: CGRect(x: 0, y: 20, width: 40, height: 20),
                                               width: 800, height: 400)
        XCTAssertLessThanOrEqual(data.count, PhotoPipeline.maximumPNGBytes)
        let source = try XCTUnwrap(CGImageSourceCreateWithData(data as CFData, nil))
        XCTAssertEqual(CGImageSourceGetType(source) as String?, UTType.png.identifier)
        let result = try XCTUnwrap(CGImageSourceCreateImageAtIndex(source, 0, nil))
        XCTAssertEqual(result.width, 800)
        XCTAssertEqual(result.height, 400)
        XCTAssertEqual(result.bitsPerComponent, 8)
        XCTAssertEqual(result.colorSpace?.name, CGColorSpace.sRGB)
        let center = try pixel(result, x: 400, y: 200)
        XCTAssertGreaterThan(center.blue, 240)
        XCTAssertLessThan(center.red, 15)
        XCTAssertLessThan(center.green, 15)
    }

    func testExportDoesNotCopyPrivateSourceMetadata() throws {
        let url = try fixture(type: .jpeg, orientation: 1)
        defer { try? FileManager.default.removeItem(at: url) }
        let photo = try PhotoPipeline.decode(url: url)
        let data = try PhotoPipeline.encodePNG(photo: photo,
                                               crop: CGRect(origin: .zero, size: photo.size),
                                               width: 800, height: 400)
        let source = try XCTUnwrap(CGImageSourceCreateWithData(data as CFData, nil))
        let properties = try XCTUnwrap(CGImageSourceCopyPropertiesAtIndex(source, 0, nil) as? [CFString: Any])
        XCTAssertNil(properties[kCGImagePropertyGPSDictionary])
        // ImageIO may write its own harmless dimensions/color-space EXIF entries.
        let exif = properties[kCGImagePropertyExifDictionary] as? [CFString: Any]
        XCTAssertNil(exif?[kCGImagePropertyExifDateTimeOriginal])
        XCTAssertNil(exif?[kCGImagePropertyExifUserComment])
    }

    func testNativeHEICImportAndBoundedDownsample() throws {
        let available = CGImageDestinationCopyTypeIdentifiers() as! [String]
        guard available.contains(UTType.heic.identifier) else { throw XCTSkip("HEIC encoding unavailable on this runner") }
        let url = try fixture(type: .heic, orientation: 1)
        defer { try? FileManager.default.removeItem(at: url) }
        let photo = try PhotoPipeline.decode(url: url, maximumDimension: 32)
        XCTAssertEqual(max(photo.image.width, photo.image.height), 32)
        XCTAssertEqual(photo.image.width, photo.image.height * 2)
        XCTAssertEqual(photo.image.bitsPerComponent, 8)
        XCTAssertEqual(photo.image.colorSpace?.name, CGColorSpace.sRGB)
    }

    func testInvalidInputAndPanelAreRejectedBeforeAllocatingOutput() throws {
        for size in [(-1, 480), (800, 0), (Int.max, 1), (4_096, 4_096)] {
            XCTAssertThrowsError(try PhotoPipeline.validatePanel(width: size.0, height: size.1)) { error in
                XCTAssertEqual(error as? PhotoPipelineError, .invalidPanel)
            }
        }
        let url = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: url) }
        try Data("not an image".utf8).write(to: url)
        XCTAssertThrowsError(try PhotoPipeline.decode(url: url)) { error in
            XCTAssertEqual(error as? PhotoPipelineError, .unreadable)
        }
        let photo = PreparedPhoto(image: try quadrantImage())
        XCTAssertThrowsError(try PhotoPipeline.encodePNG(photo: photo,
                                                        crop: CGRect(x: -1, y: 0, width: 80, height: 40),
                                                        width: 800, height: 400)) { error in
            XCTAssertEqual(error as? PhotoPipelineError, .invalidCrop)
        }
    }

    func testOversizedPNGIsRejectedWithoutReducingResolutionOrColor() throws {
        let width = 2_048, height = 2_048
        var random: UInt32 = 0x54C3_927B
        var bytes = [UInt8](repeating: 255, count: width * height * 4)
        for index in 0..<(width * height) {
            random ^= random << 13
            random ^= random >> 17
            random ^= random << 5
            bytes[index * 4] = UInt8(truncatingIfNeeded: random)
            bytes[index * 4 + 1] = UInt8(truncatingIfNeeded: random >> 8)
            bytes[index * 4 + 2] = UInt8(truncatingIfNeeded: random >> 16)
        }
        let provider = try XCTUnwrap(CGDataProvider(data: Data(bytes) as CFData))
        let image = try XCTUnwrap(CGImage(width: width, height: height, bitsPerComponent: 8, bitsPerPixel: 32,
                                          bytesPerRow: width * 4, space: CGColorSpace(name: CGColorSpace.sRGB)!,
                                          bitmapInfo: CGBitmapInfo(rawValue: CGImageAlphaInfo.noneSkipLast.rawValue),
                                          provider: provider, decode: nil, shouldInterpolate: false, intent: .defaultIntent))
        XCTAssertThrowsError(try PhotoPipeline.encodePNG(photo: PreparedPhoto(image: image),
                                                        crop: CGRect(x: 0, y: 0, width: width, height: height),
                                                        width: width, height: height)) { error in
            XCTAssertEqual(error as? PhotoPipelineError, .uploadTooLarge)
        }
    }

    private func fixture(type: UTType, orientation: Int) throws -> URL {
        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent("inky-test-\(UUID().uuidString)")
            .appendingPathExtension(type.preferredFilenameExtension ?? "img")
        let destination = try XCTUnwrap(CGImageDestinationCreateWithURL(url as CFURL, type.identifier as CFString, 1, nil))
        CGImageDestinationAddImage(destination, try quadrantImage(), [
            kCGImagePropertyOrientation: orientation,
            kCGImageDestinationLossyCompressionQuality: 1,
            kCGImagePropertyGPSDictionary: [
                kCGImagePropertyGPSLatitude: 12.3, kCGImagePropertyGPSLatitudeRef: "N",
                kCGImagePropertyGPSLongitude: 45.6, kCGImagePropertyGPSLongitudeRef: "E",
            ],
            kCGImagePropertyExifDictionary: [
                kCGImagePropertyExifDateTimeOriginal: "2000:01:01 12:00:00",
                kCGImagePropertyExifUserComment: "inky-private-fixture",
            ],
        ] as CFDictionary)
        XCTAssertTrue(CGImageDestinationFinalize(destination))
        return url
    }

    private func quadrantImage() throws -> CGImage {
        let width = 80, height = 40
        var bytes = [UInt8](repeating: 255, count: width * height * 4)
        for y in 0..<height {
            for x in 0..<width {
                let color: [UInt8]
                switch (x < width / 2, y < height / 2) {
                case (true, true): color = [255, 0, 0]
                case (false, true): color = [0, 255, 0]
                case (true, false): color = [0, 0, 255]
                case (false, false): color = [255, 255, 0]
                }
                let start = (y * width + x) * 4
                for channel in 0..<3 { bytes[start + channel] = color[channel] }
            }
        }
        let provider = try XCTUnwrap(CGDataProvider(data: Data(bytes) as CFData))
        return try XCTUnwrap(CGImage(width: width, height: height, bitsPerComponent: 8, bitsPerPixel: 32,
                                     bytesPerRow: width * 4, space: CGColorSpace(name: CGColorSpace.sRGB)!,
                                     bitmapInfo: CGBitmapInfo(rawValue: CGImageAlphaInfo.noneSkipLast.rawValue),
                                     provider: provider, decode: nil, shouldInterpolate: false, intent: .defaultIntent))
    }

    private func pixel(_ image: CGImage, x: Int, y: Int) throws -> (red: UInt8, green: UInt8, blue: UInt8) {
        let context = try XCTUnwrap(CGContext(data: nil, width: image.width, height: image.height,
                                              bitsPerComponent: 8, bytesPerRow: image.width * 4,
                                              space: CGColorSpace(name: CGColorSpace.sRGB)!,
                                              bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue))
        context.draw(image, in: CGRect(x: 0, y: 0, width: image.width, height: image.height))
        let bytes = try XCTUnwrap(context.data).assumingMemoryBound(to: UInt8.self)
        let offset = (y * image.width + x) * 4
        return (bytes[offset], bytes[offset + 1], bytes[offset + 2])
    }
}
