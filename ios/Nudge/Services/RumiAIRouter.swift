import Foundation
import Observation

/// The one path from chat, contextual help, visit preparation and voice to the Rumi chat server.
@Observable final class RumiAIRouter: ChatTransport {
    private(set) var revision: UUID = UUID()
    private(set) var status: String = "Ready"
    var clientID: UUID = UUID() {
        didSet { if clientID != oldValue { dropSession() } }
    }
    /// The phone side of chat-server tool tasks. The portal browser installs itself here.
    var device: any RumiToolDevice = RumiNoPortalDevice() {
        didSet { dropSession() }
    }
    private let api: RumiAPI
    private let makeSession: (@MainActor (RumiAPI, any RumiToolDevice, UUID, @escaping @MainActor (String) -> Void) -> any RumiChatSessioning)?
    private var session: (any RumiChatSessioning)?
    private var active: [UUID: Task<String, any Error>] = [:]

    init(api: RumiAPI, makeSession: (@MainActor (RumiAPI, any RumiToolDevice, UUID, @escaping @MainActor (String) -> Void) -> any RumiChatSessioning)? = nil) {
        self.api = api
        self.makeSession = makeSession
    }

    var canSend: Bool { api.isSignedIn }
    var isConnected: Bool { session?.isConnected ?? false }

    func cancelAll() {
        revision = UUID()
        for task in active.values { task.cancel() }
        active = [:]
    }

    func suspend() {
        cancelAll()
        dropSession()
        status = "Reconnects on your next message"
    }

    private func dropSession() {
        session?.close()
        session = nil
    }

    func stream(requestID: UUID, system: String, messages: [AIChatMessage], onDelta: @escaping @MainActor (String) -> Void) async throws -> String {
        try await run { session, guarded in
            try await session.stream(requestID: requestID, system: system, messages: messages, onDelta: guarded(onDelta))
        }
    }

    /// One spoken turn: 16 kHz mono 24-bit PCM in, the server's transcript, reply text and reply audio out.
    func speak(pcm: Data, onTranscript: @escaping @MainActor (String) -> Void,
               onDelta: @escaping @MainActor (String) -> Void,
               onAudio: @escaping @MainActor (Data) -> Void) async throws -> String {
        try await run { session, guarded in
            try await session.speak(pcm: pcm, onTranscript: guarded(onTranscript), onDelta: guarded(onDelta), onAudio: guarded(onAudio))
        }
    }

    func prepareVisit(input: String) async throws -> String {
        try await stream(requestID: UUID(),
                         system: "",
                         messages: [.init(role: "user", content: "Help me prepare up to three questions for this sample visit. Do not take any external action.\n<selected-context-data>\(input)</selected-context-data>")], onDelta: { _ in })
    }

    private func run(_ body: @escaping @MainActor (any RumiChatSessioning, _ guarded: Guarded) async throws -> String) async throws -> String {
        try Task.checkCancellation()
        guard api.isSignedIn else { throw RumiConnectionError.signIn }
        let revision = revision
        let selected = backendSession(revision: revision)
        let guarded = Guarded { [weak self] in self?.revision == revision && !Task.isCancelled }
        let operationID = UUID()
        let task = Task { try await body(selected, guarded) }
        active[operationID] = task
        defer { active[operationID] = nil }
        do {
            let result = try await withTaskCancellationHandler { try await task.value } onCancel: { task.cancel() }
            try Task.checkCancellation()
            guard self.revision == revision else { throw CancellationError() }
            return result
        } catch {
            if self.revision == revision && !Task.isCancelled {
                status = (error as? RumiConnectionError)?.errorDescription ?? "Rumi is not available right now"
            }
            throw error
        }
    }

    private func backendSession(revision: UUID) -> any RumiChatSessioning {
        if let session { return session }
        let report: @MainActor (String) -> Void = { [weak self] text in if self?.revision == revision { self?.status = text } }
        let created = makeSession?(api, device, clientID, report)
            ?? RumiChatSession(tokens: RumiAPITokenProvider(api: api), device: device, sessionID: clientID, status: report)
        session = created
        return created
    }
}

/// Drops callbacks from a turn that a newer turn or a reset replaced.
struct Guarded {
    let isCurrent: @MainActor () -> Bool

    func callAsFunction<T>(_ handler: @escaping @MainActor (T) -> Void) -> @MainActor (T) -> Void {
        { value in if isCurrent() { handler(value) } }
    }
}
