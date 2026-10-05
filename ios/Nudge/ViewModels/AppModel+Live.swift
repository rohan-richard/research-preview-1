import Foundation

/// The signed-in patient's own data from the Rumi API. Signed out, the app keeps its sample patients.
extension AppModel {
    var isLive: Bool { api.isSignedIn }

    /// Called on launch and whenever the signed-in user changes.
    func signedInUserChanged() async {
        if api.isSignedIn {
            if sampleUserState == nil { sampleUserState = .init(journeys: journeys, logs: logs, habitCheckIns: habitCheckIns, appointments: appointments, memories: memories,
                                    entries: entries, threads: threads, bills: bills, moments: moments) }
            // Messages, bills and Today's stories have no backend yet, so a signed-in patient sees none of the samples.
            memories = []
            threads = []
            bills = []
            moments = []
            await loadLiveData()
            needsAboutYou = api.user?.onboardingComplete == false
        } else if let sample = sampleUserState {
            sampleUserState = nil
            needsAboutYou = false
            useSampleClinicalData()
            journeys = sample.journeys
            logs = sample.logs
            habitCheckIns = sample.habitCheckIns
            appointments = sample.appointments
            memories = sample.memories
            entries = sample.entries
            threads = sample.threads
            bills = sample.bills
            moments = sample.moments
            liveConditions = nil
            liveCarePlan = nil
            liveFirstName = nil
        }
    }

    func loadLiveData() async {
        guard api.isSignedIn else { return }
        await records.refresh()
        async let labs = liveLabs()
        async let meds = liveMedications()
        async let items = liveRecordItems()
        async let team = liveCareTeam()
        async let visits = liveVisits()
        async let journeys = liveJourneys()
        async let logs = liveLogs()
        async let consents = liveConsents()
        async let conditions = liveConditionList()
        async let plan = livePlan()
        async let me: AboutYouProfile? = try? api.send(.get, "/v1/me/profile")
        if let value = await labs { labSeries = value }
        if let value = await meds { medications = value }
        if let value = await items { recordItems = (labItems() + medicationItems() + value).sorted { $0.date > $1.date } }
        if let value = await team { careTeam = value }
        if let value = await visits { appointments = value }
        if let value = await journeys { self.journeys = value }
        if let value = await logs {
            self.logs = value.compactMap(\.symptomLog).sorted { $0.at < $1.at }
            entries = value.compactMap { $0.careEntry(medications: medications) }
        }
        if let value = await consents { self.consents = value }
        if let value = await conditions { liveConditions = value }
        if let value = await plan { liveCarePlan = value }
        if let value = await me { liveFirstName = value.preferredName ?? value.firstName }
        sources = records.connections.map {
            RecordSource(name: $0.organization, railLabel: "Fasten Connect", connected: $0.status != "revoked",
                         lastSync: $0.lastSyncedAt ?? .distantPast)
        }
    }

    private func useSampleClinicalData() {
        labSeries = persona.labSeries
        medications = persona.medications
        careTeam = persona.careTeam
        recordItems = pathway == .metabolic ? MarcusFixtures.recordItems : []
        sources = pathway == .metabolic ? MarcusFixtures.sources : []
        consents = MarcusFixtures.consents
    }

    // MARK: Records

