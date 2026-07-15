import XCTest
@testable import ViduraPetKit

/// Guards ViduraCore's priority-0 custom-bin-path override and its cache
/// invalidation (spec §9). The Settings panel lets a user point the pet at
/// a directory holding the `vidura-*` CLIs, and that deliberate GUI choice
/// must outrank every ambient/environmental default — `$VIDURA_BIN`, PATH,
/// and the dev fallback. Two properties are pinned here:
///
///  1. When `Preferences.customBinPath` names a directory that actually
///     contains an executable for the tool, `binPath` resolves *there*,
///     ahead of anything PATH would offer.
///  2. Clearing that setting and calling `invalidateBinPathCache()` drops
///     the cached hit, so resolution stops returning the (now removed)
///     custom directory instead of wedging on the stale value forever —
///     which is the whole reason the setting's change handler must invalidate.
///
/// Both tests are hermetic. `Preferences.customBinPathRaw()` reads
/// `UserDefaults.standard` by default, and `ViduraCore` calls that no-arg
/// form, so the override key has to live on `.standard` — but we treat it as
/// borrowed state: `setUp` clears any pre-existing value and `tearDown`
/// removes it again, so the real user domain is never left polluted. The
/// `whichResolver` seam is stubbed to return `nil` throughout, which pins
/// the PATH branch to a known-empty result: that way the *only* route by
/// which `binPath` could return the temp directory is priority 0, and the
/// post-invalidation assertion can't be fooled by a real `vidura-state`
/// sitting on the developer's PATH.
final class ViduraCoreBinPathTests: XCTestCase {

    /// The temp directory we plant a fake `vidura-state` executable in. Held
    /// as a stored property so `tearDown` can tear it back down regardless of
    /// which assertion (or failure) ended the test.
    private var tempDir: URL!

    override func setUpWithError() throws {
        try super.setUpWithError()

        // Start from a clean slate: no stale cache, the default resolver
        // restored, and no leftover override key from a prior run or from
        // the developer's own environment (we're about to borrow .standard).
        ViduraCore.resetBinPathCacheForTesting()
        UserDefaults.standard.removeObject(forKey: Preferences.customBinPathKey)

        // A per-test unique directory containing one executable named exactly
        // like the tool we resolve. `isExecutableFile(atPath:)` — which the
        // priority-0 branch gates on — requires the file to actually exist and
        // carry an executable bit, so we write real content and chmod 0755.
        tempDir = FileManager.default.temporaryDirectory
            .appendingPathComponent("vidura-core-binpath-tests-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: tempDir, withIntermediateDirectories: true)

        let toolURL = tempDir.appendingPathComponent("vidura-state")
        try "#!/bin/sh\nexit 0\n".write(to: toolURL, atomically: true, encoding: .utf8)
        try FileManager.default.setAttributes(
            [.posixPermissions: 0o755],
            ofItemAtPath: toolURL.path
        )
    }

    override func tearDownWithError() throws {
        // Restore every borrowed global before the next test / suite runs:
        // drop the injected resolver and cache, remove the override key from
        // the real .standard domain, and delete the temp tree.
        ViduraCore.resetBinPathCacheForTesting()
        UserDefaults.standard.removeObject(forKey: Preferences.customBinPathKey)
        if let tempDir {
            try? FileManager.default.removeItem(at: tempDir)
        }
        tempDir = nil
        try super.tearDownWithError()
    }

    /// Priority 0 wins: with the override pointing at a directory that holds
    /// an executable `vidura-state`, `binPath` must return the path *inside*
    /// that directory even though the PATH resolver is available — here it's
    /// stubbed to `nil`, so if priority 0 didn't fire the whole lookup would
    /// miss and return `nil`, making the assertion unambiguous.
    func test_binPath_customBinPathOverride_takesPriorityZero() {
        UserDefaults.standard.set(tempDir.path, forKey: Preferences.customBinPathKey)

        // resetBinPathCacheForTesting also restores the default (real)
        // resolver, so inject the nil stub *after* it: no PATH hit can mask or
        // mimic the priority-0 result.
        ViduraCore.resetBinPathCacheForTesting()
        ViduraCore.whichResolver = { _ in nil }

        let expected = tempDir.appendingPathComponent("vidura-state").path
        let resolved = ViduraCore.binPath("vidura-state")

        XCTAssertEqual(
            resolved,
            expected,
            "custom bin-path override (priority 0) should resolve the tool inside the user-chosen directory, ahead of PATH"
        )
    }

    /// Cache invalidation: once the user clears the setting, dropping the
    /// cache via `invalidateBinPathCache()` must stop `binPath` from returning
    /// the (now removed) custom directory. Without the invalidation the first
    /// resolution would stay cached per tool name and the stale path would be
    /// served indefinitely — the exact bug the Settings change handler avoids.
    func test_binPath_invalidateCache_dropsCustomPathAfterClear() {
        UserDefaults.standard.set(tempDir.path, forKey: Preferences.customBinPathKey)
        ViduraCore.resetBinPathCacheForTesting()
        ViduraCore.whichResolver = { _ in nil }

        let customPath = tempDir.appendingPathComponent("vidura-state").path

        // First resolution takes and caches the priority-0 hit.
        XCTAssertEqual(
            ViduraCore.binPath("vidura-state"),
            customPath,
            "precondition: the override should resolve while the key is set"
        )

        // User clears the field: the key is removed, then the change handler
        // invalidates the cache. With the resolver still stubbed to nil and no
        // override in place, resolution must no longer point at the temp dir.
        UserDefaults.standard.removeObject(forKey: Preferences.customBinPathKey)
        ViduraCore.invalidateBinPathCache()

        XCTAssertNotEqual(
            ViduraCore.binPath("vidura-state"),
            customPath,
            "after clearing the override and invalidating the cache, resolution must not keep returning the stale custom path"
        )
    }
}
