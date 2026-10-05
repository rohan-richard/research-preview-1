import SwiftUI
import Charts

/// Compact sourced values without inferred normal/abnormal labels.
struct TodayMetricsView: View {
    @Environment(AppModel.self) private var model

    private var metrics: [LabSeries] { Array(model.labSeries.filter { $0.latest != nil }.prefix(3)) }

    var body: some View {
        if !metrics.isEmpty {
            VStack(alignment: .leading, spacing: 10) {
                HStack {
                    Text("Latest measures")
                        .font(NudgeType.serif(19))
                        .foregroundStyle(Theme.ink)
                    Spacer()
                    Button("View all") { model.openCare(.records) }
                        .font(NudgeType.rounded(12, .semibold))
                        .foregroundStyle(Theme.warm)
                        .frame(minHeight: 44)
                }
                ForEach(metrics) { series in
                    metricRow(series)
                }
            }
        }
    }

    private func metricRow(_ series: LabSeries) -> some View {
        Button {
            model.carePath.append(YouDestination.labDetail(series.id))
            model.tab = .care
        } label: {
            OrganicSurface(radius: 18) {
                HStack(spacing: 12) {
                    VStack(alignment: .leading, spacing: 4) {
                        Text(series.name)
                            .font(NudgeType.rounded(13, .medium))
                            .foregroundStyle(Theme.inkMuted)
                        if let latest = series.latest {
                            HStack(alignment: .firstTextBaseline, spacing: 4) {
                                Text(latest.value.formatted(.number.precision(.fractionLength(0...1))))
                                    .font(NudgeType.number(19))
                                    .foregroundStyle(Theme.ink)
                                Text(series.unit)
                                    .font(NudgeType.rounded(11))
                                    .foregroundStyle(Theme.inkMuted)
                            }
                            Text("\(model.isLive ? "Your records" : "Sample") · \(latest.date.formatted(.dateTime.month(.abbreviated).day().year()))")
                                .font(NudgeType.rounded(10))
                                .foregroundStyle(Theme.inkMuted)
                        }
                    }
                    .fixedSize(horizontal: false, vertical: true)
                    Spacer(minLength: 0)
                    if series.points.count > 1 {
                        Chart(series.points.sorted { $0.date < $1.date }) { point in
                            LineMark(x: .value("Date", point.date), y: .value(series.name, point.value))
                                .foregroundStyle(Theme.life)
                                .lineStyle(StrokeStyle(lineWidth: 1.5))
                        }
                        .chartXAxis(.hidden)
                        .chartYAxis(.hidden)
                        .chartYScale(domain: .automatic(includesZero: false))
                        .frame(width: 62, height: 26)
                        .accessibilityHidden(true)
                    }
                    Image(systemName: "chevron.right")
                        .font(.system(size: 11))
                        .foregroundStyle(Theme.inkMuted)
                }
                .padding(.horizontal, 16)
                .padding(.vertical, 13)
            }
        }
        .buttonStyle(NudgeButtonStyle())
        .accessibilityIdentifier("today.metric.\(series.id)")
    }
}
