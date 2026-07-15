import XCTest
@testable import ViduraPetKit

/// Locks the `LoginItemControlling` seam (spec §8.1, §12) that `SettingsView`'s
/// launch-at-login toggle depends on. We never touch the real `SMAppService` —
/// it mutates the OS login-item registry and can't run in a unit test — so
/// these tests exercise the *protocol contract* through an in-memory fake. The
/// point isn't to test `LaunchAtLogin` itself; it's to prove the seam is
/// injectable and behaves the way the view assumes: `setEnabled(_:)` flips
/// `isEnabled`, and `isAvailable` is an independent read the view gates on.
final class LaunchAtLoginTests: XCTestCase {

    /// An in-memory `LoginItemControlling` standing in for `LaunchAtLogin`.
    ///
    /// A `struct` to match how the seam is passed around (the production
    /// `LaunchAtLogin` is a value type too), but `setEnabled(_:)` is
    /// non-`mutating` in the protocol — the real one talks to the system, not
    /// to stored state — so the fake routes its mutable bits through a tiny
    /// reference-type box. That keeps the fake copyable and shareable while
    /// still letting `setEnabled` record the flip that a real call would.
    struct FakeLoginItem: LoginItemControlling {
        /// Reference box so a non-`mutating` `setEnabled` can persist a change
        /// visible through the value-type fake (and any copies of it).
        final class State {
            var isEnabled: Bool
            var isAvailable: Bool
            /// Whether `setEnabled` should throw, modelling the OS refusing the
            /// change even when the control believed it could act.
            var shouldThrowOnSet: Bool
            /// Every value `setEnabled` was asked to apply, in order — lets a
            /// test assert *intent was recorded* even when availability or a
            /// throw means the effective state didn't move.
            var recordedIntents: [Bool] = []

            init(isEnabled: Bool, isAvailable: Bool, shouldThrowOnSet: Bool) {
                self.isEnabled = isEnabled
                self.isAvailable = isAvailable
                self.shouldThrowOnSet = shouldThrowOnSet
            }
        }

        let state: State

        init(isEnabled: Bool = false,
             isAvailable: Bool = true,
             shouldThrowOnSet: Bool = false) {
            self.state = State(isEnabled: isEnabled,
                               isAvailable: isAvailable,
                               shouldThrowOnSet: shouldThrowOnSet)
        }

        var isAvailable: Bool { state.isAvailable }
        var isEnabled: Bool { state.isEnabled }

        /// A stub `setEnabled` that models an OS the caller has already gated
        /// on `isAvailable`: it always *records the intent*, then either throws
        /// (if configured) or commits the new value to the shared state.
        func setEnabled(_ enabled: Bool) throws {
            state.recordedIntents.append(enabled)
            if state.shouldThrowOnSet {
                throw FakeError.refused
            }
            state.isEnabled = enabled
        }

        enum FakeError: Error { case refused }
    }

    // MARK: - Core contract: setEnabled flips isEnabled

    func test_setEnabledTrue_registersLoginItem() throws {
        let item = FakeLoginItem(isEnabled: false)

        try item.setEnabled(true)

        XCTAssertTrue(item.isEnabled)
    }

    func test_setEnabledFalse_unregistersLoginItem() throws {
        let item = FakeLoginItem(isEnabled: true)

        try item.setEnabled(false)

        XCTAssertFalse(item.isEnabled)
    }

    func test_toggleRoundTrips() throws {
        let item = FakeLoginItem(isEnabled: false)

        try item.setEnabled(true)
        XCTAssertTrue(item.isEnabled)

        try item.setEnabled(false)
        XCTAssertFalse(item.isEnabled)
    }

    // MARK: - isAvailable is an independent read the view gates on

    func test_isAvailable_isIndependentOfIsEnabled() {
        // Unavailable (no bundle) but happens to be "enabled": the view uses
        // isAvailable to decide whether to offer the toggle at all, so the two
        // reads must not be coupled.
        let unavailable = FakeLoginItem(isEnabled: true, isAvailable: false)
        XCTAssertFalse(unavailable.isAvailable)
        XCTAssertTrue(unavailable.isEnabled)

        let available = FakeLoginItem(isEnabled: false, isAvailable: true)
        XCTAssertTrue(available.isAvailable)
        XCTAssertFalse(available.isEnabled)
    }

    /// Even when the control is unavailable, `setEnabled` still honours the
    /// protocol contract: it records the intent it was handed. The real
    /// contract is "gate on `isAvailable` first"; this documents that the fake
    /// doesn't silently swallow calls, so a test can prove the view never
    /// *asked* for a change it shouldn't have.
    func test_unavailableControl_stillRecordsIntent() throws {
        let item = FakeLoginItem(isEnabled: false, isAvailable: false)

        try item.setEnabled(true)

        XCTAssertEqual(item.state.recordedIntents, [true])
    }

    // MARK: - Throwing seam mirrors SMAppService refusing the change

    func test_setEnabledThrows_leavesStateUnchanged_butRecordsIntent() {
        let item = FakeLoginItem(isEnabled: false, shouldThrowOnSet: true)

        XCTAssertThrowsError(try item.setEnabled(true))
        // The failed call must not have flipped the live state...
        XCTAssertFalse(item.isEnabled)
        // ...yet the attempt is still recorded, matching real setEnabled which
        // reaches SMAppService before it can throw.
        XCTAssertEqual(item.state.recordedIntents, [true])
    }

    // MARK: - Value-type fake shares state across copies (mirrors injection)

    func test_fakeIsUsableAsProtocolExistential() throws {
        // How SettingsView actually holds it: as `any LoginItemControlling`,
        // not the concrete type. Prove the seam works through the abstraction.
        let control: any LoginItemControlling = FakeLoginItem(isEnabled: false)

        try control.setEnabled(true)

        XCTAssertTrue(control.isEnabled)
    }
}
