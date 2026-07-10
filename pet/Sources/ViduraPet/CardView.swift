import SwiftUI

/// The popover's content: pending suggestions as quiet, restrained cards.
/// Deliberately undecorated — no animation, no mascot, no cheerful
/// copy beyond what the Python core itself writes (blunt_summary is
/// already the whole voice of the app; this view just lays it out).
struct CardView: View {
    @ObservedObject var state: StateModel

    @State private var pendingDoAction: DoSheetContext?

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            header

            if !celebratableIds.isEmpty {
                celebrationBanner
            }

            if state.entries.isEmpty {
                emptyState
            } else {
                ScrollView {
                    VStack(alignment: .leading, spacing: 10) {
                        ForEach(state.entries) { entry in
                            EntryRow(entry: entry, state: state) { context in
                                pendingDoAction = context
                            }
                        }
                    }
                    .padding(12)
                }
                .frame(maxHeight: 420)
            }

            if let lastError = state.lastError {
                errorLine(lastError)
            }
        }
        .frame(width: 400)
        .sheet(item: $pendingDoAction) { context in
            DoConfirmSheet(context: context, state: state)
        }
        .onAppear { state.refresh() }
    }

    private var celebratableIds: [Int] {
        state.mood?.adoptedUncelebratedIds ?? []
    }

    /// The panel header IS the pet: a small pixel-art creature (mood ->
    /// grid mapping lives in PixelPetGrid.grid(for:), the one designer
    /// swap point for future art) next to the "Vidura" title and mood
    /// word. Static swap only on mood change — no animation, per the
    /// anti-Clippy invariant.
    private var header: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 12) {
                PixelPet(mood: currentMood)
                    .frame(width: 72, height: 72)

                VStack(alignment: .leading, spacing: 2) {
                    Text("Vidura")
                        .font(.title2.weight(.semibold))
                    if let mood = state.mood?.mood {
                        Text(mood.capitalized)
                            .font(.subheadline)
                            .foregroundStyle(.secondary)
                    }
                }

                Spacer()
            }
            .padding(16)
            Divider()
        }
    }

    /// Falls back to ASLEEP (same default the rest of the app uses)
    /// until the first poll resolves a real mood.
    private var currentMood: Mood {
        state.mood.flatMap { Mood(rawValue: $0.mood) } ?? .asleep
    }

    @ViewBuilder
    private var celebrationBanner: some View {
        if let firstId = celebratableIds.first {
            HStack(spacing: 8) {
                Image(systemName: "star.circle")
                    .foregroundStyle(.secondary)
                Text("Advice adopted — behavior changed.")
                    .font(.caption)
                Spacer()
                Button("Nice") {
                    Task { await state.celebrate(firstId) }
                }
                .font(.caption)
                .controlSize(.small)
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 8)
        }
    }

    private func errorLine(_ message: String) -> some View {
        // Quiet by default — only the CLIs-entirely-missing case (the one
        // failure mode that means the pet cannot function at all) earns
        // an alarming color; every other error stays secondary.
        Text(message)
            .font(.caption2)
            .foregroundStyle(message.contains("CLIs not found") ? AnyShapeStyle(.red) : AnyShapeStyle(.secondary))
            .padding(.horizontal, 12)
            .padding(.vertical, 8)
    }

    private var emptyState: some View {
        VStack(spacing: 6) {
            Image(systemName: "moon.zzz")
                .font(.largeTitle)
                .foregroundStyle(.secondary)
            Text("Nothing earned.")
                .font(.callout)
            Text("Silence is correct.")
                .font(.caption)
                .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 36)
        .padding(.horizontal, 16)
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

private struct EntryRow: View {
    let entry: LedgerEntry
    @ObservedObject var state: StateModel
    let onDo: (DoSheetContext) -> Void

    @State private var isStartingDo = false
    @State private var isExpanded = false

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text(entry.fixId)
                    .font(.system(.caption2, design: .monospaced))
                    .padding(.horizontal, 8)
                    .padding(.vertical, 3)
                    .background(.tertiary.opacity(0.5), in: Capsule())
                Spacer()
                Text(String(format: "%.0f%%", entry.confidence * 100))
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            Text(entry.bluntSummary)
                .font(.callout)
                .foregroundStyle(.primary)
                .lineLimit(isExpanded ? nil : 4)
                .fixedSize(horizontal: false, vertical: true)
                .onTapGesture { isExpanded.toggle() }

            ForEach(entry.evidence.prefix(2), id: \.self) { quote in
                HStack(alignment: .top, spacing: 8) {
                    RoundedRectangle(cornerRadius: 1)
                        .fill(.tertiary)
                        .frame(width: 2)
                    Text(truncatedQuote(quote))
                        .font(.system(.caption, design: .monospaced))
                        .foregroundStyle(.secondary)
                }
            }

            HStack(spacing: 8) {
                Spacer()
                Button("Dismiss") { Task { await state.dismiss(entry.id) } }
                    .buttonStyle(.bordered)
                Button("Accept") { Task { await state.accept(entry.id) } }
                    .buttonStyle(.borderedProminent)
                if entry.hasAction {
                    Button("Do — \(entry.actionLabel ?? "Run")") {
                        startDo()
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(isStartingDo)
                }
            }
            .controlSize(.small)
        }
        .padding(12)
        .background(.quaternary.opacity(0.5), in: RoundedRectangle(cornerRadius: 10))
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
