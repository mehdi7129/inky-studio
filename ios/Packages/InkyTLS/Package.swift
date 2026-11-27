// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "InkyTLS",
    platforms: [.iOS(.v18), .macOS(.v13)],
    products: [.library(name: "InkyTLS", targets: ["InkyTLS"])],
    targets: [
        .binaryTarget(name: "MbedTLS", path: "Artifacts/MbedTLS.xcframework"),
        .target(name: "CInkyTLS", dependencies: ["MbedTLS"], publicHeadersPath: "include"),
        .target(name: "InkyTLS", dependencies: ["CInkyTLS"]),
        .testTarget(name: "InkyTLSTests", dependencies: ["InkyTLS"], resources: [.copy("Support")]),
    ]
)
