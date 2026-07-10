import CoreGraphics
#if canImport(AppKit)
import AppKit
#endif

/// Pure frame math for the manually-positioned status-item panel — no
/// AppKit side effects, no live status item or screen required. Extracted
/// specifically so the math that has twice shipped positioning bugs
/// (NSPopover mispositioning, then manual-anchoring drift, then a
/// fixed-height void) can be exercised directly in unit tests.
public enum PanelGeometry {
    /// Computes the panel's frame given the status button's screen rect,
    /// the screen's visible frame, and the content's own fitting height.
    ///
    /// - Top edge hangs 6pt below `buttonRect.minY` (the bottom of the
    ///   menu-bar button), matching the panel dropping just under the
    ///   menu bar.
    /// - X is centered on the button, then clamped so the panel stays at
    ///   least 8pt inside the screen's left/right visible edges.
    /// - Height is `contentHeight` clamped to `[minHeight, maxHeight]`.
    /// - Y is floored so the panel's bottom never goes below the screen's
    ///   visible bottom edge + 8pt.
    public static func frame(
        buttonRect: CGRect,
        screenVisible: CGRect,
        contentHeight: CGFloat,
        width: CGFloat = 400,
        minHeight: CGFloat = 120,
        maxHeight: CGFloat = 640
    ) -> CGRect {
        let height = min(max(contentHeight, minHeight), maxHeight)

        var x = buttonRect.midX - width / 2
        let minX = screenVisible.minX + 8
        let maxX = screenVisible.maxX - width - 8
        // Degenerate/zero-size screens can put maxX below minX; clamp to
        // minX in that case rather than producing an inverted range.
        if maxX >= minX {
            x = min(max(x, minX), maxX)
        } else {
            x = minX
        }

        let yTop = buttonRect.minY - 6
        let y = max(yTop - height, screenVisible.minY + 8)

        return CGRect(x: x, y: y, width: width, height: height)
    }
}
