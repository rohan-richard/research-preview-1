import SwiftUI

struct ConversationView: View {
    @Environment(AppModel.self) private var model
    var orbSpace: Namespace.ID
    @State private var showAIConnection: Bool = false
    @State private var showVoice: Bool = false
    @State private var followLatest: Bool = true
    @FocusState private var focused: Bool

    var body: some View {
        ZStack {
            ConversationScene()
            VStack(spacing: 0) {
                HStack {
                    Button { model.closeConversation() } label: { Image(systemName: "chevron.down").frame(width: 44, height: 44) }
                        .accessibilityLabel("Close conversation").accessibilityIdentifier("chat.close")
                    Spacer()
                    RumiMarkView(size: 30, animated: model.companion.isThinking)
                    Text("Rumi").font(NudgeType.display(26))
                    Spacer()
                    Button { showVoice = true } label: { Image(systemName: "waveform").frame(width: 44, height: 44) }
                        .accessibilityLabel("Talk out loud")
                }.padding(.horizontal, 18)
                Button { focused = false; showAIConnection = true } label: {
                    HStack(spacing: 6) {
                        Text("Rumi chat · sample care")
                        Image(systemName: "chevron.down").font(.system(size: 10, weight: .semibold))
                    }.font(NudgeType.rounded(12)).foregroundStyle(Theme.inkMuted).frame(minHeight: 44)
                }.accessibilityIdentifier("chat.aiConnection")
                ScrollViewReader { proxy in
                    ScrollView {
                        LazyVStack(alignment: .leading, spacing: 20) {
                            ForEach(model.companion.turns) { turn in ConversationTurnView(turn: turn) }
                            Color.clear.frame(height: 8).id("latest")
                        }.padding(.horizontal, 22).padding(.vertical, 12)
                    }
                    .scrollDismissesKeyboard(.interactively)
                    .onScrollGeometryChange(for: Bool.self) { geometry in
                        geometry.contentOffset.y + geometry.containerSize.height >= geometry.contentSize.height - 140
                    } action: { _, atBottom in followLatest = atBottom }
                    .onChange(of: model.companion.turns.count) { _, _ in withAnimation { proxy.scrollTo("latest", anchor: .bottom) } }
                    .onChange(of: model.companion.turns.last?.text) { _, _ in if followLatest { proxy.scrollTo("latest", anchor: .bottom) } }
                    .onAppear { proxy.scrollTo("latest", anchor: .bottom) }
                }
                if model.companion.turns.count <= 1 && model.companion.pendingContext == nil {
                    ScrollView(.horizontal) {
                        HStack(spacing: 8) {
                            ForEach(["Help me prepare for a visit", "Make a habit easier", "A question about my results"], id: \.self) { text in
                                Button(text) { if model.companion.composerDraft.isEmpty { model.companion.setDraft(text) } }
                                    .font(NudgeType.rounded(13)).padding(.horizontal, 14).frame(minHeight: 44)
                                    .background(Theme.surface, in: .capsule)
                            }
                        }
                    }.contentMargins(.horizontal, 20).scrollIndicators(.hidden)
                }
                if model.companion.turns.count <= 1 {
                    Text("Messages and sample context are processed by AI. Please don't enter real medical information in this demo.")
                        .font(NudgeType.rounded(11)).foregroundStyle(Theme.inkMuted).padding(.horizontal, 22).padding(.top, 10)
                }
                if let context = model.companion.pendingContext {
                    CareContextView(context: context, remove: { model.companion.removeContext() })
                        .padding(.horizontal, 18).padding(.top, 8)
                    Text("Send shares this context and your question with AI. Close returns without sending.")
                        .font(NudgeType.rounded(11)).foregroundStyle(Theme.inkMuted).padding(.horizontal, 22).padding(.top, 4)
                }
                if !model.aiRouter.canSend {
                    Button("Sign in to chat with Rumi") { showAIConnection = true }
                        .font(NudgeType.rounded(13)).frame(minHeight: 44).accessibilityIdentifier("chat.backendSetup")
                }
                if let error = model.companion.lastError {
                    Text(error).font(NudgeType.rounded(12)).foregroundStyle(Theme.attention).padding(.horizontal, 20)
                }
                HStack(alignment: .bottom, spacing: 10) {
                    TextField("What's on your mind?", text: Binding(get: { model.companion.composerDraft }, set: { model.companion.setDraft($0) }), axis: .vertical)
                        .font(NudgeType.rounded(16)).lineLimit(1...5).focused($focused)
                        .padding(15).background(Theme.surface, in: .rect(cornerRadius: 23))
                        .accessibilityIdentifier("chat.composer")
                    if model.companion.isThinking {
                        Button { model.companion.endSession(orb: model.orb) } label: {
                            Image(systemName: "stop.fill").frame(width: 48, height: 48).background(Theme.accentSoft, in: .circle)
                        }.accessibilityLabel("Stop reply").accessibilityIdentifier("chat.stop")
                    }
                    if !model.companion.composerDraft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                        Button { model.companion.send(model.companion.composerDraft, orb: model.orb) } label: {
                            Image(systemName: "arrow.up").font(.system(size: 18, weight: .semibold))
                                .foregroundStyle(Theme.onAccent).frame(width: 48, height: 48).background(Theme.buttonFill, in: .circle)
                        }.accessibilityLabel("Send").accessibilityIdentifier("chat.send").disabled(!model.aiRouter.canSend || model.companion.isThinking)
                    }
                }.padding(.horizontal, 18).padding(.vertical, 12)
            }
        }
        .foregroundStyle(Theme.ink)
        .sheet(isPresented: $showAIConnection) { AIConnectionView() }
        .fullScreenCover(isPresented: $showVoice) { VoiceModeView() }
        .onDisappear { model.persistUserData() }
        .alert("Keep your current question?", isPresented: Binding(get: { model.companion.replacementContext != nil }, set: { if !$0 { model.companion.replacementContext = nil } })) {
            Button("Keep current draft", role: .cancel) { model.companion.replacementContext = nil }
            Button("Replace draft and context", role: .destructive) { model.companion.replaceDraftAndContext() }
        } message: { Text("You have edited a question about another item. Replacing starts a new question about \(model.companion.replacementContext?.title ?? "the selected item") and replaces the unsent words.") }
    }
}

