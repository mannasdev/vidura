import XCTest
@testable import ViduraPetKit

/// Pins down `PetResolution.resolve(selection:earned:)` — the one rule that
/// reconciles the user's Pets-picker choice against the character the core
/// actually diagnosed (spec § "Pet model": *override with an Auto option;
/// mood always core-driven*).
///
/// Every case deliberately uses an `earned` value distinct from `selection`,
/// so a test that expects `earned` back could never pass by accidentally
/// echoing the selection (and vice versa) — the returned identity alone tells
/// us which branch fired.
final class PetResolutionTests: XCTestCase {
    /// "Auto (Earned)" defers entirely to the core: whatever the diagnosis
    /// earned is what renders, regardless of what a stale pin might have said.
    func test_autoSelection_yieldsEarnedCharacter() {
        XCTAssertEqual(
            PetResolution.resolve(selection: Preferences.autoSelection, earned: "founder"),
            "founder"
        )
    }

    /// A real pin to a shipped species honors that pin — it swaps the costume,
    /// not the mood — so the earned diagnosis is ignored for identity purposes.
    func test_validPinnedId_yieldsItself() {
        XCTAssertEqual(
            PetResolution.resolve(selection: "founder", earned: "robot"),
            "founder"
        )
    }

    /// `"face"` is a real earned id (the "still getting to know you" state) and
    /// lives in `allCharacterIds`, so if it somehow arrives as a selection it is
    /// treated as valid and returned as-is rather than falling back to earned.
    func test_faceIsAValidId_yieldsItself() {
        XCTAssertEqual(
            PetResolution.resolve(selection: "face", earned: "temple-cat"),
            "face"
        )
    }

    /// An unknown / stale id (a species removed or renamed after the user
    /// pinned it, or a hand-edited defaults value) must not be trusted: it
    /// falls back to the core's earned diagnosis, never crashing or blanking.
    func test_unknownId_fallsBackToEarned() {
        XCTAssertEqual(
            PetResolution.resolve(selection: "dragon", earned: "turtleneck"),
            "turtleneck"
        )
    }
}
