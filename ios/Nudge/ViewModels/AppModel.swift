import SwiftUI
import Observation

/// Root app store — one data spine (§11.3). Every surface renders from here;
/// a value shown on Today, in the Hub, in Trends and in chat is the same value
/// with the same freshness stamp. The active persona shapes what lives inside
/// the world without changing the world itself.
@Observable final class AppModel {
    enum Tab: String, CaseIterable {
        case today = "Today"
        case care = "Care"
        case messages = "Messages"
        case you = "You"

        var glyph: String {
            switch self {
            case .today: return "sun.haze"
            case .care: return "cross.case"
            case .you: return "book.closed"
            case .messages: return "bubble.left.and.bubble.right"
            }
        }
    }

    // MARK: Navigation & shell
    var tab: Tab = .today
    var carePath: NavigationPath = NavigationPath()
    var messagesPath: NavigationPath = NavigationPath()
    var youPath: NavigationPath = NavigationPath()
    var youSection: YouView.Section = .story
    var messageDrafts: [String: String] = [:]
    var demoRecordImport: DemoRecordImport? = nil
    var visitPreps: [String: AppointmentPrep] = [:]
    var habitCheckIns: [HabitCheckIn] = []
    var workflows: [ReviewedWorkflow] = []
    var storageError: Bool = false

    // MARK: Account
    let api: RumiAPI

    func openYou(_ destination: YouDestination) {
        youPath = NavigationPath()
        youPath.append(destination)
        tab = .you
    }

    func appointment(withID id: UUID) -> Appointment? {
        appointments.first { $0.id == id }
    }
    /// The next actual upcoming, non-cancelled visit; never substitutes an old fixture.
    func nextAppointment(after date: Date) -> Appointment? {
        appointments.filter { $0.date >= date && $0.status != .cancelled }
            .min { $0.date < $1.date }
    }

    var showConversation = false
    var conversationSeed: String? = nil
    var showQuickLog = false
    /// Pre-linked medication when logging from a med surface.
    var quickLogMedID: String? = nil
    var showSettings = false
    var showRecap = false
    /// The agent-network overview (the family of helpers and what each is doing).
    var showAgentNetwork = false
    /// When opening the network straight to one agent's detail.
    var agentNetworkFocusID: String? = nil
    var justBloomedToday = false

    // MARK: Lifecycle
    var hasOnboarded: Bool {
        didSet { UserDefaults.standard.set(hasOnboarded, forKey: "nudge.hasOnboarded") }
    }
    /// When onboarding finished — drives the first-14-days holds (ENG-3, §4.10).
    var onboardedAt: Date {
        didSet { UserDefaults.standard.set(onboardedAt.timeIntervalSince1970, forKey: "nudge.onboardedAt") }
    }
    var daysSinceOnboarding: Int {
        max(0, Calendar.current.dateComponents([.day], from: onboardedAt, to: .now).day ?? 0)
    }
    /// Looking-ahead is suppressed by opt-out and in the first 14 days (PRD-5).
    var showsLookingAhead: Bool {
        !lookingAheadOptOut && daysSinceOnboarding >= 14 && lookingAhead != nil
    }

    // MARK: The person
    var profile: UserProfile {
        didSet { persistProfile() }
    }

    /// The name the world greets — the user's own when given.
    var displayFirstName: String {
        if isLive { return liveFirstName ?? api.user?.displayName.components(separatedBy: " ").first ?? "there" }
        return profile.firstName.isEmpty ? persona.firstName : profile.firstName
    }

    // MARK: Care pathway — the experience adapts to the condition
    private(set) var pathway: CarePathway
    private(set) var persona: Persona

    // MARK: Stores (persona fixture spine)
    var moments: [Moment]
    var insights: [Insight]
    var medications: [Medication]
    var journeys: [Journey]
    var programs: [Program]
    var logs: [SymptomLog] = []
    var currents: [CurrentsPiece]
    var labSeries: [LabSeries]
    var storyEvents: [StoryEvent]
    var careTeam: [CareTeamMember]
    var appointments: [Appointment]
    var guideItems: [GuideItem]
    var recordItems: [RecordItem]
    var sources: [RecordSource]
    var consents: [ConsentEntry]
    var memory: [MemoryItem]

    // MARK: Care hub (v5 §4.4) — the clinical action center's data spine
    var threads: [MessageThread]
    var bills: [Bill]
    var cost: CostSummary
    var careDocuments: [CareDocument]
    var savings: [MedicationSaving]
    var requests: [CareRequest]
    private(set) var resultToAck: (title: String, detail: String, series: String?)?
    private(set) var lookingAhead: LookingAheadNudge?
    /// Care-plan goals the user has turned into journeys (§4.4.5).
    var derivedJourneyGoals: Set<String> = []
    /// Whether the latest significant result has been acknowledged (REC-5).
    var resultAcknowledged = false
    /// Deep-link target when routing into Care from Today's "Needs you".
    var pendingCareDestination: CareDestination? = nil

    // MARK: Life log, agentic actions, held moments
    var entries: [CareEntry]
    var agentActions: [AgentAction]
    var memories: [MemoryGlimpse]

    // MARK: Agent network — wallet, connections, the agent family, reports
    var walletCards: [WalletCard]
    var connections: [Connection]
    var agentServices: [AgentService]
    /// The live work of the network — what each agent is doing, and what's
    /// waiting on one human tap (§ agentic differentiator).
    var agentTasks: [AgentTask]
    /// Which per-doctor reports have already been sent this session.
    var reportSentKeys: Set<String> = []

    // MARK: Preferences
    var tonePreference: String {
        didSet { UserDefaults.standard.set(tonePreference, forKey: "nudge.tone") }
    }
    var epsilonConsent: Bool {
        didSet { UserDefaults.standard.set(epsilonConsent, forKey: "nudge.epsilon") }
    }
    /// The looking-ahead opt-out (§4.10 PRD-6) — respected everywhere.
    var lookingAheadOptOut: Bool {
        didSet { UserDefaults.standard.set(lookingAheadOptOut, forKey: "nudge.lookingAheadOptOut") }
    }
    var eraWarmth: String {
        didSet { UserDefaults.standard.set(eraWarmth, forKey: "nudge.eraWarmth") }
    }
    var soundOn: Bool {
        didSet {
            UserDefaults.standard.set(soundOn, forKey: "nudge.sound")
            SoundEngine.shared.enabled = soundOn
        }
    }
    /// The music bed — its own switch, one tap from anywhere it plays.
    var musicOn: Bool {
        didSet {
            UserDefaults.standard.set(musicOn, forKey: "nudge.music")
            SoundEngine.shared.setMusicEnabled(musicOn)
        }
    }
    /// "Auto" follows the system; "Day" and "Night" pin a world.
    var appearance: String {
        didSet { UserDefaults.standard.set(appearance, forKey: "nudge.appearance") }
    }
    var quietStart: Int = 21
    var quietEnd: Int = 8
    var notificationClasses: [String: Bool] = [
        "Habit moments": true,
        "Insights": true,
        "Heads-ups": true,
        "Logistics": true,
        "Check-ins": true,
    ]

