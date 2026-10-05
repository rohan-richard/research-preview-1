import SwiftUI

/// A short daily orientation with direct care actions and an optional companion.
struct TodayCanvasView: View {
    @Environment(AppModel.self) private var model
    var orbSpace: Namespace.ID
    @State private var showPreparedWork: Bool = false

    var body: some View {
        scroll.sheet(isPresented: $showPreparedWork) { WorkflowLibraryView() }
    }

    private var scroll: some View {
        ScrollView {
            VStack(spacing: 0) {
                header
                    .padding(.top, 6)

                VStack(spacing: 8) {
                    Text(Date.now.formatted(.dateTime.weekday(.abbreviated).month(.abbreviated).day()))
                        .font(NudgeType.rounded(12))
                        .foregroundStyle(Theme.inkMuted)
                    Text(greeting)
                        .font(NudgeType.serif(28))
                        .foregroundStyle(Theme.ink)
                        .multilineTextAlignment(.center)
                    Text("A little clarity for your day.")
                        .font(NudgeType.rounded(14))
                        .foregroundStyle(Theme.inkMuted)
                }
                .padding(.horizontal, 24)
                .padding(.top, 8)
                .padding(.bottom, 8)

                if let appointment = model.nextAppointment(after: .now) {
                    TodayVisitCard(appointment: appointment)
                        .padding(.horizontal, 20)
                        .padding(.top, 16)
                }

                // A gentle line when the care team has something new — so the
                // user always knows to look, without it ever feeling like an alarm.
                if !model.needsYou.isEmpty {
                    TodayUpdatesView()
                        .padding(.horizontal, 20)
                        .padding(.top, 16)
                        .transition(.opacity.combined(with: .move(edge: .top)))
                }

                TodayMetricsView()
                    .padding(.horizontal, 20)
                    .padding(.top, 22)

                if !model.workflows.isEmpty {
                    Button { showPreparedWork = true } label: {
                        HStack(spacing: 12) {
                            Image(systemName: "doc.text").foregroundStyle(Theme.warm)
                            VStack(alignment: .leading, spacing: 4) {
                                Text("Pick up your prepared work").font(NudgeType.rounded(15, .semibold))
                                Text("Saved drafts · nothing sent").font(NudgeType.rounded(12)).foregroundStyle(Theme.inkMuted)
                            }
                            Spacer()
                            Image(systemName: "chevron.right").font(.caption)
                        }.padding(17).foregroundStyle(Theme.ink).background(Theme.surface, in: .rect(cornerRadius: 22))
                    }.padding(.horizontal, 20).padding(.top, 18)
                }

                // The Thread — the companion's chosen moments for right now.
                VStack(spacing: 13) {
                    if !model.moments.isEmpty {
                        ForEach(model.moments.prefix(3)) { moment in
                            MomentCard(moment: moment)
                        }
                    }
                }
                .padding(.horizontal, 20)
                .padding(.top, 16)

                if !todayEntries.isEmpty {
                    lifeStrip.padding(.top, 22)
                }


                // Generous tail so the last row always clears the floating dock
                // and the whole page scrolls freely from anywhere on screen.
                Color.clear.frame(height: 150)
            }
        }
        .scrollIndicators(.hidden)
        .scrollBounceBehavior(.always)

    }

    // MARK: Header — settings · condition, one glass voice

    private var header: some View {
        HStack(spacing: 10) {
            Text("Rumi")
                .font(NudgeType.display(29))
                .foregroundStyle(Theme.ink)
            if !model.isLive {
                Text("DEMO")
                    .font(NudgeType.rounded(10, .semibold))
                    .tracking(1)
                    .foregroundStyle(Theme.warm)
                    .padding(.horizontal, 8)
                    .padding(.vertical, 5)
                    .background(Theme.accentSoft, in: .capsule)
            }
            Spacer()
            if model.musicOn {
                ChromeIcon(systemName: "speaker.wave.2", accessibilityText: "Mute music") {
                    model.musicOn = false
                }
            }
            ChromeIcon(systemName: "person.crop.circle", accessibilityText: "Account and settings") {
                model.showSettings = true
            }
            .accessibilityIdentifier("today.settings")
        }
        .padding(.horizontal, 20)
    }

    // MARK: The '+' — impossible to miss, beautiful to press

