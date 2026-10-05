import SwiftUI

/// Care plan — the plan from the care team, in plain words, mapped against real
/// life. Each goal can become a tiny journey (opt-in, user-confirmed, §4.4.5).
/// The derivation is behavioral; it never restates a medical instruction the
/// physician didn't give (ACT-2).
struct CarePlanView: View {
    @Environment(AppModel.self) private var model

    private var plan: CarePlan { model.shownCarePlan }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                VStack(alignment: .leading, spacing: 6) {
                    Text("Care plan")
                        .font(NudgeType.serif(28))
                        .foregroundStyle(Theme.ink)
                    Text("From \(plan.author) · updated \(plan.updated)")
                        .font(NudgeType.rounded(12.5, .medium))
                        .foregroundStyle(Theme.inkMuted)
                }
                .padding(.top, 8)

                OrganicSurface(radius: 28) {
                    Text(plan.intro)
                        .font(NudgeType.rounded(14))
                        .foregroundStyle(Theme.ink.opacity(0.9))
                        .lineSpacing(3)
                        .fixedSize(horizontal: false, vertical: true)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(17)
                }

                Text("Your goals")
                    .font(NudgeType.serif(20))
                    .foregroundStyle(Theme.ink)
                    .padding(.top, 2)

                ForEach(plan.goals) { goal in
                    goalCard(goal)
                }

                ProvenanceChip(text: "From your visit notes — turning a goal into a habit is always your choice")
                    .padding(.top, 2)
            }
            .padding(.horizontal, 20)
            .padding(.bottom, 120)
        }
        .scrollIndicators(.hidden)
    }

    private func goalCard(_ goal: CarePlanGoal) -> some View {
        let accent = color(goal.accent)
        let derived = model.hasDerivedJourney(for: goal.title)
        return OrganicSurface(radius: 28) {
            VStack(alignment: .leading, spacing: 9) {
                HStack(spacing: 9) {
                    Circle()
                        .fill(accent)
                        .frame(width: 8, height: 8)
                        .shadow(color: accent.opacity(0.7), radius: 4)
                    Text(goal.title)
                        .font(NudgeType.serif(17.5))
                        .foregroundStyle(Theme.ink)
                        .fixedSize(horizontal: false, vertical: true)
                    Spacer(minLength: 0)
                }
                Text(goal.detail)
                    .font(NudgeType.rounded(13.5))
                    .foregroundStyle(Theme.inkMuted)
                    .lineSpacing(2)
                    .fixedSize(horizontal: false, vertical: true)
                if let progress = goal.progressLine {
                    Label(progress, systemImage: "chart.line.uptrend.xyaxis")
                        .font(NudgeType.rounded(12.5, .medium))
                        .foregroundStyle(accent)
                }

                Divider().overlay(Theme.edge.opacity(0.5)).padding(.vertical, 2)

                if derived {
                    Label("Following along in Journeys", systemImage: "checkmark.seal.fill")
                        .font(NudgeType.rounded(13, .semibold))
                        .foregroundStyle(Theme.life)
                } else {
                    Button {
                        model.deriveJourney(from: goal)
                    } label: {
                        HStack(spacing: 7) {
                            Image(systemName: "leaf.fill").font(.system(size: 12, weight: .semibold))
                            Text("Make it a tiny journey").font(NudgeType.rounded(13.5, .semibold))
                        }
                        .foregroundStyle(Theme.base)
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 11)
                        .background(accent, in: .capsule)
                    }
                    .buttonStyle(NudgeButtonStyle())
                }

                if let provenance = goal.provenance {
                    Text(provenance)
                        .font(NudgeType.rounded(11))
                        .foregroundStyle(Theme.inkMuted)
                }
            }
            .padding(16)
        }
    }

    private func color(_ key: AccentKey) -> Color {
        switch key {
        case .warm: return Theme.warm
        case .life: return Theme.life
        case .sky: return Theme.sky
        case .gold: return Theme.gold
        case .rose: return Theme.rose
        }
    }
}
