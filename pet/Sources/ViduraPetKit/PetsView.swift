import SwiftUI
#if canImport(AppKit)
import AppKit
#endif

/// The Pets picker surface (`PanelRoute.pets`) — the list the two dead
/// footer buttons now open (spec §4, §7). Draws the `PetCatalog.pickable`
/// rows (Auto first, then the five pinnable species) as a scrollable list,
/// each row a thumbnail + name + "what you get" description + a selected
/// check, and writes the chosen id straight to `Preferences.selectedPet`.
///
/// This surface only ever changes which *sprite* the hero draws: it mutates
/// `prefs.selectedPet`, which `CardView.currentCharacter` feeds through
/// `PetResolution.resolve`. It never touches mood, the badge, the STIRRING
/// notification, or the suggestion cards — those stay entirely core-driven
/// (see `PetResolution` for the invariant). Picking a row does not leave the
/// panel; the shared back control returns to `.home`.
///
/// Inner content only: the outer panel chrome (fixed 400pt width, bg-panel,
/// corner radius, border) lives on `CardView.body`'s `Group` and wraps every
/// route (see `CardView.body`).
struct PetsView: View {
    @ObservedObject var state: StateModel
    @ObservedObject var prefs: Preferences

    /// The Auto row renders whatever is *currently* earned, so it needs the
    /// live core diagnosis to draw its thumbnail — the same `effectiveCharacter`
    /// the hero would use, defaulted to `temple-cat` when a pre-character-system
    /// core omits it (see `MoodState.effectiveCharacter`).
    private var earnedCharacter: String {
        state.mood?.effectiveCharacter ?? CharacterAsset.defaultCharacter
    }

    /// The mood whose frame the thumbnails render. Every row shows the same
    /// mood (the live one) so the picker reads as "here's each species right
    /// now", not a grid of mismatched poses.
    private var thumbnailMood: PetMood {
        PetMood(rawMood: state.mood?.mood ?? Mood.asleep.rawValue)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            PanelSurfaceHeader(title: "Pets") { state.route = .home }

            // The list can be tall (Auto + five species with thumbnails), so
            // it scrolls inside a cap below AppDelegate's content-hugging
            // `panelMaxHeight` clamp — mirroring the suggestions ScrollView
            // pattern in CardView (spec §7).
            ScrollView {
                VStack(alignment: .leading, spacing: 8) {
                    ForEach(PetCatalog.pickable) { info in
                        PetRow(
                            info: info,
                            isSelected: prefs.selectedPet == info.id,
                            thumbnailCharacter: info.isAuto ? earnedCharacter : info.id,
                            thumbnailMood: thumbnailMood
                        ) {
                            prefs.selectedPet = info.id
                        }
                    }
                }
                .padding(.horizontal, 16)
                .padding(.bottom, 16)
            }
            .frame(maxHeight: 460)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

/// One picker row: thumbnail sprite, name + tagline + description, and a
/// trailing check when it is the current selection. The whole row is a plain
/// button (house style — `.plain` buttons, no default chrome) so tapping
/// anywhere pins the pet.
private struct PetRow: View {
    let info: PetInfo
    let isSelected: Bool
    let thumbnailCharacter: String
    let thumbnailMood: PetMood
    let onSelect: () -> Void

    var body: some View {
        Button(action: onSelect) {
            HStack(alignment: .top, spacing: 12) {
                thumbnail
                VStack(alignment: .leading, spacing: 3) {
                    HStack(spacing: 6) {
                        Text(info.displayName)
                            .font(Theme.summaryFont)
                            .foregroundStyle(Theme.textPrimary)
                        Text(info.tagline)
                            .font(Theme.metaFont)
                            .foregroundStyle(Theme.textTertiary)
                            .lineLimit(1)
                    }
                    Text(info.description)
                        .font(Theme.footerFont)
                        .foregroundStyle(Theme.textSecondary)
                        .fixedSize(horizontal: false, vertical: true)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
                Spacer(minLength: 0)
                Image(systemName: "checkmark")
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundStyle(Theme.accent)
                    .opacity(isSelected ? 1 : 0)
                    .padding(.top, 2)
            }
            .padding(12)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(isSelected ? Theme.accentSubtle : Theme.bgCard)
            .clipShape(RoundedRectangle(cornerRadius: Theme.cardRadius, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: Theme.cardRadius, style: .continuous)
                    .strokeBorder(isSelected ? Theme.accent : Theme.border, lineWidth: 1)
            )
        }
        .buttonStyle(.plain)
        .contentShape(Rectangle())
    }

    /// A small, static sprite (no animation — this is a chooser, not the
    /// hero) drawn straight from `CharacterAsset` with its own three-step
    /// art fallback, so an id lacking a rendered frame degrades gracefully
    /// rather than blanking.
    private var thumbnail: some View {
        Group {
            if let nsImage = CharacterAsset.characterImage(character: thumbnailCharacter, mood: thumbnailMood) {
                Image(nsImage: nsImage)
                    .resizable()
                    .interpolation(.none)
                    .aspectRatio(contentMode: .fit)
            } else {
                Image(systemName: "cat")
                    .resizable()
                    .aspectRatio(contentMode: .fit)
                    .foregroundStyle(Theme.textTertiary)
                    .padding(8)
            }
        }
        .frame(width: 44, height: 44)
    }
}
