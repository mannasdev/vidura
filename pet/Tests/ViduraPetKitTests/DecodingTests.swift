import XCTest
@testable import ViduraPetKit

/// Decodes realistic fixtures copied from the real Python-side shapes:
/// `vidura.mood.compute_mood`'s JSON (vidura-state stdout, see
/// vidura/mood.py + tests/test_mood.py) and `vidura-ledger list --json`
/// (vidura/ledger_cli.py + tests/test_ledger_cli.py). All keys are always
/// present per those modules' contracts — only `streak_rate_7d`,
/// `streak_rate_baseline`, and `action_label` are ever null.
final class DecodingTests: XCTestCase {
    private let decoder = JSONDecoder()

    // MARK: - MoodState

    func test_decodesFullMoodState() throws {
        let json = """
        {
            "mood": "STIRRING",
            "pending_count": 4,
            "adopted_uncelebrated_ids": [12, 15],
            "streak_rate_7d": 0.71,
            "streak_rate_baseline": 0.55,
            "sessions_24h": 3
        }
        """
        let decoded = try decoder.decode(MoodState.self, from: Data(json.utf8))
        XCTAssertEqual(decoded.mood, "STIRRING")
        XCTAssertEqual(decoded.pendingCount, 4)
        XCTAssertEqual(decoded.adoptedUncelebratedIds, [12, 15])
        XCTAssertEqual(decoded.streakRate7d, 0.71)
        XCTAssertEqual(decoded.streakRateBaseline, 0.55)
        XCTAssertEqual(decoded.sessions24h, 3)
    }

    /// Empty-DB / ASLEEP shape from tests/test_mood.py — both streak
    /// rates are null when fewer than 3 sessions exist in the window.
    func test_decodesAsleepStateWithNullStreakRates() throws {
        let json = """
        {
            "mood": "ASLEEP",
            "pending_count": 0,
            "adopted_uncelebrated_ids": [],
            "streak_rate_7d": null,
            "streak_rate_baseline": null,
            "sessions_24h": 0
        }
        """
        let decoded = try decoder.decode(MoodState.self, from: Data(json.utf8))
        XCTAssertEqual(decoded.mood, "ASLEEP")
        XCTAssertEqual(decoded.pendingCount, 0)
        XCTAssertEqual(decoded.adoptedUncelebratedIds, [])
        XCTAssertNil(decoded.streakRate7d)
        XCTAssertNil(decoded.streakRateBaseline)
        XCTAssertEqual(decoded.sessions24h, 0)
    }

    /// streak_rate_7d and streak_rate_baseline are independently
    /// nullable — a populated 7d window with a still-null baseline
    /// (fewer than 3 sessions in the prior 21-day window) must decode
    /// cleanly.
    func test_decodesMoodStateWithNullBaselineOnly() throws {
        let json = """
        {
            "mood": "CONTENT",
            "pending_count": 1,
            "adopted_uncelebrated_ids": [],
            "streak_rate_7d": 0.4,
            "streak_rate_baseline": null,
            "sessions_24h": 2
        }
        """
        let decoded = try decoder.decode(MoodState.self, from: Data(json.utf8))
        XCTAssertEqual(decoded.streakRate7d, 0.4)
        XCTAssertNil(decoded.streakRateBaseline)
    }

    /// Character-as-diagnosis spec: the additive `character` /
    /// `character_since` / `character_reason` fields decode cleanly when
    /// present, and `effectiveCharacter` passes the earned id straight
    /// through.
    func test_decodesMoodStateWithCharacterFields() throws {
        let json = """
        {
            "mood": "PROUD",
            "pending_count": 0,
            "adopted_uncelebrated_ids": [],
            "streak_rate_7d": 0.8,
            "streak_rate_baseline": 0.6,
            "sessions_24h": 5,
            "character": "founder",
            "character_since": "2026-06-20T00:00:00Z",
            "character_reason": "The Founder \\u2014 41 sessions and 52 hours in 14 days"
        }
        """
        let decoded = try decoder.decode(MoodState.self, from: Data(json.utf8))
        XCTAssertEqual(decoded.character, "founder")
        XCTAssertEqual(decoded.characterSince, "2026-06-20T00:00:00Z")
        XCTAssertEqual(decoded.characterReason, "The Founder \u{2014} 41 sessions and 52 hours in 14 days")
        XCTAssertEqual(decoded.effectiveCharacter, "founder")
    }

    /// Old-CLI compatibility: a payload built before the character system
    /// shipped omits all three keys entirely (not just nulls them out) —
    /// decoding must not throw, and `effectiveCharacter` must default to
    /// "temple-cat" (today's shipped look) per the additive-contract
    /// requirement.
    func test_decodesMoodStateWithoutCharacterFields_defaultsGracefully() throws {
        let json = """
        {
            "mood": "ASLEEP",
            "pending_count": 0,
            "adopted_uncelebrated_ids": [],
            "streak_rate_7d": null,
            "streak_rate_baseline": null,
            "sessions_24h": 0
        }
        """
        let decoded = try decoder.decode(MoodState.self, from: Data(json.utf8))
        XCTAssertNil(decoded.character)
        XCTAssertNil(decoded.characterSince)
        XCTAssertNil(decoded.characterReason)
        XCTAssertEqual(decoded.effectiveCharacter, "temple-cat")
    }

