# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Source-free installed-package test for runtime knowledge-pack ingestion.

Proves a PyPI user with NO repo-root ``knowledge/`` or ``standards/`` tree on
the working path can ingest a custom pack and have the loaders return it.
Everything runs in subprocesses from a tmp cwd so no ambient repo state leaks
in, and the global scope is redirected to a tmp dir via ``XDG_DATA_HOME``.
"""

import os
import subprocess
import sys
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _clean_env(tmp_path):
    env = dict(os.environ)
    for key in ("QA_KNOWLEDGE_PATH", "QA_STANDARDS_PATH", "QA_RULES_PATH", "QA_TEST_DATA_PATH"):
        env.pop(key, None)
    env["XDG_DATA_HOME"] = str(tmp_path / "xdg")
    # Prepend src/ so the spawned interpreters can `import sumo_qa` even when the
    # project isn't pip-installed in the active venv (pre-commit's isolated venv
    # installs only the hook's deps, not the project) — same pattern as
    # tests/test_e2e_mcp_initialize.py. The loader still returns the ingested
    # GLOBAL pack (not the source-tree knowledge/) because project/global tiers
    # resolve before the repo-root fallback, which the assertion verifies.
    src_path = str(REPO_ROOT / "src")
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{src_path}{os.pathsep}{existing}" if existing else src_path
    return env


def test_pypi_user_ingest_then_load_without_repo_tree(tmp_path):
    # The tmp cwd deliberately has NO knowledge/ or standards/ tree.
    assert not (tmp_path / "knowledge").exists()
    assert not (tmp_path / "standards").exists()

    src = tmp_path / "principles.md"
    src.write_text("CUSTOM SOURCE-FREE PRINCIPLES\n", encoding="utf-8")
    env = _clean_env(tmp_path)

    # Ingest into global scope via the installed module entry point.
    ingest = subprocess.run(
        [sys.executable, "-m", "sumo_qa.ingest", str(src), "--scope", "global"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )
    assert ingest.returncode == 0, ingest.stderr

    # Load in a fresh interpreter from the same tmp cwd: the loader must return
    # the ingested content without any repo-root knowledge/ tree present.
    code = textwrap.dedent(
        """
        from sumo_qa.knowledge_loaders import sumo_qa_load_principles
        import sys
        sys.stdout.write(sumo_qa_load_principles())
        """
    )
    load = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )
    assert load.returncode == 0, load.stderr
    assert "CUSTOM SOURCE-FREE PRINCIPLES" in load.stdout
