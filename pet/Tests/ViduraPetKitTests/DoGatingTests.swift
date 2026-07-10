import XCTest
@testable import ViduraPetKit

/// Guards the consent-integrity invariant: the Do confirmation sheet may
/// only ever show a live Confirm button when the dry-run genuinely
/// succeeded (exit 0, non-empty stdout). Any failure — nonzero exit,
/// empty stdout, timeout, missing binary — must disable Confirm.
/// `DryRunOutcome.confirmEnabled` is the single source of truth the view
/// switches on, so this pins it down directly.
final class DoGatingTests: XCTestCase {
    func test_success_enablesConfirm() {
        let outcome = DryRunOutcome.success(preview: "would run: fix-123")
        XCTAssertTrue(outcome.confirmEnabled)
    }

    func test_failure_disablesConfirm() {
        let outcome = DryRunOutcome.failure(message: "Dry run failed: exited 1")
        XCTAssertFalse(outcome.confirmEnabled)
    }

    func test_timeoutStyleFailure_disablesConfirm() {
        let outcome = DryRunOutcome.failure(message: "vidura-do timed out")
        XCTAssertFalse(outcome.confirmEnabled)
    }

    func test_emptyPreviewFailure_disablesConfirm() {
        let outcome = DryRunOutcome.failure(message: "Dry run produced no preview.")
        XCTAssertFalse(outcome.confirmEnabled)
    }
}
