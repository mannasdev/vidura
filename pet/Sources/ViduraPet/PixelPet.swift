import AppKit
import SwiftUI

/// The pet's face, rendered entirely from code as a pixel-art grid — no
/// image assets, no SF Symbols. Each mood is a small hand-authored
/// `[[Int]]` grid: 0 = transparent, 1 = body, 2 = accent. The creature
/// is a small round-ish thing with stubby ears; only the pose, face, and
/// accent pixels change between moods, so the silhouette stays legible
/// and consistent across the app's five moods.
///
/// Deliberately static: `Canvas` draws one frame and nothing animates,
/// per the anti-Clippy invariant that governs this whole app.
enum PixelPetGrid {
    /// Every grid is exactly this many cells wide/tall.
    static let width = 14
    static let height = 12

    /// Sitting upright, two dot eyes, a 3px smile.
    static let content: [[Int]] = [
        [0,0,0,0,1,1,0,0,1,1,0,0,0,0],
        [0,0,0,0,1,1,0,0,1,1,0,0,0,0],
        [0,0,0,1,1,1,1,1,1,1,1,0,0,0],
        [0,0,1,1,1,1,1,1,1,1,1,1,0,0],
        [0,1,1,1,2,1,1,1,1,2,1,1,1,0],
        [0,1,1,1,2,1,1,1,1,2,1,1,1,0],
        [0,1,1,1,1,1,1,1,1,1,1,1,1,0],
        [0,1,1,1,1,2,2,2,1,1,1,1,1,0],
        [0,1,1,1,1,1,1,1,1,1,1,1,1,0],
        [0,0,1,1,1,1,1,1,1,1,1,1,0,0],
        [0,0,0,1,1,1,1,1,1,1,1,0,0,0],
        [0,0,0,0,1,1,1,1,1,1,0,0,0,0],
    ]

    /// Lying down (flattened, ears tucked in — no ear silhouette), eyes
    /// closed as 2px horizontal lines, three "z" accent pixels ascending
    /// toward the top-right.
    static let asleep: [[Int]] = [
        [0,0,0,0,0,0,0,0,0,0,0,0,0,2],
        [0,0,0,0,0,0,0,0,0,0,0,0,2,2],
        [0,0,0,0,0,0,0,0,0,0,2,2,0,0],
        [0,0,0,0,0,0,0,0,0,0,0,0,0,0],
        [0,0,0,0,0,0,0,0,0,0,0,0,0,0],
        [0,0,0,1,1,1,1,1,1,1,1,0,0,0],
        [0,0,1,1,1,1,1,1,1,1,1,1,0,0],
        [0,1,1,1,1,1,1,1,1,1,1,1,1,0],
        [1,1,1,2,2,1,1,1,2,2,1,1,1,1],
        [1,1,1,1,1,1,1,1,1,1,1,1,1,1],
        [0,1,1,1,1,1,1,1,1,1,1,1,1,0],
        [0,0,1,1,1,1,1,1,1,1,1,0,0,0],
    ]

    /// Upright and alert — straight, tall ears — with wide 2x2 eyes and
    /// a tiny scroll (an accent rectangle outline) held in front.
    static let stirring: [[Int]] = [
        [0,0,1,1,0,0,0,0,0,1,1,0,0,0],
        [0,0,1,1,0,0,0,0,0,1,1,0,0,0],
        [0,0,0,1,1,0,0,0,1,1,0,0,0,0],
        [0,0,0,1,1,1,1,1,1,1,0,0,0,0],
        [0,0,1,1,1,1,1,1,1,1,1,0,0,0],
        [0,0,1,1,2,2,1,2,2,1,1,0,0,0],
        [0,0,1,1,2,2,1,2,2,1,1,0,0,0],
        [0,0,1,1,1,1,1,1,1,1,1,0,0,0],
        [0,0,1,1,1,1,1,1,1,1,1,0,0,0],
        [0,0,1,2,2,2,2,2,2,2,1,0,0,0],
        [0,0,1,2,0,0,0,0,0,2,1,0,0,0],
        [0,0,1,2,2,2,2,2,2,2,1,0,0,0],
    ]

    /// Sitting, closed happy "^ ^" eyes, three accent star pixels
    /// scattered above the head.
    static let proud: [[Int]] = [
        [0,2,0,0,0,1,1,0,0,1,1,0,0,2],
        [0,0,0,0,1,1,0,0,0,0,1,1,0,0],
        [0,0,0,1,1,1,1,1,1,1,1,0,0,0],
        [0,0,1,1,1,1,1,1,1,1,1,1,0,0],
        [0,1,1,1,1,1,1,1,1,1,1,1,1,0],
        [0,1,1,2,1,2,1,1,2,1,2,1,1,0],
        [0,1,1,1,2,1,1,1,1,2,1,1,1,0],
        [0,1,1,1,1,2,2,2,2,2,1,1,1,0],
        [0,1,1,1,1,1,1,1,1,1,1,1,1,0],
        [0,0,1,1,1,1,1,1,1,1,1,1,0,0],
        [0,0,0,1,1,1,1,1,1,1,1,0,0,0],
        [0,0,0,0,1,1,1,1,1,1,0,0,0,0],
    ]

