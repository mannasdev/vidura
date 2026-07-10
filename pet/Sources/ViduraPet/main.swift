import AppKit
import Combine
import SwiftUI

/// The pet sleeps by default and lives entirely in the menu bar — no
/// Dock icon, no window, no chrome beyond one status item and its
/// popover. `NSApplication`'s `.accessory` policy is what keeps it out
/// of the Dock and the Cmd-Tab switcher.
@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate {
    private var statusItem: NSStatusItem?
    private var popover: NSPopover?
    private let state = StateModel()
    private var moodCancellable: AnyCancellable?

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)

        let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
        if let button = item.button {
            // Drawn in code (PixelPetMenuBarMark), never an SF Symbol
            // lookup that could fail to resolve — the button image must
            // ALWAYS be non-nil, or a crowded menu bar can render an
            // empty status item with no anchor for the popover.
            button.image = Self.menuBarImage()
            button.target = self
            button.action = #selector(togglePopover(_:))
        }
        statusItem = item

        let popover = NSPopover()
        popover.behavior = .transient
        // 540pt (up from 480) makes room for the panel's new ~72pt face
        // header without shrinking the suggestion-card scroll area below it.
        popover.contentSize = NSSize(width: 400, height: 540)
        popover.contentViewController = NSHostingController(rootView: CardView(state: state))
        self.popover = popover

        state.start()
        observeMood()
    }

    func applicationWillTerminate(_ notification: Notification) {
        state.stop()
        moodCancellable?.cancel()
    }

    /// The menu bar mark is fixed — it does not change per mood. The
    /// ONLY thing this observes is the STIRRING transition, to show a
    /// small "•" badge on the status item title (the cleanest standard
    /// approach for a status-item indicator, short of a custom NSView).
    /// No other mood touches the menu bar at all.
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

    /// The one fixed menu-bar mark, rendered in template mode so AppKit
    /// tints it correctly for both light and dark menu bars, and for the
    /// selected/highlighted state when the popover is open. Drawn in
    /// code (never an SF Symbol lookup) so this is never nil.
    private static func menuBarImage() -> NSImage {
        let image = PixelPetMenuBarMark.image()
        image.accessibilityDescription = "Vidura"
        return image
    }

    @objc private func togglePopover(_ sender: AnyObject?) {
        guard let button = statusItem?.button, let popover else { return }
        if popover.isShown {
            popover.performClose(sender)
            return
        }

        state.refresh()

        // Accessory apps (no Dock icon, no menu bar menu of their own)
        // can otherwise show the popover anchored to a stale/drifted
        // point — especially in a crowded menu bar — unless the app is
        // explicitly activated immediately before the popover is shown.
        NSApp.activate(ignoringOtherApps: true)

        // Only ever anchor to a real, laid-out button window. If AppKit
        // hasn't given the status item a window yet (can happen right
        // after launch, or if the item was squeezed out by a crowded
        // menu bar), skip showing rather than risk a detached, floating
        // popover with an arrow pointing at nothing. No crash either way.
        guard button.window != nil else { return }
        popover.show(relativeTo: button.bounds, of: button, preferredEdge: .minY)
    }
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
