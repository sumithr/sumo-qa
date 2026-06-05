# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Tests that the built wheel ships the PEP 561 typing marker.

Covers:
  T1 — A freshly built wheel contains ``sumo_qa/py.typed``, so the
       ``Typing :: Typed`` classifier in pyproject is honoured by downstream
       type-checkers that consume the published distribution.

End-to-end packaging check: it exercises the real Hatch build path the
in-process unit suite never touches. The regression it guards against — the
marker file being deleted, or dropped from the wheel target's file selection —
is invisible to tests that import from ``src/`` because those read the source
tree, not the built artifact.

Subprocess-based + slow-ish (a full wheel build), so it is excluded from the
mutmut gate via ``[tool.mutmut].pytest_add_cli_args`` in pyproject.toml, the
same treatment the other subprocess E2E tests receive.
"""

# mutmut-subprocess-spawning: spawns a ``pip wheel`` build subprocess against the
# tree. Under mutmut the CWD is the incomplete mutants/ mirror, so the build
# would target the wrong tree; it must be excluded from the mutmut gate via
# [tool.mutmut].pytest_add_cli_args in pyproject.toml. Unlike the ``-m sumo_qa``
# E2E tests this is a build-subprocess (not an import-mutated-code spawn), so the
# tests/test_mutmut_subprocess_exclusions.py guard allow-lists it by name while
# still requiring this marker. See docs/DEVELOPMENT.md § Mutation testing.

from __future__ import annotations

import subprocess
import sys
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_built_wheel_contains_py_typed_marker(tmp_path: Path) -> None:
    """T1 — the PEP 561 marker is present in the built wheel artifact."""
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            str(REPO_ROOT),
            "--no-build-isolation",
            "--no-deps",
            "-w",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"wheel build failed:\n{result.stderr}"

    wheels = list(tmp_path.glob("*.whl"))
    assert len(wheels) == 1, f"expected exactly one wheel, found {wheels}"

    with zipfile.ZipFile(wheels[0]) as zf:
        names = zf.namelist()

    assert "sumo_qa/py.typed" in names, (
        "PEP 561 marker missing from built wheel; sumo_qa/ members: "
        f"{sorted(n for n in names if n.startswith('sumo_qa/'))}"
    )
