import AVFoundation
import PhotosUI
import SwiftUI

@MainActor
private final class PhotoImportModel: ObservableObject {
    @Published var photo: PreparedPhoto?
    @Published var isLoading = false
    @Published var isUploading = false
    @Published var progressText = ""
    @Published var errorMessage: String?
    private var loadID = UUID()

    func load(_ item: PhotosPickerItem) async {
        let identifier = UUID()
        loadID = identifier
        isLoading = true
        photo = nil
        errorMessage = nil
        progressText = "Chargement depuis Photos…"
        defer { if loadID == identifier { isLoading = false } }
        do {
            guard let file = try await item.loadTransferable(type: ImportedPhotoFile.self) else {
                throw PhotoPipelineError.unreadable
            }
            defer { try? FileManager.default.removeItem(at: file.url) }
            try Task.checkCancellation()
            guard loadID == identifier else { return }
            progressText = "Préparation de la photo…"
            let worker = Task.detached(priority: .userInitiated) {
                try autoreleasepool { try PhotoPipeline.decode(url: file.url) }
            }
            let decoded = try await withTaskCancellationHandler {
                try await worker.value
            } onCancel: {
                worker.cancel()
            }
            try Task.checkCancellation()
            guard loadID == identifier else { return }
            photo = decoded
        } catch is CancellationError {
            // Dismissing the sheet or choosing another item is not a photo error.
        } catch {
            guard !Task.isCancelled, loadID == identifier else { return }
            errorMessage = (error as? PhotoPipelineError)?.errorDescription
                ?? "La photo n’a pas pu être chargée. Si elle est sur iCloud, vérifiez la connexion puis réessayez."
        }
    }

    func load(_ capturedPhoto: CapturedPhoto) async {
        let identifier = UUID()
        loadID = identifier
        isLoading = true
        photo = nil
        errorMessage = nil
        progressText = "Préparation de la photo…"
        defer { if loadID == identifier { isLoading = false } }
        do {
            let worker = Task.detached(priority: .userInitiated) {
                try autoreleasepool { try capturedPhoto.prepare() }
            }
            let decoded = try await withTaskCancellationHandler {
                try await worker.value
            } onCancel: {
                worker.cancel()
            }
            try Task.checkCancellation()
            guard loadID == identifier else { return }
            photo = decoded
        } catch is CancellationError {
            // Leaving the import screen does not present an error.
        } catch {
            guard !Task.isCancelled, loadID == identifier else { return }
            errorMessage = (error as? PhotoPipelineError)?.errorDescription
                ?? "La photo n’a pas pu être préparée. Prenez une autre photo, puis réessayez."
        }
    }

    func upload(crop: CGRect, width: Int, height: Int,
                onUpload: @escaping (Data, String) async throws -> Void) async -> Bool {
        guard let photo, !isUploading else { return false }
        isUploading = true
        errorMessage = nil
        progressText = "Préparation pour le cadre…"
        defer { isUploading = false }
        do {
            let worker = Task.detached(priority: .userInitiated) {
                try autoreleasepool {
                    try PhotoPipeline.encodePNG(photo: photo, crop: crop, width: width, height: height)
                }
            }
            let png = try await withTaskCancellationHandler {
                try await worker.value
            } onCancel: {
                worker.cancel()
            }
            try Task.checkCancellation()
            progressText = "Envoi vers le cadre…"
            try await onUpload(png, "photo-\(UUID().uuidString.prefix(8).lowercased()).png")
            try Task.checkCancellation()
            return true
        } catch is CancellationError {
            return false
        } catch {
            guard !Task.isCancelled else { return false }
            if let pipelineError = error as? PhotoPipelineError {
                errorMessage = pipelineError.errorDescription
            } else if error is URLError {
                errorMessage = "L’envoi n’a pas pu être confirmé. Vérifiez le Wi-Fi et la file du cadre avant de réessayer."
            } else {
                errorMessage = (error as? LocalizedError)?.errorDescription
                    ?? "L’envoi a échoué. Vérifiez la connexion au cadre, puis réessayez."
            }
            return false
        }
    }
}

