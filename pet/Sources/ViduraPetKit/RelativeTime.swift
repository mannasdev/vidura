import Foundation

/// Pure formatting for the footer's "Last counsel · {relative time}"
/// line (spec §2.3). The Python core has no dedicated "last counsel"
/// field — every ledger entry already carries `updated_at`, so the most
/// recently updated entry across the *entire* ledger (any status) is
/// the most recent moment Vidura said something, and that timestamp is
/// what gets relativized here. Kept as static pure functions (no Date()
/// captured internally beyond an injectable `now`) so it's directly
/// unit-testable without waiting on the wall clock.
public enum RelativeTime {
    private static let isoFormatter: ISO8601DateFormatter = {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return formatter
    }()
    private static let isoFormatterNoFraction: ISO8601DateFormatter = {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime]
        return formatter
    }()

    /// Parses an ISO-8601 `updated_at` string as written by the Python
    /// core (`vidura/store.py`), tolerating both fractional- and
    /// whole-second forms.
    public static func parseISO8601(_ string: String) -> Date? {
        isoFormatter.date(from: string) ?? isoFormatterNoFraction.date(from: string)
    }

    /// The most recent `updated_at` across all entries, or `nil` if the
    /// ledger is empty or no timestamp parses.
    public static func mostRecentUpdate(_ entries: [LedgerEntry]) -> Date? {
        entries.compactMap { parseISO8601($0.updatedAt) }.max()
    }

    /// Coarse, human relative phrasing matching the mock's "6 days ago"
    /// register — day-granularity for anything a day or older, falling
    /// back to hour/minute phrasing for same-day updates rather than
    /// ever showing "0 days ago".
    public static func phrase(from date: Date, to now: Date = Date()) -> String {
        let seconds = max(0, now.timeIntervalSince(date))
        let minutes = Int(seconds / 60)
        let hours = Int(seconds / 3600)
        let days = Int(seconds / 86400)

        if days >= 1 {
            return days == 1 ? "1 day ago" : "\(days) days ago"
        }
        if hours >= 1 {
            return hours == 1 ? "1 hour ago" : "\(hours) hours ago"
        }
        if minutes >= 1 {
            return minutes == 1 ? "1 minute ago" : "\(minutes) minutes ago"
        }
        return "just now"
    }

    /// The full footer string, e.g. "Last counsel · 6 days ago", or a
    /// quiet fallback when there is no ledger history at all yet.
    public static func lastCounselLine(entries: [LedgerEntry], now: Date = Date()) -> String {
        guard let mostRecent = mostRecentUpdate(entries) else {
            return "Last counsel · none yet"
        }
        return "Last counsel · \(phrase(from: mostRecent, to: now))"
    }
}
