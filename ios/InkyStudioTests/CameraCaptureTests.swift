import CoreGraphics
import ImageIO
import UIKit
import UniformTypeIdentifiers
import XCTest
@testable import InkyStudio

final class CameraCaptureTests: XCTestCase {
    func testCameraCaptureNormalizesAllEightOrientationsBeforeCropping() throws {
        // Expected positions are specified from the viewer's perspective, rather
        // than deriving the answer with the production orientation conversion.
        // The non-square image also detects missing quarter-turn rotations.
        let cases: [(UIImage.Orientation, Int, Int, [RGB])] = [
            (.up, 160, 80, [.red, .green, .blue, .yellow]),
            (.upMirrored, 160, 80, [.green, .red, .yellow, .blue]),
            (.down, 160, 80, [.yellow, .blue, .green, .red]),
            (.downMirrored, 160, 80, [.blue, .yellow, .red, .green]),
            (.left, 80, 160, [.green, .yellow, .red, .blue]),
            (.leftMirrored, 80, 160, [.red, .blue, .green, .yellow]),
            (.right, 80, 160, [.blue, .red, .yellow, .green]),
            (.rightMirrored, 80, 160, [.yellow, .green, .blue, .red]),
        ]
        let source = try quadrantImage(width: 160, height: 80)
        for (orientation, width, height, quadrants) in cases {
            // UIImage.scale must not reduce the resolution to UIKit point sizes.
            let image = UIImage(cgImage: source, scale: 2, orientation: orientation)
            let capture = try XCTUnwrap(CapturedPhoto(image: image))
            let prepared = try capture.prepare()
            let name = "UIImage orientation \(orientation.rawValue)"
            XCTAssertEqual(prepared.image.width, width, name)
            XCTAssertEqual(prepared.image.height, height, name)
            XCTAssertEqual(prepared.image.bitsPerComponent, 8, name)
            XCTAssertEqual(prepared.image.colorSpace?.name, CGColorSpace.sRGB, name)
            let positions = [
                (width / 4, height / 4), (width * 3 / 4, height / 4),
                (width / 4, height * 3 / 4), (width * 3 / 4, height * 3 / 4),
            ]
            for (position, expected) in zip(positions, quadrants) {
                let actual = try pixel(prepared.image, x: position.0, y: position.1)
                assertColor(actual, equals: expected, message: "\(name), pixel \(position)")
            }
        }
    }

    func testCameraExportDoesNotCarryPrivateMetadataAndIsAlreadyUpright() throws {
        let sourceData = NSMutableData()
        let destination = try XCTUnwrap(CGImageDestinationCreateWithData(
            sourceData, UTType.jpeg.identifier as CFString, 1, nil
        ))
        CGImageDestinationAddImage(destination, try quadrantImage(width: 160, height: 80), [
            kCGImagePropertyOrientation: 6,
            kCGImageDestinationLossyCompressionQuality: 1,
            kCGImagePropertyGPSDictionary: [
                kCGImagePropertyGPSLatitude: 48.8,
                kCGImagePropertyGPSLatitudeRef: "N",
                kCGImagePropertyGPSLongitude: 2.3,
                kCGImagePropertyGPSLongitudeRef: "E",
            ],
            kCGImagePropertyExifDictionary: [
                kCGImagePropertyExifDateTimeOriginal: "2000:01:01 12:34:56",
                kCGImagePropertyExifUserComment: "private-camera-fixture",
            ],
        ] as CFDictionary)
        XCTAssertTrue(CGImageDestinationFinalize(destination))
        let originalSource = try XCTUnwrap(CGImageSourceCreateWithData(sourceData, nil))
        let originalProperties = try XCTUnwrap(
            CGImageSourceCopyPropertiesAtIndex(originalSource, 0, nil) as? [CFString: Any]
        )
        XCTAssertNotNil(originalProperties[kCGImagePropertyGPSDictionary])
        let originalEXIF = try XCTUnwrap(originalProperties[kCGImagePropertyExifDictionary] as? [CFString: Any])
        XCTAssertNotNil(originalEXIF[kCGImagePropertyExifDateTimeOriginal])
        XCTAssertNotNil(originalEXIF[kCGImagePropertyExifUserComment])

        let image = try XCTUnwrap(UIImage(data: sourceData as Data))
        let prepared = try XCTUnwrap(CapturedPhoto(image: image)).prepare()
        let png = try PhotoPipeline.encodePNG(
            photo: prepared, crop: CGRect(origin: .zero, size: prepared.size),
            width: 400, height: 800
        )
        let outputSource = try XCTUnwrap(CGImageSourceCreateWithData(png as CFData, nil))
        XCTAssertEqual(CGImageSourceGetType(outputSource) as String?, UTType.png.identifier)
        let properties = try XCTUnwrap(
            CGImageSourceCopyPropertiesAtIndex(outputSource, 0, nil) as? [CFString: Any]
        )
        XCTAssertNil(properties[kCGImagePropertyGPSDictionary])
        // ImageIO may write harmless EXIF color-space/dimension entries of its own.
        let exif = properties[kCGImagePropertyExifDictionary] as? [CFString: Any]
        XCTAssertNil(exif?[kCGImagePropertyExifDateTimeOriginal])
        XCTAssertNil(exif?[kCGImagePropertyExifUserComment])
        XCTAssertEqual((properties[kCGImagePropertyOrientation] as? NSNumber)?.intValue ?? 1, 1)
        let output = try XCTUnwrap(CGImageSourceCreateImageAtIndex(outputSource, 0, nil))
        XCTAssertEqual(output.width, 400)
        XCTAssertEqual(output.height, 800)
        // EXIF 6 was consumed during preparation, not deferred to the receiving Pi.
        assertColor(try pixel(output, x: 100, y: 200), equals: .blue, message: "Upright PNG")
        XCTAssertLessThanOrEqual(png.count, PhotoPipeline.maximumPNGBytes)
    }

