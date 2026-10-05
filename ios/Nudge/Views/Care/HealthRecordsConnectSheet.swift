import SwiftUI
import WebKit

/// Connects a health system through Fasten Stitch and watches the first import.
struct HealthRecordsConnectSheet: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss

    private enum Stage: Equatable {
        case checking, consent, widget, saving, alreadyConnected
        case importing(EHRConnection)
    }

    @State private var stage: Stage = .checking
    @State private var errorText: String? = nil
    @State private var widgetLoadError: String? = nil
    @State private var widgetAttempt = 0

    var body: some View {
        NavigationStack {
            ZStack {
                LivingGradientView()
                content
            }
            .foregroundStyle(Theme.ink)
            .navigationTitle("Connect records").navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Close") { dismiss() }.accessibilityIdentifier("records.connect.close")
                }
            }
        }
        .task { await start() }
    }

    @ViewBuilder private var content: some View {
        switch stage {
        case .checking:
            ProgressView("Checking your settings…")
        case .consent:
            card("Allow record import", body: "Rumi imports your records from the health system you connect, and keeps them in your account. You can stop this any time in the Privacy Center.") {
                Button("Allow and continue") { Task { await allow() } }
                    .buttonStyle(.borderedProminent).tint(Theme.buttonFill).foregroundStyle(Theme.onAccent).controlSize(.large)
                    .accessibilityIdentifier("records.consent.allow")
            }
        case .widget:
            VStack(spacing: 0) {
                Text("Pick your health system and sign in to its patient portal. Fasten makes the connection. Rumi never sees that password.")
                    .font(NudgeType.rounded(13)).foregroundStyle(Theme.inkMuted)
                    .padding(.horizontal, 20).padding(.vertical, 12)
                if let widgetLoadError {
                    card("Could not open the connection page", body: widgetLoadError) {
                        Button("Try again") {
                            self.widgetLoadError = nil
                            widgetAttempt += 1
                        }
                        .buttonStyle(.borderedProminent).tint(Theme.buttonFill).foregroundStyle(Theme.onAccent).controlSize(.large)
                        .accessibilityIdentifier("records.stitch.retry")
                    }
                } else {
                    StitchWebView(url: model.records.stitchURL) { orgConnectionID, platformType in
                        Task { await save(orgConnectionID: orgConnectionID, platformType: platformType) }
                    } onLoadFailure: { message in
                        widgetLoadError = message
                    }
                    .id(widgetAttempt)
                    .accessibilityIdentifier("records.stitch")
                }
            }
        case .saving:
            ProgressView("Saving your connection…")
        case .alreadyConnected:
            card("Already connected", body: "This health system is already in Rumi. To get new records, use Sync now on the Records card.") {
                Button("Done") { dismiss() }
                    .buttonStyle(.borderedProminent).tint(Theme.buttonFill).foregroundStyle(Theme.onAccent).controlSize(.large)
                    .accessibilityIdentifier("records.connect.done")
            }
        case .importing(let connection):
            card(connection.organization, body: importText(connection.sync)) {
                if connection.isSyncing { ProgressView() }
                Button("Done") { dismiss() }
                    .buttonStyle(.borderedProminent).tint(Theme.buttonFill).foregroundStyle(Theme.onAccent).controlSize(.large)
                    .accessibilityIdentifier("records.connect.done")
            }
            .task(id: connection.id) { await watch(connection.id) }
        }
        if let errorText {
            VStack {
                Spacer()
                Text(errorText).font(NudgeType.rounded(13)).foregroundStyle(Theme.attention)
                    .padding(16).accessibilityIdentifier("records.connect.error")
            }
        }
    }

    private func card(_ title: String, body: String, @ViewBuilder actions: () -> some View) -> some View {
        ScrollView {
            OrganicSurface(radius: 24) {
                VStack(alignment: .leading, spacing: 14) {
                    Text(title).font(NudgeType.serif(26))
                    Text(body).font(NudgeType.rounded(15)).foregroundStyle(Theme.inkMuted).fixedSize(horizontal: false, vertical: true)
                    actions()
                }
                .padding(22)
            }
            .padding(20)
        }
    }

    private func importText(_ sync: EHRSync) -> String {
        switch sync.status {
        case "done": "Your records are in. Open Records to see them."
        case "failed": "The import did not finish. \(sync.error ?? "") Try again from the Records card."
        default: "Your records are being imported. The first import can take a few minutes. You can close this and come back."
        }
    }

    private func start() async {
        do {
            stage = try await model.records.hasRecordsConsent() ? .widget : .consent
        } catch {
            errorText = error.localizedDescription
        }
    }

    private func allow() async {
        do {
            try await model.records.allowRecordsConsent()
            errorText = nil
            stage = .widget
        } catch {
            errorText = error.localizedDescription
        }
    }

    private func save(orgConnectionID: String, platformType: String) async {
        stage = .saving
        do {
            let connection = try await model.records.connect(orgConnectionID: orgConnectionID, platformType: platformType)
            errorText = nil
            stage = .importing(connection)
            Haptics.success()
        } catch let error as RumiAPIError where error.code == "already_connected" {
            await model.records.refresh()
            errorText = nil
            stage = .alreadyConnected
        } catch {
            errorText = error.localizedDescription
            stage = .widget
        }
    }

    private func watch(_ id: String) async {
        while !Task.isCancelled {
            try? await Task.sleep(for: .seconds(5))
            await model.records.refresh()
            guard let current = model.records.connections.first(where: { $0.id == id }) else { return }
            stage = .importing(current)
            if !current.isSyncing { return }
        }
    }
}

