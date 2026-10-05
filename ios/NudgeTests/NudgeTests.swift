import Foundation
import SwiftUI
import Testing
@testable import Nudge

@Suite(.serialized)
@MainActor
struct NudgeTests {
    @Test func preparingContextDoesNotSendOrOverwriteDraft() {
        let engine = CompanionEngine(transport: HeldChatTransport())
        engine.setDraft("Keep my own words")
        let selected = CareContext(id: "selected", scenario: "metabolic", title: "Selected result", source: "Sample source", detail: "Dated evidence", question: "Suggested question")
        engine.prepare(context: selected)
        #expect(engine.composerDraft == "Keep my own words")
        #expect(engine.pendingContext == selected)
        #expect(engine.turns.isEmpty && !engine.isThinking)
        engine.removeContext()
        #expect(engine.pendingContext == nil && engine.composerDraft == "Keep my own words")
        engine.reset()
    }

    @Test func switchingContextUpdatesUntouchedQuestionButProtectsEditedWords() {
        let engine = CompanionEngine(transport: HeldChatTransport())
        let first = CareContext(id: "a", scenario: "metabolic", title: "A", source: "Sample", detail: "A", question: "Question A")
        let second = CareContext(id: "b", scenario: "metabolic", title: "B", source: "Sample", detail: "B", question: "Question B")
        engine.prepare(context: first)
        engine.prepare(context: second)
        #expect(engine.composerDraft == "Question B" && engine.pendingContext == second)
        engine.setDraft("My edited question B")
        engine.prepare(context: first)
        #expect(engine.pendingContext == second && engine.replacementContext == first)
        #expect(engine.composerDraft == "My edited question B")
        engine.replaceDraftAndContext()
        #expect(engine.pendingContext == first && engine.composerDraft == "Question A")
        engine.reset()
    }

