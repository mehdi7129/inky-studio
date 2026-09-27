import SwiftUI

@main
struct InkyStudioApp: App {
    @StateObject private var store = AppStore()
    var body: some Scene {
        WindowGroup {
            RootView().environmentObject(store).tint(Bento.ink)
        }
    }
}

struct RootView: View {
    @EnvironmentObject private var store: AppStore
    @Environment(\.scenePhase) private var phase
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize
    @State private var selection = 0
    var body: some View {
        Group {
            if store.authenticated {
                VStack(spacing: 0) {
                    if store.isDemo { demoBanner }
                    TabView(selection: $selection) {
                        DashboardView().tabItem { Label("Cadre", systemImage: "photo") }.tag(0).accessibilityIdentifier("tab.frame")
                        QueueView().tabItem { Label("File", systemImage: "square.stack") }.tag(1).accessibilityIdentifier("tab.queue")
                        HistoryView().tabItem { Label("Historique", systemImage: "clock") }.tag(2).accessibilityIdentifier("tab.history")
                        SettingsView().tabItem { Label("Réglages", systemImage: "gearshape.fill") }.tag(3).accessibilityIdentifier("tab.settings")
                    }
                    .id(store.sessionIdentity)
                    .safeAreaInset(edge: .top, spacing: 0) {
                        if !store.connected {
                            HStack {
                                Image(systemName: "wifi.slash")
                                Text("Raspberry injoignable · données précédentes").font(.caption)
                                Spacer()
                                Button("Réessayer") { Task { await store.refresh() } }.font(.caption.weight(.semibold))
                            }.padding(12).background(Color.orange.opacity(0.12))
                        }
                        if let message = store.errorMessage {
                            HStack(alignment: .top) {
                                Text(message).font(.caption).fixedSize(horizontal: false, vertical: true)
                                Spacer(minLength: 4)
                                Button { store.errorMessage = nil } label: { Image(systemName: "xmark").frame(width: 32, height: 32) }.accessibilityLabel("Fermer le message")
                            }.padding(.leading, 16).padding(.vertical, 6).background(Color.red.opacity(0.07))
                        }
                    }
                    .overlay(alignment: .bottom) {
                        if let notice = store.notice {
                            Text(notice).font(.subheadline).padding(14).background(.regularMaterial, in: RoundedRectangle(cornerRadius: 14))
                                .padding(.horizontal, 20).padding(.bottom, 80).allowsHitTesting(false)
                                .task(id: notice) { try? await Task.sleep(for: .seconds(4)); if store.notice == notice { store.notice = nil } }
                        }
                    }
                }
            } else { ConnectionView() }
        }
        .onChange(of: phase) { _, value in store.sceneActive(value == .active) }
        .onChange(of: store.authenticated) { _, _ in selection = 0 }
        .onChange(of: store.sessionIdentity) { _, _ in selection = 0 }
    }
    private var demoBanner: some View {
        HStack(spacing: 12) {
            Label(dynamicTypeSize.isAccessibilitySize ? "Démo" : "Démo · sur cet iPhone", systemImage: "play.circle")
                .font(.caption.weight(.medium)).fixedSize(horizontal: false, vertical: true)
                .accessibilityLabel("Démonstration locale, aucun cadre connecté")
                .accessibilityIdentifier("demo.banner")
            Spacer(minLength: 0)
            Button("Quitter") { store.exitDemo() }
                .font(.caption.weight(.semibold)).frame(minHeight: 44)
                .accessibilityLabel("Quitter la démo")
                .accessibilityIdentifier("demo.exit")
        }.padding(.horizontal, 16).background(Bento.surface)
    }
}
