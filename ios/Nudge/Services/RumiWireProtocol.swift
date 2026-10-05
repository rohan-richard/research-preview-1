import Foundation

/// AIService chat protocol (aiservice_chat_server, branch portal-tools at 2796cff).
/// Keep envelope assumptions here so a current server trace can update them without touching UI.
nonisolated enum RumiWireProtocol {
    struct Configuration: Decodable, Equatable {
        let tenant_id: String
        let chat_type: String
        var background_color: String? = nil
        var isValid: Bool { !tenant_id.isEmpty && tenant_id.count <= 255 && ["CHAT", "VOICE"].contains(chat_type) }
    }

    /// A server request that the phone carries out, for example opening the portal or clicking a button.
    struct ToolRequest: Decodable, Equatable {
        let id: String
        let name: String
        var args: [String: JSONValue] = [:]
        var highlight_ref: Int? = nil
    }

    struct ToolReply: Encodable, Equatable {
        let id: String
        let ok: Bool
        var error: String? = nil
        var result: JSONValue? = nil
    }

    struct Event {
        let type: String
        var value: String? = nil
        var tool: ToolRequest? = nil
        var message_id: String? = nil
        var text: String? = nil
        var step: Int? = nil
        var max_steps: Int? = nil
        var fatal: Bool? = nil
        /// Base64 audio of a spoken reply. The text of the same frame is what this audio says.
        var audio: String? = nil
    }

    static func frame(type: String, value: String) throws -> String {
        try encode(["type": type, "value": value])
    }

    // The server reads only value.voice; any other flag shape closes the socket.
    static func voiceFlag(_ enabled: Bool) throws -> String {
        try encode(Flag(value: ["voice": enabled ? "1" : "0"]))
    }

    static func audioFrame(_ pcm: Data) throws -> String {
        try frame(type: "audio", value: "[" + pcm.map(String.init).joined(separator: ",") + "]")
    }

    static func toolReply(_ reply: ToolReply) throws -> String {
        try encode(ToolFrame(value: reply))
    }

    private struct Flag: Encodable {
        var type = "flag"
        let value: [String: String]
    }

    private struct ToolFrame: Encodable {
        var type = "tool"
        let value: ToolReply
    }

    private static func encode<T: Encodable>(_ value: T) throws -> String {
        let data = try JSONEncoder().encode(value)
        guard let text = String(data: data, encoding: .utf8) else { throw RumiConnectionError.protocolMismatch }
        return text
    }

    /// The session id is client-chosen (max 64 chars) and the server binds it to the first tenant and person.
    /// Plain ws stays only for a server on this Mac; everything else is forced to wss.
    static func socketURL(base: URL, sessionID: UUID) throws -> URL {
        guard var parts = URLComponents(url: base.appendingPathComponent(sessionID.uuidString.lowercased()), resolvingAgainstBaseURL: false),
              parts.user == nil, parts.password == nil, parts.query == nil, parts.fragment == nil else { throw RumiConnectionError.configurationResponse }
        let local = ["localhost", "127.0.0.1"].contains(parts.host ?? "")
        parts.scheme = local ? "ws" : "wss"
        guard let result = parts.url else { throw RumiConnectionError.configurationResponse }
        return result
    }

    static func decode(_ text: String) throws -> Event {
        // Spoken replies carry base64 audio, so a frame can be far larger than a text delta.
        guard text.utf8.count <= 4_194_304, let data = text.data(using: .utf8),
              let event = try? JSONDecoder().decode(Event.self, from: data) else { throw RumiConnectionError.protocolMismatch }
        return event
    }
}

nonisolated extension RumiWireProtocol.Event: Decodable {
    private enum Keys: String, CodingKey { case type, value, message_id, text, step, max_steps, fatal, audio }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: Keys.self)
        type = try container.decode(String.self, forKey: .type)
        message_id = try container.decodeIfPresent(String.self, forKey: .message_id)
        text = try container.decodeIfPresent(String.self, forKey: .text)
        step = try container.decodeIfPresent(Int.self, forKey: .step)
        max_steps = try container.decodeIfPresent(Int.self, forKey: .max_steps)
        fatal = try container.decodeIfPresent(Bool.self, forKey: .fatal)
        audio = try container.decodeIfPresent(String.self, forKey: .audio)
        if type == "tool" {
            tool = try container.decode(RumiWireProtocol.ToolRequest.self, forKey: .value)
        } else {
            value = try container.decodeIfPresent(String.self, forKey: .value)
        }
    }
}

/// Arbitrary JSON, for tool arguments and tool results.
nonisolated indirect enum JSONValue: Codable, Equatable {
    case string(String), number(Double), bool(Bool), null
    case array([JSONValue]), object([String: JSONValue])

    init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if container.decodeNil() { self = .null }
        else if let value = try? container.decode(Bool.self) { self = .bool(value) }
        else if let value = try? container.decode(Double.self) { self = .number(value) }
        else if let value = try? container.decode(String.self) { self = .string(value) }
        else if let value = try? container.decode([JSONValue].self) { self = .array(value) }
        else { self = .object(try container.decode([String: JSONValue].self)) }
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        switch self {
        case .string(let value): try container.encode(value)
        case .number(let value): try container.encode(value)
        case .bool(let value): try container.encode(value)
        case .null: try container.encodeNil()
        case .array(let value): try container.encode(value)
        case .object(let value): try container.encode(value)
        }
    }

    var stringValue: String? { if case .string(let value) = self { value } else { nil } }
    var intValue: Int? { if case .number(let value) = self { Int(value) } else { nil } }
    var boolValue: Bool? { if case .bool(let value) = self { value } else { nil } }
}

/// Accepts deltas only for the server-selected turn and requires its terminal control frame.
nonisolated struct RumiTurnAccumulator {
    private(set) var messageID: String? = nil
    private(set) var text: String = ""
    private(set) var isComplete: Bool = false

    mutating func consume(_ event: RumiWireProtocol.Event) throws -> String? {
        guard !isComplete else { return nil }
        if event.type == "control", ["server_processing", "server_speaking"].contains(event.value ?? "") {
            guard messageID == nil, let id = event.message_id, !id.isEmpty, id.count <= 256 else { return nil }
            messageID = id
        } else if event.type == "data" {
            guard let id = messageID, event.message_id == id, let delta = event.text else { return nil }
            guard text.utf8.count + delta.utf8.count <= 262_144 else { throw RumiConnectionError.protocolMismatch }
            text += delta
            return delta
        } else if event.type == "control", event.value == "server_paused" {
            guard let id = messageID, event.message_id == id else { return nil }
            guard !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { throw RumiConnectionError.incomplete }
            isComplete = true
        } else if event.type == "error" {
            throw RumiConnectionError.server(event.value ?? "The Rumi server reported an error.")
        }
        return nil
    }
}
