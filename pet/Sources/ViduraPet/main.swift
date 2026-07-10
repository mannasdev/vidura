import AppKit
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
    private var moodObservation: Task<Void, Never>?

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
        moodObservation?.cancel()
    }

    /// Mirrors state.mood into the status item's glyph. A plain poll
    /// loop (checked every second) rather than Combine plumbing — this
    /// only ever changes a static SF Symbol, never animates it.
    private func observeMood() {
        moodObservation = Task { [weak self] in
            var lastRendered: String?
            while !Task.isCancelled {
                if let self, let mood = self.state.mood?.mood, mood != lastRendered {
                    self.updateGlyph(for: mood)
                    lastRendered = mood
                }
                try? await Task.sleep(nanoseconds: 1_000_000_000)
            }
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
