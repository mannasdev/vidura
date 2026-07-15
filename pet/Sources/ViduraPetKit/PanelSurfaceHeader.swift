import SwiftUI

/// The shared top bar for the two secondary panel surfaces (`PetsView`,
/// `SettingsView`): a `‹ Back` control that returns to `.home` plus the
/// surface title, over the same 1pt rule the home footer uses. Extracted so
/// both surfaces navigate home identically (spec §7: "each show a back
/// control that sets `state.route = .home`") without duplicating the chrome.
///
/// The back action is injected rather than reaching into `StateModel` here,
/// so this stays a dumb presentational bar — the caller owns the route write.
struct PanelSurfaceHeader: View {
    let title: String
    let onBack: () -> Void

    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 8) {
                Button(action: onBack) {
                    HStack(spacing: 3) {
                        Image(systemName: "chevron.left")
                            .font(.system(size: 11, weight: .semibold))
                        Text("Back")
                            .font(Theme.footerFont)
                    }
                    .foregroundStyle(Theme.textSecondary)
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)

                Spacer()

                Text(title)
                    .font(Theme.moodFont)
                    .tracking(Theme.moodTracking)
                    .foregroundStyle(Theme.textTertiary)

                Spacer()

                // Balances the leading Back control's width so the title sits
                // visually centered rather than shoved by the asymmetric row.
                HStack(spacing: 3) {
                    Image(systemName: "chevron.left")
                        .font(.system(size: 11, weight: .semibold))
                    Text("Back")
                        .font(Theme.footerFont)
                }
                .opacity(0)
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 12)

            Rectangle()
                .fill(Theme.border)
                .frame(height: 1)
        }
    }
}
