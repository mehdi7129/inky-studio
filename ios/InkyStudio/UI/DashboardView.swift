import SwiftUI

struct DashboardView: View {
    @EnvironmentObject private var store: AppStore
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize
    @State private var importing = false
    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    Label(store.isDemo ? "Cadre simulé · aucune connexion" : store.connected ? "Raspberry connecté" : "Connexion interrompue", systemImage: store.isDemo ? "play.circle" : "circle.fill")
                        .font(.caption).foregroundStyle(store.connected ? Bento.success : Bento.secondaryInk)
                    if let current = store.state?.current {
                        VStack(alignment: .leading, spacing: 12) {
                            Text("Sur le cadre").font(.subheadline).foregroundStyle(.secondary)
                            FramePhoto(photo: current.photo, accessibilityDescription: "Photo actuellement affichée sur le cadre")
                            Text("Affichée \(Date(timeIntervalSince1970: current.displayedAt).formatted(date: .abbreviated, time: .shortened))")
                                .font(.caption).foregroundStyle(.secondary)
                            displayControls
                        }.bentoCard()
                    } else {
                        EmptyCard(symbol: "photo.on.rectangle", title: "Votre cadre vous attend", message: "Ajoutez une photo à la file, puis affichez-la avec Suivante.")
                        displayControls
                    }
                    if store.displayBusy {
                        HStack(spacing: 12) { ProgressView(); Text("Actualisation du cadre… Cela peut prendre une minute.").font(.subheadline) }.bentoCard()
                    }
                    summaryLayout {
                        VStack(alignment: .leading, spacing: 10) {
                            Image(systemName: "clock").font(.title2).foregroundStyle(Bento.amber)
                            Text("Prochain changement").font(.caption).foregroundStyle(.secondary)
                            Text(nextChange).font(.headline)
                        }.bentoCard().frame(maxWidth: .infinity, alignment: .topLeading)
                        VStack(alignment: .leading, spacing: 10) {
                            Image(systemName: "square.stack").font(.title2).foregroundStyle(Bento.blue)
                            Text("À suivre").font(.caption).foregroundStyle(.secondary)
                            Text("\(store.queue.count) photo\(store.queue.count == 1 ? "" : "s")").font(.headline)
                        }.bentoCard().frame(maxWidth: .infinity, alignment: .topLeading)
                    }
                    Button { importing = true } label: { Label("Ajouter une photo", systemImage: "plus") }
                        .buttonStyle(PrimaryButtonStyle()).disabled(!store.canMutate || store.state == nil).accessibilityIdentifier("frame.add")
                    if store.isDemo {
                        Text("Essayez les commandes et ajoutez une image. L’affichage est simulé ; rien n’est envoyé à un Raspberry.")
                            .font(.caption).foregroundStyle(.secondary)
                    } else if store.state?.display.isMock == true {
                        Label("Écran de démonstration", systemImage: "desktopcomputer").font(.caption).foregroundStyle(.secondary)
                    }
                }.padding(16).frame(maxWidth: 680).frame(maxWidth: .infinity)
            }.contentMargins(.bottom, 24, for: .scrollContent)
                .navigationTitle("Inky Studio").screenBackground().refreshable { await store.refresh() }
                .overlay { if store.state == nil && store.refreshing { ProgressView() } }
                .sheet(isPresented: $importing) { PhotoImportView(panelWidth: store.panelWidth, panelHeight: store.panelHeight) { data, filename in try await store.upload(data, filename: filename) } }
        }
    }
    private var displayControls: some View {
        controlsLayout {
            Button { Task { await store.display(previous: true) } } label: { Label("Précédente", systemImage: "chevron.left") }.accessibilityIdentifier("frame.previous")
            Button { Task { await store.display(previous: false) } } label: { Label("Suivante", systemImage: "chevron.right") }.accessibilityIdentifier("frame.next")
        }.buttonStyle(OutlineButtonStyle()).disabled(!store.canMutate || store.displayBusy)
    }
    private var summaryLayout: AnyLayout {
        dynamicTypeSize.isAccessibilitySize ? AnyLayout(VStackLayout(alignment: .leading, spacing: 12)) : AnyLayout(HStackLayout(alignment: .top, spacing: 12))
    }
    private var controlsLayout: AnyLayout {
        dynamicTypeSize.isAccessibilitySize ? AnyLayout(VStackLayout(spacing: 10)) : AnyLayout(HStackLayout(spacing: 10))
    }
    private var nextChange: String {
        if store.isDemo { return "À votre rythme" }
        guard let timestamp = store.state?.nextChangeAt else { return "Manuel" }
        return Date(timeIntervalSince1970: timestamp).formatted(.dateTime.day().month(.abbreviated).hour().minute())
    }
}
