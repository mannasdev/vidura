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
]


def load_fix_index() -> list[Fix]:
    return FIX_INDEX
