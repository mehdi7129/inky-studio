import SwiftUI

struct HistoryView: View {
    @EnvironmentObject private var store: AppStore
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize
    @State private var deleting: HistoryEntry?
    @State private var clearAll = false
    private var days: [Date] { Set(store.history.map { Calendar.current.startOfDay(for: Date(timeIntervalSince1970: $0.displayedAt)) }).sorted(by: >) }
    var body: some View {
        NavigationStack {
            List {
                if store.history.isEmpty {
                    EmptyCard(symbol: "clock", title: "L’histoire commence ici", message: "Les photos affichées sur votre cadre apparaîtront ici.")
                        .listRowBackground(Color.clear).listRowSeparator(.hidden)
                }
                ForEach(days, id: \.self) { day in
                    Section {
                        ForEach(store.history.filter { Calendar.current.isDate(Date(timeIntervalSince1970: $0.displayedAt), inSameDayAs: day) }) { entry in
                            VStack(alignment: .leading, spacing: 12) {
                                rowLayout {
                                    FramePhoto(photo: entry.photo, accessibilityDescription: "Photo affichée le \(Date(timeIntervalSince1970: entry.displayedAt).formatted(date: .abbreviated, time: .shortened))")
                                        .frame(width: dynamicTypeSize.isAccessibilitySize ? nil : 112)
                                    VStack(alignment: .leading, spacing: 6) {
                                        Text("Affichée à").font(.caption).foregroundStyle(Bento.secondaryInk)
                                        Text(Date(timeIntervalSince1970: entry.displayedAt), style: .time).font(.headline)
                                    }
                                }
                                Button { Task { await store.requeue(entry) } } label: { Label("Remettre dans la file", systemImage: "plus") }
                                    .buttonStyle(OutlineButtonStyle()).disabled(!store.canMutate).accessibilityIdentifier("history.requeue.\(entry.id)")
                            }.padding(.vertical, 8).swipeActions { Button("Supprimer", role: .destructive) { deleting = entry }.disabled(!store.canMutate) }
                        }
                    } header: {
                        Text(dayLabel(day)).foregroundStyle(Bento.secondaryInk)
                    }
                    .listRowBackground(Bento.surface)
                }
                if store.hasMoreHistory {
                    Button { Task { await store.loadMoreHistory() } } label: {
                        if store.loadingHistory { ProgressView() } else { Text("Charger les photos précédentes") }
                    }.disabled(store.loadingHistory).frame(maxWidth: .infinity, minHeight: 44)
                        .accessibilityLabel("Charger les photos précédentes")
                        .accessibilityValue(store.loadingHistory ? "Chargement en cours" : "")
                }
            }.accessibilityIdentifier("history.list")
                .listStyle(.insetGrouped).scrollContentBackground(.hidden).screenBackground()
                .contentMargins(.bottom, 24, for: .scrollContent)
                .navigationTitle("Historique").refreshable { await store.refresh() }
                .toolbar { if !store.history.isEmpty { ToolbarItem(placement: .topBarTrailing) { Button { clearAll = true } label: { Image(systemName: "trash") }.accessibilityLabel("Vider l’historique").disabled(!store.canMutate) } } }
                .confirmationDialog("Supprimer cette entrée de l’historique ?", isPresented: Binding(get: { deleting != nil }, set: { if !$0 { deleting = nil } })) {
                    Button("Supprimer", role: .destructive) { if let deleting { Task { await store.deleteHistory(deleting) } }; deleting = nil }
                }
                .confirmationDialog("Vider tout l’historique ?", isPresented: $clearAll) {
                    Button("Vider l’historique", role: .destructive) { Task { await store.clearHistory() } }
                } message: { Text(store.isDemo ? "Cette action ne vide pas la file et n’efface pas la photo affichée dans la démo." : "Cette action ne vide pas la file et n’efface pas la photo sur l’écran physique.") }
        }
    }
    private var rowLayout: AnyLayout {
        dynamicTypeSize.isAccessibilitySize ? AnyLayout(VStackLayout(alignment: .leading, spacing: 14)) : AnyLayout(HStackLayout(spacing: 14))
    }
    private func dayLabel(_ date: Date) -> String {
        if Calendar.current.isDateInToday(date) { return "Aujourd’hui" }
        if Calendar.current.isDateInYesterday(date) { return "Hier" }
        return date.formatted(date: .abbreviated, time: .omitted)
    }
}
