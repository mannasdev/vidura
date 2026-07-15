import Foundation

/// Pure decision logic for *which character sprite the popover draws* — the
/// one place that reconciles the user's Pets-picker choice against the
/// character the core actually diagnosed.
///
/// The load-bearing invariant here is a separation of concerns: pinning a
/// pet changes **only the sprite that renders**. It never touches MOOD. The
/// core (via `vidura-state` -> `MoodState.effectiveCharacter`) still owns
/// the entire asleep/stirring/proud diagnosis, the menu-bar badge, the
/// STIRRING notification, and the suggestion cards. So a user who pins the
/// Founder still watches that Founder wake into STIRRING when counsel is
/// earned — the pin swapped the costume, not the behavior (spec §
/// "Pet model": *override with an Auto option; mood always core-driven*).
///
/// Kept as a free `enum` with a single static method — no state, no
/// `@MainActor`, no I/O — precisely so the resolution rule can be
/// exhaustively unit-tested without a running `StateModel` or `Preferences`
/// store, mirroring how `MoodTransition.shouldNotify` isolates the
/// notification rule.
public enum PetResolution {
    /// Which character id to actually render.
    ///
    /// - Parameters:
    ///   - selection: the user's persisted preference — either the
    ///     `Preferences.autoSelection` sentinel (`"auto"`, meaning "let the
    ///     core decide") or a specific pinned character id.
    ///   - earned: the core-diagnosed character, i.e.
    ///     `StateModel`'s `mood?.effectiveCharacter` (already defaulted by
    ///     the caller to `CharacterAsset.defaultCharacter` when the CLI is
    ///     pre-character-system and omits the field).
    /// - Returns: the character id whose sprite should be drawn. Note this
    ///   only chooses the *identity*; `CharacterAsset.characterImage` still
    ///   applies its own three-step art fallback on top, so an id that
    ///   resolves here but lacks a rendered frame degrades gracefully rather
    ///   than blanking.
    public static func resolve(selection: String, earned: String) -> String {
        // Explicit "Auto (Earned)" — defer entirely to the core's diagnosis
        // (today's behavior, unchanged for users who never open the picker).
        if selection == Preferences.autoSelection { return earned }
        // A real pin: honor it only if it names a character we actually ship.
        if PetCatalog.allCharacterIds.contains(selection) { return selection }
        // Unknown / stale id (e.g. a character removed or renamed after the
        // user pinned it, or a hand-edited defaults value): fall back to Auto
        // behavior rather than trusting a dangling pin. No crash, no blank.
        return earned
    }
}
