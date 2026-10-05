import SwiftUI

/// The conventional browser for when the user wants the raw thing — every row
/// carries one-tap "What does this mean for me?"
struct RecordsDrawerView: View {
    @Environment(AppModel.self) private var model

    private let columns = [GridItem(.flexible(), spacing: 13), GridItem(.flexible(), spacing: 13)]

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                VStack(alignment: .leading, spacing: 4) {
                    Text("Records")
                        .font(NudgeType.serif(28))
                        .foregroundStyle(Theme.ink)
                    Text("Your health history and source documents.")
                        .font(NudgeType.rounded(13))
                        .foregroundStyle(Theme.inkMuted)
                }
                .padding(.top, 8)

                NavigationLink(value: CareDestination.documents) {
                    Label("Your documents", systemImage: "doc.on.doc")
                        .font(NudgeType.rounded(14, .medium))
                        .frame(minHeight: 44)
                }

                FastenRecordsCard()

                DisclosureGroup(model.isLive ? "Connected sources" : "Sample sources") {
                VStack(spacing: 9) {
                    ForEach(model.sources) { source in
                        HStack {
                            VStack(alignment: .leading, spacing: 2) {
                                Text(source.name)
                                    .font(NudgeType.rounded(13.5, .medium))
                                    .foregroundStyle(Theme.ink)
                                Text(source.railLabel)
                                    .font(NudgeType.rounded(11))
                                    .foregroundStyle(Theme.inkMuted)
                            }
                            Spacer()
                            FreshnessChip(date: source.lastSync)
                        }
                        .padding(.horizontal, 16)
                        .padding(.vertical, 11)
                        .background(Theme.surface.opacity(0.7), in: .rect(cornerRadius: 22, style: .continuous))
                    }
                }

                }
                .font(NudgeType.rounded(14))
                .foregroundStyle(Theme.inkMuted)

                LazyVGrid(columns: columns, spacing: 13) {
                    ForEach(RecordCategory.allCases) { category in
                        NavigationLink(value: YouDestination.category(category)) {
                            categoryCard(category)
                        }
                        .buttonStyle(NudgeButtonStyle())
                    }
                }

                NavigationLink(value: YouDestination.care) {
                    OrganicSurface(radius: 28) {
                        HStack(spacing: 13) {
                            Image(systemName: "person.2")
                                .font(.system(size: 17, weight: .light))
                                .foregroundStyle(Theme.life)
                                .frame(width: 40, height: 40)
                                .background(Theme.life.opacity(0.13), in: .circle)
                            VStack(alignment: .leading, spacing: 2) {
                                Text("Care team & visits")
                                    .font(NudgeType.serif(17))
                                    .foregroundStyle(Theme.ink)
                                Text("People involved in your care")
                                    .font(NudgeType.rounded(12.5))
                                    .foregroundStyle(Theme.inkMuted)
                            }
                            Spacer()
                            Image(systemName: "chevron.right")
                                .font(.system(size: 12, weight: .light))
                                .foregroundStyle(Theme.inkMuted)
                        }
                        .padding(16)
                    }
                }
                .buttonStyle(NudgeButtonStyle())
            }
            .padding(.horizontal, 20)
            .padding(.bottom, 120)
        }
        .scrollIndicators(.hidden)
    }

    private func categoryCard(_ category: RecordCategory) -> some View {
        let count = model.recordItems.filter { $0.category == category }.count
        return OrganicSurface(radius: 28) {
            VStack(alignment: .leading, spacing: 10) {
                Image(systemName: category.glyph)
                    .font(.system(size: 17, weight: .light))
                    .foregroundStyle(Theme.sky)
                Text(category.rawValue)
                    .font(NudgeType.serif(16))
                    .foregroundStyle(Theme.ink)
                Text(count == 0 ? "Nothing yet" : "\(count) item\(count == 1 ? "" : "s")")
                    .font(NudgeType.rounded(11.5))
                    .foregroundStyle(Theme.inkMuted)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(16)
        }
    }
}

/// One record category — rows morph into explain sheets.
struct RecordCategoryView: View {
    @Environment(AppModel.self) private var model
    let category: RecordCategory