    var colorSchemeOverride: ColorScheme? {
        switch appearance {
        case "Day": return .light
        case "Night": return .dark
        default: return nil
        }
    }

    // MARK: Companion
    let orb = OrbState()
    let companion: CompanionEngine
    let aiRouter: RumiAIRouter
    let portal: RumiPortalDevice
    let records: HealthRecords
    var aiWorkspaces: [String: RumiChatWorkspace] = [:]
    /// The sample patient's own edits, kept aside while a signed-in patient's real data is showing.
    var sampleUserState: SampleUserState? = nil
    /// The signed-in patient still has to tell the API about themselves before chat opens.
    var needsAboutYou = false
    var liveConditions: [CareCondition]? = nil
    var liveCarePlan: CarePlan? = nil
    var liveFirstName: String? = nil

    /// Transient acknowledgment after a quick log — every log gets a response,
    /// never a mute database write.
    var quickLogAck: String? = nil

    private let storageDirectory: URL

    init(storageDirectory: URL = .documentsDirectory, aiRouter: RumiAIRouter? = nil) {
        let api = RumiAPI()
        self.api = api
        records = HealthRecords(api: api)
        let router = aiRouter ?? RumiAIRouter(api: api)
        self.aiRouter = router
        let portal = RumiPortalDevice()
        self.portal = portal
        router.device = portal
        companion = CompanionEngine(transport: router)
        self.storageDirectory = storageDirectory
        hasOnboarded = UserDefaults.standard.bool(forKey: "nudge.hasOnboarded")
        tonePreference = UserDefaults.standard.string(forKey: "nudge.tone") ?? "Straight talk"
        epsilonConsent = UserDefaults.standard.object(forKey: "nudge.epsilon") as? Bool ?? false
        eraWarmth = UserDefaults.standard.string(forKey: "nudge.eraWarmth") ?? "Subtle"
        soundOn = UserDefaults.standard.object(forKey: "nudge.sound") as? Bool ?? true
        musicOn = UserDefaults.standard.object(forKey: "nudge.music") as? Bool ?? false
        appearance = UserDefaults.standard.string(forKey: "nudge.appearance") ?? "Auto"
        lookingAheadOptOut = UserDefaults.standard.bool(forKey: "nudge.lookingAheadOptOut")
        let onboardedStamp = UserDefaults.standard.object(forKey: "nudge.onboardedAt") as? Double
        onboardedAt = onboardedStamp.map { Date(timeIntervalSince1970: $0) } ?? Date(timeIntervalSinceNow: -60 * 86_400)

        if let data = UserDefaults.standard.data(forKey: "nudge.profile"),
           let decoded = try? JSONDecoder().decode(UserProfile.self, from: data) {
            profile = decoded
        } else {
            profile = UserProfile()
        }

        let savedPathway = CarePathway(rawValue: UserDefaults.standard.string(forKey: "nudge.pathway") ?? "") ?? .metabolic
        pathway = savedPathway
        let activePersona = PersonaFixtures.persona(for: savedPathway)
        persona = activePersona

        insights = activePersona.insights
        moments = activePersona.moments
        medications = activePersona.medications
        journeys = activePersona.journeys
        currents = activePersona.currents
        labSeries = activePersona.labSeries
        storyEvents = activePersona.storyEvents
        careTeam = activePersona.careTeam
        let careBundle = CareHubFixtures.bundle(for: savedPathway)
        appointments = careBundle.appointments
        threads = careBundle.threads
        bills = careBundle.bills
        cost = careBundle.cost
        careDocuments = careBundle.documents
        savings = careBundle.savings
        requests = careBundle.requestsSeed
        resultToAck = careBundle.resultToAck
        lookingAhead = careBundle.lookingAhead
        resultAcknowledged = UserDefaults.standard.bool(forKey: "nudge.resultAck.\(savedPathway.rawValue)")
        guideItems = activePersona.guideSeed
        programs = MarcusFixtures.programs
        recordItems = savedPathway == .metabolic ? MarcusFixtures.recordItems : []
        sources = savedPathway == .metabolic ? MarcusFixtures.sources : []
        consents = MarcusFixtures.consents
        memory = MarcusFixtures.memory
        entries = Self.seedEntries(for: activePersona)
        agentActions = Self.seedActions(for: savedPathway)
        memories = Self.seedMemories(for: savedPathway)
        walletCards = AgentNetwork.wallet(for: savedPathway)
        connections = AgentNetwork.connections()
        agentServices = AgentNetwork.agentServices()
        agentTasks = AgentNetwork.agentTasks(for: savedPathway)

        // Everything the user has created comes back — the log, the guide,
        // the held moments, the remembered notes.
        if let saved = PersistenceService.load(pathway: savedPathway.rawValue, directory: storageDirectory) {
            entries = saved.entries
            logs = saved.logs
            memories = saved.memories
            guideItems = saved.guideItems
            memory = saved.memoryNotes
            threads = saved.threads
            requests = saved.requests
            careDocuments = saved.documents
            messageDrafts = saved.messageDrafts ?? [:]
            demoRecordImport = saved.demoRecordImport
            appointments = saved.appointments ?? appointments
            visitPreps = saved.visitPreps ?? [:]
            journeys = saved.journeys ?? journeys
            habitCheckIns = saved.habitCheckIns ?? []
            workflows = saved.workflows ?? []
            restoreAIWorkspace(from: saved)
            derivedJourneyGoals = Set(saved.derivedJourneyGoals)
            for billIndex in bills.indices where saved.paidBillKeys.contains(bills[billIndex].key) {
                bills[billIndex].status = .paid
            }
        }

        SoundEngine.shared.enabled = soundOn
        SoundEngine.shared.setMusicEnabled(musicOn)
        companion.configure(model: self)
    }

    /// Persists everything the user owns. Cheap enough to call on every write.
    @discardableResult
    func persistUserData() -> Bool {
        captureAIWorkspace()
        let saved = PersistenceService.save(SanoUserData(
            pathway: pathway.rawValue,
            entries: sampleUserState?.entries ?? entries,
            logs: sampleUserState?.logs ?? logs,
            memories: sampleUserState?.memories ?? memories,
            guideItems: guideItems,
            memoryNotes: memory,
            threads: sampleUserState?.threads ?? threads,
            requests: requests,
            documents: careDocuments,
            paidBillKeys: (sampleUserState?.bills ?? bills).filter { $0.status == .paid }.map(\.key),
            derivedJourneyGoals: Array(derivedJourneyGoals),
            messageDrafts: messageDrafts,
            demoRecordImport: demoRecordImport,
            appointments: sampleUserState?.appointments ?? appointments,
            visitPreps: visitPreps,
            journeys: sampleUserState?.journeys ?? journeys,
            habitCheckIns: sampleUserState?.habitCheckIns ?? habitCheckIns,
            workflows: workflows,
            aiWorkspaces: aiWorkspaces
        ), directory: storageDirectory)
        storageError = !saved
        return saved
    }

