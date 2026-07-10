import AppKit
import ViduraPetKit

/// Entry point only — all real logic (AppDelegate, panel geometry, state,
/// views, decoding) lives in ViduraPetKit so it can be unit-tested. This
/// executable target exists purely because SwiftPM cannot `import` an
/// executable target from a test target.
@MainActor
enum ViduraPetMain {
    static func run() {
        let delegate = AppDelegate()
        let app = NSApplication.shared
        app.delegate = delegate
        withExtendedLifetime(delegate) {
            app.run()
        }
    }
}

MainActor.assumeIsolated {
    ViduraPetMain.run()
}
