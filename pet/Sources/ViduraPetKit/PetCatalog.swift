import Foundation

/// One row's worth of display data for the Pets picker: the identity the
/// user can pin, its one-line tagline, and the "what you get" description.
///
/// This is deliberately view-model-shaped rather than a raw string map:
/// `PetsView` renders `PetInfo` directly (thumbnail + name + description +
/// selected check), so keeping name/tagline/description together as one
/// value keeps the picker's copy in a single reviewable place instead of
/// scattered across the view. It carries no art or I/O of its own — sprite
/// loading stays entirely in `CharacterAsset`, keyed off `id`.
public struct PetInfo: Equatable, Identifiable {
    /// The character id the core speaks in (`"founder"`, `"temple-cat"`,
    /// …), OR the reserved `"auto"` sentinel for the Auto (Earned) row.
    /// This is the value written to `Preferences.selectedPet` when the row
    /// is picked, and the key `CharacterAsset.characterImage` loads art by.
    public let id: String
    /// Human name shown as the row title (e.g. "Temple Cat").
    public let displayName: String
    /// A terse mood-of-the-species line, echoing the spirit of the
    /// `character.py` reason strings (e.g. "Relentless velocity").
    public let tagline: String
    /// The "what you get" line: the earned diagnosis reframed as a
    /// choose-able identity, so the picker never contradicts the core.
    public let description: String

    /// True only for the Auto (Earned) row. Auto is not a species — it
    /// defers to the core's live diagnosis — so the picker treats it
    /// specially (no pinning; it renders whatever is currently earned).
    public var isAuto: Bool { id == "auto" }

    public init(id: String, displayName: String, tagline: String, description: String) {
        self.id = id
        self.displayName = displayName
        self.tagline = tagline
        self.description = description
    }
}

/// Pure catalog data for the Pets picker — character id → display info,
/// in the picker's display order. No I/O, no persistence, no art: this is
/// the single source of truth for *what copy the picker shows* and *which
/// ids are real*, and nothing else. Persistence lives in `Preferences`,
/// resolution in `PetResolution`, art in `CharacterAsset`.
///
/// All copy here is derived faithfully from `vidura/character.py`'s reason
/// strings (the same sentences `vidura-state` surfaces as
/// `character_reason`), so a manually-pinned pet never describes itself
/// differently from how the diagnosis would. Keep it in sync if those
/// rules change.
public enum PetCatalog {
    /// The rows the picker shows, in this exact top-to-bottom order: the
    /// Auto (Earned) mode first, then the five *pinnable* species. This is
    /// intentionally NOT every real character — see `face` in
    /// `allCharacterIds` for the one earned id we deliberately omit here.
    public static let pickable: [PetInfo] = [
        PetInfo(
            id: "auto",
            displayName: "Auto (Earned)",
            tagline: "Diagnosed from how you work",
            description: "Let Vidura decide. Your pet is diagnosed from how you have actually worked over the last 14 days, and it changes as you do."
        ),
        PetInfo(
            id: "temple-cat",
            displayName: "Temple Cat",
            tagline: "Balanced practice",
            description: "The steady baseline: neither grinding nor idle."
        ),
        PetInfo(
            id: "founder",
            displayName: "Founder",
            tagline: "Relentless velocity",
            description: "Many sessions a day, long hours, shipping hard."
        ),
        PetInfo(
            id: "robot",
            displayName: "Robot",
            tagline: "Grinding through error loops",
            description: "Long heads-down sessions and high error counts."
        ),
        PetInfo(
            id: "turtleneck",
            displayName: "Turtleneck",
            tagline: "Careful, unhurried craft",
            description: "Few, deliberate sessions: quality over speed."
        ),
        PetInfo(
            id: "dad",
            displayName: "Dad",
            tagline: "Means well",
            description: "Accepts the advice and does not change. Warm, a little exasperated."
        ),
    ]

    /// Every REAL character id the Python core (`vidura/character.py`) can
    /// emit as the earned species — all six, INCLUDING `"face"`.
    ///
    /// Note the deliberate asymmetry with `pickable`: `"face"` is a real
    /// earned id (the "insufficient data / still getting to know you"
    /// placeholder the core assigns before it has `MIN_SESSIONS` sessions
    /// to read you), so it belongs here and CAN legitimately appear via
    /// Auto. But it is intentionally absent from `pickable`: `face` is a
    /// "we don't know you yet" state, not an identity, and letting someone
    /// manually pin "we don't know you yet" is semantically incoherent.
    /// So it is reachable only through Auto, never chosen by hand.
    ///
    /// This set is the authority `PetResolution` uses to decide whether a
    /// stored/pinned id is still valid (an id not in this set is stale and
    /// falls back to Auto behavior).
    public static let allCharacterIds: Set<String> = [
        "temple-cat", "founder", "robot", "turtleneck", "dad", "face",
    ]

    /// The `PetInfo` for a picker id, or `nil` if the id is not a pickable
    /// row. Note this is scoped to `pickable`, so `info(for: "face")`
    /// returns `nil` by design (face has no picker row) — it is a lookup
    /// for the picker UI, not a general id→metadata map.
    public static func info(for id: String) -> PetInfo? {
        pickable.first { $0.id == id }
    }
}
