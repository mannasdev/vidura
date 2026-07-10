import SwiftUI
#if canImport(AppKit)
import AppKit
#endif

/// Maps the Python core's mood string to one of the six pixel-art
/// character frames delivered in `design-export/cat-*.png` (spec §5).
/// Static image swaps only — no animation, no sound, per the
/// anti-Clippy invariants; the mood simply picks which single frame
/// to render.
public enum PetMood: String, CaseIterable {
    case asleep = "ASLEEP"
    case content = "CONTENT"
    case stirring = "STIRRING"
    case proud = "PROUD"
    case concerned = "CONCERNED"
    case recognition = "RECOGNITION"

    /// Asset name inside `Resources/`, e.g. "cat-asleep".
    var assetName: String {
        "cat-\(rawValue.lowercased())"
    }

    /// Falls back to `.asleep` for any mood string the Swift side
    /// doesn't recognize (forward-compat with a Python core that adds
    /// a mood before Swift ships support for it) rather than crashing
    /// or showing nothing.
    public init(rawMood: String) {
        self = PetMood(rawValue: rawMood) ?? .asleep
    }
}

/// Loads the six character PNGs from the package's bundled resources
/// (`Bundle.module`, populated by `Package.swift`'s `.copy("Resources")`)
/// and caches them — six 384×384px bitmaps is small, but there is no
/// reason to decode the same PNG repeatedly on every header redraw.
public enum CharacterAsset {
    private static var cache: [PetMood: NSImage] = [:]

    static func image(for mood: PetMood) -> NSImage? {
        if let cached = cache[mood] {
            return cached
        }
        guard let url = Bundle.module.url(
            forResource: mood.assetName,
            withExtension: "png",
            subdirectory: "Resources"
        ) ?? Bundle.module.url(
            forResource: mood.assetName,
            withExtension: "png"
        ), let image = NSImage(contentsOf: url) else {
            return nil
        }
        cache[mood] = image
        return image
    }

    /// Default character rendered when no earned character is known yet
    /// (spec: "temple-cat — today's shipped look").
    public static let defaultCharacter = "temple-cat"

    private static var characterCache: [String: NSImage] = [:]

    /// Loads the 36-asset character system's `{character}-{mood}.png`
    /// files from `Resources/characters/`, with a three-step fallback
    /// chain so a bad/unknown character id or a not-yet-shipped asset
    /// never blanks the header (spec item 3):
    ///   1. exact `{character}-{mood}` hit;
    ///   2. `temple-cat-{mood}` (same mood, default character);
    ///   3. the legacy `cat-{mood}` asset (pre-character-system art);
    /// returning `nil` only if all three misses — the caller (
    /// `CharacterPortrait`) already handles a `nil` image with its SF
    /// Symbol placeholder.
    ///
    /// Pure with respect to inputs (aside from the cache, which is only
    /// a memoization of the same bundle lookup and never changes which
    /// image is returned for a given key) — safe to unit test directly.
    public static func characterImage(character: String, mood: PetMood) -> NSImage? {
        let cacheKey = "\(character)-\(mood.rawValue)"
        if let cached = characterCache[cacheKey] {
            return cached
        }

        if let exact = loadCharacterAsset(character: character, mood: mood) {
            characterCache[cacheKey] = exact
            return exact
        }
        if character != defaultCharacter,
           let fallbackCharacter = loadCharacterAsset(character: defaultCharacter, mood: mood) {
            characterCache[cacheKey] = fallbackCharacter
            return fallbackCharacter
        }
        if let legacy = image(for: mood) {
            characterCache[cacheKey] = legacy
            return legacy
        }
        return nil
    }

    private static func loadCharacterAsset(character: String, mood: PetMood) -> NSImage? {
        let name = "\(character)-\(mood.rawValue.lowercased())"
        guard let url = Bundle.module.url(
            forResource: name,
            withExtension: "png",
            subdirectory: "Resources/characters"
        ) ?? Bundle.module.url(
            forResource: name,
            withExtension: "png",
            subdirectory: "characters"
        ), let image = NSImage(contentsOf: url) else {
            return nil
        }
        return image
    }
}

/// The 96×96pt hero-header character portrait (spec §2.1, §5) — native
/// size, unscaled, no ref-node size override. Falls back to a plain
/// SF Symbol glyph if the bundled asset is somehow missing, so a
/// packaging problem degrades gracefully instead of leaving a blank
/// header.
///
/// Animation (all panel-internal — see AnimationPolicy/the governing
/// invariant that the menu bar itself never moves):
///   - Breathing: a slow vertical bob, only while ASLEEP or CONTENT.
///   - Micro-motion: an occasional tiny rotation nudge, any mood except
///     ASLEEP.
///   - Mood change: opacity crossfade between frames.
///   - Celebration: one small hop, fired at most once per panel-open,
///     when `celebrateOnAppear` is true.
/// All timers are `Task.sleep` loops owned by this view and cancelled on
/// disappear — no NSTimer leaks. Every knob is gated by `AnimationPolicy`,
/// which itself collapses to "off"/"instant" under Reduce Motion.
public struct CharacterPortrait: View {
    let character: String
    let mood: PetMood
    let celebrateOnAppear: Bool
    let policy: AnimationPolicy
    let onTap: (() -> Void)?

