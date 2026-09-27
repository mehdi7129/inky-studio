import AppKit

// Editable vector source for approved direction A: one bold frame,
// a solid landscape and a blue sun. iOS applies the app-icon corner mask.
// Usage: swift generate-icon.swift output.png [dark|tinted] [pixel-size]
let output = URL(fileURLWithPath: CommandLine.arguments[1])
let variant = CommandLine.arguments.count > 2 ? CommandLine.arguments[2] : "light"
let size = CommandLine.arguments.count > 3 ? Int(CommandLine.arguments[3])! : 1024
precondition(size > 0 && size <= 4096)

// Supported opaque storage; packed 24-bit AppKit bitmaps cannot be drawn into.
guard let context = CGContext(
    data: nil, width: size, height: size, bitsPerComponent: 8, bytesPerRow: size * 4,
    space: CGColorSpace(name: CGColorSpace.sRGB)!,
    bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue
) else { fatalError("Could not create the icon drawing context") }
context.scaleBy(x: CGFloat(size) / 1024, y: CGFloat(size) / 1024)
NSGraphicsContext.saveGraphicsState()
NSGraphicsContext.current = NSGraphicsContext(cgContext: context, flipped: false)

let canvas = NSColor(srgbRed: variant == "dark" ? 0.10 : 0.055,
                     green: variant == "dark" ? 0.105 : 0.055,
                     blue: variant == "dark" ? 0.115 : 0.055, alpha: 1)
let ink = NSColor(calibratedWhite: 0.98, alpha: 1)
let accent = variant == "tinted" ? NSColor(calibratedWhite: 0.65, alpha: 1)
    : NSColor(srgbRed: 0.05, green: 0.48, blue: 1, alpha: 1)
canvas.setFill()
NSBezierPath(rect: NSRect(x: 0, y: 0, width: 1024, height: 1024)).fill()

// At 29 px the 56-unit frame remains 1.59 px thick. No thin outline details.
let frameRect = NSRect(x: 162, y: 252, width: 700, height: 520)
ink.setFill()
NSBezierPath(roundedRect: frameRect, xRadius: 78, yRadius: 78).fill()
let innerRect = frameRect.insetBy(dx: 56, dy: 56)
let inner = NSBezierPath(roundedRect: innerRect, xRadius: 24, yRadius: 24)
canvas.setFill()
inner.fill()

NSGraphicsContext.saveGraphicsState()
// The solid landscape stays inside the outer frame. Avoid clipping it to the
// inner edge, which would leave a double-antialiased seam at the lower corners.
let landscape = NSBezierPath()
landscape.move(to: NSPoint(x: 200, y: 275))
landscape.line(to: NSPoint(x: 200, y: 338))
landscape.line(to: NSPoint(x: 428, y: 575))
landscape.line(to: NSPoint(x: 581, y: 413))
landscape.line(to: NSPoint(x: 652, y: 490))
landscape.line(to: NSPoint(x: 825, y: 321))
landscape.line(to: NSPoint(x: 825, y: 275))
landscape.close()
ink.setFill()
landscape.fill()
accent.setFill()
NSBezierPath(ovalIn: NSRect(x: 645, y: 578, width: 116, height: 116)).fill()
NSGraphicsContext.restoreGraphicsState()
NSGraphicsContext.restoreGraphicsState()

guard let image = context.makeImage() else { fatalError("Could not render the icon") }
let bitmap = NSBitmapImageRep(cgImage: image)
precondition(!bitmap.hasAlpha, "The App Store icon must be opaque")
try bitmap.representation(using: .png, properties: [:])!.write(to: output)
