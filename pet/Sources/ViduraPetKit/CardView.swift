import SwiftUI
#if canImport(AppKit)
import AppKit
#endif

/// The popover's content, restyled per `design-export/UI-SPEC.md`
/// (Pencil doc `616fb6b5-a712-4cbc-af00-a3b9e6d04246`). Structure and
/// tokens follow the spec exactly (§2); this remains a pure reskin —
/// same StateModel, same Accept/Dismiss/Do/confirm flow, same
/// content-hugging sizing contract AppDelegate depends on. Panel-internal
/// animation (breathing, micro-motion, mood crossfade, celebration hop)
/// lives in CharacterPortrait, gated by AnimationPolicy; the menu bar
/// itself never animates — see AppDelegate.
public struct CardView: View {
    @ObservedObject var state: StateModel

    @State private var pendingDoAction: DoSheetContext?
    @State private var showCharacterCaption = false
    private let policy = AnimationPolicy(reduceMotion: AnimationPolicy.systemReduceMotion)

    public init(state: StateModel) {
        self.state = state
    }

    /// The panel is a single window whose *content* swaps by route (spec:
    /// footer buttons navigate in-place, the panel re-fits — see
    /// `PanelRoute`). The outer chrome (fixed width, bg-panel, corner
    /// radius, border, Do-confirm sheet, refresh-on-appear) is shared by ALL
    /// routes and therefore lives on this `Group`, not inside any one
    /// surface; `PetsView` / `SettingsView` draw inner content only.
    public var body: some View {
        Group {
            switch state.route {
            case .home:
                homeContent
            case .pets:
                PetsView(state: state, prefs: state.preferences)
            case .settings:
                SettingsView(state: state, prefs: state.preferences)
            }
        }
        .frame(width: 400)
        .background(Theme.bgPanel)
        .clipShape(RoundedRectangle(cornerRadius: Theme.panelRadius, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: Theme.panelRadius, style: .continuous)
                .strokeBorder(Theme.border, lineWidth: 1)
        )
        .sheet(item: $pendingDoAction) { context in
            DoConfirmSheet(context: context, state: state)
        }
        .onAppear { state.refresh() }
    }

    /// The `.home` surface: the hero card and everything below it. Extracted
    /// out of `body` so the outer panel chrome can wrap the route switch
    /// (see `body`) while this stays the exact same content it always was.
    private var homeContent: some View {
        VStack(alignment: .leading, spacing: 0) {
            hero

            // With the core absent the pet has no mood, ledger, or errors
            // worth showing — every surface below would be empty or
            // misleading. Swap the whole content block for the setup card
            // that tells the user how to install the core; the footer chrome
            // stays so Pets/Settings/Quit and the relative-time line remain.
            if state.coreMissing {
                coreSetupCard
            } else {
                if !celebratableIds.isEmpty {
                    celebrationBanner
                }

                if state.entries.isEmpty {
                    emptyState
                } else {
                    suggestions
                }

                if let lastError = state.lastError {
                    errorLine(lastError)
                }
            }

            footerRule
            footer
        }
    }

    // MARK: - Core-missing setup card

    /// First-run / core-absent state: the CLIs the pet shells out to aren't
    /// installed, so nothing works. Rather than the tiny red "CLIs not found"
    /// error line (which reads as a fault, not an instruction), show a
    /// friendly card that names the fix and offers to copy it or re-check.
    /// Styled to match `SuggestionCard`'s chrome (bg-card, card radius, border)
    /// so it sits naturally where a suggestion normally would.
    private var coreSetupCard: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Vidura needs its brain")
                .font(Theme.summaryFont)
                .foregroundStyle(Theme.textPrimary)

            Text("Install the counsel core to wake the pet.")
                .font(Theme.footerFont)
                .foregroundStyle(Theme.textSecondary)
                .fixedSize(horizontal: false, vertical: true)

