import XCTest
@testable import ViduraPetKit

/// Pins down `CharacterAsset.characterImage(character:mood:)`'s fallback
/// chain (spec item 3): exact hit -> temple-cat same mood -> legacy
/// cat-<mood> -> nil. All 36 `{character}-{mood}.png` combos delivered in
/// design-export/characters must resolve via Bundle.module (exact hit),
/// and an unknown character id must still resolve a usable image through
/// the fallback chain rather than ever returning nil for a known mood.
final class CharacterAssetResolutionTests: XCTestCase {
    private static let allCharacters = [
        "face", "temple-cat", "founder", "turtleneck", "robot", "dad",
    ]

    /// All 6 characters x 6 moods = 36 exact-hit combinations must
    /// resolve — this is the full asset manifest the spec calls for.
    func test_allThirtySixExactCombosResolve() {
        for character in Self.allCharacters {
            for mood in PetMood.allCases {
                XCTAssertNotNil(
                    CharacterAsset.characterImage(character: character, mood: mood),
                    "Expected a bundled PNG for \(character)-\(mood.assetName)"
                )
            }
        }
    }

    /// An unrecognized character id has no exact asset, so resolution
    /// must fall back to temple-cat at the same mood rather than
    /// returning nil (spec's 2nd fallback step is exercised here since
    /// temple-cat assets are always present).
    func test_unknownCharacter_fallsBackToTempleCatSameMood() {
        for mood in PetMood.allCases {
            let fallback = CharacterAsset.characterImage(character: "not-a-real-character", mood: mood)
            let templeCat = CharacterAsset.characterImage(character: "temple-cat", mood: mood)
            XCTAssertNotNil(fallback)
            XCTAssertEqual(
                fallback?.tiffRepresentation, templeCat?.tiffRepresentation,
                "Unknown character at \(mood) should resolve to the temple-cat asset for that mood"
            )
        }
    }

    /// The default character constant itself must resolve for every mood
    /// (sanity check that "temple-cat" is spelled consistently between
    /// the constant and the asset filenames).
    func test_defaultCharacterConstant_resolvesForEveryMood() {
        for mood in PetMood.allCases {
            XCTAssertNotNil(CharacterAsset.characterImage(character: CharacterAsset.defaultCharacter, mood: mood))
        }
    }

    /// `characterImage` must never regress the legacy `image(for:)`
    /// lookup path — this is the final fallback step, exercised directly
    /// so a future refactor can't silently drop it.
    func test_legacyCatAssetsStillResolveDirectly() {
        for mood in PetMood.allCases {
            XCTAssertNotNil(CharacterAsset.image(for: mood))
        }
    }
}