    private func persistProfile() {
        if let data = try? JSONEncoder().encode(profile) {
            UserDefaults.standard.set(data, forKey: "nudge.profile")
        }
    }

    // MARK: - Pathway switching (onboarding choice + Settings preview)

    func switchPathway(_ newPathway: CarePathway) {
        guard newPathway != pathway else { return }
        companion.endSession(orb: orb)
        guard persistUserData() else { return }
        companion.reset()
        aiRouter.suspend()
        aiRouter.clientID = UUID()
        aiWorkspaces = [:]
        demoRecordImport = nil
        visitPreps = [:]
        habitCheckIns = []
        workflows = []
        memory = []
        carePath = NavigationPath()
        messagesPath = NavigationPath()
        youPath = NavigationPath()
        pendingCareDestination = nil
        messageDrafts = [:]
        pathway = newPathway
        UserDefaults.standard.set(newPathway.rawValue, forKey: "nudge.pathway")
        let activePersona = PersonaFixtures.persona(for: newPathway)
        withAnimation(NudgeSpring.gentle) {
            persona = activePersona
            insights = activePersona.insights
            moments = activePersona.moments
            medications = activePersona.medications
            journeys = activePersona.journeys
            currents = activePersona.currents
            labSeries = activePersona.labSeries
            storyEvents = activePersona.storyEvents
            careTeam = activePersona.careTeam
            recordItems = newPathway == .metabolic ? MarcusFixtures.recordItems : []
            sources = newPathway == .metabolic ? MarcusFixtures.sources : []
            let careBundle = CareHubFixtures.bundle(for: newPathway)
            appointments = careBundle.appointments
            threads = careBundle.threads
            bills = careBundle.bills
            cost = careBundle.cost
            careDocuments = careBundle.documents
            savings = careBundle.savings
            requests = careBundle.requestsSeed
            resultToAck = careBundle.resultToAck
            lookingAhead = careBundle.lookingAhead
            derivedJourneyGoals = []
            resultAcknowledged = UserDefaults.standard.bool(forKey: "nudge.resultAck.\(newPathway.rawValue)")
            guideItems = activePersona.guideSeed
            logs = []
            entries = Self.seedEntries(for: activePersona)
            agentActions = Self.seedActions(for: newPathway)
            memories = Self.seedMemories(for: newPathway)
            walletCards = AgentNetwork.wallet(for: newPathway)
            connections = AgentNetwork.connections()
            agentServices = AgentNetwork.agentServices()
            agentTasks = AgentNetwork.agentTasks(for: newPathway)
            reportSentKeys = []
        }
        if let saved = PersistenceService.load(pathway: newPathway.rawValue, directory: storageDirectory) {
            entries = saved.entries
            logs = saved.logs
            memories = saved.memories
            guideItems = saved.guideItems
            memory = saved.memoryNotes
            threads = saved.threads
            requests = saved.requests
            careDocuments = saved.documents
            messageDrafts = saved.messageDrafts ?? [:]
            demoRecordImport = saved.demoRecordImport
            appointments = saved.appointments ?? appointments
            visitPreps = saved.visitPreps ?? [:]
            journeys = saved.journeys ?? journeys
            habitCheckIns = saved.habitCheckIns ?? []
            workflows = saved.workflows ?? []
            restoreAIWorkspace(from: saved)
            derivedJourneyGoals = Set(saved.derivedJourneyGoals)
            for index in bills.indices where saved.paidBillKeys.contains(bills[index].key) {
                bills[index].status = .paid
            }
        }
    }

    // MARK: - Actions

    func series(_ id: String) -> LabSeries? {
        labSeries.first { $0.id == id }
    }

    func dismissMoment(_ id: UUID) {
        moments.removeAll { $0.id == id }
    }

    func openConversation(seed: String? = nil) {
        conversationSeed = seed
        withAnimation(NudgeSpring.gentle) { showConversation = true }
        companion.openSession(seed: seed, orb: orb)
        conversationSeed = nil
    }

    func closeConversation() {
        persistUserData()
        withAnimation(NudgeSpring.gentle) { showConversation = false }
    }

    /// Keeping a habit — one tap, a soft bloom, never a counter.
    func keepHabit(journeyID: UUID, habitID: UUID) {
        guard let journeyIndex = journeys.firstIndex(where: { $0.id == journeyID }),
              let habitIndex = journeys[journeyIndex].habits.firstIndex(where: { $0.id == habitID })
        else { return }
        guard journeys[journeyIndex].habits[habitIndex].support?.paused != true,
              !keptToday(journeyID: journeyID, habitID: habitID) else { return }
        recordHabitCheckIn(journeyID: journeyID, habitID: habitID, outcome: .kept, note: "")
        orb.celebrate()
        Haptics.bloom()
        SoundEngine.shared.bloom()
    }

    func keptToday(journeyID: UUID, habitID: UUID) -> Bool {
        guard let journey = journeys.first(where: { $0.id == journeyID }),
              let habit = journey.habits.first(where: { $0.id == habitID })
        else { return false }
        return habit.keptDates.contains { Calendar.current.isDateInToday($0) }
    }

    // MARK: Life log — meals, moves, meds taken

    @discardableResult
    func addEntry(kind: CareEntry.Kind, text: String, note: String? = nil,
                  linkedMedID: String? = nil, at date: Date = .now) -> CareEntry {
        let entry: CareEntry
        switch kind {
        case .meal:
            let match = LifeLibrary.matchMeal(text)
            entry = CareEntry(kind: .meal, title: match.suggestedTitle.capitalizedFirst,
                              detail: mealSlot(for: date), at: date,
                              imageName: match.imageName, note: note)
        case .move:
            let match = LifeLibrary.matchMove(text)
            entry = CareEntry(kind: .move, title: match.suggestedTitle.capitalizedFirst,
                              detail: "Felt good to move", at: date,
                              imageName: match.imageName, note: note)
        case .med:
            let med = medications.first { $0.id == linkedMedID } ?? medications.first
            entry = CareEntry(kind: .med, title: med?.name ?? text.capitalizedFirst,
                              detail: med?.dose ?? "Taken", at: date,
                              imageName: LifeLibrary.medImage(for: med?.id ?? ""),
                              note: note, linkedMedID: med?.id)
        }
        withAnimation(NudgeSpring.ui) {
            entries.insert(entry, at: 0)
        }
        saveEntryLive(entry)
        Haptics.success()
        SoundEngine.shared.send()
        persistUserData()
        return entry
    }

    func removeEntry(_ id: UUID) {
        entries.removeAll { $0.id == id }
        persistUserData()
    }

    private func mealSlot(for date: Date) -> String {
        switch Calendar.current.component(.hour, from: date) {
        case 5..<11: return "Breakfast"
        case 11..<15: return "Lunch"
        case 15..<17: return "Afternoon"
        default: return "Dinner"
        }
    }

    // MARK: Agentic actions — the companion does things, with one human tap

