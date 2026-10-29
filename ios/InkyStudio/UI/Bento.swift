import SwiftUI

enum Bento {
    static let background = adaptive(light: UIColor(red: 0.961, green: 0.961, blue: 0.953, alpha: 1), dark: UIColor(red: 0.063, green: 0.071, blue: 0.078, alpha: 1))
    static let canvas = background
    static let surface = adaptive(light: .white, dark: UIColor(red: 0.106, green: 0.118, blue: 0.129, alpha: 1))
    static let ink = adaptive(light: UIColor(white: 0.067, alpha: 1), dark: UIColor(white: 0.96, alpha: 1))
    // Opaque text colors keep at least 4.5:1 on both Bento backgrounds.
    static let secondaryInk = adaptive(light: UIColor(red: 101/255, green: 101/255, blue: 107/255, alpha: 1), dark: UIColor(red: 173/255, green: 178/255, blue: 186/255, alpha: 1))
    static let actionText = adaptive(light: .white, dark: UIColor(white: 0.067, alpha: 1))
    static let blue = adaptive(light: UIColor(red: 0.157, green: 0.404, blue: 0.804, alpha: 1), dark: UIColor(red: 0.467, green: 0.663, blue: 1, alpha: 1))
    static let accent = blue
    static let amber = adaptive(light: UIColor(red: 0.58, green: 0.35, blue: 0, alpha: 1), dark: UIColor(red: 0.98, green: 0.72, blue: 0.32, alpha: 1))
    static let success = adaptive(light: UIColor(red: 0.14, green: 0.44, blue: 0.24, alpha: 1), dark: UIColor(red: 0.45, green: 0.80, blue: 0.58, alpha: 1))
    static let danger = adaptive(light: UIColor(red: 0.72, green: 0.12, blue: 0.16, alpha: 1), dark: UIColor(red: 1, green: 0.55, blue: 0.56, alpha: 1))
    static let border = adaptive(light: .black.withAlphaComponent(0.10), dark: .white.withAlphaComponent(0.16))
    static let placeholder = adaptive(light: .black.withAlphaComponent(0.04), dark: .white.withAlphaComponent(0.06))
    static let pressedSurface = adaptive(light: UIColor(white: 0.94, alpha: 1), dark: UIColor(white: 0.20, alpha: 1))

    private static func adaptive(light: UIColor, dark: UIColor) -> Color {
        Color(uiColor: UIColor { traits in traits.userInterfaceStyle == .dark ? dark : light })
    }
}

extension View {
    func bentoCard(padding: CGFloat = 16) -> some View {
        self.padding(padding).frame(maxWidth: .infinity, alignment: .leading)
            .background(Bento.surface, in: RoundedRectangle(cornerRadius: 20))
            .overlay(RoundedRectangle(cornerRadius: 20).stroke(Bento.border, lineWidth: 0.7))
    }
    /// Apply on each presented surface as well as the root: sheets render above root overlays.
    func protectSensitiveContent() -> some View { modifier(SensitiveContentShield()) }

    func screenBackground() -> some View {
        self.background(Bento.background)
            // A compact native title avoids the invisible large-title space on iOS 27.
            .navigationBarTitleDisplayMode(.inline)
            .toolbarBackground(.visible, for: .navigationBar)
            .toolbarBackground(Bento.background, for: .navigationBar)
    }
}

private struct SensitiveContentShield: ViewModifier {
    @Environment(\.scenePhase) private var phase

    func body(content: Content) -> some View {
        content
            .accessibilityHidden(phase != .active)
            .allowsHitTesting(phase == .active)
            .overlay {
                if phase != .active { PrivacyCoverView().ignoresSafeArea() }
            }
    }
}

/// An anchor in this scene's real window. Its opaque UIKit view covers native
/// presentations (including PhotosPicker) above SwiftUI's root and sheet layers.
struct ScenePrivacyAnchor: UIViewRepresentable {
    var onScenePhaseChanged: (ScenePhase) -> Void = { _ in }
    func makeUIView(context: Context) -> ScenePrivacyAnchorView {
        ScenePrivacyAnchorView(onScenePhaseChanged: onScenePhaseChanged)
    }
    func updateUIView(_ view: ScenePrivacyAnchorView, context: Context) {
        view.onScenePhaseChanged = onScenePhaseChanged
    }
    static func dismantleUIView(_ view: ScenePrivacyAnchorView, coordinator: ()) { view.detach() }
}

