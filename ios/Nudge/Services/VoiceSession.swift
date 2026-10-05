import AVFoundation
import Observation

/// The hands-free voice loop: the mic opens, silence ends the turn, and the chat server
/// transcribes it, answers and speaks the answer back over the same chat socket.
@Observable final class VoiceSession {
    enum Phase: Equatable {
        case idle
        case listening
        case transcribing
        case thinking
        case speaking
        case unavailable(String)
    }

    var phase: Phase = .idle
    /// Mic/playback energy 0…1 — drives the listening and speaking glow.
    var level: Double = 0
    var heardText = ""
    var replyText = ""

    private var recorder: AVAudioRecorder?
    private var meterTask: Task<Void, Never>?
    private var processTask: Task<Void, Never>?
    private var player: AVAudioPlayer?
    private var shouldContinue = false
    /// Consecutive empty transcriptions — only after a couple do we surface a
    /// gentle hint, so a moment of quiet never trips a jarring "didn't get it".
    private var consecutiveMisses = 0

    private var recordingURL: URL {
        FileManager.default.temporaryDirectory.appendingPathComponent("rumi_voice.wav")
    }

    /// Starts the hands-free call. Once started, turns auto-commit on silence.
    func start(model: AppModel) {
        guard model.aiRouter.canSend else {
            phase = .unavailable("Sign in to talk with Rumi.")
            return
        }
        guard phase == .idle || isUnavailable else { return }
        shouldContinue = true
        startListening(model: model)
    }

    /// Stops the call from any phase and restores the ambient world.
    func stop(model: AppModel) {
        shouldContinue = false
        meterTask?.cancel()
        processTask?.cancel()
        recorder?.stop()
        recorder = nil
        player?.stop()
        player = nil
        level = 0
        restorePlaybackSession()
        model.orb.set(.ambient)
        phase = .idle
        if SoundEngine.shared.currentBed != nil {
            SoundEngine.shared.playBed(.ambient, fade: 1.4)
        }
    }

    /// Tap is now only start / interrupt / end — never required each turn.
    func toggle(model: AppModel) {
        switch phase {
        case .idle, .unavailable:
            start(model: model)
        case .listening, .transcribing, .thinking, .speaking:
            stop(model: model)
        }
    }

    func teardown(orb: OrbState) {
        shouldContinue = false
        meterTask?.cancel()
        processTask?.cancel()
        recorder?.stop()
        recorder = nil
        player?.stop()
        player = nil
        restorePlaybackSession()
        orb.set(.ambient)
        phase = .idle
    }

    private var isUnavailable: Bool {
        if case .unavailable = phase { return true }
        return false
    }

    // MARK: - Listening

    private func startListening(model: AppModel) {
        guard shouldContinue, model.aiRouter.canSend else { return }
        heardText = ""
        replyText = ""
        Task {
            let granted = await AVAudioApplication.requestRecordPermission()
            guard granted else {
                phase = .unavailable("I'd love to hear you — allow the microphone in Settings and we'll talk.")
                return
            }
            guard shouldContinue, model.aiRouter.canSend else { return }
            beginRecording(model: model)
        }
    }

    private func beginRecording(model: AppModel) {
        player?.stop()
        player = nil
        SoundEngine.shared.pauseBed(fade: 0.2)

        let session = AVAudioSession.sharedInstance()
        do {
            try session.setCategory(.playAndRecord, mode: .voiceChat, options: [.defaultToSpeaker, .allowBluetoothHFP])
            try session.setActive(true)
            // The chat server reads raw 16 kHz mono 24-bit little-endian PCM.
            let settings: [String: Any] = [
                AVFormatIDKey: kAudioFormatLinearPCM,
                AVSampleRateKey: 16_000,
                AVNumberOfChannelsKey: 1,
                AVLinearPCMBitDepthKey: 24,
                AVLinearPCMIsFloatKey: false,
                AVLinearPCMIsBigEndianKey: false,
            ]
            let recorder = try AVAudioRecorder(url: recordingURL, settings: settings)
            recorder.isMeteringEnabled = true
            guard recorder.record() else {
                phase = .unavailable("Voice needs a microphone. Allow it in Settings and try again.")
                return
            }
            self.recorder = recorder
            phase = .listening
            model.orb.set(.listening)
            Haptics.glass()
            SoundEngine.shared.glass()
            startListeningMeter(model: model)
        } catch {
            print("[Rumi] voice recording unavailable: \(error.localizedDescription)")
            phase = .unavailable("Voice needs a microphone. Allow it in Settings and try again.")
        }
    }

    /// Lightweight client-side VAD: once speech is detected, a steady quiet
    /// window commits the turn. That gives the hands-free turn-taking behavior
    /// without asking the user to tap at the end of every sentence. Tuned so a
    /// natural mid-sentence pause doesn't cut you off, and a held silence with
    /// no speech at all recycles the mic instead of transcribing noise.
    private func startListeningMeter(model: AppModel) {
        meterTask?.cancel()
        meterTask = Task { [weak self] in
            var heardSpeech = false
            var quietFrames = 0
            let startedAt = Date()
            let earliestCommit = startedAt.addingTimeInterval(1.0)

            while let self, !Task.isCancelled, self.phase == .listening {
                self.recorder?.updateMeters()
                let power = self.recorder?.averagePower(forChannel: 0) ?? -60
                let normalized = pow(10, Double(power) / 20)
                let currentLevel = min(max(normalized * 2.8, 0), 1)
                self.level = currentLevel

                if currentLevel > 0.06 { heardSpeech = true }
                // ~1.1s of quiet after real speech commits the turn.
                if heardSpeech && Date() > earliestCommit && currentLevel < 0.04 {
                    quietFrames += 1
                } else {
                    quietFrames = 0
                }

                if heardSpeech && quietFrames >= 26 {
                    self.finishListening(model: model, heardSpeech: true)
                    return
                }

                // Nobody spoke for ~8s — recycle the mic quietly rather than
                // sending silence to the transcriber.
                if !heardSpeech && Date().timeIntervalSince(startedAt) > 8 {
                    self.finishListening(model: model, heardSpeech: false)
                    return
                }
                try? await Task.sleep(for: .milliseconds(42))
            }
        }
    }

