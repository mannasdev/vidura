import Foundation

/// Pure formatting for the header's click-to-reveal caption: the
/// `character_reason` sentence the Python side already wrote (e.g. "The
/// Founder — 41 sessions and 52 hours in 14 days"), plus a relative-time
/// "since <date>" suffix built from `character_since`. Extracted as a
/// pure function (mirrors `RelativeTime`'s own style) so the caption text
/// is unit-testable without any view/state plumbing.
public enum CharacterCaption {
    /// Builds the full caption line, e.g.
    /// "The Founder — 41 sessions and 52 hours in 14 days · since 12 days ago".
    ///
    /// - `reason` and `since` are the raw `character_reason` /
    ///   `character_since` fields off `MoodState`, both optional because
    ///   an old CLI (pre character-system) omits them — this must
    ///   degrade gracefully rather than crash or show "nil".
    /// - When `reason` is missing entirely, falls back to a generic
    ///   sentence for the default "temple-cat" look so the caption is
    ///   never blank.
    /// - When `since` is missing or unparseable, the "since …" suffix is
    ///   simply omitted rather than showing a bogus date.
    public static func line(reason: String?, since: String?, now: Date = Date()) -> String {
        let baseReason = reason?.isEmpty == false ? reason! : "Balanced practice — still learning your rhythm."
        guard let since,
              let sinceDate = RelativeTime.parseISO8601(since) else {
            return baseReason
        }
        return "\(baseReason) · since \(RelativeTime.phrase(from: sinceDate, to: now))"
    }
}
