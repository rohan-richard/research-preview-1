import Foundation
import Testing
@testable import Nudge

/// Runs against the API on this Mac with FooClinic records imported for dev@rumi.local.
/// Pass TEST_RUNNER_RUMI_LIVE=1 to run it; without it the tests are skipped.
@Suite(.serialized, .enabled(if: ProcessInfo.processInfo.environment["RUMI_LIVE"] != nil))
@MainActor struct LiveDataTests {
    private func signedIn(_ email: String) async throws -> AppModel {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let model = AppModel(storageDirectory: directory)
        try await model.api.devSignIn(email: email)
        await model.signedInUserChanged()
        return model
    }

    private func eventually(_ check: () async -> Bool) async -> Bool {
        for _ in 0..<40 {
            if await check() { return true }
            try? await Task.sleep(for: .milliseconds(250))
        }
        return false
    }

    @Test func theRecordsScreensShowTheImportedRecords() async throws {
        let model = try await signedIn("dev@rumi.local")
        #expect(!model.labSeries.isEmpty)
        #expect(model.labSeries.allSatisfy { !$0.points.isEmpty })
        let categories = Set(model.recordItems.map(\.category))
        #expect(categories.isSuperset(of: [.labs, .conditions, .immunizations, .procedures, .notes]))
        #expect(model.recordItems.contains { $0.category == .immunizations && $0.title.contains("Influenza") })
        #expect(!model.appointments.isEmpty)
        #expect(model.sources.contains { $0.name.contains("FooClinic") })
        #expect(model.consents.count == LiveConsent.scopes.count && model.consents.allSatisfy { $0.apiScope != nil })
        // The sample patient's records never mix in.
        #expect(!model.recordItems.contains { MarcusFixtures.recordItems.map(\.title).contains($0.title) })

        await model.api.signOut()
        await model.signedInUserChanged()
        #expect(model.labSeries == model.persona.labSeries)
    }

    @Test func logsHabitsAndCheckInsReachTheAPI() async throws {
        let model = try await signedIn("dev@rumi.local")
        let marker = "Live test \(UUID().uuidString.prefix(8))"

        model.addLog(kind: marker, severity: 0.5, note: "from the live test", bodyRegion: "Head")
        #expect(await eventually {
            let page: LivePage<LiveLog>? = try? await model.api.send(.get, "/v1/logs?kind=symptom&limit=50")
            return page?.items.contains { $0.value["name"]?.stringValue == marker } == true
        })

        model.addEntry(kind: .meal, text: "\(marker) oatmeal")
        #expect(await eventually {
            let page: LivePage<LiveLog>? = try? await model.api.send(.get, "/v1/logs?kind=meal&limit=50")
            return page?.items.contains { $0.value["description"]?.stringValue?.contains(marker) == true } == true
        })
        #expect(model.threads.isEmpty && model.bills.isEmpty && model.moments.isEmpty)

        model.saveHabit(journeyID: nil, habitID: nil, title: marker, support: HabitSupportPlan(reason: "To test", cue: "After lunch"))
        #expect(await eventually {
            let page: LivePage<LiveJourney>? = try? await model.api.send(.get, "/v1/journeys")
            return page?.items.contains { $0.habits.contains { $0.title == marker } } == true
        })
        // Wait for the phone copy to take the API ids, then check in with them.
        #expect(await eventually {
            let page: LivePage<LiveJourney>? = try? await model.api.send(.get, "/v1/journeys")
            let id = page?.items.first { $0.habits.contains { $0.title == marker } }?.id
            return model.journeys.first?.id.uuidString.lowercased() == id
        })
        let journey = try #require(model.journeys.first)
        let habit = try #require(journey.habits.first)
        model.recordHabitCheckIn(journeyID: journey.id, habitID: habit.id, outcome: .kept, note: "")
        let checkIns = "/v1/habits/\(habit.id.uuidString.lowercased())/check-ins"
        #expect(await eventually {
            let page: LivePage<LiveCheckIn>? = try? await model.api.send(.get, checkIns)
            return page?.items.contains { $0.outcome == "kept" } == true
        })
        model.undoHabitCheckIn(journeyID: journey.id, habitID: habit.id)
        #expect(await eventually {
            let page: LivePage<LiveCheckIn>? = try? await model.api.send(.get, checkIns)
            return page?.items.isEmpty == true
        })

        // A fresh load brings the same journey back from the API.
        await model.loadLiveData()
        #expect(model.journeys.contains { $0.habits.contains { $0.title == marker } })
        let _: Empty? = try? await model.api.send(.delete, "/v1/journeys/\(journey.id.uuidString.lowercased())")
    }

    @Test func aNewPatientCanChatAfterAboutYou() async throws {
        let model = try await signedIn("about-\(UUID().uuidString.prefix(8))@rumi.local")
        #expect(model.needsAboutYou)
        var form = AboutYouForm()
        form.firstName = "Jamie"
        form.gender = "Female"
        form.location = "Chicago, IL"
        form.profession = "Teacher"
        form.reason = "Keep my blood pressure in check"
        try await model.completeAboutYou(form)
        #expect(!model.needsAboutYou && model.api.user?.onboardingComplete == true)
        let token: RumiChatAccess = try await RumiAPITokenProvider(api: model.api).access()
        #expect(!token.accessToken.isEmpty)
        #expect(model.consents.first { $0.apiScope == "ai_chat" }?.granted == true)
        let _: Empty? = try? await model.api.send(.delete, "/v1/me", body: ["confirm": "DELETE"])
    }

    @Test func anExportCanBeDownloaded() async throws {
        let model = try await signedIn("dev@rumi.local")
        let link = try await model.requestExport()
        let (data, response) = try await URLSession.shared.data(from: link)
        #expect((response as? HTTPURLResponse)?.statusCode == 200 && data.count > 100)
    }
}