    func workflowForAction(_ id: UUID) -> ReviewedWorkflow? {
        guard let action = agentActions.first(where: { $0.id == id }), action.state == .proposed else { return nil }
        let context = CareContext(id: "idea|\(action.title)", scenario: pathway.rawValue, title: action.title,
                                  source: "Illustrative task idea · not a live service", detail: action.detail,
                                  question: "Review this task idea.")
        let draft = workflowDraft(originID: action.id, title: action.title, detail: action.detail, context: context)
        saveWorkflow(draft)
        return storageError ? nil : draft
    }

    func declineAction(_ id: UUID) {
        guard let index = agentActions.firstIndex(where: { $0.id == id }) else { return }
        withAnimation(NudgeSpring.ui) { agentActions[index].state = .declined }
    }

    var pendingActions: [AgentAction] {
        agentActions.filter { $0.state == .proposed }
    }

    // MARK: Held moments — photos in glass

    func addMemory(photoFilename: String, caption: String) {
        withAnimation(NudgeSpring.delight) {
            memories.insert(MemoryGlimpse(photoFilename: photoFilename, caption: caption, date: .now), at: 0)
        }
        orb.celebrate()
        Haptics.bloom()
        SoundEngine.shared.bloom()
        persistUserData()
    }

    /// Saves a captured selfie into Documents; returns the filename.
    static func saveMemoryPhoto(_ data: Data) -> String? {
        let filename = "memory_\(UUID().uuidString).jpg"
        let url = URL.documentsDirectory.appendingPathComponent(filename)
        do {
            try data.write(to: url)
            return filename
        } catch {
            print("[Sano] memory photo save failed: \(error.localizedDescription)")
            return nil
        }
    }

    // MARK: Symptom logging — every log gets a real response

    @discardableResult
    func addLog(kind: String, severity: Double, note: String?,
                bodyRegion: String? = nil, linkedMedID: String? = nil) -> SupportPlan {
        let log = SymptomLog(
            kind: kind, severity: severity, at: .now,
            note: note?.isEmpty == true ? nil : note,
            bodyRegion: bodyRegion, linkedMedID: linkedMedID
        )
        logs.append(log)
        saveLogLive(log)
        persistUserData()
        return PersonaFixtures.supportPlan(pathway: pathway, kind: kind, severity: severity)
    }

    func logs(near medID: String) -> [SymptomLog] {
        logs.filter { $0.linkedMedID == medID }
    }

    // MARK: Discussion guide — the visit conversation, captured as it happens

    func addGuideItem(kind: GuideItem.Kind, text: String, from source: String) {
        guard !guideItems.contains(where: { $0.text == text }) else { return }
        withAnimation(NudgeSpring.ui) {
            guideItems.insert(GuideItem(kind: kind, text: text, addedFrom: source), at: 0)
        }
        Haptics.success()
        SoundEngine.shared.tick()
        persistUserData()
    }

    func toggleGuideResolved(_ id: UUID) {
        guard let index = guideItems.firstIndex(where: { $0.id == id }) else { return }
        guideItems[index].resolved.toggle()
        persistUserData()
    }

    func removeGuideItem(_ id: UUID) {
        guideItems.removeAll { $0.id == id }
        persistUserData()
    }

    /// Calls the care team's office — a real path out of the app.
    func callOffice() {
        let digits = persona.officePhone.filter(\.isNumber)
        guard let url = URL(string: "tel://\(digits)") else { return }
        UIApplication.shared.open(url)
    }

    // MARK: Insights

    func markInsightSeen(_ id: UUID) {
        guard let index = insights.firstIndex(where: { $0.id == id }) else { return }
        if insights[index].status == .fresh { insights[index].status = .seen }
    }

    func toggleInsightSaved(_ id: UUID) {
        guard let index = insights.firstIndex(where: { $0.id == id }) else { return }
        switch insights[index].status {
        case .saved: insights[index].status = .seen
        case .acted: break
        default: insights[index].status = .saved
        }
    }

    // MARK: Programs — accepted programs weave into the whole world

    func enroll(_ programID: UUID) {
        guard let index = programs.firstIndex(where: { $0.id == programID }) else { return }
        programs[index].enrolled = true
        programs[index].declined = false
        let program = programs[index]

        // The loop closes visibly (§11.3): the first step lands on Today,
        // a journey appears, and the companion starts working it.
        if moments.count < 3 {
            moments.append(Moment(
                kind: .checkIn,
                title: "Your program starts now",
                body: "\(program.title) — the first step is two minutes. I'll walk you in.",
                actionLabel: "Start"
            ))
        }
        let journey = Journey(
            title: program.title,
            why: program.personalFit,
            habits: [AtomicHabit(title: "Two minutes with the program",
                                 contextLine: "whenever today bends a little", keptDates: [])],
            gardenSeed: 57
        )
        journeys.append(journey)
        saveNewJourneyLive(journey)
        agentActions.insert(AgentAction(
            title: "Set up \(program.title)",
            detail: "I'll register you, sync the schedule, and keep the first week gentle.",
            outcomeLine: "You're set up — first step is on Today.",
            glyph: "sparkles", leavesDevice: true
        ), at: 0)
        memory.insert(MemoryItem(text: "Enrolled in \(program.title) — weave it in gently.",
                                 learnedFrom: "Programs · \(Date.now.formatted(.dateTime.month().day()))"), at: 0)
        orb.celebrate()
        Haptics.bloom()
        SoundEngine.shared.bloom()
    }

    /// Decline is one equal-weight tap, remembered. A declined program never
    /// re-surfaces in the same form within 90 days.
    func decline(_ programID: UUID) {
        guard let index = programs.firstIndex(where: { $0.id == programID }) else { return }
        programs[index].declined = true
    }

    func toggleCurrentSaved(_ id: UUID) {
        guard let index = currents.firstIndex(where: { $0.id == id }) else { return }
        currents[index].saved.toggle()
    }

    func setTaste(_ id: UUID, value: Int) {
        guard let index = currents.firstIndex(where: { $0.id == id }) else { return }
        currents[index].taste = currents[index].taste == value ? 0 : value
    }

    func deleteMemory(_ id: UUID) {
        memory.removeAll { $0.id == id }
        persistUserData()
    }

    func addMemoryNote(_ text: String, from source: String) {
        memory.insert(MemoryItem(text: text, learnedFrom: source), at: 0)
        Haptics.success()
        SoundEngine.shared.tick()
        persistUserData()
    }

    func completeOnboarding(values: String, barrier: String, tone: String) {
        tonePreference = tone
        if !values.isEmpty {
            memory.insert(MemoryItem(text: "What matters most: \(values)", learnedFrom: "Your setup preferences"), at: 0)
        }
        if !barrier.isEmpty {
            memory.insert(MemoryItem(text: "Hardest part: \(barrier)", learnedFrom: "Your setup preferences"), at: min(1, memory.count))
        }
        justBloomedToday = true
        onboardedAt = .now
        hasOnboarded = true
        persistUserData()
    }

    // MARK: - Care hub: the "Needs you" band (§3.2, TDY-3)

