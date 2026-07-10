import XCTest
@testable import ViduraPetKit

/// Pins down the footer's "Last counsel · {relative time}" derivation
/// (spec §2.3) — the Python core has no dedicated "last counsel" field,
/// so this is derived client-side from the most recent `updated_at`
/// across the full ledger. All assertions inject a fixed `now` so the
/// suite never depends on the wall clock.
final class RelativeTimeTests: XCTestCase {
    private func makeEntry(id: Int, updatedAt: String) -> LedgerEntry {
        LedgerEntry(
            id: id,
            fixId: "fix-\(id)",
            status: "pending",
            confidence: 0.5,
            occurrences: 1,
            bluntSummary: "Summary \(id).",
            evidence: [],
            novel: false,
            updatedAt: updatedAt,
            hasAction: false,
            actionLabel: nil
        )
    }

    func test_parsesFractionalSecondsISO8601() {
        let date = RelativeTime.parseISO8601("2026-07-01T10:00:00.500Z")
        XCTAssertNotNil(date)
    }

    func test_parsesWholeSecondISO8601() {
        let date = RelativeTime.parseISO8601("2026-07-01T10:00:00Z")
        XCTAssertNotNil(date)
    }

    func test_invalidString_returnsNil() {
        XCTAssertNil(RelativeTime.parseISO8601("not a date"))
    }

    func test_mostRecentUpdate_picksLatestAcrossEntries() {
        let entries = [
            makeEntry(id: 1, updatedAt: "2026-07-01T00:00:00Z"),
            makeEntry(id: 2, updatedAt: "2026-07-05T00:00:00Z"),
            makeEntry(id: 3, updatedAt: "2026-07-03T00:00:00Z")
        ]
        let mostRecent = RelativeTime.mostRecentUpdate(entries)
        XCTAssertEqual(mostRecent, RelativeTime.parseISO8601("2026-07-05T00:00:00Z"))
    }

    func test_mostRecentUpdate_emptyEntries_returnsNil() {
        XCTAssertNil(RelativeTime.mostRecentUpdate([]))
    }

    func test_phrase_sixDaysAgo_matchesMockCopy() {
        let now = RelativeTime.parseISO8601("2026-07-10T00:00:00Z")!
        let sixDaysAgo = RelativeTime.parseISO8601("2026-07-04T00:00:00Z")!
        XCTAssertEqual(RelativeTime.phrase(from: sixDaysAgo, to: now), "6 days ago")
    }

    func test_phrase_oneDayAgo_isSingular() {
        let now = RelativeTime.parseISO8601("2026-07-10T00:00:00Z")!
        let oneDayAgo = RelativeTime.parseISO8601("2026-07-09T00:00:00Z")!
        XCTAssertEqual(RelativeTime.phrase(from: oneDayAgo, to: now), "1 day ago")
    }

    func test_phrase_sameDayFewHours_usesHourGranularity() {
        let now = RelativeTime.parseISO8601("2026-07-10T10:00:00Z")!
        let threeHoursAgo = RelativeTime.parseISO8601("2026-07-10T07:00:00Z")!
        XCTAssertEqual(RelativeTime.phrase(from: threeHoursAgo, to: now), "3 hours ago")
    }

    func test_phrase_justNow_forSubMinuteGap() {
        let now = RelativeTime.parseISO8601("2026-07-10T10:00:30Z")!
        let fewSecondsAgo = RelativeTime.parseISO8601("2026-07-10T10:00:00Z")!
        XCTAssertEqual(RelativeTime.phrase(from: fewSecondsAgo, to: now), "just now")
    }

    func test_lastCounselLine_formatsWithMostRecentEntry() {
        let now = RelativeTime.parseISO8601("2026-07-10T00:00:00Z")!
        let entries = [makeEntry(id: 1, updatedAt: "2026-07-04T00:00:00Z")]
        XCTAssertEqual(
            RelativeTime.lastCounselLine(entries: entries, now: now),
            "Last counsel \u{00B7} 6 days ago"
        )
    }

    func test_lastCounselLine_emptyLedger_fallsBackQuietly() {
        XCTAssertEqual(RelativeTime.lastCounselLine(entries: []), "Last counsel \u{00B7} none yet")
    }
}