    private func finishListening(model: AppModel, heardSpeech: Bool) {
        guard phase == .listening else { return }
        meterTask?.cancel()
        level = 0
        recorder?.stop()
        recorder = nil

        // Nothing was said — silently re-open the mic, no error, no fuss.
        guard heardSpeech else {
            phase = .idle
            model.orb.set(.ambient)
            if shouldContinue {
                Task { [weak self] in
                    try? await Task.sleep(for: .milliseconds(250))
                    if self?.shouldContinue == true { self?.startListening(model: model) }
                }
            }
            return
        }

        Haptics.pull()
        phase = .transcribing
        model.orb.set(.thinking)

        processTask = Task { [weak self] in
            guard let self else { return }
            guard let pcm = Self.pcm(fromWAV: recordingURL), pcm.count > 16_000 * 3 / 2 else {
                self.keepListening(model: model)
                return
            }
            var spoken = Data()
            do {
                let reply = try await model.aiRouter.speak(pcm: pcm, onTranscript: { [weak self] text in
                    self?.heardText = text
                    self?.phase = .thinking
                }, onDelta: { [weak self] delta in
                    self?.replyText += delta
                }, onAudio: { chunk in
                    spoken.append(chunk)
                })
                guard !Task.isCancelled else { return }
                guard !self.heardText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
                    self.keepListening(model: model)
                    return
                }
                self.consecutiveMisses = 0
                model.companion.recordSpokenTurn(heard: self.heardText, reply: reply)
                self.replyText = reply
                await self.play(spoken, model: model)
            } catch is CancellationError {
                return
            } catch {
                guard !Task.isCancelled else { return }
                self.shouldContinue = false
                model.orb.set(.ambient)
                self.phase = .unavailable((error as? RumiConnectionError)?.errorDescription ?? "Rumi could not answer out loud. Try again in a moment.")
            }
        }
    }

    /// Nothing usable was heard: say so only after a couple of misses, then listen again.
    private func keepListening(model: AppModel) {
        consecutiveMisses += 1
        heardText = ""
        replyText = consecutiveMisses >= 2 ? "Still here. Take your time, I'm listening." : ""
        model.orb.set(.ambient)
        phase = .idle
        guard shouldContinue else { return }
        Task { [weak self] in
            try? await Task.sleep(for: .milliseconds(500))
            if self?.shouldContinue == true { self?.startListening(model: model) }
        }
    }

    /// The samples from a WAV file. AVAudioRecorder can put other chunks before "data", so walk them.
    nonisolated static func pcm(fromWAV url: URL) -> Data? {
        guard let file = try? Data(contentsOf: url), file.count > 12,
              file.prefix(4) == Data("RIFF".utf8), file[8..<12] == Data("WAVE".utf8) else { return nil }
        var offset = 12
        while offset + 8 <= file.count {
            let id = file[offset..<offset + 4]
            let size = file[offset + 4..<offset + 8].enumerated().reduce(0) { $0 | Int($1.element) << (8 * $1.offset) }
            let body = offset + 8
            if id == Data("data".utf8) { return Data(file[body..<min(body + size, file.count)]) }
            offset = body + size + (size & 1)
        }
        return nil
    }

    private func play(_ audio: Data, model: AppModel) async {
        guard audio.count > 800, let player = try? AVAudioPlayer(data: audio) else {
            finishSpeaking(model: model)
            return
        }
        player.isMeteringEnabled = true
        self.player = player
        SoundEngine.shared.pauseBed(fade: 0.25)
        player.volume = 1
        player.play()
        phase = .speaking
        model.orb.set(.speaking)
        startSpeakingMeter()
        try? await Task.sleep(for: .seconds(player.duration + 0.15))
        if phase == .speaking { finishSpeaking(model: model) }
    }

    private func startSpeakingMeter() {
        meterTask?.cancel()
        meterTask = Task { [weak self] in
            while let self, !Task.isCancelled, self.phase == .speaking {
                self.player?.updateMeters()
                let power = self.player?.averagePower(forChannel: 0) ?? -60
                let normalized = pow(10, Double(power) / 20)
                self.level = min(max(normalized * 2.2, 0), 1)
                try? await Task.sleep(for: .milliseconds(33))
            }
            self?.level = 0
        }
    }

    private func finishSpeaking(model: AppModel) {
        meterTask?.cancel()
        level = 0
        player?.stop()
        player = nil
        phase = .idle
        model.orb.set(.ambient)

        if shouldContinue {
            Task {
                try? await Task.sleep(for: .milliseconds(450))
                if shouldContinue { startListening(model: model) }
            }
        } else if SoundEngine.shared.currentBed != nil {
            restorePlaybackSession()
            SoundEngine.shared.playBed(.ambient, fade: 1.6)
        }
    }

    private func restorePlaybackSession() {
        let session = AVAudioSession.sharedInstance()
        try? session.setCategory(.playback, options: [.mixWithOthers])
        try? session.setActive(true)
    }
}
