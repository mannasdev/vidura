import XCTest
@testable import ViduraPetKit

/// Pins down the governing invariant: THE PET ONLY MOVES WHERE THE USER
/// IS ALREADY LOOKING. Reduce Motion must zero/disable every knob, the
/// tuned constants must stay within the bounds the invariant requires,
/// and the menu-bar source (AppDelegate.swift) must never touch an
/// animation API — a tripwire so nobody ever animates the menu bar.
final class AnimationPolicyTests: XCTestCase {
    // MARK: - Reduce Motion collapses everything

    func test_reduceMotion_disablesBreathing() {
        let policy = AnimationPolicy(reduceMotion: true)
        XCTAssertFalse(policy.breathingEnabled)
    }

    func test_reduceMotion_disablesMicroMotion() {
        let policy = AnimationPolicy(reduceMotion: true)
        XCTAssertFalse(policy.microMotionEnabled)
    }

    func test_reduceMotion_zeroesCrossfadeDuration() {
        let policy = AnimationPolicy(reduceMotion: true)
        XCTAssertEqual(policy.crossfadeDuration, 0)
    }

    func test_reduceMotion_disablesCelebration() {
        let policy = AnimationPolicy(reduceMotion: true)
        XCTAssertFalse(policy.celebrationEnabled)
    }

    // MARK: - Motion allowed when Reduce Motion is off

    func test_motionAllowed_enablesBreathing() {
        let policy = AnimationPolicy(reduceMotion: false)
        XCTAssertTrue(policy.breathingEnabled)
    }

    func test_motionAllowed_enablesMicroMotion() {
        let policy = AnimationPolicy(reduceMotion: false)
        XCTAssertTrue(policy.microMotionEnabled)
    }

    func test_motionAllowed_nonZeroCrossfadeDuration() {
        let policy = AnimationPolicy(reduceMotion: false)
        XCTAssertEqual(policy.crossfadeDuration, 0.2)
    }

    func test_motionAllowed_enablesCelebration() {
        let policy = AnimationPolicy(reduceMotion: false)
        XCTAssertTrue(policy.celebrationEnabled)
    }

    // MARK: - Tuned constants satisfy the invariant bounds

    func test_breathingPeriod_isAtLeastFourSeconds() {
        XCTAssertGreaterThanOrEqual(AnimationPolicy.breathingPeriod, 4.0)
    }

    func test_breathingAmplitude_isAtMostThreePoints() {
        XCTAssertLessThanOrEqual(AnimationPolicy.breathingAmplitude, 3)
    }

    func test_crossfadeDuration_isAtMostQuarterSecond() {
        let policy = AnimationPolicy(reduceMotion: false)
        XCTAssertLessThanOrEqual(policy.crossfadeDuration, 0.25)
    }

    func test_microMotionInterval_rangeIsSaneAndOrdered() {
        XCTAssertLessThan(AnimationPolicy.microMotionMinInterval, AnimationPolicy.microMotionMaxInterval)
        XCTAssertGreaterThanOrEqual(AnimationPolicy.microMotionMinInterval, 6.0)
        XCTAssertLessThanOrEqual(AnimationPolicy.microMotionMaxInterval, 12.0)
    }

    // MARK: - Tripwire: the menu bar itself must never animate

    /// AppDelegate owns the status item / menu bar glyph exclusively.
    /// The governing invariant is that the menu bar NEVER animates — all
    /// motion lives inside the panel content (CardView/CharacterAsset).
    /// This greps the actual source file so a future edit that sneaks an
    /// animation API into AppDelegate fails a test instead of shipping.
    func test_appDelegateSource_containsNoAnimationAPIUsage() throws {
        let thisFile = URL(fileURLWithPath: #filePath)
        let appDelegatePath = thisFile
            .deletingLastPathComponent() // Tests/ViduraPetKitTests
            .deletingLastPathComponent() // Tests
            .deletingLastPathComponent() // package root
            .appendingPathComponent("Sources/ViduraPetKit/AppDelegate.swift")

        let source = try String(contentsOf: appDelegatePath, encoding: .utf8)

        let forbiddenTokens = ["withAnimation", "NSAnimation", ".animation("]
        for token in forbiddenTokens {
            XCTAssertFalse(
                source.contains(token),
                "AppDelegate.swift must never use \(token) — the menu bar never animates."
            )
        }
    }
}
