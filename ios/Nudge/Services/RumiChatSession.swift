import Foundation

@MainActor protocol RumiChatSessioning: ChatTransport, AnyObject {
    var isConnected: Bool { get }
    func close()
    func speak(pcm: Data, onTranscript: @escaping @MainActor (String) -> Void,
               onDelta: @escaping @MainActor (String) -> Void,
               onAudio: @escaping @MainActor (Data) -> Void) async throws -> String
}

/// One WebSocket for the whole chat. Tool tasks and their ask-the-patient pauses live on the server side
/// of this socket, so it stays open between turns and closes only on suspend, sign-out, or a mode change.
final class RumiChatSession: RumiChatSessioning {
    private let tokens: any RumiTokenProviding
    private let device: any RumiToolDevice
    private let makeSocket: @MainActor () -> any RumiSocketConnecting
    private let status: @MainActor (String) -> Void
    let sessionID: UUID

    private var socket: (any RumiSocketConnecting)?
    private var receiveLoop: Task<Void, Never>?
    private var access: RumiChatAccess?
    private var tenantID: String?
    private var turn: Turn?
    private var refreshing = false
    private var toolTasks: [String: Task<Void, Never>] = [:]
    private var voiceMode = false

    private struct Turn {
        var accumulator = RumiTurnAccumulator()
        let onDelta: @MainActor (String) -> Void
        var onTranscript: (@MainActor (String) -> Void)? = nil
        var onAudio: (@MainActor (Data) -> Void)? = nil
        let continuation: CheckedContinuation<String, any Error>
    }

    // The server reads each audio frame's value as a JSON list of byte values; one second per frame.
    private static let audioFrameBytes = 16_000 * 3

    init(tokens: any RumiTokenProviding, device: any RumiToolDevice, sessionID: UUID,
         makeSocket: @escaping @MainActor () -> any RumiSocketConnecting = { RumiSocketConnection() },
         status: @escaping @MainActor (String) -> Void = { _ in }) {
        self.tokens = tokens; self.device = device; self.sessionID = sessionID
        self.makeSocket = makeSocket; self.status = status
    }

    var isConnected: Bool { socket != nil }

    func stream(requestID: UUID, system: String, messages: [AIChatMessage], onDelta: @escaping @MainActor (String) -> Void) async throws -> String {
        guard let input = messages.last(where: { $0.role == "user" })?.content,
              !input.isEmpty, input.utf8.count <= 65_536 else { throw RumiConnectionError.protocolMismatch }
        guard turn == nil else { throw RumiConnectionError.busy }
        try await connectIfNeeded()
        guard let socket else { throw RumiConnectionError.disconnected }
        try await setVoice(false, on: socket)
        // The server owns system policy and conversation memory. Never replay history or invent a system frame.
        try Task.checkCancellation()
        try await socket.send(RumiWireProtocol.frame(type: "control", value: "client_speaking"))
        try Task.checkCancellation()
        try await socket.send(RumiWireProtocol.frame(type: "text", value: input))
        try Task.checkCancellation()
        try await socket.send(RumiWireProtocol.frame(type: "control", value: "client_paused"))
        status("Message sent · waiting for Rumi")
        return try await awaitTurn { Turn(onDelta: onDelta, continuation: $0) }
    }

    func speak(pcm: Data, onTranscript: @escaping @MainActor (String) -> Void,
               onDelta: @escaping @MainActor (String) -> Void,
               onAudio: @escaping @MainActor (Data) -> Void) async throws -> String {
        guard !pcm.isEmpty, pcm.count <= 16_000 * 3 * 120 else { throw RumiConnectionError.protocolMismatch }
        guard turn == nil else { throw RumiConnectionError.busy }
        try await connectIfNeeded()
        guard let socket else { throw RumiConnectionError.disconnected }
        try await setVoice(true, on: socket)
        try Task.checkCancellation()
        try await socket.send(RumiWireProtocol.frame(type: "control", value: "client_speaking"))
        var offset = pcm.startIndex
        while offset < pcm.endIndex {
            try Task.checkCancellation()
            let end = min(offset + Self.audioFrameBytes, pcm.endIndex)
            try await socket.send(RumiWireProtocol.audioFrame(pcm[offset..<end]))
            offset = end
        }
        try Task.checkCancellation()
        try await socket.send(RumiWireProtocol.frame(type: "control", value: "client_paused"))
        status("Listening done · waiting for Rumi")
        return try await awaitTurn { continuation in
            Turn(onDelta: onDelta, onTranscript: onTranscript, onAudio: onAudio, continuation: continuation)
        }
    }

    private func setVoice(_ enabled: Bool, on socket: any RumiSocketConnecting) async throws {
        guard voiceMode != enabled else { return }
        try await socket.send(RumiWireProtocol.voiceFlag(enabled))
        voiceMode = enabled
    }

    private func awaitTurn(_ make: @escaping (CheckedContinuation<String, any Error>) -> Turn) async throws -> String {
        let deadline = Task { [weak self] in
            try? await Task.sleep(for: .seconds(600))
            self?.finishTurn(.failure(RumiConnectionError.timeout))
        }
        defer { deadline.cancel() }
        return try await withTaskCancellationHandler {
            try await withCheckedThrowingContinuation { continuation in
                turn = make(continuation)
            }
        } onCancel: {
            Task { @MainActor in self.stop() }
        }
    }

