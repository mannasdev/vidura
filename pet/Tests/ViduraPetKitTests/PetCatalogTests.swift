import XCTest
@testable import ViduraPetKit

/// Pins down `PetCatalog`'s two-list invariant — the deliberate asymmetry
/// between what the picker *offers* (`pickable`) and what the core can
/// *earn* (`allCharacterIds`). The single most important rule here is that
/// `"face"` (the "still getting to know you" placeholder) is a real earned
/// id but is NOT a hand-pinnable identity: it must live in `allCharacterIds`
/// yet never appear as a picker row. If a future edit blurs that line —
/// dropping `face` from the earned set, or leaking it into the picker — the
/// picker would either let someone pin "we don't know you yet" or
/// `PetResolution` would treat a valid earned id as stale. These tests fail
/// loudly in either direction.
final class PetCatalogTests: XCTestCase {

    /// Auto is the picker's first row by contract: `PetsView` relies on the
    /// Auto (Earned) mode sitting at the top, and `isAuto` keys off the
    /// reserved `"auto"` sentinel. Pin both the position and the id so a
    /// reordering can't silently demote Auto or rename its sentinel.
    func test_pickableFirstRowIsAuto() {
        XCTAssertEqual(PetCatalog.pickable.first?.id, "auto")
        XCTAssertEqual(PetCatalog.pickable.first?.isAuto, true)
    }

    /// `"face"` is intentionally absent from the picker: it is a "we don't
    /// know you yet" state, not an identity, so letting someone pin it is
    /// semantically incoherent. It must be reachable only through Auto.
    func test_pickableDoesNotContainFace() {
        XCTAssertFalse(
            PetCatalog.pickable.contains { $0.id == "face" },
            "face is an earned-only placeholder and must never appear as a pinnable picker row"
        )
    }

    /// The earned set is the authority `PetResolution` trusts to decide
    /// whether a stored id is still valid. It must be exactly the six real
    /// character ids the Python core can emit — including `"face"` and
    /// EXCLUDING the picker-only `"auto"` sentinel (which is a UI mode, not
    /// a species the core ever earns).
    func test_allCharacterIdsAreExactlyTheSixRealSpecies() {
        XCTAssertEqual(
            PetCatalog.allCharacterIds,
            ["temple-cat", "founder", "robot", "turtleneck", "dad", "face"]
        )
    }

    /// Spelled out separately from the set-equality check so a failure names
    /// the exact violated invariant: `face` belongs (real earned id) and
    /// `auto` does not (picker sentinel, never earned).
    func test_allCharacterIdsIncludesFaceButNotAuto() {
        XCTAssertTrue(
            PetCatalog.allCharacterIds.contains("face"),
            "face is a real earned id and must be a valid (non-stale) stored character"
        )
        XCTAssertFalse(
            PetCatalog.allCharacterIds.contains("auto"),
            "auto is a picker-only sentinel, never a species the core earns"
        )
    }

    /// Every offered row must carry usable copy: `PetsView` renders the name
    /// as the row title and the description as its "what you get" line, so a
    /// blank in either would show an empty picker row. (Tagline is exercised
    /// elsewhere; name + description are the load-bearing on-screen text.)
    func test_everyPickableRowHasNonEmptyNameAndDescription() {
        for pet in PetCatalog.pickable {
            XCTAssertFalse(
                pet.displayName.isEmpty,
                "\(pet.id) has an empty displayName — the row title would render blank"
            )
            XCTAssertFalse(
                pet.description.isEmpty,
                "\(pet.id) has an empty description — the 'what you get' line would render blank"
            )
        }
    }

    /// `info(for:)` is the picker's id → row lookup. For a real pickable id
    /// it must return that exact row (identity, not a copy of shared copy).
    func test_infoReturnsMatchingPickableEntry() {
        let founder = PetCatalog.info(for: "founder")
        XCTAssertEqual(founder?.id, "founder")
        XCTAssertEqual(founder, PetCatalog.pickable.first { $0.id == "founder" })
    }

    /// The lookup is deliberately scoped to `pickable`, so `"face"` — a real
    /// earned id with no picker row — must return `nil`. This is the
    /// asymmetry made observable: face is a valid character yet not a
    /// pickable one.
    func test_infoForFaceIsNilBecauseItHasNoPickerRow() {
        XCTAssertNil(PetCatalog.info(for: "face"))
    }

    /// A genuinely unknown id (never a character, never a sentinel) must
    /// resolve to `nil` rather than crashing or returning a stray row.
    func test_infoForUnknownIdIsNil() {
        XCTAssertNil(PetCatalog.info(for: "not-a-real-id"))
    }
}