    private func liveLabs() async -> [LabSeries]? {
        guard let page: LivePage<LiveLab> = try? await api.send(.get, "/v1/ehr/labs?limit=200") else { return nil }
        return await withTaskGroup(of: LabSeries?.self) { group in
            for lab in page.items {
                guard let code = lab.code.code?.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) else { continue }
                group.addTask { [api] in
                    guard let series: LiveLabSeries = try? await api.send(.get, "/v1/ehr/labs/\(code)") else { return nil }
                    return series.labSeries(category: lab.category)
                }
            }
            var all: [LabSeries] = []
            for await series in group { if let series, !series.points.isEmpty { all.append(series) } }
            // Vitals and the most measured results first: those are the ones worth a chart.
            return all.sorted { ($0.points.count, $0.name) > ($1.points.count, $1.name) }
        }
    }

    private func liveMedications() async -> [Medication]? {
        guard let page: LivePage<LiveMedication> = try? await api.send(.get, "/v1/ehr/medications?status=active&limit=200") else { return nil }
        return page.items.map(\.medication)
    }

    private func liveRecordItems() async -> [RecordItem]? {
        async let conditions: LivePage<LiveCondition>? = try? api.send(.get, "/v1/ehr/conditions?status=all&limit=200")
        async let immunizations: LivePage<LiveImmunization>? = try? api.send(.get, "/v1/ehr/immunizations?limit=200")
        async let procedures: LivePage<LiveProcedure>? = try? api.send(.get, "/v1/ehr/procedures?limit=200")
        async let documents: LivePage<LiveDocument>? = try? api.send(.get, "/v1/ehr/documents?limit=200")
        let (c, i, p, d) = await (conditions, immunizations, procedures, documents)
        guard c != nil || i != nil || p != nil || d != nil else { return nil }
        var all: [RecordItem] = c?.items.map(\.item) ?? []
        all += i?.items.map(\.item) ?? []
        all += p?.items.map(\.item) ?? []
        all += d?.items.map(\.item) ?? []
        return all
    }

    private func labItems() -> [RecordItem] {
        labSeries.compactMap { series in
            guard let latest = series.latest else { return nil }
            return RecordItem(category: .labs, title: series.name, detail: "\(LiveFormat.number(latest.value)) \(series.unit)",
                              date: latest.date, source: series.provenance, seriesID: series.id)
        }
    }

    private func medicationItems() -> [RecordItem] {
        medications.map { RecordItem(category: .medications, title: $0.name, detail: $0.scheduleLine, date: .now, source: $0.pharmacy) }
    }

    private func liveCareTeam() async -> [CareTeamMember]? {
        guard let page: LivePage<LiveMember> = try? await api.send(.get, "/v1/ehr/care-team?limit=200") else { return nil }
        return page.items.map { CareTeamMember(name: $0.name ?? "Care team member", role: $0.role ?? "", org: $0.organization ?? "") }
    }

    /// Booked visits from the API, then past visits from the records.
    private func liveVisits() async -> [Appointment]? {
        async let booked: LivePage<LiveAppointment>? = try? api.send(.get, "/v1/appointments?status=upcoming&limit=200")
        async let past: LivePage<LiveEncounter>? = try? api.send(.get, "/v1/ehr/encounters?limit=200")
        let (b, p) = await (booked, past)
        guard b != nil || p != nil else { return nil }
        return (b?.items.compactMap(\.appointment) ?? []) + (p?.items.compactMap(\.appointment) ?? [])
    }

    var shownConditions: [CareCondition] { isLive ? liveConditions ?? [] : persona.conditions }
    var shownCarePlan: CarePlan { isLive ? liveCarePlan ?? LivePlan.empty : persona.carePlan }
    var shownConditionChip: String { isLive ? shownConditions.first?.name ?? "Your health records" : persona.conditionChip }

    private func liveConditionList() async -> [CareCondition]? {
        guard let page: LivePage<LiveCondition> = try? await api.send(.get, "/v1/ehr/conditions?status=active&limit=200") else { return nil }
        return page.items.map(\.careCondition)
    }

    private func livePlan() async -> CarePlan? {
        guard let page: LivePage<LivePlan> = try? await api.send(.get, "/v1/care-plans?status=all") else { return nil }
        var plans: [LivePlan] = []
        for summary in page.items {
            if let full: LivePlan = try? await api.send(.get, "/v1/care-plans/\(summary.id)") { plans.append(full) }
        }
        return LivePlan.merge(plans)
    }

    // MARK: Journeys and habits

    private func liveJourneys() async -> [Journey]? {
        guard let page: LivePage<LiveJourney> = try? await api.send(.get, "/v1/journeys") else { return nil }
        var result: [Journey] = []
        for summary in page.items {
            guard let full: LiveJourney = try? await api.send(.get, "/v1/journeys/\(summary.id)") else { continue }
            var habits: [AtomicHabit] = []
            for habit in full.habits {
                let history: LivePage<LiveCheckIn>? = try? await api.send(.get, "/v1/habits/\(habit.id)/check-ins")
                habits.append(habit.atomicHabit(checkIns: history?.items ?? habit.thisWeek ?? []))
            }
            result.append(Journey(id: UUID(uuidString: full.id) ?? UUID(), title: full.title, why: full.why,
                                  habits: habits, gardenSeed: full.id.utf8.reduce(0) { ($0 + Int($1)) % 97 }))
        }
        return result
    }

    /// A journey made on the phone gets its API ids, so later edits and check-ins find it.
    func saveNewJourneyLive(_ journey: Journey) {
        guard isLive else { return }
        Task {
            guard let created: LiveJourney = try? await api.send(.post, "/v1/journeys", body: ["title": journey.title, "why": journey.why]),
                  let newID = UUID(uuidString: created.id) else { return }
            var habitIDs: [UUID: UUID] = [:]
            for habit in journey.habits {
                let body = LiveHabit.body(title: habit.title, support: habit.support, context: habit.contextLine)
                if let made: LiveHabit = try? await api.send(.post, "/v1/journeys/\(created.id)/habits", body: body),
                   let id = UUID(uuidString: made.id) { habitIDs[habit.id] = id }
            }
            guard let index = journeys.firstIndex(where: { $0.id == journey.id }) else { return }
            journeys[index].id = newID
            for h in journeys[index].habits.indices {
                if let id = habitIDs[journeys[index].habits[h].id] { journeys[index].habits[h].id = id }
            }
        }
    }

    func saveHabitLive(habitID: UUID, title: String, support: HabitSupportPlan) {
        guard isLive else { return }
        var body = LiveHabit.body(title: title, support: support, context: support.cue)
        body["paused"] = support.paused
        Task { let _: Empty? = try? await api.send(.patch, "/v1/habits/\(habitID.uuidString.lowercased())", body: body) }
    }

    func saveCheckInLive(habitID: UUID, outcome: HabitCheckIn.Outcome?, note: String) {
        guard isLive else { return }
        let path = "/v1/habits/\(habitID.uuidString.lowercased())/check-ins/\(LiveFormat.day(.now))"
        Task {
            if let outcome {
                let _: Empty? = try? await api.send(.put, path, body: ["outcome": LiveCheckIn.apiOutcome(outcome), "note": note])
            } else {
                let _: Empty? = try? await api.send(.delete, path)
            }
        }
    }

    // MARK: Logs

    private func liveLogs() async -> [LiveLog]? {
        let page: LivePage<LiveLog>? = try? await api.send(.get, "/v1/logs?limit=200")
        return page?.items
    }

    func saveEntryLive(_ entry: CareEntry) {
        guard isLive else { return }
        var body: [String: Any] = ["taken_at": ISO8601DateFormatter().string(from: entry.at)]
        switch entry.kind {
        case .meal: body["kind"] = "meal"; body["value"] = ["description": entry.title]
        case .move: body["kind"] = "activity"; body["value"] = ["description": entry.title]
        case .med:
            guard let id = entry.linkedMedID, UUID(uuidString: id) != nil else { return }
            body["kind"] = "medication_taken"; body["value"] = ["medication_id": id, "status": "taken"]
        }
        if let note = entry.note, !note.isEmpty { body["note"] = note }
        Task { let _: Empty? = try? await api.send(.post, "/v1/logs", body: body) }
    }

    func saveLogLive(_ log: SymptomLog) {
        guard isLive else { return }
        var value: [String: Any] = ["name": log.kind, "severity": max(1, min(10, Int((log.severity * 10).rounded())))]
        if let region = log.bodyRegion { value["body_region"] = region }
        var body: [String: Any] = ["kind": "symptom", "value": value, "taken_at": ISO8601DateFormatter().string(from: log.at)]
        if let note = log.note { body["note"] = note }
        Task { let _: Empty? = try? await api.send(.post, "/v1/logs", body: body) }
    }

    // MARK: Onboarding

    /// Saves the answers, grants the chat consent the patient just turned on, and finishes onboarding on the server.
    func completeAboutYou(_ form: AboutYouForm) async throws {
        let _: Empty = try await api.send(.patch, "/v1/me/profile", body: form.body)
        try await setConsentLive("ai_chat", granted: true)
        let _: Empty = try await api.send(.post, "/v1/me/onboarding/complete")
        await api.reloadUser()
        needsAboutYou = false
        await loadLiveData()
    }

    // MARK: Privacy

    private func liveConsents() async -> [ConsentEntry]? {
        guard let granted: [String: Bool] = try? await api.send(.get, "/v1/me/consents") else { return nil }
        return LiveConsent.scopes.map { scope in
            ConsentEntry(source: scope.title, scope: scope.detail, granted: granted[scope.id] ?? false, at: .now, apiScope: scope.id)
        }
    }

    func setConsentLive(_ scope: String, granted: Bool) async throws {
        let _: Empty = try await api.send(.put, "/v1/me/consents/\(scope)", body: ["granted": granted, "policy_version": LiveConsent.policyVersion])
    }

    /// Asks the API for a full export and waits for the worker to build it. Returns the download link.
    func requestExport() async throws -> URL {
        let request: LiveExport = try await api.send(.post, "/v1/me/exports")
        for _ in 0..<60 {
            try await Task.sleep(for: .seconds(2))
            let status: LiveExport = try await api.send(.get, "/v1/me/exports/\(request.id)")
            if status.status == "failed" { throw RumiAPIError.api(status: 500, code: "export_failed", message: "The export could not be built. Try again later.") }
            if let link = status.downloadUrl, let url = URL(string: link) { return url }
        }
        throw RumiAPIError.api(status: 504, code: "export_slow", message: "The export is still being built. Try again in a few minutes.")
    }

    func deleteAccount() async throws {
        // The patient already confirmed in the app's own dialog; the API asks for the same word.
        let _: Empty = try await api.send(.delete, "/v1/me", body: ["confirm": "DELETE"])
        await api.signOut()
        PersistenceService.wipe()
        await signedInUserChanged()
    }
}

