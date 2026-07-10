import Foundation
import UserNotifications
import AppKit

/// The pet's one piece of mutable state: current mood + ledger, refreshed
/// on a slow poll. Anti-Clippy invariants live here as much as anywhere —
/// no timer in this file fires faster than 60s, and the STIRRING
/// notification fires exactly once per transition into that mood.
@MainActor
final class StateModel: ObservableObject {
    @Published private(set) var mood: MoodState?
    @Published private(set) var entries: [LedgerEntry] = []
    @Published private(set) var lastError: String?
    /// Set once per STIRRING transition so the popover can show the
    /// "counsel earned" framing even if the user opens it before the
    /// notification banner is dismissed. Not itself a notification.
    @Published private(set) var justEnteredStirring = false

    private var previousMood: String?
    private var pollTimer: Timer?
    private var sweepTimer: Timer?
    private var sweepInFlight = false

    /// Poll interval: 60s minimum per the plan's anti-Clippy invariant
    /// ("no timers faster than 60s"). Do not lower this.
    static let pollInterval: TimeInterval = 60
    /// Ambient sweep interval: 30 minutes, per the plan.
    static let sweepInterval: TimeInterval = 30 * 60

    init() {
        requestNotificationAuthorization()
    }

    func start() {
        refresh()
        pollTimer?.invalidate()
        pollTimer = Timer.scheduledTimer(withTimeInterval: Self.pollInterval, repeats: true) { [weak self] _ in
            Task { @MainActor in self?.refresh() }
        }
        sweepTimer?.invalidate()
        sweepTimer = Timer.scheduledTimer(withTimeInterval: Self.sweepInterval, repeats: true) { [weak self] _ in
            Task { @MainActor in self?.runAmbientSweep() }
        }
    }

    func stop() {
        pollTimer?.invalidate()
        pollTimer = nil
        sweepTimer?.invalidate()
        sweepTimer = nil
    }

    /// Re-fetch mood + ledger. Safe to call from a manual popover-open
    /// refresh as well as the timer — it's just two fast local reads.
    func refresh() {
        Task {
            await self.pollState()
            await self.pollLedger()
        }
    }

    private func pollState() async {
        do {
            let result = try await ViduraCore.runAsync("vidura-state")
            guard result.exitCode == 0 else {
                lastError = result.stderr.isEmpty ? "vidura-state exited \(result.exitCode)" : result.stderr
                return
            }
            let decoded = try JSONDecoder().decode(MoodState.self, from: Data(result.stdout.utf8))
            applyNewMood(decoded)
            lastError = nil
        } catch {
            lastError = "\(error)"
        }
    }

    private func pollLedger() async {
        do {
            let result = try await ViduraCore.runAsync("vidura-ledger", arguments: ["list", "--json"])
            guard result.exitCode == 0 else {
                lastError = result.stderr.isEmpty ? "vidura-ledger exited \(result.exitCode)" : result.stderr
                return
            }
            let decoded = try JSONDecoder().decode([LedgerEntry].self, from: Data(result.stdout.utf8))
            entries = decoded.filter { $0.status == "pending" }
        } catch {
            lastError = "\(error)"
        }
    }

    /// Applies a freshly-decoded mood, firing the ONE notification the
    /// whole app ever sends: the ASLEEP/CONTENT/etc. -> STIRRING
    /// transition. Staying in STIRRING (or re-entering it on a later
    /// poll without ever having left) never re-fires it.
    private func applyNewMood(_ new: MoodState) {
        let wasStirring = (previousMood == Mood.stirring.rawValue)
        let isStirring = (new.mood == Mood.stirring.rawValue)
        if isStirring && !wasStirring {
            justEnteredStirring = true
            fireStirringNotification(pendingCount: new.pendingCount)
        } else if !isStirring {
            justEnteredStirring = false
        }
        previousMood = new.mood
        mood = new
    }

    // MARK: - Notifications

    /// UNUserNotificationCenter requires a real app bundle (a bundle
    /// identifier) — a bare SwiftPM debug binary run outside an .app
    /// wrapper has none and throws an NSInternalInconsistencyException
    /// merely by touching .current(). Treat "no bundle" exactly like
    /// "permission denied": skip silently, the glyph still changes.
    private var hasAppBundle: Bool {
        Bundle.main.bundleIdentifier != nil
    }

    private func requestNotificationAuthorization() {
        guard hasAppBundle else { return }
        UNUserNotificationCenter.current().requestAuthorization(options: [.alert]) { _, _ in
            // Denial is handled silently — the glyph still changes
            // regardless of notification permission (plan requirement).
        }
    }

    private func fireStirringNotification(pendingCount: Int) {
        guard hasAppBundle else { return }
        let content = UNMutableNotificationContent()
        content.title = "Vidura"
        let plural = pendingCount == 1 ? "" : "s"
        content.body = "Counsel earned — \(pendingCount) suggestion\(plural) waiting."
        let request = UNNotificationRequest(
            identifier: "vidura.stirring.\(UUID().uuidString)",
            content: content,
            trigger: nil
        )
        UNUserNotificationCenter.current().add(request) { _ in
            // Best-effort; a failed notification never blocks the mood
            // change itself, which is the load-bearing signal.
        }
    }

    // MARK: - Ambient sweep

    /// Runs vidura-sweep in the background at .utility QoS every 30
    /// minutes. Skips if one is already in flight so overlapping sweeps
    /// never stack up.
    func runAmbientSweep() {
        guard !sweepInFlight else { return }
        sweepInFlight = true
        Task {
            defer { Task { @MainActor in self.sweepInFlight = false } }
            _ = try? await ViduraCore.runAsync(
                "vidura-sweep",
                timeout: ViduraCore.sweepTimeout,
                qos: .utility
            )
            await self.pollState()
            await self.pollLedger()
        }
    }

    // MARK: - Ledger actions (called from CardView)

    func accept(_ id: Int) async {
        _ = try? await ViduraCore.runAsync("vidura-ledger", arguments: ["accept", String(id)])
        refresh()
    }

    func dismiss(_ id: Int) async {
        _ = try? await ViduraCore.runAsync("vidura-ledger", arguments: ["dismiss", String(id)])
        refresh()
    }

    func celebrate(_ id: Int) async {
        _ = try? await ViduraCore.runAsync("vidura-ledger", arguments: ["celebrate", String(id)])
        refresh()
    }

    /// Dry-run preview for the Do confirmation sheet — never mutates.
    func doDryRun(_ id: Int) async -> ViduraCore.Result? {
        try? await ViduraCore.runAsync("vidura-do", arguments: [String(id), "--dry-run"])
    }

    /// Confirmed execution: the pet has already shown the exact action
    /// (from doDryRun's output) and the user tapped Confirm — --yes is
    /// safe here per Task 1's contract because that confirmation just
    /// happened in this UI.
    func doConfirmed(_ id: Int) async -> ViduraCore.Result? {
        let result = try? await ViduraCore.runAsync("vidura-do", arguments: [String(id), "--yes"])
        refresh()
        return result
    }
}
