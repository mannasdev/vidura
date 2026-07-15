import SwiftUI
#if canImport(AppKit)
import AppKit
#endif

/// The Settings surface (`PanelRoute.settings`) — the four controls the spec
/// (§8) locks: launch-at-login, CLI location (VIDURA_BIN override),
/// notifications toggle, and a read-only About/version block. Short enough
/// (spec §7) that it needs no ScrollView.
///
/// Persistence discipline: every mutable control writes through
/// `Preferences` (`notificationsEnabled`, `customBinPath`) EXCEPT
/// launch-at-login, whose single source of truth is the system itself
/// (`SMAppService`, read live through the injected `LoginItemControlling`
/// seam). Nothing here caches a login-item bool locally.
///
/// Inner content only — the outer panel chrome lives on `CardView.body`.
struct SettingsView: View {
    @ObservedObject var state: StateModel
    @ObservedObject var prefs: Preferences

    /// Injected launch-at-login control (spec §8.1). Defaults to the real
    /// `LaunchAtLogin` over `SMAppService`; tests / previews can pass a fake
    /// `LoginItemControlling`. Held as the existential the view depends on.
    let loginItem: any LoginItemControlling

    init(state: StateModel, prefs: Preferences, loginItem: any LoginItemControlling = LaunchAtLogin()) {
        self.state = state
        self.prefs = prefs
        self.loginItem = loginItem
    }

    /// Mirror of the live login-item state. Seeded from `loginItem.isEnabled`
    /// on appear and after each toggle so the row reflects the system (which
    /// the user can also change from System Settings) rather than a stale
    /// cache — the source of truth stays `SMAppService`, this is just the
    /// view's rendering of it.
    @State private var launchAtLoginOn = false
    /// Surfaces an `SMAppService` register/unregister throw inline instead of
    /// silently dropping it (the row is gated on `isAvailable`, so this path
    /// is only reachable in the packaged app).
    @State private var launchAtLoginError: String?

    /// Local editing buffer for the bin-path field. Bound to the TextField so
    /// keystrokes don't thrash `Preferences` (and its `didSet` write-through)
    /// on every character; committed to `prefs.customBinPath` on submit / when
    /// the folder picker returns. Seeded from the stored value on appear.
    @State private var binPathDraft = ""

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            PanelSurfaceHeader(title: "Settings") { state.route = .home }

