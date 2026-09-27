import SwiftUI

struct SettingsView: View {
    @EnvironmentObject private var store: AppStore
    @State private var draft = FrameSettings()
    @State private var enableBiometric = false
    @State private var changePassword = false
    @State private var bluetoothSetup = false
    @State private var confirmUpdate = false
    @State private var confirmForget = false
    @State private var loaded = false
    private var dirty: Bool { loaded && store.settings != draft }
    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 16) {
                    VStack(alignment: .leading, spacing: 16) {
                        Label("Programmation", systemImage: "clock").font(.headline).foregroundStyle(Bento.amber)
                        Picker("Mode de changement", selection: $draft.changeMode) {
                            Text("Quotidien").tag(ChangeMode.daily)
                            Text("Intervalle").tag(ChangeMode.interval)
                            Text("Manuel").tag(ChangeMode.manual)
                        }.pickerStyle(.segmented).accessibilityIdentifier("settings.mode")
                        if draft.changeMode == .daily {
                            HStack {
                                Text("Heure d’affichage").font(.subheadline)
                                Spacer()
                                Picker("Heure d’affichage", selection: $draft.changeHour) {
                                    ForEach(0..<24) { hour in Text(String(format: "%02d:00", hour)).tag(hour) }
                                }.labelsHidden().accessibilityIdentifier("settings.hour")
                            }
                            Text("Selon l’heure locale du Raspberry.").font(.caption).foregroundStyle(.secondary)
                        } else if draft.changeMode == .interval {
                            Stepper(value: $draft.changeIntervalMinutes, in: 1...1440) {
                                Text("Toutes les \(draft.changeIntervalMinutes) min").font(.subheadline)
                            }.accessibilityIdentifier("settings.interval")
                        } else {
                            Text("Les photos changent uniquement avec les commandes du cadre.").font(.caption).foregroundStyle(.secondary)
                        }
                    }.bentoCard()
                    VStack(alignment: .leading, spacing: 12) {
                        Label("Image", systemImage: "photo").font(.headline)
                        HStack { Text("Saturation"); Spacer(); Text(draft.saturation.formatted(.number.precision(.fractionLength(1)))).foregroundStyle(.secondary).monospacedDigit() }
                        Slider(value: $draft.saturation, in: 0...2, step: 0.1).accessibilityLabel("Saturation").accessibilityIdentifier("settings.saturation")
                        Text("La couleur est adaptée au panneau lors de l’affichage.").font(.caption).foregroundStyle(.secondary)
                    }.bentoCard()
                    Button { Task { await store.saveSettings(draft) } } label: {
                        if store.busy { ProgressView().tint(Bento.actionText) } else { Text("Enregistrer les réglages") }
                    }.buttonStyle(PrimaryButtonStyle()).disabled(!dirty || !store.canMutate).accessibilityIdentifier("settings.save")
                    VStack(alignment: .leading, spacing: 12) {
                        Label("Connexion", systemImage: "wifi").font(.headline)
                        Toggle(isOn: Binding(get: { store.biometricEnabled }, set: { enabled in
                            if enabled { enableBiometric = true } else { store.disableBiometrics() }
                        })) {
                            Label("Connexion avec \(store.biometricName)", systemImage: store.biometricName == "Face ID" ? "faceid" : "touchid")
                        }.tint(Bento.blue).disabled(store.vault.capability == nil && !store.biometricEnabled).accessibilityIdentifier("settings.biometric")
                        Text(store.vault.capability == nil ? "Configurez Face ID ou Touch ID dans les réglages de votre iPhone pour l’activer." : "Utiliser le mot de passe enregistré.")
                            .font(.caption).foregroundStyle(.secondary)
                        if store.bluetoothSupported || !store.connected {
                            Divider()
                            Button { bluetoothSetup = true } label: {
                                Label("Configurer le Wi-Fi du cadre", systemImage: "wifi")
                                    .frame(maxWidth: .infinity, minHeight: 44, alignment: .leading)
                            }.disabled(store.busy || store.displayBusy)
                                .accessibilityIdentifier("settings.bluetooth")
                        }
                        if store.passwordChangeSupported {
                            Divider()
                            Button { changePassword = true } label: {
                                Label("Changer le mot de passe du cadre", systemImage: "key")
                                    .frame(maxWidth: .infinity, minHeight: 44, alignment: .leading)
                            }.disabled(!store.canMutate || store.displayBusy)
                                .accessibilityIdentifier("settings.password")
                        }
                    }.bentoCard()
                    VStack(alignment: .leading, spacing: 14) {
                        Label("Mon cadre", systemImage: "photo.artframe").font(.headline)
                        if let display = store.state?.display {
                            VStack(alignment: .leading, spacing: 4) {
                                Text(display.model).font(.subheadline)
                                Text("\(display.width) × \(display.height) · \(display.colors) couleurs").font(.caption).foregroundStyle(.secondary)
                            }
                        }
                        Text(store.address).font(.caption).foregroundStyle(.secondary).textSelection(.enabled)
                        Divider()
                        HStack { Text("Version du Pi"); Spacer(); Text(store.version).foregroundStyle(.secondary) }.font(.subheadline)
                        Button { Task { await store.checkUpdate() } } label: {
                            HStack { Text("Vérifier les mises à jour"); Spacer(); Image(systemName: "arrow.clockwise") }.font(.subheadline).frame(minHeight: 44)
                        }.disabled(!store.canMutate).accessibilityIdentifier("settings.checkUpdate")
                        if let update = store.availableUpdate {
                            if update.updateAvailable, let version = update.latest {
                                Button("Installer la version \(version)") { confirmUpdate = true }.buttonStyle(OutlineButtonStyle()).disabled(!store.canMutate)
                            } else {
                                Text(update.latest == nil ? "La dernière version n’a pas pu être vérifiée." : "Votre Raspberry est à jour.").font(.caption).foregroundStyle(.secondary)
                            }
                        }
                        if let message = store.updateMessage { Label(message, systemImage: "arrow.down.circle").font(.caption).foregroundStyle(Bento.blue) }
                        Button("Se déconnecter", role: .destructive) { Task { await store.logout() } }
                            .font(.subheadline).frame(maxWidth: .infinity, minHeight: 44).accessibilityIdentifier("settings.logout")
                    }.bentoCard()
                    HStack(spacing: 12) {
                        Image(systemName: "circle.lefthalf.filled").foregroundStyle(.secondary)
                        Text("Apparence")
                        Spacer()
                        Text("Système").foregroundStyle(.secondary)
                    }.font(.subheadline).bentoCard().accessibilityElement(children: .combine)
                    Button("Oublier ce cadre", role: .destructive) { confirmForget = true }.font(.subheadline).frame(minHeight: 44)
                    Text("Inky Studio pour iPhone · \(Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "1.0")")
                        .font(.caption).foregroundStyle(.secondary).padding(.bottom, 16)
                }.padding(16).frame(maxWidth: 680).frame(maxWidth: .infinity)
            }.navigationTitle("Réglages").screenBackground()
                .task { if !loaded, let settings = store.settings { draft = settings; loaded = true } }
                .onChange(of: store.settings) { old, new in if !loaded || draft == old { if let new { draft = new; loaded = true } } }
                .sheet(isPresented: $enableBiometric) { BiometricSetupView() }
                .sheet(isPresented: $changePassword) { PasswordChangeView() }
                .sheet(isPresented: $bluetoothSetup) {
                    BluetoothSetupView(beginWindow: store.connected && store.bluetoothSupported ? {
                        try await store.beginBluetoothAdoption()
                    } : nil) { endpoint, owner in
                        await store.finishBluetoothSetup(endpoint: endpoint, owner: owner)
                    }
                }
                .confirmationDialog("Mettre à jour le Raspberry ?", isPresented: $confirmUpdate) {
                    Button("Installer la mise à jour") { Task { await store.startUpdate() } }
                } message: { Text("Le service va redémarrer. Une reconnexion sera ensuite nécessaire.") }
                .confirmationDialog("Oublier ce cadre sur cet iPhone ?", isPresented: $confirmForget) {
                    Button("Oublier ce cadre", role: .destructive) { Task { await store.logout(forget: true) } }
                } message: { Text("L’adresse et le mot de passe enregistré seront supprimés de cet iPhone. Les photos du cadre seront conservées.") }
        }
    }
}

