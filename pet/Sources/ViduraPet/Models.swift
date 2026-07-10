import Foundation

/// Mirrors vidura.mood.compute_mood's JSON payload (vidura-state stdout).
/// All fields are always present per that module's contract, so decoding
/// never needs defensive optionals beyond what the Python side allows.
struct MoodState: Codable, Equatable {
    let mood: String
    let pendingCount: Int
    let adoptedUncelebratedIds: [Int]
    let streakRate7d: Double?
    let streakRateBaseline: Double?
    let sessions24h: Int

    enum CodingKeys: String, CodingKey {
        case mood
        case pendingCount = "pending_count"
        case adoptedUncelebratedIds = "adopted_uncelebrated_ids"
        case streakRate7d = "streak_rate_7d"
        case streakRateBaseline = "streak_rate_baseline"
        case sessions24h = "sessions_24h"
    }
}

enum Mood: String {
    case asleep = "ASLEEP"
    case content = "CONTENT"
    case stirring = "STIRRING"
    case proud = "PROUD"
    case concerned = "CONCERNED"

    /// SF Symbol per the plan's mood table. Static glyph only — no
    /// animation APIs are used anywhere in this app (anti-Clippy
    /// invariant: no motion to attract attention).
    var symbolName: String {
        switch self {
        case .asleep: return "moon.zzz"
        case .content: return "moon.stars"
        case .stirring: return "sparkles"
        case .proud: return "star.circle"
        case .concerned: return "cloud"
        }
    }
}

/// Mirrors one row of `vidura-ledger list --json` (Task 1's enriched
/// ledger entry: has_action/action_label consulted from the fix index
/// on the Python side so this app never needs its own copy of it).
struct LedgerEntry: Codable, Identifiable, Equatable {
    let id: Int
    let fixId: String
    let status: String
    let confidence: Double
    let occurrences: Int
    let bluntSummary: String
    let evidence: [String]
    let novel: Bool
    let updatedAt: String
    let hasAction: Bool
    let actionLabel: String?

    enum CodingKeys: String, CodingKey {
        case id
        case fixId = "fix_id"
        case status
        case confidence
        case occurrences
        case bluntSummary = "blunt_summary"
        case evidence
        case novel
        case updatedAt = "updated_at"
        case hasAction = "has_action"
        case actionLabel = "action_label"
    }
}
