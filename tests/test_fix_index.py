from vidura.fix_index import load_fix_index


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
