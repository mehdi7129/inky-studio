import SwiftUI

struct QueueView: View {
    @EnvironmentObject private var store: AppStore
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize
    @State private var importing = false
    @State private var editing = false
    @State private var deleting: QueueEntry?
    var body: some View {
        NavigationStack {
            List {
                Section {
                    if store.queue.isEmpty {
                        EmptyCard(symbol: "square.stack", title: "La file est vide", message: "Ajoutez vos prochaines photos. Elles défileront à leur tour.")
                            .listRowBackground(Color.clear).listRowSeparator(.hidden)
                    }
                    ForEach(Array(store.queue.enumerated()), id: \.element.id) { index, entry in
                        rowLayout {
                            FramePhoto(photo: entry.photo, accessibilityDescription: "Photo \(index + 1) dans la file")
                                .frame(width: dynamicTypeSize.isAccessibilitySize ? nil : 98)
                            VStack(alignment: .leading, spacing: 6) {
                                Text(String(format: "%02d", index + 1)).font(.headline.monospacedDigit())
                                if index == 0 { Text("Prochaine photo").font(.caption).foregroundStyle(Bento.blue) }
                            }
                            if !dynamicTypeSize.isAccessibilitySize { Spacer(minLength: 0) }
                        }.padding(.vertical, 8).accessibilityIdentifier("queue.row.\(entry.photo.id)")
                            .accessibilityElement(children: .ignore)
                            .accessibilityLabel("Photo \(index + 1) dans la file\(index == 0 ? ", prochaine photo" : "")")
                            .listRowBackground(Bento.surface)
                            .swipeActions { Button("Retirer", role: .destructive) { deleting = entry }.accessibilityIdentifier("queue.remove.\(entry.photo.id)").disabled(!store.canMutate) }
                            .contextMenu {
                                if store.canMutate, index > 0 { Button("Monter", systemImage: "arrow.up") { move(index, by: -1) } }
                                if store.canMutate, index + 1 < store.queue.count { Button("Descendre", systemImage: "arrow.down") { move(index, by: 1) } }
                                Button("Retirer de la file", systemImage: "trash", role: .destructive) { deleting = entry }.disabled(!store.canMutate)
                            }
                            .moveDisabled(!store.canMutate).deleteDisabled(!store.canMutate)
                            .accessibilityAction(named: "Monter") { if store.canMutate, index > 0 { move(index, by: -1) } }
                            .accessibilityAction(named: "Descendre") { if store.canMutate, index + 1 < store.queue.count { move(index, by: 1) } }
                    }
                    .onMove { source, target in
                        var entries = store.queue
                        entries.move(fromOffsets: source, toOffset: target)
                        Task { await store.reorder(entries.map { $0.photo.id }) }
                    }
                    .onDelete { indices in if let index = indices.first { deleting = store.queue[index] } }
                } header: {
                    Text("\(store.queue.count) photo\(store.queue.count == 1 ? "" : "s") dans la file")
                        .font(.subheadline).textCase(nil)
                }
                if !store.queue.isEmpty {
                    Section {
                        Text("Maintenez une photo pour la déplacer, ou choisissez Modifier la file.").font(.caption).foregroundStyle(.secondary)
                        Button(editing ? "Terminer" : "Modifier la file") { withAnimation { editing.toggle() } }
                            .accessibilityIdentifier("queue.edit").disabled(!store.canMutate).frame(maxWidth: .infinity, minHeight: 44)
                    }.listRowBackground(Bento.surface)
                }
            }.listStyle(.insetGrouped).scrollContentBackground(.hidden).screenBackground()
                .contentMargins(.bottom, 24, for: .scrollContent)
                .environment(\.editMode, .constant(editing ? .active : .inactive))
                .navigationTitle("À suivre").toolbar {
                    ToolbarItem(placement: .topBarTrailing) { Button { importing = true } label: { Image(systemName: "plus.circle.fill").foregroundStyle(Bento.blue) }.accessibilityLabel("Ajouter une photo").disabled(!store.canMutate) }
                }
                .disabled(store.busy).refreshable { await store.refresh() }
                .confirmationDialog("Retirer cette photo de la file ?", isPresented: Binding(get: { deleting != nil }, set: { if !$0 { deleting = nil } })) {
                    Button("Retirer", role: .destructive) { if let deleting { Task { await store.remove(deleting) } }; deleting = nil }
                } message: { Text("Elle restera disponible dans l’historique si elle a déjà été affichée.") }
                .sheet(isPresented: $importing) { PhotoImportView(panelWidth: store.panelWidth, panelHeight: store.panelHeight) { data, filename in try await store.upload(data, filename: filename) } }
        }
    }
    private var rowLayout: AnyLayout {
        dynamicTypeSize.isAccessibilitySize ? AnyLayout(VStackLayout(alignment: .leading, spacing: 12)) : AnyLayout(HStackLayout(spacing: 12))
    }
    private func move(_ index: Int, by delta: Int) {
        var entries = store.queue
        entries.swapAt(index, index + delta)
        Task { await store.reorder(entries.map { $0.photo.id }) }
    }
}