struct SampleUserState {
    var journeys: [Journey]
    var logs: [SymptomLog]
    var habitCheckIns: [HabitCheckIn]
    var appointments: [Appointment]
    var memories: [MemoryGlimpse]
    var entries: [CareEntry]
    var threads: [MessageThread]
    var bills: [Bill]
    var moments: [Moment]
}

// MARK: - API shapes

nonisolated struct LivePage<Item: Decodable>: Decodable {
    let items: [Item]
}

nonisolated struct LiveCode: Decodable {
    var code: String? = nil
    var display: String? = nil
}

nonisolated struct LiveSource: Decodable {
    var organization: String? = nil
}

nonisolated struct LiveLab: Decodable {
    let code: LiveCode
    var category: String? = nil
}

nonisolated struct LiveLabSeries: Decodable {
    struct Point: Decodable {
        var value: JSONValue? = nil
        var effectiveAt: Date? = nil
    }
    let code: LiveCode
    var unit: String? = nil
    var rangeLow: Double? = nil
    var rangeHigh: Double? = nil
    let points: [Point]

    func labSeries(category: String?) -> LabSeries {
        let values = points.compactMap { point -> LabPoint? in
            guard case .number(let value) = point.value, let date = point.effectiveAt else { return nil }
            return LabPoint(date: date, value: value)
        }
        let band = rangeLow.flatMap { low in rangeHigh.map { low...$0 } }
        let name = code.display ?? code.code ?? "Result"
        return LabSeries(id: code.code ?? name, name: name, unit: unit ?? "", points: values, band: band,
                         bandLabel: band == nil ? nil : "Reference range", annotation: nil,
                         provenance: category == "vital-signs" ? "Vital signs · your health records" : "Lab result · your health records",
                         explainReading: "This is \(name) from your health records.",
                         explainNextStep: "Ask your care team what this result means for you.",
                         explainAsk: "What does my \(name) result mean?")
    }
}

