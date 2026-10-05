import Foundation
import Observation

nonisolated struct EHRSync: Decodable, Equatable {
    let status: String
    let error: String?
}

nonisolated struct EHRConnection: Decodable, Equatable, Identifiable {
    let id: String
    let organization: String
    let status: String
    let lastSyncedAt: Date?
    let sync: EHRSync

    var isSyncing: Bool { ["requested", "downloading"].contains(sync.status) }
}

nonisolated struct EHRSummary: Decodable, Equatable {
    struct Counts: Decodable, Equatable {
        let conditions: Int
        let allergies: Int
        let medications: Int
        let labTypes: Int
        let encounters: Int
    }
    let connected: Bool
    let lastSyncedAt: Date?
    let counts: Counts
}

nonisolated private struct Page<Item: Decodable>: Decodable {
    let items: [Item]
}

/// Real health-record connections through the Rumi API and Fasten Connect. The demo import stays separate.
@Observable final class HealthRecords {
    private(set) var connections: [EHRConnection] = []
    private(set) var summary: EHRSummary?
    private(set) var lastError: String?
    private let api: RumiAPI

    init(api: RumiAPI) {
        self.api = api
    }

    /// The API serves the Fasten Stitch widget with our public id. The private key never leaves the server.
    var stitchURL: URL { AppConfig.apiBaseURL.appending(path: "/v1/integrations/fasten/stitch") }
    var isSyncing: Bool { connections.contains(where: \.isSyncing) }

    func refresh() async {
        guard api.isSignedIn else {
            connections = []
            summary = nil
            return
        }
        do {
            let page: Page<EHRConnection> = try await api.send(.get, "/v1/ehr/connections")
            connections = page.items
            summary = try await api.send(.get, "/v1/ehr/summary")
            lastError = nil
        } catch {
            lastError = error.localizedDescription
        }
    }

    func hasRecordsConsent() async throws -> Bool {
        let consents: [String: Bool] = try await api.send(.get, "/v1/me/consents")
        return consents["health_records"] ?? false
    }

    func allowRecordsConsent() async throws {
        let _: Empty = try await api.send(.put, "/v1/me/consents/health_records", body: ["granted": true, "policy_version": "2026-09"])
    }

    func connect(orgConnectionID: String, platformType: String) async throws -> EHRConnection {
        let body: [String: Any] = [
            "org_connection_id": orgConnectionID,
            "organization": Self.organizationName(platformType),
            "platform_type": platformType,
        ]
        let created: EHRConnection = try await api.send(.post, "/v1/ehr/connections", body: body)
        await refresh()
        return created
    }

    func sync(_ id: String) async throws {
        let _: Empty = try await api.send(.post, "/v1/ehr/connections/\(id)/sync")
        await refresh()
    }

    func disconnect(_ id: String) async throws {
        let _: Empty = try await api.send(.delete, "/v1/ehr/connections/\(id)")
        await refresh()
    }

    // The Stitch event names the platform, not the health system. The API fills the real name from Fasten's catalog later.
    nonisolated static func organizationName(_ platformType: String) -> String {
        switch platformType.lowercased() {
        case "epic": "Epic health system"
        case "cerner", "oracle": "Oracle Health system"
        case "fooclinic", "sandbox": "FooClinic (Sandbox)"
        case "": "Connected health system"
        default: "\(platformType.capitalized) health system"
        }
    }
}
