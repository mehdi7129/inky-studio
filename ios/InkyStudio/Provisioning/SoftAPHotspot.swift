import Foundation
#if os(iOS)
@preconcurrency import NetworkExtension
#endif

@MainActor protocol SoftAPJoining: AnyObject {
    func join(_ descriptor: SoftAPDescriptor) async throws
    func leave(_ descriptor: SoftAPDescriptor)
    func cancel()
}

/// Applying a configuration is only consent to join. A fresh TCP/TLS handshake
/// with the scanned pin, performed by the caller, proves accessory reachability.
@MainActor final class SoftAPHotspot: SoftAPJoining {
    private var pending: (UUID, CheckedContinuation<Void, Error>)?
    func join(_ descriptor: SoftAPDescriptor) async throws {
        #if os(iOS)
        guard pending == nil else { throw SoftAPError.busy }
        let id = UUID()
        let configuration = NEHotspotConfiguration(ssid: descriptor.ssid, passphrase: descriptor.passphrase, isWEP: false)
        configuration.joinOnce = true
        try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
            pending = (id, continuation)
            NEHotspotConfigurationManager.shared.apply(configuration) { error in
                Task { @MainActor [weak self] in
                    guard let self else { return }
                    guard self.pending?.0 == id else {
                        if self.pending == nil {
                            NEHotspotConfigurationManager.shared.removeConfiguration(forSSID: descriptor.ssid)
                        }
                        return
                    }
                    self.pending = nil
                    if let error = error as NSError? {
                        guard error.domain == NEHotspotConfigurationErrorDomain,
                              error.code == NEHotspotConfigurationError.alreadyAssociated.rawValue else {
                            continuation.resume(throwing: SoftAPError.unavailable)
                            return
                        }
                    }
                    continuation.resume()
                }
            }
        }
        try Task.checkCancellation()
        #else
        throw SoftAPError.unavailable
        #endif
    }

    func cancel() {
        guard let (_, continuation) = pending else { return }
        pending = nil
        continuation.resume(throwing: SoftAPError.cancelled)
    }

    func leave(_ descriptor: SoftAPDescriptor) {
        #if os(iOS)
        // Removes only the configuration installed by this app. No home-network
        // password is requested from iOS or saved by this adapter.
        NEHotspotConfigurationManager.shared.removeConfiguration(forSSID: descriptor.ssid)
        #endif
    }
}