            // The install command, framed like an evidence block so it reads
            // as a literal thing to run, not prose.
            Text(Self.coreInstallCommand)
                .font(Theme.evidenceFont)
                .foregroundStyle(Theme.textSecondary)
                .textSelection(.enabled)
                .padding(.vertical, 10)
                .padding(.horizontal, 12)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(Theme.bgEvidence)
                .clipShape(RoundedRectangle(cornerRadius: Theme.evidenceRadius, style: .continuous))

            HStack(spacing: 8) {
                Button("Copy command") {
                    #if canImport(AppKit)
                    NSPasteboard.general.clearContents()
                    NSPasteboard.general.setString(Self.coreInstallCommand, forType: .string)
                    #endif
                }
                .buttonStyle(.plain)
                .font(Theme.dismissFont)
                .foregroundStyle(Theme.textSecondary)
                .padding(.vertical, 7)
                .padding(.horizontal, 12)
                .background(Theme.bgEvidence)
                .clipShape(RoundedRectangle(cornerRadius: Theme.buttonRadius, style: .continuous))

                Spacer(minLength: 0)

                // Re-check invalidates the cached bin-path resolution (so a
                // just-completed install is seen without a relaunch) and
                // refreshes — a successful poll clears `coreMissing`.
                Button("Re-check") {
                    Task {
                        ViduraCore.invalidateBinPathCache()
                        state.refresh()
                    }
                }
                .buttonStyle(.plain)
                .font(Theme.acceptFont)
                .foregroundStyle(Theme.accent)
                .padding(.vertical, 7)
                .padding(.horizontal, 12)
                .background(Theme.accentSubtle)
                .clipShape(RoundedRectangle(cornerRadius: Theme.buttonRadius, style: .continuous))
            }
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Theme.bgCard)
        .clipShape(RoundedRectangle(cornerRadius: Theme.cardRadius, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: Theme.cardRadius, style: .continuous)
                .strokeBorder(Theme.border, lineWidth: 1)
        )
        .padding(.horizontal, 16)
        .padding(.bottom, 16)
    }

    /// The exact install command shown in the card and written to the
    /// pasteboard by "Copy command" — one constant so the two can't drift.
    private static let coreInstallCommand = "pipx install vidura-cli"

    private var celebratableIds: [Int] {
        state.mood?.adoptedUncelebratedIds ?? []
    }

    private var currentMood: PetMood {
        PetMood(rawMood: state.mood?.mood ?? Mood.asleep.rawValue)
    }

    /// The character id whose sprite the hero draws. Reconciles the user's
    /// Pets-picker choice against the core's earned diagnosis via
    /// `PetResolution.resolve`: a real pin wins, `"auto"` defers to the core,
    /// and a stale/unknown pin falls back to Auto. The `earned` argument is
    /// the core's `effectiveCharacter`, defaulted to "temple-cat" (today's
    /// shipped look) when a pre-character-system core omits the field — see
    /// `MoodState.effectiveCharacter`. Pinning swaps only the costume, never
    /// the mood/behavior (see `PetResolution`).
    private var currentCharacter: String {
        PetResolution.resolve(
            selection: state.preferences.selectedPet,
            earned: state.mood?.effectiveCharacter ?? CharacterAsset.defaultCharacter
        )
    }

    private var characterCaption: String {
        CharacterCaption.line(
            reason: state.mood?.characterReason,
            since: state.mood?.characterSince
        )
    }

    /// The mood label's color per spec §7 ambiguity #1: ASLEEP/CONTENT
    /// (calm/neutral baseline moods) render muted (text-tertiary);
    /// active/urgent moods (STIRRING, CONCERNED, RECOGNITION, PROUD)
    /// render in the alert-orange accent.
    private var moodLabelColor: Color {
        switch currentMood {
        case .asleep, .content:
            return Theme.textTertiary
        case .stirring, .proud, .concerned, .recognition:
            return Theme.accent
        }
    }

    private var subtitle: String {
        state.entries.isEmpty ? "Nothing to say." : "One thing to say."
    }

    // MARK: - Hero (§2.1)

    private var hero: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(alignment: .center, spacing: 18) {
                CharacterPortrait(
                    character: currentCharacter,
                    mood: currentMood,
                    celebrateOnAppear: state.shouldCelebrateOnOpen,
                    policy: policy,
                    onTap: { showCharacterCaption.toggle() }
                )
                .id(state.panelOpenCount)
                VStack(alignment: .leading, spacing: 4) {
                    Text("Vidura")
                        .font(Theme.nameFont)
                        .foregroundStyle(Theme.textPrimary)
                    Text(currentMood.rawValue)
                        .font(Theme.moodFont)
                        .tracking(Theme.moodTracking)
                        .foregroundStyle(moodLabelColor)
                    Text(subtitle)
                        .font(Theme.subtitleFont)
                        .foregroundStyle(Theme.textSecondary)
                }
                Spacer(minLength: 0)
            }

            if showCharacterCaption {
                Text(characterCaption)
                    .font(Theme.footerFont)
                    .foregroundStyle(Theme.textTertiary)
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(.top, 8)
            }
        }
        .padding(.top, 18)
        .padding(.trailing, 20)
        .padding(.bottom, 14)
        .padding(.leading, 20)
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    // MARK: - Suggestions (§2.2)

    /// Spec shows a single card and no scroll affordance (§7 ambiguity
    /// #5), and the normal case (0-1 pending suggestions) never needs
    /// one — the panel just hugs this content like everything else.
    /// The ScrollView only starts clipping once content would exceed
    /// AppDelegate's `panelMaxHeight` safety clamp (a pathological
    /// multi-suggestion pileup), so it's a defensive fallback rather
    /// than a normal-path scroll container.
    private var suggestions: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 12) {
                ForEach(state.entries) { entry in
                    SuggestionCard(entry: entry, state: state) { context in
                        pendingDoAction = context
                    }
                }
            }
            .padding(.top, 0)
            .padding(.trailing, 16)
            .padding(.bottom, 16)
            .padding(.leading, 16)
        }
        .frame(maxHeight: 520)
    }

    @ViewBuilder
    private var celebrationBanner: some View {
        if let firstId = celebratableIds.first {
            HStack(spacing: 8) {
                Image(systemName: "star.circle")
                    .foregroundStyle(Theme.textSecondary)
                Text("Advice adopted — behavior changed.")
                    .font(Theme.metaFont)
                    .foregroundStyle(Theme.textPrimary)
                Spacer()
                Button("Nice") {
                    Task { await state.celebrate(firstId) }
                }
                .font(Theme.metaFont)
                .controlSize(.small)
            }
            .padding(.horizontal, 16)
            .padding(.bottom, 8)
        }
    }

    private func errorLine(_ message: String) -> some View {
        // Quiet by default — only the CLIs-entirely-missing case (the one
        // failure mode that means the pet cannot function at all) earns
        // an alarming color; every other error stays tertiary.
        Text(message)
            .font(Theme.footerFont)
            .foregroundStyle(message.contains("CLIs not found") ? AnyShapeStyle(.red) : AnyShapeStyle(Theme.textTertiary))
            .padding(.horizontal, 16)
            .padding(.bottom, 8)
    }

    // MARK: - Empty state (§2.4)

    private var emptyState: some View {
        VStack(spacing: 7) {
            Text("Nothing earned.")
                .font(Theme.emptyPrimaryFont)
                .foregroundStyle(Theme.textPrimary)
            Text("Silence is correct.")
                .font(Theme.emptySecondaryFont)
                .foregroundStyle(Theme.textSecondary)
        }
        .multilineTextAlignment(.center)
        .frame(maxWidth: .infinity)
        .padding(.top, 34)
        .padding(.trailing, 20)
        .padding(.bottom, 44)
        .padding(.leading, 20)
    }

    // MARK: - Footer (§2.3)

    private var footerRule: some View {
        Rectangle()
            .fill(Theme.border)
            .frame(height: 1)
    }

    private var footer: some View {
        HStack(alignment: .center) {
            Text(footerLeftText)
                .font(Theme.footerFont)
                .foregroundStyle(Theme.textTertiary)
            Spacer()
            HStack(spacing: 14) {
                Button("Pets") { state.route = .pets }
                Button("Settings") { state.route = .settings }
                Button("Quit") { NSApplication.shared.terminate(nil) }
            }
            .buttonStyle(.plain)
            .font(Theme.footerFont)
            .foregroundStyle(Theme.textTertiary)
        }
        .padding(.vertical, 10)
        .padding(.horizontal, 20)
    }

    /// "Last counsel · {relative time}" plus the accepted/dismissed
    /// counts derived from the full (unfiltered) ledger — extends the
    /// spec's single relative-time string with the counts the task
    /// brief asks the footer to carry.
    private var footerLeftText: String {
        let base = RelativeTime.lastCounselLine(entries: state.entries)
        guard state.counts.accepted > 0 || state.counts.dismissed > 0 else { return base }
        return "\(base) · \(state.counts.accepted) accepted, \(state.counts.dismissed) dismissed"
    }
}

