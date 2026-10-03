import SwiftUI

struct GettingStartedView: View {
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    VStack(alignment: .leading, spacing: 8) {
                        Text("Un cadre, vos photos.").font(.title.weight(.bold))
                        Text("Quelques repères pour la première connexion.")
                            .foregroundStyle(Bento.secondaryInk)
                    }.padding(.vertical, 8)
                    step("1", title: "Préparer le cadre", symbol: "photo.artframe") {
                        Text("Il vous faut un Raspberry Pi, un écran Inky compatible et le serveur Inky Studio déjà installé sur le Raspberry.")
                        Text("L’app iPhone accompagne ce matériel. Elle n’installe pas le serveur sur un Raspberry vierge.").foregroundStyle(Bento.secondaryInk)
                    }
                    step("2", title: "Rejoindre le même Wi-Fi", symbol: "wifi") {
                        Text("Pour commencer, connectez l’iPhone et le cadre au même réseau local.")
                        Text("Saisissez le nom local du Raspberry ou son adresse IP, avec le port du serveur : par exemple inky.local:8000.")
                        Text("Autorisez « Réseau local » quand iOS le demande. Le partage des photos nécessite que les deux appareils puissent communiquer sur ce réseau.").foregroundStyle(Bento.secondaryInk)
                    }
                    step("3", title: "Ouvrir votre cadre", symbol: "key") {
                        Text("Utilisez le mot de passe de l’app du cadre. Il est distinct du mot de passe Wi-Fi et du compte Linux / SSH.")
                        Text("Vous pourrez activer Face ID si vous le souhaitez, puis personnaliser le mot de passe dans Réglages.").foregroundStyle(Bento.secondaryInk)
                    }
                    step("4", title: "Préparer les prochains voyages", symbol: "antenna.radiowaves.left.and.right") {
                        Text("Une fois connecté au cadre, ouvrez Réglages → Configurer le Wi-Fi du cadre, puis scannez son QR pour associer cet iPhone.")
                        Text("Cet iPhone déjà associé pourra ensuite transmettre un nouveau réseau au cadre par Bluetooth. La première association nécessite encore une connexion locale au cadre.")
                        Text("Privilégiez un réseau WPA2 personnel en 2,4 GHz. Les portails d’hôtel et réseaux d’entreprise ne sont pas pris en charge. L’app ne commande pas le cadre à distance via le réseau mobile.").foregroundStyle(Bento.secondaryInk)
                    }
                    DisclosureGroup {
                        VStack(alignment: .leading, spacing: 18) {
                            help("Cadre introuvable", "Vérifiez qu’il est allumé, que son serveur fonctionne et que l’adresse est correcte. Évitez les réseaux invités qui isolent les appareils. Dans Réglages iOS → Apps → Inky Studio, autorisez Réseau local si l’option est présente.")
                            if let settings = URL(string: UIApplication.openSettingsURLString) {
                                Link("Ouvrir les réglages iOS", destination: settings)
                                    .frame(minHeight: 44).accessibilityIdentifier("guide.iosSettings")
                            }
                            help("Retrouver le mot de passe", "Sur le Raspberry, la commande inky-studio password affiche le mot de passe initial s’il est encore disponible. Un mot de passe personnalisé n’est pas consultable : suivez la procédure de récupération locale sur le site de support.")
                            help("La photo met du temps à apparaître", "Un écran e-ink peut clignoter et prendre environ une minute pour s’actualiser. Attendez la fin du rafraîchissement avant de lancer une autre commande.")
                        }.padding(.top, 16)
                    } label: {
                        Label("Besoin d’un coup de main ?", systemImage: "questionmark.circle").font(.headline)
                            .frame(minHeight: 44)
                    }.bentoCard().accessibilityIdentifier("guide.troubleshooting")
                    SupportPrivacyLinks(identifierPrefix: "guide")
                    Button("Fermer le guide") { dismiss() }
                        .buttonStyle(PrimaryButtonStyle()).accessibilityIdentifier("guide.connect")
                }.padding(20).frame(maxWidth: 600).frame(maxWidth: .infinity)
            }.accessibilityIdentifier("guide.scroll")
                .navigationTitle("Premiers pas").screenBackground()
                .toolbar {
                    ToolbarItem(placement: .confirmationAction) {
                        Button("Fermer") { dismiss() }.accessibilityIdentifier("guide.close")
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
