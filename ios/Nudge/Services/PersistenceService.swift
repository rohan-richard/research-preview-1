import Foundation

/// Everything the user creates survives relaunch — the life log, symptom
/// logs, held moments, the visit guide, and what the companion remembers.
/// One JSON document in the app's own container; private, exportable,
/// deletable. Persona fixtures stay code-side and merge on load.
struct SanoUserData: Codable {
    var pathway: String = ""
    var entries: [CareEntry] = []
    var logs: [SymptomLog] = []
    var memories: [MemoryGlimpse] = []
    var guideItems: [GuideItem] = []
    var memoryNotes: [MemoryItem] = []
    // v5 Care hub — everything the user creates in Care survives relaunch.
    var threads: [MessageThread] = []
    var requests: [CareRequest] = []
    var documents: [CareDocument] = []
    /// Stable keys of bills the user has paid (paid handoff is user-driven).
    var paidBillKeys: [String] = []
    /// Care-plan goals the user turned into journeys (§4.4.5).
    var derivedJourneyGoals: [String] = []
    /// Optional so snapshots written before reply-draft persistence still decode.
    var messageDrafts: [String: String]? = nil
    var demoRecordImport: DemoRecordImport? = nil
    var appointments: [Appointment]? = nil
    var visitPreps: [String: AppointmentPrep]? = nil
    var journeys: [Journey]? = nil
    var habitCheckIns: [HabitCheckIn]? = nil
    var conversation: [ConversationTurn]? = nil
    var composerDraft: String? = nil
    var workflows: [ReviewedWorkflow]? = nil
    var pendingCareContext: CareContext? = nil
    var aiWorkspaces: [String: RumiChatWorkspace]? = nil
}

enum PersistenceService {
    private static var fileURL: URL {
        URL.documentsDirectory.appendingPathComponent("sano_user_data.json")
    }

    private static func scenarioURL(_ pathway: String, directory: URL) -> URL? {
        guard CarePathway(rawValue: pathway) != nil else { return nil }
        return directory.appendingPathComponent("sano_demo_\(pathway).json")
    }

    static func load(pathway: String? = nil, directory: URL = .documentsDirectory) -> SanoUserData? {
        let legacyURL = directory.appendingPathComponent("sano_user_data.json")
        let scopedURL = pathway.flatMap { scenarioURL($0, directory: directory) }
        let url = scopedURL.flatMap { FileManager.default.fileExists(atPath: $0.path) ? $0 : nil } ?? legacyURL
        guard let data = try? Data(contentsOf: url) else { return nil }
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        do {
            let saved = try decoder.decode(SanoUserData.self, from: data)
            guard pathway == nil || saved.pathway == pathway else { return nil }
            return saved
        } catch {
            print("[Sano] user data could not be restored")
            return nil
        }
    }

    @discardableResult
    static func save(_ data: SanoUserData, directory: URL = .documentsDirectory) -> Bool {
        guard let destination = scenarioURL(data.pathway, directory: directory) else { return false }
        // Never overwrite an unreadable existing snapshot with newly seeded data.
        if FileManager.default.fileExists(atPath: destination.path) {
            let decoder = JSONDecoder()
            decoder.dateDecodingStrategy = .iso8601
            guard let existing = try? Data(contentsOf: destination),
                  (try? decoder.decode(SanoUserData.self, from: existing)) != nil else { return false }
        }
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        do {
            let encoded = try encoder.encode(data)
            try encoded.write(to: destination, options: [.atomic, .completeFileProtection])
            return true
        } catch {
            print("[Rumi] local save failed")
            return false
        }
    }

    static func wipe() {
        try? FileManager.default.removeItem(at: fileURL)
        for pathway in CarePathway.allCases {
            if let url = scenarioURL(pathway.rawValue, directory: .documentsDirectory) {
                try? FileManager.default.removeItem(at: url)
            }
        }
    }
}
