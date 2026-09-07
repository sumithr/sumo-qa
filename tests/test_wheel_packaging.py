# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Tests that the built wheel ships the PEP 561 typing marker and the bundled
skill modules.

Covers:
  T1 — A freshly built wheel contains ``sumo_qa/py.typed``, so the
       ``Typing :: Typed`` classifier in pyproject is honoured by downstream
       type-checkers that consume the published distribution.
  T2 — (#451) every lazy skill module under ``skills/<skill>/modules/*.md``
       lands in the wheel at ``sumo_qa/_data/skills/<skill>/modules/<id>.md``,
       so a pip/uv/pipx install can serve ``mode="module"`` slices. A module
       dropped from the ``force-include`` copy would be invisible to the
       source-tree tests but fatal to an installed server.

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

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILLS_DIR = REPO_ROOT / "skills"


@pytest.fixture(scope="module")
def built_wheel_names(tmp_path_factory: pytest.TempPathFactory) -> list[str]:
    """Build the wheel ONCE per module and return its member names. Both
    membership checks read the same artifact, so the (slow) build is shared."""
    out_dir = tmp_path_factory.mktemp("wheel")
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
            str(out_dir),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"wheel build failed:\n{result.stderr}"

    wheels = list(out_dir.glob("*.whl"))
    assert len(wheels) == 1, f"expected exactly one wheel, found {wheels}"

    with zipfile.ZipFile(wheels[0]) as zf:
        return zf.namelist()


def test_built_wheel_contains_py_typed_marker(built_wheel_names: list[str]) -> None:
    """T1 — the PEP 561 marker is present in the built wheel artifact."""
    names = built_wheel_names

    assert "sumo_qa/py.typed" in names, (
        "PEP 561 marker missing from built wheel; sumo_qa/ members: "
        f"{sorted(n for n in names if n.startswith('sumo_qa/'))}"
    )


def test_built_wheel_contains_every_skill_module(built_wheel_names: list[str]) -> None:
    """T2 — every ``skills/<skill>/modules/*.md`` in the source tree is a
    member of the built wheel under ``sumo_qa/_data/skills/`` (#451). Asserted
    against the BUILT artifact, not the source tree: the regression this guards
    (a module missing from the shipped wheel) is invisible to source-tree
    tests. Also pins that at least one module ships, so the check cannot pass
    vacuously over an empty set."""
    source_modules = sorted(SKILLS_DIR.glob("*/modules/*.md"))
    assert source_modules, "no skill ships a modules/ dir; the wheel check has no subject"
    expected = [
        f"sumo_qa/_data/skills/{p.parent.parent.name}/modules/{p.name}" for p in source_modules
    ]
    shipped = set(built_wheel_names)
    missing = [m for m in expected if m not in shipped]
    assert not missing, (
        f"skill modules missing from the built wheel: {missing}; shipped _data/skills "
        f"members: {sorted(n for n in shipped if '/modules/' in n)}"
    )
