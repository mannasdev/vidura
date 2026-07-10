import XCTest
@testable import ViduraPetKit

/// Pins down `CharacterCaption.line` — the click-to-reveal caption
/// text under the header (spec item 4): `character_reason` plus a
/// "since <relative date>" suffix built from `character_since`, tolerant
/// of either field being absent (old-CLI compatibility).
final class CharacterCaptionTests: XCTestCase {
    private let now = ISO8601DateFormatter().date(from: "2026-07-10T00:00:00Z")!

    func test_fullReasonAndSince_formatsWithRelativeSuffix() {
        let line = CharacterCaption.line(
            reason: "The Founder \u{2014} 41 sessions and 52 hours in 14 days",
            since: "2026-06-28T00:00:00Z",
            now: now
        )
        XCTAssertEqual(
            line,
            "The Founder \u{2014} 41 sessions and 52 hours in 14 days · since 12 days ago"
        )
    }

    /// Missing `character_since` (old CLI, or a genuinely absent value):
    /// the reason renders alone, with no dangling "since" suffix.
    func test_missingSince_omitsSuffix() {
        let line = CharacterCaption.line(
            reason: "The Founder \u{2014} 41 sessions and 52 hours in 14 days",
            since: nil,
            now: now
        )
        XCTAssertEqual(line, "The Founder \u{2014} 41 sessions and 52 hours in 14 days")
    }

    /// Unparseable `character_since` string must not crash or show a
    /// bogus date — degrades exactly like a missing value.
    func test_unparseableSince_omitsSuffix() {
        let line = CharacterCaption.line(
            reason: "The Founder \u{2014} 41 sessions and 52 hours in 14 days",
            since: "not-a-date",
            now: now
        )
        XCTAssertEqual(line, "The Founder \u{2014} 41 sessions and 52 hours in 14 days")
    }

    /// Both fields missing entirely (old CLI, defaulted "temple-cat"
    /// look): falls back to a generic, never-blank sentence.
    func test_missingReasonAndSince_fallsBackToGenericSentence() {
        let line = CharacterCaption.line(reason: nil, since: nil, now: now)
        XCTAssertEqual(line, "Balanced practice — still learning your rhythm.")
    }

    /// An empty-string reason (defensive: some producer sends "" rather
    /// than omitting the key) is treated the same as missing.
    func test_emptyReason_fallsBackToGenericSentence() {
        let line = CharacterCaption.line(reason: "", since: nil, now: now)
        XCTAssertEqual(line, "Balanced practice — still learning your rhythm.")
    }
}