nonisolated struct LiveMedication: Decodable {
    let id: String
    let code: LiveCode
    var doseText: String? = nil
    var prescriber: String? = nil
    var nextRefillDate: String? = nil
    var source: LiveSource? = nil

    var medication: Medication {
        let days = nextRefillDate.flatMap(LiveFormat.date).map { max(0, Calendar.current.dateComponents([.day], from: .now, to: $0).day ?? 0) }
        // With no refill date the supply is unknown; a large number keeps "running low" from firing on a guess.
        return Medication(id: id, name: code.display ?? "Medication", dose: doseText ?? "", purposeLine: prescriber.map { "Prescribed by \($0)" } ?? "",
                          scheduleLine: doseText ?? "", supplyDaysRemaining: days ?? 999, pharmacy: source?.organization ?? "",
                          guidance: [], watchlist: [], history: [], adherence30: [])
    }
}

nonisolated struct LiveCondition: Decodable {
    let code: LiveCode
    var clinicalStatus: String? = nil
    var onsetDate: String? = nil
    var source: LiveSource? = nil

    var item: RecordItem {
        RecordItem(category: .conditions, title: code.display ?? "Condition", detail: (clinicalStatus ?? "").capitalized,
                   date: onsetDate.flatMap(LiveFormat.date) ?? .distantPast, source: source?.organization ?? "Your health records")
    }
}

