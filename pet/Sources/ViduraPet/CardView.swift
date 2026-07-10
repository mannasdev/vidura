import SwiftUI

/// The popover's content: pending suggestions as plain, blunt cards.
/// Deliberately undecorated — no animation, no mascot, no cheerful
/// copy beyond what the Python core itself writes (blunt_summary is
/// already the whole voice of the app; this view just lays it out).
struct CardView: View {
    @ObservedObject var state: StateModel

    @State private var pendingDoAction: DoSheetContext?

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            header

            if let lastError = state.lastError {
                errorBanner(lastError)
            }

            if !state.entries.isEmpty || !celebratableIds.isEmpty {
                celebrationBanner
            }

            Divider()

            if state.entries.isEmpty {
                emptyState
            } else {
                ScrollView {
                    VStack(alignment: .leading, spacing: 8) {
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
        }
        .frame(width: 360)
        .sheet(item: $pendingDoAction) { context in
            DoConfirmSheet(context: context, state: state)
        }
        .onAppear { state.refresh() }
    }

    private var celebratableIds: [Int] {
        state.mood?.adoptedUncelebratedIds ?? []
    }

    private var header: some View {
        HStack {
            Text("Vidura")
                .font(.headline)
            Spacer()
            if let mood = state.mood?.mood {
                Text(mood.capitalized)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
        .padding(12)
    }

    private func errorBanner(_ message: String) -> some View {
        Text(message)
            .font(.caption)
            .foregroundStyle(.red)
            .padding(.horizontal, 12)
            .padding(.bottom, 8)
    }

    @ViewBuilder
    private var celebrationBanner: some View {
        if let firstId = celebratableIds.first {
            HStack {
                Text("A suggestion you adopted has paid off.")
                    .font(.caption)
                Spacer()
                Button("Nice") {
                    Task { await state.celebrate(firstId) }
                }
                .font(.caption)
            }
            .padding(.horizontal, 12)
            .padding(.bottom, 8)
        }
    }

    private var emptyState: some View {
        Text("Nothing pending. The pet is resting.")
            .font(.callout)
            .foregroundStyle(.secondary)
            .padding(16)
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

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(entry.bluntSummary)
                .font(.body)
                .fixedSize(horizontal: false, vertical: true)

            HStack(spacing: 6) {
                Text(entry.fixId)
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                Text(String(format: "confidence %.2f", entry.confidence))
                    .font(.caption2)
                    .foregroundStyle(.secondary)
            }

            ForEach(entry.evidence.prefix(2), id: \.self) { quote in
                Text(quote)
                    .font(.system(.caption2, design: .monospaced))
                    .foregroundStyle(.secondary)
                    .lineLimit(2)
            }

            HStack {
                Button("Accept") { Task { await state.accept(entry.id) } }
                Button("Dismiss") { Task { await state.dismiss(entry.id) } }
                if entry.hasAction {
                    Spacer()
                    Button(entry.actionLabel ?? "Do") {
                        startDo()
                    }
                    .disabled(isStartingDo)
                }
            }
            .font(.caption)
        }
        .padding(10)
        .background(Color.gray.opacity(0.08))
        .clipShape(RoundedRectangle(cornerRadius: 8))
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
                .background(Color.gray.opacity(0.08))
                .clipShape(RoundedRectangle(cornerRadius: 6))

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
