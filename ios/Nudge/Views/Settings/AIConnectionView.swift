import SwiftUI

/// Who Rumi chats as and how the chat connection is doing.
struct AIConnectionView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @State private var showSignIn: Bool = false

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    Text("Rumi chat")
                        .font(NudgeType.display(30)).accessibilityIdentifier("ai.connection.title")
                    Text("Rumi's own chat server answers you, signed in as you. It remembers you between visits, can talk out loud, and can work in your patient portal when you ask.")
                        .font(NudgeType.rounded(15)).foregroundStyle(Theme.inkMuted)
                    account
                    VStack(alignment: .leading, spacing: 8) {
                        Label(model.aiRouter.isConnected ? "Connected" : "Not connected", systemImage: "point.3.connected.trianglepath.dotted")
                            .font(NudgeType.rounded(14, .semibold)).accessibilityIdentifier("ai.connection.active")
                        Text(model.aiRouter.status).font(NudgeType.rounded(13)).foregroundStyle(Theme.inkMuted)
                    }.padding(18).frame(maxWidth: .infinity, alignment: .leading).background(Theme.raised, in: .rect(cornerRadius: 20))
                }.padding(.horizontal, 20).padding(.vertical, 16)
            }
            .background(Theme.base).foregroundStyle(Theme.ink)
            .navigationTitle("AI connection").navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() }.accessibilityIdentifier("ai.connection.close") } }
            .sheet(isPresented: $showSignIn) { SignInView().presentationBackground(Theme.base) }
        }
    }

    private var account: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Your Rumi account").font(NudgeType.serif(24))
            if let user = model.api.user {
                Text("Chat runs as \(user.email). The chat server only ever sees a short-lived token for you, never your sign-in.")
                    .font(NudgeType.rounded(14)).foregroundStyle(Theme.inkMuted)
                    .accessibilityIdentifier("ai.connection.account")
            } else {
                Text("Sign in first. Rumi needs to know who you are before it can open a chat.")
                    .font(NudgeType.rounded(14)).foregroundStyle(Theme.inkMuted)
                Button("Sign in") { showSignIn = true }
                    .font(NudgeType.rounded(14, .semibold)).foregroundStyle(Theme.warm).frame(minHeight: 44)
                    .accessibilityIdentifier("ai.connection.signIn")
            }
        }.padding(18).frame(maxWidth: .infinity, alignment: .leading).background(Theme.surface, in: .rect(cornerRadius: 22))
    }
}