    /// Slightly slumped (compressed top, no perked ears — instead two
    /// droopy single-pixel ears leaning outward/down), a flat 2px mouth,
    /// and one accent cloud pixel-cluster at the top-right.
    static let concerned: [[Int]] = [
        [0,0,0,0,0,0,0,0,0,0,0,2,2,0],
        [0,1,0,0,0,0,0,0,0,0,2,2,2,2],
        [1,1,0,0,0,0,0,0,0,0,0,2,2,0],
        [0,1,1,0,0,0,0,0,0,1,1,0,0,0],
        [0,0,1,1,1,1,1,1,1,1,0,0,0,0],
        [0,1,1,1,1,1,1,1,1,1,1,0,0,0],
        [0,1,1,1,1,1,1,1,1,1,1,1,0,0],
        [0,1,1,1,1,1,1,1,1,1,1,1,0,0],
        [0,1,1,1,2,2,2,2,2,1,1,1,0,0],
        [0,0,1,1,1,1,1,1,1,1,1,0,0,0],
        [0,0,0,1,1,1,1,1,1,1,0,0,0,0],
        [0,0,0,0,1,1,1,1,1,0,0,0,0,0],
    ]

    /// Mood -> grid. DESIGNER SWAP POINT: when real pixel art replaces
    /// these hand-authored grids, this is the one function to change —
    /// nothing else in the app should need to know how a mood is drawn.
    static func grid(for mood: Mood) -> [[Int]] {
        switch mood {
        case .asleep: return asleep
        case .content: return content
        case .stirring: return stirring
        case .proud: return proud
        case .concerned: return concerned
        }
    }
}

/// Renders one `PixelPetGrid` mood grid as crisp, unsmoothed square
/// pixels via `Canvas`. Body cells use `Color.primary.opacity(0.85)` so
/// the creature adapts to light/dark mode; accent cells use a single
/// muted teal.
struct PixelPet: View {
    let mood: Mood

    private static let accent = Color(red: 0.29, green: 0.53, blue: 0.53)

    var body: some View {
        let grid = PixelPetGrid.grid(for: mood)
        Canvas { context, size in
            let cols = CGFloat(PixelPetGrid.width)
            let rows = CGFloat(PixelPetGrid.height)
            let cell = min(size.width / cols, size.height / rows)
            let originX = (size.width - cell * cols) / 2
            let originY = (size.height - cell * rows) / 2

            for (rowIndex, row) in grid.enumerated() {
                for (colIndex, value) in row.enumerated() where value != 0 {
                    let rect = CGRect(
                        x: originX + CGFloat(colIndex) * cell,
                        y: originY + CGFloat(rowIndex) * cell,
                        width: cell,
                        height: cell
                    )
                    let color: Color = value == 2 ? Self.accent : Color.primary.opacity(0.85)
                    context.fill(Path(rect), with: .color(color))
                }
            }
        }
        .accessibilityLabel(Text(mood.rawValue.capitalized))
    }
}

/// The status item's fixed menu-bar mark, derived from the same
/// creature: a simplified 10x10 monochrome silhouette (body outline
/// only, no face) rendered to an 18x18 template `NSImage` so AppKit
/// tints it correctly for light/dark menu bars and the highlighted
/// state. This is the ONE mark ever shown in the status item — mood
/// never changes it; only the STIRRING "\u{2022}" title suffix does
/// (see AppDelegate.updateBadge).
enum PixelPetMenuBarMark {
    private static let silhouette: [[Int]] = [
        [0,0,0,1,1,0,1,1,0,0],
        [0,0,1,1,1,1,1,1,0,0],
        [0,1,1,1,1,1,1,1,1,0],
        [1,1,1,1,1,1,1,1,1,1],
        [1,1,1,1,1,1,1,1,1,1],
        [1,1,1,1,1,1,1,1,1,1],
        [1,1,1,1,1,1,1,1,1,1],
        [0,1,1,1,1,1,1,1,1,0],
        [0,0,1,1,1,1,1,1,0,0],
        [0,0,0,1,1,1,1,0,0,0],
    ]

    static func image() -> NSImage {
        let size = NSSize(width: 18, height: 18)
        let image = NSImage(size: size, flipped: false) { rect in
            let cols = CGFloat(silhouette.first?.count ?? 10)
            let rows = CGFloat(silhouette.count)
            let cell = min(rect.width / cols, rect.height / rows)
            let originX = (rect.width - cell * cols) / 2
            let originY = (rect.height - cell * rows) / 2

            NSColor.black.setFill()
            for (rowIndex, row) in silhouette.enumerated() {
                for (colIndex, value) in row.enumerated() where value != 0 {
                    // NSImage's flipped:false drawing handler still uses a
                    // bottom-up coordinate space, so invert the row index
                    // to keep the silhouette right-side up.
                    let flippedRow = CGFloat(silhouette.count - 1 - rowIndex)
                    let pixelRect = NSRect(
                        x: originX + CGFloat(colIndex) * cell,
                        y: originY + flippedRow * cell,
                        width: cell,
                        height: cell
                    )
                    NSBezierPath(rect: pixelRect).fill()
                }
            }
            return true
        }
        image.isTemplate = true
        return image
    }
}
