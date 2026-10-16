import SwiftUI

struct ConnectionView: View {
    @EnvironmentObject private var store: AppStore
    @State private var gettingStarted = false
    @State private var scanningLANQR = false
    @State private var bluetoothSetup = false
    @ScaledMetric(relativeTo: .largeTitle) private var titleSize = 40
    #if DEBUG
    @State private var fixturePassword = ""
    private var legacyLoginFixture: Bool {
        let arguments = ProcessInfo.processInfo.arguments
        return arguments.contains("--uitesting") && arguments.contains("--legacy-login-fixture")
    }
    private var bluetoothFixture: Bool {
        let arguments = ProcessInfo.processInfo.arguments
        return arguments.contains("--uitesting") && arguments.contains("--bluetooth-fixture")
    }
    #endif

    var body: some View {
        GeometryReader { geometry in
            ScrollView {
                VStack(alignment: .leading, spacing: 0) {
                    InkyBrandHeader().padding(.top, 16).padding(.bottom, 36)
                    VStack(alignment: .leading, spacing: 20) {
                        ScanPhotoSymbol().frame(maxWidth: .infinity).padding(.vertical, 10)
                        Text("Connecter\nmon cadre.")
                            .font(.system(size: titleSize, weight: .bold)).tracking(-1.2)
                            .fixedSize(horizontal: false, vertical: true)
                            .accessibilityAddTraits(.isHeader)
                        Text("Scannez le QR code affiché sur votre cadre.")
                            .font(.title3).foregroundStyle(Bento.secondaryInk)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    .padding(24).frame(maxWidth: .infinity, alignment: .leading)
                    .background(Bento.surface, in: RoundedRectangle(cornerRadius: 28))
                    .overlay(RoundedRectangle(cornerRadius: 28).stroke(Bento.border, lineWidth: 0.7))
                    .accessibilityIdentifier("connection.card")
                    Button { scanningLANQR = true } label: {
                        Label("Scanner un QR code", systemImage: "qrcode.viewfinder")
                            .frame(minHeight: 32)
                    }
                    .buttonStyle(PrimaryButtonStyle()).padding(.top, 20)
                    .disabled(store.connecting || store.unlocking)
                    .accessibilityIdentifier("connection.scanLANQR")
                    if store.hasPendingFactorySetup {
                        Button("Reprendre la configuration") { store.resumeFactorySetup() }
                            .frame(maxWidth: .infinity, minHeight: 44)
                            .disabled(store.connecting || store.unlocking)
                            .accessibilityIdentifier("connection.resumeFactory")
                    }
                    if store.recoveringConnection {
                        Text("Votre accès enregistré est conservé jusqu’à la validation du nouveau QR.")
                            .font(.footnote).foregroundStyle(Bento.secondaryInk).padding(.top, 16)
                        Button("Annuler") { store.cancelConnectionRecovery() }
                            .frame(maxWidth: .infinity, minHeight: 44)
                            .accessibilityIdentifier("connection.cancelRecovery")
                    }
                    if store.connecting {
                        VStack(spacing: 8) {
                            HStack(spacing: 12) { ProgressView(); Text("Connexion au cadre…") }
                            Button("Annuler la connexion") { store.cancelLogin() }
                                .frame(minHeight: 44).accessibilityIdentifier("connection.cancel")
                        }.font(.subheadline).frame(maxWidth: .infinity).padding(.top, 20)
                    }
                    if let error = store.localAuthenticationError ?? store.errorMessage {
                        Text(error).font(.subheadline).foregroundStyle(Bento.danger)
                            .fixedSize(horizontal: false, vertical: true)
                            .padding(.top, 16).accessibilityIdentifier("connection.error")
                    }
                    #if DEBUG
                    if legacyLoginFixture { fixtureLogin.padding(.top, 20) }
                    else if bluetoothFixture {
                        Button("Ouvrir la fixture Wi-Fi") { bluetoothSetup = true }
                            .accessibilityIdentifier("connection.bluetooth").padding(.top, 20)
                    }
                    #endif
                    Spacer(minLength: 44)
                    VStack(spacing: 12) {
                        Image(systemName: "faceid").font(.system(size: 28, weight: .light)).accessibilityHidden(true)
                        Text("Accès protégé par l’iPhone.").font(.subheadline)
                        HStack(spacing: 12) {
                            Button("Aide") { gettingStarted = true }
                                .frame(minHeight: 44)
                                .accessibilityIdentifier("connection.guide")
                            Text("·").accessibilityHidden(true)
                            Link("Confidentialité", destination: SupportPrivacyLinks.privacyURL)
                                .frame(minHeight: 44)
                                .accessibilityIdentifier("connection.privacy")
                        }.font(.footnote).frame(minHeight: 44).padding(.top, 6)
                    }
                    .foregroundStyle(Bento.secondaryInk).frame(maxWidth: .infinity)
                    .padding(.bottom, 12)
                }
                .padding(.horizontal, 24).frame(maxWidth: 540)
                .frame(minHeight: geometry.size.height, alignment: .top)
                .frame(maxWidth: .infinity)
            }.accessibilityIdentifier("connection.scroll")
        }
        .background(Bento.background).foregroundStyle(Bento.ink)
        .sheet(isPresented: $gettingStarted, onDismiss: { store.presentQueuedFactorySetup() }) {
            GettingStartedView(allowWiFiSetup: !store.isMediaPhotoAccess && store.hasAdoptedFrame && !store.pairingNeedsCompletion)
        }
        .sheet(isPresented: $scanningLANQR, onDismiss: { store.presentQueuedFactorySetup() }) {
            LANLoginScannerView().interactiveDismissDisabled(store.recoveringConnection)
        }
        #if DEBUG
        .sheet(isPresented: $bluetoothSetup) {
            BluetoothSetupView { endpoint, owner in
                await store.finishBluetoothSetup(endpoint: endpoint, owner: owner)
            }
        }
        #endif
    }

    #if DEBUG
    // Only the explicit loopback E2E fixture exposes synthetic credentials.
    // Release and the public QR screen contain no frame password field.
    private var fixtureLogin: some View {
        VStack(spacing: 12) {
            SecureField("Mot de passe synthétique", text: $fixturePassword)
                .textContentType(.none).textFieldStyle(.roundedBorder)
                .accessibilityIdentifier("connection.password")
            Button("Connexion de test") {
                let password = fixturePassword
                fixturePassword = ""
                Task { await store.login(password: password, rememberBiometric: false) }
            }.accessibilityIdentifier("connection.submit").disabled(store.connecting)
            if ProcessInfo.processInfo.arguments.contains("--bluetooth-fixture") {
                Button("Ouvrir la fixture Wi-Fi") { bluetoothSetup = true }
                    .accessibilityIdentifier("connection.bluetooth")
            }
        }
    }
    #endif
}

struct LANLoginScannerView: View {
    @EnvironmentObject private var store: AppStore
    @Environment(\.dismiss) private var dismiss
    var body: some View {
        NavigationStack {
            VStack(spacing: 20) {
                Text("Placez le QR du cadre ou l’invitation d’un autre iPhone dans le viseur. Pour les photos, rejoignez le même Wi-Fi que le cadre.")
                    .font(.subheadline).foregroundStyle(Bento.secondaryInk)
                #if DEBUG && targetEnvironment(simulator)
                if ProcessInfo.processInfo.arguments.contains("--uitesting"),
                   ProcessInfo.processInfo.arguments.contains("--qr-input-fixture") {
                    QRInputFixture { text in acceptQR(text) }
                } else { cameraScanner }
                #else
                cameraScanner
                #endif
                Spacer(minLength: 0)
            }.padding(24).background(Bento.background)
                .navigationTitle("Scanner un QR code").navigationBarTitleDisplayMode(.inline)
                .toolbar { ToolbarItem(placement: .cancellationAction) {
                    Button("Annuler") {
                        if store.recoveringConnection { store.cancelConnectionRecovery() }
                        dismiss()
                    }.accessibilityIdentifier("connection.cancelScanner")
                } }
        }.protectSensitiveContent()
    }