extension LiveCondition {
    var careCondition: CareCondition {
        let since = onsetDate.flatMap(LiveFormat.date).map { $0.formatted(.dateTime.month(.abbreviated).year()) } ?? "an unknown date"
        return CareCondition(name: code.display ?? "Condition", since: since, state: (clinicalStatus ?? "active").capitalized,
                             plainLine: "From \(source?.organization ?? "your health records").", glyph: "heart.text.square", accent: .sky)
    }
}

nonisolated struct LivePlan: Decodable {
    struct Goal: Decodable {
        var description: String? = nil
        var status: String? = nil
        var dueDate: String? = nil
    }
    struct Activity: Decodable {
        var description: String? = nil
        var status: String? = nil
    }
    let id: String
    var title: String? = nil
    var description: String? = nil
    var status: String? = nil
    var periodStart: String? = nil
    var author: String? = nil
    var source: LiveSource? = nil
    var goals: [Goal]? = nil
    var activities: [Activity]? = nil

    static let empty = CarePlan(author: "your care team", updated: "not yet",
                                intro: "Your health records have no care plan yet. When your care team adds one, it shows here.", goals: [])

    /// The app shows one plan, so every imported plan becomes part of it, active ones first.
    static func merge(_ plans: [LivePlan]) -> CarePlan? {
        guard !plans.isEmpty else { return nil }
        let ordered = plans.sorted { ($0.status == "active" ? 0 : 1, $1.periodStart ?? "") < ($1.status == "active" ? 0 : 1, $0.periodStart ?? "") }
        let accents: [AccentKey] = [.life, .sky, .warm, .gold, .rose]
        var goals: [CarePlanGoal] = []
        for plan in ordered {
            let from = plan.title ?? "Care plan"
            for goal in plan.goals ?? [] {
                goals.append(CarePlanGoal(title: goal.description ?? "Goal", detail: from, progressLine: (goal.status ?? "").replacingOccurrences(of: "_", with: " ").capitalized,
                                          accent: accents[goals.count % accents.count], provenance: plan.source?.organization))
            }
            for activity in plan.activities ?? [] {
                goals.append(CarePlanGoal(title: activity.description ?? "Step", detail: from, progressLine: (activity.status ?? "").replacingOccurrences(of: "_", with: " ").capitalized,
                                          accent: accents[goals.count % accents.count], provenance: plan.source?.organization))
            }
        }
        let first = ordered[0]
        let updated = first.periodStart.flatMap(LiveFormat.date)?.formatted(.dateTime.month(.abbreviated).day().year()) ?? "from your records"
        let intro = ordered.map { [$0.title, $0.description].compactMap { $0 }.joined(separator: ". ") }.filter { !$0.isEmpty }.joined(separator: "\n")
        return CarePlan(author: first.author ?? first.source?.organization ?? "your care team", updated: updated,
                        intro: intro.isEmpty ? "The care plans in your health records." : intro, goals: goals)
    }
}

