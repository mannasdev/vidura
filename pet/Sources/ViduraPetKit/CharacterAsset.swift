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
enum CharacterAsset {
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
}

/// The 96×96pt hero-header character portrait (spec §2.1, §5) — native
/// size, unscaled, no ref-node size override. Falls back to a plain
/// SF Symbol glyph if the bundled asset is somehow missing, so a
/// packaging problem degrades gracefully instead of leaving a blank
/// header.
public struct CharacterPortrait: View {
    let mood: PetMood

    public init(mood: PetMood) {
        self.mood = mood
    }

    public var body: some View {
        Group {
            if let nsImage = CharacterAsset.image(for: mood) {
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
    }
}
