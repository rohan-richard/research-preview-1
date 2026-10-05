import Foundation

/// The local transcript, draft and server session id of the chat.
nonisolated struct RumiChatWorkspace: Codable {
    var clientID: UUID = UUID()
    var turns: [ConversationTurn] = []
    var draft: String = ""
    var context: CareContext? = nil
    var savedAt: Date? = nil
}

nonisolated enum RumiConnectionError: Error, LocalizedError {
    case signIn, onboarding, consent, unavailable, token, configurationResponse, authentication
    case protocolMismatch, incomplete, timeout, disconnected, busy
    case server(String)

    var errorDescription: String? {
        switch self {
        case .signIn: "Sign in to chat with Rumi."
        case .onboarding: "Finish setting up your profile before chatting with Rumi."
        case .consent: "Turn on Rumi chat in the Privacy Center first."
        case .unavailable: "Rumi's chat server is not available right now. Your message is kept."
        case .token: "Rumi could not get a chat token. Try again in a moment."
        case .configurationResponse: "The server configuration did not match the supported chat contract. No care information was sent."
        case .authentication: "The Rumi server rejected chat authentication. Sign in again and retry."
        case .protocolMismatch: "The server's message format needs an adapter update. No external action was confirmed."
        case .incomplete: "The server did not finish this reply. It may still have processed your message; retry only if you want to send it again."
        case .timeout: "The Rumi server took too long to respond. Nothing was rerouted."
        case .disconnected: "The Rumi connection closed. Your words are kept."
        case .busy: "A reply is already in progress. Stop it before sending another message."
        case .server(let message): message
        }
    }
}
