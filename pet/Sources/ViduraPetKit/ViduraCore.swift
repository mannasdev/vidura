import Foundation

/// Thin shell-out layer to the Python core. Swift never touches the
/// store, the fix index, or the executor directly — every read and
/// every mutation goes through one of vidura-state / vidura-ledger /
/// vidura-do, exactly like a human at a terminal. This is the ONLY
/// file that knows how those binaries are found and invoked.
public enum ViduraCore {

    /// One CLI invocation's outcome: exit code plus captured stdout/stderr.
    public struct Result {
        public let exitCode: Int32
        public let stdout: String
        public let stderr: String
    }

    enum CoreError: Error {
        case binaryNotFound(String)
        case timedOut(String)
    }

    /// Process.run never blocks the caller's thread for longer than this —
    /// routine CLI calls (state/list/accept/dismiss/celebrate) are fast
    /// local SQLite reads/writes.
    static let defaultTimeout: TimeInterval = 30
    /// vidura-sweep walks session logs on disk; give it real headroom.
    static let sweepTimeout: TimeInterval = 30 * 60

    /// Resolve an executable path for `tool` (e.g. "vidura-state") in
    /// priority order:
    ///   1. $VIDURA_BIN/<tool>            — explicit override
    ///   2. `/usr/bin/env <tool>` via PATH — normal installed CLI
    ///   3. ~/Desktop/Projects/vidura/.venv/bin/<tool> — dev fallback
    ///
    /// Cached per tool name after the first successful resolution: `run`
    /// calls this from concurrent background-queue Tasks (StateModel's
    /// poll timer, sweep timer, and user-triggered ledger actions can all
    /// be in flight together), and re-shelling `/usr/bin/which` on every
    /// single CLI call is wasted work for a path that essentially never
    /// changes mid-session. Guarded by `cacheLock`, not @MainActor,
    /// because callers run on arbitrary utility-QoS queues.
    static func binPath(_ tool: String) -> String? {
        cacheLock.lock()
        if let cached = resolvedPaths[tool] {
            cacheLock.unlock()
            return cached
        }
        cacheLock.unlock()

        guard let resolved = resolveBinPath(tool) else { return nil }

        cacheLock.lock()
        resolvedPaths[tool] = resolved
        cacheLock.unlock()
        return resolved
    }

    /// Serializes access to `resolvedPaths`. A plain NSLock is enough —
    /// resolution itself (a few filesystem checks plus, at worst, one
    /// `/usr/bin/which` shell-out) is short, and callers never hold the
    /// lock while doing that work.
    private static let cacheLock = NSLock()
    private static var resolvedPaths: [String: String] = [:]

    /// Test-only: drop the cache and remove any injected resolver so
    /// each test starts from a clean slate.
    static func resetBinPathCacheForTesting() {
        cacheLock.lock()
        resolvedPaths.removeAll()
        cacheLock.unlock()
        whichResolver = defaultWhichResolver
    }

    /// The actual (uncached) resolution logic, factored out of `binPath`
    /// so the cache wrapper above stays a thin lock+dictionary shim.
    private static func resolveBinPath(_ tool: String) -> String? {
        let fm = FileManager.default

        if let binDir = ProcessInfo.processInfo.environment["VIDURA_BIN"] {
            let candidate = (binDir as NSString).appendingPathComponent(tool)
            if fm.isExecutableFile(atPath: candidate) {
                return candidate
            }
        }

        if let onPath = resolveViaEnv(tool) {
            return onPath
        }

        let devFallback = NSString(string: "~/Desktop/Projects/vidura/.venv/bin/\(tool)")
            .expandingTildeInPath
        if fm.isExecutableFile(atPath: devFallback) {
            return devFallback
        }

        return nil
    }

    /// Injectable seam for tests: the default implementation shells out
    /// to `/usr/bin/which`; tests can swap in a spy to count invocations
    /// or simulate a hang without touching the real filesystem/PATH.
    static var whichResolver: (String) -> String? = defaultWhichResolver

    /// Resolve `tool` against PATH without actually running it, using
    /// /usr/bin/which — which is always present on macOS, performs a
    /// pure PATH lookup, and never executes the target.
    private static func resolveViaEnv(_ tool: String) -> String? {
        whichResolver(tool)
    }

    /// Default `whichResolver`: shells out to `/usr/bin/which` with the
    /// same bounded deadline-poll pattern `run(_:arguments:timeout:)`
    /// uses, so a hung or misbehaving `which` can never block `binPath`
    /// (and therefore every CLI call) forever. Short deadline — this is
    /// a pure PATH lookup, not real work.
    private static let defaultWhichResolver: (String) -> String? = { tool in
        let which = Process()
        which.executableURL = URL(fileURLWithPath: "/usr/bin/which")
        which.arguments = [tool]
        let pipe = Pipe()
        which.standardOutput = pipe
        which.standardError = Pipe()
        do {
            try which.run()
        } catch {
            return nil
        }

        let deadline = Date().addingTimeInterval(5)
        while which.isRunning && Date() < deadline {
            Thread.sleep(forTimeInterval: 0.05)
        }
        if which.isRunning {
            which.terminate()
            return nil
        }

        guard which.terminationStatus == 0 else { return nil }
        let data = pipe.fileHandleForReading.readDataToEndOfFile()
        let path = String(data: data, encoding: .utf8)?
            .trimmingCharacters(in: .whitespacesAndNewlines)
        guard let path, !path.isEmpty, FileManager.default.isExecutableFile(atPath: path) else {
            return nil
        }
        return path
    }

