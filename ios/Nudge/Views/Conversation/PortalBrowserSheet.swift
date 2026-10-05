import SwiftUI
import WebKit

/// The portal the chat server works in, shown while a task runs. The patient watches and approves anything that submits.
struct PortalBrowserSheet: View {
    let device: RumiPortalDevice
    let onStop: () -> Void

    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 10) {
                RumiMarkView(size: 28, animated: device.pendingConfirm == nil)
                VStack(alignment: .leading, spacing: 2) {
                    Text("Rumi is working in your portal").font(NudgeType.serif(17))
                    Text(device.origin.host ?? "Patient portal").font(NudgeType.rounded(11)).foregroundStyle(Theme.inkMuted).lineLimit(1)
                }
                Spacer()
                Button(action: onStop) {
                    Label("Stop", systemImage: "stop.fill").font(NudgeType.rounded(13, .semibold))
                        .padding(.horizontal, 14).frame(height: 40).background(Theme.accentSoft, in: .capsule)
                }
                .accessibilityLabel("Stop Rumi in the portal").accessibilityIdentifier("portal.stop")
            }
            .padding(.horizontal, 16).padding(.vertical, 12)
            if device.isLoading { ProgressView().progressViewStyle(.linear).tint(Theme.mint) }
            ZStack(alignment: .bottom) {
                if let webView = device.webView {
                    PortalWebView(webView: webView).accessibilityIdentifier("portal.web")
                }
                if let error = device.loadError {
                    VStack(spacing: 14) {
                        Image(systemName: "wifi.exclamationmark").font(.largeTitle)
                        Text(error).font(NudgeType.rounded(14)).multilineTextAlignment(.center)
                        Button("Try again") { device.reload() }
                            .font(NudgeType.rounded(14, .semibold)).frame(minHeight: 44).accessibilityIdentifier("portal.retry")
                    }
                    .padding(24).frame(maxWidth: .infinity, maxHeight: .infinity).background(Theme.raised)
                }
                if let pending = device.pendingConfirm {
                    PortalConfirmCard(summary: pending.summary) { device.respond(allowed: $0) }
                        .transition(.move(edge: .bottom).combined(with: .opacity))
                }
            }
            .animation(NudgeSpring.gentle, value: device.pendingConfirm)
        }
        .background(Theme.base).foregroundStyle(Theme.ink)
        .interactiveDismissDisabled(device.pendingConfirm != nil)
        .accessibilityElement(children: .contain).accessibilityIdentifier("portal.sheet")
    }
}

/// Rumi stops here before anything that books, cancels or submits. The words say exactly what will happen.
private struct PortalConfirmCard: View {
    let summary: String
    let respond: (Bool) -> Void

    private var lines: [String] {
        summary.split(separator: "\n", omittingEmptySubsequences: true).map { $0.trimmingCharacters(in: .whitespaces) }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Before Rumi continues").font(NudgeType.kicker()).foregroundStyle(Theme.gold).textCase(.uppercase)
            Text(lines.first ?? "Continue").font(NudgeType.serif(20))
            if lines.count > 1 {
                ScrollView {
                    VStack(alignment: .leading, spacing: 4) {
                        ForEach(Array(lines.dropFirst().flatMap { $0.components(separatedBy: " · ") }.enumerated()), id: \.offset) { _, line in
                            Text(line).font(NudgeType.rounded(14)).frame(maxWidth: .infinity, alignment: .leading)
                        }
                    }
                }
                .frame(maxHeight: 130)
            }
            HStack(spacing: 10) {
                Button { respond(false) } label: {
                    Text("Don't allow").font(NudgeType.rounded(15, .semibold)).frame(maxWidth: .infinity).frame(height: 50)
                        .background(Theme.raised, in: .rect(cornerRadius: 16))
                }
                .accessibilityIdentifier("portal.confirm.deny")
                Button { Haptics.success(); respond(true) } label: {
                    Text("Allow").font(NudgeType.rounded(15, .semibold)).foregroundStyle(Theme.onAccent).frame(maxWidth: .infinity).frame(height: 50)
                        .background(Theme.buttonFill, in: .rect(cornerRadius: 16))
                }
                .accessibilityIdentifier("portal.confirm.allow")
            }
        }
        .padding(18)
        .background(Theme.surface, in: .rect(cornerRadius: 24))
        .overlay(RoundedRectangle(cornerRadius: 24).strokeBorder(Theme.gold, lineWidth: 1.5))
        .shadow(color: Theme.shadow.opacity(0.18), radius: 12, y: 4)
        .padding(16)
        .onAppear { Haptics.pull() }
        .accessibilityElement(children: .contain).accessibilityIdentifier("portal.confirm")
    }
}

private struct PortalWebView: UIViewRepresentable {
    let webView: WKWebView

    func makeUIView(context: Context) -> WKWebView { webView }
    func updateUIView(_ uiView: WKWebView, context: Context) {}
}
