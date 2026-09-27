import SwiftUI

struct PasswordChangeView: View {
    @EnvironmentObject private var store: AppStore
    @Environment(\.dismiss) private var dismiss
    @State private var current = ""
    @State private var new = ""
    @State private var confirmation = ""
    @State private var submitting = false
    @State private var failure: String?
    @State private var success: String?
    @FocusState private var focused: Field?
    private enum Field { case current, new, confirmation }

    private var valid: Bool {
        !current.isEmpty && (8...64).contains(new.unicodeScalars.count)
            && new == confirmation && new != current
    }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    if let success {
                        Label("Mot de passe modifié", systemImage: "checkmark.circle.fill")
                            .font(.title2.bold()).foregroundStyle(Bento.success)
                        Text(success).accessibilityIdentifier("password.success")
                        Button("Terminer") { dismiss() }.buttonStyle(PrimaryButtonStyle())
                    } else {
                        Text("Ce mot de passe protège l’accès à votre cadre.")
                            .foregroundStyle(.secondary)
                        VStack(alignment: .leading, spacing: 16) {
                            passwordField("Mot de passe actuel", value: $current, type: .password, field: .current)
                            passwordField("Nouveau mot de passe", value: $new, type: .newPassword, field: .new)
                            passwordField("Confirmer le mot de passe", value: $confirmation, type: .newPassword, field: .confirmation)
                            Text("8 à 64 caractères. Vous pouvez utiliser une phrase de passe.")
                                .font(.caption).foregroundStyle(.secondary)
                            if !confirmation.isEmpty && new != confirmation {
                                Text("Les nouveaux mots de passe ne correspondent pas.")
                                    .font(.caption).foregroundStyle(.red)
                            }
                        }.bentoCard()
                        if store.biometricEnabled {
                            Label("La connexion avec \(store.biometricName) sera mise à jour.", systemImage: "faceid")
                                .font(.subheadline).bentoCard()
                        }
                        Text("Les autres connexions au cadre seront fermées. Le mot de passe du Wi-Fi reste inchangé.")
                            .font(.subheadline).foregroundStyle(.secondary)
                        if let failure {
                            Label(failure, systemImage: "exclamationmark.circle")
                                .font(.subheadline).foregroundStyle(.red)
                                .accessibilityIdentifier("password.error")
                        }
                        Button(action: save) {
                            if submitting { ProgressView().tint(Bento.actionText) }
                            else { Text("Enregistrer le mot de passe") }
                        }.buttonStyle(PrimaryButtonStyle())
                            .disabled(!valid || submitting || !store.canMutate)
                            .accessibilityIdentifier("password.save")
                    }
                }.padding(20).frame(maxWidth: 680).frame(maxWidth: .infinity)
            }.screenBackground().navigationTitle("Mot de passe du cadre")
                .toolbar {
                    ToolbarItem(placement: .cancellationAction) {
                        if success == nil { Button("Annuler") { dismiss() }.disabled(submitting) }
                    }
                }
        }.interactiveDismissDisabled(submitting)
    }

    private func passwordField(_ title: String, value: Binding<String>, type: UITextContentType, field: Field) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title).font(.subheadline.weight(.medium))
            SecureField(title, text: value)
                .textContentType(type).textInputAutocapitalization(.never).autocorrectionDisabled()
                .textFieldStyle(.roundedBorder).focused($focused, equals: field)
                .submitLabel(field == .confirmation ? .done : .next)
                .accessibilityIdentifier("password.\(field)")
                .onSubmit {
                    switch field {
                    case .current: focused = .new
                    case .new: focused = .confirmation
                    case .confirmation: if valid && !submitting { save() }
                    }
                }
        }
    }

    private func save() {
        guard valid, !submitting else { return }
        focused = nil
        submitting = true
        failure = nil
        Task {
            let result = await store.changePassword(current: current, new: new)
            submitting = false
            switch result {
            case .success(let message):
                current = ""; new = ""; confirmation = ""
                success = message
            case .failure(let message): failure = message
            }
        }
    }
}