    @State private var explaining: RecordItem? = nil
    @State private var conflictItem: RecordItem? = nil

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 13) {
                Text(category.rawValue)
                    .font(NudgeType.serif(28))
                    .foregroundStyle(Theme.ink)
                    .padding(.top, 8)

                if category == .medications {
                    NavigationLink(value: YouDestination.medications) {
                        HStack {
                            Text("Open the full medications space")
                                .font(NudgeType.rounded(13.5, .medium))
                                .foregroundStyle(Theme.ink)
                            Spacer()
                            Image(systemName: "arrow.right")
                                .font(.system(size: 12, weight: .light))
                                .foregroundStyle(Theme.inkMuted)
                        }
                        .padding(.horizontal, 16)
                        .padding(.vertical, 13)
                        .background(.ultraThinMaterial, in: .rect(cornerRadius: 22, style: .continuous))
                        .overlay(
                            RoundedRectangle(cornerRadius: 22, style: .continuous)
                                .strokeBorder(Color.white.opacity(0.22), lineWidth: 0.8)
                        )
                    }
                    .buttonStyle(NudgeButtonStyle())
                }

                if items.isEmpty {
                    ContentUnavailableView("No source entries available", systemImage: "doc.text.magnifyingglass", description: Text("This sample story does not include records in this category. No other person's entries have been substituted."))
                }
                ForEach(items) { item in
                    recordRow(item)
                }
            }
            .padding(.horizontal, 20)
            .padding(.bottom, 120)
        }
        .scrollIndicators(.hidden)
        .sheet(item: $explaining) { item in
            ExplainSheet(item: item)
                .presentationDetents([.medium, .large])
                .presentationBackground(Theme.base)
        }
        .sheet(item: $conflictItem) { item in
            ConflictSheet(item: item)
                .presentationDetents([.medium])
                .presentationBackground(Theme.base)
        }
    }

    private var items: [RecordItem] {
        model.recordItems
            .filter { $0.category == category }
            .sorted { $0.date > $1.date }
    }

    private func recordRow(_ item: RecordItem) -> some View {
        OrganicSurface(radius: 26) {
            VStack(alignment: .leading, spacing: 8) {
                HStack(alignment: .top) {
                    VStack(alignment: .leading, spacing: 3) {
                        Text(item.title)
                            .font(NudgeType.serif(16.5))
                            .foregroundStyle(Theme.ink)
                        Text(item.detail)
                            .font(NudgeType.rounded(12.5))
                            .foregroundStyle(Theme.inkMuted)
                    }
                    Spacer()
                    Text(item.date.formatted(.dateTime.month(.abbreviated).year()))
                        .font(NudgeType.rounded(11, .medium))
                        .foregroundStyle(Theme.inkMuted)
                }

                HStack(spacing: 8) {
                    if let seriesID = item.seriesID {
                        NavigationLink(value: YouDestination.labDetail(seriesID)) {
                            explainLabel("Trend", glyph: "chart.xyaxis.line")
                        }
                        .buttonStyle(NudgeButtonStyle())
                    }

                    Button {
                        explaining = item
                    } label: {
                        explainLabel("What does this mean for me?", glyph: "sparkles")
                    }
                    .buttonStyle(NudgeButtonStyle())

                    if item.conflicted {
                        Button {
                            conflictItem = item
                        } label: {
                            HStack(spacing: 4) {
                                Image(systemName: "arrow.triangle.branch")
                                    .font(.system(size: 10, weight: .medium))
                                Text("Sources differ")
                                    .font(NudgeType.rounded(11.5, .medium))
                            }
                            .foregroundStyle(Theme.attention)
                            .padding(.horizontal, 11)
                            .padding(.vertical, 7)
                            .background(Theme.attention.opacity(0.12), in: .capsule)
                        }
                        .buttonStyle(NudgeButtonStyle())
                    }
                }

                Text(item.source)
                    .font(NudgeType.rounded(10.5))
                    .foregroundStyle(Theme.inkMuted.opacity(0.8))
            }
            .padding(16)
        }
    }

    private func explainLabel(_ text: String, glyph: String) -> some View {
        HStack(spacing: 4) {
            Image(systemName: glyph)
                .font(.system(size: 10, weight: .medium))
            Text(text)
                .font(NudgeType.rounded(11.5, .medium))
        }
        .foregroundStyle(Theme.ink)
        .padding(.horizontal, 11)
        .padding(.vertical, 7)
        .background(.ultraThinMaterial, in: .capsule)
        .overlay(Capsule().strokeBorder(Color.white.opacity(0.25), lineWidth: 0.8))
    }
}

/// Calm merged view when sources disagree — reconciliation is a
/// clinical-safety feature, not hygiene.
private struct ConflictSheet: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    let item: RecordItem

    @State private var showReview: Bool = false

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Capsule().fill(Theme.inkMuted.opacity(0.3)).frame(width: 36, height: 4)
                .frame(maxWidth: .infinity)
                .padding(.top, 10)

            Kicker(text: "Sources differ here", color: Theme.attention)
            Text(item.title)
                .font(NudgeType.serif(22))
                .foregroundStyle(Theme.ink)
            Text(item.conflictNote ?? "")
                .font(NudgeType.rounded(15))
                .foregroundStyle(Theme.ink.opacity(0.85))
                .lineSpacing(3)

            Group {
                Button {
                    showReview = true
                } label: {
                    Text("Prepare a clarification question")
                        .font(NudgeType.rounded(15, .semibold))
                        .foregroundStyle(Theme.base)
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 14)
                        .background(Theme.ink, in: .capsule)
                }
                .buttonStyle(NudgeButtonStyle())
            }

            Spacer()
        }
        .padding(.horizontal, 24)
        .sheet(isPresented: $showReview) {
            WorkflowReviewView(originID: item.id, title: "Clarify · \(item.title)",
                               detail: "Could you help clarify the conflicting information for \(item.title)? \(item.conflictNote ?? "The sources differ.")",
                               context: model.context(for: item))
        }
    }
}