/// The supplied mint/blush/butter palette stays behind opaque readable message content.
struct ConversationScene: View {
    @Environment(\.colorScheme) private var scheme
    var body: some View {
        let palette = Theme.conversationPalette(scheme)
        ZStack {
            LivingGradientView()
            LinearGradient(colors: [palette.0.opacity(0.45), .clear, palette.1.opacity(0.3)], startPoint: .topLeading, endPoint: .bottomTrailing)
        }.ignoresSafeArea().allowsHitTesting(false)
    }
}

private struct ConversationTurnView: View {
    @Environment(AppModel.self) private var model
    let turn: ConversationTurn
    @State private var showHabit: Bool = false
    @State private var showWorkflow: Bool = false

    var body: some View {
        HStack {
            if turn.role == .user { Spacer(minLength: 36) }
            VStack(alignment: .leading, spacing: 12) {
                if turn.role == .user, let context = turn.context { CareContextView(context: context) }
                if !turn.text.isEmpty {
                    Text(turn.text).font(NudgeType.rounded(16)).textSelection(.enabled)
                        .fixedSize(horizontal: false, vertical: true)
                        .accessibilityIdentifier(turn.role == .user ? "chat.userMessage" : "chat.response")
                }
                if turn.streaming && turn.text.isEmpty { ProgressView().accessibilityLabel("Rumi is thinking") }
                if turn.delivery == .interrupted || turn.delivery == .failed {
                    Text(turn.delivery == .failed ? "Reply unavailable. Your message is kept." : "Reply stopped. This answer may be incomplete.")
                        .font(NudgeType.rounded(13)).foregroundStyle(Theme.attention).accessibilityIdentifier("chat.interrupted")
                    if model.companion.canRetry(turn) && model.aiRouter.canSend {
                        Text("The server may have processed this message. Trying again can repeat it.").font(.caption).foregroundStyle(Theme.inkMuted)
                        Button("Try again") { model.companion.retry(turnID: turn.id, orb: model.orb) }.frame(minHeight: 44)
                    }
                }
                if turn.delivery == .complete { richContent }
            }
            .padding(16)
            .background(turn.role == .user ? Theme.accentSoft : Theme.surface, in: .rect(cornerRadius: 22))
            if turn.role == .companion { Spacer(minLength: 12) }
        }
        .sheet(isPresented: $showHabit) {
            if case .habitProposal(let title, let cue) = turn.rich {
                HabitPlanView(proposedTitle: title, proposedCue: cue, onSaved: { model.companion.resolveRich(turnID: turn.id) })
            }
        }
        .sheet(isPresented: $showWorkflow) {
            WorkflowReviewView(originID: turn.id, title: proposalTitle, detail: proposalDetail, context: turn.context)
        }
    }

    @ViewBuilder private var richContent: some View {
        if turn.declined {
            Text("Not now · nothing was done").font(NudgeType.rounded(13)).foregroundStyle(Theme.inkMuted)
        } else {
            switch turn.rich {
            case .none: EmptyView()
            case .trend(let id):
                if let series = model.series(id) { GlowChart(series: series, accent: Theme.warm, height: 130, showAnnotation: true) }
            case .guideAdd(let question):
                Text(question).font(NudgeType.serif(18))
                if turn.richResolved { Label("Added to your discussion guide", systemImage: "checkmark").font(.caption) }
                else {
                    Button("Add question to my guide") {
                        model.addGuideItem(kind: .question, text: question, from: "AI draft · chosen by you")
                        model.companion.resolveRich(turnID: turn.id)
                    }.frame(minHeight: 44)
                    decline
                }
            case .habitProposal(let title, let cue):
                Text(title).font(NudgeType.serif(18))
                Text(cue).font(NudgeType.rounded(13)).foregroundStyle(Theme.inkMuted)
                if turn.richResolved { Text("Step chosen · not marked completed").font(.caption) }
                else { Button("Make it my own") { showHabit = true }.frame(minHeight: 44); decline }
            case .agentAction, .refillFix:
                Text(proposalTitle).font(NudgeType.serif(18))
                Text("Draft only · nothing sent").font(.caption).foregroundStyle(Theme.inkMuted)
                Button(turn.richResolved ? "Open saved draft" : "Review this draft") { showWorkflow = true }.frame(minHeight: 44)
                if !turn.richResolved { decline }
            case .program:
                Text("Program suggestions need eligibility review.").font(.caption)
            }
        }
    }
    private var decline: some View {
        Button("Not now") { model.companion.declineRich(turnID: turn.id) }.frame(minHeight: 44).foregroundStyle(Theme.inkMuted)
    }
    private var proposalTitle: String {
        switch turn.rich { case .agentAction(let title, _): return title; case .refillFix(let med, _): return "Refill question · \(med)"; default: return "Draft" }
    }
    private var proposalDetail: String {
        switch turn.rich { case .agentAction(_, let detail), .refillFix(_, let detail): return detail; default: return "" }
    }
}
