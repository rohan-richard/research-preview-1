import SwiftUI

/// The full picture, in one calm place: what you're carrying, where you are in
/// it, the plan from your care team, and what to expect next. Personal without
/// ever feeling like a chart.
struct ConditionOverviewView: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                hero

                if !model.isLive, let phase = model.persona.phase {
                    phaseCard(phase)
                }

                Text("What you're carrying")
                    .font(NudgeType.serif(21))
                    .foregroundStyle(Theme.ink)
                    .padding(.top, 4)

                ForEach(model.shownConditions) { condition in
                    conditionCard(condition)
                }

                carePlanCard

                // The expectations are written for each sample patient; real records carry no such guidance.
                if !model.isLive {
                    Text("What to expect")
                        .font(NudgeType.serif(21))
                        .foregroundStyle(Theme.ink)
                        .padding(.top, 4)

                    ForEach(model.persona.expectations) { item in
                        expectationCard(item)
                    }
                }

                clinicalDataLinks
            }
            .padding(.horizontal, 20)
            .padding(.bottom, 120)
        }
        .scrollIndicators(.hidden)
    }

    // MARK: Hero — the condition's emotional ground, not a diagnosis banner

    private var hero: some View {
        Color.clear
            .frame(height: 190)
            .overlay {
                if UIImage(named: model.persona.heroImage) != nil {
                    Image(model.persona.heroImage)
                        .resizable()
                        .aspectRatio(contentMode: .fill)
                        .allowsHitTesting(false)
                } else {
                    SceneVisual(seed: 41, height: 190)
                }
            }
            .clipShape(.rect(cornerRadius: 36, style: .continuous))
            .overlay(alignment: .bottomLeading) {
                VStack(alignment: .leading, spacing: 3) {
                    Text("Your picture")
                        .font(NudgeType.kicker())
                        .tracking(1.6)
                        .foregroundStyle(.white.opacity(0.85))
                    Text(model.shownConditionChip)
                        .font(NudgeType.serif(23))
                        .foregroundStyle(.white)
                }
                .padding(18)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(
                    LinearGradient(colors: [.black.opacity(0.45), .clear], startPoint: .bottom, endPoint: .top)
                )
            }
            .clipShape(.rect(cornerRadius: 36, style: .continuous))
            .padding(.top, 8)

    }

    // MARK: Phase — where you are in the arc

    private func phaseCard(_ phase: CarePhase) -> some View {
        OrganicSurface(radius: 32) {
            VStack(alignment: .leading, spacing: 10) {
                Kicker(text: phase.kicker, color: Theme.rose)
                Text(phase.headline)
                    .font(NudgeType.serif(20))
                    .foregroundStyle(Theme.ink)
                Text(phase.detail)
                    .font(NudgeType.rounded(13.5))
                    .foregroundStyle(Theme.inkMuted)
                    .lineSpacing(3)
                    .fixedSize(horizontal: false, vertical: true)

                if let progress = phase.progress {
                    GeometryReader { geo in
                        ZStack(alignment: .leading) {
                            Capsule()
                                .fill(Theme.base.opacity(0.8))
                            Capsule()
                                .fill(
                                    LinearGradient(colors: [Theme.rose, Theme.gold],
                                                   startPoint: .leading, endPoint: .trailing)
                                )
                                .frame(width: max(12, geo.size.width * progress))
                                .shadow(color: Theme.gold.opacity(0.5), radius: 8)
                        }
                    }
                    .frame(height: 10)
                    .padding(.top, 4)
                }
            }
            .padding(18)
        }
    }

    private func conditionCard(_ condition: CareCondition) -> some View {
        let accent = color(condition.accent)
        return OrganicSurface(radius: 30) {
            VStack(alignment: .leading, spacing: 8) {
                HStack(spacing: 12) {
                    Image(systemName: condition.glyph)
                        .font(.system(size: 15, weight: .light))
                        .foregroundStyle(accent)
                        .frame(width: 36, height: 36)
                        .background(accent.opacity(0.13), in: .circle)
                    VStack(alignment: .leading, spacing: 2) {
                        Text(condition.name)
                            .font(NudgeType.serif(17.5))
                            .foregroundStyle(Theme.ink)
                        Text("Since \(condition.since) · \(condition.state)")
                            .font(NudgeType.rounded(12))
                            .foregroundStyle(Theme.inkMuted)
                    }
                    Spacer()
                }
                Text(condition.plainLine)
                    .font(NudgeType.rounded(13.5))
                    .foregroundStyle(Theme.ink.opacity(0.85))
                    .lineSpacing(3)
                    .fixedSize(horizontal: false, vertical: true)
            }
            .padding(16)
        }
    }

    // MARK: The plan from the care team

    private var carePlanCard: some View {
        let plan = model.shownCarePlan
        return OrganicSurface(radius: 32) {
            VStack(alignment: .leading, spacing: 12) {
                Kicker(text: "The plan from \(plan.author)", color: Theme.sky)
                Text(plan.intro)
                    .font(NudgeType.rounded(13.5))
                    .foregroundStyle(Theme.inkMuted)
                    .lineSpacing(3)
                    .fixedSize(horizontal: false, vertical: true)

                ForEach(plan.goals) { goal in
                    let accent = color(goal.accent)
                    VStack(alignment: .leading, spacing: 4) {
                        HStack(spacing: 8) {
                            Circle()
                                .fill(accent)
                                .frame(width: 7, height: 7)
                                .shadow(color: accent.opacity(0.7), radius: 4)
                            Text(goal.title)
                                .font(NudgeType.rounded(14.5, .semibold))
                                .foregroundStyle(Theme.ink)
                        }
                        Text(goal.detail)
                            .font(NudgeType.rounded(12.5))
                            .foregroundStyle(Theme.inkMuted)
                            .padding(.leading, 15)
                        if let progress = goal.progressLine {
                            Text(progress)
                                .font(NudgeType.rounded(12, .medium))
                                .foregroundStyle(accent)
                                .padding(.leading, 15)
                        }
                    }
                    .padding(.vertical, 3)
                }

                ProvenanceChip(text: "Updated \(plan.updated) · from your visit notes")
            }
            .padding(18)
        }
    }

    private func expectationCard(_ item: ExpectationItem) -> some View {
        let accent = color(item.accent)
        return OrganicSurface(radius: 28) {
            HStack(alignment: .top, spacing: 13) {
                Text(item.window)
                    .font(NudgeType.rounded(11, .semibold))
                    .foregroundStyle(accent)
                    .padding(.horizontal, 10)
                    .padding(.vertical, 6)
                    .background(accent.opacity(0.13), in: .capsule)
                    .fixedSize()
                VStack(alignment: .leading, spacing: 4) {
                    Text(item.title)
                        .font(NudgeType.serif(16))
                        .foregroundStyle(Theme.ink)
                    Text(item.detail)
                        .font(NudgeType.rounded(13))
                        .foregroundStyle(Theme.inkMuted)
                        .lineSpacing(3)
                        .fixedSize(horizontal: false, vertical: true)
                }
                Spacer(minLength: 0)
            }
            .padding(15)
        }
    }

    // MARK: Clinical data — clearly findable from here

    private var clinicalDataLinks: some View {
        OrganicSurface(radius: 30) {
            VStack(alignment: .leading, spacing: 12) {
                Kicker(text: "Your numbers, one tap away", color: Theme.gold)
                ForEach(model.labSeries) { series in
                    NavigationLink(value: YouDestination.labDetail(series.id)) {
                        HStack {
                            Text(series.name)
                                .font(NudgeType.rounded(14, .medium))
                                .foregroundStyle(Theme.ink)
                            Spacer()
                            if let latest = series.latest {
                                Text("\(latest.value.formatted(.number.precision(.fractionLength(0...1)))) \(series.unit)")
                                    .font(NudgeType.number(13))
                                    .foregroundStyle(Theme.inkMuted)
                            }
                            Image(systemName: "chevron.right")
                                .font(.system(size: 10, weight: .light))
                                .foregroundStyle(Theme.inkMuted)
                        }
                        .padding(.vertical, 6)
                    }
                    .buttonStyle(NudgeButtonStyle())
                }
                NavigationLink(value: YouDestination.records) {
                    Text("The full record, when you want the raw thing")
                        .font(NudgeType.rounded(12.5, .medium))
                        .foregroundStyle(Theme.inkMuted)
                        .underline()
                }
                .buttonStyle(NudgeButtonStyle())
            }
            .padding(17)
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
