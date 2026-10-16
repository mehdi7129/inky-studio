import CoreImage.CIFilterBuiltins
import SwiftUI

struct ShareAccessView: View {
    @EnvironmentObject private var store: AppStore
    @Environment(\.dismiss) private var dismiss
    @State private var confirmingRevocation: PhotoAccessDeviceSummary?

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    VStack(alignment: .leading, spacing: 12) {
                        Label("Des photos, à plusieurs.", systemImage: "person.2")
                            .font(.title2.bold()).accessibilityAddTraits(.isHeader)
                        Text("L’autre iPhone pourra envoyer des photos et choisir la programmation. Les réglages du cadre et les accès restent sous votre contrôle.")
                            .foregroundStyle(Bento.secondaryInk)
                        Text("Les deux iPhone doivent pouvoir rejoindre le même réseau Wi-Fi que le cadre.")
                            .font(.footnote).foregroundStyle(Bento.secondaryInk)
                    }.bentoCard()

                    if store.localUnlocked && store.canShareAccess {
                        if let invitation = store.activeInvitation {
                            invitationCard(invitation)
                        } else {
                            Button { Task { await store.createInvitation() } } label: {
                                Label("Créer une invitation", systemImage: "qrcode")
                            }.buttonStyle(PrimaryButtonStyle()).disabled(store.photoAccessBusy)
                                .accessibilityIdentifier("access.createInvitation")
                        }
                        if store.photoAccessBusy { ProgressView("Mise à jour des accès…").frame(maxWidth: .infinity) }
                        if let error = store.photoAccessError {
                            Text(error).font(.subheadline).foregroundStyle(Bento.danger)
                                .fixedSize(horizontal: false, vertical: true).accessibilityIdentifier("access.error")
                        }
                        devicesCard
                    } else {
                        Text("Déverrouillez l’app avec un accès propriétaire pour gérer le partage.")
                            .foregroundStyle(Bento.secondaryInk).bentoCard()
                    }
                }.padding(20).frame(maxWidth: 600).frame(maxWidth: .infinity)
            }.accessibilityIdentifier("access.scroll").screenBackground().navigationTitle("Partager l’accès")
                .navigationBarTitleDisplayMode(.inline)
                .toolbar { ToolbarItem(placement: .confirmationAction) {
                    Button("Fermer") {
                        store.cancelPhotoAccessOperation()
                        dismiss()
                    }.accessibilityIdentifier("access.close")
                } }
                .task { await store.refreshAccessDevices() }
                .confirmationDialog("Retirer l’accès de cet iPhone ?", isPresented: Binding(
                    get: { confirmingRevocation != nil },
                    set: { if !$0 { confirmingRevocation = nil } }
                )) {
                    if let device = confirmingRevocation {
                        Button("Retirer l’accès", role: .destructive) {
                            confirmingRevocation = nil
                            Task { await store.revokeAccessDevice(device.deviceID) }
                        }
                    }
                } message: {
                    Text("Cet iPhone ne pourra plus se connecter au cadre. Les photos déjà envoyées seront conservées.")
                }
        }.protectSensitiveContent()
    }

    private func invitationCard(_ invitation: PhotoAccessInvitation) -> some View {
        let image = invitationImage(invitation.code)
        return TimelineView(.periodic(from: .now, by: 1)) { context in
            let remaining = max(0, Int(ceil(invitation.expiresAt - context.date.timeIntervalSince1970)))
            VStack(spacing: 16) {
                if remaining > 0, let image = invitationImage(invitation.code) {
                    Image(uiImage: image).interpolation(.none).resizable().scaledToFit()
                        .padding(24).background(.white, in: RoundedRectangle(cornerRadius: 16))
                        .frame(maxWidth: 300).accessibilityHidden(true)
                        .accessibilityIdentifier("access.invitationQR")
                    Text("Scannez ce QR avec Inky Studio sur l’autre iPhone.")
                        .font(.headline).multilineTextAlignment(.center)
                    Text("Expire dans \(remaining / 60):\(String(format: "%02d", remaining % 60)) · Utilisable une seule fois")
                        .font(.footnote).monospacedDigit().foregroundStyle(Bento.secondaryInk)
                        .accessibilityIdentifier("access.invitationExpiry")
                    Button("Annuler cette invitation", role: .destructive) {
                        Task { await store.revokeActiveInvitation() }
                    }.frame(minHeight: 44).disabled(store.photoAccessBusy)
                        .accessibilityIdentifier("access.revokeInvitation")
                } else if remaining <= 0 {
                    Label("Invitation expirée", systemImage: "clock.badge.exclamationmark").font(.headline)
                    Text("Créez un nouveau QR pour inviter cet iPhone.")
                        .foregroundStyle(Bento.secondaryInk)
                    Button("Créer une nouvelle invitation") { Task { await store.createInvitation() } }
                        .buttonStyle(PrimaryButtonStyle()).disabled(store.photoAccessBusy)
                        .accessibilityIdentifier("access.renewInvitation")
                } else {
                    Label("QR indisponible", systemImage: "exclamationmark.triangle").font(.headline)
                    Text("Fermez puis rouvrez le partage pour réessayer d’afficher cette invitation.")
                        .foregroundStyle(Bento.secondaryInk)
                }
            }.frame(maxWidth: .infinity).bentoCard()
        }
    }

    private var devicesCard: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                Text("Appareils autorisés").font(.headline).accessibilityAddTraits(.isHeader)
                Spacer()
                Button { Task { await store.refreshAccessDevices() } } label: {
                    Image(systemName: "arrow.clockwise").frame(width: 44, height: 44)
                }.accessibilityLabel("Actualiser les accès").disabled(store.photoAccessBusy)
            }
            if store.accessDevices.isEmpty {
                Text("Les appareils autorisés apparaîtront ici.").font(.subheadline).foregroundStyle(Bento.secondaryInk)
            }
            ForEach(store.accessDevices, id: \.deviceID) { device in
                HStack(alignment: .top) {
                    Image(systemName: device.role == .owner ? "person.crop.circle.badge.checkmark" : "iphone")
                    VStack(alignment: .leading, spacing: 4) {
                        Text(device.role == .owner ? "Propriétaire" : "Accès photos")
                        Text(String(device.deviceID.uuidString.lowercased().prefix(8)))
                            .font(.caption.monospaced()).foregroundStyle(Bento.secondaryInk)
                        if device.revoked { Text("Accès retiré").font(.caption).foregroundStyle(Bento.secondaryInk) }
                    }
                    Spacer()
                    if device.role == .media && !device.revoked {
                        Button("Retirer", role: .destructive) { confirmingRevocation = device }
                            .frame(minHeight: 44).disabled(store.photoAccessBusy)
                            .accessibilityLabel("Retirer l’accès photos de l’appareil \(device.deviceID.uuidString.prefix(8))")
                    }
                }.font(.subheadline)
            }
        }.bentoCard()
    }

    private func invitationImage(_ code: FrameInvitationCode) -> UIImage? {
        guard let payload = try? code.encodedPayload() else { return nil }
        let filter = CIFilter.qrCodeGenerator()
        filter.message = Data(payload.utf8)
        filter.correctionLevel = "M"
        guard let output = filter.outputImage,
              let image = Self.qrContext.createCGImage(output, from: output.extent) else { return nil }
        return UIImage(cgImage: image)
    }
    private static let qrContext = CIContext()
}
