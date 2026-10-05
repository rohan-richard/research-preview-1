import SwiftUI

struct FastenRecordsCard: View {
    @Environment(AppModel.self) private var model
    @State private var showConnect: Bool = false
    @State private var showRealConnect: Bool = false
    @State private var expanded: Bool = false
    @State private var showLiveInfo: Bool = false
    @State private var actionError: String? = nil

    var body: some View {
        OrganicSurface {
            VStack(alignment: .leading, spacing: 12) {
                Label("Health records", systemImage: "link").font(NudgeType.serif(20))
                if model.api.isSignedIn { realRecords } else { demoRecords }
            }.padding(18)
        }
        .foregroundStyle(Theme.ink)
        .task { await model.records.refresh() }
        .sheet(isPresented: $showConnect) {
            FastenConnectionView(pathway: model.pathway) { model.demoRecordImport = $0; model.persistUserData() }
        }
        .sheet(isPresented: $showRealConnect, onDismiss: { Task { await model.records.refresh() } }) {
            HealthRecordsConnectSheet().presentationBackground(Theme.base)
        }
        .alert("Sign in to connect your records", isPresented: $showLiveInfo) {
            Button("OK", role: .cancel) { }
        } message: { Text("Real record connections need your Rumi account. Sign in from Settings, then come back here.") }
    }

    private var realRecords: some View {
        VStack(alignment: .leading, spacing: 10) {
            ForEach(model.records.connections) { connection in
                HStack(alignment: .top, spacing: 12) {
                    VStack(alignment: .leading, spacing: 3) {
                        Text(connection.organization).font(NudgeType.rounded(15, .semibold))
                        Text(statusLine(connection)).font(NudgeType.rounded(12)).foregroundStyle(Theme.inkMuted)
                    }
                    Spacer()
                    if connection.isSyncing {
                        ProgressView()
                    } else if connection.status != "revoked" {
                        Button("Sync now") { Task { await run { try await model.records.sync(connection.id) } } }
                            .font(NudgeType.rounded(13, .medium)).frame(minHeight: 44)
                            .accessibilityIdentifier("records.sync")
                    }
                }
            }
            if let summary = model.records.summary, summary.connected {
                Text("\(summary.counts.conditions) conditions · \(summary.counts.medications) medications · \(summary.counts.labTypes) lab types · \(summary.counts.encounters) visits")
                    .font(NudgeType.rounded(12)).foregroundStyle(Theme.inkMuted)
            }
            if model.records.connections.isEmpty {
                Text("Connect a health system and Rumi brings your records together. You choose what to share at the portal.")
                    .font(NudgeType.rounded(14)).foregroundStyle(Theme.inkMuted)
            }
            Button(model.records.connections.isEmpty ? "Connect a health system" : "Connect another health system") { showRealConnect = true }
                .frame(minHeight: 44)
                .accessibilityIdentifier("records.connect")
            if let text = actionError ?? model.records.lastError {
                Text(text).font(NudgeType.rounded(12)).foregroundStyle(Theme.attention)
            }
            Button("Try a demo connection instead") { showConnect = true }.frame(minHeight: 44)
                .font(NudgeType.rounded(13, .medium))
                .accessibilityIdentifier("records.connectFasten")
        }
    }

    private var demoRecords: some View {
        VStack(alignment: .leading, spacing: 12) {
            if let record = model.demoRecordImport {
                Text(record.isRevoked ? "Demo connection paused" : record.isPartial ? "Partial sample import" : "Sample import ready")
                    .font(NudgeType.rounded(15, .semibold))
                Text("\(record.items.count) items · \(record.importedAt.formatted(date: .abbreviated, time: .shortened))")
                    .font(NudgeType.rounded(12)).foregroundStyle(Theme.inkMuted)
                DisclosureGroup("Review imported sample items", isExpanded: $expanded) {
                    ForEach(record.items) { item in
                        VStack(alignment: .leading, spacing: 4) {
                            Text(item.title).font(NudgeType.rounded(14, .medium))
                            Text(item.detail).font(NudgeType.rounded(12)).foregroundStyle(Theme.inkMuted)
                        }.frame(maxWidth: .infinity, alignment: .leading).padding(.vertical, 7)
                    }
                }
                Text(record.provenance).font(NudgeType.rounded(12)).foregroundStyle(Theme.inkMuted)
                HStack {
                    Button("Try again") { showConnect = true }.frame(minHeight: 44)
                    Spacer()
                    Button("Remove import", role: .destructive) { model.demoRecordImport = nil; model.persistUserData() }.frame(minHeight: 44)
                }
            } else {
                Text("Bring authorized records together. Try profile confirmation, sharing and an import with sample data.")
                    .font(NudgeType.rounded(14)).foregroundStyle(Theme.inkMuted)
                Button("Try a demo connection") { showConnect = true }.frame(minHeight: 44)
                    .accessibilityIdentifier("records.connectFasten")
            }
            Button("Connect my real records") { showLiveInfo = true }.frame(minHeight: 44)
                .font(NudgeType.rounded(13, .medium))
        }
    }

    private func statusLine(_ connection: EHRConnection) -> String {
        switch connection.sync.status {
        case "requested", "downloading": "Importing…"
        case "failed": "Import failed · \(connection.sync.error ?? "try again")"
        default:
            if connection.status == "revoked" { "No longer syncing" }
            else if let at = connection.lastSyncedAt { "Synced \(at.formatted(date: .abbreviated, time: .shortened))" }
            else { "Connected" }
        }
    }

    private func run(_ work: () async throws -> Void) async {
        do { try await work(); actionError = nil } catch { actionError = error.localizedDescription }
    }
}
