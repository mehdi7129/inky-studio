import Accessibility
import SwiftUI

@main
struct InkyStudioApp: App {
    @StateObject private var store = AppStore()
    var body: some Scene {
        WindowGroup {
            RootView().environmentObject(store).tint(Bento.ink)
                #if DEBUG
                .preferredColorScheme(uiTestAppearance)
                #endif
        }
    }

    #if DEBUG
    // The launch argument alone does not change UIKit's appearance on every
    // Simulator runtime. Scope this override to the explicit UI-test fixture.
    private var uiTestAppearance: ColorScheme? {
        let arguments = ProcessInfo.processInfo.arguments
        guard arguments.contains("--uitesting"),
              let index = arguments.firstIndex(of: "-AppleInterfaceStyle"),
              arguments.indices.contains(index + 1) else { return nil }
        switch arguments[index + 1].lowercased() {
        case "dark": return .dark
        case "light": return .light
        default: return nil
        }
    }
    #endif
}

struct RootView: View {
    @EnvironmentObject private var store: AppStore
    @Environment(\.scenePhase) private var phase
    @State private var selection = 0
    @State private var finishingPairing = false
    var body: some View {
        Group {
            if store.recoveringConnection {
                ConnectionView()
            } else if store.unlocking || (!store.localUnlocked && store.authenticated) ||
                        ((store.credentialStored || store.hasAdoptedFrame) && !store.authenticated && !store.connecting) {
                LocalLockView()
            } else if store.authenticated && store.localUnlocked && !store.connecting && !store.unlocking {
                VStack(spacing: 0) {
                    connectionBanners
                    TabView(selection: $selection) {
                        DashboardView().tabItem { Label("Cadre", systemImage: "photo") }.tag(0).accessibilityIdentifier("tab.frame")
                        QueueView().tabItem { Label("File", systemImage: "square.stack") }.tag(1).accessibilityIdentifier("tab.queue")
                        HistoryView().tabItem { Label("Historique", systemImage: "clock") }.tag(2).accessibilityIdentifier("tab.history")
                        SettingsView().tabItem { Label("Réglages", systemImage: "gearshape.fill") }.tag(3).accessibilityIdentifier("tab.settings")
                    }
                    .id(store.sessionIdentity)
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
        .background { ScenePrivacyAnchor() }
        .accessibilityHidden(phase != .active)
        .overlay {
            if phase != .active { PrivacyCoverView() }
        }
        .sheet(isPresented: $finishingPairing) { LANLoginScannerView() }
        .onChange(of: phase) { _, value in
            store.sceneChanged(value)
            if value == .background { finishingPairing = false }
        }
        .onChange(of: store.authenticated) { _, _ in selection = 0 }
        .onChange(of: store.sessionIdentity) { _, _ in selection = 0 }
        .onChange(of: store.notice) { previous, current in
            guard let message = current?.trimmingCharacters(in: .whitespacesAndNewlines),
                  !message.isEmpty,
                  message != previous?.trimmingCharacters(in: .whitespacesAndNewlines) else { return }
            AccessibilityNotification.Announcement(message).post()
        }
    }
    // Keep banners in the parent stack so nested navigation bars cannot
    // draw through them. Each message owns its vertical space.
    private var connectionBanners: some View {
        VStack(spacing: 0) {
            if store.pairingNeedsCompletion {
                VStack(alignment: .leading, spacing: 10) {
                    Label("Association à finaliser", systemImage: "lock.trianglebadge.exclamationmark")
                        .font(.subheadline.weight(.semibold))
                    if let message = store.credentialStorageError {
                        Text(message).font(.caption).fixedSize(horizontal: false, vertical: true)
                    }
                    if store.canRetryCredentialStorage {
                        Button("Enregistrer l’accès sur cet iPhone") {
                            Task { await store.retryCredentialStorage() }
                        }.frame(minHeight: 44).accessibilityIdentifier("connection.retryCredentialStorage")
                    } else {
                        Button("Terminer par QR") { finishingPairing = true }
                            .frame(minHeight: 44).disabled(!store.canScanLANLoginCode)
                            .accessibilityIdentifier("connection.finishPairingQR")
                    }
                }.frame(maxWidth: .infinity, alignment: .leading)
                    .padding(12).background(Color.orange.opacity(0.12))
                    .accessibilityIdentifier("connection.pairingIncomplete")
            } else if let message = store.credentialStorageError {
                HStack(alignment: .top, spacing: 10) {
                    Image(systemName: "lock.trianglebadge.exclamationmark")
                    Text(message).font(.caption).fixedSize(horizontal: false, vertical: true)
                    Spacer(minLength: 0)
                }.padding(12).background(Color.orange.opacity(0.12))
                    .accessibilityIdentifier("connection.credentialStorageError")
            }
            if !store.connected {
                HStack {
                    Image(systemName: "wifi.slash")
                    Text("Raspberry injoignable · données précédentes").font(.caption)
                    Spacer()
                    Button { Task { await store.refresh() } } label: {
                        Text("Réessayer").font(.caption.weight(.semibold))
                            .frame(minHeight: 44).contentShape(Rectangle())
                    }
                }.padding(12).background(Color.orange.opacity(0.12))
                .accessibilityIdentifier("connection.offline")
            }
            if let message = store.displayIssue {
                HStack(alignment: .top, spacing: 10) {
                    Image(systemName: "exclamationmark.triangle")
                    Text(message).font(.caption).fixedSize(horizontal: false, vertical: true)
                    Spacer(minLength: 0)
                }.padding(12).background(Color.orange.opacity(0.12))
                    .accessibilityIdentifier("connection.displayIssue")
            }
            if let message = store.errorMessage {
                HStack(alignment: .top) {
                    Text(message).font(.caption).fixedSize(horizontal: false, vertical: true)
                    Spacer(minLength: 4)
                    Button { store.errorMessage = nil } label: {
                        Image(systemName: "xmark").frame(width: 44, height: 44).contentShape(Rectangle())
                    }.accessibilityLabel("Fermer le message")
                }.padding(.leading, 16).padding(.vertical, 6).background(Color.red.opacity(0.07))
                .accessibilityIdentifier("connection.error")
            }
        }.fixedSize(horizontal: false, vertical: true)
    }
}
