import Foundation
import UserNotifications
import AppKit

/// The pet's one piece of mutable state: current mood + ledger, refreshed
/// on a slow poll. Anti-Clippy invariants live here as much as anywhere —
/// no timer in this file fires faster than 60s, and the STIRRING
/// notification fires exactly once per transition into that mood.
@MainActor
public final class StateModel: ObservableObject {
    @Published private(set) var mood: MoodState?
    @Published private(set) var entries: [LedgerEntry] = []
    @Published private(set) var counts: LedgerCounts = LedgerCounts(accepted: 0, dismissed: 0)
    @Published private(set) var lastError: String?
    /// Set once per STIRRING transition so the popover can show the
    /// "counsel earned" framing even if the user opens it before the
    /// notification banner is dismissed. Not itself a notification.
    @Published private(set) var justEnteredStirring = false

    private var previousMood: String?
    private var pollTimer: Timer?
    private var sweepTimer: Timer?
    private var sweepInFlight = false
    private var refreshInFlight = false

    /// Poll interval: 60s minimum per the plan's anti-Clippy invariant
    /// ("no timers faster than 60s"). Do not lower this.
    public static let pollInterval: TimeInterval = 60
    /// Ambient sweep interval: 30 minutes, per the plan.
    public static let sweepInterval: TimeInterval = 30 * 60

    public init() {
        requestNotificationAuthorization()
    }

    /// Test-only seeding hook: builds a StateModel with fixed entries and
    /// mood, and skips notification-authorization requests (which throw
    /// outside a real app bundle). Used by ContentSizingTests to measure
    /// CardView's fitting size without any CLI calls or live process.
    public init(preview entries: [LedgerEntry], mood: MoodState?) {
        self.entries = entries
        self.mood = mood
        self.counts = LedgerCounts.derive(from: entries)
    }

    public func start() {
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

    public func stop() {
        pollTimer?.invalidate()
        pollTimer = nil
        sweepTimer?.invalidate()
        sweepTimer = nil
    }

    /// Re-fetch mood + ledger. Safe to call from a manual popover-open
    /// refresh as well as the timer — it's just two fast local reads.
    /// Guarded against overlap: the popover-open refresh and the 60s
    /// timer can otherwise fire close together and race, which used to
    /// let the STIRRING transition's notification double-fire.
    public func refresh() {
        guard !refreshInFlight else { return }
        refreshInFlight = true
        Task {
            defer { refreshInFlight = false }
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
        } catch let error as ViduraCore.CoreError {
            lastError = Self.friendlyMessage(for: error)
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
            // `vidura-ledger list --json` returns ALL entries regardless
            // of status — `entries` (pending, shown as cards) and
            // `counts` (accepted/dismissed, shown in the footer) are both
            // derived from this one unfiltered decode.
            let decoded = try JSONDecoder().decode([LedgerEntry].self, from: Data(result.stdout.utf8))
            entries = decoded.filter { $0.status == "pending" }
            counts = LedgerCounts.derive(from: decoded)
        } catch let error as ViduraCore.CoreError {
            lastError = Self.friendlyMessage(for: error)
        } catch {
            lastError = "\(error)"
        }
    }

    /// A short, actionable line for the popover's error slot — the pet
    /// otherwise just looks asleep/empty when the CLIs can't be found or
    /// keep failing, which is indistinguishable from "nothing pending".
    private static func friendlyMessage(for error: ViduraCore.CoreError) -> String {
        switch error {
        case .binaryNotFound:
            return "vidura CLIs not found — set VIDURA_BIN"
        case .timedOut(let tool):
            return "\(tool) timed out"
        }
    }

    /// Applies a freshly-decoded mood, firing the ONE notification the
    /// whole app ever sends: the ASLEEP/CONTENT/etc. -> STIRRING
    /// transition. Staying in STIRRING (or re-entering it on a later
    /// poll without ever having left) never re-fires it. The actual
    /// transition decision lives in `MoodTransition.shouldNotify` so it
    /// can be unit-tested without a running StateModel.
    private func applyNewMood(_ new: MoodState) {
        let isStirring = (new.mood == Mood.stirring.rawValue)
        if MoodTransition.shouldNotify(previous: previousMood, current: new.mood) {
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
    public func runAmbientSweep() {
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

    public func accept(_ id: Int) async {
        _ = try? await ViduraCore.runAsync("vidura-ledger", arguments: ["accept", String(id)])
        refresh()
    }

    public func dismiss(_ id: Int) async {
        _ = try? await ViduraCore.runAsync("vidura-ledger", arguments: ["dismiss", String(id)])
        refresh()
    }

    public func celebrate(_ id: Int) async {
        _ = try? await ViduraCore.runAsync("vidura-ledger", arguments: ["celebrate", String(id)])
        refresh()
    }

    /// Dry-run preview for the Do confirmation sheet — never mutates.
    /// Explicitly checks the exit code: only a clean exit (0) with
    /// non-empty stdout counts as a trustworthy preview. Anything else —
    /// nonzero exit, empty output, a thrown/timed-out/missing-binary
    /// error — is surfaced as a hard failure so the sheet never offers a
    /// live Confirm button over a preview that isn't real.
    public func doDryRun(_ id: Int) async -> DryRunOutcome {
        do {
            let result = try await ViduraCore.runAsync("vidura-do", arguments: [String(id), "--dry-run"])
            guard result.exitCode == 0 else {
                let detail = result.stderr.isEmpty ? "exited \(result.exitCode)" : result.stderr
                return .failure(message: "Dry run failed: \(detail)")
            }
            guard !result.stdout.isEmpty else {
                return .failure(message: "Dry run produced no preview.")
            }
            return .success(preview: result.stdout)
        } catch let error as ViduraCore.CoreError {
            return .failure(message: Self.friendlyMessage(for: error))
        } catch {
            return .failure(message: "\(error)")
        }
    }

    /// Confirmed execution: the pet has already shown the exact action
    /// (from doDryRun's output) and the user tapped Confirm — --yes is
    /// safe here per Task 1's contract because that confirmation just
    /// happened in this UI.
    public func doConfirmed(_ id: Int) async -> ViduraCore.Result? {
        let result = try? await ViduraCore.runAsync("vidura-do", arguments: [String(id), "--yes"])
        refresh()
        return result
    }
}