    /// Only the items that genuinely need the user right now. Empty when
    /// nothing is pending — never a blank, the surfaces show a reassuring line.
    var needsYou: [NeedsYouItem] {
        var items: [NeedsYouItem] = []
        for thread in threads where thread.unread {
            items.append(NeedsYouItem(kind: .message,
                title: "Reply from \(thread.memberName)",
                detail: thread.preview,
                destination: .thread(thread.id)))
        }
        if !isLive, !resultAcknowledged, let result = resultToAck {
            items.append(NeedsYouItem(kind: .result,
                title: "New result — \(result.title)",
                detail: result.detail,
                destination: .records))
        }
        for med in medications where med.supplyDaysRemaining <= 7 {
            items.append(NeedsYouItem(kind: .refill,
                title: "\(med.name) is running low",
                detail: "\(med.supplyDaysRemaining) days left at \(med.pharmacy)",
                destination: .medications))
        }
        for bill in bills where bill.status == .open {
            items.append(NeedsYouItem(kind: .bill,
                title: "A bill from \(bill.provider)",
                detail: "$\(Int(bill.amount)) · \(bill.encounter)",
                destination: .billDetail(bill.id)))
        }
        for appt in appointments where appt.status == .pending {
            items.append(NeedsYouItem(kind: .appointment,
                title: "Confirm: \(appt.with)",
                detail: appt.date.formatted(.dateTime.month().day().hour().minute()),
                destination: .appointmentDetail(appt.id)))
        }
        return items
    }

    /// Care-team attention worth a gentle indicator on Today and a dock badge:
    /// unread messages plus a freshly-landed result. Refills/bills/appointments
    /// already live in the "Needs you" band; this count is the "new from your
    /// care team" signal specifically.
    var messageUnreadCount: Int { threads.filter(\.unread).count }
    // The result to acknowledge is a sample-patient story; real records have no such flag yet.
    var recordUpdateCount: Int { (!isLive && !resultAcknowledged && resultToAck != nil) ? 1 : 0 }
    var careUnreadCount: Int { messageUnreadCount + recordUpdateCount }

    /// Routes into a specific Care surface (from Today's "Needs you").
    func openCare(_ destination: CareDestination) {
        pendingCareDestination = nil
        if destination.isMessaging {
            messagesPath = NavigationPath()
            if destination != .messages { messagesPath.append(destination) }
            tab = .messages
        } else {
            carePath = NavigationPath()
            carePath.append(destination)
            tab = .care
        }
    }

    // MARK: - Care hub actions (every consequential step is user-confirmed, §2.2)

    func markThreadRead(_ id: UUID) {
        guard let index = threads.firstIndex(where: { $0.id == id }), threads[index].unread else { return }
        threads[index].unread = false
        persistUserData()
    }

    func updateMessageDraft(threadID: UUID, text: String) {
        guard threads.contains(where: { $0.id == threadID }) else { return }
        messageDrafts[threadID.uuidString] = text.isEmpty ? nil : text
        persistUserData()
    }

    /// Sends a message in a thread — only ever after explicit confirmation in
    /// the compose UI. The standing guarantee: nothing sends without you (MSG-3).
    func sendMessage(threadID: UUID, text: String, origin: String? = nil, attachment: String? = nil) {
        guard let index = threads.firstIndex(where: { $0.id == threadID }) else { return }
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        let mode = threads[index].mode
        threads[index].messages.append(CareMessage(
            author: .user, text: trimmed, at: .now,
            state: mode == .inApp ? .sent : .draft, origin: origin, attachment: attachment))
        Haptics.success()
        SoundEngine.shared.send()
        persistUserData()
    }

    /// Starts a fresh thread with a care-team member, message already composed
    /// and confirmed. Used by the companion's draft-a-note flow and Requests.
    @discardableResult
    func startThread(practice: String, member: String, role: String,
                     mode: MessageChannelMode, category: MessageCategory,
                     text: String, origin: String? = nil) -> UUID {
        let thread = MessageThread(
            practice: practice, memberName: member, memberRole: role,
            mode: mode, category: category,
            messages: [CareMessage(author: .user, text: text, at: .now,
                                   state: mode == .inApp ? .sent : .draft, origin: origin)])
        threads.insert(thread, at: 0)
        Haptics.success()
        SoundEngine.shared.send()
        persistUserData()
        return thread.id
    }

    func submitRequest(kind: RequestKind, subject: String, detail: String, routedTo: String) {
        requests.insert(CareRequest(kind: kind, subject: subject, detail: detail, routedTo: routedTo), at: 0)
        Haptics.success()
        SoundEngine.shared.send()
        persistUserData()
    }

    func acknowledgeResult() {
        resultAcknowledged = true
        UserDefaults.standard.set(true, forKey: "nudge.resultAck.\(pathway.rawValue)")
        Haptics.tick()
    }

    // MARK: - Agent network: reports, wallet, connections, the agent family

    /// Builds a tailored, cross-referenced report per doctor over a window.
    func reports(rangeDays: Int) -> [DoctorReport] {
        AgentNetwork.reports(persona: persona, careTeam: careTeam, labSeries: labSeries,
                             medications: medications, logs: logs, guideItems: guideItems,
                             entries: entries, rangeDays: rangeDays)
    }

    func reportSent(_ report: DoctorReport) -> Bool { reportSentKeys.contains(report.id) }

    /// Sends a per-doctor summary — only ever after the user reviews and approves.
    func sendReport(_ report: DoctorReport) {
        reportSentKeys.insert(report.id)
        storyEvents.insert(StoryEvent(kind: .companion, date: .now,
            title: "Summary sent to \(report.doctorName)",
            detail: "Your \(report.title.lowercased()) is in their hands before the visit."), at: 0)
        // The send is an agentic action: the Care-pathway agent carries it to
        // the office, and the work shows up in the network's record.
        agentTasks.removeAll { $0.id == "report-\(report.id)" }
        agentTasks.insert(AgentTask(
            id: "report-\(report.id)", agentID: "pathway",
            title: "Delivered your \(report.title.lowercased()) to \(report.org)",
            detail: "Sent \(report.doctorName) the summary, with the rest of your team cross-referenced so everyone shares one picture.",
            mode: .automatic, status: .done,
            sources: [AgentSource("Your record"), AgentSource(report.org)],
            cadence: "Just now",
            outcomeLine: "In \(report.doctorName)'s hands before you arrive."), at: 0)
        quickLogAck = "Sent to \(report.doctorName) — they'll have it before you arrive."
        orb.celebrate(); Haptics.bloom(); SoundEngine.shared.bloom()
        Task {
            try? await Task.sleep(for: .seconds(5))
            if quickLogAck?.contains(report.doctorName) == true { quickLogAck = nil }
        }
    }

