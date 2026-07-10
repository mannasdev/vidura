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
    private let policy = AnimationPolicy(reduceMotion: AnimationPolicy.systemReduceMotion)

    public init(state: StateModel) {
        self.state = state
    }

    public var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            hero

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

            footerRule
            footer
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

    private var celebratableIds: [Int] {
        state.mood?.adoptedUncelebratedIds ?? []
    }

    private var currentMood: PetMood {
        PetMood(rawMood: state.mood?.mood ?? Mood.asleep.rawValue)
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
        HStack(alignment: .center, spacing: 18) {
            CharacterPortrait(
                mood: currentMood,
                celebrateOnAppear: state.shouldCelebrateOnOpen,
                policy: policy
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
                Button("Pets") {}
                Button("Settings") {}
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
