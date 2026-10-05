import AVFoundation
import Foundation
import Testing
@testable import Nudge

/// Runs against the API and chat server on this Mac. Pass a 16 kHz mono 24-bit WAV of speech with
/// TEST_RUNNER_RUMI_VOICE_WAV=/path/to/speech.wav; without it the test is skipped.
@MainActor struct LiveVoiceTests {
    static let speech = ProcessInfo.processInfo.environment["RUMI_VOICE_WAV"]

    @Test(.enabled(if: speech != nil))
    func aSpokenQuestionGetsASpokenAnswer() async throws {
        let path = try #require(Self.speech)
        let pcm = try #require(VoiceSession.pcm(fromWAV: URL(fileURLWithPath: path)))
        Keychain.delete("refresh_token", service: "app.rumi.api.live-voice")
        let api = RumiAPI(baseURL: URL(string: "http://localhost:8000")!, keychainService: "app.rumi.api.live-voice")
        try await api.devSignIn(email: "dev@rumi.local")
        let session = RumiChatSession(tokens: RumiAPITokenProvider(api: api), device: RumiNoPortalDevice(), sessionID: UUID())
        defer { session.close() }

        var heard = "", audio = Data()
        let reply = try await session.speak(pcm: pcm, onTranscript: { heard = $0 }, onDelta: { _ in }, onAudio: { audio.append($0) })

        #expect(heard.lowercased().contains("health"))
        #expect(reply.count > 20)
        let player = try AVAudioPlayer(data: audio)
        #expect(player.duration > 2)

        // The same socket goes back to text for a typed question.
        let typed = try await session.stream(requestID: UUID(), system: "", messages: [.init(role: "user", content: "Thanks. Just say ok.")], onDelta: { _ in })
        #expect(!typed.isEmpty)
    }
}
