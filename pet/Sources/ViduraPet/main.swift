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

    private static let panelSize = NSSize(width: 400, height: 540)

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)

        let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
        if let button = item.button {
            // Drawn in code (PixelPetMenuBarMark), never an SF Symbol
            // lookup that could fail to resolve — the button image must
            // ALWAYS be non-nil, or a crowded menu bar can render an
            // empty status item with no anchor for the panel.
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

    /// The one fixed menu-bar mark, rendered in template mode so AppKit
    /// tints it correctly for both light and dark menu bars. Drawn in
    /// code (never an SF Symbol lookup) so this is never nil.
    private static func menuBarImage() -> NSImage {
        let image = PixelPetMenuBarMark.image()
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
        guard let button = statusItem?.button, let buttonWindow = button.window else { return }
        state.refresh()

        // The button's rect in SCREEN coordinates — measured, not
        // inferred by any popover machinery. X centers the panel under
        // the icon; Y hangs it just below the menu bar. Both clamped to
        // the button's own screen so a crowded bar or edge icon can't
        // push the panel off-screen.
        let buttonRect = buttonWindow.convertToScreen(button.convert(button.bounds, to: nil))
        let size = Self.panelSize
        let screenFrame = (buttonWindow.screen ?? NSScreen.main)?.visibleFrame
            ?? NSRect(x: 0, y: 0, width: 1440, height: 900)

        var x = buttonRect.midX - size.width / 2
        x = min(max(x, screenFrame.minX + 8), screenFrame.maxX - size.width - 8)
        let yTop = buttonRect.minY - 6
        let y = max(yTop - size.height, screenFrame.minY + 8)

        let panel = self.panel ?? makePanel()
        self.panel = panel
        panel.setFrame(NSRect(x: x, y: y, width: size.width, height: size.height), display: true)
        panel.makeKeyAndOrderFront(nil)
        installOutsideClickMonitor()
    }

    private func hidePanel() {
        panel?.orderOut(nil)
        removeOutsideClickMonitor()
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
            contentRect: NSRect(origin: .zero, size: Self.panelSize),
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

        let content = CardView(state: state)
            .frame(width: Self.panelSize.width, height: Self.panelSize.height)
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
