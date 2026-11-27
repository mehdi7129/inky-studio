import Foundation

/// Presentation state is RAM-only. The QR claim token never enters defaults or a checkpoint.
struct FactorySetupPresentation: Identifiable {
    let id = UUID()
    var code: FrameBootstrapCode?
    let owner: OwnershipRecord?
}
