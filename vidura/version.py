"""Shared package-version lookup for every CLI entry point.

The distribution is published as vidura-cli ("vidura" on PyPI is an
unrelated project — see pyproject.toml) while the import package stays
`vidura`; this helper owns that name mapping so each entry point's
--version flag doesn't repeat the distribution name.
"""

from importlib.metadata import PackageNotFoundError, version


def package_version() -> str:
    """Installed vidura-cli version, or "unknown" when running from a
    source tree without an installed distribution."""
    try:
        return version("vidura-cli")
    except PackageNotFoundError:
        return "unknown"
