# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Record and verify the evidence files that ship with a sumo-qa release.

``.github/workflows/release.yml`` runs all three subcommands; .github/SECURITY.md
describes the files and how a consumer checks them.

``record DIST`` runs in the build job once DIST holds the wheel and the sdist,
before anything else is installed. It writes ``build-info.json``: source commit
and ref, workflow run, runner, Python, the exact version of every package in
the build environment (the build runs with ``--no-isolation``, so that
environment is the whole set of build inputs) and the SHA-256 of the wheel and
sdist. The build job then publishes the digest of ``build-info.json`` as a job
output, outside the artifact store, and the attest job checks the file against
it, so a later job can change neither the file nor, through it, the packages.

``sums DIST`` runs once the CycloneDX SBOM (``sbom.cdx.json``, generated in a
separate job, of whose artifact the attest job takes only that file) has joined
the build job's files. It writes ``SHA256SUMS``: the digest of every other file
in DIST, in ``sha256sum`` format. The build-provenance attestation takes its
subjects from this file.

``verify DIST [--commit SHA]`` is the gate before signing. It fails when DIST
holds anything but one wheel, one sdist, ``sbom.cdx.json``, ``build-info.json``
and ``SHA256SUMS``, a required file is missing, a file is unlisted in or absent
from ``SHA256SUMS``, a digest does not match, a package does not match the
digest ``build-info.json`` recorded in the build job, the SBOM has no non-empty
``serialNumber`` (``actions/attest`` requires one, of any form) or does not
describe the built version, or ``build-info.json`` names a different commit.
The signed attestations are checked separately with ``gh attestation verify``.
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


def sums(dist: Path) -> None:
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


def _dict(value: object) -> dict:
    return value if isinstance(value, dict) else {}


def _check_sbom(dist: Path, version: str) -> list[str]:
    bom = _load_json(dist / SBOM)
    if bom is None:
        return [f"{SBOM} is missing or not a JSON object"]
    if bom.get("bomFormat") != "CycloneDX" or not bom.get("specVersion"):
        return [f"{SBOM} is not a CycloneDX document"]
    # actions/attest only checks that serialNumber is present, not its form.
    serial = bom.get("serialNumber")
    if not isinstance(serial, str) or not serial:
        return [f"{SBOM} has no serialNumber (a non-empty string), which actions/attest requires"]
    components = bom.get("components", [])
    if not isinstance(components, list):
        return [f"{SBOM} components is not a list"]
    components = [_dict(_dict(bom.get("metadata")).get("component")), *map(_dict, components)]
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
    if commit and _dict(info.get("source")).get("commit") != commit:
        errors.append(f"{BUILD_INFO} source commit is not {commit}")
    if not _dict(info.get("python")).get("version"):
        errors.append(f"{BUILD_INFO} does not record the Python version")
    tools = _dict(info.get("build_environment"))
    errors += [f"{BUILD_INFO} does not record {tool}" for tool in BUILD_TOOLS if tool not in tools]
    return errors


def verify(dist: Path, commit: str | None = None) -> list[str]:
    wheels, sdists = _packages(dist)
    if len(wheels) != 1 or len(sdists) != 1:
        return [f"expected one wheel and one sdist, found {len(wheels)} and {len(sdists)}"]
    version = _version(wheels[0])
    allowed = {p.name for p in wheels + sdists} | {SBOM, BUILD_INFO, SUMS}
    errors = [
        f"{p.name} is not a release file" for p in sorted(dist.iterdir()) if p.name not in allowed
    ]
    errors += _check_sums(dist)
    if _version(sdists[0]) != version:
        errors.append(f"sdist version {_version(sdists[0])} is not wheel version {version}")
    errors += _check_sbom(dist, version)
    errors += _check_build_info(dist, wheels + sdists, commit)
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("record").add_argument("dist", type=Path)
    sub.add_parser("sums").add_argument("dist", type=Path)
    check = sub.add_parser("verify")
    check.add_argument("dist", type=Path)
    check.add_argument("--commit", help="source commit build-info.json must name")
    args = parser.parse_args(argv)
    if args.command == "record":
        record(args.dist)
        return 0
    if args.command == "sums":
        sums(args.dist)
        return 0
    errors = verify(args.dist, args.commit)
    for error in errors:
        print(f"release evidence: {error}", file=sys.stderr)
    if not errors:
        print(f"release evidence verified: {args.dist}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