    private var plusButton: some View {
        Button {
            Haptics.pull()
            SoundEngine.shared.glass()
            model.quickLogMedID = nil
            model.showQuickLog = true
        } label: {
            Label("Log", systemImage: "plus")
                .font(NudgeType.rounded(15, .semibold))
                .foregroundStyle(Theme.onAccent)
                .padding(.horizontal, 20)
                .frame(height: 50)
                .background(Theme.buttonFill, in: .capsule)
                .shadow(color: Theme.shadow.opacity(0.18), radius: 10, y: 4)
        }
        .buttonStyle(NudgeButtonStyle())
        .accessibilityLabel("Log something — a symptom, a meal, a move, a med")
        .padding(.trailing, 22)
        .padding(.bottom, 96)
    }

    // MARK: Life strip — today's meals, moves and meds as floating objects

    private var lifeStrip: some View {
        VStack(alignment: .leading, spacing: 10) {
            Button {
                openLife()
            } label: {
                HStack {
                    Text("Your day, logged")
                        .font(NudgeType.serif(19))
                        .foregroundStyle(Theme.ink)
                    Spacer()
                    HStack(spacing: 4) {
                        Text("See it all")
                            .font(NudgeType.rounded(12, .semibold))
                        Image(systemName: "chevron.right")
                            .font(.system(size: 9, weight: .semibold))
                    }
                    .foregroundStyle(Theme.warm)
                }
                .contentShape(Rectangle())
            }
            .buttonStyle(NudgeButtonStyle())
            .padding(.horizontal, 22)

            ScrollView(.horizontal) {
                HStack(spacing: 14) {
                    ForEach(todayEntries.prefix(6)) { entry in
                        Button { openLife() } label: {
                            LifeThumb(entry: entry)
                        }
                        .buttonStyle(NudgeButtonStyle())
                    }
                }
            }
            .scrollIndicators(.hidden)
            .contentMargins(.horizontal, 20)
        }
    }

    private func openLife() {
        Haptics.glass()
        SoundEngine.shared.glass()
        model.openYou(.life)
    }

    // MARK: Care-team alert — a calm nudge toward the Care hub

    private var careAlertBanner: some View {
        Button {
            Haptics.glass()
            SoundEngine.shared.glass()
            withAnimation(NudgeSpring.ui) { model.tab = .care }
        } label: {
            HStack(spacing: 12) {
                ZStack {
                    Image(systemName: "cross.case")
                        .font(.system(size: 15, weight: .light))
                        .foregroundStyle(Theme.sky)
                        .frame(width: 38, height: 38)
                        .background(Theme.sky.opacity(0.14), in: .circle)
                    Circle()
                        .fill(Theme.warm)
                        .frame(width: 9, height: 9)
                        .overlay(Circle().strokeBorder(Theme.surface, lineWidth: 1.5))
                        .offset(x: 14, y: -14)
                }
                VStack(alignment: .leading, spacing: 1) {
                    Text(careAlertTitle)
                        .font(NudgeType.serif(16))
                        .foregroundStyle(Theme.ink)
                    Text("Tap to open your Care hub")
                        .font(NudgeType.rounded(12))
                        .foregroundStyle(Theme.inkMuted)
                }
                Spacer()
                Image(systemName: "chevron.right")
                    .font(.system(size: 11, weight: .light))
                    .foregroundStyle(Theme.inkMuted)
            }
            .padding(14)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Theme.surface.opacity(0.95), in: .rect(cornerRadius: 26, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: 26, style: .continuous)
                    .strokeBorder(Theme.sky.opacity(0.3), lineWidth: 0.9)
            )
        }
        .buttonStyle(NudgeButtonStyle())
        .accessibilityLabel("\(careAlertTitle). Opens your Care hub.")
    }

    private var careAlertTitle: String {
        let count = model.careUnreadCount
        if model.threads.contains(where: { $0.unread }) {
            return count > 1 ? "\(count) updates from your care team" : "A new message from your care team"
        }
        return "A new result is ready"
    }

    private var todayEntries: [CareEntry] {
        model.entries.filter { Calendar.current.isDateInToday($0.at) }
    }

    private var greeting: String {
        let hour = Calendar.current.component(.hour, from: .now)
        let name = model.displayFirstName
        switch hour {
        case 5..<12: return "Morning, \(name)."
        case 12..<17: return "Afternoon, \(name)."
        default: return "Evening, \(name)."
        }
    }

}

