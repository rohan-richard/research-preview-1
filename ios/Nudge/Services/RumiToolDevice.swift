import Foundation

/// The phone side of a chat-server tool task. The server asks; the device acts in the patient's own portal and replies.
@MainActor protocol RumiToolDevice: AnyObject {
    func handle(_ request: RumiWireProtocol.ToolRequest) async -> RumiWireProtocol.ToolReply
    /// The server stopped or finished the task. Drop anything still waiting on the patient.
    func cancelAll()
}

/// Until the portal browser ships, every request is refused so the server ends the task cleanly.
final class RumiNoPortalDevice: RumiToolDevice {
    func handle(_ request: RumiWireProtocol.ToolRequest) async -> RumiWireProtocol.ToolReply {
        .init(id: request.id, ok: false, error: "This build has no portal browser yet.")
    }
    func cancelAll() {}
}
