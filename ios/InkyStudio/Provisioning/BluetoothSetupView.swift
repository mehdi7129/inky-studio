import SwiftUI

enum BluetoothDiscoveryPresentation {
    static func shouldScan(stage: BluetoothSetupCoordinator.Stage, isActive: Bool, isUITestFixture: Bool) -> Bool {
        stage == .nearby && isActive && !isUITestFixture
    }
}

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
    private let authorize: (() async -> Bool)?
    private let onClose: (() -> Void)?
    private let routeFactoryCode: ((FrameBootstrapCode) -> Void)?
    private let routeFactoryOwner: ((OwnershipRecord) -> Void)?
    @State private var initialBootstrapCode: FrameBootstrapCode?
    @State private var initialFactoryOwner: OwnershipRecord?

    init(beginWindow: (() async throws -> Void)? = nil,
         initialBootstrapCode: FrameBootstrapCode? = nil,
         initialFactoryOwner: OwnershipRecord? = nil,
         authorize: (() async -> Bool)? = nil,
         onClose: (() -> Void)? = nil,
         routeFactoryCode: ((FrameBootstrapCode) -> Void)? = nil,
         routeFactoryOwner: ((OwnershipRecord) -> Void)? = nil,
         didFinishFactory: ((URL, OwnershipRecord, FactorySetupStatus) async -> Bool)? = nil,
         didFinish: @escaping (URL, OwnershipRecord) async -> Void) {
        let transport = BluetoothTransport()
        let channel = SecureBluetoothChannel(transport: transport)
        _transport = StateObject(wrappedValue: transport)
        _coordinator = StateObject(wrappedValue: BluetoothSetupCoordinator(channel: channel, vault: OwnershipVault(),
            softAPChannel: TCPProvisioningConnection(),
            confirmHTTPS: { endpoint, owner, transaction in
                try await InkyAPI.confirmProvisionedWiFi(endpoint: endpoint, owner: owner, transactionID: transaction)
            }, authorizeFactory: authorize, didFinishFactory: didFinishFactory, didFinish: didFinish))
        self.beginWindow = beginWindow
        self.authorize = authorize
        self.onClose = onClose
        self.routeFactoryCode = routeFactoryCode
        self.routeFactoryOwner = routeFactoryOwner
        _initialBootstrapCode = State(initialValue: initialBootstrapCode)
        _initialFactoryOwner = State(initialValue: initialFactoryOwner)
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
                            .accessibilityIdentifier("bluetooth.error")
                    }
                }.padding(20).frame(maxWidth: 540).frame(maxWidth: .infinity)
            }
            .navigationTitle(coordinator.isFactory ? "Configurer le cadre" : "Wi-Fi du cadre").screenBackground()
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button(coordinator.stage == .completed ? "Terminer" : "Fermer") {
                        if coordinator.hasTransaction { confirmClose = true }
                        else { onClose?(); coordinator.close(); dismiss() }
                    }.accessibilityIdentifier("bluetooth.close")
                }
            }
            .sheet(isPresented: $scanningQR) { scanner }
            .confirmationDialog("Quitter la vérification Wi-Fi ?", isPresented: $confirmClose) {
                Button("Quitter et reprendre plus tard") { onClose?(); coordinator.close(); dismiss() }
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
                if initialBootstrapCode != nil || initialFactoryOwner != nil {
                    guard await authorize?() == true else { return }
                    if let code = initialBootstrapCode {
                        initialBootstrapCode = nil
                        coordinator.acceptBootstrapCode(code)
                    } else if let owner = initialFactoryOwner {
                        initialFactoryOwner = nil
                        coordinator.selectSavedFrame(owner)
                    }
                }
            }
            .onChange(of: coordinator.stage) { _, stage in
                updateDiscovery(stage: stage, isActive: scenePhase == .active)
                if stage == .credentials { ssid = coordinator.selectedSSID }
                if stage == .suspended || stage == .completed { password = "" }
            }
            .onChange(of: scenePhase) { _, phase in
                if phase == .background {
                    transport.stopScan(); onClose?(); coordinator.suspend(); password = ""
                    initialBootstrapCode = nil
                } else if phase == .active, coordinator.stage == .suspended { Task { await coordinator.resume() } }
                updateDiscovery(stage: coordinator.stage, isActive: phase == .active)
            }
            .onDisappear { transport.stopScan(); onClose?(); coordinator.close(); password = ""; initialBootstrapCode = nil }
        }
        .preferredColorScheme(uiTestColorScheme)
    }

    private func updateDiscovery(stage: BluetoothSetupCoordinator.Stage, isActive: Bool) {
        if !coordinator.isSoftAP, BluetoothDiscoveryPresentation.shouldScan(stage: stage, isActive: isActive, isUITestFixture: coordinator.isUITestFixture) {
            transport.startScan(profile: coordinator.discoveryProfile)
        } else { transport.stopScan() }
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
        case .nearby: return coordinator.isSoftAP ? "Rejoindre votre cadre" : "Choisir le cadre à proximité"
        case .connecting, .claiming: return "Connexion au cadre"
        case .networks: return "Choisir un réseau Wi-Fi"
        case .credentials: return "Rejoindre ce réseau"
        case .applying: return "Configuration en cours"
        case .confirming: return "Vérifier la connexion"
        case .suspended: return "Reprendre la configuration"
        case .completed: return "Votre cadre est connecté"
        case .rolledBack: return "L’essai Wi-Fi est terminé"
        case .factoryCountry: return "Dans quel pays est le cadre ?"
        case .factoryApplying: return "Préparation du cadre"
        case .factoryContinue: return "Continuer la configuration"
        case .factoryHandoff: return "Vérification de la connexion sécurisée"
        case .factoryWaitingOrigin: return "Retrouver le cadre sur le réseau"
        case .factoryRecovery: return "Reprendre cette étape"
        case .factoryPhotoAccess: return "Votre cadre est prêt"
        case .softAPPrepared: return "L’essai Wi-Fi est prêt"
        case .softAPClaimRetry: return "Association non confirmée"
        }
    }
    private var message: String {
        switch coordinator.stage {
        case .introduction, .preparingQR, .scanQR:
            return "Scannez le QR affiché sur le cadre pour associer cet iPhone et configurer son Wi-Fi."
        case .nearby: return "Restez près du cadre. Son identité sera vérifiée avant de transmettre votre mot de passe Wi-Fi."
        case .connecting: return "Vérification de l’identité affichée sur votre cadre…"
        case .claiming: return "Enregistrement de l’autorisation de cet iPhone. L’écran du cadre peut prendre quelques instants à se rafraîchir."
        case .networks: return "Choisissez un réseau personnel WPA2. Les réseaux ouverts, d’entreprise ou avec portail de connexion ne sont pas pris en charge."
        case .credentials: return "Le mot de passe sera transmis au cadre par une connexion chiffrée."
        case .applying: return coordinator.isSoftAP ? "Le cadre enregistre cet essai avant de quitter son Wi-Fi temporaire." : "Le cadre essaie le nouveau réseau. L’ancien réseau reste disponible en cas d’échec."
        case .confirming: return "Sur cet iPhone, ouvrez Réglages → Wi-Fi et rejoignez « \(coordinator.selectedSSID) ». Revenez ensuite dans Inky Studio pour terminer la vérification."
        case .suspended: return coordinator.isSoftAP ? "Vos accès et l’identifiant de cet essai sont conservés. Si le cadre est revenu à son Wi-Fi temporaire, rejoignez-le pour retrouver son état." : "Restez près du cadre pour retrouver l’état de la configuration par Bluetooth."
        case .completed: return "L’accès au cadre a été vérifié sur le nouveau réseau. Vous pouvez retrouver vos photos."
        case .rolledBack: return "Le nouveau réseau n’a pas été confirmé. Le cadre conserve ses anciens réglages Wi-Fi."
        case .factoryCountry: return "Choisissez le pays où le cadre sera utilisé. L’heure sera fournie automatiquement par cet iPhone."
        case .factoryApplying: return "Le cadre vérifie ses réglages. Une étape déjà envoyée ne sera pas relancée automatiquement."
        case .factoryContinue: return "Poursuivez pour vérifier les étapes enregistrées sur le cadre."
        case .factoryHandoff: return "L’identité du même cadre est vérifiée sur sa connexion normale."
        case .factoryWaitingOrigin: return "Le cadre doit confirmer son adresse réseau avant d’ouvrir l’accès aux photos. Vous pouvez maintenant configurer son Wi-Fi."
        case .factoryRecovery: return "Le résultat précédent est conservé. Pour une nouvelle tentative, confirmez le pays puis relancez explicitement cette étape."
        case .factoryPhotoAccess: return "Terminez l’association pour accéder aux photos depuis cet iPhone."
        case .softAPPrepared: return "Les paramètres de cet essai sont enregistrés sur le cadre. Lancez-le explicitement pour passer au réseau domestique. Une tentative dont la réponse a été perdue n’est jamais relancée automatiquement."
        case .softAPClaimRetry: return "Cet iPhone a conservé sa demande d’association, mais le cadre ne l’a pas confirmée. Vous pouvez la renvoyer explicitement avec le QR que vous venez de scanner."
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
                        .font(.caption).foregroundStyle(Bento.secondaryInk)
                }
            }.bentoCard()
            if !coordinator.savedFrames.isEmpty {
                VStack(alignment: .leading, spacing: 12) {
                    Text("Cadres enregistrés").font(.headline)
                    ForEach(coordinator.savedFrames, id: \.id) { record in
                        Button {
                            Task {
                                if record.isFactory {
                                    if let routeFactoryOwner { routeFactoryOwner(record); dismiss(); return }
                                    guard await authorize?() == true else { return }
                                }
                                coordinator.selectSavedFrame(record)
                            }
                        } label: {
                            HStack {
                                Image(systemName: "photo.artframe")
                                VStack(alignment: .leading, spacing: 3) {
                                    Text("Cadre · \(record.id.uuidString.prefix(6))").font(.subheadline.weight(.medium))
                                    Text(record.isFactorySetupPending ? "Reprendre la configuration" : (record.wifiTransactionID == nil ? "Changer le Wi-Fi" : "Reprendre la vérification Wi-Fi"))
                                        .font(.caption).foregroundStyle(Bento.secondaryInk)
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
            if coordinator.isSoftAP {
                VStack(alignment: .leading, spacing: 12) {
                    Text("L’iPhone va demander votre accord pour rejoindre le Wi-Fi temporaire du cadre. Son identité sera ensuite vérifiée avec le QR.")
                        .font(.subheadline)
                    Button("Rejoindre le Wi-Fi du cadre") {
                        Task { await coordinator.rejoinSoftAP() }
                    }.buttonStyle(PrimaryButtonStyle()).accessibilityIdentifier("softap.join")
                }.bentoCard()
            } else {
            VStack(alignment: .leading, spacing: 12) {
                if transport.discoveredFrames.isEmpty {
                    HStack(spacing: 12) {
                        if transport.isScanning { ProgressView() }
                        Text(transport.isScanning ? "Recherche de votre cadre…" : "Aucun cadre détecté").font(.subheadline)
                    }
                    Text("Vérifiez que le cadre est allumé et que le Bluetooth est autorisé sur cet iPhone.")
                        .font(.caption).foregroundStyle(Bento.secondaryInk)
                }
                if let error = transport.error { Text(error).font(.subheadline).foregroundStyle(Bento.danger) }
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
                Button("Relancer la recherche") { transport.startScan(profile: coordinator.discoveryProfile) }.frame(minHeight: 44)
            }.bentoCard()
            settingsLink
            }
        case .preparingQR, .connecting, .claiming, .applying, .factoryApplying, .factoryHandoff:
            HStack(spacing: 14) { ProgressView(); Text(coordinator.stage == .preparingQR ? "Préparation de l’écran du cadre…" : "Un instant…").font(.subheadline) }
                .frame(maxWidth: .infinity, alignment: .leading).bentoCard()
        case .factoryCountry, .factoryRecovery:
            countrySelection
            Button(coordinator.stage == .factoryRecovery ? "Lancer une nouvelle tentative" : "Préparer le cadre") {
                Task { await coordinator.beginFactorySystemSetup() }
            }.buttonStyle(PrimaryButtonStyle()).disabled(!FactorySetupValidation.country(coordinator.selectedCountry))
                .accessibilityIdentifier("factory.apply")
        case .factoryContinue:
            Button("Continuer") { Task { await coordinator.continueFactorySetup() } }
                .buttonStyle(PrimaryButtonStyle()).accessibilityIdentifier("factory.continue")
        case .factoryWaitingOrigin:
            HStack { ProgressView(); Text("Vérification de l’adresse du cadre…") }.bentoCard()
            Button("Configurer le Wi-Fi") { Task { await coordinator.configureFactoryWiFi() } }
                .buttonStyle(OutlineButtonStyle()).accessibilityIdentifier("factory.configureWiFi")
        case .factoryPhotoAccess:
            Label("La configuration du cadre est confirmée.", systemImage: "checkmark.shield").bentoCard()
            Button("Ouvrir mon cadre") { Task { await coordinator.finishFactoryPhotoAccess() } }
                .buttonStyle(PrimaryButtonStyle()).accessibilityIdentifier("factory.finish")
        case .networks:
            VStack(alignment: .leading, spacing: 12) {
                if coordinator.scanningNetworks { ProgressView("Recherche des réseaux…") }
                if let current = coordinator.currentSSID { Label("Réseau actuel : \(current)", systemImage: "wifi").font(.caption).foregroundStyle(Bento.secondaryInk) }
                ForEach(coordinator.networks) { network in
                    Button { coordinator.chooseNetwork(network) } label: {
                        HStack {
                            Image(systemName: network.supported ? "wifi" : "wifi.exclamationmark")
                            VStack(alignment: .leading, spacing: 3) {
                                Text(network.ssid).font(.subheadline.weight(.medium)).lineLimit(2)
                                if !network.supported { Text("Non compatible").font(.caption).foregroundStyle(Bento.secondaryInk) }
                            }
                            Spacer()
                            if network.supported { Image(systemName: "lock.fill").font(.caption) }
                        }.frame(minHeight: 48)
                    }.buttonStyle(.plain).disabled(!network.supported || coordinator.scanningNetworks)
                }
                Button("Actualiser les réseaux") { Task { await coordinator.scanNetworks() } }.frame(minHeight: 44).disabled(coordinator.scanningNetworks)
                Button("Saisir un autre réseau") { coordinator.chooseNetwork(nil) }.frame(minHeight: 44).disabled(coordinator.scanningNetworks)
            }.bentoCard()
            if coordinator.isFactory, coordinator.owner?.isFactorySetupPending == true {
                Button("Vérifier la fin de la configuration") { Task { await coordinator.continueFactorySetup() } }
                    .buttonStyle(OutlineButtonStyle()).disabled(coordinator.scanningNetworks)
                    .accessibilityIdentifier("factory.verifyCompletion")
            }
        case .credentials:
            VStack(alignment: .leading, spacing: 14) {
                TextField("Nom du réseau Wi-Fi", text: $ssid).textInputAutocapitalization(.never).autocorrectionDisabled()
                    .padding(12).background(Bento.background, in: RoundedRectangle(cornerRadius: 10)).accessibilityIdentifier("bluetooth.ssid")
                SecureField("Mot de passe Wi-Fi", text: $password).textContentType(.password)
                    .padding(12).background(Bento.background, in: RoundedRectangle(cornerRadius: 10)).accessibilityIdentifier("bluetooth.password")
                Text("Réseau personnel WPA2 uniquement.").font(.caption).foregroundStyle(Bento.secondaryInk)
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
                    Text("L’essai sera annulé s’il n’est pas confirmé dans \(remaining) s.").font(.caption).foregroundStyle(Bento.secondaryInk)
                }
                Text("La vérification reprend automatiquement à votre retour dans l’app.")
                    .font(.caption).foregroundStyle(Bento.secondaryInk)
            }.bentoCard()
            Button("Annuler l’essai Wi-Fi", role: .destructive) { Task { await coordinator.cancelWiFi() } }.frame(minHeight: 44)
        case .suspended:
            Button(coordinator.isSoftAP ? "Réessayer sur le réseau actuel" : "Reprendre par Bluetooth") { Task { await coordinator.resume() } }
                .buttonStyle(PrimaryButtonStyle()).accessibilityIdentifier("bluetooth.resume")
            if coordinator.isSoftAP {
                Button("Rejoindre le Wi-Fi temporaire du cadre") { Task { await coordinator.rejoinSoftAP() } }
                    .buttonStyle(OutlineButtonStyle()).accessibilityIdentifier("softap.recover")
                Button("Scanner le QR actuel du cadre") { coordinator.showScanner(); scanningQR = true }
                    .buttonStyle(OutlineButtonStyle()).accessibilityIdentifier("softap.rescan")
            }
            settingsLink
        case .completed:
            Label("Connecté à \(coordinator.selectedSSID)", systemImage: "checkmark.circle.fill")
                .font(.headline).foregroundStyle(Bento.success).bentoCard()
            Button("Retrouver mon cadre") { dismiss() }.buttonStyle(PrimaryButtonStyle())
        case .rolledBack:
            Button("Choisir un réseau") { Task { await coordinator.scanNetworks() } }.buttonStyle(PrimaryButtonStyle())
        case .softAPPrepared:
            Button("Lancer cet essai Wi-Fi") { Task { await coordinator.activatePreparedNetwork() } }
                .buttonStyle(PrimaryButtonStyle()).accessibilityIdentifier("softap.activatePrepared")
        case .softAPClaimRetry:
            Button("Associer avec ce QR") { Task { await coordinator.retrySoftAPClaim() } }
                .buttonStyle(PrimaryButtonStyle()).accessibilityIdentifier("softap.retryClaim")
        }
    }

    private var countrySelection: some View {
        VStack(alignment: .leading, spacing: 12) {
            Picker("Pays du cadre", selection: Binding(get: { coordinator.selectedCountry }, set: { coordinator.chooseCountry($0) })) {
                Text("Choisir un pays").tag("")
                ForEach(countryOptions, id: \.code) { country in Text(country.name).tag(country.code) }
            }.accessibilityIdentifier("factory.country")
            Text("L’heure est automatique. Le pays reste votre choix et sera vérifié par le cadre.")
                .font(.caption).foregroundStyle(Bento.secondaryInk)
        }.bentoCard()
    }
    private var countryOptions: [(code: String, name: String)] {
        if coordinator.isSoftAP { return [(code: "FR", name: "France")] }
        return Locale.Region.isoRegions.map(\.identifier).filter { FactorySetupValidation.country($0) }
            .map { (code: $0, name: Locale.current.localizedString(forRegionCode: $0) ?? $0) }
            .sorted { $0.name.localizedStandardCompare($1.name) == .orderedAscending }
    }
    private func acceptScannedCode(_ text: String) {
        Task {
            if let code = try? FrameBootstrapCode.parse(text) {
                if let routeFactoryCode { routeFactoryCode(code); scanningQR = false; dismiss(); return }
                guard await authorize?() == true else { return }
            }
            coordinator.acceptQRCode(text)
        }
    }

    private var settingsLink: some View {
        Link("Ouvrir les réglages d’Inky Studio", destination: URL(string: UIApplication.openSettingsURLString)!)
            .font(.subheadline).frame(minHeight: 44)
    }

    private var scanner: some View {
        NavigationStack {
            VStack(spacing: 20) {
                Text("Placez le QR affiché sur le cadre dans le viseur.").font(.subheadline).foregroundStyle(Bento.secondaryInk)
                #if DEBUG && targetEnvironment(simulator)
                if ProcessInfo.processInfo.arguments.contains("--uitesting") {
                    QRTestInput { text in scanningQR = false; acceptScannedCode(text) }
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
            case .success(let text): acceptScannedCode(text)
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