    /// Pays a bill from a chosen card — the agentic path, with one human tap.
    func payBill(_ billID: UUID, with card: WalletCard) {
        guard let index = bills.firstIndex(where: { $0.id == billID }) else { return }
        bills[index].status = .paid
        let bill = bills[index]
        storyEvents.insert(StoryEvent(kind: .companion, date: .now,
            title: "Paid \(bill.provider)",
            detail: "$\(Int(bill.amount)) from your \(card.name) — done and filed."), at: 0)
        quickLogAck = "Paid $\(Int(bill.amount)) to \(bill.provider) from your \(card.name)."
        Haptics.bloom(); SoundEngine.shared.bloom()
        persistUserData()
        Task {
            try? await Task.sleep(for: .seconds(5))
            if quickLogAck?.contains(bill.provider) == true { quickLogAck = nil }
        }
    }

    func toggleConnection(_ id: String) {
        guard let index = connections.firstIndex(where: { $0.id == id }) else { return }
        withAnimation(NudgeSpring.ui) { connections[index].connected.toggle() }
        if connections[index].connected {
            connections[index].accountLine = Self.sampleAccount(for: id, name: displayFirstName)
            Haptics.bloom(); SoundEngine.shared.bloom()
        } else {
            connections[index].accountLine = nil
            Haptics.tick()
        }
    }

    func toggleAgentService(_ id: String) {
        guard let index = agentServices.firstIndex(where: { $0.id == id }) else { return }
        withAnimation(NudgeSpring.ui) { agentServices[index].active.toggle() }
        Haptics.tick()
    }

    // MARK: Agent activity — each helper's real work, surfaced not hidden

    func tasks(forAgent id: String) -> [AgentTask] {
        agentTasks.filter { $0.agentID == id }
    }

    /// Things genuinely waiting on one human tap — surfaced on Today.
    var agentTasksWaiting: [AgentTask] {
        agentServices.contains(where: { !$0.active })
            ? agentTasks.filter { $0.status == .waiting && isAgentActive($0.agentID) }
            : agentTasks.filter { $0.status == .waiting }
    }

    /// Quiet automatic work in motion right now — the machine, humming.
    var agentTasksInMotion: [AgentTask] {
        agentTasks.filter { ($0.status == .working || $0.status == .scheduled) && isAgentActive($0.agentID) }
    }

    private func isAgentActive(_ agentID: String) -> Bool {
        agentServices.first(where: { $0.id == agentID })?.active ?? true
    }

    /// Count of live work for one agent (for the network tiles' status line).
    func activeTaskCount(forAgent id: String) -> Int {
        agentTasks.filter { $0.agentID == id && ($0.status == .working || $0.status == .waiting || $0.status == .scheduled) }.count
    }

    func waitingCount(forAgent id: String) -> Int {
        agentTasks.filter { $0.agentID == id && $0.status == .waiting }.count
    }

    /// A demonstration proposal can become reviewable work, never an external success.
    func workflowForAgentTask(_ id: String) -> ReviewedWorkflow? {
        guard let task = agentTasks.first(where: { $0.id == id }), task.status == .waiting,
              agentServices.first(where: { $0.id == task.agentID })?.active == true else { return nil }
        if let existing = workflows.first(where: { $0.agentTaskID == id }) { return existing }
        let context = CareContext(id: task.id, scenario: pathway.rawValue, title: task.title,
                                  source: "Demonstration proposal · not live monitoring",
                                  detail: task.detail + "\nIllustrative source labels: " + task.sources.map(\.label).joined(separator: ", "),
                                  question: "Review this proposed task.")
        let draft = ReviewedWorkflow(originID: UUID(), title: task.title, detail: task.detail,
                                     context: context, agentTaskID: task.id)
        saveWorkflow(draft)
        return storageError ? nil : draft
    }

    func declineAgentTask(_ id: String) {
        if let index = workflows.firstIndex(where: { $0.agentTaskID == id }) {
            workflows[index].status = .declined
            workflows[index].reviewedAt = nil
            persistUserData()
        } else {
            withAnimation(NudgeSpring.ui) { agentTasks.removeAll { $0.id == id } }
        }
        Haptics.tick()
    }

    /// Opens the agent network, optionally straight into one agent's detail.
    func openAgentNetwork(focus agentID: String? = nil) {
        agentNetworkFocusID = agentID
        showAgentNetwork = true
    }

    private static func sampleAccount(for id: String, name: String) -> String {
        let handle = name.lowercased()
        switch id {
        case "gmail", "gcal": return "\(handle)@gmail.com"
        case "imessage": return "Apple ID · \(handle)"
        case "sms": return "(404) 555-0149"
        case "instagram": return "@\(handle)_atl"
        default: return "Connected"
        }
    }

    // Appointments (§4.4.2)

    func confirmAppointment(_ id: UUID) {
        guard let index = appointments.firstIndex(where: { $0.id == id }) else { return }
        appointments[index].status = .confirmed
        // The scheduling agent owns the follow-through — its work is now visible.
        agentTasks.removeAll { $0.id == "appt-\(id.uuidString)" }
        agentTasks.insert(AgentTask(
            id: "appt-\(id.uuidString)", agentID: "scheduling",
            title: "Confirmed \(appointments[index].with)",
            detail: "Demo confirmation saved locally. No office or calendar was contacted.",
            mode: .automatic, status: .done,
            sources: [AgentSource("Google Calendar", "gcal")],
            cadence: "Just now",
            outcomeLine: "Demo confirmation · not a real booking"), at: 0)
        persistUserData()
        Haptics.success()
        SoundEngine.shared.bloom()
    }

    func rescheduleAppointment(_ id: UUID, to date: Date) {
        guard let index = appointments.firstIndex(where: { $0.id == id }) else { return }
        appointments[index].date = date
        appointments[index].status = .confirmed
        appointments[index].trip = nil
        visitPreps[id.uuidString]?.invalidateReview()
        persistUserData()
        appointments.sort { $0.date < $1.date }
        Haptics.success()
        SoundEngine.shared.bloom()
    }

    @discardableResult
    func bookAppointment(with: String, date: Date, location: String,
                         kind: AppointmentKind = .inPerson) -> Appointment {
        let appt = Appointment(with: with, date: date, location: location,
                               prepReady: false, kind: kind, status: .confirmed)
        appointments.append(appt)
        persistUserData()
        appointments.sort { $0.date < $1.date }
        Haptics.success()
        SoundEngine.shared.bloom()
        return appt
    }

    /// Telehealth join unlocks only inside a sensible pre-window (APT-6).
    func canJoin(_ appt: Appointment) -> Bool {
        guard appt.kind == .telehealth, appt.joinLink != nil else { return false }
        let minutes = Calendar.current.dateComponents([.minute], from: .now, to: appt.date).minute ?? 9_999
        return minutes <= 15 && minutes >= -90
    }

    // Bills — the app prepares and routes; the user authorizes payment (BILL-4)

    func markBillPaid(_ id: UUID) {
        guard let index = bills.firstIndex(where: { $0.id == id }) else { return }
        bills[index].status = .paid
        Haptics.bloom()
        SoundEngine.shared.bloom()
        persistUserData()
    }

    var openBillsTotal: Double { bills.filter { $0.status == .open }.map(\.amount).reduce(0, +) }