nonisolated struct LiveImmunization: Decodable {
    var display: String? = nil
    var occurredAt: Date? = nil
    var status: String? = nil
    var source: LiveSource? = nil

    var item: RecordItem {
        RecordItem(category: .immunizations, title: display ?? "Immunization", detail: (status ?? "").capitalized,
                   date: occurredAt ?? .distantPast, source: source?.organization ?? "Your health records")
    }
}

nonisolated struct LiveProcedure: Decodable {
    var display: String? = nil
    var performedAt: Date? = nil
    var status: String? = nil
    var source: LiveSource? = nil

    var item: RecordItem {
        RecordItem(category: .procedures, title: display ?? "Procedure", detail: (status ?? "").capitalized,
                   date: performedAt ?? .distantPast, source: source?.organization ?? "Your health records")
    }
}

nonisolated struct LiveDocument: Decodable {
    var title: String? = nil
    var date: Date? = nil
    var type: String? = nil
    var source: LiveSource? = nil

    var item: RecordItem {
        RecordItem(category: .notes, title: title ?? type ?? "Clinical note", detail: type ?? "",
                   date: date ?? .distantPast, source: source?.organization ?? "Your health records")
    }
}

nonisolated struct LiveMember: Decodable {
    var name: String? = nil
    var role: String? = nil
    var organization: String? = nil
}

nonisolated struct LiveEncounter: Decodable {
    let id: String
    var type: String? = nil
    var startAt: Date? = nil
    var practitioner: String? = nil
    var organization: String? = nil

    var appointment: Appointment? {
        guard let startAt else { return nil }
        return Appointment(id: UUID(uuidString: id) ?? UUID(), with: practitioner ?? type ?? "Visit", date: startAt,
                           location: organization ?? "", prepReady: false, status: .visited, planGoalHint: type)
    }
}

nonisolated struct LiveAppointment: Decodable {
    let id: String
    var clinician: String? = nil
    var organization: String? = nil
    var location: String? = nil
    var kind: String? = nil
    var status: String? = nil
    var startsAt: Date? = nil
    var joinLink: String? = nil
    var reason: String? = nil

    var appointment: Appointment? {
        guard let startsAt else { return nil }
        return Appointment(id: UUID(uuidString: id) ?? UUID(), with: clinician ?? organization ?? "Visit", date: startsAt,
                           location: location ?? organization ?? "", prepReady: false,
                           kind: kind == "telehealth" ? .telehealth : .inPerson,
                           status: status == "cancelled" ? .cancelled : status == "pending" ? .pending : .confirmed,
                           joinLink: joinLink, planGoalHint: reason)
    }
}

nonisolated struct LiveCheckIn: Decodable {
    let date: String
    let outcome: String
    var note: String? = nil

    static func apiOutcome(_ outcome: HabitCheckIn.Outcome) -> String {
        switch outcome {
        case .kept: "kept"
        case .fallback: "fallback"
        case .blocked: "blocked"
        case .skipped: "skipped"
        }
    }
}

