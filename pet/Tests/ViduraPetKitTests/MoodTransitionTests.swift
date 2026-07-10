import XCTest
@testable import ViduraPetKit

/// Pins down the one notification the app ever sends: it must fire ONLY
/// on the transition INTO STIRRING, never while staying in it and never
/// on transitions between two non-STIRRING moods.
final class MoodTransitionTests: XCTestCase {
    func test_nilToStirring_notifies() {
        XCTAssertTrue(MoodTransition.shouldNotify(previous: nil, current: Mood.stirring.rawValue))
    }

    func test_contentToStirring_notifies() {
        XCTAssertTrue(
            MoodTransition.shouldNotify(previous: Mood.content.rawValue, current: Mood.stirring.rawValue)
        )
    }

    func test_stirringToStirring_doesNotNotify() {
        XCTAssertFalse(
            MoodTransition.shouldNotify(previous: Mood.stirring.rawValue, current: Mood.stirring.rawValue)
        )
    }

    func test_stirringToContent_doesNotNotify() {
        XCTAssertFalse(
            MoodTransition.shouldNotify(previous: Mood.stirring.rawValue, current: Mood.content.rawValue)
        )
    }

    func test_contentToContent_doesNotNotify() {
        XCTAssertFalse(
            MoodTransition.shouldNotify(previous: Mood.content.rawValue, current: Mood.content.rawValue)
        )
    }

    func test_nilToNonStirring_doesNotNotify() {
        XCTAssertFalse(MoodTransition.shouldNotify(previous: nil, current: Mood.asleep.rawValue))
    }
}
