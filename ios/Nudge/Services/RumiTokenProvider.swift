import Foundation

/// What `GET /v1/chat/token` returns: a 10-minute chat-server JWT for the signed-in patient.
nonisolated struct RumiChatAccess: Decodable, Equatable {
    let accessToken: String
    let expiresIn: Int
    let socketUrl: String
    let tenant: String

    var socketURL: URL? { URL(string: socketUrl) }

    /// The chat server's HTTP base: the socket address without its trailing /ws.
    var serverURL: URL? {
        guard var parts = URLComponents(string: socketUrl) else { return nil }
        parts.scheme = parts.scheme == "ws" ? "http" : "https"
        if parts.path.hasSuffix("/ws") { parts.path = String(parts.path.dropLast(3)) }
        return parts.url
    }

    /// Expiry checking is a usability guard, NOT signature verification or patient authorization.
    static func hasUsableExpiry(_ token: String, now: Date = .now) -> Bool {
        let parts = token.split(separator: ".", omittingEmptySubsequences: false)
        guard token.utf8.count <= 16_384, parts.count == 3, parts.allSatisfy({ !$0.isEmpty }),
              token.unicodeScalars.allSatisfy({ CharacterSet(charactersIn: "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-.").contains($0) }) else { return false }
        var payload = String(parts[1]).replacingOccurrences(of: "-", with: "+").replacingOccurrences(of: "_", with: "/")
        payload += String(repeating: "=", count: (4 - payload.count % 4) % 4)
        guard let data = Data(base64Encoded: payload), let claims = try? JSONDecoder().decode(Expiry.self, from: data) else { return false }
        let remaining = claims.exp - now.timeIntervalSince1970
        return remaining > 15 && remaining <= 660
    }

    private struct Expiry: Decodable { let exp: Double }
}

@MainActor protocol RumiTokenProviding {
    func access() async throws -> RumiChatAccess
    func configuration(for access: RumiChatAccess) async throws -> RumiWireProtocol.Configuration
}

/// Our API mints the chat token for the signed-in user. The tenant API key never reaches the app.
final class RumiAPITokenProvider: RumiTokenProviding {
    private let api: RumiAPI
    init(api: RumiAPI) { self.api = api }

    func access() async throws -> RumiChatAccess {
        let access: RumiChatAccess
        do {
            access = try await api.send(.get, "/v1/chat/token")
        } catch let error as RumiAPIError {
            throw Self.connectionError(for: error)
        }
        guard RumiChatAccess.hasUsableExpiry(access.accessToken), access.socketURL != nil, access.serverURL != nil else { throw RumiConnectionError.token }
        return access
    }

    func configuration(for access: RumiChatAccess) async throws -> RumiWireProtocol.Configuration {
        guard let server = access.serverURL else { throw RumiConnectionError.token }
        let data = try await get(server.appendingPathComponent("getConfig"), bearer: access.accessToken)
        guard let value = try? JSONDecoder().decode(RumiWireProtocol.Configuration.self, from: data), value.isValid else { throw RumiConnectionError.configurationResponse }
        return value
    }

    nonisolated static func connectionError(for error: RumiAPIError) -> RumiConnectionError {
        switch error.code {
        case "onboarding_required": .onboarding
        case "consent_required": .consent
        case "chat_server_unavailable": .unavailable
        default: error == .notSignedIn || error.endsSession ? .signIn : .token
        }
    }

    private func get(_ url: URL, bearer: String) async throws -> Data {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.httpCookieStorage = nil
        configuration.urlCredentialStorage = nil
        configuration.urlCache = nil
        let session = URLSession(configuration: configuration, delegate: RumiSessionDelegate(), delegateQueue: nil)
        defer { session.invalidateAndCancel() }
        var request = URLRequest(url: url, cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: 15)
        request.setValue("Bearer \(bearer)", forHTTPHeaderField: "Authorization")
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        let (bytes, response) = try await session.bytes(for: request)
        guard let http = response as? HTTPURLResponse else { throw RumiConnectionError.configurationResponse }
        guard http.statusCode != 401 && http.statusCode != 403 else { throw RumiConnectionError.authentication }
        guard http.statusCode == 200, http.url == url,
              http.value(forHTTPHeaderField: "Content-Type")?.lowercased().contains("application/json") == true else { throw RumiConnectionError.configurationResponse }
        var result = Data()
        for try await byte in bytes {
            try Task.checkCancellation()
            guard result.count < 65_536 else { throw RumiConnectionError.configurationResponse }
            result.append(byte)
        }
        return result
    }
}