final class ScenePrivacyAnchorView: UIView {
    private weak var protectedWindow: UIWindow?
    private var shield: UIView?
    var onScenePhaseChanged: (ScenePhase) -> Void
    private var attachment = UUID()
    private var lastDeliveredPhase: ScenePhase?

    init(onScenePhaseChanged: @escaping (ScenePhase) -> Void = { _ in }) {
        self.onScenePhaseChanged = onScenePhaseChanged
        super.init(frame: .zero)
        isUserInteractionEnabled = false
        isAccessibilityElement = false
        let center = NotificationCenter.default
        center.addObserver(self, selector: #selector(willDeactivate(_:)),
                           name: UIScene.willDeactivateNotification, object: nil)
        center.addObserver(self, selector: #selector(didActivate(_:)),
                           name: UIScene.didActivateNotification, object: nil)
        center.addObserver(self, selector: #selector(didEnterBackground(_:)),
                           name: UIScene.didEnterBackgroundNotification, object: nil)
    }
    required init?(coder: NSCoder) { nil }

    override func didMoveToWindow() {
        super.didMoveToWindow()
        if protectedWindow !== window {
            removeShield()
            protectedWindow = window
            attachment = UUID()
            lastDeliveredPhase = nil
        }
        guard let scene = window?.windowScene else { return }
        switch scene.activationState {
        case .foregroundActive: removeShield(); deliver(.active, from: scene)
        case .foregroundInactive: showShield(); deliver(.inactive, from: scene)
        case .background, .unattached: showShield(); deliver(.background, from: scene)
        @unknown default: showShield(); deliver(.background, from: scene)
        }
    }

    @objc private func willDeactivate(_ notification: Notification) {
        guard let scene = notification.object as? UIWindowScene,
              scene === protectedWindow?.windowScene else { return }
        showShield()
        deliver(.inactive, from: scene, synchronously: true)
    }

    @objc private func didActivate(_ notification: Notification) {
        guard let scene = notification.object as? UIWindowScene,
              scene === protectedWindow?.windowScene else { return }
        removeShield()
        deliver(.active, from: scene)
    }

    @objc private func didEnterBackground(_ notification: Notification) {
        guard let scene = notification.object as? UIWindowScene,
              scene === protectedWindow?.windowScene else { return }
        showShield()
        deliver(.background, from: scene, synchronously: true)
    }

    private func deliver(_ phase: ScenePhase, from scene: UIWindowScene, synchronously: Bool = false) {
        let currentAttachment = attachment
        let publish = { [weak self, weak scene] in
            guard let self, let scene, self.attachment == currentAttachment,
                  self.protectedWindow === self.window,
                  scene === self.protectedWindow?.windowScene else { return }
            // An activation queued before deactivation must never admit a mutation.
            guard phase != .active || scene.activationState == .foregroundActive else { return }
            guard self.lastDeliveredPhase != phase else { return }
            self.lastDeliveredPhase = phase
            self.onScenePhaseChanged(phase)
        }
        // Native deactivation/background must close admission before another ready
        // authentication job runs. Only the attachment snapshot can occur in render.
        if synchronously { publish() }
        else { DispatchQueue.main.async { publish() } }
    }

    private func showShield() {
        guard shield == nil, let window = protectedWindow else { return }
        let cover = UIView(frame: window.bounds)
        cover.autoresizingMask = [.flexibleWidth, .flexibleHeight]
        cover.backgroundColor = UIColor(Bento.background)
        cover.layer.zPosition = 10_000
        cover.isAccessibilityElement = true
        cover.accessibilityLabel = "Inky Studio verrouillé"
        cover.accessibilityViewIsModal = true
        let symbol = UIImageView(image: UIImage(systemName: "lock.iphone"))
        symbol.preferredSymbolConfiguration = UIImage.SymbolConfiguration(pointSize: 52, weight: .ultraLight)
        symbol.tintColor = .label
        symbol.contentMode = .scaleAspectFit
        let title = UILabel()
        title.text = "Inky Studio"
        title.font = .preferredFont(forTextStyle: .title2)
        title.textColor = .label
        title.adjustsFontForContentSizeCategory = true
        let content = UIStackView(arrangedSubviews: [symbol, title])
        content.axis = .vertical
        content.alignment = .center
        content.spacing = 20
        content.translatesAutoresizingMaskIntoConstraints = false
        cover.addSubview(content)
        NSLayoutConstraint.activate([
            content.centerXAnchor.constraint(equalTo: cover.centerXAnchor),
            content.centerYAnchor.constraint(equalTo: cover.centerYAnchor),
            content.leadingAnchor.constraint(greaterThanOrEqualTo: cover.leadingAnchor, constant: 24),
            content.trailingAnchor.constraint(lessThanOrEqualTo: cover.trailingAnchor, constant: -24),
        ])
        window.addSubview(cover)
        shield = cover
    }

