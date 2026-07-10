import XCTest
@testable import ViduraPetKit

/// These would have caught bug #1 (NSPopover mispositioning — replaced by
/// manual math) and bug #3 (anchoring drift) had they existed first: they
/// pin down the exact frame math in `PanelGeometry.frame` independent of
/// any live status item, window, or screen.
final class PanelGeometryTests: XCTestCase {
    private let screen = CGRect(x: 0, y: 0, width: 1440, height: 900)

    func test_centeredUnderButton() {
        let buttonRect = CGRect(x: 700, y: 880, width: 20, height: 20)
        let frame = PanelGeometry.frame(
            buttonRect: buttonRect,
            screenVisible: screen,
            contentHeight: 300
        )
        XCTAssertEqual(frame.midX, buttonRect.midX, accuracy: 0.001)
        XCTAssertEqual(frame.width, 400)
    }

    func test_clampedAtLeftScreenEdge() {
        // Button near the far left — an unclamped centered frame would
        // push the panel's left edge off-screen.
        let buttonRect = CGRect(x: 5, y: 880, width: 20, height: 20)
        let frame = PanelGeometry.frame(
            buttonRect: buttonRect,
            screenVisible: screen,
            contentHeight: 300
        )
        XCTAssertEqual(frame.minX, screen.minX + 8)
    }

    func test_clampedAtRightScreenEdge() {
        // Button near the far right — an unclamped centered frame would
        // push the panel's right edge off-screen.
        let buttonRect = CGRect(x: 1430, y: 880, width: 20, height: 20)
        let frame = PanelGeometry.frame(
            buttonRect: buttonRect,
            screenVisible: screen,
            contentHeight: 300
        )
        XCTAssertEqual(frame.maxX, screen.maxX - 8, accuracy: 0.001)
    }

    func test_topEdgeHangsSixPointsBelowButtonMinY() {
        let buttonRect = CGRect(x: 700, y: 880, width: 20, height: 20)
        let frame = PanelGeometry.frame(
            buttonRect: buttonRect,
            screenVisible: screen,
            contentHeight: 300
        )
        // Top edge of the panel = frame.maxY (AppKit coordinates: y grows
        // upward), and it should sit 6pt below the button's bottom edge.
        XCTAssertEqual(frame.maxY, buttonRect.minY - 6, accuracy: 0.001)
    }

    func test_heightClampsAtMinimum() {
        let buttonRect = CGRect(x: 700, y: 880, width: 20, height: 20)
        let frame = PanelGeometry.frame(
            buttonRect: buttonRect,
            screenVisible: screen,
            contentHeight: 10,
            minHeight: 120,
            maxHeight: 640
        )
        XCTAssertEqual(frame.height, 120)
    }

    func test_heightClampsAtMaximum() {
        let buttonRect = CGRect(x: 700, y: 880, width: 20, height: 20)
        let frame = PanelGeometry.frame(
            buttonRect: buttonRect,
            screenVisible: screen,
            contentHeight: 5000,
            minHeight: 120,
            maxHeight: 640
        )
        XCTAssertEqual(frame.height, 640)
    }

    func test_heightPassesThroughWithinBounds() {
        let buttonRect = CGRect(x: 700, y: 880, width: 20, height: 20)
        let frame = PanelGeometry.frame(
            buttonRect: buttonRect,
            screenVisible: screen,
            contentHeight: 300,
            minHeight: 120,
            maxHeight: 640
        )
        XCTAssertEqual(frame.height, 300)
    }

    func test_panelNeverExtendsOffScreenBottom() {
        // Button very close to the bottom of the screen with a tall
        // content height — without the floor, y could go negative /
        // below the screen's visible bottom.
        let buttonRect = CGRect(x: 700, y: 20, width: 20, height: 20)
        let frame = PanelGeometry.frame(
            buttonRect: buttonRect,
            screenVisible: screen,
            contentHeight: 640
        )
        XCTAssertGreaterThanOrEqual(frame.minY, screen.minY + 8)
    }

    func test_degenerateZeroSizeScreenDoesNotCrash() {
        let zeroScreen = CGRect(x: 0, y: 0, width: 0, height: 0)
        let buttonRect = CGRect(x: 0, y: 0, width: 20, height: 20)
        let frame = PanelGeometry.frame(
            buttonRect: buttonRect,
            screenVisible: zeroScreen,
            contentHeight: 300
        )
        // Just needs to produce finite, sane numbers rather than crash or
        // produce NaN/inf from an inverted clamp range.
        XCTAssertTrue(frame.width.isFinite)
        XCTAssertTrue(frame.height.isFinite)
        XCTAssertTrue(frame.origin.x.isFinite)
        XCTAssertTrue(frame.origin.y.isFinite)
    }
}