private struct BiometricSetupView: View {
    @EnvironmentObject private var store: AppStore
    @Environment(\.dismiss) private var dismiss
    @State private var password = ""
    var body: some View {
        NavigationStack {
            VStack(alignment: .leading, spacing: 24) {
                Label("Activer \(store.biometricName)", systemImage: "faceid").font(.title2.weight(.bold))
                Text("Confirmez le mot de passe du cadre pour l’enregistrer dans le trousseau de cet iPhone.").foregroundStyle(.secondary)
                SecureField("Mot de passe du cadre", text: $password).textContentType(.password).textFieldStyle(.roundedBorder)
                Button {
                    Task { await store.enableBiometrics(password: password); if store.biometricEnabled { dismiss() } }
                } label: { if store.busy { ProgressView().tint(Bento.actionText) } else { Text("Activer") } }
                    .buttonStyle(PrimaryButtonStyle()).disabled(password.isEmpty || store.busy)
                if let error = store.errorMessage { Text(error).font(.subheadline).foregroundStyle(.red) }
                Spacer()
            }.padding(24).background(Bento.background)
                .toolbar { ToolbarItem(placement: .cancellationAction) { Button("Annuler") { dismiss() }.disabled(store.busy) } }
        }.presentationDetents([.medium, .large]).interactiveDismissDisabled(store.busy)
    }
}