/// Native, single-photo import presented as a sheet. The upload callback receives an
/// opaque sRGB PNG at the exact panel resolution; quantization remains on the Pi.
struct PhotoImportView: View {
    let panelWidth: Int
    let panelHeight: Int
    let onUpload: (Data, String) async throws -> Void

    @Environment(\.dismiss) private var dismiss
    @Environment(\.openURL) private var openURL
    @StateObject private var model = PhotoImportModel()
    @State private var selection: PhotosPickerItem?
    @State private var showPicker = false
    @State private var showCamera = false
    @State private var pendingCapture: CapturedPhoto?
    @State private var cameraIssue: CameraIssue?
    @State private var isRequestingCamera = false
    @State private var cameraRequestTask: Task<Void, Never>?
    @State private var cameraPreparationTask: Task<Void, Never>?
    @State private var zoom: CGFloat = 1
    @State private var normalizedOffset: CGSize = .zero
    @State private var viewportSize: CGSize = .zero
    @State private var uploadTask: Task<Void, Never>?
    @GestureState private var dragTranslation: CGSize = .zero
    @GestureState private var gestureZoom: CGFloat = 1

    private let background = Bento.background
    private let secondary = Bento.secondaryInk
    private let accent = Bento.blue

    init(panelWidth: Int, panelHeight: Int,
         onUpload: @escaping (Data, String) async throws -> Void) {
        self.panelWidth = panelWidth
        self.panelHeight = panelHeight
        self.onUpload = onUpload
    }

    private var validPanel: Bool {
        (try? PhotoPipeline.validatePanel(width: panelWidth, height: panelHeight)) != nil
    }

