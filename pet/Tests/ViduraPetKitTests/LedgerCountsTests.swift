import XCTest
@testable import ViduraPetKit

/// The footer's counts line ("N accepted, M dismissed") is derived from
/// the FULL ledger (`vidura-ledger list --json`'s unfiltered result),
/// not the pending-only subset the cards render — these pin that
/// derivation down as pure logic, independent of any live CLI call.
final class LedgerCountsTests: XCTestCase {
    private func makeEntry(id: Int, status: String) -> LedgerEntry {
        LedgerEntry(
            id: id,
            fixId: "fix-\(id)",
            status: status,
            confidence: 0.5,
            occurrences: 1,
            bluntSummary: "Summary \(id).",
            evidence: [],
            novel: false,
            updatedAt: "2026-07-10T00:00:00Z",
            hasAction: false,
            actionLabel: nil
        )
    }

    func test_emptyLedger_zeroCounts() {
        let counts = LedgerCounts.derive(from: [])
        XCTAssertEqual(counts.accepted, 0)
        XCTAssertEqual(counts.dismissed, 0)
    }

    func test_countsOnlyAcceptedAndDismissed_ignoresPending() {
        let entries = [
            makeEntry(id: 1, status: "pending"),
            makeEntry(id: 2, status: "accepted"),
            makeEntry(id: 3, status: "accepted"),
            makeEntry(id: 4, status: "dismissed"),
            makeEntry(id: 5, status: "pending")
        ]
        let counts = LedgerCounts.derive(from: entries)
        XCTAssertEqual(counts.accepted, 2)
        XCTAssertEqual(counts.dismissed, 1)
    }

    /// An unrecognized/future status string must never crash the count —
    /// it simply isn't counted in either bucket.
    func test_unknownStatus_isIgnoredNotCrashing() {
        let entries = [
            makeEntry(id: 1, status: "expired"),
            makeEntry(id: 2, status: "accepted")
        ]
        let counts = LedgerCounts.derive(from: entries)
        XCTAssertEqual(counts.accepted, 1)
        XCTAssertEqual(counts.dismissed, 0)
    }

    func test_allDismissed() {
        let entries = [
            makeEntry(id: 1, status: "dismissed"),
            makeEntry(id: 2, status: "dismissed")
        ]
        let counts = LedgerCounts.derive(from: entries)
        XCTAssertEqual(counts.accepted, 0)
        XCTAssertEqual(counts.dismissed, 2)
    }
}
