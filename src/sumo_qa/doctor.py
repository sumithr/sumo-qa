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

from dataclasses import dataclass, field
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


def main(argv: list[str] | None = None) -> int:  # pragma: no cover -- wired in Task 11
    """Stub. Filled in by the CLI surface task."""
    return 0
