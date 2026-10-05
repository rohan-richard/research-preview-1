import Foundation

/// A single point in a lab/vital series.
struct LabPoint: Identifiable, Equatable {
    let id = UUID()
    let date: Date
    let value: Double
}

struct SeriesAnnotation: Equatable {
    let date: Date
    let label: String
}

/// A chartable metric with provenance and an optional soft reference band.
struct LabSeries: Identifiable, Equatable {
    let id: String
    let name: String
    let unit: String
    let points: [LabPoint]
    let band: ClosedRange<Double>?
    let bandLabel: String?
    let annotation: SeriesAnnotation?
    let provenance: String
    let explainReading: String
    let explainNextStep: String
    let explainAsk: String

    var latest: LabPoint? { points.max(by: { $0.date < $1.date }) }
}

enum RecordCategory: String, CaseIterable, Identifiable, Hashable {
    case labs = "Labs"
    case medications = "Medications"
    case conditions = "Conditions"
    case immunizations = "Immunizations"
    case procedures = "Procedures"
    case notes = "Notes"
    case documents = "Documents"

    var id: String { rawValue }

    var glyph: String {
        switch self {
        case .labs: return "drop"
        case .medications: return "pills"
        case .conditions: return "heart.text.square"
        case .immunizations: return "syringe"
        case .procedures: return "cross.case"
        case .notes: return "text.book.closed"
        case .documents: return "doc.text"
        }
    }
}

/// A generic record row in the records drawer.
struct RecordItem: Identifiable, Equatable, Hashable {
    let id = UUID()
    let category: RecordCategory
    let title: String
    let detail: String
    let date: Date
    let source: String
    var conflicted: Bool = false
    var conflictNote: String? = nil
    var seriesID: String? = nil
}

struct Medication: Identifiable, Equatable, Hashable {
    let id: String
    let name: String
    let dose: String
    let purposeLine: String
    let scheduleLine: String
    var supplyDaysRemaining: Int
    let pharmacy: String
    let guidance: [String]
    let watchlist: [String]
    let history: [String]
    /// Last 30 days, 0…1 per day — feeds the tide. PDC lives one tap deep,
    /// never on the surface.
    var adherence30: [Double]

    var tideLevel: Double {
        guard !adherence30.isEmpty else { return 0 }
        return adherence30.reduce(0, +) / Double(adherence30.count)
    }
}

struct CareTeamMember: Identifiable, Equatable {
    let id = UUID()
    let name: String
    let role: String
    let org: String
}

struct Appointment: Identifiable, Equatable, Codable {
    var id = UUID()
    let with: String
    var date: Date
    let location: String
    var prepReady: Bool
    /// v5 Care enrichment — defaults keep every existing fixture call valid.
    var kind: AppointmentKind = .inPerson
    var status: AppointmentStatus = .confirmed
    /// Telehealth join target; the button unlocks only inside the pre-window.
    var joinLink: String? = nil
    /// The wayfinding trip plan (or readiness flow for telehealth).
    var trip: TripPlan? = nil
    /// Which care-plan goal this visit advances, in plain words.
    var planGoalHint: String? = nil
}

/// A connected data source with rail + freshness — aggregation quality is a
/// first-class UX concern.
struct RecordSource: Identifiable, Equatable {
    let id = UUID()
    let name: String
    let railLabel: String
    var connected: Bool
    var lastSync: Date
}

struct ConsentEntry: Identifiable, Equatable {
    let id = UUID()
    let source: String
    let scope: String
    var granted: Bool
    let at: Date
    /// The API consent this row sets, when the patient is signed in.
    var apiScope: String? = nil
}

struct MemoryItem: Identifiable, Equatable, Codable {
    var id = UUID()
    var text: String
    let learnedFrom: String
}
