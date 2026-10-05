import SwiftUI

/// Medications — the calm list is the surface; full depth lives one tap deep.
/// Adherence is a soft tide, never a percentage red-flag. Logging how a med
/// feels lives right here, beside the med.
struct MedicationsView: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                VStack(alignment: .leading, spacing: 4) {
                    Text("Medications")
                        .font(NudgeType.serif(28))
                        .foregroundStyle(Theme.ink)
                    Text(subtitle)
                        .font(NudgeType.rounded(13))
                        .foregroundStyle(Theme.inkMuted)
                }
                .padding(.top, 8)

                // The tide needs dose history, which only the sample patients have.
                if !model.isLive {
                    VStack(alignment: .leading, spacing: 8) {
                        TideView(level: overallTide)
                        Text("Sample coverage over 30 days · not confirmed dose-taking.")
                            .font(NudgeType.rounded(12))
                            .foregroundStyle(Theme.inkMuted)
                    }
                }

                VStack(spacing: 12) {
                    ForEach(model.medications) { med in
                        medRow(med)
                    }
                }
            }
            .padding(.horizontal, 20)
            .padding(.bottom, 120)
        }
        .scrollIndicators(.hidden)
    }

    private var subtitle: String {
        if model.isLive {
            return model.medications.isEmpty
                ? "Your health records list no current medications."
                : "From your health records."
        }
        switch model.pathway {
        case .metabolic: return "Three friends doing quiet work, every day."
        case .oncology: return "The supporting cast that makes treatment livable."
        case .procedure: return "What's safe now — and what pauses before the 23rd."
        case .cardiometabolic: return "Four working together — heart, sugar and kidneys, covered."
        }
    }

    private var overallTide: Double {
        let levels = model.medications.map(\.tideLevel)
        guard !levels.isEmpty else { return 0 }
        return levels.reduce(0, +) / Double(levels.count)
    }

    private func medRow(_ med: Medication) -> some View {
        OrganicSurface(radius: 30) {
            VStack(alignment: .leading, spacing: 8) {
                HStack(alignment: .top, spacing: 12) {
                    NavigationLink(value: YouDestination.medDetail(med.id)) {
                        HStack(spacing: 12) {
                            Color(.secondarySystemBackground)
                                .frame(width: 54, height: 54)
                                .overlay {
                                    Image(LifeLibrary.medImage(for: med.id))
                                        .resizable()
                                        .aspectRatio(contentMode: .fill)
                                        .allowsHitTesting(false)
                                }
                                .clipShape(.rect(cornerRadius: 16))
                                .overlay(
                                    RoundedRectangle(cornerRadius: 16, style: .continuous)
                                        .strokeBorder(Color.white.opacity(0.55), lineWidth: 0.8)
                                )
                            VStack(alignment: .leading, spacing: 3) {
                                Text(med.name)
                                    .font(NudgeType.serif(18))
                                    .foregroundStyle(Theme.ink)
                                Text(med.purposeLine)
                                    .font(NudgeType.rounded(13))
                                    .foregroundStyle(Theme.inkMuted)
                            }
                        }
                    }
                    .buttonStyle(NudgeButtonStyle())
                    .accessibilityIdentifier("medication.open.\(med.id)")
                    Spacer()
                    supplyChip(med)
                }
                HStack(spacing: 6) {
                    Image(systemName: "clock")
                        .font(.system(size: 10, weight: .light))
                    Text("\(med.dose) · \(med.scheduleLine)")
                        .font(NudgeType.rounded(12))
                    Spacer()
                    // Log a symptom in this med's orbit — patterns need anchors.
                    Button {
                        Haptics.tick()
                        model.quickLogMedID = med.id
                        model.showQuickLog = true
                    } label: {
                        HStack(spacing: 4) {
                            Image(systemName: "plus")
                                .font(.system(size: 10, weight: .medium))
                            Text("Log near this")
                                .font(NudgeType.rounded(11.5, .medium))
                        }
                        .foregroundStyle(Theme.warm)
                        .padding(.horizontal, 10)
                        .padding(.vertical, 6)
                        .background(Theme.warm.opacity(0.11), in: .capsule)
                    }
                    .buttonStyle(NudgeButtonStyle())
                    .accessibilityLabel("Log a symptom near \(med.name)")
                }
                .foregroundStyle(Theme.inkMuted)
            }
            .padding(17)
        }
    }

    private func supplyChip(_ med: Medication) -> some View {
        let soon = med.supplyDaysRemaining <= 7
        return Text("Sample: \(med.supplyDaysRemaining) days")
            .font(NudgeType.number(11, .medium))
            .foregroundStyle(soon ? Theme.attention : Theme.inkMuted)
            .padding(.horizontal, 10)
            .padding(.vertical, 6)
            .background(
                (soon ? Theme.attention.opacity(0.13) : Theme.base.opacity(0.8)),
                in: .capsule
            )
    }
}
