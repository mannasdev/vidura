import Foundation
import ServiceManagement

/// The launch-at-login control, behind a protocol seam so `SettingsView`'s
/// toggle logic can be exercised against a fake without ever touching the
/// real `SMAppService` (which mutates system state and can't run in a unit
/// test). This mirrors the `LoginItemControlling` split the design spec
/// (§8.1, §12) calls for: the view depends only on the protocol, the app
/// injects `LaunchAtLogin`, tests inject a stub.
///
/// Launch-at-login has **no** entry in `Preferences`/`UserDefaults` — its
/// single source of truth is the system itself (`SMAppService.mainApp.status`),
/// read live every time. Persisting it locally would only let the app's idea
/// of the setting drift from the OS's actual login-item registry.
public protocol LoginItemControlling {
    /// Whether the control can act at all. False when the process is a bare
    /// SwiftPM debug binary with no real `.app` wrapper: `SMAppService`
    /// requires a bundle to register against, so the UI shows the row
    /// **disabled** (with an "available in the packaged app" note) instead
    /// of offering a toggle that could only ever throw. Same "no bundle"
    /// condition `StateModel.hasAppBundle` uses to no-op notifications.
    var isAvailable: Bool { get }

    /// The live system state — `true` when the app is currently registered
    /// as a login item. Read fresh so the toggle always reflects reality
    /// (e.g. if the user removed the item from System Settings) rather than
    /// a cached local copy.
    var isEnabled: Bool { get }

    /// Register (`enabled == true`) or unregister the login item. Throws
    /// when there is no app bundle to register — callers should gate on
    /// `isAvailable` first so this only runs where it can succeed.
    func setEnabled(_ enabled: Bool) throws
}

/// Production `LoginItemControlling` over `SMAppService.mainApp`.
///
/// `SMAppService` is available from macOS 13 — the package's deployment
/// target — so no `@available` guard is needed anywhere it's used.
public struct LaunchAtLogin: LoginItemControlling {
    public init() {}

    /// Requires a real bundle identifier, the same guard
    /// `StateModel.hasAppBundle` applies before touching
    /// `UNUserNotificationCenter`: a bare debug binary has no bundle id and
    /// `SMAppService` has nothing to register, so the Settings row is
    /// disabled rather than throwing.
    public var isAvailable: Bool { Bundle.main.bundleIdentifier != nil }

    /// Reads the live registration status straight from the system registry
    /// — no local cache to fall out of sync with System Settings.
    public var isEnabled: Bool { SMAppService.mainApp.status == .enabled }

    /// `register()`/`unregister()` throw when there is no app bundle (a bare
    /// SwiftPM binary) or when the OS refuses the change. `isAvailable` lets
    /// the UI disable the row up front so this throw path is only reached in
    /// the packaged app, where it's a genuine (surfaceable) error.
    public func setEnabled(_ enabled: Bool) throws {
        if enabled {
            try SMAppService.mainApp.register()
        } else {
            try SMAppService.mainApp.unregister()
        }
    }
}
