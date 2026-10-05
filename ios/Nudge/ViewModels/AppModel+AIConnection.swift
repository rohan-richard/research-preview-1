import Foundation

extension AppModel {
    func captureAIWorkspace() {
        aiWorkspaces[Self.chatWorkspace] = .init(clientID: aiRouter.clientID, turns: companion.turns,
                                                 draft: companion.composerDraft, context: companion.pendingContext, savedAt: .now)
    }

    func restoreAIWorkspace(from saved: SanoUserData) {
        aiWorkspaces = saved.aiWorkspaces ?? [:]
        let workspace = aiWorkspaces[Self.chatWorkspace] ?? .init()
        aiRouter.clientID = workspace.clientID
        companion.restore(turns: workspace.turns, draft: workspace.draft,
                          context: workspace.context?.scenario == pathway.rawValue ? workspace.context : nil)
    }

    // Saved under the old mode's key so chats from before the Rork removal keep loading.
    static let chatWorkspace = "backend"
}
