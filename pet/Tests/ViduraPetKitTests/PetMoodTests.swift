import XCTest
@testable import ViduraPetKit

/// Pins down the mood-string → character-asset mapping (spec §5) and
/// its forward-compat fallback: an unrecognized mood string must never
/// crash or show a blank header, it should fall back to `.asleep`.
final class PetMoodTests: XCTestCase {
    func test_allSixMoodsMapToExpectedAssetNames() {
        XCTAssertEqual(PetMood(rawValue: "ASLEEP")?.assetName, "cat-asleep")
        XCTAssertEqual(PetMood(rawValue: "CONTENT")?.assetName, "cat-content")
        XCTAssertEqual(PetMood(rawValue: "STIRRING")?.assetName, "cat-stirring")
        XCTAssertEqual(PetMood(rawValue: "PROUD")?.assetName, "cat-proud")
        XCTAssertEqual(PetMood(rawValue: "CONCERNED")?.assetName, "cat-concerned")
        XCTAssertEqual(PetMood(rawValue: "RECOGNITION")?.assetName, "cat-recognition")
    }

    func test_unknownMoodString_fallsBackToAsleep() {
        XCTAssertEqual(PetMood(rawMood: "SOMETHING_NEW").assetName, "cat-asleep")
    }

    func test_knownMoodString_roundTripsViaFallbackInitializer() {
        XCTAssertEqual(PetMood(rawMood: "STIRRING"), .stirring)
    }

    func test_bundledAssetLoadsForEveryMood() {
        for mood in PetMood.allCases {
            XCTAssertNotNil(
                CharacterAsset.image(for: mood),
                "Expected a bundled PNG for \(mood.assetName)"
            )
        }
    }
}
