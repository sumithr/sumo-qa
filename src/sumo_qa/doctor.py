# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""sumo-qa-doctor — read-only setup and host compatibility diagnostics.

Shipped as the ``sumo-qa-doctor`` console script (exposed via
``[project.scripts]`` in pyproject.toml) and as ``python -m sumo_qa.doctor``.

Runs a fixed sequence of read-only checks against the local sumo-qa install
and the host configs the ``sumo-qa-install`` installer would write to.
Never mutates any file on disk. Prints a human-readable report by default
or a JSON document with ``--json``.

The JSON shape is INTERNAL until sumo-qa 1.0 — see docs/INSTALL.md.

Doctor never modifies installer.py — every read-only probe it needs is
imported from installer's existing public + private surface. That keeps
the installer's existing test suite passing unchanged across this change.
"""

from __future__ import annotations

import sys as _sys
from dataclasses import dataclass, field
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version
from typing import Literal

Status = Literal["OK", "WARN", "FAIL"]


@dataclass(frozen=True)
class CheckResult:
    """The outcome of one diagnostic check.

    ``check_id`` is stable across releases (machine-parseable). ``status``
    is one of ``OK`` / ``WARN`` / ``FAIL``. ``summary`` is a one-line human
    description. ``fix`` is the exact shell command the user should run
    (``None`` when no fix applies — OK records, or WARN records that are
    purely informational).
    """

    check_id: str
    status: Status
    summary: str
    fix: str | None = None
    details: dict = field(default_factory=dict)


def check_python_version() -> CheckResult:
    """Report the interpreter version and the installed sumo-qa package version.

    Always ``OK`` — Python <3.10 is rejected by pyproject.toml's
    ``requires-python = ">=3.10"`` before this script can even import, so
    the check is a disclosure not a gate. The two strings end up in install
    bug reports and let support distinguish "user is on the wrong Python"
    from "user is on a stale sumo-qa".
    """
    py = ".".join(str(p) for p in _sys.version_info[:3])
    try:
        pkg = _pkg_version("sumo-qa")
    except PackageNotFoundError:  # pragma: no cover -- defensive; not pip-installed
        pkg = "unknown (not installed via pip)"
    return CheckResult(
        check_id="python_version",
        status="OK",
        summary=f"Python {py}; sumo-qa {pkg}",
        details={"python_version": py, "sumo_qa_version": pkg},
    )


def main(argv: list[str] | None = None) -> int:  # pragma: no cover -- wired in Task 11
    """Stub. Filled in by the CLI surface task."""
    return 0
