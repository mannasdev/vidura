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
/// result, fully deterministic math we own.
@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate {
    private var statusItem: NSStatusItem?
    private var panel: PetPanel?
    private var outsideClickMonitor: Any?
    private let state = StateModel()
    private var moodCancellable: AnyCancellable?

    private static let panelWidth: CGFloat = 400
    private static let panelMinHeight: CGFloat = 120
    private static let panelMaxHeight: CGFloat = 640
    private var contentCancellable: AnyCancellable?

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)

        let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
        if let button = item.button {
            button.image = Self.menuBarImage()
            button.target = self
            button.action = #selector(togglePanel(_:))
        }
        statusItem = item

        state.start()
        observeMood()
    }

    func applicationWillTerminate(_ notification: Notification) {
        state.stop()
        moodCancellable?.cancel()
        removeOutsideClickMonitor()
    }

    /// The menu bar mark is fixed — it does not change per mood. The
    /// ONLY thing this observes is the STIRRING transition, to show a
    /// small "•" badge on the status item title. No other mood touches
    /// the menu bar at all.
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
        button.title = isStirring ? "\u{2022}" : ""
        button.imagePosition = isStirring ? .imageLeading : .imageOnly
        button.setAccessibilityLabel(isStirring ? "Vidura — stirring" : "Vidura")
    }

    /// One fixed menu-bar mark: a plain SF Symbol, template mode so it
    /// tints for light/dark menu bars. Falls back to a drawn dot if the
    /// symbol is unavailable — the image must never be nil or a crowded
    /// menu bar renders an empty, unclickable item.
    private static func menuBarImage() -> NSImage {
        if let symbol = NSImage(
            systemSymbolName: "moon.zzz",
            accessibilityDescription: "Vidura"
        ) {
            symbol.isTemplate = true
            return symbol
        }
        let fallback = NSImage(size: NSSize(width: 18, height: 18), flipped: false) { rect in
            NSColor.black.setFill()
            NSBezierPath(ovalIn: rect.insetBy(dx: 5, dy: 5)).fill()
            return true
        }
        fallback.isTemplate = true
        fallback.accessibilityDescription = "Vidura"
        return fallback
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
        state.refresh()

        let panel = self.panel ?? makePanel()
        self.panel = panel
        positionPanel(panel)
        panel.makeKeyAndOrderFront(nil)
        installOutsideClickMonitor()

        // The panel hugs its content: when entries/mood change while it
        // is open (accept, dismiss, poll), re-measure and re-anchor so
        // there is never a fixed-height void around the content.
        contentCancellable = state.$entries
            .combineLatest(state.$mood)
            .receive(on: RunLoop.main)
            .sink { [weak self] _, _ in
                guard let self, let panel = self.panel, panel.isVisible else { return }
                self.positionPanel(panel)
            }
    }

    /// Frame math we own end to end: X centers the panel under the
    /// status icon, the TOP edge hangs just below the menu bar, and the
    /// HEIGHT is the SwiftUI content's own fitting size (clamped) — the
    /// panel is exactly as tall as what's inside it.
    private func positionPanel(_ panel: PetPanel) {
        guard let button = statusItem?.button, let buttonWindow = button.window else { return }
        let buttonRect = buttonWindow.convertToScreen(button.convert(button.bounds, to: nil))
        let screenFrame = (buttonWindow.screen ?? NSScreen.main)?.visibleFrame
            ?? NSRect(x: 0, y: 0, width: 1440, height: 900)

        var height = Self.panelMinHeight
        if let contentView = panel.contentViewController?.view {
            contentView.layoutSubtreeIfNeeded()
            height = min(max(contentView.fittingSize.height, Self.panelMinHeight), Self.panelMaxHeight)
        }

        var x = buttonRect.midX - Self.panelWidth / 2
        x = min(max(x, screenFrame.minX + 8), screenFrame.maxX - Self.panelWidth - 8)
        let yTop = buttonRect.minY - 6
        let y = max(yTop - height, screenFrame.minY + 8)

        panel.setFrame(NSRect(x: x, y: y, width: Self.panelWidth, height: height), display: true)
    }

    private func hidePanel() {
        panel?.orderOut(nil)
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
            Task { @MainActor in self?.hidePanel() }
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
        // never floating in a fixed-height void.
        let content = CardView(state: state)
            .frame(width: Self.panelWidth)
            .fixedSize(horizontal: false, vertical: true)
            .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: 14, style: .continuous)
                    .strokeBorder(Color.primary.opacity(0.12), lineWidth: 0.5)
            )
        panel.contentViewController = NSHostingController(rootView: content)
        return panel
    }
}

/// Borderless windows refuse key status by default; the panel needs it
/// so buttons inside are clickable on the first click.
final class PetPanel: NSPanel {
    override var canBecomeKey: Bool { true }
}

@MainActor
enum ViduraPetMain {
    static func run() {
        let delegate = AppDelegate()
        let app = NSApplication.shared
        app.delegate = delegate
        withExtendedLifetime(delegate) {
            app.run()
        }
    }
}

MainActor.assumeIsolated {
    ViduraPetMain.run()
}
