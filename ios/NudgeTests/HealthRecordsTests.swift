import Foundation
import Testing
@testable import Nudge

@Suite(.serialized)
@MainActor
struct HealthRecordsTests {
    private static let service = "app.rumi.api.records-tests"
    private static let connection = #"{"id":"c1","organization":"Epic health system","status":"connected","last_synced_at":"2026-10-01T09:00:00Z","sync":{"status":"done","error":null}}"#

    private func makeRecords() async throws -> HealthRecords {
        StubURLProtocol.reset()
        Keychain.delete("refresh_token", service: Self.service)
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [StubURLProtocol.self]
        let api = RumiAPI(baseURL: URL(string: "https://api.test")!, session: URLSession(configuration: config), keychainService: Self.service)
        StubURLProtocol.reply("POST", "/v1/auth/sign-in", 200, #"{"access_token":"a","expires_in":900,"refresh_token":"rt","user":{"id":"u1","email":"e@x.com","display_name":"E","status":"active","onboarding_complete":true,"providers":["google"],"created_at":"2026-10-01T10:00:00Z"}}"#)
        try await api.signIn(provider: "google", idToken: "t", nonce: "n")
        return HealthRecords(api: api)
    }

    @Test func refreshLoadsConnectionsAndTheSummary() async throws {
        let records = try await makeRecords()
        StubURLProtocol.reply("GET", "/v1/ehr/connections", 200, #"{"items":[\#(Self.connection)]}"#)
        StubURLProtocol.reply("GET", "/v1/ehr/summary", 200, #"{"connected":true,"last_synced_at":"2026-10-01T09:00:00Z","counts":{"conditions":2,"allergies":1,"medications":4,"lab_types":9,"encounters":12}}"#)
        await records.refresh()
        #expect(records.connections.map(\.organization) == ["Epic health system"])
        #expect(records.connections.first?.isSyncing == false)
        #expect(records.summary?.counts.labTypes == 9 && records.lastError == nil)
    }

    @Test func connectPostsTheStitchConnectionAndRefreshes() async throws {
        let records = try await makeRecords()
        StubURLProtocol.reply("POST", "/v1/ehr/connections", 201, Self.connection.replacingOccurrences(of: "\"done\"", with: "\"requested\""))
        StubURLProtocol.reply("GET", "/v1/ehr/connections", 200, #"{"items":[\#(Self.connection)]}"#)
        StubURLProtocol.reply("GET", "/v1/ehr/summary", 200, #"{"connected":true,"last_synced_at":null,"counts":{"conditions":0,"allergies":0,"medications":0,"lab_types":0,"encounters":0}}"#)
        let created = try await records.connect(orgConnectionID: "fedec7b7", platformType: "epic")
        #expect(created.sync.status == "requested" && created.isSyncing)
        let post = try #require(StubURLProtocol.seen.first { $0.url?.path == "/v1/ehr/connections" && $0.httpMethod == "POST" })
        #expect(post.value(forHTTPHeaderField: "Authorization") == "Bearer a")
        #expect(records.connections.count == 1)
    }

    @Test func stitchCompleteEventYieldsTheConnection() {
        let text = #"{"api_mode":"test","event_type":"widget.complete","data":[{"org_connection_id":"fedec7b7-8cf6","endpoint_id":"8e2f","platform_type":"epic"}]}"#
        let connection = StitchEvent.completedConnection(in: text)
        #expect(connection?.org_connection_id == "fedec7b7-8cf6" && connection?.platform_type == "epic")
        #expect(StitchEvent.completedConnection(in: #"{"event_type":"patient.connection_pending","data":[]}"#) == nil)
        #expect(HealthRecords.organizationName("epic") == "Epic health system")
    }
}