    func testCameraPreparationBoundsLargeRotatedCaptureWithoutStretching() throws {
        let source = try quadrantImage(width: 8_192, height: 512)
        let capture = try XCTUnwrap(CapturedPhoto(image: UIImage(cgImage: source, scale: 1, orientation: .right)))
        let prepared = try capture.prepare()
        XCTAssertEqual(prepared.image.width, 256)
        XCTAssertEqual(prepared.image.height, 4_096)
        XCTAssertEqual(max(prepared.image.width, prepared.image.height), PhotoPipeline.maximumDecodeDimension)
        XCTAssertEqual(prepared.image.height, prepared.image.width * 16)
        assertColor(try pixel(prepared.image, x: 64, y: 1_024), equals: .blue, message: "Rotated downsample")
    }

    func testCancelledCameraPreparationDoesNotProduceAnImage() async throws {
        let capture = try XCTUnwrap(CapturedPhoto(image: UIImage(cgImage: try quadrantImage(width: 160, height: 80))))
        let worker = Task.detached {
            // Cancel inside the task to avoid a race between scheduling and cancellation.
            withUnsafeCurrentTask { $0?.cancel() }
            return try capture.prepare()
        }
        do {
            _ = try await worker.value
            XCTFail("A dismissed camera import should not finish preparation")
        } catch is CancellationError {
            // Expected: no prepared image can be delivered to a dismissed import.
        } catch {
            XCTFail("Expected CancellationError, received \(error)")
        }
    }

    private struct RGB {
        let red: UInt8
        let green: UInt8
        let blue: UInt8
        static let red = RGB(red: 255, green: 0, blue: 0)
        static let green = RGB(red: 0, green: 255, blue: 0)
        static let blue = RGB(red: 0, green: 0, blue: 255)
        static let yellow = RGB(red: 255, green: 255, blue: 0)
    }

    private func quadrantImage(width: Int, height: Int) throws -> CGImage {
        var bytes = [UInt8](repeating: 255, count: width * height * 4)
        for y in 0..<height {
            for x in 0..<width {
                let color: RGB
                switch (x < width / 2, y < height / 2) {
                case (true, true): color = .red
                case (false, true): color = .green
                case (true, false): color = .blue
                case (false, false): color = .yellow
                }
                let offset = (y * width + x) * 4
                bytes[offset] = color.red
                bytes[offset + 1] = color.green
                bytes[offset + 2] = color.blue
            }
        }
        let provider = try XCTUnwrap(CGDataProvider(data: Data(bytes) as CFData))
        return try XCTUnwrap(CGImage(
            width: width, height: height, bitsPerComponent: 8, bitsPerPixel: 32, bytesPerRow: width * 4,
            space: try XCTUnwrap(CGColorSpace(name: CGColorSpace.sRGB)),
            bitmapInfo: CGBitmapInfo(rawValue: CGImageAlphaInfo.noneSkipLast.rawValue),
            provider: provider, decode: nil, shouldInterpolate: false, intent: .defaultIntent
        ))
    }

    private func pixel(_ image: CGImage, x: Int, y: Int) throws -> RGB {
        let context = try XCTUnwrap(CGContext(
            data: nil, width: image.width, height: image.height, bitsPerComponent: 8, bytesPerRow: image.width * 4,
            space: try XCTUnwrap(CGColorSpace(name: CGColorSpace.sRGB)),
            bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue
        ))
        context.draw(image, in: CGRect(x: 0, y: 0, width: image.width, height: image.height))
        let bytes = try XCTUnwrap(context.data).assumingMemoryBound(to: UInt8.self)
        let offset = (y * image.width + x) * 4
        return RGB(red: bytes[offset], green: bytes[offset + 1], blue: bytes[offset + 2])
    }

    private func assertColor(_ actual: RGB, equals expected: RGB, message: String,
                             file: StaticString = #filePath, line: UInt = #line) {
        // Allow normal JPEG/color-conversion rounding, while detecting any wrong quadrant.
        XCTAssertEqual(Double(actual.red), Double(expected.red), accuracy: 20, message, file: file, line: line)
        XCTAssertEqual(Double(actual.green), Double(expected.green), accuracy: 20, message, file: file, line: line)
        XCTAssertEqual(Double(actual.blue), Double(expected.blue), accuracy: 20, message, file: file, line: line)
    }
}
