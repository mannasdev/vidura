import Foundation

/// Pure decision logic for the ONE notification the whole app ever
/// sends: firing exactly when the mood transitions INTO STIRRING from
/// something else (or from no prior mood at all). Staying in STIRRING,
/// or moving between any two non-STIRRING moods, never notifies.
public enum MoodTransition {
    /// - Parameters:
    ///   - previous: The raw mood string before this update, or `nil` if
    ///     no mood has been observed yet.
    ///   - current: The raw mood string just decoded.
    /// - Returns: `true` only when `current` is STIRRING and `previous`
    ///   was not STIRRING (including `previous == nil`).
    public static func shouldNotify(previous: String?, current: String) -> Bool {
        let wasStirring = previous == Mood.stirring.rawValue
        let isStirring = current == Mood.stirring.rawValue
        return isStirring && !wasStirring
    }
}
