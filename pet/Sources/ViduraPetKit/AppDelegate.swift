import AppKit
import Combine
import SwiftUI

/// The pet sleeps by default and lives entirely in the menu bar — no
/// Dock icon, no window, no chrome beyond one status item and its
/// panel. `NSApplication`'s `.accessory` policy is what keeps it out
/// of the Dock and the Cmd-Tab switcher.
///
/// PANEL POSITIONING NOTE: this deliberately does NOT use NSPopover.
/// On macOS 26, NSPopover.show(relativeTo:) from a status item in an
/// accessory app mispositions vertically (correct X, ~600pt low) —
/// observed twice on real hardware. Instead we place an NSPanel
/// manually from the status button's actual screen rect: same visual
/// result, fully deterministic math we own. The actual frame math is
/// extracted into `PanelGeometry.frame` so it can be unit-tested
/// without a live status item or screen.
@MainActor
public final class AppDelegate: NSObject, NSApplicationDelegate {
    private var statusItem: NSStatusItem?
    private var panel: PetPanel?
    private var outsideClickMonitor: Any?
    private let state = StateModel()
    private var moodCancellable: AnyCancellable?

    private static let panelWidth: CGFloat = 400
    private static let panelMinHeight: CGFloat = 120
    private static let panelMaxHeight: CGFloat = 640
    private var contentCancellable: AnyCancellable?

    public override init() {
        super.init()
    }