    var body: some View {
        NavigationStack {
            GeometryReader { bounds in
                ScrollView {
                    VStack(spacing: 20) {
                        if let photo = model.photo {
                            cropCanvas(photo: photo)
                                .frame(height: min(430, max(240, bounds.size.height * 0.53)))
                            cropControls
                        } else {
                            selectionPlaceholder
                                .frame(minHeight: max(260, bounds.size.height * 0.7))
                        }
                        if let error = model.errorMessage {
                            Label(error, systemImage: "exclamationmark.circle")
                                .font(.callout)
                                .foregroundStyle(.red)
                                .frame(maxWidth: .infinity, alignment: .leading)
                                .padding(16)
                                .background(Bento.surface, in: RoundedRectangle(cornerRadius: 16))
                                .padding(.horizontal, 16)
                                .accessibilityIdentifier("photo-import-error")
                        }
                    }
                    .padding(.bottom, 20)
                }
                .background(background)
            }
            .navigationTitle(model.photo == nil ? "Ajouter une photo" : "Cadrer la photo")
            .navigationBarTitleDisplayMode(.inline)
            .toolbarBackground(Bento.surface, for: .navigationBar)
            .toolbarBackground(.visible, for: .navigationBar)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Annuler") { dismiss() }
                        .disabled(model.isUploading)
                        .accessibilityIdentifier("cancel-photo-import")
                }
                if model.photo != nil {
                    ToolbarItem(placement: .topBarTrailing) {
                        Menu {
                            Button(action: takePhoto) {
                                Label("Prendre une photo", systemImage: "camera")
                            }
                            Button(action: choosePhoto) {
                                Label("Choisir dans Photos", systemImage: "photo.on.rectangle")
                            }
                        } label: {
                            Image(systemName: "photo.on.rectangle")
                        }
                        .accessibilityLabel("Choisir une autre photo")
                        .accessibilityIdentifier("change-photo-source")
                        .disabled(model.isLoading || model.isUploading || isRequestingCamera)
                    }
                }
            }
            .safeAreaInset(edge: .bottom, spacing: 0) {
                if model.photo != nil { uploadBar }
            }
        }
        .tint(accent)
        .interactiveDismissDisabled(model.isUploading)
        .photosPicker(isPresented: $showPicker, selection: $selection,
                      matching: .images, preferredItemEncoding: .current)
        .fullScreenCover(isPresented: $showCamera, onDismiss: prepareCapture) {
            CameraCaptureView { result in
                switch result {
                case let .success(photo): pendingCapture = photo
                case .failure:
                    model.errorMessage = "La photo n’a pas pu être récupérée. Prenez une autre photo, puis réessayez."
                case nil: break
                }
                showCamera = false
            }
            .ignoresSafeArea()
        }
        .alert(item: $cameraIssue) { issue in
            if issue == .denied {
                return Alert(
                    title: Text(issue.title), message: Text(issue.message),
                    primaryButton: .default(Text("Ouvrir Réglages")) {
                        if let url = URL(string: UIApplication.openSettingsURLString) { openURL(url) }
                    },
                    secondaryButton: .cancel(Text("Plus tard"))
                )
            }
            return Alert(
                title: Text(issue.title), message: Text(issue.message),
                primaryButton: .default(Text("Choisir dans Photos"), action: choosePhoto),
                secondaryButton: .cancel(Text("Annuler"))
            )
        }
        .task {
            if !validPanel {
                model.errorMessage = PhotoPipelineError.invalidPanel.errorDescription
            }
        }
        .task(id: selection) {
            guard let selection else { return }
            zoom = 1
            normalizedOffset = .zero
            await model.load(selection)
        }
        .onChange(of: zoom) { _, _ in clampStoredOffset() }
        .onDisappear {
            uploadTask?.cancel()
            cameraRequestTask?.cancel()
            cameraPreparationTask?.cancel()
        }
    }

    private var selectionPlaceholder: some View {
        VStack(spacing: 20) {
            if model.isLoading {
                ProgressView().controlSize(.large)
                Text(model.progressText).font(.headline)
                Text("Votre photo sera adaptée au format du cadre.")
                    .font(.callout).foregroundStyle(secondary)
            } else {
                Image(systemName: "photo.badge.plus")
                    .font(.system(size: 52, weight: .light))
                    .foregroundStyle(secondary)
                Text("Un nouveau souvenir sur le cadre")
                    .font(.title2.weight(.semibold))
                Text("Prenez une photo ou choisissez-en une dans Photos, puis ajustez son cadrage.")
                    .font(.body).foregroundStyle(secondary)
                Button(action: takePhoto) {
                    Label("Prendre une photo", systemImage: "camera")
                        .font(.body.weight(.semibold))
                        .frame(maxWidth: .infinity, minHeight: 52)
                        .background(Bento.ink, in: RoundedRectangle(cornerRadius: 14))
                        .foregroundStyle(Bento.actionText)
                }
                .disabled(!validPanel || isRequestingCamera)
                .accessibilityIdentifier("take-photo")
                Button(action: choosePhoto) {
                    Label("Choisir dans Photos", systemImage: "photo.on.rectangle")
                        .font(.body.weight(.semibold))
                        .frame(maxWidth: .infinity, minHeight: 52)
                        .background(Bento.surface, in: RoundedRectangle(cornerRadius: 14))
                        .foregroundStyle(Bento.ink)
                }
                .disabled(!validPanel || isRequestingCamera)
                .accessibilityIdentifier("choose-photo")
            }
        }
        .multilineTextAlignment(.center)
        .padding(24)
    }

    private func cropCanvas(photo: PreparedPhoto) -> some View {
        GeometryReader { proxy in
            let viewport = CropGeometry.viewport(
                in: proxy.size, panel: CGSize(width: panelWidth, height: panelHeight)
            )
            let geometry = cropGeometry(photo: photo, viewport: viewport, liveGesture: true)
            let cropRect = CGRect(x: (proxy.size.width - viewport.width) / 2,
                                  y: (proxy.size.height - viewport.height) / 2,
                                  width: viewport.width, height: viewport.height)
            ZStack {
                Color.black
                Image(decorative: photo.image, scale: 1)
                    .resizable()
                    .interpolation(.high)
                    .frame(width: geometry.displayedSize.width, height: geometry.displayedSize.height)
                    .position(x: proxy.size.width / 2 + geometry.clampedOffset.width,
                              y: proxy.size.height / 2 + geometry.clampedOffset.height)
                Path { path in
                    path.addRect(CGRect(origin: .zero, size: proxy.size))
                    path.addRect(cropRect)
                }
                .fill(.black.opacity(0.5), style: FillStyle(eoFill: true))
                Path { path in
                    for fraction in [CGFloat(1.0 / 3.0), CGFloat(2.0 / 3.0)] {
                        let x = cropRect.minX + cropRect.width * fraction
                        let y = cropRect.minY + cropRect.height * fraction
                        path.move(to: CGPoint(x: x, y: cropRect.minY))
                        path.addLine(to: CGPoint(x: x, y: cropRect.maxY))
                        path.move(to: CGPoint(x: cropRect.minX, y: y))
                        path.addLine(to: CGPoint(x: cropRect.maxX, y: y))
                    }
                }
                .stroke(.white.opacity(0.5), lineWidth: 0.5)
                Rectangle()
                    .strokeBorder(.white, lineWidth: 2)
                    .frame(width: viewport.width, height: viewport.height)
            }
            .clipped()
            .contentShape(Rectangle())
            .gesture(DragGesture(minimumDistance: 0)
                .updating($dragTranslation) { value, state, _ in state = value.translation }
                .onEnded { value in
                    guard viewport.width > 0, viewport.height > 0 else { return }
                    normalizedOffset.width += value.translation.width / viewport.width
                    normalizedOffset.height += value.translation.height / viewport.height
                    clampStoredOffset()
                }
            )
            .simultaneousGesture(MagnifyGesture()
                .updating($gestureZoom) { value, state, _ in state = value.magnification }
                .onEnded { value in zoom = min(CropGeometry.maximumZoom, max(1, zoom * value.magnification)) }
            )
            .allowsHitTesting(!model.isUploading)
            .accessibilityElement(children: .ignore)
            .accessibilityLabel("Cadrage de la photo")
            .accessibilityHint("Utilisez le réglage de zoom ou les actions pour déplacer la photo.")
            .accessibilityAction(named: "Déplacer la photo à gauche") { movePhoto(x: -0.1, y: 0) }
            .accessibilityAction(named: "Déplacer la photo à droite") { movePhoto(x: 0.1, y: 0) }
            .accessibilityAction(named: "Déplacer la photo vers le haut") { movePhoto(x: 0, y: -0.1) }
            .accessibilityAction(named: "Déplacer la photo vers le bas") { movePhoto(x: 0, y: 0.1) }
            .onAppear { viewportSize = viewport }
            .onChange(of: viewport) { _, value in
                viewportSize = value
                clampStoredOffset()
            }
        }
    }

    private var cropControls: some View {
        VStack(spacing: 16) {
            Text("Format du cadre · \(panelWidth) × \(panelHeight)")
                .font(.footnote).foregroundStyle(secondary)
            Text("Déplacez et pincez pour cadrer.")
                .font(.body).foregroundStyle(secondary)
            HStack(spacing: 16) {
                zoomButton(symbol: "minus", label: "Réduire le zoom") { zoom = max(1, zoom - 0.25) }
                Slider(value: $zoom, in: 1...CropGeometry.maximumZoom)
                    .tint(Bento.ink)
                    .accessibilityLabel("Zoom de la photo")
                    .accessibilityValue(String(format: "%.1f fois", Double(zoom)))
                zoomButton(symbol: "plus", label: "Augmenter le zoom") {
                    zoom = min(CropGeometry.maximumZoom, zoom + 0.25)
                }
            }
            Button("Réinitialiser") {
                zoom = 1
                normalizedOffset = .zero
            }
            .font(.callout)
            .foregroundStyle(secondary)
            .frame(minHeight: 44)
            Text("Les couleurs seront adaptées à l’écran.")
                .font(.footnote).foregroundStyle(secondary)
        }
        .multilineTextAlignment(.center)
        .padding(.horizontal, 20)
        .disabled(model.isUploading)
    }

    private func zoomButton(symbol: String, label: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Image(systemName: symbol)
                .font(.body.weight(.medium))
                .foregroundStyle(Bento.ink)
                .frame(width: 44, height: 44)
                .background(Bento.surface, in: Circle())
                .overlay(Circle().strokeBorder(Bento.border))
        }
        .accessibilityLabel(label)
    }

    private var uploadBar: some View {
        VStack(spacing: 8) {
            Button {
                guard let photo = model.photo, viewportSize.width > 0 else { return }
                let crop = cropGeometry(photo: photo, viewport: viewportSize).sourceRect
                uploadTask = Task {
                    let succeeded = await model.upload(crop: crop, width: panelWidth, height: panelHeight,
                                                       onUpload: onUpload)
                    if succeeded { dismiss() }
                }
            } label: {
                HStack(spacing: 12) {
                    if model.isUploading {
                        ProgressView().tint(Bento.actionText)
                        Text(model.progressText)
                    } else {
                        Image(systemName: "plus")
                        Text("Ajouter à la file")
                    }
                }
                .font(.body.weight(.semibold))
                .frame(maxWidth: .infinity, minHeight: 52)
                .foregroundStyle(Bento.actionText)
                .background(Bento.ink, in: RoundedRectangle(cornerRadius: 14))
            }
            .disabled(model.isUploading || !validPanel || viewportSize.width <= 0)
            .accessibilityIdentifier("upload-photo")
            Text("Elle sera affichée à son tour.")
                .font(.footnote).foregroundStyle(secondary)
        }
        .padding(.horizontal, 16)
        .padding(.top, 12)
        .padding(.bottom, 8)
        .background(background)
    }

    private func cropGeometry(photo: PreparedPhoto, viewport: CGSize, liveGesture: Bool = false) -> CropGeometry {
        CropGeometry(sourceSize: photo.size, viewportSize: viewport,
                     zoom: zoom * (liveGesture ? gestureZoom : 1),
                     offset: CGSize(width: normalizedOffset.width * viewport.width + (liveGesture ? dragTranslation.width : 0),
                                    height: normalizedOffset.height * viewport.height + (liveGesture ? dragTranslation.height : 0)))
    }

    private func clampStoredOffset() {
        guard let photo = model.photo, viewportSize.width > 0, viewportSize.height > 0 else { return }
        let clamped = cropGeometry(photo: photo, viewport: viewportSize).clampedOffset
        normalizedOffset = CGSize(width: clamped.width / viewportSize.width,
                                  height: clamped.height / viewportSize.height)
    }

    private func movePhoto(x: CGFloat, y: CGFloat) {
        guard !model.isUploading else { return }
        normalizedOffset.width += x
        normalizedOffset.height += y
        clampStoredOffset()
    }

    private func choosePhoto() {
        // Clearing the selection allows retrying the same iCloud item after a failure.
        selection = nil
        showPicker = true
    }

    private func takePhoto() {
        guard !isRequestingCamera, !model.isLoading, !model.isUploading else { return }
        guard UIImagePickerController.isSourceTypeAvailable(.camera),
              UIImagePickerController.availableMediaTypes(for: .camera)?.contains("public.image") == true else {
            cameraIssue = .unavailable
            return
        }
        isRequestingCamera = true
        cameraRequestTask = Task { @MainActor in
            defer { isRequestingCamera = false }
            let status = AVCaptureDevice.authorizationStatus(for: .video)
            switch status {
            case .authorized:
                break
            case .notDetermined:
                let granted = await AVCaptureDevice.requestAccess(for: .video)
                guard !Task.isCancelled else { return }
                guard granted else {
                    cameraIssue = .denied
                    return
                }
            case .denied:
                cameraIssue = .denied
                return
            case .restricted:
                cameraIssue = .restricted
                return
            @unknown default:
                cameraIssue = .unavailable
                return
            }
            guard !Task.isCancelled else { return }
            selection = nil
            pendingCapture = nil
            showCamera = true
        }
    }

    private func prepareCapture() {
        guard let photo = pendingCapture else { return }
        pendingCapture = nil
        zoom = 1
        normalizedOffset = .zero
        cameraPreparationTask = Task { await model.load(photo) }
    }
}

private enum CameraIssue: String, Identifiable {
    case denied, restricted, unavailable

    var id: String { rawValue }
    var title: String {
        switch self {
        case .denied: "Autoriser l’appareil photo"
        case .restricted: "Appareil photo restreint"
        case .unavailable: "Appareil photo indisponible"
        }
    }
    var message: String {
        switch self {
        case .denied:
            "Autorisez l’accès à l’appareil photo dans Réglages pour prendre une photo. Vous pouvez aussi revenir et choisir une image dans Photos."
        case .restricted:
            "Une restriction de cet appareil empêche l’accès à la caméra. Vous pouvez choisir une image dans Photos."
        case .unavailable:
            "Cet appareil ne permet pas de prendre une photo ici. Vous pouvez choisir une image dans Photos."
        }
    }
}
