import Foundation
import Testing
@testable import Nudge

@Suite(.serialized)
@MainActor struct RumiAIConnectionTests {
    private static let access = RumiChatAccess(accessToken: "t", expiresIn: 600, socketUrl: "ws://localhost:8101/chat/ws", tenant: "rumi-chat")

    @Test func socketURLKeepsThePrefixAndForcesTLSAwayFromLocalhost() throws {
        let id = UUID()
        let local = try RumiWireProtocol.socketURL(base: try #require(Self.access.socketURL), sessionID: id)
        #expect(local.scheme == "ws" && local.path == "/chat/ws/\(id.uuidString.lowercased())")
        let remote = try RumiWireProtocol.socketURL(base: try #require(URL(string: "ws://chat.example/chat/ws")), sessionID: id)
        #expect(remote.scheme == "wss" && remote.host == "chat.example")
        #expect(Self.access.serverURL?.absoluteString == "http://localhost:8101/chat")
        #expect(throws: RumiConnectionError.self) { try RumiWireProtocol.socketURL(base: try #require(URL(string: "wss://user:pw@chat.example/ws")), sessionID: id) }
    }

    @Test func configurationMatchesServerGetConfig() throws {
        func decode(_ json: String) -> RumiWireProtocol.Configuration? { try? JSONDecoder().decode(RumiWireProtocol.Configuration.self, from: Data(json.utf8)) }
        #expect(decode(#"{"tenant_id":"acme","chat_type":"VOICE","background_color":null}"#)?.isValid == true)
        #expect(decode(##"{"tenant_id":"acme","chat_type":"CHAT","background_color":"#101820"}"##)?.isValid == true)
        #expect(decode(#"{"tenant_id":"acme","chat_type":"TEXT"}"#)?.isValid == false)
        #expect(decode(#"{"identifier":"acme","chat_type":"CHAT"}"#) == nil)
    }

    @Test func tokenExpiryIsCheckedWithoutClaimingAuthentication() throws {
        let now = Date(timeIntervalSince1970: 1_800_000_000)
        func token(expires: Double) throws -> String {
            let payload = try JSONEncoder().encode(["exp": expires]).base64EncodedString()
                .replacingOccurrences(of: "+", with: "-").replacingOccurrences(of: "/", with: "_").replacingOccurrences(of: "=", with: "")
            return "header.\(payload).signature"
        }
        #expect(RumiChatAccess.hasUsableExpiry(try token(expires: now.timeIntervalSince1970 + 600), now: now))
        #expect(!RumiChatAccess.hasUsableExpiry(try token(expires: now.timeIntervalSince1970 - 1), now: now))
        #expect(!RumiChatAccess.hasUsableExpiry(try token(expires: now.timeIntervalSince1970 + 86_400), now: now))
        #expect(!RumiChatAccess.hasUsableExpiry("tenant-api-key", now: now))
    }

    @Test func apiErrorsMapToPlainConnectionErrors() {
        #expect(RumiAPITokenProvider.connectionError(for: .notSignedIn).errorDescription == RumiConnectionError.signIn.errorDescription)
        #expect(RumiAPITokenProvider.connectionError(for: .api(status: 409, code: "onboarding_required", message: "")).errorDescription == RumiConnectionError.onboarding.errorDescription)
        #expect(RumiAPITokenProvider.connectionError(for: .api(status: 409, code: "consent_required", message: "")).errorDescription == RumiConnectionError.consent.errorDescription)
        #expect(RumiAPITokenProvider.connectionError(for: .api(status: 502, code: "chat_server_unavailable", message: "")).errorDescription == RumiConnectionError.unavailable.errorDescription)
    }

    @Test func deltasAndCompletionMustBelongToSelectedServerTurn() throws {
        var accumulator = RumiTurnAccumulator()
        #expect(try accumulator.consume(.init(type: "data", message_id: "stale", text: "wrong")) == nil)
        _ = try accumulator.consume(.init(type: "control", value: "server_processing", message_id: "current"))
        #expect(try accumulator.consume(.init(type: "data", message_id: "stale", text: "wrong")) == nil)
        #expect(try accumulator.consume(.init(type: "data", message_id: "current", text: "Right")) == "Right")
        _ = try accumulator.consume(.init(type: "control", value: "server_paused", message_id: "stale"))
        #expect(!accumulator.isComplete)
        _ = try accumulator.consume(.init(type: "control", value: "server_paused", message_id: "current"))
        #expect(accumulator.isComplete && accumulator.text == "Right")
        #expect(throws: RumiConnectionError.self) { try RumiWireProtocol.decode("not json") }
    }

    @Test func toolFramesDecodeWithTheirArguments() throws {
        let event = try RumiWireProtocol.decode(#"{"type":"tool","value":{"id":"ab12","name":"click","args":{"ref":7,"consequential":true},"highlight_ref":7},"message_id":"m1"}"#)
        let request = try #require(event.tool)
        #expect(request.name == "click" && request.args["ref"]?.intValue == 7 && request.args["consequential"]?.boolValue == true && request.highlight_ref == 7)
        let acting = try RumiWireProtocol.decode(#"{"type":"control","value":"server_acting","message_id":"m1","step":3,"max_steps":30}"#)
        #expect(acting.step == 3 && acting.max_steps == 30)
        let reply = try RumiWireProtocol.toolReply(.init(id: "ab12", ok: true, result: .object(["url": .string("/portal/home")])))
        let sent = try #require(JSONSerialization.jsonObject(with: Data(reply.utf8)) as? [String: Any])
        #expect(sent["type"] as? String == "tool")
        #expect((sent["value"] as? [String: Any])?["ok"] as? Bool == true)
    }

    @Test func theChatDraftAndContextSurviveARelaunch() throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        let model = AppModel(storageDirectory: directory)
        let context = CareContext(id: "a", scenario: model.pathway.rawValue, title: "A", source: "Sample", detail: "Selected A", question: "Question A")
        model.companion.prepare(context: context)
        model.companion.setDraft("Unsent question")
        #expect(model.persistUserData())
        let restored = AppModel(storageDirectory: directory)
        #expect(restored.companion.composerDraft == "Unsent question" && restored.companion.pendingContext == context)
        #expect(restored.aiRouter.clientID == model.aiRouter.clientID)
    }

    @Test func signedOutChatSendsNothing() async throws {
        var opened = 0
        let router = RumiAIRouter(api: signedOutAPI()) { _, _, _, _ in opened += 1; return HeldSession() }
        #expect(!router.canSend)
        await #expect(throws: RumiConnectionError.self) { try await router.prepareVisit(input: "Private draft") }
        await #expect(throws: RumiConnectionError.self) {
            try await router.stream(requestID: UUID(), system: "", messages: [.init(role: "user", content: "Question")], onDelta: { _ in })
        }
        await #expect(throws: RumiConnectionError.self) {
            try await router.speak(pcm: Data([1, 2, 3]), onTranscript: { _ in }, onDelta: { _ in }, onAudio: { _ in })
        }
        #expect(opened == 0)
    }

    @Test func documentedTextOrderRefreshesTheSameSocketWithoutReplay() async throws {
        let socket = ScriptedRumiSocket(events: [
            "{\"type\":\"auth\",\"value\":\"session_expiring\"}",
            "{\"type\":\"control\",\"value\":\"server_processing\",\"message_id\":\"turn-a\"}",
            "{\"type\":\"control\",\"value\":\"server_speaking\",\"message_id\":\"turn-a\"}",
            "{\"type\":\"data\",\"text\":\"Ignore\",\"audio\":null,\"message_id\":\"old\"}",
            "{\"type\":\"data\",\"text\":\"Selected reply\",\"audio\":null,\"message_id\":\"turn-a\"}",
            "{\"type\":\"control\",\"value\":\"server_paused\",\"message_id\":\"turn-a\"}"
        ])
        let tokens = TestRumiTokens()
        let session = RumiChatSession(tokens: tokens, device: RumiNoPortalDevice(), sessionID: UUID(), makeSocket: { socket })
        let result = try await session.stream(requestID: UUID(), system: "Must not be a made-up system frame", messages: [.init(role: "assistant", content: "Old provider history"), .init(role: "user", content: "Only selected question")], onDelta: { _ in })
        #expect(result == "Selected reply")
        let sent = try socket.sent.map { try #require(JSONSerialization.jsonObject(with: Data($0.utf8)) as? [String: Any]) }
        #expect(sent.prefix(5).map { $0["type"] as? String } == ["auth", "flag", "control", "text", "control"])
        #expect(sent[1]["value"] as? [String: String] == ["voice": "0"])
        #expect(sent[2]["value"] as? String == "client_speaking" && sent[4]["value"] as? String == "client_paused")
        #expect(sent[3]["value"] as? String == "Only selected question")
        #expect(!sent.contains { ($0["value"] as? String)?.contains("Old provider history") == true })
        let limit = Date.now.addingTimeInterval(2)
        while tokens.count < 2 && Date.now < limit { try await Task.sleep(for: .milliseconds(10)) }
        #expect(tokens.count == 2 && socket.sent.filter { $0.contains("\"auth\"") }.count == 2)
        #expect(socket.openCount == 1 && !socket.closed && session.isConnected)
        session.close()
        #expect(socket.closed && !session.isConnected)
    }

    @Test func toolRequestsAreAnsweredByTheDeviceDuringATurn() async throws {
        let socket = ScriptedRumiSocket(events: [
            "{\"type\":\"control\",\"value\":\"server_processing\",\"message_id\":\"t\"}",
            "{\"type\":\"tool\",\"value\":{\"id\":\"r1\",\"name\":\"open\",\"args\":{\"path\":\"/portal/home\"}},\"message_id\":\"t\"}",
            "{\"type\":\"control\",\"value\":\"server_acting\",\"message_id\":\"t\",\"step\":1,\"max_steps\":30}",
            "{\"type\":\"data\",\"text\":\"I could not open your portal.\",\"message_id\":\"t\"}",
            "{\"type\":\"control\",\"value\":\"server_paused\",\"message_id\":\"t\"}"
        ])
        let device = RecordingDevice()
        var statuses: [String] = []
        let session = RumiChatSession(tokens: TestRumiTokens(), device: device, sessionID: UUID(), makeSocket: { socket }, status: { statuses.append($0) })
        let result = try await session.stream(requestID: UUID(), system: "", messages: [.init(role: "user", content: "Book my follow-up")], onDelta: { _ in })
        #expect(result == "I could not open your portal.")
        #expect(device.requests.map(\.name) == ["open"])
        let reply = try #require(socket.sent.first { $0.contains("\"r1\"") })
        #expect(reply.contains("\"ok\":false"))
        #expect(statuses.contains { $0.contains("step 1 of 30") })
    }

    @Test func authenticationFailureAndTruncationNeverComplete() async throws {
        for events in [["{\"type\":\"auth\",\"value\":\"auth_failed\"}"], ["{\"type\":\"control\",\"value\":\"server_processing\",\"message_id\":\"a\"}", "{\"type\":\"data\",\"message_id\":\"a\",\"text\":\"Partial\"}"]] {
            let socket = ScriptedRumiSocket(events: events)
            let session = RumiChatSession(tokens: TestRumiTokens(), device: RumiNoPortalDevice(), sessionID: UUID(), makeSocket: { socket })
            await #expect(throws: RumiConnectionError.self) {
                try await session.stream(requestID: UUID(), system: "", messages: [.init(role: "user", content: "Sample")], onDelta: { _ in })
            }
            #expect(!session.isConnected)
        }
    }

    @Test func cancellingDropsLateOutputFromTheTurn() async throws {
        let held = HeldSession()
        let router = RumiAIRouter(api: try await signedInAPI()) { _, _, _, _ in held }
        var deltas = ""
        let operation = Task { try await router.stream(requestID: UUID(), system: "", messages: [.init(role: "user", content: "Sample")]) { deltas += $0 } }
        let limit = Date.now.addingTimeInterval(2)
        while held.continuation == nil && Date.now < limit { try await Task.sleep(for: .milliseconds(10)) }
        #expect(held.continuation != nil)
        router.cancelAll()
        held.delta?("Late text")
        held.continuation?.resume(returning: "Late reply")
        await #expect(throws: CancellationError.self) { try await operation.value }
        #expect(deltas.isEmpty)
    }

    @Test func aSpokenTurnSendsTheVoiceFlagAndAudioAndReturnsTheReply() async throws {
        let speech = Data("hello".utf8).base64EncodedString()
        let socket = ScriptedRumiSocket(events: [
            "{\"type\":\"control\",\"value\":\"server_processing\",\"message_id\":\"v\"}",
            "{\"type\":\"transcript\",\"text\":\"Book my follow-up\",\"message_id\":\"v\"}",
            "{\"type\":\"control\",\"value\":\"server_speaking\",\"message_id\":\"v\"}",
            "{\"type\":\"data\",\"text\":\"Sure.\",\"audio\":\"\(speech)\",\"message_id\":\"v\"}",
            "{\"type\":\"control\",\"value\":\"server_paused\",\"message_id\":\"v\"}"
        ])
        let session = RumiChatSession(tokens: TestRumiTokens(), device: RumiNoPortalDevice(), sessionID: UUID(), makeSocket: { socket })
        var heard = "", audio = Data()
        // A slice keeps its parent's indexes, which is what a WAV reader hands over.
        let pcm = Data((0..<(16_000 * 3 + 10)).map { UInt8($0 % 256) }).dropFirst(4)
        let reply = try await session.speak(pcm: pcm, onTranscript: { heard = $0 }, onDelta: { _ in }, onAudio: { audio.append($0) })
        #expect(reply == "Sure." && heard == "Book my follow-up" && audio == Data("hello".utf8))
        let sent = try socket.sent.map { try #require(JSONSerialization.jsonObject(with: Data($0.utf8)) as? [String: Any]) }
        #expect(sent.map { $0["type"] as? String } == ["auth", "flag", "flag", "control", "audio", "audio", "control"])
        #expect(sent[2]["value"] as? [String: String] == ["voice": "1"])
        let frames = try sent.filter { $0["type"] as? String == "audio" }.map { frame in
            try JSONSerialization.jsonObject(with: Data(try #require(frame["value"] as? String).utf8)) as? [Int] ?? []
        }
        #expect(frames.map(\.count) == [16_000 * 3, 6] && Data(frames.joined().map { UInt8($0) }) == pcm)
        session.close()
    }

    @Test func cancellingBetweenControlAndTextDoesNotTransmitQuestion() async throws {
        let socket = HeldSendRumiSocket()
        let session = RumiChatSession(tokens: TestRumiTokens(), device: RumiNoPortalDevice(), sessionID: UUID(), makeSocket: { socket })
        let operation = Task { try await session.stream(requestID: UUID(), system: "", messages: [.init(role: "user", content: "Do not transmit")], onDelta: { _ in }) }
        let limit = Date.now.addingTimeInterval(2)
        while socket.waiter == nil && Date.now < limit { try await Task.sleep(for: .milliseconds(10)) }
        #expect(socket.waiter != nil)
        operation.cancel()
        socket.waiter?.resume()
        await #expect(throws: CancellationError.self) { try await operation.value }
        #expect(!socket.sent.contains(where: { $0.contains("Do not transmit") }))
    }

    @Test func recordedWAVGivesOnlyItsSamples() throws {
        func le32(_ value: Int) -> Data { Data((0..<4).map { UInt8((value >> (8 * $0)) & 0xff) }) }
        let samples = Data([1, 2, 3, 4, 5, 6])
        var wav = Data("RIFF".utf8) + le32(0) + Data("WAVE".utf8)
        wav += Data("fmt ".utf8) + le32(16) + Data(count: 16)
        wav += Data("FLLR".utf8) + le32(3) + Data(count: 4)
        wav += Data("data".utf8) + le32(samples.count) + samples
        let url = FileManager.default.temporaryDirectory.appendingPathComponent("\(UUID().uuidString).wav")
        try wav.write(to: url)
        defer { try? FileManager.default.removeItem(at: url) }
        #expect(VoiceSession.pcm(fromWAV: url) == samples)
    }

    @Test func aSpokenTurnJoinsTheChatHistory() {
        let engine = CompanionEngine(transport: RecordingAITransport())
        engine.recordSpokenTurn(heard: "  What is my next visit?  ", reply: "Your next visit is on Monday.")
        #expect(engine.turns.map(\.text) == ["What is my next visit?", "Your next visit is on Monday."])
        #expect(engine.turns.last?.replyTo == engine.turns.first?.id)
        engine.recordSpokenTurn(heard: "   ", reply: "Ignored")
        #expect(engine.turns.count == 2)
    }

    private func signedInAPI() async throws -> RumiAPI {
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [SignInStub.self]
        Keychain.delete("refresh_token", service: "app.rumi.api.router-tests-in")
        let api = RumiAPI(baseURL: URL(string: "https://api.test")!, session: URLSession(configuration: config), keychainService: "app.rumi.api.router-tests-in")
        try await api.devSignIn(email: "dev@rumi.local")
        return api
    }

    private func signedOutAPI() -> RumiAPI {
        Keychain.delete("refresh_token", service: "app.rumi.api.router-tests")
        return RumiAPI(baseURL: URL(string: "https://api.test")!, keychainService: "app.rumi.api.router-tests")
    }
}

@MainActor private final class RecordingAITransport: ChatTransport {
    var messages: [[AIChatMessage]] = []
    func stream(requestID: UUID, system: String, messages: [AIChatMessage], onDelta: @escaping @MainActor (String) -> Void) async throws -> String { self.messages.append(messages); return "A question to review" }
}

@MainActor private final class HeldSession: RumiChatSessioning {
    var continuation: CheckedContinuation<String, any Error>?
    var delta: (@MainActor (String) -> Void)?
    var isConnected: Bool { true }
    func close() {}
    func stream(requestID: UUID, system: String, messages: [AIChatMessage], onDelta: @escaping @MainActor (String) -> Void) async throws -> String {
        delta = onDelta
        return try await withCheckedThrowingContinuation { continuation = $0 }
    }
    func speak(pcm: Data, onTranscript: @escaping @MainActor (String) -> Void, onDelta: @escaping @MainActor (String) -> Void,
               onAudio: @escaping @MainActor (Data) -> Void) async throws -> String {
        try await stream(requestID: UUID(), system: "", messages: [], onDelta: onDelta)
    }
}

/// Answers every request with a signed-in token reply, so a router test can run as a signed-in patient.
nonisolated private final class SignInStub: URLProtocol {
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        let body = #"{"access_token":"access-1","expires_in":900,"refresh_token":"rt_1","user":{"id":"u1","email":"dev@rumi.local","display_name":"Dev","status":"active","onboarding_complete":true,"providers":["dev"],"created_at":"2026-10-05T10:00:00Z"}}"#
        let response = HTTPURLResponse(url: request.url!, statusCode: 200, httpVersion: nil, headerFields: ["Content-Type": "application/json"])!
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: Data(body.utf8))
        client?.urlProtocolDidFinishLoading(self)
    }
    override func stopLoading() {}
}

@MainActor private final class TestRumiTokens: RumiTokenProviding {
    var count = 0
    func access() async throws -> RumiChatAccess {
        count += 1
        return RumiChatAccess(accessToken: "synthetic-chat-token-\(count)", expiresIn: 600, socketUrl: "ws://localhost:8101/ws", tenant: "test-tenant")
    }
    func configuration(for access: RumiChatAccess) async throws -> RumiWireProtocol.Configuration { .init(tenant_id: "test-tenant", chat_type: "CHAT") }
}

@MainActor private final class RecordingDevice: RumiToolDevice {
    var requests: [RumiWireProtocol.ToolRequest] = []
    func handle(_ request: RumiWireProtocol.ToolRequest) async -> RumiWireProtocol.ToolReply {
        requests.append(request)
        return .init(id: request.id, ok: false, error: "no portal in tests")
    }
    func cancelAll() {}
}

@MainActor private final class HeldSendRumiSocket: RumiSocketConnecting {
    var sent: [String] = []
    var waiter: CheckedContinuation<Void, Never>?
    var closed = false
    func open(url: URL) async throws { }
    func send(_ text: String) async throws {
        sent.append(text)
        if text.contains("client_speaking") { await withCheckedContinuation { waiter = $0 } }
    }
    func receive() async throws -> String { try await Task.sleep(for: .seconds(30)); throw RumiConnectionError.disconnected }
    func close() { closed = true }
}

@MainActor private final class ScriptedRumiSocket: RumiSocketConnecting {
    var events: [String]
    var sent: [String] = []
    var openCount = 0
    var closed = false
    init(events: [String]) { self.events = events }
    func open(url: URL) async throws { openCount += 1 }
    func send(_ text: String) async throws { #expect(openCount == 1); sent.append(text) }
    func receive() async throws -> String {
        if events.isEmpty {
            // A real socket stays quiet after the last frame; only a close ends it.
            try await Task.sleep(for: .seconds(30))
            throw RumiConnectionError.disconnected
        }
        return events.removeFirst()
    }
    func close() { closed = true }
}