    // Documents — extraction is confirmed before it touches the record (DOC-4)

    func addDocument(_ document: CareDocument) {
        careDocuments.insert(document, at: 0)
        Haptics.success()
        SoundEngine.shared.send()
        persistUserData()
    }

    func confirmDocument(_ id: UUID) {
        guard let index = careDocuments.firstIndex(where: { $0.id == id }) else { return }
        careDocuments[index].confirmed = true
        persistUserData()
    }

    func removeDocument(_ id: UUID) {
        careDocuments.removeAll { $0.id == id }
        persistUserData()
    }

    // Savings — applying submits PII only after an explicit confirm (SAV-3)

    func applySaving(_ id: UUID) {
        guard let index = savings.firstIndex(where: { $0.id == id }) else { return }
        savings[index].applied = true
        Haptics.bloom()
        SoundEngine.shared.bloom()
    }

    func savings(for medID: String) -> [MedicationSaving] {
        savings.filter { $0.medID == medID }
    }

    // Care plan → action (§4.4.5) — opt-in, user-confirmed, removable

    func hasDerivedJourney(for goalTitle: String) -> Bool {
        derivedJourneyGoals.contains(goalTitle)
    }

    func deriveJourney(from goal: CarePlanGoal) {
        guard !derivedJourneyGoals.contains(goal.title) else { return }
        derivedJourneyGoals.insert(goal.title)
        let habit = AtomicHabit(title: behavioralHabit(for: goal),
                                contextLine: "a tiny version, built around your day", keptDates: [])
        let journey = Journey(title: goal.title, why: goal.detail, habits: [habit], gardenSeed: Int.random(in: 5...60), planGoal: goal.title)
        saveNewJourneyLive(journey)
        withAnimation(NudgeSpring.delight) {
            journeys.append(journey)
        }
        orb.celebrate()
        Haptics.bloom()
        SoundEngine.shared.bloom()
        persistUserData()
    }

    /// The derivation is suggestive and behavioral — it never restates or
    /// implies a medical instruction the physician did not give (ACT-2).
    private func behavioralHabit(for goal: CarePlanGoal) -> String {
        let lower = goal.title.lowercased()
        if lower.contains("walk") || lower.contains("move") || lower.contains("evening") { return "A few minutes of movement" }
        if lower.contains("bp") || lower.contains("pressure") { return "A quick morning reading" }
        if lower.contains("water") || lower.contains("hydrat") { return "Refill the water bottle" }
        if lower.contains("prehab") || lower.contains("strong") { return "Today's prehab set" }
        if lower.contains("nausea") { return "The on-schedule dose reminder" }
        return "One small step toward this"
    }

    // MARK: - Seeds

    private static func seedEntries(for persona: Persona) -> [CareEntry] {
        let cal = Calendar.current
        func at(_ daysAgo: Int, _ hour: Int, _ minute: Int = 0) -> Date {
            cal.date(bySettingHour: hour, minute: minute, second: 0,
                     of: cal.date(byAdding: .day, value: -daysAgo, to: .now) ?? .now) ?? .now
        }
        var seeded: [CareEntry] = []

        // A realistic, vegetarian-forward week-and-a-half of meals across
        // breakfast, lunch, dinner and snacks. (daysAgo, hour, minute, title, slot, image)
        let meals: [(Int, Int, Int, String, String, String)] = [
            (0, 8, 5, "Oatmeal & berries", "Breakfast", "oatmeal_bowl_blueberries"),
            (0, 12, 40, "Chickpea curry & rice", "Lunch", "lentil_soup_bowl"),
            (0, 19, 0, "Tofu & veg stir-fry", "Dinner", "grain_bowl_chicken_quinoa"),
            (1, 8, 0, "Veggie omelette", "Breakfast", "vegetable_omelette_plate"),
            (1, 13, 0, "Greek salad bowl", "Lunch", "grilled_salmon_lemon_greens"),
            (1, 15, 30, "Berry smoothie", "Snack", "yogurt_parfait_glass"),
            (1, 18, 30, "Lentil soup", "Dinner", "lentil_soup_bowl"),
            (2, 8, 10, "Avocado toast", "Breakfast", "vegetable_omelette_plate"),
            (2, 12, 30, "Quinoa grain bowl", "Lunch", "grain_bowl_chicken_quinoa"),
            (2, 15, 30, "Yogurt parfait", "Afternoon", "yogurt_parfait_glass"),
            (2, 18, 45, "Salmon & greens", "Dinner", "grilled_salmon_lemon_greens"),
            (3, 8, 0, "Overnight oats", "Breakfast", "oatmeal_bowl_blueberries"),
            (3, 13, 0, "Hummus mezze plate", "Lunch", "grain_bowl_chicken_quinoa"),
            (3, 19, 0, "Minestrone & bread", "Dinner", "lentil_soup_bowl"),
            (4, 8, 15, "Tofu scramble", "Breakfast", "vegetable_omelette_plate"),
            (4, 12, 45, "Veggie pasta", "Lunch", "grain_bowl_chicken_quinoa"),
            (4, 18, 30, "Paneer tikka & rice", "Dinner", "grain_bowl_chicken_quinoa"),
            (5, 8, 0, "Granola & yogurt", "Breakfast", "yogurt_parfait_glass"),
            (5, 13, 0, "Caprese salad", "Lunch", "grilled_salmon_lemon_greens"),
            (5, 19, 0, "Dal & brown rice", "Dinner", "lentil_soup_bowl"),
            (6, 8, 10, "Oatmeal & berries", "Breakfast", "oatmeal_bowl_blueberries"),
            (6, 12, 30, "Falafel wrap", "Lunch", "grain_bowl_chicken_quinoa"),
            (6, 18, 45, "Veggie chili", "Dinner", "lentil_soup_bowl"),
            (7, 8, 0, "Veggie omelette", "Breakfast", "vegetable_omelette_plate"),
            (7, 13, 0, "Buddha bowl", "Lunch", "grain_bowl_chicken_quinoa"),
            (7, 19, 0, "Grilled salmon", "Dinner", "grilled_salmon_lemon_greens"),
            (8, 8, 5, "Berry smoothie", "Breakfast", "yogurt_parfait_glass"),
            (8, 12, 40, "Lentil soup", "Lunch", "lentil_soup_bowl"),
            (8, 18, 30, "Tofu stir-fry", "Dinner", "grain_bowl_chicken_quinoa"),
            (9, 8, 0, "Overnight oats", "Breakfast", "oatmeal_bowl_blueberries"),
            (9, 13, 0, "Chickpea salad", "Lunch", "grilled_salmon_lemon_greens"),
            (9, 19, 0, "Vegetable curry", "Dinner", "lentil_soup_bowl"),
        ]
        for m in meals {
            seeded.append(CareEntry(kind: .meal, title: m.3, detail: m.4,
                                    at: at(m.0, m.1, m.2), imageName: m.5))
        }

        // Moves — walks, stretch, strength and garden time across the week.
        let stretchTitle = persona.pathway == .procedure ? "Quad sets & walk" : "Stretch & breathe"
        let stretchImage = persona.pathway == .procedure ? "dumbbells_towel_wellness" : "yoga_mat_rolled"
        let moves: [(Int, Int, Int, String, String, String)] = [
            (0, 20, 0, "Evening walk", "Felt good to move", "terracotta_cream_sneakers"),
            (1, 19, 10, "Evening walk", "After the game", "terracotta_cream_sneakers"),
            (2, 9, 0, stretchTitle, "Felt good to move", stretchImage),
            (3, 18, 30, "Strength work", "Steady sets", "dumbbells_towel_wellness"),
            (4, 7, 30, "Morning yoga", "Breath first", "yoga_mat_rolled"),
            (5, 20, 0, "Walk with DeShawn", "Two laps of the block", "terracotta_cream_sneakers"),
            (6, 16, 0, "Garden time", "Hands in the dirt", "soft_editorial_studio"),
            (7, 19, 30, "Evening walk", "Felt good to move", "terracotta_cream_sneakers"),
            (8, 7, 30, "Stretch & breathe", "Easy morning", "yoga_mat_rolled"),
            (9, 20, 0, "Evening walk", "Quiet night loop", "terracotta_cream_sneakers"),
        ]
        for mv in moves {
            seeded.append(CareEntry(kind: .move, title: mv.3, detail: mv.4,
                                    at: at(mv.0, mv.1, mv.2), imageName: mv.5))
        }

        // Meds — the first med most mornings, the second every other day.
        for daysAgo in 0...9 {
            if let firstMed = persona.medications.first {
                seeded.append(CareEntry(kind: .med, title: firstMed.name, detail: firstMed.dose,
                                        at: at(daysAgo, 8, 15), imageName: LifeLibrary.medImage(for: firstMed.id),
                                        linkedMedID: firstMed.id))
            }
            if persona.medications.count > 1, daysAgo % 2 == 0 {
                let med = persona.medications[1]
                seeded.append(CareEntry(kind: .med, title: med.name, detail: med.dose,
                                        at: at(daysAgo, 8, 18), imageName: LifeLibrary.medImage(for: med.id),
                                        linkedMedID: med.id))
            }
        }

        return seeded.sorted { $0.at > $1.at }
    }

