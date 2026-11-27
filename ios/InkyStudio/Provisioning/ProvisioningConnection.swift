import Foundation

@MainActor
protocol ProvisioningConnection: AnyObject {
    func connect(peripheralID: UUID, identity: FrameIdentity) async throws -> PinnedFrameTrust
    func request(_ data: Data, timeout: TimeInterval) async throws -> Data
    func connectBootstrap(peripheralID: UUID, identity: FrameIdentity) async throws -> BootstrapFrameTrust
    func requestBootstrap(_ data: Data, timeout: TimeInterval) async throws -> Data
    func disconnect()
}

extension ProvisioningConnection {
    func connectBootstrap(peripheralID: UUID, identity: FrameIdentity) async throws -> BootstrapFrameTrust { throw BluetoothTransportError.unsupportedFrame }
    func requestBootstrap(_ data: Data, timeout: TimeInterval) async throws -> Data { throw BluetoothTransportError.unsupportedFrame }
}
extension SecureBluetoothChannel: ProvisioningConnection {}
