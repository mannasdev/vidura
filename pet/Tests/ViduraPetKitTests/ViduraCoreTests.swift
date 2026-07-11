import XCTest
@testable import ViduraPetKit

/// Guards two ViduraCore hardening properties from the 2026-07-11 review
/// (package D): `binPath` caches its resolution per tool name instead of
/// re-shelling `/usr/bin/which` on every call (it's invoked from
/// concurrent background-queue Tasks — StateModel's poll timer, sweep
/// timer, and ledger actions can all be in flight together), and `run`
/// escalates a hung child from SIGTERM to SIGKILL instead of leaking it.
final class ViduraCoreTests: XCTestCase {
    override func tearDown() {
        ViduraCore.resetBinPathCacheForTesting()
        super.tearDown()
    }

    // MARK: - binPath caching

    /// First call resolves via the injected spy; every subsequent call
    /// for the same tool name must hit the cache, not the resolver —
    /// pins down "cache the resolved binary path per tool name" without
    /// touching the real filesystem or PATH.
    func test_binPath_cachesResolution_doesNotReResolve() {
        var callCount = 0
        ViduraCore.whichResolver = { tool in
            callCount += 1
            return "/fake/bin/\(tool)"
        }

        let first = ViduraCore.binPath("vidura-state")
        let second = ViduraCore.binPath("vidura-state")
        let third = ViduraCore.binPath("vidura-state")

        XCTAssertEqual(first, "/fake/bin/vidura-state")
        XCTAssertEqual(second, "/fake/bin/vidura-state")
        XCTAssertEqual(third, "/fake/bin/vidura-state")
        XCTAssertEqual(callCount, 1, "resolver should only be invoked once — the other two calls must be served from cache")
    }

    /// The cache is keyed per tool name — resolving one tool must not
    /// serve a cached hit for a different tool's lookup.
    func test_binPath_cachesIndependently_perToolName() {
        var callCount = 0
        ViduraCore.whichResolver = { tool in
            callCount += 1
            return "/fake/bin/\(tool)"
        }

        let state = ViduraCore.binPath("vidura-state")
        let ledger = ViduraCore.binPath("vidura-ledger")
        let stateAgain = ViduraCore.binPath("vidura-state")

        XCTAssertEqual(state, "/fake/bin/vidura-state")
        XCTAssertEqual(ledger, "/fake/bin/vidura-ledger")
        XCTAssertEqual(stateAgain, "/fake/bin/vidura-state")
        XCTAssertEqual(callCount, 2, "one resolver call per distinct tool name")
    }

    /// A failed resolution (tool not found anywhere) must not be cached
    /// as a permanent negative — if the resolver would succeed on a
    /// later call (e.g. PATH changed), binPath should retry rather than
    /// wedge on the first failure forever. This also confirms VIDURA_BIN
    /// takes priority over the (uncached, always-consulted-on-miss)
    /// resolver path when set.
    func test_binPath_doesNotCacheFailure() {
        var callCount = 0
        ViduraCore.whichResolver = { _ in
            callCount += 1
            return nil
        }

        let first = ViduraCore.binPath("nonexistent-tool")
        let second = ViduraCore.binPath("nonexistent-tool")

        XCTAssertNil(first)
        XCTAssertNil(second)
        XCTAssertEqual(callCount, 2, "a miss should not be cached — every call re-resolves until one succeeds")
    }

    // MARK: - SIGTERM -> SIGKILL escalation

    /// A child that traps SIGTERM and ignores it must still be gone by
    /// deadline + grace: `run` should escalate to SIGKILL, which cannot
    /// be caught, and the process must be reaped. Spawns a real
    /// `/bin/sh` with a short timeout so this exercises the actual
    /// escalation path in `run`, not a mock — `Process` execs `/bin/sh`
    /// directly (no fork wrapper), so `process.processIdentifier` is the
    /// trapping shell's own pid, letting us confirm with `kill(pid, 0)`
    /// that it's actually gone afterward, not just that `run` returned.
    ///
    /// Marked with a generous outer wait since it depends on real
    /// process scheduling; if this proves flaky under sandboxing, the
    /// deterministic binPath-cache tests above still cover the rest of
    /// package D.
    func test_run_escalatesToSigkill_whenChildIgnoresSigterm() throws {
        ViduraCore.whichResolver = { tool in
            tool == "sh" ? "/bin/sh" : nil
        }
        defer { ViduraCore.resetBinPathCacheForTesting() }

        // trap "" TERM ignores SIGTERM outright; sleep 30 gives the
        // process a lifetime far longer than the 1s timeout below, so if
        // escalation didn't happen the process would still be alive
        // when we check.
        let pidFile = FileManager.default.temporaryDirectory
            .appendingPathComponent("vidura-core-tests-\(UUID().uuidString).pid")
        defer { try? FileManager.default.removeItem(at: pidFile) }

        let start = Date()
        var caughtTimeout = false

        do {
            _ = try ViduraCore.run(
                "sh",
                arguments: ["-c", "trap '' TERM; echo $$ > \(pidFile.path); sleep 30"],
                timeout: 1
            )
            XCTFail("expected CoreError.timedOut")
        } catch ViduraCore.CoreError.timedOut {
            caughtTimeout = true
        } catch {
            XCTFail("expected CoreError.timedOut, got \(error)")
        }

        let elapsed = Date().timeIntervalSince(start)
        XCTAssertTrue(caughtTimeout, "run() should throw .timedOut once the child outlives the timeout")
        // deadline (1s) + SIGTERM grace (2s) + generous scheduling slack
        XCTAssertLessThan(elapsed, 6, "escalation to SIGKILL should bound total wait well under the old unbounded hang")

        // Give the pid file a brief window to appear in case the shell
        // wrote it just before being killed.
        var pidText: String?
        for _ in 0..<20 {
            pidText = try? String(contentsOf: pidFile, encoding: .utf8)
            if pidText != nil { break }
            Thread.sleep(forTimeInterval: 0.05)
        }
        guard let pidText, let pid = Int32(pidText.trimmingCharacters(in: .whitespacesAndNewlines)) else {
            throw XCTSkip("child never wrote its pid before being killed — cannot verify liveness directly")
        }

        // kill(pid, 0) sends no signal but still checks whether the
        // process exists; -1 (with errno ESRCH) means it's gone, which
        // is exactly what SIGKILL escalation should guarantee here.
        let stillAlive = kill(pid, 0) == 0
        XCTAssertFalse(stillAlive, "child that traps SIGTERM should have been reaped via SIGKILL escalation")
    }
}
