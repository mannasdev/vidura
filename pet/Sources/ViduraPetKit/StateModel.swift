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

    /// Increments once per `panelDidOpen()` call — CardView observes this
    /// (rather than SwiftUI's `onAppear`, which only fires once for the
    /// lifetime of the reused NSHostingController) to know exactly when a
    /// fresh panel-open has happened, so the celebration hop can fire "at
    /// most once per panel-open" as the animation spec requires.
    @Published private(set) var panelOpenCount = 0
    /// Whether `adopted_uncelebrated` was non-empty at the moment of the
    /// most recent `panelDidOpen()` call — the celebration hop's trigger
    /// condition, captured once at open time so a later `celebrate()`
    /// call (which empties the list) can't retroactively cancel a hop
    /// that already started.
    @Published private(set) var shouldCelebrateOnOpen = false

    /// Which of the three in-panel surfaces (home / pets / settings) the
    /// shared `NSPanel` is currently showing. Footer buttons set it; the
    /// back controls reset it to `.home`; `AppDelegate.hidePanel()` also
    /// resets it so reopening always lands on the pet. See `PanelRoute`.
    @Published public var route: PanelRoute = .home

    /// User-facing settings (selected pet, notification toggle, custom bin
    /// path). Held here because it's the one object both `AppDelegate` and
    /// `CardView` already share, and it gates two behaviors this model owns:
    /// which sprite `CardView` resolves, and whether `applyNewMood` fires
    /// the STIRRING banner. Injected (with a default) so tests can supply an
    /// isolated `Preferences` backed by a scratch `UserDefaults`.
    public let preferences: Preferences

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

    /// `preferences` defaults to `nil` (not `Preferences()`) because a default
    /// argument expression is evaluated in a nonisolated context, and
    /// `Preferences` is `@MainActor` — constructing it there is a concurrency
    /// error. The real default is built inside this (main-actor-isolated) body
    /// instead, where the isolation is satisfied.
    public init(preferences: Preferences? = nil) {
        self.preferences = preferences ?? Preferences()
        requestNotificationAuthorization()
    }

    /// Test-only seeding hook: builds a StateModel with fixed entries and
    /// mood, and skips notification-authorization requests (which throw
    /// outside a real app bundle). Used by ContentSizingTests to measure
    /// CardView's fitting size without any CLI calls or live process.
    public init(preview entries: [LedgerEntry], mood: MoodState?, preferences: Preferences? = nil) {
        self.preferences = preferences ?? Preferences()
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

    /// Called by AppDelegate exactly once per panel-open (not per
    /// `refresh()`, which also fires on the 60s poll timer while the
    /// panel is closed). Captures whether a celebration hop should fire
    /// for this open, then refreshes as usual.
    public func panelDidOpen() {
        shouldCelebrateOnOpen = !(mood?.adoptedUncelebratedIds.isEmpty ?? true)
        panelOpenCount += 1
        refresh()
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
        let transitionNotify = MoodTransition.shouldNotify(previous: previousMood, current: new.mood)
        if transitionNotify {
            // The in-panel "counsel earned" framing (`justEnteredStirring`)
            // is a UI cue, NOT a notification — it always fires on the
            // transition so the popover reads correctly regardless of the
            // user's notification preference. Only the OS banner is gated by
            // `notificationsEnabled`; muting notifications must never mute
            // the glyph/panel signal (plan requirement).
            justEnteredStirring = true
            if Self.shouldFireStirring(
                notificationsEnabled: preferences.notificationsEnabled,
                transitionNotify: transitionNotify
            ) {
                fireStirringNotification(pendingCount: new.pendingCount)
            }
        } else if !isStirring {
            justEnteredStirring = false
        }
        previousMood = new.mood
        mood = new
    }

    /// Pure decision for whether the STIRRING OS banner should fire: both the
    /// mood actually transitioned into STIRRING (`transitionNotify`, from
    /// `MoodTransition.shouldNotify`) AND the user has notifications enabled.
    /// Factored out — like `MoodTransition.shouldNotify` — so the AND-gate
    /// can be unit-tested without a running `StateModel` or notification
    /// center.
    /// `nonisolated` so the pure AND-gate can be unit-tested synchronously
    /// from a non-main-actor test context (`NotificationGatingTests`) — it
    /// touches no isolated state, exactly like `MoodTransition.shouldNotify`.
    nonisolated static func shouldFireStirring(notificationsEnabled: Bool, transitionNotify: Bool) -> Bool {
        notificationsEnabled && transitionNotify
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
    ///
    /// `sweepInFlight` is only an in-process guard — it says nothing
    /// about the hook CLI's own sweep running concurrently in a separate
    /// process. Cross-process coordination lives inside vidura-sweep
    /// itself (a Python-side lock), not here.
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
