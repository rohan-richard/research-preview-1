import Foundation
import Observation

nonisolated enum RumiAPIError: Error, LocalizedError, Equatable {
    case api(status: Int, code: String, message: String)
    case notSignedIn
    case transport(String)
    case badResponse

    var errorDescription: String? {
        switch self {
        case .api(_, _, let message): message
        case .notSignedIn: "Sign in to continue."
        case .transport(let detail): "Rumi could not reach its server. \(detail)"
        case .badResponse: "The server sent something Rumi did not expect."
        }
    }

    var code: String? {
        if case .api(_, let code, _) = self { code } else { nil }
    }
}

/// The Rumi API client. The access token stays in memory. The refresh token lives in the Keychain,
/// so a signed-in patient stays signed in across launches.
@Observable final class RumiAPI {
    private(set) var user: RumiUser?
    var isSignedIn: Bool { user != nil }

    private let baseURL: URL
    private let session: URLSession
    private let keychainService: String
    private var accessToken: String?
    private let platform = "ios"

    init(baseURL: URL = AppConfig.apiBaseURL, session: URLSession = .shared, keychainService: String = "app.rumi.api") {
        self.baseURL = baseURL
        self.session = session
        self.keychainService = keychainService
        #if DEBUG
        // UI tests pass -rumi.signedOut YES so a sign-in from an earlier test does not leak in.
        if UserDefaults.standard.bool(forKey: "rumi.signedOut") { Keychain.delete("refresh_token", service: keychainService) }
        #endif
    }

    var hasStoredSession: Bool { refreshToken != nil }

    private var refreshToken: String? {
        get { Keychain.read("refresh_token", service: keychainService) }
        set {
            if let newValue { Keychain.write(newValue, key: "refresh_token", service: keychainService) }
            else { Keychain.delete("refresh_token", service: keychainService) }
        }
    }

    // MARK: Sign in and out

    func signIn(provider: String, idToken: String, nonce: String, given: String? = nil, family: String? = nil) async throws {
        var body: [String: Any] = ["provider": provider, "id_token": idToken, "nonce": nonce, "platform": platform]
        let name = ["given": given, "family": family].compactMapValues { $0 }
        if !name.isEmpty { body["name"] = name }
        establish(try await send(.post, "/v1/auth/sign-in", body: body, authorized: false))
    }

    /// Only works against a local API started with DEV_SIGN_IN=1.
    func devSignIn(email: String) async throws {
        establish(try await send(.post, "/v1/auth/dev-sign-in", body: ["email": email, "platform": platform], authorized: false))
    }

    /// Turns a stored refresh token back into a signed-in user. Call once at launch.
    func restoreSession() async {
        guard hasStoredSession, user == nil else { return }
        do {
            try await refresh()
            user = try await send(.get, "/v1/auth/me")
        } catch let error as RumiAPIError where error.endsSession {
            forget()
        } catch {
            // Offline or the server is down. Keep the token and try again next launch.
        }
    }

    /// Reads the signed-in user again, for example after onboarding finishes on the server.
    func reloadUser() async {
        guard let fresh: RumiUser = try? await send(.get, "/v1/auth/me") else { return }
        user = fresh
    }

    func signOut() async {
        if accessToken != nil {
            let _: Empty? = try? await send(.post, "/v1/auth/sign-out", retryOnExpiry: false)
        }
        forget()
    }

    private func establish(_ tokens: TokenResponse) {
        accessToken = tokens.accessToken
        if let refreshed = tokens.refreshToken { refreshToken = refreshed }
        user = tokens.user
    }

    private func forget() {
        accessToken = nil
        refreshToken = nil
        user = nil
    }

    private func refresh() async throws {
        guard let token = refreshToken else { throw RumiAPIError.notSignedIn }
        do {
            let tokens: TokenResponse = try await send(.post, "/v1/auth/refresh", body: ["refresh_token": token], authorized: false)
            accessToken = tokens.accessToken
            if let refreshed = tokens.refreshToken { refreshToken = refreshed }
        } catch let error as RumiAPIError where error.endsSession {
            forget()
            throw error
        }
    }

    // MARK: Requests

    enum Method: String {
        case get = "GET", post = "POST", patch = "PATCH", put = "PUT", delete = "DELETE"
    }

    func send<T: Decodable>(_ method: Method, _ path: String, body: [String: Any]? = nil,
                            authorized: Bool = true, retryOnExpiry: Bool = true) async throws -> T {
        // appending(path:) escapes "?", so a query string is split off and set on its own.
        let parts = path.split(separator: "?", maxSplits: 1).map(String.init)
        guard var components = URLComponents(url: baseURL.appending(path: parts[0]), resolvingAgainstBaseURL: false) else { throw RumiAPIError.badResponse }
        if parts.count == 2 { components.percentEncodedQuery = parts[1] }
        guard let url = components.url else { throw RumiAPIError.badResponse }
        var request = URLRequest(url: url)
        request.httpMethod = method.rawValue
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        if let body {
            request.httpBody = try JSONSerialization.data(withJSONObject: body)
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        }
        if authorized {
            guard let accessToken else { throw RumiAPIError.notSignedIn }
            request.setValue("Bearer \(accessToken)", forHTTPHeaderField: "Authorization")
        }
        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await session.data(for: request)
        } catch {
            throw RumiAPIError.transport(error.localizedDescription)
        }
        guard let http = response as? HTTPURLResponse else { throw RumiAPIError.badResponse }
        if (200..<300).contains(http.statusCode) {
            let payload = data.isEmpty ? Data("{}".utf8) : data
            do { return try Self.decoder.decode(T.self, from: payload) } catch { throw RumiAPIError.badResponse }
        }
        if authorized, retryOnExpiry, http.statusCode == 401 {
            try await refresh()
            return try await send(method, path, body: body, authorized: true, retryOnExpiry: false)
        }
        let failure = (try? Self.decoder.decode(ErrorBody.self, from: data))?.error
        throw RumiAPIError.api(status: http.statusCode, code: failure?.code ?? "http_\(http.statusCode)",
                               message: failure?.message ?? "The request failed (\(http.statusCode)).")
    }

    private static let decoder: JSONDecoder = {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        decoder.dateDecodingStrategy = .iso8601
        return decoder
    }()
}

nonisolated struct Empty: Decodable {}

nonisolated private struct TokenResponse: Decodable {
    let accessToken: String
    let refreshToken: String?
    let user: RumiUser?
}

nonisolated private struct ErrorBody: Decodable {
    struct Detail: Decodable { let code: String; let message: String }
    let error: Detail
}

extension RumiAPIError {
    /// Errors after which the stored refresh token is useless.
    nonisolated var endsSession: Bool {
        self == .notSignedIn || code == "session_expired" || code == "account_disabled"
    }
}