    private var cameraScanner: some View {
        QRScannerView { result in
            dismiss()
            switch result {
            case .success(let text): connect(text)
            case .failure(let error): store.errorMessage = error.localizedDescription
            }
        }.clipShape(RoundedRectangle(cornerRadius: 20)).frame(minHeight: 280)
    }

    private func acceptQR(_ text: String) {
        dismiss()
        connect(text)
    }

    private func connect(_ text: String) {
        if let bootstrap = try? FrameBootstrapCode.parse(text) {
            store.queueFactorySetup(bootstrap)
        } else if let invitation = try? FrameInvitationCode.parse(text) {
            Task { await store.claimInvitation(invitation) }
        } else if (try? FrameLANLoginCode.parse(text)) != nil {
            Task { await store.loginFromLANQRCode(text) }
        } else {
            store.errorMessage = "Ce QR n’est pas valide. Scannez le QR du cadre ou demandez une nouvelle invitation au propriétaire."
        }
    }

}

struct LocalLockView: View {
    @EnvironmentObject private var store: AppStore
    @State private var gettingStarted = false
    @State private var confirmingForget = false
    @ScaledMetric(relativeTo: .largeTitle) private var titleSize = 36

    var body: some View {
        GeometryReader { geometry in
            ScrollView {
                VStack(alignment: .leading, spacing: 28) {
                    InkyBrandHeader().padding(.top, 20)
                    Spacer(minLength: 44)
                    VStack(alignment: .leading, spacing: 24) {
                        Image(systemName: "lock.iphone")
                            .font(.system(size: 68, weight: .ultraLight))
                            .frame(maxWidth: .infinity).padding(.vertical, 24).accessibilityHidden(true)
                        Text("Votre cadre,\nen toute confiance.")
                            .font(.system(size: titleSize, weight: .bold)).tracking(-0.9)
                            .fixedSize(horizontal: false, vertical: true).accessibilityAddTraits(.isHeader)
                        Text("Déverrouillez Inky Studio avec Face ID, Touch ID ou le code de cet iPhone.")
                            .foregroundStyle(Bento.secondaryInk).fixedSize(horizontal: false, vertical: true)
                    }.padding(24).frame(maxWidth: .infinity, alignment: .leading)
                        .background(Bento.surface, in: RoundedRectangle(cornerRadius: 28))
                        .overlay(RoundedRectangle(cornerRadius: 28).stroke(Bento.border, lineWidth: 0.7))
                    Button { Task { await store.unlock() } } label: {
                        HStack(spacing: 12) {
                            if store.unlocking { ProgressView().tint(Bento.actionText) }
                            else { Image(systemName: "lock.open") }
                            Text(store.localUnlocked ? "Réessayer la connexion" : "Déverrouiller")
                        }.frame(minHeight: 32)
                    }.buttonStyle(PrimaryButtonStyle()).disabled(store.unlocking)
                        .accessibilityIdentifier("lock.unlock")
                        .accessibilityLabel(store.localUnlocked ? "Réessayer la connexion au cadre" : "Déverrouiller Inky Studio")
                        .accessibilityValue(store.unlocking ? "Vérification en cours" : "")
                    if let error = store.localAuthenticationError ?? store.errorMessage {
                        Text(error).font(.subheadline).foregroundStyle(Bento.danger)
                            .fixedSize(horizontal: false, vertical: true).accessibilityIdentifier("lock.error")
                    }
                    if store.hasAdoptedFrame || store.hasIndividualPhotoAccess {
                        Button("Oublier ce cadre…") {
                            Task { confirmingForget = await store.authorizeForgetCurrentFrame() }
                        }
                        .disabled(store.unlocking || store.connecting)
                        .frame(maxWidth: .infinity, minHeight: 44)
                        .font(.footnote).foregroundStyle(Bento.secondaryInk)
                        .accessibilityIdentifier("lock.forget")
                    } else {
                        Button("Scanner un nouveau QR") { Task { await store.beginConnectionRecovery() } }
                            .disabled(store.unlocking || store.connecting)
                            .frame(maxWidth: .infinity, minHeight: 44)
                            .font(.footnote).foregroundStyle(Bento.secondaryInk)
                            .accessibilityIdentifier("lock.recover")
                    }
                    Spacer(minLength: 44)
                    Text("Accès protégé par l’iPhone.").font(.subheadline).foregroundStyle(Bento.secondaryInk)
                        .frame(maxWidth: .infinity)
                    Button("Aide") { gettingStarted = true }.font(.footnote)
                        .frame(maxWidth: .infinity, minHeight: 44).accessibilityIdentifier("lock.help")
                }.padding(.horizontal, 24).padding(.bottom, 12).frame(maxWidth: 540)
                    .frame(minHeight: geometry.size.height).frame(maxWidth: .infinity)
            }.accessibilityIdentifier("lock.scroll")
        }.background(Bento.background).foregroundStyle(Bento.ink)
            .sheet(isPresented: $gettingStarted, onDismiss: { store.presentQueuedFactorySetup() }) { GettingStartedView(allowWiFiSetup: !store.isMediaPhotoAccess && store.hasAdoptedFrame && !store.pairingNeedsCompletion) }
            .confirmationDialog("Oublier ce cadre sur cet iPhone ?", isPresented: $confirmingForget) {
                Button("Oublier ce cadre", role: .destructive) {
                    Task { await store.forgetCurrentFrameAfterConfirmation() }
                }
                Button("Annuler", role: .cancel) { store.cancelForgetCurrentFrame() }
            } message: {
                Text("L’accès et l’association de ce cadre seront supprimés de cet iPhone. Les photos du cadre seront conservées. Il faudra un QR pour l’associer à nouveau.")
            }
            .onDisappear { store.cancelForgetCurrentFrame() }
    }
}

struct PrivacyCoverView: View {
    var body: some View {
        ZStack {
            Bento.background.ignoresSafeArea()
            VStack(spacing: 20) {
                Image(systemName: "lock.iphone").font(.system(size: 52, weight: .ultraLight))
                Text("Inky Studio").font(.title2.weight(.bold))
            }.foregroundStyle(Bento.ink)
        }.accessibilityElement(children: .ignore).accessibilityLabel("Inky Studio verrouillé")
    }
}

private struct InkyBrandHeader: View {
    var body: some View {
        Label("Inky Studio", systemImage: "photo")
            .font(.title3.weight(.bold)).labelStyle(.titleAndIcon)
            .accessibilityAddTraits(.isHeader)
    }
}

private struct ScanPhotoSymbol: View {
    @ScaledMetric(relativeTo: .largeTitle) private var size = 112
    var body: some View {
        ZStack {
            Image(systemName: "viewfinder").font(.system(size: size, weight: .ultraLight))
            Image(systemName: "photo").font(.system(size: size * 0.46, weight: .light))
        }.frame(height: size).accessibilityHidden(true)
    }
}

struct SupportPrivacyLinks: View {
    let identifierPrefix: String
    static let privacyURL = URL(string: "https://inky-studio.netlify.app/confidentialite.html")!

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Aide et confidentialité").font(.headline).accessibilityAddTraits(.isHeader)
            Link(destination: URL(string: "https://inky-studio.netlify.app/support.html")!) {
                linkLabel("Support", systemImage: "questionmark.circle")
            }
            .accessibilityLabel("Support Inky Studio")
            .accessibilityHint("Ouvre le site de support dans le navigateur.")
            .accessibilityIdentifier("\(identifierPrefix).support")
            Divider()
            Link(destination: Self.privacyURL) { linkLabel("Confidentialité", systemImage: "hand.raised") }
                .accessibilityLabel("Politique de confidentialité")
                .accessibilityHint("Ouvre la politique de confidentialité dans le navigateur.")
                .accessibilityIdentifier("\(identifierPrefix).privacy")
        }.buttonStyle(.plain).bentoCard()
    }

    private func linkLabel(_ title: String, systemImage: String) -> some View {
        HStack(spacing: 12) {
            Label(title, systemImage: systemImage).fixedSize(horizontal: false, vertical: true)
            Spacer(minLength: 0)
            Image(systemName: "arrow.up.right").foregroundStyle(Bento.secondaryInk).accessibilityHidden(true)
        }.font(.body).foregroundStyle(Bento.blue)
            .frame(maxWidth: .infinity, minHeight: 44, alignment: .leading).contentShape(Rectangle())
    }
}

#if DEBUG && targetEnvironment(simulator)
private struct QRInputFixture: View {
    let accept: (String) -> Void
    @State private var value = ""
    var body: some View {
        VStack(spacing: 16) {
            TextField("QR synthétique", text: $value).textInputAutocapitalization(.never).autocorrectionDisabled()
                .accessibilityIdentifier("connection.testQR")
            Button("Lire le QR synthétique") {
                let text = value
                value = ""
                accept(text)
            }.accessibilityIdentifier("connection.acceptTestQR")
        }.padding(20).bentoCard()
    }
}
#endif
