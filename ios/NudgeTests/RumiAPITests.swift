import Foundation
import Testing
@testable import Nudge

nonisolated final class StubURLProtocol: URLProtocol {
    nonisolated(unsafe) static var replies: [String: [(status: Int, body: String)]] = [:]
    nonisolated(unsafe) static var seen: [URLRequest] = []

    static func reply(_ method: String, _ path: String, _ status: Int, _ body: String) {
        replies["\(method) \(path)", default: []].append((status, body))
    }

    static func reset() {
        replies = [:]
        seen = []
    }

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        Self.seen.append(request)
        let key = "\(request.httpMethod ?? "GET") \(request.url?.path ?? "")"
        var queue = Self.replies[key] ?? [(404, #"{"error":{"code":"not_found","message":"no stub"}}"#)]
        let reply = queue.count > 1 ? queue.removeFirst() : queue[0]
        Self.replies[key] = queue
        let response = HTTPURLResponse(url: request.url!, statusCode: reply.status, httpVersion: nil, headerFields: ["Content-Type": "application/json"])!
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: Data(reply.body.utf8))
        client?.urlProtocolDidFinishLoading(self)
    }

    override func stopLoading() {}
}

@Suite(.serialized)
@MainActor
struct RumiAPITests {
    private static let service = "app.rumi.api.tests"
    private static let user = #"{"id":"u1","email":"elena@example.com","display_name":"Elena R.","status":"active","onboarding_complete":false,"providers":["google"],"created_at":"2026-09-30T10:00:00Z"}"#
    private static let tokens = #"{"access_token":"access-1","expires_in":900,"refresh_token":"rt_first","user":\#(user)}"#
    private static let expiredAccess = #"{"error":{"code":"access_token_invalid","message":"The access token is missing or expired."}}"#

    private func makeAPI() -> RumiAPI {
        StubURLProtocol.reset()
        Keychain.delete("refresh_token", service: Self.service)
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [StubURLProtocol.self]
        return RumiAPI(baseURL: URL(string: "https://api.test")!, session: URLSession(configuration: config), keychainService: Self.service)
    }

    private func calls() -> [String] {
        StubURLProtocol.seen.map { "\($0.httpMethod ?? "") \($0.url?.path ?? "")" }
    }

    @Test func signInKeepsTheRefreshTokenAndSendsTheAccessToken() async throws {
        let api = makeAPI()
        StubURLProtocol.reply("POST", "/v1/auth/sign-in", 200, Self.tokens)
        StubURLProtocol.reply("GET", "/v1/auth/me", 200, Self.user)
        try await api.signIn(provider: "google", idToken: "id-token", nonce: "nonce-1")
        #expect(api.user?.email == "elena@example.com")
        #expect(api.hasStoredSession)
        #expect(Keychain.read("refresh_token", service: Self.service) == "rt_first")
        #expect(StubURLProtocol.seen[0].value(forHTTPHeaderField: "Authorization") == nil)
        let me: RumiUser = try await api.send(.get, "/v1/auth/me")
        #expect(me.displayName == "Elena R.")
        #expect(StubURLProtocol.seen[1].value(forHTTPHeaderField: "Authorization") == "Bearer access-1")
    }

    @Test func anExpiredAccessTokenIsRefreshedOnceThenRetried() async throws {
        let api = makeAPI()
        StubURLProtocol.reply("POST", "/v1/auth/sign-in", 200, Self.tokens)
        StubURLProtocol.reply("GET", "/v1/auth/me", 401, Self.expiredAccess)
        StubURLProtocol.reply("GET", "/v1/auth/me", 200, Self.user)
        StubURLProtocol.reply("POST", "/v1/auth/refresh", 200, #"{"access_token":"access-2","expires_in":900,"refresh_token":"rt_second"}"#)
        try await api.signIn(provider: "google", idToken: "id-token", nonce: "nonce-1")
        let me: RumiUser = try await api.send(.get, "/v1/auth/me")
        #expect(me.email == "elena@example.com")
        #expect(calls() == ["POST /v1/auth/sign-in", "GET /v1/auth/me", "POST /v1/auth/refresh", "GET /v1/auth/me"])
        #expect(StubURLProtocol.seen[3].value(forHTTPHeaderField: "Authorization") == "Bearer access-2")
        #expect(Keychain.read("refresh_token", service: Self.service) == "rt_second")
    }

    @Test func anEndedSessionSignsTheUserOut() async throws {
        let api = makeAPI()
        StubURLProtocol.reply("POST", "/v1/auth/sign-in", 200, Self.tokens)
        StubURLProtocol.reply("GET", "/v1/auth/me", 401, Self.expiredAccess)
        StubURLProtocol.reply("POST", "/v1/auth/refresh", 401, #"{"error":{"code":"session_expired","message":"Sign in again."}}"#)
        try await api.signIn(provider: "google", idToken: "id-token", nonce: "nonce-1")
        await #expect(throws: RumiAPIError.api(status: 401, code: "session_expired", message: "Sign in again.")) {
            let _: RumiUser = try await api.send(.get, "/v1/auth/me")
        }
        #expect(api.user == nil)
        #expect(!api.hasStoredSession)
    }

    @Test func restoreSessionUsesTheStoredRefreshToken() async throws {
        let api = makeAPI()
        Keychain.write("rt_stored", key: "refresh_token", service: Self.service)
        StubURLProtocol.reply("POST", "/v1/auth/refresh", 200, #"{"access_token":"access-3","expires_in":900,"refresh_token":"rt_next"}"#)
        StubURLProtocol.reply("GET", "/v1/auth/me", 200, Self.user)
        await api.restoreSession()
        #expect(api.user?.email == "elena@example.com")
        #expect(calls() == ["POST /v1/auth/refresh", "GET /v1/auth/me"])
        #expect(StubURLProtocol.seen[1].value(forHTTPHeaderField: "Authorization") == "Bearer access-3")
    }

    @Test func restoreSessionKeepsTheTokenWhenTheServerIsUnreachable() async throws {
        let api = makeAPI()
        Keychain.write("rt_stored", key: "refresh_token", service: Self.service)
        StubURLProtocol.reply("POST", "/v1/auth/refresh", 503, #"{"ok":false}"#)
        await api.restoreSession()
        #expect(api.user == nil)
        #expect(api.hasStoredSession)
    }
}
