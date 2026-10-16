import SwiftUI

struct SettingsView: View {
    var onShareAccess: () -> Void = {}
    @EnvironmentObject private var store: AppStore
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize
    @State private var draft = FrameSettings()
    @State private var bluetoothSetup = false
    @State private var confirmUpdate = false
    @State private var confirmForget = false
    @State private var gettingStarted = false
    @State private var loaded = false
    private var dirty: Bool { loaded && store.settings != draft }
    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 16) {
                    VStack(alignment: .leading, spacing: 16) {
                        Label("Programmation", systemImage: "clock").font(.headline).foregroundStyle(Bento.amber)
                        if dynamicTypeSize.isAccessibilitySize { modePicker.pickerStyle(.menu) }
                        else { modePicker.pickerStyle(.segmented) }
                        if draft.changeMode == .daily {
                            HStack {
                                Text("Heure d’affichage").font(.subheadline)
                                Spacer()
                                Picker("Heure d’affichage", selection: $draft.changeHour) {
                                    ForEach(0..<24) { hour in Text(String(format: "%02d:00", hour)).tag(hour) }
                                }.labelsHidden().accessibilityIdentifier("settings.hour")
                            }
                            Text("Selon l’heure locale du Raspberry.").font(.caption).foregroundStyle(Bento.secondaryInk)
                        } else if draft.changeMode == .interval {
                            Stepper(value: $draft.changeIntervalMinutes, in: 1...1440) {
                                Text(draft.changeIntervalMinutes == 1 ? "Toutes les minutes" : "Toutes les \(draft.changeIntervalMinutes) min").font(.subheadline)
                            }.accessibilityIdentifier("settings.interval")
                        } else {
                            Text("Utilisez Précédente et Suivante dans l’onglet Cadre pour changer de photo.").font(.caption).foregroundStyle(Bento.secondaryInk)
                        }
                    }.bentoCard()
                    if store.canAdminister { VStack(alignment: .leading, spacing: 12) {
                        Label("Image", systemImage: "photo").font(.headline)
                        HStack { Text("Saturation"); Spacer(); Text(draft.saturation.formatted(.number.precision(.fractionLength(1)))).foregroundStyle(Bento.secondaryInk).monospacedDigit() }
                        Slider(value: $draft.saturation, in: 0...2, step: 0.1).accessibilityLabel("Saturation").accessibilityIdentifier("settings.saturation")
                        Text("Les couleurs sont adaptées à l’écran lors de l’affichage.").font(.caption).foregroundStyle(Bento.secondaryInk)
                    }.bentoCard() }
                    Button { Task { await store.saveSettings(draft) } } label: {
                        if store.busy { ProgressView().tint(Bento.actionText) } else { Text("Enregistrer les réglages") }
                    }.buttonStyle(PrimaryButtonStyle()).disabled(!dirty || !store.canMutate).accessibilityIdentifier("settings.save")
                        .accessibilityLabel("Enregistrer les réglages")
                        .accessibilityValue(store.busy ? "Opération en cours" : "")
                    VStack(alignment: .leading, spacing: 12) {
                        Label("Accès protégé", systemImage: "lock.iphone").font(.headline)
                        Text("Face ID, Touch ID ou le code de cet iPhone est requis pour ouvrir Inky Studio.")
                            .font(.subheadline).foregroundStyle(Bento.secondaryInk)
                        Button { store.lock() } label: {
                            Label("Verrouiller l’app", systemImage: "lock")
                                .frame(maxWidth: .infinity, minHeight: 44, alignment: .leading)
                        }.accessibilityIdentifier("settings.lock")
                        if store.canAdminister && (store.bluetoothSupported || store.hasAdoptedFrame) {
                            Divider()
                            Button { bluetoothSetup = true } label: {
                                Label("Configurer le Wi-Fi du cadre", systemImage: "wifi")
                                    .frame(maxWidth: .infinity, minHeight: 44, alignment: .leading)
                            }.disabled(store.busy || store.displayBusy || store.pairingNeedsCompletion)
                                .accessibilityIdentifier("settings.bluetooth")
                        }
                    }.bentoCard()
                    VStack(alignment: .leading, spacing: 12) {
                        Label(store.photoAccessRole == .media ? "Accès partagé" : "Partager le cadre", systemImage: "person.2")
                            .font(.headline)
                        if store.photoAccessRole == .media {
                            Text("Vous pouvez ajouter des photos et choisir leur programmation. Le propriétaire gère les accès et la configuration du cadre.")
                                .font(.subheadline).foregroundStyle(Bento.secondaryInk)
                            if let deviceID = store.photoAccessDeviceID {
                                Text("Identifiant de cet accès : \(deviceID.uuidString.lowercased().prefix(8))")
                                    .font(.caption.monospaced()).foregroundStyle(Bento.secondaryInk)
                            }
                        } else {
                            Text("Invitez un autre iPhone à envoyer des photos, sans partager votre accès propriétaire.")
                                .font(.subheadline).foregroundStyle(Bento.secondaryInk)
                            Button { onShareAccess() } label: {
                                Label("Partager l’accès", systemImage: "qrcode")
                                    .frame(maxWidth: .infinity, minHeight: 44, alignment: .leading)
                            }.disabled(!store.canShareAccess).accessibilityIdentifier("settings.shareAccess")
                            if !store.canShareAccess {
                                Text("Le partage nécessite une association sécurisée avec le cadre.")
                                    .font(.caption).foregroundStyle(Bento.secondaryInk)
                            }
                        }
                    }.bentoCard()
                    VStack(alignment: .leading, spacing: 14) {
                        Label("Mon cadre", systemImage: "photo.artframe").font(.headline)
                        if let display = store.state?.display {
                            VStack(alignment: .leading, spacing: 4) {
                                Text(display.model).font(.subheadline)
                                Text("\(display.width) × \(display.height) · \(display.colors) couleurs").font(.caption).foregroundStyle(Bento.secondaryInk)
                            }
                        }
                        Divider()
                        HStack { Text("Version du cadre"); Spacer(); Text(store.version).foregroundStyle(Bento.secondaryInk) }.font(.subheadline)
                        if store.canAdminister { Button { Task { await store.checkUpdate() } } label: {
                            HStack { Text("Vérifier les mises à jour"); Spacer(); Image(systemName: "arrow.clockwise") }.font(.subheadline).frame(minHeight: 44)
                        }.disabled(!store.canMutate).accessibilityIdentifier("settings.checkUpdate")
                        if let update = store.availableUpdate {
                            if update.updateAvailable, let version = update.latest {
                                Button("Installer la version \(version)") { confirmUpdate = true }.buttonStyle(OutlineButtonStyle()).disabled(!store.canMutate)
                            } else {
                                Text(update.latest == nil ? "La dernière version n’a pas pu être vérifiée." : "Votre cadre est à jour.").font(.caption).foregroundStyle(Bento.secondaryInk)
                            }
                        }
                        if let message = store.updateMessage { Label(message, systemImage: "arrow.down.circle").font(.caption).foregroundStyle(Bento.blue) } }
                    }.bentoCard()
                    HStack(spacing: 12) {
                        Image(systemName: "circle.lefthalf.filled").foregroundStyle(Bento.secondaryInk)
                        Text("Apparence")
                        Spacer()
                        Text("Système").foregroundStyle(Bento.secondaryInk)
                    }.font(.subheadline).bentoCard().accessibilityElement(children: .combine)
                    SupportPrivacyLinks(identifierPrefix: "settings")
                    Button { gettingStarted = true } label: { Label("Premiers pas avec un cadre", systemImage: "questionmark.circle").frame(minHeight: 44) }
                        .accessibilityIdentifier("settings.guide")
                    Button("Oublier ce cadre", role: .destructive) { confirmForget = true }
                        .font(.subheadline).frame(minHeight: 44).accessibilityIdentifier("settings.forget")
                    Text("Inky Studio pour iPhone · \(Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "1.0")")
                        .font(.caption).foregroundStyle(Bento.secondaryInk).padding(.bottom, 16)
                }.padding(16).frame(maxWidth: 680).frame(maxWidth: .infinity)
            }.accessibilityIdentifier("settings.scroll")
                .navigationTitle("Réglages").screenBackground()
                .task { if !loaded, let settings = store.settings { draft = settings; loaded = true } }
                .onChange(of: store.settings) { old, new in if !loaded || draft == old { if let new { draft = new; loaded = true } } }
                .sheet(isPresented: $gettingStarted) { GettingStartedView(allowWiFiSetup: !store.isMediaPhotoAccess && store.hasAdoptedFrame && !store.pairingNeedsCompletion) }
                .sheet(isPresented: $bluetoothSetup) {
                    BluetoothSetupView(beginWindow: store.connected && store.bluetoothSupported ? {
                        try await store.beginBluetoothAdoption()
                    } : nil) { endpoint, owner in
                        await store.finishBluetoothSetup(endpoint: endpoint, owner: owner)
                    }
                }
                .confirmationDialog("Mettre à jour le cadre ?", isPresented: $confirmUpdate) {
                    Button("Installer la mise à jour") { Task { await store.startUpdate() } }
                } message: { Text("Le service va redémarrer. Une reconnexion sera ensuite nécessaire.") }
                .confirmationDialog("Oublier ce cadre sur cet iPhone ?", isPresented: $confirmForget) {
                    Button("Oublier ce cadre", role: .destructive) { Task { await store.logout(forget: true) } }
                } message: { Text("L’accès enregistré sera supprimé de cet iPhone. Les photos du cadre seront conservées. Un nouveau scan sera nécessaire pour vous reconnecter.") }
        }
    }
    private var modePicker: some View {
        Picker("Mode de changement", selection: $draft.changeMode) {
            Text("Quotidien").tag(ChangeMode.daily)
            Text("Intervalle").tag(ChangeMode.interval)
            Text("Manuel").tag(ChangeMode.manual)
        }.accessibilityIdentifier("settings.mode")
    }
}
