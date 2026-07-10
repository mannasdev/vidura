import XCTest
import SwiftUI
@testable import ViduraPetKit

/// Would have caught bug #2: the panel's content sat in a fixed 480pt
/// frame regardless of how much (or little) content it actually had,
/// leaving a void under a short empty state. These measure CardView's
/// own `fittingSize` directly via NSHostingView, the same measurement
/// AppDelegate.positionPanel relies on, so a regression to a fixed-height
/// layout fails here before it ever reaches a screen.
@MainActor
final class ContentSizingTests: XCTestCase {
    private func fittingSize(for state: StateModel) -> CGSize {
        let content = CardView(state: state)
            .frame(width: 400)
            .fixedSize(horizontal: false, vertical: true)
        let hostingView = NSHostingView(rootView: content)
        hostingView.layoutSubtreeIfNeeded()
        return hostingView.fittingSize
    }

    func test_emptyState_heightIsBelowVoidThreshold() {
        let state = StateModel(preview: [], mood: nil)
        let size = fittingSize(for: state)
        // The old fixed-height regression pinned this at 480pt regardless
        // of content; the empty state's real content is short.
        XCTAssertLessThan(size.height, 320)
    }

    func test_threeEntries_tallerThanEmptyState() {
        let emptyState = StateModel(preview: [], mood: nil)
        let emptyHeight = fittingSize(for: emptyState).height

        let entries = (1...3).map { makeEntry(id: $0) }
        let filledState = StateModel(preview: entries, mood: nil)
        let filledHeight = fittingSize(for: filledState).height

        XCTAssertGreaterThan(filledHeight, emptyHeight)
    }

    func test_widthIsAlways400_empty() {
        let state = StateModel(preview: [], mood: nil)
        XCTAssertEqual(fittingSize(for: state).width, 400)
    }

    func test_widthIsAlways400_withEntries() {
        let entries = (1...3).map { makeEntry(id: $0) }
        let state = StateModel(preview: entries, mood: nil)
        XCTAssertEqual(fittingSize(for: state).width, 400)
    }

    private func makeEntry(id: Int) -> LedgerEntry {
        LedgerEntry(
            id: id,
            fixId: "fix-\(id)",
            status: "pending",
            confidence: 0.8,
            occurrences: 3,
            bluntSummary: "You keep doing the thing that doesn't work, entry \(id).",
            evidence: ["quote one", "quote two"],
            novel: false,
            updatedAt: "2026-07-10T00:00:00Z",
            hasAction: false,
            actionLabel: nil
        )
    }
}
