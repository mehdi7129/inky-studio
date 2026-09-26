import SwiftUI

struct ConnectionView: View {
    @EnvironmentObject private var store: AppStore
    @State private var password = ""
    @State private var showPassword = false
    @State private var remember = false
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
                        if store.connecting { ProgressView().tint(.white) }
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
                        if store.connecting { ProgressView().tint(.white) }
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
                if store.hasSavedFrame {
                    Button("Changer de cadre") { Task { await store.logout(forget: true); showPassword = false; password = ""; remember = false } }
                        .frame(maxWidth: .infinity, minHeight: 44).padding(.top, 8).disabled(store.connecting)
                }
            }.padding(20).frame(maxWidth: 540)
                .frame(maxWidth: .infinity)
        }.background(Bento.background).scrollDismissesKeyboard(.interactively)
            .onAppear { remember = store.biometricEnabled }
            .onChange(of: store.biometricEnabled) { _, enabled in remember = enabled }
    }
    private func connect() { passwordFocused = false; Task { await store.login(password: password, rememberBiometric: remember) } }
}