nonisolated struct LiveHabit: Decodable {
    let id: String
    let title: String
    var context: String? = nil
    var reason: String? = nil
    var cue: String? = nil
    var barrier: String? = nil
    var fallback: String? = nil
    var confidence: Int? = nil
    var pace: String? = nil
    var paused: Bool? = nil
    var thisWeek: [LiveCheckIn]? = nil

    func atomicHabit(checkIns: [LiveCheckIn]) -> AtomicHabit {
        let kept = checkIns.filter { ["kept", "fallback"].contains($0.outcome) }.compactMap { LiveFormat.date($0.date) }
        let support = HabitSupportPlan(reason: reason ?? "", cue: cue ?? "", barrier: barrier ?? "", fallback: fallback ?? "",
                                       confidence: confidence ?? 3, pace: pace == "steady" ? "Steady" : "Small steps", paused: paused ?? false)
        return AtomicHabit(id: UUID(uuidString: id) ?? UUID(), title: title, contextLine: context ?? cue ?? "", keptDates: kept, support: support)
    }

    static func body(title: String, support: HabitSupportPlan?, context: String) -> [String: Any] {
        var body: [String: Any] = ["title": title]
        if !context.isEmpty { body["context"] = context }
        guard let support else { return body }
        for (key, value) in [("reason", support.reason), ("cue", support.cue), ("barrier", support.barrier), ("fallback", support.fallback)] where !value.isEmpty {
            body[key] = value
        }
        body["confidence"] = max(1, min(5, support.confidence))
        body["pace"] = support.pace == "Steady" ? "steady" : "small_steps"
        return body
    }
}

nonisolated struct LiveJourney: Decodable {
    let id: String
    let title: String
    var why: String = ""
    var habits: [LiveHabit] = []
}

nonisolated struct LiveLog: Decodable {
    let id: String
    let kind: String
    let value: [String: JSONValue]
    let takenAt: Date
    var note: String? = nil

    var symptomLog: SymptomLog? {
        guard kind == "symptom", let name = value["name"]?.stringValue else { return nil }
        let severity = Double(value["severity"]?.intValue ?? 1) / 10
        let region = (value["bodyRegion"] ?? value["body_region"])?.stringValue
        return SymptomLog(id: UUID(uuidString: id) ?? UUID(), kind: name, severity: severity, at: takenAt, note: note, bodyRegion: region)
    }
}

extension LiveLog {
    func careEntry(medications: [Medication]) -> CareEntry? {
        let id = UUID(uuidString: self.id) ?? UUID()
        switch kind {
        case "meal":
            let text = value["description"]?.stringValue ?? "Meal"
            return CareEntry(id: id, kind: .meal, title: text.capitalizedFirst, detail: "Meal", at: takenAt,
                             imageName: LifeLibrary.matchMeal(text).imageName, note: note)
        case "activity":
            let text = value["description"]?.stringValue ?? "Activity"
            return CareEntry(id: id, kind: .move, title: text.capitalizedFirst, detail: "Felt good to move", at: takenAt,
                             imageName: LifeLibrary.matchMove(text).imageName, note: note)
        case "medication_taken":
            let medID = (value["medicationId"] ?? value["medication_id"])?.stringValue
            let med = medications.first { $0.id == medID }
            return CareEntry(id: id, kind: .med, title: med?.name ?? "Medication", detail: med?.dose ?? "Taken", at: takenAt,
                             imageName: LifeLibrary.medImage(for: medID ?? ""), note: note, linkedMedID: medID)
        default:
            return nil
        }
    }
}

nonisolated struct LiveExport: Decodable {
    let id: String
    let status: String
    var downloadUrl: String? = nil
}

enum LiveConsent {
    static let policyVersion = "2026-10"
    static let scopes: [(id: String, title: String, detail: String)] = [
        ("ai_chat", "Chat with Rumi", "Rumi's AI reads what you write and answers you."),
        ("ai_patient_facts", "Let Rumi remember about you", "Rumi keeps short notes about you between chats."),
        ("health_records", "Health records import", "Rumi imports and keeps records from the health systems you connect."),
        ("everyday_rhythms", "Everyday rhythms", "Rumi uses your logs and habits to time its check-ins."),
        ("outreach_sms", "Text messages", "Rumi may send you text messages."),
        ("outreach_call", "Phone calls", "Rumi may call you."),
    ]
}

nonisolated enum LiveFormat {
    static func date(_ text: String) -> Date? {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = "yyyy-MM-dd"
        return formatter.date(from: String(text.prefix(10)))
    }

    static func day(_ date: Date) -> String {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = "yyyy-MM-dd"
        return formatter.string(from: date)
    }

    static func number(_ value: Double) -> String {
        value.formatted(.number.precision(.fractionLength(0...2)))
    }
}
