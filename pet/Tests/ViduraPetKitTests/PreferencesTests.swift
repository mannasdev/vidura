import XCTest
@testable import ViduraPetKit

/// Pins down the app's ONE persistence layer (spec §12): every user choice
/// that survives relaunch must write through to `UserDefaults` and read back
/// on the next launch, and "no override" must be a true *absence* of a key
/// rather than a stored empty value. These are the invariants `ViduraCore`'s
/// bin-path resolution and the picker's Auto row silently depend on, so a
/// regression to `bool(forKey:)` (which can't tell "unset" from "false") or
/// to persisting `""` for an emptied text field fails here before it can ship.
///
/// Every test runs against an INJECTED, isolated in-memory suite — never
/// `.standard`. `Preferences` takes `defaults:` precisely so tests can
/// round-trip each key without polluting the real user domain (and without
/// one test's writes leaking into the next). We derive the suite name from
/// the running test's name and wipe the domain in both `setUp` and
/// `tearDown`, so each case starts and ends from a clean slate even if a
/// prior run crashed mid-flight and left a value behind.
///
/// `@MainActor` because `Preferences` is a `@MainActor ObservableObject` —
/// constructing one and touching its `@Published` properties must happen on
/// the main actor, so the whole test class hops there.
@MainActor
final class PreferencesTests: XCTestCase {
    /// Per-test suite name, unique to the running test method so parallel or
    /// re-ordered cases can never share an in-memory domain. `self.name` is
    /// something like `-[PreferencesTests test_foo]`, which is plenty unique
    /// within the suite and stable for a given method.
    private var suiteName: String { "vidura.pet.tests.\(name)" }

    /// A fresh `UserDefaults` bound to this test's isolated suite. Constructing
    /// a new one each access is cheap and always points at the same on-disk
    /// (memory-backed, since we never persist) domain, so a value written via
    /// one handle is visible through another — which is exactly what lets us
    /// simulate a relaunch with a second `Preferences(defaults:)` below.
    private func makeDefaults() -> UserDefaults {
        // `UserDefaults(suiteName:)` for a non-standard, non-global-domain
        // name gives us a private scratch domain; force-unwrap is safe because
        // the initializer only returns nil for reserved names like the global
        // domain or `.standard`'s own identifier, which we never use here.
        UserDefaults(suiteName: suiteName)!
    }

    override func setUp() {
        super.setUp()
        // Guarantee a clean domain even if a previous crashed run left values.
        UserDefaults().removePersistentDomain(forName: suiteName)
    }

    override func tearDown() {
        // Don't let this test's writes outlive it and leak into the next case
        // (or, worse, onto disk for the developer's machine).
        UserDefaults().removePersistentDomain(forName: suiteName)
        super.tearDown()
    }

    // MARK: - Defaults when nothing is stored

    /// A fresh install has no stored values yet, so `Preferences` must seed
    /// the shipped defaults: Auto species (defer to the core's earned
    /// diagnosis), notifications ON, and no bin-path override. The
    /// notifications case is the subtle one — `object(forKey:) == nil` must
    /// win over `bool(forKey:)`'s false-for-missing, or a fresh install would
    /// silently ship with the STIRRING banner disabled.
    func test_defaults_whenNothingStored() {
        let prefs = Preferences(defaults: makeDefaults())

        XCTAssertEqual(prefs.selectedPet, Preferences.autoSelection)
        XCTAssertTrue(prefs.notificationsEnabled)
        XCTAssertNil(prefs.customBinPath)
    }

    // MARK: - Round-trips (write through one instance, read via a fresh one)

    /// Simulates a relaunch: mutate through one `Preferences`, then read the
    /// value back through a *fresh* `Preferences(defaults:)` on the same suite.
    /// A fresh instance is the honest test because it re-runs `init`'s seed
    /// reads against the store — it would catch a `didSet` that wrote to the
    /// wrong key just as much as a missing write-through.
    func test_selectedPet_roundTripsAcrossInstances() {
        let defaults = makeDefaults()
        let writer = Preferences(defaults: defaults)

        writer.selectedPet = "cat-proud"

        let reloaded = Preferences(defaults: defaults)
        XCTAssertEqual(reloaded.selectedPet, "cat-proud")
    }

