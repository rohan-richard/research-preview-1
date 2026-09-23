import SwiftUI

/// One moment on the Thread — one organic surface, one clear action.
/// Swipe to dismiss: it melts away, never to guilt-reappear. Each moment
/// carries a studio image or a soft gradient tile — never a pixel jumble.
struct MomentCard: View {
    @Environment(AppModel.self) private var model
    let moment: Moment

    @State private var dragX: CGFloat = 0
    @State private var meltProgress: Double = 0
    @State private var actionFired = false

    var body: some View {
        OrganicSurface(radius: 22) {
            HStack(alignment: .top, spacing: 14) {
                thumb

                VStack(alignment: .leading, spacing: 5) {
                    Text(moment.title)
                        .font(NudgeType.rounded(15, .semibold))
                        .foregroundStyle(Theme.ink)
                    Text(moment.body)
                        .font(NudgeType.rounded(13.5))
                        .foregroundStyle(Theme.inkMuted)
                        .fixedSize(horizontal: false, vertical: true)

                    Button(action: act) {
                        // Plain chip — this card melts through a Metal shader,
                        // and glass must never sit under a layer effect.
                        Text(moment.actionLabel)
                            .font(NudgeType.rounded(13, .semibold))
                            .foregroundStyle(Theme.ink)
                            .padding(.horizontal, 15)
                            .frame(minHeight: 44)
                            .background(Theme.raised.opacity(0.9), in: .capsule)
                            .overlay(Capsule().strokeBorder(Theme.edge.opacity(0.7), lineWidth: 0.8))
                    }
                    .buttonStyle(NudgeButtonStyle())
                    .padding(.top, 6)
                }
                Spacer(minLength: 0)
            }
            .padding(16)
        }
        .rippleOnTap(glow: 0.4)
        .melt(meltProgress)
        .offset(x: dragX)
        .opacity(1 - min(Double(abs(dragX)) / 320, 0.5))
        .gesture(
            DragGesture()
                .onChanged { value in
                    guard abs(value.translation.width) > abs(value.translation.height) else { return }
                    dragX = value.translation.width
                }
                .onEnded { value in
                    if abs(value.translation.width) > 96 {
                        dismiss()
                    } else {
                        withAnimation(NudgeSpring.ui) { dragX = 0 }
                    }
                }
        )
        .sensoryFeedback(.success, trigger: actionFired)
        .accessibilityElement(children: .combine)
        .accessibilityHint("Swipe left or right to set this aside")
    }

    /// A real image when the moment is about a real thing; otherwise a
    /// smooth gradient tile with the glyph — never noise.
    @ViewBuilder
    private var thumb: some View {
        if let imageName, UIImage(named: imageName) != nil {
            Color(.secondarySystemBackground)
                .frame(width: 56, height: 56)
                .overlay {
                    Image(imageName)
                        .resizable()
                        .aspectRatio(contentMode: .fill)
                        .allowsHitTesting(false)
                }
                .clipShape(.rect(cornerRadius: 16))
                .overlay(
                    RoundedRectangle(cornerRadius: 16, style: .continuous)
                        .strokeBorder(Color.white.opacity(0.55), lineWidth: 0.8)
                )
        } else {
            RoundedRectangle(cornerRadius: 16, style: .continuous)
                .fill(
                    LinearGradient(
                        colors: [accent.opacity(0.32), accent.opacity(0.1)],
                        startPoint: .topLeading, endPoint: .bottomTrailing
                    )
                )
                .frame(width: 56, height: 56)
                .overlay(
                    Image(systemName: moment.glyph)
                        .font(.system(size: 19, weight: .light))
                        .foregroundStyle(accent)
                )
        }
    }

    private var imageName: String? {
        switch moment.kind {
        case .task:
            if let medID = moment.medID ?? model.medications.first?.id, moment.title.lowercased().contains("refill") || moment.kind == .task {
                return LifeLibrary.medImage(for: medID)
            }
            return nil
        case .habit:
            return "terracotta_cream_sneakers"
        case .insight, .checkIn:
            return nil
        }
    }

    private var accent: Color {
        switch moment.kind {
        case .insight: return Theme.sky
        case .habit: return Theme.life
        case .task: return Theme.gold
        case .checkIn: return Theme.warm
        }
    }

    private func act() {
        actionFired.toggle()
        switch moment.kind {
        case .insight:
            model.youPath = NavigationPath()
            model.youSection = .insights
            model.tab = .you
            if let id = moment.insightID { model.markInsightSeen(id) }
            dismissQuietly()
        case .habit:
            model.openYou(.journeys)
            dismissQuietly()
        case .task:
            if let id = moment.medID, let medication = model.medications.first(where: { $0.id == id }) {
                model.openConversation(context: model.context(for: medication))
                dismissQuietly()
            } else { model.openCare(.medications) }
        case .checkIn:
            model.openConversation()
            dismissQuietly()
        }
    }

    private func dismiss() {
        withAnimation(NudgeSpring.gentle) { meltProgress = 1.05 }
        Task {
            try? await Task.sleep(for: .milliseconds(480))
            model.dismissMoment(moment.id)
        }
    }

    private func dismissQuietly() {
        Task {
            try? await Task.sleep(for: .milliseconds(350))
            model.dismissMoment(moment.id)
        }
    }
}
