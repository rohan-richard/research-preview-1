import Foundation

nonisolated struct AIChatMessage: Codable, Equatable {
    let role: String
    let content: String
}

@MainActor protocol ChatTransport {
    func stream(requestID: UUID, system: String, messages: [AIChatMessage], onDelta: @escaping @MainActor (String) -> Void) async throws -> String
}

extension ChatTransport {
    func stream(system: String, messages: [AIChatMessage], onDelta: @escaping @MainActor (String) -> Void) async throws -> String {
        try await stream(requestID: UUID(), system: system, messages: messages, onDelta: onDelta)
    }
}
