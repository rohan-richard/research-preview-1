import Foundation

/// The Care hub data spine (v5 §4.4). The clinical action center — messages,
/// appointments, the care plan, medications & refills, records, bills, and
/// documents — all rendered from these models. Calm but utilitarian: every
/// value carries provenance and freshness, and nothing consequential happens
/// without an explicit, equal-weight confirmation (§2.2, §5.5).

// MARK: - Navigation

/// Type-safe destinations inside Care. Today's "Needs you" routes here too.
enum CareDestination: Hashable {
    case messages
    case thread(UUID)
    case appointments
    case appointmentDetail(UUID)
    case trip(UUID)
    case carePlan
    case medications
    case requests
    case savings(String)        // medication id
    case records
    case bills
    case billDetail(UUID)
    case documents
    case visitPrep(UUID)
    case reports
    case wallet
    case connections

    var isMessaging: Bool {
        switch self {
        case .messages, .thread, .requests: return true
        default: return false
        }
    }
}

// MARK: - Messages (care-team communication · §4.4.1)

/// Whether a practice supports true in-app secure threads (R1 athena/Privia),
/// or the app must hand a drafted message off to the portal. The user always
/// sees which mode applies (MSG-4).
enum MessageChannelMode: String, Codable {
    case inApp
    case portal

    var label: String {
        switch self {
        case .inApp: return "Demo conversation"
        case .portal: return "Drafted for the portal"
        }
    }
}

/// Categories the practice exposes; composing routes accordingly (MSG-5).
enum MessageCategory: String, Codable, CaseIterable, Identifiable {
    case medical = "Medical question"
    case refill = "Refill"
    case admin = "Admin / scheduling"
    case records = "Records request"

    var id: String { rawValue }

    var glyph: String {
        switch self {
        case .medical: return "stethoscope"
        case .refill: return "pills"
        case .admin: return "calendar"
        case .records: return "doc.on.doc"
        }
    }
}

enum MessageState: String, Codable {
    case draft, sending, sent, delivered, replied
}

struct CareMessage: Identifiable, Codable, Equatable {
    enum Author: String, Codable { case user, team }

    var id = UUID()
    let author: Author
    var text: String
    var at: Date
    var state: MessageState = .delivered
    /// Origin context when the message began elsewhere — a symptom pattern,
    /// a result, the discussion guide — so the care team sees why (MSG-8).
    var origin: String? = nil
    /// Attachment label + provenance, on user action (MSG-7).
    var attachment: String? = nil
}

struct MessageThread: Identifiable, Codable, Equatable {
    var id = UUID()
    let practice: String
    let memberName: String
    let memberRole: String
    let mode: MessageChannelMode
    var category: MessageCategory = .medical
    var messages: [CareMessage]
    var unread: Bool = false

    var lastMessage: CareMessage? { messages.max(by: { $0.at < $1.at }) }
    var preview: String { lastMessage?.text ?? "No messages yet" }
    var lastAt: Date { lastMessage?.at ?? .distantPast }
}

// MARK: - Appointment enrichment (§4.4.2 / §4.4.3)

enum AppointmentKind: String, Codable {
    case inPerson
    case telehealth

    var label: String { self == .telehealth ? "Telehealth" : "In person" }
    var glyph: String { self == .telehealth ? "video" : "building.2" }
}

enum AppointmentStatus: String, Codable {
    case confirmed, pending, cancelled, visited

    var label: String {
        switch self {
        case .confirmed: return "Confirmed"
        case .pending: return "Pending"
        case .cancelled: return "Cancelled"
        case .visited: return "Visited"
        }
    }
}

/// One step in a trip plan — gets the user to the visit without friction.
struct TripStep: Identifiable, Equatable {
    let id = UUID()
    let glyph: String
    let title: String
    let detail: String
}

/// The wayfinding "trip plan" (§4.4.3) — depart-by, route, and the pre-visit
/// checklist; or a readiness flow for a telehealth visit.
struct TripPlan: Equatable, Codable {
    let departBy: Date
    let travelMinutes: Int
    let routeHint: String
    let destinationDetail: String
    let mapQuery: String
    let checklist: [String]
    var isVirtual: Bool = false
    /// A known calendar conflict to surface before it bites (WAY-3).
    var calendarConflict: String? = nil
    /// Whether a ride can be offered (WAY-4).
    var rideHint: String? = nil
}

// MARK: - Bills, costs & out-of-pocket (§4.4.9)

enum BillStatus: String, Codable {
    case open, paid, inDispute

    var label: String {
        switch self {
        case .open: return "Open"
        case .paid: return "Paid"
        case .inDispute: return "In dispute"
        }
    }
}

struct BillLineItem: Identifiable, Equatable, Codable {
    var id = UUID()
    let label: String
    let billed: Double
    let planPaid: Double
    let youOwe: Double
    /// Why you owe it — deductible, copay, coinsurance, out-of-network.
    let reason: String
}

struct Bill: Identifiable, Equatable, Codable {
    var id = UUID()
    /// Stable key (provider + encounter) so paid state survives relaunch.
    let key: String
    let provider: String
    let encounter: String
    let statementDate: Date
    let dueDate: Date?
    var status: BillStatus
    let amount: Double
    let lineItems: [BillLineItem]
    /// The companion's plain-language read of the statement (BILL-2).
    let plainSummary: String
    /// A likely billing error the companion flags, if any (BILL-5).
    let flag: String?
    let source: String
}

