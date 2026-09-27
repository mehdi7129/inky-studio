import SwiftUI

@MainActor
struct BluetoothSetupView: View {
    @Environment(\.dismiss) private var dismiss
    @Environment(\.scenePhase) private var scenePhase
    @StateObject private var transport: BluetoothTransport
    @StateObject private var coordinator: BluetoothSetupCoordinator
    @State private var scanningQR = false
    @State private var ssid = ""
    @State private var password = ""
    @State private var confirmClose = false
    private let beginWindow: (() async throws -> Void)?

    init(beginWindow: (() async throws -> Void)? = nil,
         didFinish: @escaping (URL, OwnershipRecord) async -> Void) {
        let transport = BluetoothTransport()
        let channel = SecureBluetoothChannel(transport: transport)
        _transport = StateObject(wrappedValue: transport)
        _coordinator = StateObject(wrappedValue: BluetoothSetupCoordinator(channel: channel, vault: OwnershipVault(),
            confirmHTTPS: { endpoint, owner, transaction in
                try await InkyAPI.confirmProvisionedWiFi(endpoint: endpoint, owner: owner, transactionID: transaction)
            }, didFinish: didFinish))
        self.beginWindow = beginWindow
    }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    VStack(alignment: .leading, spacing: 8) {
                        Text(title).font(.title2.weight(.bold))
                        Text(message).font(.subheadline).foregroundStyle(.secondary)
                    }
                    content
                    if let error = coordinator.errorMessage {
                        Label(error, systemImage: "exclamationmark.circle")
                            .font(.subheadline).foregroundStyle(.red)
                            .accessibilityIdentifier("bluetooth.error")
                    }
                }.padding(20).frame(maxWidth: 540).frame(maxWidth: .infinity)
            }
            .navigationTitle("Wi-Fi du cadre").screenBackground()
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button(coordinator.stage == .completed ? "Terminer" : "Fermer") {
                        if coordinator.hasTransaction { confirmClose = true }
                        else { coordinator.close(); dismiss() }
                    }.accessibilityIdentifier("bluetooth.close")
                }
            }
            .sheet(isPresented: $scanningQR) { scanner }
            .confirmationDialog("Quitter la vérification Wi-Fi ?", isPresented: $confirmClose) {
                Button("Quitter et reprendre plus tard") { coordinator.close(); dismiss() }
                Button("Continuer la vérification", role: .cancel) {}
            } message: {
                Text("Le cadre annulera l’essai s’il n’est pas confirmé à temps. Vous pourrez retrouver son état par Bluetooth.")
            }
            .interactiveDismissDisabled(coordinator.hasTransaction || coordinator.isWorking)
            .task {
                #if DEBUG
                let arguments = ProcessInfo.processInfo.arguments
                if let index = arguments.firstIndex(of: "--bluetooth-fixture"), arguments.indices.contains(index + 1),
                   coordinator.installUITestFixture(named: arguments[index + 1]) { return }
                #endif
                coordinator.loadSavedFrames()
            }
            .onChange(of: coordinator.stage) { _, stage in
                if stage == .nearby && !coordinator.isUITestFixture { transport.startScan() }
                else { transport.stopScan() }
                if stage == .credentials { ssid = coordinator.selectedSSID }
                if stage == .suspended || stage == .completed { password = "" }
            }
            .onChange(of: scenePhase) { _, phase in
                if phase != .active { transport.stopScan(); coordinator.suspend(); password = "" }
                else if coordinator.stage == .suspended { Task { await coordinator.resume() } }
            }
            .onDisappear { transport.stopScan(); coordinator.close(); password = "" }
        }
        .preferredColorScheme(uiTestColorScheme)
    }

    private var uiTestColorScheme: ColorScheme? {
        #if DEBUG
        guard coordinator.isUITestFixture else { return nil }
        let arguments = ProcessInfo.processInfo.arguments
        guard let index = arguments.firstIndex(of: "-AppleInterfaceStyle"), arguments.indices.contains(index + 1) else { return nil }
        switch arguments[index + 1] {
        case "Dark": return .dark
        case "Light": return .light
        default: return nil
        }
        #else
        return nil
        #endif
    }

    private var title: String {
        switch coordinator.stage {
        case .introduction, .preparingQR, .scanQR: return "Connecter votre cadre"
        case .nearby: return "Choisir le cadre à proximité"
        case .connecting, .claiming: return "Connexion au cadre"
        case .networks: return "Choisir un réseau Wi-Fi"
        case .credentials: return "Rejoindre ce réseau"
        case .applying: return "Configuration en cours"
        case .confirming: return "Vérifier la connexion"
        case .suspended: return "Reprendre la configuration"
        case .completed: return "Votre cadre est connecté"
        case .rolledBack: return "L’essai Wi-Fi est terminé"
        }
    }
    private var message: String {
        switch coordinator.stage {
        case .introduction, .preparingQR, .scanQR:
            return "Scannez le QR affiché sur le cadre pour associer cet iPhone. Le Bluetooth permet ensuite de changer son Wi-Fi."
        case .nearby: return "Restez près du cadre. Son identité sera vérifiée avant de transmettre votre mot de passe Wi-Fi."
        case .connecting: return "Vérification de l’identité affichée sur votre cadre…"
        case .claiming: return "Enregistrement de l’autorisation de cet iPhone. L’écran du cadre peut prendre quelques instants à se rafraîchir."
        case .networks: return "Choisissez un réseau personnel WPA2. Les réseaux ouverts, d’entreprise ou avec portail de connexion ne sont pas pris en charge."
        case .credentials: return "Le mot de passe sera transmis au cadre par une connexion chiffrée."
        case .applying: return "Le cadre essaie le nouveau réseau. L’ancien réseau reste disponible en cas d’échec."
        case .confirming: return "Connectez aussi cet iPhone au réseau « \(coordinator.selectedSSID) ». La configuration sera terminée après vérification de l’accès au cadre."
        case .suspended: return "Restez près du cadre pour retrouver l’état de la configuration par Bluetooth."
        case .completed: return "L’accès au cadre a été vérifié sur le nouveau réseau. Vous pouvez retrouver vos photos."
        case .rolledBack: return "Le nouveau réseau n’a pas été confirmé. Le cadre conserve ses anciens réglages Wi-Fi."
        }
    }

    @ViewBuilder private var content: some View {
        switch coordinator.stage {
        case .introduction, .scanQR:
            VStack(alignment: .leading, spacing: 16) {
                if let beginWindow {
                    Button {
                        Task { await coordinator.displayQR(using: beginWindow); if coordinator.stage == .scanQR { scanningQR = true } }
                    } label: { Label("Afficher le QR sur le cadre", systemImage: "qrcode") }
                        .buttonStyle(PrimaryButtonStyle()).accessibilityIdentifier("bluetooth.showQR")
                }
                Button { coordinator.showScanner(); scanningQR = true } label: {
                    Label("Scanner le QR du cadre", systemImage: "qrcode.viewfinder")
                }.buttonStyle(OutlineButtonStyle()).accessibilityIdentifier("bluetooth.scanQR")
                if beginWindow == nil {
                    Text("Pour une première association, affichez le QR depuis les réglages du cadre connecté. Un iPhone déjà associé peut retrouver le cadre ci-dessous.")
                        .font(.caption).foregroundStyle(.secondary)
                }
            }.bentoCard()
            if !coordinator.savedFrames.isEmpty {
                VStack(alignment: .leading, spacing: 12) {
                    Text("Cadres enregistrés").font(.headline)
                    ForEach(coordinator.savedFrames, id: \.id) { record in
                        Button { coordinator.selectSavedFrame(record) } label: {
                            HStack {
                                Image(systemName: "photo.artframe")
                                VStack(alignment: .leading, spacing: 3) {
                                    Text("Cadre · \(record.id.uuidString.prefix(6))").font(.subheadline.weight(.medium))
                                    Text(record.wifiTransactionID == nil ? "Changer le Wi-Fi" : "Reprendre la vérification Wi-Fi")
                                        .font(.caption).foregroundStyle(.secondary)
                                }
                                Spacer()
                                Image(systemName: "chevron.right").font(.caption)
                            }.frame(minHeight: 48)
                        }.buttonStyle(.plain)
                    }
                }.bentoCard()
            }
            if coordinator.errorMessage != nil { settingsLink }
        case .nearby:
            VStack(alignment: .leading, spacing: 12) {
                if transport.discoveredFrames.isEmpty {
                    HStack(spacing: 12) {
                        if transport.isScanning { ProgressView() }
                        Text(transport.isScanning ? "Recherche de votre cadre…" : "Aucun cadre détecté").font(.subheadline)
                    }
                    Text("Vérifiez que le cadre est allumé et que le Bluetooth est autorisé sur cet iPhone.")
                        .font(.caption).foregroundStyle(.secondary)
                }
                if let error = transport.error { Text(error).font(.subheadline).foregroundStyle(.red) }
                ForEach(transport.discoveredFrames) { frame in
                    Button { Task { await coordinator.connect(peripheralID: frame.id) } } label: {
                        HStack {
                            Image(systemName: "photo.artframe")
                            Text(frame.name).font(.subheadline.weight(.medium))
                            Spacer()
                            Image(systemName: "chevron.right").font(.caption)
                        }.frame(minHeight: 48)
                    }.buttonStyle(.plain).accessibilityIdentifier("bluetooth.frame")
                }
                Button("Relancer la recherche") { transport.startScan() }.frame(minHeight: 44)
            }.bentoCard()
            settingsLink
        case .preparingQR, .connecting, .claiming, .applying:
            HStack(spacing: 14) { ProgressView(); Text(coordinator.stage == .preparingQR ? "Préparation de l’écran du cadre…" : "Un instant…").font(.subheadline) }
                .frame(maxWidth: .infinity, alignment: .leading).bentoCard()
        case .networks:
            VStack(alignment: .leading, spacing: 12) {
                if coordinator.scanningNetworks { ProgressView("Recherche des réseaux…") }
                if let current = coordinator.currentSSID { Label("Réseau actuel : \(current)", systemImage: "wifi").font(.caption).foregroundStyle(.secondary) }
                ForEach(coordinator.networks) { network in
                    Button { coordinator.chooseNetwork(network) } label: {
                        HStack {
                            Image(systemName: network.supported ? "wifi" : "wifi.exclamationmark")
                            VStack(alignment: .leading, spacing: 3) {
                                Text(network.ssid).font(.subheadline.weight(.medium)).lineLimit(2)
                                if !network.supported { Text("Non compatible").font(.caption).foregroundStyle(.secondary) }
                            }
                            Spacer()
                            if network.supported { Image(systemName: "lock.fill").font(.caption) }
                        }.frame(minHeight: 48)
                    }.buttonStyle(.plain).disabled(!network.supported || coordinator.scanningNetworks)
                }
                Button("Actualiser les réseaux") { Task { await coordinator.scanNetworks() } }.frame(minHeight: 44).disabled(coordinator.scanningNetworks)
                Button("Saisir un autre réseau") { coordinator.chooseNetwork(nil) }.frame(minHeight: 44).disabled(coordinator.scanningNetworks)
            }.bentoCard()
        case .credentials:
            VStack(alignment: .leading, spacing: 14) {
                TextField("Nom du réseau Wi-Fi", text: $ssid).textInputAutocapitalization(.never).autocorrectionDisabled()
                    .padding(12).background(Bento.background, in: RoundedRectangle(cornerRadius: 10)).accessibilityIdentifier("bluetooth.ssid")
                SecureField("Mot de passe Wi-Fi", text: $password).textContentType(.password)
                    .padding(12).background(Bento.background, in: RoundedRectangle(cornerRadius: 10)).accessibilityIdentifier("bluetooth.password")
                Text("Réseau personnel WPA2 uniquement.").font(.caption).foregroundStyle(.secondary)
            }.bentoCard()
            Button("Connecter le cadre") {
                let secret = password
                password = ""
                Task { await coordinator.applyNetwork(ssid: ssid, password: secret) }
            }.buttonStyle(PrimaryButtonStyle()).disabled(!BluetoothSetupCoordinator.validWiFiInput(ssid: ssid, password: password))
                .accessibilityIdentifier("bluetooth.apply")
            Button("Choisir un autre réseau") { password = ""; Task { await coordinator.scanNetworks() } }.frame(minHeight: 44)
        case .confirming:
            VStack(alignment: .leading, spacing: 14) {
                HStack(spacing: 12) { ProgressView(); Text("Vérification de l’accès au cadre…").font(.subheadline) }
                if let remaining = coordinator.remainingSeconds, remaining > 0 {
                    Text("L’essai sera annulé s’il n’est pas confirmé dans \(remaining) s.").font(.caption).foregroundStyle(.secondary)
                }
                settingsLink
            }.bentoCard()
            Button("Annuler l’essai Wi-Fi", role: .destructive) { Task { await coordinator.cancelWiFi() } }.frame(minHeight: 44)
        case .suspended:
            Button("Reprendre par Bluetooth") { Task { await coordinator.resume() } }
                .buttonStyle(PrimaryButtonStyle()).accessibilityIdentifier("bluetooth.resume")
            settingsLink
        case .completed:
            Label("Connecté à \(coordinator.selectedSSID)", systemImage: "checkmark.circle.fill")
                .font(.headline).foregroundStyle(Bento.success).bentoCard()
            Button("Retrouver mon cadre") { dismiss() }.buttonStyle(PrimaryButtonStyle())
        case .rolledBack:
            Button("Choisir un réseau") { Task { await coordinator.scanNetworks() } }.buttonStyle(PrimaryButtonStyle())
        }
    }

    private var settingsLink: some View {
        Link("Ouvrir les réglages iOS", destination: URL(string: UIApplication.openSettingsURLString)!)
            .font(.subheadline).frame(minHeight: 44)
    }

    private var scanner: some View {
        NavigationStack {
            VStack(spacing: 20) {
                Text("Placez le QR affiché sur le cadre dans le viseur.").font(.subheadline).foregroundStyle(.secondary)
                #if DEBUG && targetEnvironment(simulator)
                if ProcessInfo.processInfo.arguments.contains("--uitesting") {
                    QRTestInput { text in scanningQR = false; coordinator.acceptQRCode(text) }
                } else { cameraScanner }
                #else
                cameraScanner
                #endif
            }.padding(20).background(Bento.background).navigationTitle("Scanner le cadre")
                .navigationBarTitleDisplayMode(.inline)
                .toolbar { ToolbarItem(placement: .cancellationAction) { Button("Annuler") { scanningQR = false } } }
        }
    }
    private var cameraScanner: some View {
        QRScannerView { result in
            scanningQR = false
            switch result {
            case .success(let text): coordinator.acceptQRCode(text)
            case .failure(let error): coordinator.scannerFailed(error)
            }
        }.clipShape(RoundedRectangle(cornerRadius: 20)).frame(minHeight: 280)
    }
}

#if DEBUG
private struct QRTestInput: View {
    let accept: (String) -> Void
    @State private var value = ""
    var body: some View {
        VStack {
            TextField("QR de test", text: $value).textInputAutocapitalization(.never).autocorrectionDisabled().accessibilityIdentifier("bluetooth.testQR")
            Button("Utiliser le QR de test") { accept(value); value = "" }.accessibilityIdentifier("bluetooth.acceptTestQR")
        }
    }
}
#endif
