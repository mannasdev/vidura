import Foundation

/// Thin shell-out layer to the Python core. Swift never touches the
/// store, the fix index, or the executor directly — every read and
/// every mutation goes through one of vidura-state / vidura-ledger /
/// vidura-do, exactly like a human at a terminal. This is the ONLY
/// file that knows how those binaries are found and invoked.
enum ViduraCore {

    /// One CLI invocation's outcome: exit code plus captured stdout/stderr.
    struct Result {
        let exitCode: Int32
        let stdout: String
        let stderr: String
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
    static func binPath(_ tool: String) -> String? {
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

    /// Ask `/usr/bin/env <tool>` to resolve `tool` against PATH, without
    /// actually running it (env -v style probe would run it, so instead
    /// we use `command -v` semantics via /usr/bin/which, which is always
    /// present on macOS and never executes the target).
    private static func resolveViaEnv(_ tool: String) -> String? {
        let which = Process()
        which.executableURL = URL(fileURLWithPath: "/usr/bin/which")
        which.arguments = [tool]
        let pipe = Pipe()
        which.standardOutput = pipe
        which.standardError = Pipe()
        do {
            try which.run()
            which.waitUntilExit()
            guard which.terminationStatus == 0 else { return nil }
            let data = pipe.fileHandleForReading.readDataToEndOfFile()
            let path = String(data: data, encoding: .utf8)?
                .trimmingCharacters(in: .whitespacesAndNewlines)
            guard let path, !path.isEmpty, FileManager.default.isExecutableFile(atPath: path) else {
                return nil
            }
            return path
        } catch {
            return nil
        }
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

        try process.run()

        let deadline = Date().addingTimeInterval(timeout)
        while process.isRunning && Date() < deadline {
            Thread.sleep(forTimeInterval: 0.05)
        }
        if process.isRunning {
            process.terminate()
            throw CoreError.timedOut(tool)
        }

        let stdoutData = stdoutPipe.fileHandleForReading.readDataToEndOfFile()
        let stderrData = stderrPipe.fileHandleForReading.readDataToEndOfFile()
        return Result(
            exitCode: process.terminationStatus,
            stdout: String(data: stdoutData, encoding: .utf8) ?? "",
            stderr: String(data: stderrData, encoding: .utf8) ?? ""
        )
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