    /// Run `tool` with `arguments`, off the calling thread. Never call
    /// this from the main thread and block on it synchronously — callers
    /// use the async variant or dispatch to a background queue themselves.
    static func run(
        _ tool: String,
        arguments: [String] = [],
        timeout: TimeInterval = defaultTimeout
    ) throws -> Result {
        guard let path = binPath(tool) else {
            throw CoreError.binaryNotFound(tool)
        }

        let process = Process()
        process.executableURL = URL(fileURLWithPath: path)
        process.arguments = arguments

        let stdoutPipe = Pipe()
        let stderrPipe = Pipe()
        process.standardOutput = stdoutPipe
        process.standardError = stderrPipe

        // Drain both pipes concurrently with the process's lifetime via
        // readabilityHandler. Pipes have a small fixed kernel buffer
        // (~64KB); a chatty child that fills stdout or stderr before we
        // ever call readDataToEndOfFile() would block forever on write()
        // while we block on waiting for it to exit — a classic pipe
        // deadlock. Accumulating incrementally as data arrives avoids
        // that regardless of output volume or timing.
        let stdoutBox = OutputBox()
        let stderrBox = OutputBox()

        stdoutPipe.fileHandleForReading.readabilityHandler = { handle in
            let chunk = handle.availableData
            if !chunk.isEmpty { stdoutBox.append(chunk) }
        }
        stderrPipe.fileHandleForReading.readabilityHandler = { handle in
            let chunk = handle.availableData
            if !chunk.isEmpty { stderrBox.append(chunk) }
        }

        try process.run()

        let deadline = Date().addingTimeInterval(timeout)
        while process.isRunning && Date() < deadline {
            Thread.sleep(forTimeInterval: 0.05)
        }
        if process.isRunning {
            // SIGTERM first, but a child that traps or ignores it (or is
            // itself stuck past signal delivery, e.g. blocked in a
            // syscall) would otherwise leak as a hung, unreachable
            // process forever. Give it a short grace period to exit
            // cleanly, then escalate to SIGKILL, which cannot be
            // caught or ignored, and reap so it doesn't linger as a
            // zombie.
            process.terminate()
            let killDeadline = Date().addingTimeInterval(2)
            while process.isRunning && Date() < killDeadline {
                Thread.sleep(forTimeInterval: 0.05)
            }
            if process.isRunning {
                kill(process.processIdentifier, SIGKILL)
                process.waitUntilExit()
            }
            stdoutPipe.fileHandleForReading.readabilityHandler = nil
            stderrPipe.fileHandleForReading.readabilityHandler = nil
            throw CoreError.timedOut(tool)
        }

        // Process has exited, but bytes already in the pipe buffer may
        // not have been delivered to the readabilityHandler yet. Clear
        // the handler and do one last synchronous drain to catch any
        // remainder before reading the accumulated buffers.
        stdoutPipe.fileHandleForReading.readabilityHandler = nil
        stderrPipe.fileHandleForReading.readabilityHandler = nil
        let stdoutRemainder = stdoutPipe.fileHandleForReading.readDataToEndOfFile()
        let stderrRemainder = stderrPipe.fileHandleForReading.readDataToEndOfFile()
        if !stdoutRemainder.isEmpty { stdoutBox.append(stdoutRemainder) }
        if !stderrRemainder.isEmpty { stderrBox.append(stderrRemainder) }

        return Result(
            exitCode: process.terminationStatus,
            stdout: String(data: stdoutBox.data, encoding: .utf8) ?? "",
            stderr: String(data: stderrBox.data, encoding: .utf8) ?? ""
        )
    }

    /// Thread-safe accumulator for pipe output collected off the
    /// readabilityHandler's dispatch queue while `run` polls for exit
    /// on its own thread.
    private final class OutputBox: @unchecked Sendable {
        private var buffer = Data()
        private let lock = NSLock()

        func append(_ chunk: Data) {
            lock.lock()
            buffer.append(chunk)
            lock.unlock()
        }

        var data: Data {
            lock.lock()
            defer { lock.unlock() }
            return buffer
        }
    }

    /// Async convenience: runs `run(_:arguments:timeout:)` on a background
    /// utility queue so callers on the main actor never block. This is the
    /// entrypoint everything in StateModel/CardView should use.
    static func runAsync(
        _ tool: String,
        arguments: [String] = [],
        timeout: TimeInterval = defaultTimeout,
        qos: DispatchQoS.QoSClass = .utility
    ) async throws -> Result {
        try await withCheckedThrowingContinuation { continuation in
            DispatchQueue.global(qos: qos).async {
                do {
                    let result = try run(tool, arguments: arguments, timeout: timeout)
                    continuation.resume(returning: result)
                } catch {
                    continuation.resume(throwing: error)
                }
            }
        }
    }
}