    /// Explicit JSON `null`s (as opposed to omitted keys) for the three
    /// character fields must also decode to `nil`, not throw.
    func test_decodesMoodStateWithNullCharacterFields() throws {
        let json = """
        {
            "mood": "CONTENT",
            "pending_count": 0,
            "adopted_uncelebrated_ids": [],
            "streak_rate_7d": 0.5,
            "streak_rate_baseline": 0.5,
            "sessions_24h": 2,
            "character": null,
            "character_since": null,
            "character_reason": null
        }
        """
        let decoded = try decoder.decode(MoodState.self, from: Data(json.utf8))
        XCTAssertNil(decoded.character)
        XCTAssertNil(decoded.characterSince)
        XCTAssertNil(decoded.characterReason)
        XCTAssertEqual(decoded.effectiveCharacter, "temple-cat")
    }

    // MARK: - LedgerEntry

    /// Full-field row shape from tests/test_ledger_cli.py: has_action
    /// true with a populated action_label.
    func test_decodesLedgerEntryWithAction() throws {
        let json = """
        {
            "id": 7,
            "fix_id": "judge-executor-split",
            "status": "pending",
            "confidence": 0.8,
            "occurrences": 3,
            "blunt_summary": "You keep re-deriving the executor split.",
            "evidence": ["q"],
            "novel": true,
            "updated_at": "2026-07-01T10:00:00Z",
            "has_action": true,
            "action_label": "Copy /office-hours"
        }
        """
        let decoded = try decoder.decode(LedgerEntry.self, from: Data(json.utf8))
        XCTAssertEqual(decoded.id, 7)
        XCTAssertEqual(decoded.fixId, "judge-executor-split")
        XCTAssertEqual(decoded.status, "pending")
        XCTAssertEqual(decoded.confidence, 0.8)
        XCTAssertEqual(decoded.occurrences, 3)
        XCTAssertEqual(decoded.bluntSummary, "You keep re-deriving the executor split.")
        XCTAssertEqual(decoded.evidence, ["q"])
        XCTAssertTrue(decoded.novel)
        XCTAssertEqual(decoded.updatedAt, "2026-07-01T10:00:00Z")
        XCTAssertTrue(decoded.hasAction)
        XCTAssertEqual(decoded.actionLabel, "Copy /office-hours")
    }

    /// Inform-only fix shape: has_action is always present as a computed
    /// bool (never omitted), but false — with action_label present and
    /// null, not missing from the payload.
    func test_decodesLedgerEntryWithoutAction() throws {
        let json = """
        {
            "id": 9,
            "fix_id": "inform-only-fix",
            "status": "pending",
            "confidence": 0.62,
            "occurrences": 1,
            "blunt_summary": "Noted, no action attached.",
            "evidence": [],
            "novel": false,
            "updated_at": "2026-07-05T08:30:00Z",
            "has_action": false,
            "action_label": null
        }
        """
        let decoded = try decoder.decode(LedgerEntry.self, from: Data(json.utf8))
        XCTAssertFalse(decoded.hasAction)
        XCTAssertNil(decoded.actionLabel)
        XCTAssertEqual(decoded.evidence, [])
    }

    func test_decodesEmptyLedgerList() throws {
        let json = "[]"
        let decoded = try decoder.decode([LedgerEntry].self, from: Data(json.utf8))
        XCTAssertEqual(decoded, [])
    }

    func test_decodesLedgerListWithMultipleEntries() throws {
        let json = """
        [
            {
                "id": 1,
                "fix_id": "fix-a",
                "status": "pending",
                "confidence": 0.9,
                "occurrences": 5,
                "blunt_summary": "First.",
                "evidence": ["a", "b"],
                "novel": false,
                "updated_at": "2026-07-01T00:00:00Z",
                "has_action": true,
                "action_label": "Run it"
            },
            {
                "id": 2,
                "fix_id": "fix-b",
                "status": "dismissed",
                "confidence": 0.3,
                "occurrences": 1,
                "blunt_summary": "Second.",
                "evidence": [],
                "novel": true,
                "updated_at": "2026-07-02T00:00:00Z",
                "has_action": false,
                "action_label": null
            }
        ]
        """
        let decoded = try decoder.decode([LedgerEntry].self, from: Data(json.utf8))
        XCTAssertEqual(decoded.count, 2)
        XCTAssertEqual(decoded[0].status, "pending")
        XCTAssertEqual(decoded[1].status, "dismissed")
        XCTAssertNil(decoded[1].actionLabel)
    }
}