    public func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)

        let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
        if let button = item.button {
            button.image = Self.menuBarImage(withBadge: false)
            button.target = self
            button.action = #selector(togglePanel(_:))
        }
        statusItem = item

        state.start()
        observeMood()
    }

    public func applicationWillTerminate(_ notification: Notification) {
        state.stop()
        moodCancellable?.cancel()
        removeOutsideClickMonitor()
    }

    /// The menu bar mark's silhouette is fixed — it does not change per
    /// mood. The ONLY thing this observes is the STIRRING transition, to
    /// show or hide the small accent-colored badge dot at the glyph's
    /// top-right corner (spec §4: "the badge dot only appears when
    /// Vidura has counsel waiting"). No other mood touches the menu bar.
    private func observeMood() {
        moodCancellable = state.$mood
            .map { $0?.mood }
            .removeDuplicates()
            .sink { [weak self] moodRaw in
                guard let self, let moodRaw else { return }
                self.updateBadge(for: moodRaw)
            }
    }

    private func updateBadge(for moodRaw: String) {
        guard let button = statusItem?.button else { return }
        let isStirring = moodRaw == Mood.stirring.rawValue
        // The image must ALWAYS stay template (macOS retints it for
        // light/dark menu bars). The amber badge therefore cannot be
        // baked into the image — compositing a colored dot flattens the
        // whole image to non-template, which rendered the silhouette as
        // literal black pixels on dark menu bars (owner-reported bug).
        // Instead the dot is a colored attributed-string title beside
        // the template image: both properties survive.
        button.image = Self.menuBarImage(withBadge: false)
        if isStirring {
            button.attributedTitle = NSAttributedString(
                string: "\u{25CF}",
                attributes: [
                    .foregroundColor: NSColor(srgbRed: 0xB4 / 255, green: 0x53 / 255, blue: 0x09 / 255, alpha: 1),
                    .font: NSFont.systemFont(ofSize: 7),
                    .baselineOffset: 4,
                ]
            )
            button.imagePosition = .imageLeading
        } else {
            button.attributedTitle = NSAttributedString(string: "")
            button.imagePosition = .imageOnly
        }
        button.setAccessibilityLabel(isStirring ? "Vidura — stirring" : "Vidura")
    }

    /// The menu-bar mark glyph (spec §4): a small pixel-style rounded
    /// head silhouette with two rectangular eyes, matching the
    /// character's face in miniature, drawn in template mode so AppKit
    /// tints it correctly for light/dark menu bars. ALWAYS template —
    /// the stirring badge lives in the button's attributed title (see
    /// updateBadge), never composited into this image: compositing
    /// flattens template mode and the silhouette renders black on dark
    /// menu bars. Static image, no animation.
    static func menuBarImage(withBadge: Bool) -> NSImage {
        let size = NSSize(width: 18, height: 18)
        let image = NSImage(size: size, flipped: false) { rect in
            let inkColor = NSColor.black // template mode remaps this
            inkColor.setStroke()
            inkColor.setFill()

            // Rounded head silhouette (bun/ears nub + rounded body),
            // approximated as a rounded rect with a small notch on top.
            let headRect = rect.insetBy(dx: 3, dy: 2.5)
            let headPath = NSBezierPath(roundedRect: headRect, xRadius: 5, yRadius: 5)
            headPath.lineWidth = 1.4
            headPath.stroke()

            // Ears/"bun" nub.
            let nubRect = NSRect(x: rect.midX - 1.5, y: headRect.maxY - 1, width: 3, height: 3)
            NSBezierPath(roundedRect: nubRect, xRadius: 1, yRadius: 1).fill()

            // Two rectangular eye slits.
            let eyeWidth: CGFloat = 2.4
            let eyeHeight: CGFloat = 1.4
            let eyeY = headRect.midY - eyeHeight / 2
            NSBezierPath(
                rect: NSRect(x: headRect.midX - 3.6, y: eyeY, width: eyeWidth, height: eyeHeight)
            ).fill()
            NSBezierPath(
                rect: NSRect(x: headRect.midX + 1.2, y: eyeY, width: eyeWidth, height: eyeHeight)
            ).fill()

            return true
        }
        image.isTemplate = true
        image.accessibilityDescription = "Vidura"
        return image
    }

    @objc private func togglePanel(_ sender: AnyObject?) {
        if let panel, panel.isVisible {
            hidePanel()
            return
        }
        showPanel()
    }

    private func showPanel() {
        guard statusItem?.button != nil else { return }
        state.panelDidOpen()

        let panel = self.panel ?? makePanel()
        self.panel = panel
        positionPanel(panel)
        panel.makeKeyAndOrderFront(nil)
        installOutsideClickMonitor()

        // The panel hugs its content: when entries/mood change while it
        // is open (accept, dismiss, poll), OR the user navigates between
        // surfaces (route change: home/pets/settings), re-measure and
        // re-anchor so there is never a fixed-height void around the content.
        // `$route` is folded in here precisely because each surface has a
        // different fitting height and switching must re-fit the panel.
        contentCancellable = state.$entries
            .combineLatest(state.$mood, state.$route)
            .receive(on: RunLoop.main)
            .sink { [weak self] _, _, _ in
                guard let self, let panel = self.panel, panel.isVisible else { return }
                self.positionPanel(panel)
            }
    }

    /// Frame math lives in `PanelGeometry.frame` (pure, unit-tested); this
    /// just gathers the live inputs (status button rect, screen, content
    /// fitting size) and hands them off.
    private func positionPanel(_ panel: PetPanel) {
        guard let button = statusItem?.button, let buttonWindow = button.window else { return }
        let buttonRect = buttonWindow.convertToScreen(button.convert(button.bounds, to: nil))
        let screenFrame = (buttonWindow.screen ?? NSScreen.main)?.visibleFrame
            ?? NSRect(x: 0, y: 0, width: 1440, height: 900)

        var contentHeight = Self.panelMinHeight
        if let contentView = panel.contentViewController?.view {
            contentView.layoutSubtreeIfNeeded()
            contentHeight = contentView.fittingSize.height
        }

        let frame = PanelGeometry.frame(
            buttonRect: buttonRect,
            screenVisible: screenFrame,
            contentHeight: contentHeight,
            width: Self.panelWidth,
            minHeight: Self.panelMinHeight,
            maxHeight: Self.panelMaxHeight
        )
        panel.setFrame(frame, display: true)
    }

    private func hidePanel() {
        panel?.orderOut(nil)
        // Always reopen on the pet: reset the route so a visit that ended on
        // the Pets or Settings surface doesn't reappear there next time.
        state.route = .home
        removeOutsideClickMonitor()
        contentCancellable?.cancel()
        contentCancellable = nil
    }

    /// Transient behavior (click anywhere outside → close), which
    /// NSPopover used to give us for free.
    private func installOutsideClickMonitor() {
        removeOutsideClickMonitor()
        outsideClickMonitor = NSEvent.addGlobalMonitorForEvents(
            matching: [.leftMouseDown, .rightMouseDown]
        ) { [weak self] _ in
            // Strong-bind before the Task so the @Sendable closure captures an
            // immutable `let`, not the weak captured `var` (a hard error on
            // stricter Swift toolchains — see the same fix in StateModel.start).
            guard let self else { return }
            Task { @MainActor in self.hidePanel() }
        }
    }

    private func removeOutsideClickMonitor() {
        if let monitor = outsideClickMonitor {
            NSEvent.removeMonitor(monitor)
            outsideClickMonitor = nil
        }
    }

    private func makePanel() -> PetPanel {
        let panel = PetPanel(
            contentRect: NSRect(x: 0, y: 0, width: Self.panelWidth, height: Self.panelMinHeight),
            styleMask: [.borderless, .nonactivatingPanel, .fullSizeContentView],
            backing: .buffered,
            defer: false
        )
        panel.level = .popUpMenu
        panel.isOpaque = false
        panel.backgroundColor = .clear
        panel.hasShadow = true
        panel.hidesOnDeactivate = false
        panel.isReleasedWhenClosed = false
        panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]

        // Width fixed, height free — the panel takes its height from
        // this view's fitting size (positionPanel), so the content is
        // never floating in a fixed-height void. CardView itself now
        // draws the panel's opaque bg-panel background, border, and
        // 14pt corner radius per the design spec's exact solid tokens
        // (§1.1) — no extra chrome layered on top here.
        let content = CardView(state: state)
            .frame(width: Self.panelWidth)
            .fixedSize(horizontal: false, vertical: true)
        panel.contentViewController = NSHostingController(rootView: content)
        return panel
    }
}

/// Borderless windows refuse key status by default; the panel needs it
/// so buttons inside are clickable on the first click.
final class PetPanel: NSPanel {
    override var canBecomeKey: Bool { true }
}
