"""Flat, hardcoded Fix Index for M0/M1 — design doc Premise #8.

The original spec calls for a versioned, PR-able YAML knowledge base
with ~30 seed entries. That's real infrastructure for a community that
doesn't exist yet in v1 (Premise #1: single-player first). This module
ships the small subset the Reflector needs to have *something* to match
against at M0 scale. Migrate to YAML + PR process once there's a real
reason to accept outside contributions.
"""

from dataclasses import dataclass


@dataclass
class Fix:
    id: str
    title: str
    friction_patterns: list[str]
    remedy: str
    confidence_floor: float


FIX_INDEX: list[Fix] = [
    Fix(
        id="judge-executor-split",
        title="Judge/executor two-model workflow",
        friction_patterns=[
            "long ideation sessions in a single model",
            "user asks the same model to both generate and evaluate plans",
            "re-prompting on architecture/planning decisions 3+ times",
        ],
        remedy=(
            "Split the workflow: a stronger model judges and critiques plans; "
            "a faster model executes. Run planning in one session with the judge "
            "model, then execute the approved plan with the executor model."
        ),
        confidence_floor=0.7,
    ),
    Fix(
        id="repeated-error-loop",
        title="Same error 3+ times without a systematic-debugging pass",
        friction_patterns=[
            "same error string recurring across multiple fix attempts",
            "trial-and-error fixes without root-cause investigation",
        ],
        remedy=(
            "Stop guessing at fixes. Reproduce the error deterministically, "
            "add logging/instrumentation at the failure point, and confirm the "
            "root cause before attempting another fix."
        ),
        confidence_floor=0.7,
    ),
    Fix(
        id="undo-revert-language",
        title="Frequent 'no, that's not what I meant' corrections",
        friction_patterns=[
            "undo or revert language appearing 2+ times in one session",
            "user re-explaining the same requirement after a wrong implementation",
        ],
        remedy=(
            "The spec was underspecified before implementation started. Write "
            "a short spec or plan and get explicit agreement before writing code."
        ),
        confidence_floor=0.75,
    ),
    Fix(
        id="single-long-session-no-checkpoints",
        title="Very long session with no intermediate commits",
        friction_patterns=[
            "session duration exceeds 2 hours with no git commits",
            "large amount of uncommitted work at risk of loss",
        ],
        remedy=(
            "Commit working increments as you go, not just at the end. "
            "Smaller commits make it easier to recover from a bad turn."
        ),
        confidence_floor=0.6,
    ),
    Fix(
        id="plan-mode-skipped",
        title="Non-trivial multi-file change started without a plan",
        friction_patterns=[
            "3+ files touched in a single session with no upfront plan",
            "architecture decisions made implicitly mid-implementation",
        ],
        remedy=(
            "For changes touching multiple files or components, write a short "
            "plan first and get it reviewed before implementation starts."
        ),
        confidence_floor=0.65,
    ),
    Fix(
        id="spec-before-code",
        title="Vague feature request expanded through corrections instead of a spec",
        friction_patterns=[
            "one-line feature request followed by many turns of the user correcting scope or behavior",
            "requirements emerging mid-implementation ('oh and it should also...')",
            "the final implementation differs substantially from the first attempt",
        ],
        remedy=(
            "Write a short spec before code: what it does, what it explicitly "
            "doesn't, and 1-2 concrete input/output examples. A spec skill or "
            "brainstorming pass before implementation removes whole rounds of rework."
        ),
        confidence_floor=0.7,
    ),
    Fix(
        id="examples-first-prompting",
        title="Desired output described abstractly across turns instead of shown once",
        friction_patterns=[
            "user describes a format, style, or transformation in prose repeatedly",
            "assistant output shape corrected multiple times ('no, more like...')",
        ],
        remedy=(
            "Show, don't describe: include one or two concrete examples of the "
            "desired output in the first prompt. Models match examples far more "
            "reliably than adjectives."
        ),
        confidence_floor=0.65,
    ),
    Fix(
        id="context-window-thrash",
        title="Marathon session re-explaining earlier decisions after context loss",
        friction_patterns=[
            "user re-states decisions or constraints already settled earlier in the session",
            "compaction or summarization artifacts followed by confusion about prior work",
            "very long single session mixing several unrelated tasks",
        ],
        remedy=(
            "Scope sessions to one task and hand off deliberately: save a short "
            "written state (decisions, next steps) and start fresh instead of "
            "pushing a bloated context that degrades every answer."
        ),
        confidence_floor=0.65,
    ),
    Fix(
        id="missing-claude-md",
        title="Project conventions re-explained every session",
        friction_patterns=[
            "user repeats build/test/run commands or conventions across sessions",
            "assistant guesses wrong test runner, formatter, or directory layout and is corrected",
        ],
        remedy=(
            "Write a CLAUDE.md at the repo root with the build/test/run commands, "
            "conventions, and gotchas you keep repeating. It loads automatically "
            "every session."
        ),
        confidence_floor=0.7,
    ),
    Fix(
        id="stale-claude-md",
        title="CLAUDE.md instructions overridden by hand every session",
        friction_patterns=[
            "user repeatedly countermands the same documented instruction",
            "assistant follows project docs that no longer match reality",
        ],
        remedy=(
            "When you correct the same documented behavior twice, update "
            "CLAUDE.md instead of correcting a third time — stale instructions "
            "are worse than none."
        ),
        confidence_floor=0.65,
    ),
    Fix(
        id="manual-ui-verification",
        title="UI state relayed to the agent by hand instead of tooling",
        friction_patterns=[
            "user describes what the browser shows or pastes screenshots repeatedly",
            "'did it work?' loops where the agent cannot see the running app",
        ],
        remedy=(
            "Give the agent eyes: a browser-automation skill or MCP (e.g. "
            "Playwright-based) lets it load the page, click, and screenshot "
            "itself — turning describe-check loops into one autonomous pass."
        ),
        confidence_floor=0.7,
    ),
    Fix(
        id="github-context-by-paste",
        title="PR/issue content pasted into chat by hand",
        friction_patterns=[
            "user pastes pull request diffs, review comments, or issue text manually",
            "agent asked to act on GitHub state it cannot fetch",
        ],
        remedy=(
            "Install the gh CLI (or a GitHub MCP) so the agent fetches PRs, "
            "issues, and reviews itself — and can post comments and open PRs "
            "without copy-paste relays."
        ),
        confidence_floor=0.65,
    ),
    Fix(
        id="docs-by-paste",
        title="Library documentation pasted into the prompt",
        friction_patterns=[
            "large blocks of API docs or README content pasted by the user",
            "hallucinated API usage corrected by pasting official docs",
        ],
        remedy=(
            "Let the agent fetch docs itself (web fetch or a docs MCP) — pasted "
            "docs eat your context window and go stale; fetched docs arrive "
            "exactly when needed."
        ),
        confidence_floor=0.6,
    ),
    Fix(
        id="fix-without-failing-test",
        title="Bug fixes shipped without a failing test first",
        friction_patterns=[
            "bug fixed and declared done without a test reproducing it",
            "the same area regresses across sessions",
        ],
        remedy=(
            "Test-driven bug fixing: write the failing test first, watch it fail, "
            "then fix. The test is the only durable proof the bug stays dead."
        ),
        confidence_floor=0.65,
    ),
    Fix(
        id="shotgun-debugging",
        title="Speculative edit-and-retry instead of diagnosis",
        friction_patterns=[
            "sequence of small speculative changes each hoping to fix the issue",
            "edits reverted and replaced by different guesses without new information",
            "no instrumentation or reproduction step between failed attempts",
        ],
        remedy=(
            "Stop editing, start measuring: reproduce deterministically, add "
            "logging at the failure point, confirm the root cause, then make one "
            "informed fix. A systematic-debugging skill enforces this order."
        ),
        confidence_floor=0.7,
    ),
    Fix(
        id="monolith-prompt",
        title="Multi-feature builds requested in one giant turn",
        friction_patterns=[
            "single prompt asking for many features at once, output partially wrong",
            "user triaging which parts of a big response to keep",
        ],
        remedy=(
            "Decompose: plan first, then execute one scoped task at a time "
            "(subagents or a task list). Small verified steps beat one large "
            "unverifiable one."
        ),
        confidence_floor=0.65,
    ),
    Fix(
        id="human-shell-relay",
        title="User runs commands by hand and pastes output back",
        friction_patterns=[
            "user pastes terminal output the agent asked them to produce",
            "'run this and tell me what it says' loops",
        ],
        remedy=(
            "Let the agent run its own commands — configure tool permissions so "
            "routine, safe commands don't need you as the relay. You review "
            "intent, not stdout."
        ),
        confidence_floor=0.6,
    ),
    Fix(
        id="permission-prompt-fatigue",
        title="Flow broken by repeated permission prompts for routine commands",
        friction_patterns=[
            "many permission approvals for the same safe command classes",
            "sessions stalling while waiting for approval on read-only operations",
        ],
        remedy=(
            "Add an allowlist for the read-only and routine commands you always "
            "approve (project settings permissions). Keep prompts for the "
            "genuinely destructive."
        ),
        confidence_floor=0.6,
    ),
    Fix(
        id="parallel-work-collision",
        title="Parallel tasks colliding in one working tree",
        friction_patterns=[
            "stash/unstash churn between unrelated tasks",
            "uncommitted changes from one task contaminating another's diff",
        ],
        remedy=(
            "Use git worktrees for parallel streams — each task gets an isolated "
            "checkout, and nothing leaks between them."
        ),
        confidence_floor=0.6,
    ),
    Fix(
        id="research-in-main-context",
        title="Exploration, implementation, and review interleaved in one context",
        friction_patterns=[
            "long exploratory searching and file reading before the actual change",
            "context filled with research the final change no longer needs",
        ],
        remedy=(
            "Dispatch subagents for research and review — they burn their own "
            "context and return only conclusions, keeping the main session lean "
            "and focused on the change itself."
        ),
        confidence_floor=0.65,
    ),
    Fix(
        id="wrong-model-for-task",
        title="Model tier mismatched to the task",
        friction_patterns=[
            "heavyweight model grinding through mechanical edits or transcription",
            "small model wrestling with architecture or judgment decisions and losing",
        ],
        remedy=(
            "Match the tier to the work: fast models for mechanical execution, "
            "strongest models for planning, judgment, and review. The split pays "
            "for itself in both cost and quality."
        ),
        confidence_floor=0.65,
    ),
    Fix(
        id="whole-file-paste",
        title="Entire files pasted into chat instead of referenced",
        friction_patterns=[
            "large file contents pasted by the user when a path would do",
            "agent asked about code it could simply read from disk",
        ],
        remedy=(
            "Reference paths and let the agent read files itself — it reads "
            "exactly the ranges it needs, and your context window stays usable."
        ),
        confidence_floor=0.6,
    ),
    Fix(
        id="unverified-done-claims",
        title="'Done' accepted without verification, breakage discovered later",
        friction_patterns=[
            "'you said it was fixed but' follow-ups in later turns or sessions",
            "completion claims not backed by a test run or manual check",
        ],
        remedy=(
            "Make verification part of done: run the tests, exercise the "
            "feature, show the output — before accepting completion. A "
            "verification skill or habit closes this gap permanently."
        ),
        confidence_floor=0.7,
    ),
    Fix(
        id="session-limit-lost-work",
        title="Session limits cutting off in-flight work with nothing recoverable",
        friction_patterns=[
            "session or usage limit reached mid-task with uncommitted changes",
            "background agents or long jobs killed by a session ending, work lost",
        ],
        remedy=(
            "Work in commit-sized increments and checkpoint before long "
            "operations; treat the session limit like a train departure — "
            "never board it holding unsaved work."
        ),
        confidence_floor=0.65,
    ),
    Fix(
        id="post-edit-ritual-by-hand",
        title="The same format/lint/test ritual repeated manually after every change",
        friction_patterns=[
            "user or agent runs the identical formatting or lint command after each edit",
            "review feedback dominated by mechanical style fixes",
        ],
        remedy=(
            "Automate the ritual with hooks: run formatters/linters "
            "automatically after edits so neither of you spends turns on "
            "mechanical cleanup."
        ),
        confidence_floor=0.65,
    ),
    Fix(
        id="interrupt-churn",
        title="Frequent mid-task interruptions redirecting the agent",
        friction_patterns=[
            "request interrupted markers appearing several times in one session",
            "agent redirected mid-execution because intent was underspecified upfront",
        ],
        remedy=(
            "Front-load intent: constraints, non-goals, and the definition of "
            "done in the opening prompt (or a quick plan-mode pass) — steering "
            "upfront is cheaper than braking mid-flight."
        ),
        confidence_floor=0.65,
    ),
]


def load_fix_index() -> list[Fix]:
    return FIX_INDEX
