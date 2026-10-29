// swift-tools-version: 6.0
import PackageDescription

// Host-only transport interop harness. The shipping app continues to use the
// Xcode project; these are the same source files and the same pinned TLS bridge.
let package = Package(
    name: "InkySoftAPHostValidation",
    platforms: [.macOS(.v15)],
    dependencies: [.package(path: "Packages/InkyTLS")],
    targets: [
        .target(name: "InkyStudio", dependencies: [.product(name: "InkyTLS", package: "InkyTLS")],
            path: "InkyStudio", sources: [
                "Provisioning/FrameIdentity.swift", "Provisioning/FrameBootstrapCode.swift",
                "Provisioning/SoftAPBootstrap.swift", "Provisioning/SoftAPHotspot.swift",
                "Provisioning/ProvisioningConnection.swift", "Provisioning/TCPProvisioningConnection.swift",
                "Provisioning/PinnedFrameTrust.swift", "Provisioning/BootstrapFrameTrust.swift",
                "Provisioning/OwnershipVault.swift", "Provisioning/FactorySetupModels.swift",
                "Provisioning/BluetoothTransport.swift", "Provisioning/SecureBluetoothChannel.swift"
            ]),
        .testTarget(name: "SoftAPHostTests", dependencies: ["InkyStudio"], path: "InkyStudioTests",
            sources: ["SoftAPTransportTests.swift", "FrameTrustTestFixtures.swift"]),
        .testTarget(name: "SoftAPInteropTests", dependencies: ["InkyStudio"], path: "HostTests")
    ], swiftLanguageModes: [.v5]
)
