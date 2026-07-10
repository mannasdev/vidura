import SwiftUI
#if canImport(AppKit)
import AppKit
#endif

/// Design tokens from `design-export/UI-SPEC.md` §1.1/§1.2/§1.3 — the
/// Pencil-authored light/dark palette, fonts, and radii for the panel
/// reskin. Every color here is a *dynamic* NSColor (resolved at draw time
/// via the current NSAppearance) rather than a static value, so the same
/// SwiftUI tree renders correctly in both the light and dark popovers
/// without any asset catalog.
public enum Theme {
    // MARK: - Dynamic color helper

    /// Builds a `Color` that resolves to `light` in a light appearance and
    /// `dark` in a dark appearance, re-evaluated live by AppKit on every
    /// appearance change (matches `Color(NSColor)` dynamic-provider
    /// semantics) — no asset catalog required.
    static func dynamic(light: NSColor, dark: NSColor) -> Color {
        #if canImport(AppKit)
        let nsColor = NSColor(name: nil) { appearance in
            appearance.bestMatch(from: [.aqua, .darkAqua]) == .darkAqua ? dark : light
        }
        return Color(nsColor)
        #else
        return Color(light)
        #endif
    }

    private static func hex(_ hex: UInt32, alpha: CGFloat = 1) -> NSColor {
        let r = CGFloat((hex >> 16) & 0xFF) / 255
        let g = CGFloat((hex >> 8) & 0xFF) / 255
        let b = CGFloat(hex & 0xFF) / 255
        return NSColor(srgbRed: r, green: g, blue: b, alpha: alpha)
    }

    // MARK: - Tokens (§1.1)

    public static let bgPanel = dynamic(light: hex(0xF7F4EE), dark: hex(0x201D18))
    public static let bgCard = dynamic(light: hex(0xFFFFFF), dark: hex(0x2A2620))
    public static let bgEvidence = dynamic(light: hex(0xF3EFE6), dark: hex(0x191612))
    public static let border = dynamic(light: hex(0xE4DDCE), dark: hex(0x3A342B))
    public static let textPrimary = dynamic(light: hex(0x2B2419), dark: hex(0xEDE6D9))
    public static let textSecondary = dynamic(light: hex(0x6E6353), dark: hex(0xA79B87))
    public static let textTertiary = dynamic(light: hex(0x9A8F7C), dark: hex(0x6E6355))
    public static let accent = dynamic(light: hex(0xB45309), dark: hex(0xE5A158))
    public static let accentSubtle = dynamic(
        light: hex(0xB45309, alpha: 0.10),
        dark: hex(0xE5A158, alpha: 0.13)
    )

    /// Accept button fill — light mock hardcodes `#2B2419` (near-black,
    /// equal to text-primary light). No dark-mode Accept exists in the
    /// mock (see spec §7.2); we invert per the spec's own recommendation:
    /// dark fill = text-primary dark (`#EDE6D9`), with dark ink label.
    public static let acceptFill = dynamic(light: hex(0x2B2419), dark: hex(0xEDE6D9))
    public static let acceptLabel = dynamic(light: hex(0xFFFFFF), dark: hex(0x2B2419))

    /// Quote bullet bar — 50% alpha of accent-light in the one observed
    /// mock; no separate dark-mode quote bar was captured, so the same
    /// literal is reused (it's a fixed accent tint, not a token swap).
    public static let quoteBar = Color(hex(0xB45309, alpha: 0.50))

    // MARK: - Fonts (§1.2)
    //
    // Deviation from spec: Lora / Inter / IBM Plex Mono are not installed
    // as system fonts on macOS and no font files were provided alongside
    // the character assets, so `Font.custom` would silently fall back to
    // the system font anyway (with a console warning) — instead we use
    // SwiftUI's `.serif`/`.default`/`.monospaced` design axis on the
    // system font at the spec's exact sizes/weights/tracking. This keeps
    // the serif-editorial-accent-vs-UI-sans-vs-mono-log distinction the
    // spec calls for (§1.2, §2.4) without bundling third-party font files.
    public static let nameFont = Font.system(size: 22, weight: .semibold, design: .serif)
    public static let moodFont = Font.system(size: 11, weight: .semibold)
    /// Applied via `Text.tracking(_:)` at the call site — spec's 1.5pt
    /// letter-spacing on the mood label (§1.2) is a view-level modifier
    /// in SwiftUI, not a Font property.
    public static let moodTracking: CGFloat = 1.5
    public static let subtitleFont = Font.system(size: 13, weight: .regular)
    public static let tagFont = Font.system(size: 10.5, weight: .regular, design: .monospaced)
    public static let metaFont = Font.system(size: 11, weight: .regular)
    public static let summaryFont = Font.system(size: 14.5, weight: .medium)
    public static let evidenceFont = Font.system(size: 11, weight: .regular, design: .monospaced)
    public static let dismissFont = Font.system(size: 12.5, weight: .medium)
    public static let doButtonFont = Font.system(size: 12.5, weight: .semibold)
    public static let acceptFont = Font.system(size: 12.5, weight: .semibold)
    public static let footerFont = Font.system(size: 11, weight: .regular)
    public static let emptyPrimaryFont = Font.system(size: 17, weight: .regular, design: .serif)
    public static let emptySecondaryFont = Font.system(size: 13, weight: .regular)

    // MARK: - Radii (§1.3)

    public static let panelRadius: CGFloat = 14
    public static let cardRadius: CGFloat = 10
    public static let evidenceRadius: CGFloat = 8
    public static let buttonRadius: CGFloat = 7
    public static let tagRadius: CGFloat = 4
}
