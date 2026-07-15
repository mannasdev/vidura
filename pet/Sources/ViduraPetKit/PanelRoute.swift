import Foundation

/// Which of the three in-panel surfaces the single `NSPanel` is currently
/// showing. There are no separate windows or sheets: the footer buttons
/// swap the panel's *content* and the panel re-fits itself around it, so
/// navigation is just a value on `StateModel` rather than a presentation.
///
/// Lifecycle of this value, and why it lives where it does:
/// - `StateModel` holds it as `@Published var route: PanelRoute` — the one
///   object both `AppDelegate` and `CardView` already share, and already the
///   home of view-coordination state (`panelOpenCount`, `shouldCelebrateOnOpen`).
/// - The footer `Pets` / `Settings` buttons set it to `.pets` / `.settings`;
///   the back control on each of those surfaces sets it back to `.home`.
/// - `AppDelegate` folds `state.$route` into its existing content-refit
///   observation (alongside `$entries` / `$mood`), so switching surfaces
///   re-measures the content-hugging panel's `fittingSize` and re-anchors it.
/// - `hidePanel()` resets it to `.home`, so reopening the pet always lands on
///   the hero card rather than wherever the last visit left off.
public enum PanelRoute: Equatable {
    case home
    case pets
    case settings
}
