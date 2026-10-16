import SwiftUI

struct GettingStartedView: View {
    @Environment(\.dismiss) private var dismiss
    @EnvironmentObject private var store: AppStore
    var allowWiFiSetup = false
    @State private var bluetoothSetup = false

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    VStack(alignment: .leading, spacing: 8) {
                        Text("Vos photos, simplement.").font(.title.weight(.bold))
                        Text("Le QR du cadre suffit pour commencer.").foregroundStyle(Bento.secondaryInk)
                    }.padding(.vertical, 8)
                    step("1", title: "Allumer le cadre", symbol: "photo.artframe") {
                        Text("Votre cadre Inky doit être prêt et afficher son QR de connexion.")
                        Text("Si aucun QR n’est visible, consultez l’aide de votre cadre. L’app ne prépare pas un Raspberry vierge.")
                            .foregroundStyle(Bento.secondaryInk)
                    }
                    step("2", title: "Rejoindre le même Wi-Fi", symbol: "wifi") {
                        Text("Connectez cet iPhone au même réseau local que le cadre.")
                        Text("Autorisez Réseau local et Appareil photo quand iOS le demande. Certains réseaux invités empêchent les appareils de communiquer entre eux.")
                            .foregroundStyle(Bento.secondaryInk)
                    }
                    step("3", title: "Scanner le QR", symbol: "qrcode.viewfinder") {
                        Text("Touchez Scanner un QR code, puis visez le code affiché sur le cadre.")
                        Text("L’accès est protégé par Face ID, Touch ID ou le code de cet iPhone. Configurez un code iPhone pour utiliser Inky Studio.")
                            .foregroundStyle(Bento.secondaryInk)
                        Text("Après la connexion, l’accès est conservé dans le trousseau sécurisé. Déverrouillez l’app pour retrouver votre cadre, sans scanner à chaque fois.")
                            .foregroundStyle(Bento.secondaryInk)
                        Text("Pour partager les photos avec un autre iPhone, le propriétaire peut créer une invitation dans Réglages → Partager l’accès. Scannez ce QR dans les cinq minutes ; il est utilisable une seule fois.")
                            .foregroundStyle(Bento.secondaryInk)
                    }
                    step("4", title: "Ajouter votre première photo", symbol: "photo.badge.plus") {
                        Text("Prenez une photo ou choisissez-en une dans Photos. Ajustez son cadrage, puis ajoutez-la à la file.")
                        Text("Touchez Suivante pour l’afficher, ou choisissez une programmation dans Réglages. Un rafraîchissement e-ink peut prendre environ une minute.")
                            .foregroundStyle(Bento.secondaryInk)
                    }
                    DisclosureGroup {
                        VStack(alignment: .leading, spacing: 18) {
                            help("Le cadre ne se connecte pas", "Vérifiez qu’il est allumé et sur le même Wi-Fi que l’iPhone. Autorisez Réseau local et Appareil photo dans les réglages iOS. La connexion au cadre n’est pas disponible à distance via le réseau mobile.")
                            Link("Ouvrir les réglages iOS", destination: URL(string: UIApplication.openSettingsURLString)!)
                                .frame(minHeight: 44).accessibilityIdentifier("guide.iosSettings")
                            help("Le QR n’est plus affiché", "L’accès déjà enregistré sur cet iPhone se retrouve en déverrouillant l’app. Si vous avez oublié le cadre ou changé d’iPhone, suivez l’aide du cadre pour retrouver un QR de connexion.")
                            help("Changer le Wi-Fi du cadre", "Depuis un cadre connecté, ouvrez Réglages → Configurer le Wi-Fi du cadre pour associer cet iPhone par Bluetooth. Un iPhone déjà associé peut ensuite retrouver le cadre à proximité. Les réseaux personnels WPA2 sont pris en charge ; les réseaux d’entreprise et portails d’hôtel ne le sont pas.")
                            if allowWiFiSetup && !store.isMediaPhotoAccess {
                                Button {
                                    Task {
                                        if !store.localUnlocked { await store.unlock() }
                                        if store.localUnlocked { bluetoothSetup = true }
                                    }
                                } label: {
                                    Label("Retrouver le cadre par Bluetooth", systemImage: "wifi")
                                        .frame(minHeight: 44)
                                }.accessibilityIdentifier("guide.bluetooth")
                            }
                            help("L’affichage n’est pas confirmé", "Vérifiez le cadre avant une nouvelle tentative manuelle. Une commande non confirmée ne prouve pas que la photo a été affichée. Vérifiez également la file avant de renvoyer une photo.")
                        }.padding(.top, 16)
                    } label: {
                        Label("Besoin d’aide ?", systemImage: "questionmark.circle").font(.headline)
                            .frame(minHeight: 44)
                    }.bentoCard().accessibilityIdentifier("guide.troubleshooting")
                    SupportPrivacyLinks(identifierPrefix: "guide")
                    Button("Fermer le guide") { dismiss() }
                        .buttonStyle(PrimaryButtonStyle()).accessibilityIdentifier("guide.connect")
                }.padding(20).frame(maxWidth: 600).frame(maxWidth: .infinity)
            }.accessibilityIdentifier("guide.scroll")
                .navigationTitle("Aide").screenBackground()
                .toolbar {
                    ToolbarItem(placement: .confirmationAction) {
                        Button("Fermer") { dismiss() }.accessibilityIdentifier("guide.close")
                    }
                }
                .sheet(isPresented: $bluetoothSetup) {
                    BluetoothSetupView { endpoint, owner in
                        await store.finishBluetoothSetup(endpoint: endpoint, owner: owner)
                    }
                }
        }
    }

    private func step<Content: View>(_ number: String, title: String, symbol: String,
                                    @ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Label("\(number). \(title)", systemImage: symbol)
                .font(.headline).foregroundStyle(Bento.blue).accessibilityAddTraits(.isHeader)
            content().font(.subheadline).fixedSize(horizontal: false, vertical: true)
        }.bentoCard()
    }

    private func help(_ title: String, _ message: String) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title).font(.subheadline.weight(.semibold)).accessibilityAddTraits(.isHeader)
            Text(message).font(.subheadline).foregroundStyle(Bento.secondaryInk).fixedSize(horizontal: false, vertical: true)
        }
    }
}
