import Foundation

extension AppModel {
    func savePrep(_ value: AppointmentPrep) {
        guard appointment(withID: value.appointmentID) != nil else { return }
        visitPreps[value.appointmentID.uuidString] = value
        persistUserData()
    }

    func workflowDraft(originID: UUID, title: String, detail: String, context: CareContext?) -> ReviewedWorkflow {
        if let saved = workflows.first(where: { $0.originID == originID }) { return saved }
        if let context, let saved = workflows.first(where: { $0.context?.id == context.id && $0.context?.scenario == context.scenario && $0.title == title }) { return saved }
        return .init(originID: originID, title: title, detail: detail, context: context)
    }

    func saveWorkflow(_ value: ReviewedWorkflow) {
        guard value.context == nil || value.context?.scenario == pathway.rawValue else { return }
        if let index = workflows.firstIndex(where: { $0.originID == value.originID }) { workflows[index] = value }
        else { workflows.insert(value, at: 0) }
        persistUserData()
    }

    func saveHabit(journeyID: UUID?, habitID: UUID?, title: String, support: HabitSupportPlan) {
        let trimmed = title.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        if let journeyID, let habitID,
           let j = journeys.firstIndex(where: { $0.id == journeyID }),
           let h = journeys[j].habits.firstIndex(where: { $0.id == habitID }) {
            journeys[j].habits[h].title = trimmed
            journeys[j].habits[h].contextLine = support.cue
            journeys[j].habits[h].support = support
            saveHabitLive(habitID: habitID, title: trimmed, support: support)
        } else if journeyID == nil && habitID == nil {
            let habit = AtomicHabit(title: trimmed, contextLine: support.cue, keptDates: [], support: support)
            let journey = Journey(title: "A little room for change", why: support.reason, habits: [habit], gardenSeed: 72)
            journeys.insert(journey, at: 0)
            saveNewJourneyLive(journey)
        }
        persistUserData()
    }

    func recordHabitCheckIn(journeyID: UUID, habitID: UUID, outcome: HabitCheckIn.Outcome, note: String) {
        guard let j = journeys.firstIndex(where: { $0.id == journeyID }),
              let h = journeys[j].habits.firstIndex(where: { $0.id == habitID }),
              journeys[j].habits[h].support?.paused != true else { return }
        // One editable daily check-in; changing the outcome replaces it rather than inflating progress.
        habitCheckIns.removeAll { $0.habitID == habitID && Calendar.current.isDateInToday($0.at) }
        journeys[j].habits[h].keptDates.removeAll { Calendar.current.isDateInToday($0) }
        habitCheckIns.append(.init(habitID: habitID, outcome: outcome, note: note, planAtCheckIn: journeys[j].habits[h].support))
        if outcome == .kept || outcome == .fallback { journeys[j].habits[h].keptDates.append(.now) }
        saveCheckInLive(habitID: habitID, outcome: outcome, note: note)
        persistUserData()
    }

    func undoHabitCheckIn(journeyID: UUID, habitID: UUID) {
        guard let j = journeys.firstIndex(where: { $0.id == journeyID }),
              let h = journeys[j].habits.firstIndex(where: { $0.id == habitID }) else { return }
        habitCheckIns.removeAll { $0.habitID == habitID && Calendar.current.isDateInToday($0.at) }
        journeys[j].habits[h].keptDates.removeAll { Calendar.current.isDateInToday($0) }
        saveCheckInLive(habitID: habitID, outcome: nil, note: "")
        persistUserData()
    }
}
