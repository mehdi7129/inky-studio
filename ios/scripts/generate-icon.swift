import AppKit
// Repository-native vector artwork. No external asset or generated photo required.
let size = 1024
// AppKit cannot draw into a packed 24-bit RGB bitmap: its graphics context is nil.
// Use supported 32-bit RGB storage with a skipped byte, keeping the image opaque.
guard let context = CGContext(
    data: nil, width: size, height: size, bitsPerComponent: 8, bytesPerRow: size * 4,
    space: CGColorSpace(name: CGColorSpace.sRGB)!,
    bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue
) else { fatalError("Could not create the icon drawing context") }
NSGraphicsContext.saveGraphicsState()
NSGraphicsContext.current = NSGraphicsContext(cgContext: context, flipped: false)
NSColor(calibratedWhite: 0.96, alpha: 1).setFill()
NSBezierPath(rect: NSRect(x: 0, y: 0, width: size, height: size)).fill()
func tile(_ rect: NSRect, _ color: NSColor) {
    color.setFill()
    NSBezierPath(roundedRect: rect, xRadius: 48, yRadius: 48).fill()
}
tile(NSRect(x: 148, y: 322, width: 728, height: 554), NSColor(calibratedWhite: 0.055, alpha: 1))
tile(NSRect(x: 148, y: 148, width: 432, height: 142), .white)
tile(NSRect(x: 612, y: 148, width: 118, height: 142), NSColor(calibratedRed: 0.18, green: 0.47, blue: 0.93, alpha: 1))
tile(NSRect(x: 762, y: 148, width: 114, height: 142), NSColor(calibratedRed: 0.98, green: 0.68, blue: 0.25, alpha: 1))
NSColor.white.setStroke()
let frame = NSBezierPath(roundedRect: NSRect(x: 258, y: 427, width: 508, height: 344), xRadius: 30, yRadius: 30)
frame.lineWidth = 20; frame.stroke()
let mountain = NSBezierPath()
mountain.move(to: NSPoint(x: 277, y: 452)); mountain.line(to: NSPoint(x: 448, y: 627)); mountain.line(to: NSPoint(x: 552, y: 524)); mountain.line(to: NSPoint(x: 624, y: 596)); mountain.line(to: NSPoint(x: 749, y: 467))
mountain.lineJoinStyle = .round; mountain.lineWidth = 20; mountain.stroke()
NSColor.white.setFill(); NSBezierPath(ovalIn: NSRect(x: 635, y: 657, width: 50, height: 50)).fill()
NSGraphicsContext.restoreGraphicsState()
guard let image = context.makeImage() else { fatalError("Could not render the icon") }
let bitmap = NSBitmapImageRep(cgImage: image)
precondition(!bitmap.hasAlpha, "The App Store icon must be opaque")
let output = URL(fileURLWithPath: CommandLine.arguments[1])
try bitmap.representation(using: .png, properties: [:])!.write(to: output)
