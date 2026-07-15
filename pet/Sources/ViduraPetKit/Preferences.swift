import Foundation
import Combine

/// The app's ONE persistence layer — a thin, observable façade over
/// `UserDefaults`. Until this file existed the pet stored nothing: species
/// was always the core's live diagnosis and every setting was a compile-time
/// constant (see the design spec §2, "there is no user override and no
/// persistence layer"). Three user choices now survive relaunch, and they
/// all live here so there is exactly one place that touches `UserDefaults`:
///
/// - `selectedPet` — `"auto"` (the `autoSelection` sentinel) to defer to the
///   core's earned diagnosis, or a pinned character id. Only ever changes
///   which *sprite* is drawn; mood/badge/notification logic stays core-driven.
/// - `notificationsEnabled` — gates the single STIRRING banner. Default ON:
///   an unset key must read as "on", because the pet shipped notifying and a
///   fresh install has no stored value yet (see the `object(forKey:)==nil`
///   dance in `init`, which is why this can't just be `bool(forKey:)`).
/// - `customBinPath` — the directory holding the `vidura-*` CLIs, for users
///   whose install isn't on `$VIDURA_BIN` or PATH. Optional: an empty field
///   means "no override", so we `removeObject` rather than storing `""`.
///
/// `@MainActor` because it's an `ObservableObject` driving SwiftUI — the
/// views (`SettingsView`, `PetsView`) mutate it on the main actor, and the
/// `@Published` write-through in each `didSet` runs there. The one exception
/// is `customBinPathRaw`, which `ViduraCore` calls from its utility-QoS
/// queues; that's `nonisolated static` and reads `UserDefaults` directly (a
/// thread-safe read), so a non-main-actor caller never has to hop actors
/// just to resolve a bin path. The key constant is shared so the writer here
/// and that raw reader can never disagree about where the value lives.
///
/// The `defaults` are injectable (default `.standard`) so tests can round-trip
/// each key against an isolated in-memory suite without polluting the real
/// user domain — the persistence discipline the spec's testing plan (§12)
/// calls for.
@MainActor
public final class Preferences: ObservableObject {
    // `nonisolated` because these are plain compile-time string constants read
    // from non-main-actor contexts (`customBinPathRaw`, `ViduraCore`'s
    // utility-QoS bin-path resolution, and `PetResolution.resolve`). Leaving
    // them main-actor-isolated makes those reads an error under Swift 6.
    public nonisolated static let selectedPetKey = "vidura.pet.selectedPet"
    public nonisolated static let notificationsEnabledKey = "vidura.pet.notificationsEnabled"
    public nonisolated static let customBinPathKey = "vidura.pet.customBinPath"

    /// Sentinel stored in `selectedPet` meaning "defer to the core's earned
    /// diagnosis" — i.e. today's behavior. Kept as a named constant because
    /// `PetResolution.resolve` and the picker both compare against it, and a
    /// stray string literal in either would silently break the Auto row.
    public nonisolated static let autoSelection = "auto"

    @Published public var selectedPet: String {
        didSet { defaults.set(selectedPet, forKey: Self.selectedPetKey) }
    }

    @Published public var notificationsEnabled: Bool {
        didSet { defaults.set(notificationsEnabled, forKey: Self.notificationsEnabledKey) }
    }

    /// Write-through with a deliberate asymmetry: a non-empty path is stored,
    /// but `nil` (or an empty string — an emptied text field) *removes* the
    /// key entirely rather than persisting `""`. That keeps "no override" a
    /// true absence, so `ViduraCore`'s priority-0 check (spec §9) sees either
    /// a real directory or nothing, never a blank that would resolve every
    /// tool to a bare `/` path.
    @Published public var customBinPath: String? {
        didSet {
            if let path = customBinPath, !path.isEmpty {
                defaults.set(path, forKey: Self.customBinPathKey)
            } else {
                defaults.removeObject(forKey: Self.customBinPathKey)
                // Normalize an emptied field (`""`) back to `nil` so the
                // observable property reads as a true absence too, not just the
                // stored key. Assigning inside `didSet` does NOT re-fire it, so
                // this collapses "" → nil once without recursion. Guarded so a
                // genuine `nil` assignment doesn't pointlessly re-assign nil.
                if customBinPath != nil { customBinPath = nil }
            }
        }
    }

    private let defaults: UserDefaults

    public init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
        // Setting a stored property in `init` does NOT fire its `didSet`,
        // which is exactly what we want: these are seed reads, not writes.
        // (If they fired, launch would pointlessly re-store every value —
        // and, worse, the `notificationsEnabled` default-true seed would
        // write `true` back on first launch, defeating the "unset" test.)
        self.selectedPet = defaults.string(forKey: Self.selectedPetKey) ?? Self.autoSelection
        // Default ON when the key has never been set: `bool(forKey:)` alone
        // returns `false` for a missing key, which would silently disable
        // notifications on a fresh install. Distinguish "absent" (→ true)
        // from "explicitly false" via `object(forKey:) == nil`.
        self.notificationsEnabled = defaults.object(forKey: Self.notificationsEnabledKey) == nil
            ? true
            : defaults.bool(forKey: Self.notificationsEnabledKey)
        self.customBinPath = defaults.string(forKey: Self.customBinPathKey)
    }

    /// Thread-safe raw read for NON-main-actor callers: `ViduraCore` resolves
    /// bin paths on utility-QoS queues and can't (and shouldn't) hop to the
    /// main actor just to read one string. `UserDefaults` reads are themselves
    /// thread-safe, so no locking is needed here — this is `nonisolated` and
    /// goes straight to the store. Shares `customBinPathKey` with the writer
    /// above so the two can never drift.
    nonisolated public static func customBinPathRaw(_ defaults: UserDefaults = .standard) -> String? {
        defaults.string(forKey: customBinPathKey)
    }
}