/// Identifies which ledger entry a Do confirmation sheet is for, plus
/// the dry-run outcome already fetched for it. The sheet's ability to
/// show a live Confirm button is entirely gated on `outcome` being
/// `.success` — see DoConfirmSheet.
struct DoSheetContext: Identifiable {
    let entry: LedgerEntry
    let outcome: DryRunOutcome
    var id: Int { entry.id }
}

/// Suggestion Card (spec §2.2): meta row (tag chip + confidence/seen
/// text), summary prose, evidence block, action row (Dismiss / Do /
/// Accept in ascending visual weight).
private struct SuggestionCard: View {
    let entry: LedgerEntry
    @ObservedObject var state: StateModel
    let onDo: (DoSheetContext) -> Void

    @State private var isStartingDo = false

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            metaRow
            summary
            if !entry.evidence.isEmpty {
                evidenceBlock
            }
            actionsRow
        }
        .padding(16)
        .background(Theme.bgCard)
        .clipShape(RoundedRectangle(cornerRadius: Theme.cardRadius, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: Theme.cardRadius, style: .continuous)
                .strokeBorder(Theme.border, lineWidth: 1)
        )
    }

    private var metaRow: some View {
        HStack(alignment: .center) {
            Text(entry.fixId)
                .font(Theme.tagFont)
                .foregroundStyle(Theme.accent)
                .padding(.vertical, 3)
                .padding(.horizontal, 8)
                .background(Theme.accentSubtle)
                .clipShape(RoundedRectangle(cornerRadius: Theme.tagRadius, style: .continuous))
            Spacer()
            Text(metaText)
                .font(Theme.metaFont)
                .foregroundStyle(Theme.textTertiary)
        }
        .frame(maxWidth: .infinity)
    }

    /// "{confidence}% · seen {n}×" — single concatenated string per
    /// spec §2.2/§7 ambiguity #6.
    private var metaText: String {
        let confidencePercent = Int((entry.confidence * 100).rounded())
        return "\(confidencePercent)% · seen \(entry.occurrences)\u{00D7}"
    }

    private var summary: some View {
        Text(entry.bluntSummary)
            .font(Theme.summaryFont)
            .foregroundStyle(Theme.textPrimary)
            // Spec's line-height 1.5 at 14.5pt ≈ 21.75pt total leading;
            // SwiftUI's lineSpacing is the *extra* gap added atop the
            // font's own single-line height, so ~4pt gets us close.
            .lineSpacing(4)
            .fixedSize(horizontal: false, vertical: true)
            .frame(maxWidth: .infinity, alignment: .leading)
    }

    private var evidenceBlock: some View {
        VStack(alignment: .leading, spacing: 7) {
            ForEach(entry.evidence.prefix(2), id: \.self) { quote in
                HStack(alignment: .center, spacing: 9) {
                    RoundedRectangle(cornerRadius: 2)
                        .fill(Theme.quoteBar)
                        .frame(width: 3, height: 14)
                    Text(truncatedQuote(quote))
                        .font(Theme.evidenceFont)
                        .foregroundStyle(Theme.textSecondary)
                        .lineLimit(1)
                        .truncationMode(.tail)
                }
            }
        }
        .padding(.vertical, 10)
        .padding(.horizontal, 12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Theme.bgEvidence)
        .clipShape(RoundedRectangle(cornerRadius: Theme.evidenceRadius, style: .continuous))
    }

    private var actionsRow: some View {
        HStack(alignment: .center, spacing: 8) {
            Button("Dismiss") { Task { await state.dismiss(entry.id) } }
                .buttonStyle(.plain)
                .font(Theme.dismissFont)
                .foregroundStyle(Theme.textSecondary)
                .padding(.vertical, 7)
                .padding(.horizontal, 10)

            Spacer(minLength: 0)

            if entry.hasAction {
                Button {
                    startDo()
                } label: {
                    Text("Do \u{2014} \(entry.actionLabel ?? "Run")")
                        .font(Theme.doButtonFont)
                        .foregroundStyle(Theme.accent)
                        .lineLimit(1)
                        .truncationMode(.tail)
                }
                .buttonStyle(.plain)
                .padding(.vertical, 7)
                .padding(.horizontal, 12)
                .background(Theme.accentSubtle)
                .clipShape(RoundedRectangle(cornerRadius: Theme.buttonRadius, style: .continuous))
                .disabled(isStartingDo)
            }

            Button {
                Task { await state.accept(entry.id) }
            } label: {
                Text("Accept")
                    .font(Theme.acceptFont)
                    .foregroundStyle(Theme.acceptLabel)
            }
            .buttonStyle(.plain)
            .padding(.vertical, 7)
            .padding(.horizontal, 14)
            .background(Theme.acceptFill)
            .clipShape(RoundedRectangle(cornerRadius: Theme.buttonRadius, style: .continuous))
        }
        .frame(maxWidth: .infinity)
    }

    private func truncatedQuote(_ quote: String) -> String {
        let limit = 140
        guard quote.count > limit else { return quote }
        return String(quote.prefix(limit)) + "\u{2026}"
    }

    private func startDo() {
        isStartingDo = true
        Task {
            let outcome = await state.doDryRun(entry.id)
            isStartingDo = false
            onDo(DoSheetContext(entry: entry, outcome: outcome))
        }
    }
}

