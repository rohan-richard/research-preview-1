import SwiftUI

/// Short, reversible setup. Sign-in is optional here. The demo works without an account.
struct OnboardingFlowView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    var isPreview: Bool = false

    enum Stage: Int, CaseIterable {
        case welcome, scenario, records, preferences
    }

    @State private var stage: Stage = .welcome
    @State private var selectedPathway: CarePathway = .metabolic
    @State private var tone: String = "Straight talk"
    @State private var music: Bool = false
    @State private var showSignIn: Bool = false
    @State private var showConnection: Bool = false
    @State private var pendingImport: DemoRecordImport? = nil

    var body: some View {
        ZStack {
            LivingGradientView()
            VStack(spacing: 0) {
                navigation
                ScrollView {
                    VStack(alignment: .leading, spacing: 24) {
                        switch stage {
                        case .welcome: welcome
                        case .scenario: scenarios
                        case .records: records
                        case .preferences: preferences
                        }
                    }
                    .padding(.horizontal, 24)
                    .padding(.top, 22)
                    .padding(.bottom, 24)
                    .frame(maxWidth: 540)
                    .frame(maxWidth: .infinity)
                }
                .scrollIndicators(.hidden)
                .scrollBounceBehavior(.basedOnSize)
                footer
            }
        }
        .onAppear {
            selectedPathway = model.pathway
            tone = model.tonePreference
            music = model.musicOn
        }
        .sheet(isPresented: $showConnection) {
            FastenConnectionView(pathway: selectedPathway) { pendingImport = $0 }
        }
        .sheet(isPresented: $showSignIn) {
            SignInView().presentationBackground(Theme.base)
        }
    }

    private var navigation: some View {
        HStack {
            if stage != .welcome {
                Button {
                    move(to: Stage(rawValue: stage.rawValue - 1) ?? .welcome)
                } label: {
                    Image(systemName: "chevron.left")
                        .font(.system(size: 18, weight: .medium))
                        .frame(width: 44, height: 44)
                }
                .accessibilityLabel("Back")
                .accessibilityIdentifier("onboarding.back")
            } else {
                Text("Rumi")
                    .font(NudgeType.display(32))
                    .frame(minHeight: 44)
            }
            Spacer()
            if isPreview {
                Button { dismiss() } label: {
                    Image(systemName: "xmark")
                        .font(.system(size: 16))
                        .frame(width: 44, height: 44)
                }
                .accessibilityLabel("Close welcome preview")
                .accessibilityIdentifier("onboarding.close")
            } else {
                Text("\(stage.rawValue + 1) of 4")
                    .font(NudgeType.rounded(12, .medium))
                    .foregroundStyle(Theme.inkMuted)
            }
        }
        .foregroundStyle(Theme.ink)
        .padding(.horizontal, 24)
        .padding(.top, 8)
        .overlay(alignment: .bottom) {
            if stage != .welcome {
                GeometryReader { proxy in
                    Capsule()
                        .fill(Theme.gold)
                        .frame(width: proxy.size.width * CGFloat(stage.rawValue + 1) / 4, height: 2)
                }
                .frame(height: 2)
                .padding(.horizontal, 24)
                .offset(y: 8)
                .accessibilityHidden(true)
            }
        }
    }

    private var welcome: some View {
        VStack(spacing: 22) {
            RumiMarkView(size: 136, animated: true)
                .padding(.top, 8)
            VStack(spacing: 12) {
                Text("A little less to carry.")
                    .font(NudgeType.serif(34))
                    .foregroundStyle(Theme.ink)
                    .accessibilityIdentifier("onboarding.welcomeTitle")
                Text("Your care, your next steps,\nand the life in between.")
                    .font(NudgeType.rounded(17))
                    .foregroundStyle(Theme.inkMuted)
                    .lineSpacing(4)
            }
            .multilineTextAlignment(.center)
            .fixedSize(horizontal: false, vertical: true)

            OrganicSurface(radius: 22) {
                VStack(spacing: 0) {
                    introductionRow("calendar", title: "Know what's next", detail: "Visits, questions and care plans")
                    Divider().overlay(Theme.edge).padding(.leading, 54)
                    introductionRow("heart.text.square", title: "See the bigger picture", detail: "Records, medications and daily logs")
                    Divider().overlay(Theme.edge).padding(.leading, 54)
                    introductionRow("bubble.left", title: "Help when you want it", detail: "A companion, not a required conversation")
                }
                .padding(.horizontal, 16)
                .padding(.vertical, 4)
            }
        }
        .frame(maxWidth: .infinity)
    }

    private var scenarios: some View {
        VStack(alignment: .leading, spacing: 22) {
            heading("Take a look around.", detail: "Choose a sample story to explore. You can try the others later in Settings.")
            VStack(spacing: 10) {
                ForEach(CarePathway.allCases) { pathway in
                    scenarioRow(pathway)
                }
            }
            Label("Sample people and records. Not your medical information.", systemImage: "info.circle")
                .font(NudgeType.rounded(13))
                .foregroundStyle(Theme.inkMuted)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    private func scenarioRow(_ pathway: CarePathway) -> some View {
        let selected = selectedPathway == pathway
        return Button {
            Haptics.tick()
            if selectedPathway != pathway { pendingImport = nil }
            selectedPathway = pathway
        } label: {
            HStack(spacing: 14) {
                Image(systemName: pathway.glyph)
                    .font(.system(size: 20, weight: .regular))
                    .foregroundStyle(Theme.warm)
                    .frame(width: 44, height: 44)
                    .background(Theme.accentSoft, in: .circle)
                VStack(alignment: .leading, spacing: 5) {
                    Text(scenarioTitle(pathway))
                        .font(NudgeType.rounded(16, .semibold))
                        .foregroundStyle(Theme.ink)
                    Text(scenarioDetail(pathway))
                        .font(NudgeType.rounded(13))
                        .foregroundStyle(Theme.inkMuted)
                }
                .fixedSize(horizontal: false, vertical: true)
                Spacer(minLength: 0)
                Image(systemName: selected ? "checkmark.circle.fill" : "circle")
                    .font(.system(size: 22, weight: .light))
                    .foregroundStyle(selected ? Theme.warm : Theme.edge)
            }
            .padding(16)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(selected ? Theme.raised : Theme.surface, in: .rect(cornerRadius: 20))
            .overlay(RoundedRectangle(cornerRadius: 20).strokeBorder(selected ? Theme.gold : Theme.edge, lineWidth: selected ? 1.3 : 0.7))
            .contentShape(.rect(cornerRadius: 20))
        }
        .buttonStyle(NudgeButtonStyle())
        .accessibilityAddTraits(selected ? .isSelected : [])
        .accessibilityIdentifier("onboarding.scenario.\(pathway.rawValue)")
    }

    private var records: some View {
        VStack(alignment: .leading, spacing: 22) {
            heading("Your records, together.", detail: "See how Fasten can bring authorized health information into one place. Connecting is optional.")
            OrganicSurface {
                VStack(alignment: .leading, spacing: 16) {
                    Label("Fasten Connect", systemImage: "link").font(NudgeType.serif(22))
                    Text(pendingImport == nil ? "Confirm a prefilled sample profile, choose what to share, and see an import arrive." : "\(pendingImport?.items.count ?? 0) sample items ready to keep when you finish setup.")
                        .font(NudgeType.rounded(15)).foregroundStyle(Theme.inkMuted)
                    Button(pendingImport == nil ? "Try the connection" : "Review connection again") { showConnection = true }
                        .buttonStyle(.borderedProminent).tint(Theme.buttonFill).controlSize(.large)
                        .accessibilityIdentifier("onboarding.connectRecords")
                    Text("Demonstration only. Real imports need authorized Fasten access, provider sign-in or identity verification, and your consent.")
                        .font(NudgeType.rounded(12)).foregroundStyle(Theme.inkMuted)
                }.padding(20)
            }
            Text("You can revisit this in Care → Records & results.").font(NudgeType.rounded(14)).foregroundStyle(Theme.inkMuted)
        }
    }

    private var preferences: some View {
        VStack(alignment: .leading, spacing: 24) {
            heading("Make room for you.", detail: "Two small preferences. Everything here is optional and can change in Settings.")
            OrganicSurface(radius: 22) {
                VStack(alignment: .leading, spacing: 16) {
                    Text("Companion tone")
                        .font(NudgeType.rounded(16, .semibold))
                    Picker("Companion tone", selection: $tone) {
                        Text("Straight talk").tag("Straight talk")
                        Text("Gentle nudges").tag("Gentle nudges")
                    }
                    .pickerStyle(.segmented)
                    Text("Chat is there when you need it. Your care is always available without it.")
                        .font(NudgeType.rounded(14))
                        .foregroundStyle(Theme.inkMuted)
                        .fixedSize(horizontal: false, vertical: true)
                }
                .foregroundStyle(Theme.ink)
                .padding(20)
            }
            OrganicSurface(radius: 22) {
                Toggle(isOn: $music) {
                    VStack(alignment: .leading, spacing: 5) {
                        Text("Background music")
                            .font(NudgeType.rounded(16, .semibold))
                        Text("A quiet soundtrack, if you'd like.")
                            .font(NudgeType.rounded(13))
                            .foregroundStyle(Theme.inkMuted)
                    }
                }
                .tint(Theme.warm)
                .foregroundStyle(Theme.ink)
                .padding(20)
            }
            Label("Record connections and permissions can wait. This demo uses sample data.", systemImage: "link")
                .font(NudgeType.rounded(13))
                .foregroundStyle(Theme.inkMuted)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    private var footer: some View {
        VStack(spacing: 8) {
            Button {
                switch stage {
                case .welcome: move(to: .scenario)
                case .scenario: move(to: .records)
                case .records: move(to: .preferences)
                case .preferences: finish(applyPreferences: true)
                }
            } label: {
                HStack(spacing: 10) {
                    Text(primaryTitle)
                    Image(systemName: "arrow.right").font(.system(size: 14, weight: .semibold))
                }
                .font(NudgeType.rounded(16, .semibold))
                .foregroundStyle(Theme.onAccent)
                .frame(maxWidth: .infinity, minHeight: 54)
                .background(Theme.buttonFill, in: .rect(cornerRadius: 16))
            }
            .buttonStyle(NudgeButtonStyle())
            .accessibilityIdentifier("onboarding.continue")
            if stage == .welcome {
                if let user = model.api.user {
                    Button("Signed in as \(user.email)") { showSignIn = true }
                        .accessibilityIdentifier("onboarding.signedInAs")
                        .font(NudgeType.rounded(14, .medium))
                        .frame(minHeight: 44)
                } else {
                    Button("Sign in") { showSignIn = true }
                        .accessibilityIdentifier("onboarding.signIn")
                        .font(NudgeType.rounded(14, .semibold))
                        .frame(minHeight: 44)
                }
            } else if stage == .preferences {
                Button("Skip for now") { finish(applyPreferences: false) }
                    .accessibilityIdentifier("onboarding.skip")
                    .font(NudgeType.rounded(14, .medium))
                    .frame(minHeight: 44)
            }
        }
        .foregroundStyle(Theme.warm)
        .padding(.horizontal, 24)
        .padding(.top, 14)
        .padding(.bottom, 12)
        .frame(maxWidth: 540)
        .frame(maxWidth: .infinity)
        .background(Theme.base.opacity(0.97))
    }

    private var primaryTitle: String {
        switch stage {
        case .welcome: return "Get started"
        case .scenario: return "Continue"
        case .records: return pendingImport == nil ? "Continue without connecting" : "Continue"
        case .preferences: return isPreview ? "Done" : "Open Today"
        }
    }

    private func heading(_ title: String, detail: String) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(title).font(NudgeType.serif(32)).foregroundStyle(Theme.ink)
            Text(detail).font(NudgeType.rounded(16)).foregroundStyle(Theme.inkMuted).lineSpacing(3)
        }
        .fixedSize(horizontal: false, vertical: true)
    }

    private func introductionRow(_ glyph: String, title: String, detail: String) -> some View {
        HStack(spacing: 14) {
            Image(systemName: glyph)
                .font(.system(size: 20, weight: .regular))
                .foregroundStyle(Theme.warm)
                .frame(width: 36)
            VStack(alignment: .leading, spacing: 4) {
                Text(title).font(NudgeType.rounded(15, .semibold)).foregroundStyle(Theme.ink)
                Text(detail).font(NudgeType.rounded(12.5)).foregroundStyle(Theme.inkMuted)
            }
            .fixedSize(horizontal: false, vertical: true)
            Spacer(minLength: 0)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.vertical, 16)
    }

    private func move(to next: Stage) {
        Haptics.tick()
        withAnimation(reduceMotion ? nil : .easeInOut(duration: 0.2)) { stage = next }
    }

    private func finish(applyPreferences: Bool) {
        guard !isPreview else { dismiss(); return }
        model.switchPathway(selectedPathway)
        guard model.pathway == selectedPathway else { return }
        if let pendingImport { model.demoRecordImport = pendingImport }
        if applyPreferences { model.musicOn = music }
        model.completeOnboarding(values: "", barrier: "", tone: applyPreferences ? tone : model.tonePreference)
        model.persistUserData()
        if model.musicOn { SoundEngine.shared.playBed(.ambient, fade: 2) }
        Haptics.success()
    }

    private func scenarioTitle(_ pathway: CarePathway) -> String {
        switch pathway {
        case .metabolic: return "Everyday care"
        case .oncology: return "Through treatment"
        case .procedure: return "Preparing for a procedure"
        case .cardiometabolic: return "Bringing care together"
        }
    }

    private func scenarioDetail(_ pathway: CarePathway) -> String {
        switch pathway {
        case .metabolic: return "Marcus · diabetes and daily habits"
        case .oncology: return "Elena · support between visits"
        case .procedure: return "Sam · preparation and recovery"
        case .cardiometabolic: return "Rosa · heart, kidney and diabetes care"
        }
    }
}
