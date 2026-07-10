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
            button.image = NSImage(
                systemSymbolName: Mood.asleep.symbolName,
                accessibilityDescription: "Vidura"
            )
            button.target = self
            button.action = #selector(togglePopover(_:))
        }
        statusItem = item

        let popover = NSPopover()
        popover.behavior = .transient
        popover.contentSize = NSSize(width: 360, height: 480)
        popover.contentViewController = NSHostingController(rootView: CardView(state: state))
        self.popover = popover

        state.start()
        observeMood()
    }

    func applicationWillTerminate(_ notification: Notification) {
        state.stop()
        moodCancellable?.cancel()
    }

    /// Mirrors state.mood into the status item's glyph via a Combine
    /// sink on the @Published property — fires exactly when `mood`
    /// changes, with no timer of any kind. This is what makes the
    /// anti-Clippy "no timers faster than 60s" invariant unambiguous:
    /// there is nothing here polling at any interval at all.
    private func observeMood() {
        moodCancellable = state.$mood
            .map { $0?.mood }
            .removeDuplicates()
            .sink { [weak self] moodRaw in
                guard let self, let moodRaw else { return }
                self.updateGlyph(for: moodRaw)
            }
    }

    private func updateGlyph(for moodRaw: String) {
        let symbol = Mood(rawValue: moodRaw)?.symbolName ?? Mood.asleep.symbolName
        statusItem?.button?.image = NSImage(
            systemSymbolName: symbol,
            accessibilityDescription: "Vidura — \(moodRaw.lowercased())"
        )
    }

    @objc private func togglePopover(_ sender: AnyObject?) {
        guard let button = statusItem?.button, let popover else { return }
        if popover.isShown {
            popover.performClose(sender)
        } else {
            state.refresh()
            popover.show(relativeTo: button.bounds, of: button, preferredEdge: .minY)
            NSApp.activate(ignoringOtherApps: true)
        }
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