    @State private var breathingUp = false
    @State private var microMotionTask: Task<Void, Never>?
    @State private var microMotionAngle: Double = 0
    @State private var hopOffset: CGFloat = 0
    @State private var hasFiredCelebration = false

    public init(
        character: String = CharacterAsset.defaultCharacter,
        mood: PetMood,
        celebrateOnAppear: Bool = false,
        policy: AnimationPolicy = AnimationPolicy(reduceMotion: AnimationPolicy.systemReduceMotion),
        onTap: (() -> Void)? = nil
    ) {
        self.character = character
        self.mood = mood
        self.celebrateOnAppear = celebrateOnAppear
        self.policy = policy
        self.onTap = onTap
    }

    private var breathingActive: Bool {
        policy.breathingEnabled && (mood == .asleep || mood == .content)
    }

    private var microMotionActive: Bool {
        policy.microMotionEnabled && mood != .asleep
    }

    public var body: some View {
        Group {
            if let nsImage = CharacterAsset.characterImage(character: character, mood: mood) {
                Image(nsImage: nsImage)
                    .resizable()
                    .interpolation(.none)
                    .aspectRatio(contentMode: .fit)
            } else {
                Image(systemName: "cat")
                    .resizable()
                    .aspectRatio(contentMode: .fit)
                    .foregroundStyle(.secondary)
                    .padding(20)
            }
        }
        .frame(width: 96, height: 96)
        .id(mood)
        .transition(.opacity)
        .animation(.easeInOut(duration: policy.crossfadeDuration), value: mood)
        .rotationEffect(.degrees(microMotionActive ? microMotionAngle : 0))
        .offset(y: (breathingActive ? breathingBobOffset : 0) - hopOffset)
        .onAppear {
            startBreathingIfNeeded()
            startMicroMotionLoop()
            fireCelebrationIfNeeded()
        }
        .onDisappear {
            microMotionTask?.cancel()
            microMotionTask = nil
        }
        .onChange(of: mood) { _ in
            startBreathingIfNeeded()
            startMicroMotionLoop()
        }
        .contentShape(Rectangle())
        .onTapGesture {
            onTap?()
        }
    }

    // MARK: - Breathing

    private var breathingBobOffset: CGFloat {
        breathingUp ? -AnimationPolicy.breathingAmplitude : AnimationPolicy.breathingAmplitude
    }

    private func startBreathingIfNeeded() {
        guard breathingActive else {
            breathingUp = false
            return
        }
        withAnimation(
            .easeInOut(duration: AnimationPolicy.breathingPeriod / 2)
                .repeatForever(autoreverses: true)
        ) {
            breathingUp = true
        }
    }

    // MARK: - Micro-motion

    private func startMicroMotionLoop() {
        microMotionTask?.cancel()
        guard microMotionActive else {
            microMotionAngle = 0
            return
        }
        microMotionTask = Task { @MainActor in
            while !Task.isCancelled {
                let interval = Double.random(
                    in: AnimationPolicy.microMotionMinInterval...AnimationPolicy.microMotionMaxInterval
                )
                try? await Task.sleep(nanoseconds: UInt64(interval * 1_000_000_000))
                if Task.isCancelled { break }
                let nudge = Bool.random() ? 2.0 : -2.0
                withAnimation(.easeInOut(duration: 0.3)) {
                    microMotionAngle = nudge
                }
                try? await Task.sleep(nanoseconds: UInt64(0.3 * 1_000_000_000))
                if Task.isCancelled { break }
                withAnimation(.easeInOut(duration: 0.3)) {
                    microMotionAngle = 0
                }
            }
        }
    }

    // MARK: - Celebration hop

    private func fireCelebrationIfNeeded() {
        guard celebrateOnAppear, policy.celebrationEnabled, !hasFiredCelebration else { return }
        hasFiredCelebration = true
        withAnimation(.spring(response: 0.4, dampingFraction: 0.5)) {
            hopOffset = 6
        }
        Task { @MainActor in
            try? await Task.sleep(nanoseconds: UInt64(0.4 * 1_000_000_000))
            withAnimation(.spring(response: 0.4, dampingFraction: 0.5)) {
                hopOffset = 0
            }
        }
    }
}
