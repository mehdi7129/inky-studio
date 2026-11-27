import Foundation

enum APIError: Error, LocalizedError, Equatable, Sendable {
    case unauthorized
    case http(statusCode: Int, message: String)
    case invalidResponse
    case invalidAddress(String)
    case invalidData

    var isUnauthorized: Bool {
        if case .unauthorized = self { return true }
        return false
    }

    var errorDescription: String? {
        switch self {
        case .unauthorized:
            return String(localized: "Connexion refusée ou session expirée. Vérifiez le mot de passe du cadre.")
        case .http(_, let message), .invalidAddress(let message): return message
        case .invalidResponse: return String(localized: "Le cadre a envoyé une réponse inattendue.")
        case .invalidData: return String(localized: "La réponse du cadre est illisible. Vérifiez sa version puis réessayez.")
        }
    }

    static func response(status: Int, data: Data) -> APIError {
        if status == 401 { return .unauthorized }
        var detail: String?
        if let body = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
            if let message = body["detail"] as? String {
                detail = message
            } else if let errors = body["detail"] as? [[String: Any]] {
                // FastAPI/Pydantic validation errors contain input values as well;
                // display only the messages, never echo the submitted password.
                let messages = errors.compactMap { $0["msg"] as? String }
                if !messages.isEmpty { detail = String(localized: "Données non valides : ") + messages.joined(separator: "; ") }
            }
        }
        if let detail, !detail.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            return .http(statusCode: status, message: detail)
        }
        let message: String
        switch status {
        case 300..<400: message = String(localized: "Le cadre redirige vers une autre adresse. Vérifiez l’adresse enregistrée.")
        case 403: message = String(localized: "Cette action n’est pas autorisée sur le cadre.")
        case 404: message = String(localized: "Cette ressource est introuvable sur le cadre.")
        case 409: message = String(localized: "Le cadre est occupé. Attendez la fin de l’opération puis réessayez.")
        case 413: message = String(localized: "Cette photo est trop volumineuse pour le cadre.")
        case 422: message = String(localized: "Le cadre n’a pas accepté ces données. Vérifiez les valeurs saisies.")
        case 429: message = String(localized: "Trop de tentatives. Patientez une minute avant de réessayer.")
        case 500...599: message = String(localized: "Le cadre rencontre une erreur (\(status)). Réessayez dans un instant.")
        default: message = String(localized: "L’opération a échoué (HTTP \(status)).")
        }
        return .http(statusCode: status, message: message)
    }
}