    @Test func sourceEntryReopensEditedDraftWithNewViewIdentity() throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        let model = AppModel(storageDirectory: directory)
        let context = CareContext(id: "stable-med", scenario: model.pathway.rawValue, title: "Selected medicine", source: "Sample", detail: "Details", question: "Question")
        var draft = model.workflowDraft(originID: UUID(), title: "Refill question", detail: "Original", context: context)
        draft.edit(detail: "Patient edited words", recipient: "Selected team")
        model.saveWorkflow(draft)
        let reopened = model.workflowDraft(originID: UUID(), title: "Refill question", detail: "Original", context: context)
        #expect(reopened.id == draft.id && reopened.detail == "Patient edited words")
    }

    @Test func contextualTurnAndPendingDraftRoundTrip() throws {
        let context = CareContext(id: "medication-b", scenario: "metabolic", title: "Selected medication", source: "Sample list", detail: "No known dispense date", question: "A question")
        var turn = ConversationTurn(role: .user, text: "Please explain")
        turn.context = context
        let snapshot = SanoUserData(pathway: "metabolic", conversation: [turn], composerDraft: "Unsent", pendingCareContext: context)
        let decoded = try JSONDecoder().decode(SanoUserData.self, from: JSONEncoder().encode(snapshot))
        #expect(decoded.conversation?.first?.context == context)
        let engine = CompanionEngine(transport: HeldChatTransport())
        engine.restore(turns: decoded.conversation ?? [], draft: decoded.composerDraft ?? "", context: decoded.pendingCareContext)
        #expect(engine.pendingContext?.id == "medication-b")
        engine.reset()
        #expect(engine.pendingContext == nil)
    }

    @Test func selectedContextReachesTransportWithoutChangingTheSnapshot() async throws {
        let transport = HeldChatTransport()
        let engine = CompanionEngine(transport: transport)
        let context = CareContext(id: "result-b", scenario: "metabolic", title: "Only this result", source: "Source B", detail: "Value B", question: "Explain")
        engine.prepare(context: context)
        engine.send("My question", orb: OrbState())
        try await transport.waitForCallCount(1)
        #expect(transport.receivedMessages.first?.last?.content.contains("Value B") == true)
        #expect(engine.turns.first?.context == context)
        #expect(engine.pendingContext == nil)
        transport.finish(index: 0, text: "A response")
        let deadline = Date.now.addingTimeInterval(2)
        while engine.isThinking && Date.now < deadline { try await Task.sleep(for: .milliseconds(10)) }
        #expect(engine.turns.last?.context == context)
    }

    @Test func taskIdeaReviewDoesNotFabricateItsOutcome() throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        let model = AppModel(storageDirectory: directory)
        let action = AgentAction(title: "Sample task", detail: "Prepare a question", outcomeLine: "Never sent", glyph: "doc.text", leavesDevice: true)
        model.agentActions = [action]
        let priorStoryCount = model.storyEvents.count
        let draft = try #require(model.workflowForAction(action.id))
        #expect(draft.status == .draft)
        #expect(model.agentActions.first?.state == .proposed)
        #expect(model.storyEvents.count == priorStoryCount)
        #expect(model.quickLogAck == nil)
    }

    @Test func agentProposalCreatesOneDraftAndNeverCompletesExternalWork() throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        let model = AppModel(storageDirectory: directory)
        model.workflows = []
        model.agentServices = [.init(id: "scheduling", name: "Scheduling", role: "Prepare", glyph: "calendar", accent: .warm)]
        model.agentTasks = [.init(id: "selected-task", agentID: "scheduling", title: "Prepare a visit question", detail: "Draft only", mode: .needsApproval, status: .waiting, sources: [], cadence: "Example", outcomeLine: "Never claim sent")]
        let first = try #require(model.workflowForAgentTask("selected-task"))
        let second = try #require(model.workflowForAgentTask("selected-task"))
        #expect(first.id == second.id && model.workflows.count == 1)
        #expect(first.recipient.isEmpty && first.status == .draft)
        #expect(model.agentTasks.first?.status == .waiting)
        model.declineAgentTask("selected-task")
        #expect(model.agentTasks.count == 1)
        #expect(model.workflows.first?.status == .declined)
        #expect(model.workflowForAgentTask("selected-task")?.id == first.id)
        model.agentServices[0].active = false
        #expect(model.workflowForAgentTask("selected-task") == nil)
    }

    @Test func bundledFieldsWeightsResolveWithoutSystemFallback() {
        NudgeFonts.registerAll()
        for name in ["FONTSPRINGDEMO-FieldsDisplayRegular", "FONTSPRINGDEMO-FieldsDisplaySemiBoldRegular", "FONTSPRINGDEMO-FieldsDisplayMediumRegular", "FONTSPRINGDEMO-FieldsDisplayBold"] {
            #expect(UIFont(name: name, size: 24) != nil)
        }
    }

    @Test func onboardingIncludesOptionalRecordsStage() {
        #expect(OnboardingFlowView.Stage.allCases == [.welcome, .scenario, .records, .preferences])
    }

    @Test func nextVisitIgnoresPastAndCancelledAppointments() {
        let model = AppModel()
        let now = Date(timeIntervalSince1970: 1_800_000_000)
        let old = Appointment(with: "Past", date: now.addingTimeInterval(-100), location: "Clinic", prepReady: true)
        let cancelled = Appointment(with: "Cancelled", date: now.addingTimeInterval(50), location: "Clinic", prepReady: true, status: .cancelled)
        let next = Appointment(with: "Next", date: now.addingTimeInterval(100), location: "Clinic", prepReady: true)
        let later = Appointment(with: "Later", date: now.addingTimeInterval(200), location: "Clinic", prepReady: true)
        model.appointments = [later, cancelled, old, next]
        #expect(model.nextAppointment(after: now)?.id == next.id)
        model.appointments = [old, cancelled]
        #expect(model.nextAppointment(after: now) == nil)
    }

    @Test func fourPrimaryDestinations() {
        #expect(AppModel.Tab.allCases.map(\.rawValue) == ["Today", "Care", "Messages", "You"])
    }

    @Test func communicationRoutesHaveTheirOwnHome() {
        #expect(CareDestination.messages.isMessaging)
        #expect(CareDestination.thread(UUID()).isMessaging)
        #expect(CareDestination.requests.isMessaging)
        #expect(!CareDestination.records.isMessaging)
        #expect(!CareDestination.appointments.isMessaging)
    }

    @Test func selectedAppointmentDoesNotFallBack() throws {
        let model = AppModel()
        model.appointments = CareHubFixtures.bundle(for: .metabolic).appointments
        let selected = try #require(model.appointments.last)
        #expect(model.appointment(withID: selected.id) == selected)
        #expect(model.appointment(withID: UUID()) == nil)
        model.appointments = []
        #expect(model.appointment(withID: selected.id) == nil)
    }

    @Test func directMessagesRoutePreservesOtherTabPaths() {
        let model = AppModel()
        model.carePath.append(CareDestination.appointments)
        model.youPath.append(YouDestination.journeys)
        model.openCare(.thread(UUID()))
        #expect(model.tab == .messages)
        #expect(model.messagesPath.count == 1)
        #expect(model.carePath.count == 1)
        #expect(model.youPath.count == 1)
        model.openCare(.messages)
        #expect(model.messagesPath.isEmpty)
    }

    @Test func oldSnapshotsDecodeWithoutDraftsAndKeepEmptyCollections() throws {
        let data = Data("""
        {"pathway":"metabolic","entries":[],"logs":[],"memories":[],"guideItems":[],
         "memoryNotes":[],"threads":[],"requests":[],"documents":[],"paidBillKeys":[],"derivedJourneyGoals":[]}
        """.utf8)
        let decoded = try JSONDecoder().decode(SanoUserData.self, from: data)
        #expect(decoded.guideItems.isEmpty)
        #expect(decoded.memoryNotes.isEmpty)
        #expect(decoded.threads.isEmpty)
        #expect(decoded.messageDrafts == nil)
    }

    @Test func scenarioSnapshotsDoNotOverwriteEachOther() throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        PersistenceService.save(SanoUserData(pathway: "metabolic", messageDrafts: ["a": "Unsent A"]), directory: directory)
        PersistenceService.save(SanoUserData(pathway: "oncology", messageDrafts: ["b": "Unsent B"]), directory: directory)
        let first = try #require(PersistenceService.load(pathway: "metabolic", directory: directory))
        #expect(first.messageDrafts?["a"] == "Unsent A")
        #expect(first.messageDrafts?["b"] == nil)
        PersistenceService.save(SanoUserData(pathway: "metabolic", messageDrafts: [:]), directory: directory)
        #expect(PersistenceService.load(pathway: "metabolic", directory: directory)?.messageDrafts?.isEmpty == true)
        #expect(PersistenceService.load(pathway: "oncology", directory: directory)?.messageDrafts?["b"] == "Unsent B")
    }

    @Test func profilesRequireRealDatesAndDoNotMatchAnotherSample() {
        var profile = RecordConnectionProfile.sample("metabolic")
        #expect(profile.isValid)
        #expect(profile.matchesSample("metabolic"))
        #expect(!profile.matchesSample("oncology"))
        profile.dateOfBirth = "2025-02-30"
        #expect(!profile.isValid)
        profile.dateOfBirth = ""
        #expect(!profile.isValid)
    }

    @Test func savedCareContextKeepsIDsAndReviewedVersions() throws {
        let visit = Appointment(with: "Selected clinician", date: .now, location: "Sample clinic", prepReady: false)
        var prep = AppointmentPrep(appointmentID: visit.id, goal: "Discuss a concern")
        prep.reviewedAt = .now
        prep.reviewedText = prep.brief(visit: visit.with)
        let snapshot = SanoUserData(pathway: "metabolic", appointments: [visit], visitPreps: [visit.id.uuidString: prep], journeys: [])
        let restored = try JSONDecoder().decode(SanoUserData.self, from: JSONEncoder().encode(snapshot))
        #expect(restored.appointments?.first?.id == visit.id)
        #expect(restored.visitPreps?[visit.id.uuidString]?.reviewedText == prep.reviewedText)
        #expect(restored.journeys?.isEmpty == true)
        prep.goal = "A different priority"
        prep.invalidateReview()
        #expect(prep.reviewedAt == nil && prep.reviewedText == nil)
    }

    @Test func workflowEditInvalidatesApprovalAndNeverBecomesSent() {
        var draft = ReviewedWorkflow(originID: UUID(), title: "A question", detail: "Please review this", recipient: "My clinic")
        draft.approve()
        #expect(draft.status == .ready)
        draft.edit(detail: "Changed draft", recipient: "Another clinic")
        #expect(draft.status == .draft && draft.reviewedAt == nil)
        draft.status = .declined
        #expect(draft.status != .ready)
    }

    @Test func habitCheckInUpdatesOnlySelectedHabitAndCanBeUndone() throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        let model = AppModel(storageDirectory: directory)
        let first = AtomicHabit(title: "First", contextLine: "", keptDates: [])
        let selected = AtomicHabit(title: "Selected", contextLine: "After coffee", keptDates: [], support: .init(fallback: "Open the notebook"))
        let journey = Journey(title: "Mine", why: "My reason", habits: [first, selected], gardenSeed: 1)
        model.journeys = [journey]
        model.habitCheckIns = []
        model.recordHabitCheckIn(journeyID: journey.id, habitID: selected.id, outcome: .kept, note: "")
        model.recordHabitCheckIn(journeyID: journey.id, habitID: selected.id, outcome: .fallback, note: "Tired today")
        #expect(model.habitCheckIns.count == 1)
        #expect(model.journeys[0].habits[0].keptDates.isEmpty)
        #expect(model.journeys[0].habits[1].keptDates.count == 1)
        let stored = try #require(PersistenceService.load(pathway: model.pathway.rawValue, directory: directory))
        #expect(stored.habitCheckIns?.first?.outcome == .fallback)
        model.undoHabitCheckIn(journeyID: journey.id, habitID: selected.id)
        #expect(model.habitCheckIns.isEmpty)
        #expect(model.journeys[0].habits[1].keptDates.isEmpty)
    }

    @Test func chatRestoreMarksPartialReplyInterrupted() {
        var reply = ConversationTurn(role: .companion, text: "Partial")
        reply.streaming = true
        reply.delivery = .streaming
        let engine = CompanionEngine(transport: HeldChatTransport())
        engine.restore(turns: [reply], draft: "Unsent thought")
        #expect(engine.turns.first?.id == reply.id)
        #expect(engine.turns.first?.delivery == .interrupted)
        #expect(engine.turns.first?.streaming == false)
        #expect(engine.composerDraft == "Unsent thought")
        engine.declineRich(turnID: reply.id)
        #expect(engine.turns.first?.declined == true)
    }

    @Test func cancelledOldChatCannotWriteIntoNewConversation() async throws {
        let transport = HeldChatTransport()
        let engine = CompanionEngine(transport: transport)
        let orb = OrbState()
        engine.send("First", orb: orb)
        try await transport.waitForCallCount(1)
        engine.reset()
        engine.send("Second", orb: orb)
        try await transport.waitForCallCount(2)
        transport.finish(index: 0, text: "Obsolete [[guide:Wrong question]]")
        transport.finish(index: 1, text: "Current response")
        let deadline = Date.now.addingTimeInterval(2)
        while engine.isThinking && Date.now < deadline { try await Task.sleep(for: .milliseconds(10)) }
        #expect(engine.turns.filter { $0.role == .user }.map(\.text) == ["Second"])
        #expect(engine.turns.last?.text == "Current response")
        #expect(engine.turns.last?.rich == ConversationTurn.Rich.none)
        #expect(!engine.isThinking)
    }

    @Test func replyDraftsRoundTripWithoutBecomingMessages() throws {
        let snapshot = SanoUserData(pathway: "metabolic", messageDrafts: ["thread-a": "A question for my visit"])
        let decoded = try JSONDecoder().decode(SanoUserData.self, from: JSONEncoder().encode(snapshot))
        #expect(decoded.messageDrafts?["thread-a"] == "A question for my visit")
        #expect(decoded.threads.isEmpty)
    }
}

@MainActor
private final class HeldChatTransport: ChatTransport {
    private var continuations: [CheckedContinuation<String, any Error>] = []
    var receivedMessages: [[AIChatMessage]] = []
    func stream(requestID: UUID, system: String, messages: [AIChatMessage], onDelta: @escaping @MainActor (String) -> Void) async throws -> String {
        receivedMessages.append(messages)
        return try await withCheckedThrowingContinuation { continuations.append($0) }
    }
    func waitForCallCount(_ count: Int) async throws {
        let deadline = Date.now.addingTimeInterval(2)
        while continuations.count < count && Date.now < deadline { try await Task.sleep(for: .milliseconds(10)) }
        #expect(continuations.count >= count)
    }
    func finish(index: Int, text: String) { continuations[index].resume(returning: text) }
}
