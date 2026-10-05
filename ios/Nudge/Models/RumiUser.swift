import Foundation

/// The signed-in patient, as `GET /v1/auth/me` returns it.
nonisolated struct RumiUser: Codable, Equatable {
    var id: String
    var email: String
    var displayName: String
    var status: String
    var onboardingComplete: Bool
    var providers: [String]
    var createdAt: Date
}