    /// Stops the running turn on the server and keeps the socket for the next one.
    func stop() {
        if let socket, turn != nil {
            Task { try? await socket.send(RumiWireProtocol.frame(type: "control", value: "client_stop")) }
        }
        device.cancelAll()
        finishTurn(.failure(CancellationError()))
    }

    func close() {
        finishTurn(.failure(RumiConnectionError.disconnected))
        device.cancelAll()
        for task in toolTasks.values { task.cancel() }
        toolTasks = [:]
        receiveLoop?.cancel(); receiveLoop = nil
        socket?.close(); socket = nil
        access = nil
    }

    private func connectIfNeeded() async throws {
        if socket != nil { return }
        status("Requesting a chat token…")
        let access = try await tokens.access()
        try Task.checkCancellation()
        let config = try await tokens.configuration(for: access)
        try Task.checkCancellation()
        guard let base = access.socketURL else { throw RumiConnectionError.token }
        let socket = makeSocket()
        status("Opening secure WebSocket…")
        do {
            try await socket.open(url: try RumiWireProtocol.socketURL(base: base, sessionID: sessionID))
            try Task.checkCancellation()
            // Success has no ACK frame. A rejection arrives as auth_failed in the receive loop.
            try await socket.send(RumiWireProtocol.frame(type: "auth", value: access.accessToken))
            try await socket.send(RumiWireProtocol.voiceFlag(false))
            voiceMode = false
        } catch {
            socket.close()
            throw (error as? RumiConnectionError) ?? RumiConnectionError.disconnected
        }
        self.socket = socket
        self.access = access
        self.tenantID = config.tenant_id
        receiveLoop = Task { [weak self] in await self?.receiveForever(socket) }
        status("Connected to Rumi")
    }

    private func receiveForever(_ socket: any RumiSocketConnecting) async {
        while !Task.isCancelled {
            do {
                let event = try RumiWireProtocol.decode(try await socket.receive())
                await handle(event)
            } catch is CancellationError {
                return
            } catch {
                guard self.socket === socket else { return }
                self.socket = nil
                receiveLoop = nil
                finishTurn(.failure((error as? RumiConnectionError) ?? RumiConnectionError.disconnected))
                status("Rumi connection closed")
                return
            }
        }
    }

    private func handle(_ event: RumiWireProtocol.Event) async {
        switch event.type {
        case "auth":
            switch event.value {
            case "auth_failed":
                finishTurn(.failure(RumiConnectionError.authentication))
                close()
            case "session_expiring", "session_expired":
                await reauthenticate()
            default:
                break
            }
        case "tool":
            guard let request = event.tool else { return }
            status("Rumi is working in your portal…")
            // A confirm can wait minutes for the patient, so the receive loop must not wait with it.
            toolTasks[request.id] = Task { [weak self] in
                let reply = await self?.device.handle(request) ?? .init(id: request.id, ok: false, error: "The chat session ended.")
                guard let self, !Task.isCancelled else { return }
                self.toolTasks[request.id] = nil
                if let socket = self.socket { try? await socket.send(RumiWireProtocol.toolReply(reply)) }
            }
        case "transcript":
            if let text = event.text { turn?.onTranscript?(text) }
        case "control" where event.value == "server_acting":
            if let step = event.step, let total = event.max_steps { status("Rumi is working in your portal · step \(step) of \(total)") }
        case "error":
            let failure = RumiConnectionError.server(event.value ?? "The Rumi server reported an error.")
            if event.fatal == true { finishTurn(.failure(failure)); close() }
            else if turn != nil { finishTurn(.failure(failure)) }
        default:
            consume(event)
        }
    }

    private func consume(_ event: RumiWireProtocol.Event) {
        guard turn != nil else { return }
        if event.type == "data", let audio = event.audio, let data = Data(base64Encoded: audio) {
            turn?.onAudio?(data)
        }
        do {
            if let delta = try turn!.accumulator.consume(event) {
                status("Receiving Rumi's reply…")
                turn?.onDelta(delta)
            }
            if turn?.accumulator.isComplete == true {
                status("Reply received")
                finishTurn(.success(turn!.accumulator.text))
            }
        } catch {
            finishTurn(.failure(error))
        }
    }

    private func reauthenticate() async {
        guard !refreshing, let socket else { return }
        refreshing = true
        defer { refreshing = false }
        status("Renewing chat access…")
        do {
            let fresh = try await tokens.access()
            let config = try await tokens.configuration(for: fresh)
            guard config.tenant_id == tenantID else { throw RumiConnectionError.authentication }
            try await socket.send(RumiWireProtocol.frame(type: "auth", value: fresh.accessToken))
            access = fresh
        } catch {
            // The server closes the socket itself if no fresh auth arrives in time.
            status("Could not renew chat access")
        }
    }

    private func finishTurn(_ result: Result<String, any Error>) {
        guard let current = turn else { return }
        turn = nil
        current.continuation.resume(with: result)
    }
}
