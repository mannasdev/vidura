import string

from vidura.fix_index import FixAction, fix_index_for_prompt, load_fix_index


def test_returns_at_least_five_fixes():
    fixes = load_fix_index()
    assert len(fixes) >= 5


def test_every_fix_has_required_nonempty_fields():
    for fix in load_fix_index():
        assert fix.id
        assert fix.title
        assert fix.friction_patterns
        assert fix.remedy
        assert 0.0 <= fix.confidence_floor <= 1.0


def test_ids_are_unique():
    fixes = load_fix_index()
    ids = [f.id for f in fixes]
    assert len(ids) == len(set(ids))


def test_judge_executor_split_fix_present():
    fixes = load_fix_index()
    ids = [f.id for f in fixes]
    assert "judge-executor-split" in ids


def test_no_fix_uses_reserved_novel_id():
    assert all(f.id != "novel" for f in load_fix_index())


def test_index_has_at_least_twenty_entries():
    assert len(load_fix_index()) >= 20


_V1_ACTION_IDS = {
    "github-context-by-paste",
    "manual-ui-verification",
    "fix-without-failing-test",
    "shotgun-debugging",
    "missing-claude-md",
    "permission-prompt-fatigue",
    "spec-before-code",
}


def test_exactly_seven_fixes_carry_an_action():
    fixes = load_fix_index()
    with_action = [f for f in fixes if f.action is not None]
    assert len(with_action) == 7
    assert {f.id for f in with_action} == _V1_ACTION_IDS


def test_all_other_fixes_have_no_action():
    for fix in load_fix_index():
        if fix.id not in _V1_ACTION_IDS:
            assert fix.action is None


def test_action_tier_values_are_valid():
    for fix in load_fix_index():
        if fix.action is not None:
            assert fix.action.tier in (1, 2, 3)


_SAFE_TOKEN_CHARS = set(string.ascii_letters + string.digits + "-_./@")


def test_run_actions_have_argv_list_and_no_shell_metachars_needed():
    run_fixes = [f for f in load_fix_index() if f.action and f.action.tier == 3]
    assert run_fixes  # sanity: at least one RUN action exists
    for fix in run_fixes:
        assert isinstance(fix.action.argv, list)
        assert len(fix.action.argv) > 0
        for token in fix.action.argv:
            assert isinstance(token, str)
            # each argv element is a single shell-safe token — no spaces or
            # shell metacharacters, since the executor calls subprocess with
            # shell=False and the argv list passed through untouched.
            assert set(token) <= _SAFE_TOKEN_CHARS


def test_write_action_has_target_file():
    write_fixes = [f for f in load_fix_index() if f.action and f.action.tier == 2]
    assert len(write_fixes) == 1
    fix = write_fixes[0]
    assert fix.id == "missing-claude-md"
    assert fix.action.target_file == "CLAUDE.md"
    assert fix.action.payload


def test_copy_actions_have_payload_text():
    copy_fixes = [f for f in load_fix_index() if f.action and f.action.tier == 1]
    assert len(copy_fixes) == 2
    for fix in copy_fixes:
        assert fix.action.payload
        assert fix.action.argv is None


def test_fix_action_dataclass_shape():
    action = FixAction(tier=1, label="Copy something", payload="text")
    assert action.argv is None
    assert action.target_file is None


def test_fix_index_for_prompt_shape_and_no_action_leak():
    dicts = fix_index_for_prompt()
    assert len(dicts) == len(load_fix_index())
    for d in dicts:
        assert set(d.keys()) == {"id", "title", "friction_patterns", "remedy", "confidence_floor"}
        assert "action" not in d  # never round-tripped through the model


def test_fix_index_for_prompt_used_identically_by_report_and_sweep(monkeypatch):
    """report.py and sweep.py both build their fix_index payload from
    the same shared helper — this used to be a verbatim-duplicated
    comprehension in each module that could silently drift."""
    from vidura.report import build_report_request
    from vidura.sweep import _batch_request
    from vidura.store import open_db

    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as d:
        conn = open_db(Path(d) / "db.sqlite")
        report_request = build_report_request([])
        from vidura.sweep import SessionWork

        batch_request = _batch_request(conn, [SessionWork(path=Path("x"), chunks=[], streak_count=0)])
        conn.close()
    assert report_request.fix_index == batch_request.fix_index == fix_index_for_prompt()
