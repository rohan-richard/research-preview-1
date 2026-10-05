import SwiftUI

/// The shell after onboarding: tab scenes, floating dock, the persistent
/// minimized orb, the conversation morph, quick-log sheet, and the recap film.
/// The whole canvas answers touch — every tap sends a fluid wave through the
/// world, not just one corner of it.
struct RootView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.scenePhase) private var scenePhase
    @Namespace private var orbSpace

    var body: some View {
        @Bindable var model = model

        ZStack {
            Group {
                switch model.tab {
                case .today:
                    TodayCanvasView(orbSpace: orbSpace)
                case .care:
                    CareHubView()
                case .you:
                    YouView()
                case .messages:
                    CareHubView(isMessages: true)
                }
            }
            .opacity(model.showConversation ? 0 : 1)

            if !model.showConversation {
                VStack {
                    Spacer()
                    HStack(spacing: 10) {
                        Spacer()
                        Button { Haptics.glass(); model.openConversation() } label: {
                            HStack(spacing: 8) {
                                RumiMarkView(size: 30)
                                Text("Rumi").font(NudgeType.rounded(15, .semibold))
                            }
                            .foregroundStyle(Theme.ink).padding(.horizontal, 16).frame(height: 50)
                            .background(Theme.surface, in: .capsule)
                            .overlay(Capsule().strokeBorder(Theme.edge, lineWidth: 1))
                        }
                        .accessibilityLabel("Talk with Rumi").accessibilityIdentifier("rumi.floating")
                        Button { model.quickLogMedID = nil; model.showQuickLog = true } label: {
                            Label("Log", systemImage: "plus").font(NudgeType.rounded(15, .semibold))
                                .foregroundStyle(Theme.onAccent).padding(.horizontal, 18).frame(height: 50)
                                .background(Theme.buttonFill, in: .capsule)
                        }
                        .accessibilityIdentifier("log.floating")
                    }
                    .buttonStyle(NudgeButtonStyle())
                    .shadow(color: Theme.shadow.opacity(0.18), radius: 10, y: 4)
                    .padding(.horizontal, 20).padding(.bottom, 92)
                }
            }

            if !model.showConversation {
                VStack {
                    Spacer()
                    NudgeDock()
                        .padding(.bottom, 6)
                }
            }

            if model.showConversation {
                ConversationView(orbSpace: orbSpace)
                    .transition(.opacity)
            }

            if let ack = model.quickLogAck {
                VStack {
                    Spacer()
                    CompanionAckToast(text: ack)
                        .padding(.bottom, 112)
                        .transition(.move(edge: .bottom).combined(with: .opacity))
                }
                .animation(NudgeSpring.gentle, value: model.quickLogAck)
            }
        }
        .sheet(isPresented: $model.showQuickLog) {
            QuickLogView(linkedMedID: model.quickLogMedID)
                .presentationDetents([.large])
                .presentationBackground(Theme.base)
        }
        .sheet(isPresented: $model.showSettings) {
            SettingsView()
                .presentationBackground(Theme.base)
        }
        .sheet(isPresented: $model.showAgentNetwork) {
            AgentNetworkView()
                .presentationBackground(Theme.base)
        }
        .sheet(isPresented: Binding(get: { model.portal.isPresented }, set: { if !$0 { model.portal.hide() } })) {
            PortalBrowserSheet(device: model.portal) {
                model.companion.endSession(orb: model.orb)
                model.portal.cancelAll()
            }
            .presentationDetents([.large])
            .presentationBackground(Theme.base)
        }
        .fullScreenCover(isPresented: $model.showRecap) {
            RecapPlayerView()
        }
        .alert("Your latest changes aren't saved yet", isPresented: $model.storageError) {
            Button("Try again") { model.persistUserData() }
            Button("Keep working", role: .cancel) { }
        } message: { Text("Your work is still open in this session. Please try saving again before closing the app.") }
        .onChange(of: scenePhase) { _, phase in
            if phase == .background { model.companion.endSession(orb: model.orb); model.persistUserData() }
        }
        .onChange(of: model.showConversation) { _, open in
            if open {
                SoundEngine.shared.playBed(.ambient)
            }
        }
    }
}

/// Every log gets a companion response within seconds — never a mute write.
struct CompanionAckToast: View {
    @Environment(AppModel.self) private var model
    let text: String

    var body: some View {
        GlassSurface(radius: 30) {
            HStack(alignment: .top, spacing: 12) {
                OrbView(size: 34, state: model.orb)
                Text(text)
                    .font(NudgeType.rounded(14))
                    .foregroundStyle(Theme.ink)
                    .fixedSize(horizontal: false, vertical: true)
            }
            .padding(16)
        }
        .padding(.horizontal, 24)
        .onTapGesture {
            model.quickLogAck = nil
            model.openConversation(seed: "pattern")
        }
    }
}
