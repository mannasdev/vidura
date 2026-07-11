import pytest


@pytest.fixture(autouse=True)
def _isolated_support_dir(tmp_path, monkeypatch):
    """Every test gets its own VIDURA_SUPPORT_DIR by default, pointed at
    pytest's per-test tmp_path.

    Without this, anything that resolves vidura.hooks_cli._support_dir()
    (e.g. vidura.sweep's process-level lockfile, added alongside the
    sweep-side concurrency hardening) falls through to the real
    ~/Library/Application Support/Vidura on the machine running the
    tests — touching a real user's lock/cooldown/log files, and
    potentially colliding with an actually-running sweep. Individual
    tests that need a specific support dir (e.g. tests/test_hooks_cli.py)
    already set VIDURA_SUPPORT_DIR themselves, which simply overrides
    this default."""
    monkeypatch.setenv("VIDURA_SUPPORT_DIR", str(tmp_path / "vidura-support"))
