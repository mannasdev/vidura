import Foundation

/// Outcome of a `vidura-do --dry-run` invocation, used to gate whether
/// the confirmation sheet may ever show a live Confirm button. A dry-run
/// that failed, timed out, or exited nonzero is NOT a preview of a safe
/// action — it's a hard error, and the sheet must not offer to proceed.
enum DryRunOutcome {
    /// Exit code 0 and non-empty stdout: `preview` is the exact action
    /// the confirmed run will take. Confirm may be shown.
    case success(preview: String)
    /// Nonzero exit, empty stdout on success, a thrown CoreError, or any
    /// other failure to produce a trustworthy preview. `message` is
    /// shown as a hard error; the sheet offers Cancel/Close only.
    case failure(message: String)
}

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

    /// The menu bar glyph is fixed and does NOT vary by mood — see
    /// `AppDelegate` in main.swift. This static symbol is the ONE mark
    /// ever shown in the status item, template-rendered so AppKit tints
    /// it to match the menu bar's light/dark appearance automatically.
    static let menuBarSymbolName = "circle.hexagongrid.circle"

    /// Mood -> big expressive face glyph shown in the popover header.
    /// PLACEHOLDER ONLY: these SF Symbols stand in for future designer
    /// art (a real illustrated face per mood). When that art lands, this
    /// is the one function to swap — nothing else in the app should need
    /// to know how a mood is drawn. Static glyph only, per the anti-Clippy
    /// invariant: no animation anywhere in this app.
    var faceSymbolName: String {
        switch self {
        case .asleep: return "powersleep"
        case .content: return "face.smiling"
        case .stirring: return "sparkles"
        case .proud: return "star.circle.fill"
        case .concerned: return "cloud.fill"
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