    private func removeShield() { shield?.removeFromSuperview(); shield = nil }
    func detach() {
        attachment = UUID()
        NotificationCenter.default.removeObserver(self)
        removeShield()
        protectedWindow = nil
        onScenePhaseChanged = { _ in }
    }
    deinit { NotificationCenter.default.removeObserver(self) }
}

struct PrimaryButtonStyle: ButtonStyle {
    @Environment(\.isEnabled) private var isEnabled
    func makeBody(configuration: Configuration) -> some View {
        configuration.label.font(.body.weight(.semibold)).multilineTextAlignment(.center)
            .fixedSize(horizontal: false, vertical: true).padding(.horizontal, 14).padding(.vertical, 12)
            .frame(maxWidth: .infinity).frame(minHeight: 52)
            .foregroundStyle(Bento.actionText).background(Bento.ink.opacity(configuration.isPressed ? 0.75 : 1), in: RoundedRectangle(cornerRadius: 14))
            .contentShape(RoundedRectangle(cornerRadius: 14))
            .opacity(isEnabled ? 1 : 0.45)
    }
}
struct OutlineButtonStyle: ButtonStyle {
    @Environment(\.isEnabled) private var isEnabled
    func makeBody(configuration: Configuration) -> some View {
        configuration.label.font(.subheadline.weight(.medium)).multilineTextAlignment(.center)
            .fixedSize(horizontal: false, vertical: true).padding(.horizontal, 12).padding(.vertical, 10)
            .frame(maxWidth: .infinity).frame(minHeight: 46)
            .foregroundStyle(Bento.ink).background(configuration.isPressed ? Bento.pressedSurface : Bento.surface, in: RoundedRectangle(cornerRadius: 12))
            .overlay(RoundedRectangle(cornerRadius: 12).stroke(Bento.border, lineWidth: 1))
            .contentShape(RoundedRectangle(cornerRadius: 12))
            .opacity(isEnabled ? 1 : 0.45)
    }
}

struct FramePhoto: View {
    @EnvironmentObject private var store: AppStore
    let photo: Photo
    var accessibilityDescription = "Photo"
    @State private var image: UIImage?
    @State private var loading = true
    var body: some View {
        ZStack {
            Bento.placeholder
            if let image {
                Image(uiImage: image).resizable().scaledToFit()
            } else if loading { ProgressView() }
            else { Image(systemName: "photo").font(.title2).foregroundStyle(Bento.secondaryInk).accessibilityLabel("Aperçu indisponible") }
        }
        .aspectRatio(CGFloat(photo.width) / CGFloat(max(photo.height, 1)), contentMode: .fit)
        .clipShape(RoundedRectangle(cornerRadius: 12))
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(accessibilityDescription)
        .accessibilityValue(loading ? "Chargement de l’aperçu" : image == nil ? "Aperçu indisponible" : "")
        .accessibilityAddTraits(.isImage)
        .task(id: "\(photo.id)-\(store.connected)") {
            guard store.connected else { loading = false; return }
            loading = image == nil
            let loadedImage = await store.image(for: photo)
            guard !Task.isCancelled else { return }
            image = loadedImage
            loading = false
        }
    }
}

struct EmptyCard: View {
    let symbol: String
    let title: String
    let message: String
    var body: some View {
        VStack(spacing: 14) {
            Image(systemName: symbol).font(.system(size: 38, weight: .light)).foregroundStyle(Bento.secondaryInk)
            Text(title).font(.headline)
            Text(message).font(.subheadline).foregroundStyle(Bento.secondaryInk).multilineTextAlignment(.center)
        }.frame(maxWidth: .infinity).padding(.vertical, 30).bentoCard()
    }
}