/// A small studio-photo tile for the Today life strip.
struct LifeThumb: View {
    let entry: CareEntry

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Color(.secondarySystemBackground)
                .frame(width: 92, height: 92)
                .overlay {
                    Image(entry.imageName)
                        .resizable()
                        .aspectRatio(contentMode: .fill)
                        .allowsHitTesting(false)
                }
                .clipShape(.rect(cornerRadius: 22))
                .overlay(
                    RoundedRectangle(cornerRadius: 22, style: .continuous)
                        .strokeBorder(Color.white.opacity(0.5), lineWidth: 0.8)
                )
                .shadow(color: Theme.shadow.opacity(0.14), radius: 10, y: 4)

            Text(entry.title)
                .font(NudgeType.rounded(11.5, .medium))
                .foregroundStyle(Theme.ink)
                .lineLimit(1)
            Text(entry.at.formatted(date: .omitted, time: .shortened))
                .font(NudgeType.number(10, .medium))
                .foregroundStyle(Theme.inkMuted)
        }
        .frame(width: 92)
    }
}

/// The companion proposing a real step — approve or wave it off, one tap each.
struct AgentActionCard: View {
    @Environment(AppModel.self) private var model
    let action: AgentAction
    @State private var review: ReviewedWorkflow? = nil

    var body: some View {
        OrganicSurface(radius: 22) {
            VStack(alignment: .leading, spacing: 10) {
                HStack(spacing: 9) {
                    Image(systemName: action.glyph)
                        .font(.system(size: 14, weight: .light))
                        .foregroundStyle(Theme.gold)
                        .frame(width: 32, height: 32)
                        .background(Theme.gold.opacity(0.14), in: .circle)
                    VStack(alignment: .leading, spacing: 1) {
                        Kicker(text: "Demonstration task idea", color: Theme.gold)
                        Text(action.title)
                            .font(NudgeType.serif(17))
                            .foregroundStyle(Theme.ink)
                    }
                }
                Text(action.detail)
                    .font(NudgeType.rounded(13))
                    .foregroundStyle(Theme.inkMuted)
                    .fixedSize(horizontal: false, vertical: true)

                HStack(spacing: 10) {
                    Button {
                        review = model.workflowForAction(action.id)
                    } label: {
                        Text("Review task idea")
                            .font(NudgeType.rounded(13.5, .semibold))
                            .foregroundStyle(Theme.base)
                            .padding(.horizontal, 16)
                            .padding(.vertical, 9)
                            .background(Theme.ink, in: .capsule)
                    }
                    .buttonStyle(NudgeButtonStyle())

                    Button {
                        model.declineAction(action.id)
                    } label: {
                        // Plain chip — this card rides shader sweeps, and glass
                        // must never sit under a layer effect.
                        Text("Not now")
                            .font(NudgeType.rounded(13.5, .medium))
                            .foregroundStyle(Theme.ink)
                            .padding(.horizontal, 16)
                            .padding(.vertical, 9)
                            .background(Theme.raised.opacity(0.9), in: .capsule)
                            .overlay(Capsule().strokeBorder(Theme.edge.opacity(0.7), lineWidth: 0.8))
                    }
                    .buttonStyle(NudgeButtonStyle())

                    Spacer()

                    if action.leavesDevice {
                        HStack(spacing: 4) {
                            Image(systemName: "hand.raised")
                                .font(.system(size: 9, weight: .medium))
                            Text("Nothing will be sent")
                                .font(NudgeType.rounded(10, .medium))
                        }
                        .foregroundStyle(Theme.inkMuted.opacity(0.8))
                    }
                }
            }
            .padding(17)
        }
        .sheet(item: $review) { value in
            WorkflowReviewView(originID: value.originID, title: value.title, detail: value.detail, context: value.context)
        }
    }
}

extension Notification.Name {
    /// Asks the You tab to open the conditions overview.
    static let nudgeOpenConditions = Notification.Name("nudgeOpenConditions")
    /// Asks the You tab to open the Life Catalog (meals, moves, meds).
    static let nudgeOpenLife = Notification.Name("nudgeOpenLife")
}
