import SwiftUI

struct ConnectionView: View {
    @EnvironmentObject private var store: AppStore
    @State private var password = ""
    @State private var showPassword = false
    @State private var remember = false
    @State private var bluetoothSetup = false
    @State private var gettingStarted = false
    @FocusState private var passwordFocused: Bool
    private var biometric: Bool { store.hasSavedFrame && store.biometricEnabled && !showPassword }
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                Label("Inky Studio", systemImage: "photo").font(.title3.weight(.bold)).padding(.top, 28)
                VStack(alignment: .leading, spacing: 8) {
                    Text(store.hasSavedFrame ? "Retrouver mon cadre" : "Bonjour, Inky.").font(.largeTitle.weight(.bold)).tracking(-1)
                    Text(store.hasSavedFrame ? "Votre cadre vous attend." : "Vos photos, sur votre cadre.").font(.title3).foregroundStyle(.secondary)
                }
                if !store.hasSavedFrame { discoveryActions }
                if store.hasSavedFrame {
                    HStack(spacing: 16) {
                        Image(systemName: "photo").font(.largeTitle).foregroundStyle(.secondary)
                        VStack(alignment: .leading, spacing: 4) {
                            Text("Mon cadre").font(.headline)
                            Text(store.address).font(.subheadline).foregroundStyle(.secondary).textSelection(.enabled)
                        }
                        Spacer(minLength: 0)
                    }.bentoCard()
                } else {
                    VStack(alignment: .leading, spacing: 10) {
                        Text("Adresse du Raspberry").font(.subheadline.weight(.medium))
                        TextField("inky.local:8000", text: $store.address).keyboardType(.URL).textContentType(.URL)
                            .textInputAutocapitalization(.never).autocorrectionDisabled()
                            .padding(12).background(Bento.background, in: RoundedRectangle(cornerRadius: 10))
                            .accessibilityIdentifier("connection.address")
                        Text("Saisissez son nom local ou son adresse IP.").font(.caption).foregroundStyle(.secondary)
                    }.bentoCard()
                }
                if biometric {
                    Image(systemName: store.biometricName == "Face ID" ? "faceid" : "touchid")
                        .font(.system(size: 84, weight: .ultraLight)).foregroundStyle(.secondary)
                        .frame(maxWidth: .infinity).padding(.vertical, 28).accessibilityHidden(true)
                    Button { Task { await store.loginWithBiometrics() } } label: {
                        if store.connecting { ProgressView().tint(Bento.actionText) }
                        else { Label("Se connecter avec \(store.biometricName)", systemImage: store.biometricName == "Face ID" ? "faceid" : "touchid") }
                    }.buttonStyle(PrimaryButtonStyle()).disabled(store.connecting).accessibilityIdentifier("connection.biometric")
                    Button("Utiliser le mot de passe") { showPassword = true; passwordFocused = true }
                        .buttonStyle(OutlineButtonStyle()).disabled(store.connecting)
                } else {
                    VStack(alignment: .leading, spacing: 14) {
                        SecureField("Mot de passe du cadre", text: $password).textContentType(.password)
                            .padding(14).background(Bento.background, in: RoundedRectangle(cornerRadius: 10))
                            .focused($passwordFocused).submitLabel(.go).onSubmit { connect() }
                            .accessibilityIdentifier("connection.password")
                        if let capability = store.vault.capability {
                            Toggle("Activer \(capability)", isOn: $remember).font(.subheadline).tint(Bento.blue)
                            Text("Autorise l’utilisation du mot de passe enregistré sur cet iPhone.").font(.caption).foregroundStyle(.secondary)
                        }
                    }.bentoCard()
                    Button(action: connect) {
                        if store.connecting { ProgressView().tint(Bento.actionText) }
                        else { Text("Se connecter") }
                    }.buttonStyle(PrimaryButtonStyle()).disabled(store.connecting || store.address.trimmingCharacters(in: .whitespaces).isEmpty)
                        .accessibilityIdentifier("connection.submit")
                    if store.biometricEnabled {
                        Button("Utiliser \(store.biometricName)") { showPassword = false }.frame(maxWidth: .infinity, minHeight: 44)
                    }
                }
                if store.connecting {
                    Button("Annuler la connexion") { store.cancelLogin() }
                        .frame(maxWidth: .infinity, minHeight: 44).accessibilityIdentifier("connection.cancel")
                }
                if let error = store.errorMessage {
                    Text(error).font(.subheadline).foregroundStyle(.red).accessibilityIdentifier("connection.error")
                    if let url = URL(string: UIApplication.openSettingsURLString) {
                        Link("Ouvrir les réglages iOS", destination: url).font(.subheadline)
                    }
                }
                Text("Votre iPhone et le cadre doivent être sur le même réseau Wi-Fi.")
                    .font(.subheadline).foregroundStyle(.secondary).multilineTextAlignment(.center).frame(maxWidth: .infinity)
                Button { bluetoothSetup = true } label: {
                    Label("Configurer le Wi-Fi du cadre", systemImage: "wifi")
                }.buttonStyle(OutlineButtonStyle()).disabled(store.connecting)
                    .accessibilityIdentifier("connection.bluetooth")
                Text("Pour un iPhone déjà associé au cadre. La première association se prépare après la connexion, dans Réglages.")
                    .font(.caption).foregroundStyle(.secondary)
                if store.hasSavedFrame {
                    Button("Changer de cadre") { Task { await store.logout(forget: true); showPassword = false; password = ""; remember = false } }
                        .frame(maxWidth: .infinity, minHeight: 44).padding(.top, 8).disabled(store.connecting)
                }
                if store.hasSavedFrame { discoveryActions }
                SupportPrivacyLinks(identifierPrefix: "connection")
            }.padding(20).frame(maxWidth: 540)
                .frame(maxWidth: .infinity)
        }.background(Bento.background).scrollDismissesKeyboard(.interactively)
            .onAppear { remember = store.biometricEnabled }
            .onChange(of: store.biometricEnabled) { _, enabled in remember = enabled }
            .sheet(isPresented: $gettingStarted) { GettingStartedView() }
            .sheet(isPresented: $bluetoothSetup) {
                BluetoothSetupView { endpoint, owner in
                    await store.finishBluetoothSetup(endpoint: endpoint, owner: owner)
                }
            }
    }
    private var discoveryActions: some View {
        VStack(alignment: .leading, spacing: 10) {
            Button { Task { password = ""; await store.enterDemo() } } label: {
                Label("Explorer la démo", systemImage: "play.circle")
            }.buttonStyle(OutlineButtonStyle()).disabled(store.connecting)
                .accessibilityIdentifier("connection.demo")
            Text("Découvrez l’app sans cadre. Les essais restent temporaires sur cet iPhone.")
                .font(.caption).foregroundStyle(.secondary)
            Button { gettingStarted = true } label: {
                Label("Préparer mon cadre", systemImage: "questionmark.circle")
                    .frame(maxWidth: .infinity, minHeight: 44, alignment: .leading)
            }.font(.subheadline.weight(.medium)).foregroundStyle(Bento.blue)
                .accessibilityIdentifier("connection.guide")
        }
    }

    private func connect() { passwordFocused = false; Task { await store.login(password: password, rememberBiometric: remember) } }
}

struct SupportPrivacyLinks: View {
    let identifierPrefix: String

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
            Link(destination: URL(string: "https://inky-studio.netlify.app/confidentialite.html")!) {
                linkLabel("Confidentialité", systemImage: "hand.raised")
            }
            .accessibilityLabel("Politique de confidentialité")
            .accessibilityHint("Ouvre la politique de confidentialité dans le navigateur.")
            .accessibilityIdentifier("\(identifierPrefix).privacy")
        }.buttonStyle(.plain).bentoCard()
    }

    private func linkLabel(_ title: String, systemImage: String) -> some View {
        HStack(spacing: 12) {
            Label(title, systemImage: systemImage)
                .fixedSize(horizontal: false, vertical: true)
            Spacer(minLength: 0)
            Image(systemName: "arrow.up.right").foregroundStyle(.secondary).accessibilityHidden(true)
        }
        .font(.body).foregroundStyle(Bento.blue)
        .frame(maxWidth: .infinity, minHeight: 44, alignment: .leading)
        .contentShape(Rectangle())
    }
}
