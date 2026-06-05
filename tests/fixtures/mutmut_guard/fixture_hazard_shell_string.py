# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""HAZARD fixture (shell=True string command): ``python -m sumo_qa`` as one string.

``subprocess.run("python -m sumo_qa ...", shell=True)`` passes the WHOLE command
as a single string, not an argv list. The pre-fix guard scanned string literals
without tokenising, so it saw one token (``"python -m sumo_qa --help"``) that
matched neither the interpreter signal (``-m``/``-c``/``python``) nor the bare
``sumo_qa`` import token — and the spawn, which loads the full package (and thus
every mutated module) into a fresh interpreter, escaped detection. The guard now
shlex-tokenises a single-string command so this is classified like the argv form.
Fixture, not a test (named ``fixture_*.py``).
"""

from __future__ import annotations

import subprocess


def spawn_via_shell() -> None:
    subprocess.run("python -m sumo_qa --help", shell=True, capture_output=True)
