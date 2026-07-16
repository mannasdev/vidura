"""--version is uniform across all 7 entry points (W2, #8): every CLI
answers with the vidura-cli distribution version and exits 0 before
doing any work (no DB open, no stdin read, no session scan)."""

from importlib.metadata import PackageNotFoundError

import pytest

from vidura import cli, do_cli, hooks_cli, ledger_cli, report, state_cli, sweep
from vidura.version import package_version


@pytest.mark.parametrize(
    "entry_main",
    [
        pytest.param(report.main, id="report"),
        pytest.param(sweep.main, id="sweep"),
        pytest.param(ledger_cli.main, id="ledger"),
        pytest.param(do_cli.main, id="do"),
        pytest.param(state_cli.main, id="state"),
        pytest.param(hooks_cli.main, id="hook"),
        pytest.param(cli.main, id="reflect"),
    ],
)
def test_version_exits_zero_and_prints_version(entry_main, capsys):
    with pytest.raises(SystemExit) as excinfo:
        entry_main(["--version"])
    assert excinfo.value.code == 0
    out = capsys.readouterr().out
    assert package_version() in out
    assert out.strip()


def test_package_version_falls_back_to_unknown(monkeypatch):
    def _missing(name):
        raise PackageNotFoundError(name)
    monkeypatch.setattr("vidura.version.version", _missing)
    assert package_version() == "unknown"