/// Deductible and out-of-pocket progress from claims, plus an estimate for
/// known upcoming care — always clearly labeled an estimate (BILL-3).
struct CostSummary: Equatable {
    let planName: String
    let deductibleMet: Double
    let deductibleTotal: Double
    let oopMet: Double
    let oopTotal: Double
    let upcomingEstimate: Double?
    let upcomingLabel: String?
}

// MARK: - Documents (paper-to-digital · §4.4.10)

enum DocumentType: String, Codable, CaseIterable, Identifiable {
    case insuranceCard = "Insurance card"
    case labResult = "Lab result"
    case immunization = "Immunization"
    case bill = "Bill"
    case identification = "ID"
    case form = "Form"
    case other = "Other"

    var id: String { rawValue }

    var glyph: String {
        switch self {
        case .insuranceCard: return "creditcard"
        case .labResult: return "drop"
        case .immunization: return "syringe"
        case .bill: return "dollarsign.circle"
        case .identification: return "person.text.rectangle"
        case .form: return "doc.text"
        case .other: return "doc"
        }
    }
}

/// A field pulled from a scan — shown for confirmation before it ever alters
/// the record; low-confidence fields are flagged, never silently trusted (DOC-4).
struct ExtractedField: Identifiable, Equatable, Codable {
    var id = UUID()
    let label: String
    var value: String
    var lowConfidence: Bool = false
}

struct CareDocument: Identifiable, Equatable, Codable {
    var id = UUID()
    var title: String
    var type: DocumentType
    var capturedAt: Date
    /// "From your scan" / "Imported" — provenance is always visible (DOC-2).
    var source: String
    /// A file saved in the encrypted container (user-captured), or a bundled
    /// stand-in for the seeded examples.
    var imageFilename: String? = nil
    var bundledImage: String? = nil
    var pageCount: Int = 1
    var fields: [ExtractedField] = []
    var confirmed: Bool = false
}

// MARK: - Unified requests (§4.4.6 MED-5)

enum RequestKind: String, Codable, CaseIterable, Identifiable {
    case refill = "Refill"
    case appointment = "Appointment"
    case records = "Records copy"
    case form = "Form"

    var id: String { rawValue }

    var glyph: String {
        switch self {
        case .refill: return "pills"
        case .appointment: return "calendar.badge.plus"
        case .records: return "doc.on.doc"
        case .form: return "list.clipboard"
        }
    }
}

enum RequestState: String, Codable {
    case submitted, acknowledged, resolved

    var label: String {
        switch self {
        case .submitted: return "Submitted"
        case .acknowledged: return "Acknowledged"
        case .resolved: return "Resolved"
        }
    }
}

struct CareRequest: Identifiable, Codable, Equatable {
    var id = UUID()
    let kind: RequestKind
    let subject: String
    let detail: String
    var state: RequestState = .submitted
    var at: Date = .now
    /// Where it routed — in-app where supported, else drafted-for-portal.
    let routedTo: String
}

// MARK: - Medication savings & coupons (§4.4.7)

enum SavingKind: String, Codable {
    case copayCard = "Copay card"
    case assistance = "Patient assistance"
    case cashPrice = "Cash price"
    case alternative = "Lower-cost option"

    var glyph: String {
        switch self {
        case .copayCard: return "giftcard"
        case .assistance: return "hand.raised"
        case .cashPrice: return "tag"
        case .alternative: return "arrow.triangle.swap"
        }
    }
}

/// A savings option for a medication. Sponsorship never alters clinical
/// ranking or the neutral answer to "are there other options?" (SAV-4).
/// The app never enters or stores payment credentials (SAV-6).
struct MedicationSaving: Identifiable, Equatable {
    let id = UUID()
    let medID: String
    let kind: SavingKind
    let title: String
    /// "about $47/month less" — labeled estimated until claims confirm (SAV-5).
    let estimateLine: String
    let basis: String
    let sponsor: String?
    /// Applying submits personal info → explicit confirm, pre-filled for
    /// review, never auto-submitted (SAV-3).
    let requiresPII: Bool
    var applied: Bool = false
}

// MARK: - Looking-ahead (population risk · §4.10)

/// The only patient-facing expression of the prediction model: a population-
/// level, screening-and-prevention nudge that routes to care. Never an
/// individual prediction, probability, or date (PRD-1/2). Suppressed by
/// opt-out, crisis, and the first 14 days (PRD-5/6).
struct LookingAheadNudge: Equatable {
    let headline: String
    let body: String
    /// "why am I seeing this" — the population basis, made honest (PRD-4).
    let basis: String
    /// The guide question this routes into (PRD-3).
    let guideQuestion: String
}

// MARK: - Needs you (the Care/Today attention band · §3.2, §4.3 TDY-3)

struct NeedsYouItem: Identifiable, Equatable {
    enum Kind {
        case message, result, refill, bill, form, appointment

        var glyph: String {
            switch self {
            case .message: return "bubble.left"
            case .result: return "drop"
            case .refill: return "pills"
            case .bill: return "dollarsign.circle"
            case .form: return "list.clipboard"
            case .appointment: return "calendar"
            }
        }
    }

    let id = UUID()
    let kind: Kind
    let title: String
    let detail: String
    let destination: CareDestination
}
