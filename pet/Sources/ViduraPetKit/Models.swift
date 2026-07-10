import Foundation

/// Outcome of a `vidura-do --dry-run` invocation, used to gate whether
/// the confirmation sheet may ever show a live Confirm button. A dry-run
/// that failed, timed out, or exited nonzero is NOT a preview of a safe
/// action — it's a hard error, and the sheet must not offer to proceed.
public enum DryRunOutcome {
    /// Exit code 0 and non-empty stdout: `preview` is the exact action
    /// the confirmed run will take. Confirm may be shown.
    case success(preview: String)
    /// Nonzero exit, empty stdout on success, a thrown CoreError, or any
    /// other failure to produce a trustworthy preview. `message` is
    /// shown as a hard error; the sheet offers Cancel/Close only.
    case failure(message: String)

    /// Whether this outcome may show a live Confirm button — true only
    /// for a verified `.success`. Extracted so DoGatingTests can assert
    /// the gate directly instead of pattern-matching in the view.
    public var confirmEnabled: Bool {
        if case .success = self { return true }
        return false
    }
}

/// Mirrors vidura.mood.compute_mood's JSON payload (vidura-state stdout).
/// All fields are always present per that module's contract, so decoding
/// never needs defensive optionals beyond what the Python side allows.
public struct MoodState: Codable, Equatable {
    public let mood: String
    public let pendingCount: Int
    public let adoptedUncelebratedIds: [Int]
    public let streakRate7d: Double?
    public let streakRateBaseline: Double?
    public let sessions24h: Int

    enum CodingKeys: String, CodingKey {
        case mood
        case pendingCount = "pending_count"
        case adoptedUncelebratedIds = "adopted_uncelebrated_ids"
        case streakRate7d = "streak_rate_7d"
        case streakRateBaseline = "streak_rate_baseline"
        case sessions24h = "sessions_24h"
    }

    public init(
        mood: String,
        pendingCount: Int,
        adoptedUncelebratedIds: [Int],
        streakRate7d: Double?,
        streakRateBaseline: Double?,
        sessions24h: Int
    ) {
        self.mood = mood
        self.pendingCount = pendingCount
        self.adoptedUncelebratedIds = adoptedUncelebratedIds
        self.streakRate7d = streakRate7d
        self.streakRateBaseline = streakRateBaseline
        self.sessions24h = sessions24h
    }
}

public enum Mood: String {
    case asleep = "ASLEEP"
    case content = "CONTENT"
    case stirring = "STIRRING"
    case proud = "PROUD"
    case concerned = "CONCERNED"

    /// The menu bar glyph is fixed and does NOT vary by mood — see
    /// `AppDelegate`. It is rendered in code from the same pixel-art
    /// creature as the popover header; see `PixelPetMenuBarMark` in
    /// PixelPet.swift.
}

/// Accepted/dismissed counts for the footer's "Last counsel · …" line
/// (spec §2.3 shows only relative time, but the task brief asks the
/// footer to also carry a counts summary derived from the full ledger).
/// Pure struct + pure derivation function so the counting logic can be
/// unit-tested without any live CLI call — `StateModel` just filters
/// `vidura-ledger list --json`'s full (unfiltered) result through this.
public struct LedgerCounts: Equatable {
    public let accepted: Int
    public let dismissed: Int

    public init(accepted: Int, dismissed: Int) {
        self.accepted = accepted
        self.dismissed = dismissed
    }

    /// Derives counts from the full ledger (all statuses), not just the
    /// pending subset `StateModel.entries` holds for display. Unknown/
    /// future status strings are simply not counted as either bucket —
    /// this must never crash on a status the Swift side doesn't yet
    /// know about.
    public static func derive(from allEntries: [LedgerEntry]) -> LedgerCounts {
        var accepted = 0
        var dismissed = 0
        for entry in allEntries {
            switch entry.status {
            case "accepted": accepted += 1
            case "dismissed": dismissed += 1
            default: break
            }
        }
        return LedgerCounts(accepted: accepted, dismissed: dismissed)
    }
}

/// Mirrors one row of `vidura-ledger list --json` (Task 1's enriched
/// ledger entry: has_action/action_label consulted from the fix index
/// on the Python side so this app never needs its own copy of it).
public struct LedgerEntry: Codable, Identifiable, Equatable {
    public let id: Int
    public let fixId: String
    public let status: String
    public let confidence: Double
    public let occurrences: Int
    public let bluntSummary: String
    public let evidence: [String]
    public let novel: Bool
    public let updatedAt: String
    public let hasAction: Bool
    public let actionLabel: String?

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

    public init(
        id: Int,
        fixId: String,
        status: String,
        confidence: Double,
        occurrences: Int,
        bluntSummary: String,
        evidence: [String],
        novel: Bool,
        updatedAt: String,
        hasAction: Bool,
        actionLabel: String?
    ) {
        self.id = id
        self.fixId = fixId
        self.status = status
        self.confidence = confidence
        self.occurrences = occurrences
        self.bluntSummary = bluntSummary
        self.evidence = evidence
        self.novel = novel
        self.updatedAt = updatedAt
        self.hasAction = hasAction
        self.actionLabel = actionLabel
    }
}
