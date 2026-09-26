import CoreGraphics

/// All source rectangles use upright image pixels, with the origin at the top left.
struct CropGeometry: Equatable, Sendable {
    static let maximumZoom: CGFloat = 4

    let sourceSize: CGSize
    let viewportSize: CGSize
    let zoom: CGFloat
    let offset: CGSize

    init(sourceSize: CGSize, viewportSize: CGSize, zoom: CGFloat = 1, offset: CGSize = .zero) {
        self.sourceSize = sourceSize
        self.viewportSize = viewportSize
        self.zoom = zoom.isFinite ? min(Self.maximumZoom, max(1, zoom)) : 1
        self.offset = offset
    }

    var isValid: Bool {
        [sourceSize.width, sourceSize.height, viewportSize.width, viewportSize.height]
            .allSatisfy { $0.isFinite && $0 > 0 }
    }

    var scale: CGFloat {
        guard isValid else { return 1 }
        return max(viewportSize.width / sourceSize.width, viewportSize.height / sourceSize.height) * zoom
    }

    var displayedSize: CGSize {
        guard isValid else { return .zero }
        return CGSize(width: sourceSize.width * scale, height: sourceSize.height * scale)
    }

    var clampedOffset: CGSize {
        guard isValid else { return .zero }
        let limitX = max(0, (displayedSize.width - viewportSize.width) / 2)
        let limitY = max(0, (displayedSize.height - viewportSize.height) / 2)
        return CGSize(
            width: min(limitX, max(-limitX, offset.width.isFinite ? offset.width : 0)),
            height: min(limitY, max(-limitY, offset.height.isFinite ? offset.height : 0))
        )
    }

    var sourceRect: CGRect {
        guard isValid else { return .zero }
        let width = min(sourceSize.width, viewportSize.width / scale)
        let height = min(sourceSize.height, viewportSize.height / scale)
        return CGRect(
            x: min(sourceSize.width - width, max(0, (sourceSize.width - width) / 2 - clampedOffset.width / scale)),
            y: min(sourceSize.height - height, max(0, (sourceSize.height - height) / 2 - clampedOffset.height / scale)),
            width: width,
            height: height
        )
    }

    /// Fits the panel aspect ratio inside the available canvas, including portrait panels.
    static func viewport(in canvas: CGSize, panel: CGSize, inset: CGFloat = 12) -> CGSize {
        guard canvas.width > inset * 2, canvas.height > inset * 2,
              panel.width > 0, panel.height > 0 else { return .zero }
        let width = canvas.width - inset * 2
        let height = canvas.height - inset * 2
        let ratio = panel.width / panel.height
        if width / height > ratio {
            return CGSize(width: height * ratio, height: height)
        }
        return CGSize(width: width, height: width / ratio)
    }
}
