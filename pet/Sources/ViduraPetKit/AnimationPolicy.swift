import Foundation
#if canImport(AppKit)
import AppKit
#endif

/// Pure, testable policy gating every animation the panel is allowed to
/// run. THE PET ONLY MOVES WHERE THE USER IS ALREADY LOOKING: the menu
/// bar itself never animates (see AppDelegate — no animation API is used
/// there at all), and everything this policy governs lives inside the
/// open panel's content. System Reduce Motion is the master switch: when
/// it's on, every knob here collapses to "off" or "instant".
public struct AnimationPolicy {
    public let reduceMotion: Bool

    public init(reduceMotion: Bool) {
        self.reduceMotion = reduceMotion
    }

    /// Slow vertical bob, gated off entirely under Reduce Motion.
    public var breathingEnabled: Bool { !reduceMotion }

    /// Tiny rotation nudge every 6-12s, gated off entirely under Reduce
    /// Motion.
    public var microMotionEnabled: Bool { !reduceMotion }

    /// Mood-crossfade duration: instant (0) under Reduce Motion, 0.2s
    /// otherwise.
    public var crossfadeDuration: Double { reduceMotion ? 0 : 0.2 }

    /// The one-time celebration hop when adopted_uncelebrated is
    /// non-empty at panel-open. The celebration *banner* always shows
    /// regardless — only the hop motion is gated here.
    public var celebrationEnabled: Bool { !reduceMotion }

    /// Breathing cycle period, in seconds. Invariant: MUST be >= 4 — slow
    /// enough that it reads as ambient, not attention-seeking.
    public static let breathingPeriod: Double = 5.0

    /// Breathing vertical travel, in points. Invariant: MUST be <= 3 — a
    /// barely-perceptible bob, not a bounce.
    public static let breathingAmplitude: CGFloat = 2

    /// Micro-motion fires on a random interval in this range (seconds).
    public static let microMotionMinInterval: Double = 6
    public static let microMotionMaxInterval: Double = 12

    /// Production source: macOS's system-wide Reduce Motion toggle.
    /// Read once at view appearance (v1: no live observation of changes
    /// mid-session — the user would need to reopen the panel to pick up
    /// a toggle flipped while it's open).
    public static var systemReduceMotion: Bool {
        #if canImport(AppKit)
        return NSWorkspace.shared.accessibilityDisplayShouldReduceMotion
        #else
        return false
        #endif
    }
}