/// Hosts the Fasten Stitch widget page that the API serves and reports the finished connection.
struct StitchWebView: UIViewRepresentable {
    let url: URL
    let onComplete: @MainActor (String, String) -> Void
    let onLoadFailure: @MainActor (String) -> Void

    func makeCoordinator() -> Coordinator { Coordinator(onComplete: onComplete, onLoadFailure: onLoadFailure) }

    func makeUIView(context: Context) -> WKWebView {
        let config = WKWebViewConfiguration()
        config.userContentController.add(context.coordinator, name: "fasten")
        let webView = WKWebView(frame: .zero, configuration: config)
        webView.isOpaque = false
        webView.backgroundColor = .clear
        webView.uiDelegate = context.coordinator
        webView.navigationDelegate = context.coordinator
        webView.load(URLRequest(url: url, cachePolicy: .reloadIgnoringLocalCacheData))
        context.coordinator.watchForStall()
        return webView
    }

    func updateUIView(_ webView: WKWebView, context: Context) {}

    static func dismantleUIView(_ webView: WKWebView, coordinator: Coordinator) {
        webView.configuration.userContentController.removeScriptMessageHandler(forName: "fasten")
    }

    final class Coordinator: NSObject, WKScriptMessageHandler, WKUIDelegate, WKNavigationDelegate {
        private let onComplete: @MainActor (String, String) -> Void
        private let onLoadFailure: @MainActor (String) -> Void
        private var popup: WKWebView?
        private var loaded = false
        private var reported = false

        init(onComplete: @escaping @MainActor (String, String) -> Void, onLoadFailure: @escaping @MainActor (String) -> Void) {
            self.onComplete = onComplete
            self.onLoadFailure = onLoadFailure
        }

        // A starved web content process can leave the page blank without any failure callback.
        func watchForStall() {
            DispatchQueue.main.asyncAfter(deadline: .now() + 20) { [weak self] in
                guard let self, !self.loaded else { return }
                self.report("The connection page took too long to load.")
            }
        }

        func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
            if webView !== popup { loaded = true }
        }

        func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
            failed(webView, error)
        }

        func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
            failed(webView, error)
        }

        // iOS can stop a web view's content process to save memory; the page is blank until it loads again.
        func webViewWebContentProcessDidTerminate(_ webView: WKWebView) {
            webView.reload()
        }

        private func failed(_ webView: WKWebView, _ error: Error) {
            // The popup and in-page link changes cancel earlier loads; that is not a failure.
            guard webView !== popup, (error as NSError).code != NSURLErrorCancelled else { return }
            report(error.localizedDescription)
        }

        private func report(_ message: String) {
            guard !reported else { return }
            reported = true
            onLoadFailure(message)
        }

        // The widget opens the health system's sign-in with window.open. A web view only honours that
        // through its UI delegate, and the popup must share the configuration to keep window.opener.
        func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration,
                     for navigationAction: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
            popup?.removeFromSuperview()
            let child = WKWebView(frame: webView.bounds, configuration: configuration)
            child.autoresizingMask = [.flexibleWidth, .flexibleHeight]
            child.uiDelegate = self
            child.accessibilityIdentifier = "records.stitch.popup"
            webView.addSubview(child)
            popup = child
            return child
        }

        func webViewDidClose(_ webView: WKWebView) {
            if webView === popup {
                webView.removeFromSuperview()
                popup = nil
            }
        }

        nonisolated func userContentController(_ controller: WKUserContentController, didReceive message: WKScriptMessage) {
            Task { @MainActor in
                guard let text = message.body as? String, let connection = StitchEvent.completedConnection(in: text) else { return }
                onComplete(connection.org_connection_id, connection.platform_type ?? "")
            }
        }
    }
}

nonisolated struct StitchEvent: Decodable {
    struct Connection: Decodable {
        let org_connection_id: String
        var platform_type: String? = nil
    }
    let event_type: String
    var data: [Connection]? = nil

    static func completedConnection(in text: String) -> Connection? {
        guard let data = text.data(using: .utf8), let event = try? JSONDecoder().decode(StitchEvent.self, from: data),
              event.event_type == "widget.complete" else { return nil }
        return event.data?.first
    }
}