    private static func seedActions(for pathway: CarePathway) -> [AgentAction] {
        switch pathway {
        case .metabolic:
            return [
                AgentAction(title: "Flip Thursday's refill to delivery",
                            detail: "Atorvastatin is ready at CVS Peachtree. I can switch it to free delivery so it just arrives.",
                            outcomeLine: "Done — delivery lands Thursday afternoon.",
                            glyph: "shippingbox", leavesDevice: true),
                AgentAction(title: "Send your BP week to Dr. Patterson",
                            detail: "Seven steady mornings, charted and worded the way clinics like — ahead of June 24.",
                            outcomeLine: "Sent — it'll be in your chart before the visit.",
                            glyph: "paperplane", leavesDevice: true),
            ]
        case .oncology:
            return [
                AgentAction(title: "Pre-fill cycle 4's anti-nausea schedule",
                            detail: "Same rhythm that made cycle 3 your smoothest — ready for Dr. Rivera's sign-off.",
                            outcomeLine: "Drafted and queued for the team's sign-off.",
                            glyph: "calendar.badge.checkmark", leavesDevice: true),
                AgentAction(title: "Send the tingling log before July 6",
                            detail: "Your fingertip notes since cycle 2, mapped — exactly what dosing decisions need.",
                            outcomeLine: "Sent — Dr. Rivera will see it before your visit.",
                            glyph: "paperplane", leavesDevice: true),
            ]
        case .procedure:
            return [
                AgentAction(title: "Set the NSAID stop reminder",
                            detail: "A gentle nudge the evening of June 15 — ibuprofen and friends stop the 16th.",
                            outcomeLine: "Set — I'll catch you the evening of the 15th.",
                            glyph: "bell.badge", leavesDevice: false),
                AgentAction(title: "Send your pain trend to Dr. Chen",
                            detail: "Two points lower on prehab days — worth showing at Tuesday's pre-op.",
                            outcomeLine: "Sent — it's on the pre-op summary now.",
                            glyph: "paperplane", leavesDevice: true),
            ]
        case .cardiometabolic:
            return [
                AgentAction(title: "Renew empagliflozin before it gaps",
                            detail: "Six days left. It guards your heart and kidneys both — I can renew it at your pharmacy so the cover never lapses.",
                            outcomeLine: "Renewed — no gap in the protection.",
                            glyph: "pills", leavesDevice: true),
                AgentAction(title: "Send your weight-and-BP week to Dr. Reyes",
                            detail: "Seven days of morning weights and pressures, charted the way cardiology likes — ahead of your visit.",
                            outcomeLine: "Sent — it'll be in your chart before the visit.",
                            glyph: "paperplane", leavesDevice: true),
            ]
        }
    }

    private static func seedMemories(for pathway: CarePathway) -> [MemoryGlimpse] {
        let cal = Calendar.current
        func ago(_ days: Int) -> Date { cal.date(byAdding: .day, value: -days, to: .now) ?? .now }
        switch pathway {
        case .metabolic:
            return [
                MemoryGlimpse(imageName: "tree_path_sunset_walk", caption: "The walk that started it all", date: ago(12)),
                MemoryGlimpse(imageName: "cozy_dinner_table", caption: "Sunday dinner, done right", date: ago(5)),
                MemoryGlimpse(imageName: "recap_garden", caption: "First tomato of the season", date: ago(2)),
            ]
        case .oncology:
            return [
                MemoryGlimpse(imageName: "recap_garden", caption: "Good-window morning in the garden", date: ago(8)),
                MemoryGlimpse(imageName: "cozy_dinner_table", caption: "Halfway dinner with the girls", date: ago(4)),
                MemoryGlimpse(imageName: "tree_path_sunset_walk", caption: "Ten gentle minutes, day 12", date: ago(2)),
            ]
        case .procedure:
            return [
                MemoryGlimpse(imageName: "tree_path_sunset_walk", caption: "The path waiting for the new knee", date: ago(6)),
                MemoryGlimpse(imageName: "cozy_dinner_table", caption: "Carb-loading, allegedly", date: ago(3)),
                MemoryGlimpse(imageName: "recap_garden", caption: "Prehab garden break", date: ago(1)),
            ]
        case .cardiometabolic:
            return [
                MemoryGlimpse(imageName: "tree_path_sunset_walk", caption: "A good-breath morning walk", date: ago(9)),
                MemoryGlimpse(imageName: "cozy_dinner_table", caption: "Low-sodium, still Sunday", date: ago(4)),
                MemoryGlimpse(imageName: "recap_garden", caption: "Slow morning in the garden", date: ago(2)),
            ]
        }
    }
}

extension String {
    var capitalizedFirst: String {
        guard let first = first else { return self }
        return first.uppercased() + dropFirst()
    }
}