    /// The `false` direction specifically: `notificationsEnabled` defaults to
    /// true, so persisting an *off* value and reading it back proves the
    /// stored `false` is honored rather than being re-seeded to true on the
    /// next launch (the exact bug the `object(forKey:) == nil` dance guards).
    func test_notificationsEnabled_persistsFalseAcrossInstances() {
        let defaults = makeDefaults()
        let writer = Preferences(defaults: defaults)

        writer.notificationsEnabled = false

        let reloaded = Preferences(defaults: defaults)
        XCTAssertFalse(reloaded.notificationsEnabled)
    }

    /// And the round-trip back to true, so a user who toggles off then on
    /// again lands on the shipped default and stays there.
    func test_notificationsEnabled_persistsTrueAcrossInstances() {
        let defaults = makeDefaults()
        let writer = Preferences(defaults: defaults)

        writer.notificationsEnabled = false
        writer.notificationsEnabled = true

        let reloaded = Preferences(defaults: defaults)
        XCTAssertTrue(reloaded.notificationsEnabled)
    }

    /// A non-empty bin path is a real override, so it must survive to the next
    /// launch verbatim — this is what `ViduraCore`'s priority-0 resolution
    /// reads to find the `vidura-*` CLIs off PATH.
    func test_customBinPath_roundTripsAcrossInstances() {
        let defaults = makeDefaults()
        let writer = Preferences(defaults: defaults)

        writer.customBinPath = "/opt/vidura/bin"

        let reloaded = Preferences(defaults: defaults)
        XCTAssertEqual(reloaded.customBinPath, "/opt/vidura/bin")
    }

    // MARK: - "No override" is a true absence, not a stored empty string

    /// Emptying the text field (setting `""`) must *remove* the key, never
    /// persist a blank. If it stored `""`, `ViduraCore` would resolve every
    /// tool against a bare `/` path (spec §9). We assert both the observable
    /// property (`nil`) and — because that's the exact value `ViduraCore`
    /// reads from a non-main-actor queue — the raw static reader.
    func test_customBinPath_emptyStringRemovesKey() {
        let defaults = makeDefaults()
        let prefs = Preferences(defaults: defaults)

        prefs.customBinPath = "/opt/vidura/bin"   // establish a stored value
        prefs.customBinPath = ""                  // then empty the field

        XCTAssertNil(prefs.customBinPath)
        XCTAssertNil(Preferences.customBinPathRaw(defaults))

        // A relaunch must also see the absence, not a resurrected blank.
        let reloaded = Preferences(defaults: defaults)
        XCTAssertNil(reloaded.customBinPath)
    }

    /// Same discipline for an explicit `nil`: clearing the override removes
    /// the key so "no override" reads as a true absence on the next launch.
    func test_customBinPath_nilRemovesKey() {
        let defaults = makeDefaults()
        let prefs = Preferences(defaults: defaults)

        prefs.customBinPath = "/opt/vidura/bin"   // establish a stored value
        prefs.customBinPath = nil                 // then clear it

        XCTAssertNil(prefs.customBinPath)
        XCTAssertNil(Preferences.customBinPathRaw(defaults))

        let reloaded = Preferences(defaults: defaults)
        XCTAssertNil(reloaded.customBinPath)
    }

    /// The raw non-main-actor reader must see a stored path too — it shares
    /// `customBinPathKey` with the write-through, so this guards against the
    /// two ever drifting to different keys.
    func test_customBinPathRaw_seesStoredValue() {
        let defaults = makeDefaults()
        let prefs = Preferences(defaults: defaults)

        prefs.customBinPath = "/opt/vidura/bin"

        XCTAssertEqual(Preferences.customBinPathRaw(defaults), "/opt/vidura/bin")
    }
}
