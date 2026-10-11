import SwiftUI

/// Candidate-only entry; disabled unless explicitly opted in through launch/managed defaults.
enum BootstrapFeatures {
    static var enabled: Bool { UserDefaults.standard.bool(forKey: "factoryBootstrapEnabled") }
}

@MainActor struct BootstrapSetupView: View {
    @Environment(\.dismiss) private var dismiss
    @Environment(\.scenePhase) private var scenePhase
    @StateObject private var transport: BluetoothTransport
    @StateObject private var coordinator: BootstrapSetupCoordinator
    @State private var scanningQR = false

    init() {
        let transport = BluetoothTransport(profile: .bootstrap)
        _transport = StateObject(wrappedValue: transport)
        _coordinator = StateObject(wrappedValue: BootstrapSetupCoordinator(
            channel: BootstrapBluetoothChannel(transport: transport), vault: BootstrapOwnershipVault()))
    }
    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    VStack(alignment: .leading, spacing: 8) {
                        Text(title).font(.title2.weight(.bold))
                        Text(message).font(.subheadline).foregroundStyle(Bento.secondaryInk)
                    }
                    content
                    if let error = coordinator.errorMessage {
                        Label(error, systemImage: "exclamationmark.circle")
                            .font(.subheadline).foregroundStyle(Bento.danger)
                            .accessibilityIdentifier("bootstrap.error")
                    }
                }.padding(20).frame(maxWidth: 540).frame(maxWidth: .infinity)
            }.navigationTitle("Associer le cadre").screenBackground()
                .accessibilityIdentifier("bootstrap.scroll")
                .toolbar {
                    ToolbarItem(placement: .cancellationAction) {
                        Button("Fermer") { coordinator.close(); dismiss() }.accessibilityIdentifier("bootstrap.close")
                    }
                }
                .sheet(isPresented: $scanningQR) { scanner }
                .interactiveDismissDisabled(coordinator.isWorking)
                .task {
                    #if DEBUG
                    let arguments = ProcessInfo.processInfo.arguments
                    if let index = arguments.firstIndex(of: "--bootstrap-fixture"), arguments.indices.contains(index + 1),
                       coordinator.installUITestFixture(named: arguments[index + 1]) { return }
                    #endif
                    coordinator.loadSavedFrames()
                }
                .onChange(of: coordinator.stage) { _, stage in
                    if stage == .nearby && !coordinator.isUITestFixture { transport.startScan() }
                    else { transport.stopScan() }
                }
                .onChange(of: scenePhase) { _, phase in
                    if phase != .active { transport.stopScan(); coordinator.suspend() }
                    else if coordinator.stage == .suspended { Task { await coordinator.resume() } }
                }
                .onDisappear { transport.stopScan(); coordinator.close() }
        }.preferredColorScheme(uiTestColorScheme)
    }
    private var title: String {
        switch coordinator.stage {
        case .introduction, .scanQR: "Associer votre nouveau cadre"
        case .nearby: "Choisir le cadre à proximité"
        case .connecting, .checking: "Vérifier votre cadre"
        case .claiming: "Association en cours"
        case .suspended, .uncertain: "Vérifier l’association"
        case .recoveryRequired: "Association à vérifier"
        case .adoptedAwaitingPreparation: "Cadre associé"
        }
    }
    private var message: String {
        switch coordinator.stage {
        case .introduction, .scanQR:
            "Scannez le QR de premier démarrage affiché sur le cadre. L’association utilise le Bluetooth, sans réseau Wi-Fi."
        case .nearby:
            "Restez près du cadre. L’identité du QR sera vérifiée avant d’envoyer l’autorisation de cet iPhone."
        case .connecting: "Vérification de l’identité du cadre par Bluetooth…"
        case .checking: "Recherche de votre association enregistrée…"
        case .claiming: "Enregistrement de cet iPhone sur le cadre…"
        case .suspended, .uncertain:
            coordinator.hasSavedIntention
                ? "Votre autorisation est conservée sur cet iPhone. Reprenez par Bluetooth pour vérifier si le cadre a terminé l’association."
                : "Reprenez par Bluetooth pour vérifier l’identité du cadre. L’autorisation doit être enregistrée sur cet iPhone avant l’association."
        case .recoveryRequired:
            "Vérifiez l’écran du cadre et le message ci-dessous avant de reprendre par Bluetooth."
        case .adoptedAwaitingPreparation:
            "Cet iPhone est associé au cadre. La préparation du cadre reste en attente ; les photos et la configuration Wi-Fi ne sont pas encore disponibles dans ce parcours."
        }
    }
    @ViewBuilder private var content: some View {
        switch coordinator.stage {
        case .introduction, .scanQR:
            VStack(alignment: .leading, spacing: 12) {
                Label("Premier démarrage", systemImage: "photo.artframe").font(.headline)
                Text("Le QR doit être visible sur votre cadre. Aucun mot de passe Wi-Fi n’est demandé à cette étape.")
                    .font(.subheadline).foregroundStyle(Bento.secondaryInk)
                Button { coordinator.showScanner(); scanningQR = true } label: {
                    Label("Scanner le QR du cadre", systemImage: "qrcode.viewfinder")
                }.buttonStyle(PrimaryButtonStyle()).accessibilityIdentifier("bootstrap.scanQR")
            }.bentoCard()
            if !coordinator.savedFrames.isEmpty {
                VStack(alignment: .leading, spacing: 12) {
                    Text("Associations enregistrées").font(.headline)
                    ForEach(coordinator.savedFrames) { record in
                        Button { coordinator.selectSavedFrame(record) } label: {
                            HStack(spacing: 12) {
                                Image(systemName: "photo.artframe")
                                VStack(alignment: .leading, spacing: 3) {
                                    Text("Cadre · \(record.id.uuidString.prefix(6))").font(.subheadline.weight(.medium))
                                    Text(record.state == .pending ? "Vérifier l’association" : "Préparation en attente")
                                        .font(.caption).foregroundStyle(Bento.secondaryInk)
                                }
                                Spacer(); Image(systemName: "chevron.right").font(.caption)
                            }.frame(minHeight: 48)
                        }.buttonStyle(.plain)
                    }
                }.bentoCard()
            }
        case .nearby:
            VStack(alignment: .leading, spacing: 12) {
                if transport.discoveredFrames.isEmpty {
                    HStack(spacing: 12) {
                        if transport.isScanning { ProgressView() }
                        Text(transport.isScanning ? "Recherche de votre cadre…" : "Aucun cadre détecté").font(.subheadline)
                    }
                }
                Text("Vérifiez que le cadre est allumé et que le Bluetooth est autorisé sur cet iPhone.")
                    .font(.caption).foregroundStyle(Bento.secondaryInk)
                if let error = transport.error { Text(error).font(.subheadline).foregroundStyle(Bento.danger) }
                ForEach(transport.discoveredFrames) { frame in
                    Button { Task { await coordinator.connect(peripheralID: frame.id) } } label: {
                        HStack {
                            Image(systemName: "photo.artframe"); Text(frame.name).font(.subheadline.weight(.medium))
                            Spacer(); Image(systemName: "chevron.right").font(.caption)
                        }.frame(minHeight: 48)
                    }.buttonStyle(.plain).accessibilityIdentifier("bootstrap.frame")
                }
                Button("Relancer la recherche") { transport.startScan() }.frame(minHeight: 44)
            }.bentoCard()
        case .connecting, .checking, .claiming:
            HStack(spacing: 14) { ProgressView(); Text("Un instant…").font(.subheadline) }
                .frame(maxWidth: .infinity, alignment: .leading).bentoCard()
        case .suspended, .uncertain, .recoveryRequired:
            VStack(alignment: .leading, spacing: 12) {
                Label(!coordinator.hasSavedIntention ? "Vérifier l’association" : "Autorisation conservée", systemImage: "lock.shield").font(.headline)
                Text(!coordinator.hasSavedIntention ? "L’association n’a pas pu être préparée sur cet iPhone." : "Une réponse manquante ne permet pas de savoir si l’association est terminée.")
                    .font(.subheadline).foregroundStyle(Bento.secondaryInk)
                Button { Task { await coordinator.resume() } } label: { Text("Reprendre par Bluetooth") }
                    .buttonStyle(PrimaryButtonStyle()).accessibilityIdentifier("bootstrap.resume")
                Button("Scanner un QR affiché sur le cadre") { coordinator.showScanner(); scanningQR = true }
                    .frame(minHeight: 44).accessibilityIdentifier("bootstrap.rescan")
            }.bentoCard()
        case .adoptedAwaitingPreparation:
            VStack(alignment: .leading, spacing: 12) {
                Label("Cet iPhone est associé", systemImage: "checkmark.circle.fill")
                    .font(.headline).foregroundStyle(Bento.success)
                Divider()
                Label("Préparation du cadre en attente", systemImage: "clock")
                    .font(.subheadline.weight(.medium)).foregroundStyle(Bento.secondaryInk)
                Text("Vous pourrez retrouver cette association à votre retour dans l’app.")
                    .font(.caption).foregroundStyle(Bento.secondaryInk)
            }.bentoCard().accessibilityIdentifier("bootstrap.pendingPreparation")
            Button("Terminer") { coordinator.close(); dismiss() }.buttonStyle(PrimaryButtonStyle())
        }
        if coordinator.stage != .adoptedAwaitingPreparation {
            Link("Ouvrir les réglages d’Inky Studio", destination: URL(string: UIApplication.openSettingsURLString)!)
                .font(.subheadline).frame(minHeight: 44)
        }
    }
    private var scanner: some View {
        NavigationStack {
            VStack(spacing: 20) {
                Text("Placez le QR de premier démarrage dans le viseur.").font(.subheadline).foregroundStyle(Bento.secondaryInk)
                QRScannerView { result in
                    scanningQR = false
                    switch result {
                    case .success(let text): coordinator.acceptQRCode(text)
                    case .failure(let error): coordinator.scannerFailed(error)
                    }
                }.clipShape(RoundedRectangle(cornerRadius: 20)).frame(minHeight: 280)
            }.padding(20).background(Bento.background).navigationTitle("Scanner le cadre")
                .navigationBarTitleDisplayMode(.inline)
                .toolbar { ToolbarItem(placement: .cancellationAction) { Button("Annuler") { scanningQR = false } } }
        }
    }
    private var uiTestColorScheme: ColorScheme? {
        #if DEBUG
        guard coordinator.isUITestFixture else { return nil }
        let arguments = ProcessInfo.processInfo.arguments
        guard let index = arguments.firstIndex(of: "-AppleInterfaceStyle"), arguments.indices.contains(index + 1) else { return nil }
        if arguments[index + 1] == "Dark" { return .dark }
        if arguments[index + 1] == "Light" { return .light }
        #endif
        return nil
    }
}
