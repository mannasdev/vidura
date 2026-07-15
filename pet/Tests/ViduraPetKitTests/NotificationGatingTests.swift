import XCTest
@testable import ViduraPetKit

/// Pins down the AND-gate that guards the STIRRING OS banner
/// (`StateModel.shouldFireStirring`). The banner is the one piece of
/// user-facing noise the app can push, so its firing rule must be exact:
/// it fires ONLY when the mood actually transitioned into STIRRING
/// (`transitionNotify`, decided by `MoodTransition.shouldNotify`) AND the
/// user has left notifications enabled. All three other input combinations
/// must stay silent.
///
/// This is deliberately the *whole* truth table rather than one happy-path
/// case: the two most costly regressions here are opposite failures —
/// notifying when the user muted us, and dropping the banner on a real
/// transition — so both "false" axes are asserted independently. Because the
/// helper is `static` and pure, no running `StateModel`, `Preferences`, or
/// `UNUserNotificationCenter` is needed, and the test needs no `@MainActor`.
final class NotificationGatingTests: XCTestCase {
    /// The single case that must fire: real transition + notifications on.
    func test_firesOnlyWhenBothEnabledAndTransition() {
        XCTAssertTrue(
            StateModel.shouldFireStirring(notificationsEnabled: true, transitionNotify: true)
        )
    }

    /// User muted notifications: even a genuine transition stays silent.
    /// (The in-panel "counsel earned" cue is handled separately and is not
    /// gated by this helper — see `applyNewMood`.)
    func test_suppressedWhenNotificationsDisabled() {
        XCTAssertFalse(
            StateModel.shouldFireStirring(notificationsEnabled: false, transitionNotify: true)
        )
    }

    /// No transition into STIRRING this poll: nothing to announce, so the
    /// banner stays silent regardless of the notification preference.
    func test_suppressedWhenNoTransition() {
        XCTAssertFalse(
            StateModel.shouldFireStirring(notificationsEnabled: true, transitionNotify: false)
        )
    }

    /// Neither axis satisfied — the trivially-silent corner of the table,
    /// asserted so a future change to the gate's default can't slip through.
    func test_suppressedWhenNeither() {
        XCTAssertFalse(
            StateModel.shouldFireStirring(notificationsEnabled: false, transitionNotify: false)
        )
    }
}