            VStack(alignment: .leading, spacing: 18) {
                launchAtLoginSection
                binPathSection
                notificationsSection
                aboutSection
            }
            .padding(.horizontal, 16)
            .padding(.top, 16)
            .padding(.bottom, 18)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .onAppear {
            launchAtLoginOn = loginItem.isEnabled
            binPathDraft = prefs.customBinPath ?? ""
        }
    }

    // MARK: - 1. Launch at login (spec §8.1)

    @ViewBuilder
    private var launchAtLoginSection: some View {
        settingRow(title: "Launch at login") {
            if loginItem.isAvailable {
                Toggle("", isOn: launchAtLoginBinding)
                    .labelsHidden()
                    .toggleStyle(.switch)
                    .controlSize(.small)
            } else {
                // No app bundle (bare SwiftPM binary): SMAppService has nothing
                // to register, so show the row disabled with a note rather than
                // offering a toggle that could only throw (spec §8.1, §11).
                Text("Available in the packaged app")
                    .font(Theme.footerFont)
                    .foregroundStyle(Theme.textTertiary)
            }
        }
        if let launchAtLoginError {
            fieldHint(launchAtLoginError, isError: true)
        }
    }

    /// Drives the toggle through the `LoginItemControlling` seam: the setter
    /// calls `setEnabled` (the system is the source of truth) and re-reads the
    /// live state so a refused change doesn't leave the switch lying.
    private var launchAtLoginBinding: Binding<Bool> {
        Binding(
            get: { launchAtLoginOn },
            set: { newValue in
                do {
                    try loginItem.setEnabled(newValue)
                    launchAtLoginError = nil
                } catch {
                    launchAtLoginError = "Could not update login item: \(error.localizedDescription)"
                }
                // Re-read live regardless — a throw leaves the system where it
                // was, and the switch must reflect that, not the attempted value.
                launchAtLoginOn = loginItem.isEnabled
            }
        )
    }

    // MARK: - 2. CLI location / VIDURA_BIN (spec §8.2)

    private var binPathSection: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("CLI location")
                .font(Theme.summaryFont)
                .foregroundStyle(Theme.textPrimary)
            Text("Folder holding the vidura-* commands. Leave empty to use $VIDURA_BIN or your PATH.")
                .font(Theme.footerFont)
                .foregroundStyle(Theme.textSecondary)
                .fixedSize(horizontal: false, vertical: true)

            HStack(spacing: 8) {
                TextField("/path/to/vidura/bin", text: $binPathDraft, onCommit: commitBinPath)
                    .textFieldStyle(.roundedBorder)
                    .font(Theme.evidenceFont)
                Button("Choose…", action: chooseBinFolder)
                    .controlSize(.small)
            }

            binPathValidityHint
        }
    }

    /// Immediate inline feedback on whether the entered directory actually
    /// holds an executable `vidura-state` (spec §8.2). Only shown for a
    /// non-empty draft — an empty field is the valid "no override" state.
    @ViewBuilder
    private var binPathValidityHint: some View {
        let trimmed = binPathDraft.trimmingCharacters(in: .whitespacesAndNewlines)
        if !trimmed.isEmpty {
            if Self.directoryHasStateCLI(trimmed) {
                fieldHint("Found vidura-state here.", isError: false)
            } else {
                fieldHint("No executable vidura-state in this folder.", isError: true)
            }
        }
    }

    /// True when `dir/vidura-state` exists and is executable — the same
    /// priority-0 candidate `ViduraCore.resolveBinPath` will test, so the
    /// inline hint and the actual resolution never disagree.
    static func directoryHasStateCLI(_ dir: String) -> Bool {
        let candidate = (dir as NSString).appendingPathComponent("vidura-state")
        return FileManager.default.isExecutableFile(atPath: candidate)
    }

    /// Persist the edited path and take it live: write-through to
    /// `Preferences` (empty → removes the key, i.e. "no override"), then
    /// invalidate the cached resolution and refresh so a correction clears the
    /// "vidura CLIs not found" error without a relaunch (spec §8.2, §9).
    private func commitBinPath() {
        let trimmed = binPathDraft.trimmingCharacters(in: .whitespacesAndNewlines)
        prefs.customBinPath = trimmed.isEmpty ? nil : trimmed
        ViduraCore.invalidateBinPathCache()
        state.refresh()
    }

    private func chooseBinFolder() {
        #if canImport(AppKit)
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.allowsMultipleSelection = false
        if panel.runModal() == .OK, let url = panel.url {
            binPathDraft = url.path
            commitBinPath()
        }
        #endif
    }

    // MARK: - 3. Notifications (spec §8.3)

    private var notificationsSection: some View {
        VStack(alignment: .leading, spacing: 4) {
            settingRow(title: "Notifications") {
                Toggle("", isOn: $prefs.notificationsEnabled)
                    .labelsHidden()
                    .toggleStyle(.switch)
                    .controlSize(.small)
            }
            Text("When off, the pet still changes mood — only the banner is muted.")
                .font(Theme.footerFont)
                .foregroundStyle(Theme.textSecondary)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    // MARK: - 4. About / version (spec §8.4)

    private var aboutSection: some View {
        VStack(alignment: .leading, spacing: 5) {
            Rectangle()
                .fill(Theme.border)
                .frame(height: 1)
                .padding(.bottom, 6)

            Text("Vidura \(Self.appVersion)")
                .font(Theme.summaryFont)
                .foregroundStyle(Theme.textPrimary)

            // The currently-diagnosed character + reason, so even in Auto the
            // user can see *why* they are what they are (spec §8.4). Read-only,
            // straight off the live mood.
            if let reason = state.mood?.characterReason, !reason.isEmpty {
                Text(reason)
                    .font(Theme.footerFont)
                    .foregroundStyle(Theme.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            } else {
                Text("Getting to know how you work…")
                    .font(Theme.footerFont)
                    .foregroundStyle(Theme.textTertiary)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    /// The app's short version string from the bundle, or a dev placeholder
    /// when running as a bare SwiftPM binary with no Info.plist.
    static var appVersion: String {
        Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "dev"
    }

    // MARK: - Row helpers

    /// A labelled row with a trailing control — the shared shape for the
    /// toggle rows so title typography and spacing stay identical.
    private func settingRow<Control: View>(
        title: String,
        @ViewBuilder control: () -> Control
    ) -> some View {
        HStack(alignment: .center) {
            Text(title)
                .font(Theme.summaryFont)
                .foregroundStyle(Theme.textPrimary)
            Spacer()
            control()
        }
        .frame(maxWidth: .infinity)
    }

    private func fieldHint(_ text: String, isError: Bool) -> some View {
        Text(text)
            .font(Theme.footerFont)
            .foregroundStyle(isError ? AnyShapeStyle(.red) : AnyShapeStyle(Theme.textTertiary))
            .fixedSize(horizontal: false, vertical: true)
    }
}