private struct DoConfirmSheet: View {
    let context: DoSheetContext
    @ObservedObject var state: StateModel
    @Environment(\.dismiss) private var dismiss

    @State private var resultText: String?
    @State private var isRunning = false

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Confirm action")
                .font(.headline)
            Text(context.entry.actionLabel ?? "Run action")
                .font(.subheadline)

            switch context.outcome {
            case .success(let preview):
                ScrollView {
                    Text(preview)
                        .font(.system(.caption, design: .monospaced))
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
                .frame(maxHeight: 160)
                .padding(8)
                .background(.quaternary.opacity(0.5), in: RoundedRectangle(cornerRadius: 6))

                if let resultText {
                    Text(resultText)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }

                HStack {
                    Button("Cancel") { dismiss() }
                    Spacer()
                    // Confirm only ever appears here, inside .success —
                    // a failed/timed-out/nonzero-exit dry run can never
                    // reach this branch, so there is no code path where
                    // Confirm is live without a verified-clean preview.
                    Button("Confirm") {
                        isRunning = true
                        Task {
                            let result = await state.doConfirmed(context.entry.id)
                            isRunning = false
                            resultText = result?.stdout.isEmpty == false ? result!.stdout : result?.stderr
                        }
                    }
                    .disabled(isRunning)
                    .keyboardShortcut(.defaultAction)
                }

            case .failure(let message):
                Text(message)
                    .font(.system(.caption, design: .monospaced))
                    .foregroundStyle(.red)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(8)
                    .background(Color.red.opacity(0.08))
                    .clipShape(RoundedRectangle(cornerRadius: 6))

                Text("No preview could be verified, so this action cannot be confirmed here.")
                    .font(.caption)
                    .foregroundStyle(.secondary)

                HStack {
                    Spacer()
                    Button("Close") { dismiss() }
                        .keyboardShortcut(.defaultAction)
                }
            }
        }
        .padding(16)
        .frame(width: 360)
    }
}
