import SwiftUI

enum Bento {
    static let background = Color(red: 0.961, green: 0.961, blue: 0.953)
    static let ink = Color(red: 0.067, green: 0.067, blue: 0.067)
    static let blue = Color(red: 0.18, green: 0.47, blue: 0.93)
    static let amber = Color(red: 0.65, green: 0.40, blue: 0.0)
    static let border = Color.black.opacity(0.10)
}

extension View {
    func bentoCard(padding: CGFloat = 16) -> some View {
        self.padding(padding).frame(maxWidth: .infinity, alignment: .leading)
            .background(.white, in: RoundedRectangle(cornerRadius: 20))
            .overlay(RoundedRectangle(cornerRadius: 20).stroke(Bento.border, lineWidth: 0.7))
    }
    func screenBackground() -> some View {
        self.background(Bento.background).toolbarBackground(.visible, for: .navigationBar)
            .toolbarBackground(Bento.background, for: .navigationBar)
    }
}

struct PrimaryButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label.font(.body.weight(.semibold)).frame(maxWidth: .infinity).frame(minHeight: 52)
            .foregroundStyle(.white).background(Bento.ink.opacity(configuration.isPressed ? 0.75 : 1), in: RoundedRectangle(cornerRadius: 14))
            .contentShape(RoundedRectangle(cornerRadius: 14))
    }
}
struct OutlineButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label.font(.subheadline.weight(.medium)).frame(maxWidth: .infinity).frame(minHeight: 46)
            .foregroundStyle(Bento.ink).background(configuration.isPressed ? Color.black.opacity(0.05) : .white, in: RoundedRectangle(cornerRadius: 12))
            .overlay(RoundedRectangle(cornerRadius: 12).stroke(Bento.border, lineWidth: 1))
    }
}

struct FramePhoto: View {
    @EnvironmentObject private var store: AppStore
    let photo: Photo
    @State private var image: UIImage?
    @State private var loading = true
    var body: some View {
        ZStack {
            Color.black.opacity(0.04)
            if let image {
                Image(uiImage: image).resizable().scaledToFit()
            } else if loading { ProgressView() }
            else { Image(systemName: "photo").font(.title2).foregroundStyle(.secondary).accessibilityLabel("Aperçu indisponible") }
        }
        .aspectRatio(CGFloat(photo.width) / CGFloat(max(photo.height, 1)), contentMode: .fit)
        .clipShape(RoundedRectangle(cornerRadius: 12))
        .accessibilityLabel(photo.displayName)
        .task(id: "\(photo.id)-\(store.connected)") {
            guard store.connected else { loading = false; return }
            loading = image == nil
            let loadedImage = await store.image(for: photo)
            guard !Task.isCancelled else { return }
            image = loadedImage
            loading = false
        }
    }
}

extension Photo {
    var displayName: String {
        let stem = (originalFilename as NSString).deletingPathExtension
        return stem.isEmpty ? "Sans titre" : stem
    }
}

struct EmptyCard: View {
    let symbol: String
    let title: String
    let message: String
    var body: some View {
        VStack(spacing: 14) {
            Image(systemName: symbol).font(.system(size: 38, weight: .light)).foregroundStyle(.secondary)
            Text(title).font(.headline)
            Text(message).font(.subheadline).foregroundStyle(.secondary).multilineTextAlignment(.center)
        }.frame(maxWidth: .infinity).padding(.vertical, 30).bentoCard()
    }
}
