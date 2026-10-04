# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Guard the hashed runtime lock the release SBOM job installs.

``release.yml`` installs ``.github/release/runtime-requirements.txt`` with
``--no-deps``, so a ``pyproject.toml`` dependency floor raised without
regenerating the lock would only fail on the release runner's ``pip check``.
This fails it in CI instead: every runtime dependency that applies on the
release runner (Linux, CPython 3.13) must be pinned in the lock to a version
its specifier allows.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover -- 3.10 backport path
    import tomli as tomllib

REPO_ROOT = Path(__file__).resolve().parents[1]
LOCK = REPO_ROOT / ".github" / "release" / "runtime-requirements.txt"
RUNNER = {
    "python_version": "3.13",
    "python_full_version": "3.13.0",
    "implementation_name": "cpython",
    "platform_python_implementation": "CPython",
    "sys_platform": "linux",
    "platform_system": "Linux",
    "os_name": "posix",
    "platform_machine": "x86_64",
}
_PIN = re.compile(r"^([A-Za-z0-9._-]+)==([^\s;\\]+)", re.MULTILINE)


def unmet(pyproject: str, lock: str) -> list[str]:
    """The runtime requirements in ``pyproject`` the pins in ``lock`` do not satisfy."""
    pins: dict[str, set[str]] = {}
    for name, version in _PIN.findall(lock):
        pins.setdefault(canonicalize_name(name), set()).add(version)
    problems = []
    for spec in tomllib.loads(pyproject)["project"]["dependencies"]:
        req = Requirement(spec)
        if req.marker and not req.marker.evaluate(RUNNER):
            continue
        versions = pins.get(canonicalize_name(req.name), set())
        if not versions or not all(req.specifier.contains(v, prereleases=True) for v in versions):
            problems.append(f"{spec} (lock pins {sorted(versions) or 'nothing'})")
    return problems


def test_runtime_lock_satisfies_pyproject_dependencies() -> None:
    problems = unmet(
        (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"),
        LOCK.read_text(encoding="utf-8"),
    )
    assert not problems, (
        "regenerate .github/release/runtime-requirements.txt with the command in its "
        f"header; unmet: {problems}"
    )


def test_raised_floor_without_regeneration_fails() -> None:
    lock = "pyyaml==6.0.3 \\\n    --hash=sha256:00\n"
    assert unmet('[project]\ndependencies = ["PyYAML>=6"]\n', lock) == []
    assert unmet('[project]\ndependencies = ["PyYAML>=6.1"]\n', lock) == [
        "PyYAML>=6.1 (lock pins ['6.0.3'])"
    ]
    assert unmet('[project]\ndependencies = ["mcp>=2"]\n', lock) == ["mcp>=2 (lock pins nothing)"]
    assert unmet("[project]\ndependencies = [\"tomli; python_version < '3.11'\"]\n", lock) == []
