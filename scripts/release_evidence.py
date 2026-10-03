# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Record and verify the evidence files that ship with a sumo-qa release.

``.github/workflows/release.yml`` runs both subcommands; .github/SECURITY.md
describes the files and how a consumer checks them.

``record DIST`` runs in the build job once DIST holds the wheel, the sdist and
the CycloneDX SBOM (``sbom.cdx.json``). It writes:

- ``build-info.json``: source commit and ref, workflow run, runner, Python, the
  exact version of every package in the build environment (the build runs with
  ``--no-isolation``, so that environment is the whole set of build inputs) and
  the SHA-256 of the wheel and sdist;
- ``SHA256SUMS``: the digest of every other file in DIST, in ``sha256sum``
  format. The build-provenance attestation takes its subjects from this file.

``verify DIST [--commit SHA]`` is the gate before publishing. It fails when a
required file is missing, a file is unlisted in or absent from ``SHA256SUMS``,
a digest does not match, the SBOM does not describe the built version, or
``build-info.json`` names different artifacts or a different commit. The
signed attestations are checked separately with ``gh attestation verify``.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import re
import sys
from pathlib import Path

PACKAGE = "sumo-qa"
SUMS = "SHA256SUMS"
SBOM = "sbom.cdx.json"
BUILD_INFO = "build-info.json"
BUILD_TOOLS = ("build", "hatchling")
_SUM_LINE = re.compile(r"^([0-9a-f]{64}) [ *](.+)$")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _packages(dist: Path) -> tuple[list[Path], list[Path]]:
    return sorted(dist.glob("*.whl")), sorted(dist.glob("*.tar.gz"))


def _version(path: Path) -> str:
    if path.name.endswith(".whl"):
        return path.name.split("-")[1]
    return path.name.removesuffix(".tar.gz").rsplit("-", 1)[1]


def record(dist: Path) -> None:
    wheels, sdists = _packages(dist)
    env = os.environ.get
    info = {
        "source": {
            "repository": env("GITHUB_REPOSITORY"),
            "commit": env("GITHUB_SHA"),
            "ref": env("GITHUB_REF"),
        },
        "workflow": {
            "ref": env("GITHUB_WORKFLOW_REF"),
            "run_id": env("GITHUB_RUN_ID"),
            "run_attempt": env("GITHUB_RUN_ATTEMPT"),
        },
        "runner": {
            "os": env("RUNNER_OS"),
            "arch": env("RUNNER_ARCH"),
            "environment": env("RUNNER_ENVIRONMENT"),
            "image": env("ImageOS"),
            "image_version": env("ImageVersion"),
        },
        "python": {
            "implementation": platform.python_implementation(),
            "version": platform.python_version(),
        },
        "build_environment": dict(
            sorted(
                (_norm(d.metadata["Name"]), d.version) for d in importlib.metadata.distributions()
            )
        ),
        "artifacts": {p.name: _sha256(p) for p in wheels + sdists},
    }
    (dist / BUILD_INFO).write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")
    files = sorted(p for p in dist.iterdir() if p.is_file() and p.name != SUMS)
    (dist / SUMS).write_text("".join(f"{_sha256(p)}  {p.name}\n" for p in files), encoding="utf-8")


def _check_sums(dist: Path) -> list[str]:
    sums = dist / SUMS
    if not sums.is_file():
        return [f"{SUMS} is missing"]
    errors = []
    listed: dict[str, str] = {}
    for line in sums.read_text(encoding="utf-8").splitlines():
        match = _SUM_LINE.match(line)
        if not match:
            errors.append(f"{SUMS}: malformed line {line!r}")
            continue
        listed[match.group(2)] = match.group(1)
    present = {p.name for p in dist.iterdir() if p.is_file() and p.name != SUMS}
    errors += [f"{name} is not listed in {SUMS}" for name in sorted(present - listed.keys())]
    for name, digest in sorted(listed.items()):
        if name not in present:
            errors.append(f"{name} is listed in {SUMS} but missing")
        elif _sha256(dist / name) != digest:
            errors.append(f"{name} does not match its {SUMS} digest")
    return errors


def _load_json(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _check_sbom(dist: Path, version: str) -> list[str]:
    bom = _load_json(dist / SBOM)
    if bom is None:
        return [f"{SBOM} is missing or not a JSON object"]
    if bom.get("bomFormat") != "CycloneDX" or not bom.get("specVersion"):
        return [f"{SBOM} is not a CycloneDX document"]
    components = [bom.get("metadata", {}).get("component", {}), *bom.get("components", [])]
    if not any(
        _norm(str(c.get("name", ""))) == PACKAGE and c.get("version") == version for c in components
    ):
        return [f"{SBOM} does not describe {PACKAGE} {version}"]
    return []


def _check_build_info(dist: Path, packages: list[Path], commit: str | None) -> list[str]:
    info = _load_json(dist / BUILD_INFO)
    if info is None:
        return [f"{BUILD_INFO} is missing or not a JSON object"]
    errors = []
    if info.get("artifacts") != {p.name: _sha256(p) for p in packages}:
        errors.append(f"{BUILD_INFO} artifacts do not match the built wheel and sdist")
    if commit and info.get("source", {}).get("commit") != commit:
        errors.append(f"{BUILD_INFO} source commit is not {commit}")
    if not info.get("python", {}).get("version"):
        errors.append(f"{BUILD_INFO} does not record the Python version")
    tools = info.get("build_environment", {})
    errors += [f"{BUILD_INFO} does not record {tool}" for tool in BUILD_TOOLS if tool not in tools]
    return errors


def verify(dist: Path, commit: str | None = None) -> list[str]:
    wheels, sdists = _packages(dist)
    if len(wheels) != 1 or len(sdists) != 1:
        return [f"expected one wheel and one sdist, found {len(wheels)} and {len(sdists)}"]
    version = _version(wheels[0])
    errors = _check_sums(dist)
    if _version(sdists[0]) != version:
        errors.append(f"sdist version {_version(sdists[0])} is not wheel version {version}")
    errors += _check_sbom(dist, version)
    errors += _check_build_info(dist, wheels + sdists, commit)
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("record").add_argument("dist", type=Path)
    check = sub.add_parser("verify")
    check.add_argument("dist", type=Path)
    check.add_argument("--commit", help="source commit build-info.json must name")
    args = parser.parse_args(argv)
    if args.command == "record":
        record(args.dist)
        return 0
    errors = verify(args.dist, args.commit)
    for error in errors:
        print(f"release evidence: {error}", file=sys.stderr)
    if not errors:
        print(f"release evidence verified: {args.dist}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
