# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Tests for scripts/release_evidence.py, the release gate in release.yml.

Decision table over the evidence checks: a recorded release verifies, and each
missing or mismatched item fails on its own. The SBOM fixture is a real
``cyclonedx-py environment`` capture of the 0.72.1 wheel, so the SBOM check is
proven against the generator's actual output shape.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
SBOM_FIXTURE = ROOT / "tests" / "fixtures" / "release_evidence" / "sbom.cdx.json"
COMMIT = "d08258c97b7cdec5c21b64545de936b9d46aaf15"


def _load():
    spec = importlib.util.spec_from_file_location(
        "release_evidence", ROOT / "scripts" / "release_evidence.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


evidence = _load()


@pytest.fixture
def dist(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A recorded release: wheel, sdist, real SBOM, build-info and sums."""
    version = json.loads(SBOM_FIXTURE.read_text())["metadata"]["component"]["version"]
    (tmp_path / f"sumo_qa-{version}-py3-none-any.whl").write_bytes(b"wheel bytes")
    (tmp_path / f"sumo_qa-{version}.tar.gz").write_bytes(b"sdist bytes")
    shutil.copy(SBOM_FIXTURE, tmp_path / evidence.SBOM)
    monkeypatch.setenv("GITHUB_SHA", COMMIT)
    tools = [SimpleNamespace(metadata={"Name": n}, version="1.0") for n in ("build", "Hatchling")]
    monkeypatch.setattr(evidence.importlib.metadata, "distributions", lambda: tools)
    evidence.record(tmp_path)
    return tmp_path


def _resum(dist: Path) -> None:
    """Re-list digests so only the check under test can fail."""
    (dist / evidence.SUMS).unlink()
    files = sorted(p for p in dist.iterdir() if p.is_file())
    (dist / evidence.SUMS).write_text(
        "".join(f"{evidence._sha256(p)}  {p.name}\n" for p in files), encoding="utf-8"
    )


def _wheel(dist: Path) -> Path:
    return next(dist.glob("*.whl"))


def test_recorded_release_verifies(dist: Path) -> None:
    assert evidence.verify(dist, COMMIT) == []
    listed = (dist / evidence.SUMS).read_text().split()
    assert {evidence.SBOM, evidence.BUILD_INFO, _wheel(dist).name} <= set(listed)
    info = json.loads((dist / evidence.BUILD_INFO).read_text())
    assert info["source"]["commit"] == COMMIT
    assert info["build_environment"] == {"build": "1.0", "hatchling": "1.0"}


def test_missing_sums_fails(dist: Path) -> None:
    (dist / evidence.SUMS).unlink()
    assert evidence.verify(dist) == ["SHA256SUMS is missing"]


def test_tampered_wheel_fails_digest_and_build_info(dist: Path) -> None:
    _wheel(dist).write_bytes(b"tampered")
    assert evidence.verify(dist) == [
        f"{_wheel(dist).name} does not match its SHA256SUMS digest",
        "build-info.json artifacts do not match the built wheel and sdist",
    ]


def test_unlisted_file_fails(dist: Path) -> None:
    (dist / "extra.txt").write_text("x")
    assert evidence.verify(dist) == ["extra.txt is not listed in SHA256SUMS"]


def test_listed_but_missing_file_fails(dist: Path) -> None:
    (dist / evidence.SBOM).unlink()
    assert evidence.verify(dist) == [
        "sbom.cdx.json is listed in SHA256SUMS but missing",
        "sbom.cdx.json is missing or not a JSON object",
    ]


def test_malformed_sums_line_fails(dist: Path) -> None:
    with (dist / evidence.SUMS).open("a") as sums:
        sums.write("not-a-digest  x\n")
    assert evidence.verify(dist) == ["SHA256SUMS: malformed line 'not-a-digest  x'"]


@pytest.mark.parametrize(
    ("bom", "error"),
    [
        ({"bomFormat": "SPDX", "specVersion": "1.6"}, "sbom.cdx.json is not a CycloneDX document"),
        ([], "sbom.cdx.json is missing or not a JSON object"),
    ],
    ids=["not-cyclonedx", "not-an-object"],
)
def test_sbom_mismatch_fails(dist: Path, bom: object, error: str) -> None:
    (dist / evidence.SBOM).write_text(json.dumps(bom))
    _resum(dist)
    assert evidence.verify(dist) == [error]


@pytest.mark.parametrize(
    ("change", "error"),
    [
        (
            {"serialNumber": "1234"},
            "sbom.cdx.json has no urn:uuid serialNumber, which actions/attest requires",
        ),
        ({"metadata": None}, "sbom.cdx.json does not describe sumo-qa {version}"),
        ({"components": None}, "sbom.cdx.json components is not a list"),
    ],
    ids=["non-uuid-serial-number", "null-metadata", "null-components"],
)
def test_malformed_sbom_fails(dist: Path, change: dict, error: str) -> None:
    """The real SBOM with one key broken fails with a named error, never a
    traceback."""
    bom = json.loads((dist / evidence.SBOM).read_text())
    bom.update(change)
    (dist / evidence.SBOM).write_text(json.dumps(bom))
    _resum(dist)
    version = _wheel(dist).name.split("-")[1]
    assert evidence.verify(dist) == [error.format(version=version)]


def test_sbom_without_serial_number_fails(dist: Path) -> None:
    """actions/attest rejects a CycloneDX SBOM with no serialNumber, so the
    gate does too."""
    bom = json.loads((dist / evidence.SBOM).read_text())
    del bom["serialNumber"]
    (dist / evidence.SBOM).write_text(json.dumps(bom))
    _resum(dist)
    assert evidence.verify(dist) == [
        "sbom.cdx.json has no urn:uuid serialNumber, which actions/attest requires"
    ]


def test_sbom_for_other_package_fails(dist: Path) -> None:
    bom = json.loads((dist / evidence.SBOM).read_text())
    bom["metadata"]["component"]["name"] = "not-sumo-qa"
    bom["components"] = [c for c in bom["components"] if c.get("name") != "sumo-qa"]
    (dist / evidence.SBOM).write_text(json.dumps(bom))
    _resum(dist)
    version = _wheel(dist).name.split("-")[1]
    assert evidence.verify(dist) == [f"sbom.cdx.json does not describe sumo-qa {version}"]


def test_sbom_for_other_version_fails(dist: Path) -> None:
    bom = json.loads((dist / evidence.SBOM).read_text())
    bom["metadata"]["component"]["version"] = "0.0.1"
    (dist / evidence.SBOM).write_text(json.dumps(bom))
    _resum(dist)
    version = _wheel(dist).name.split("-")[1]
    assert evidence.verify(dist) == [f"sbom.cdx.json does not describe sumo-qa {version}"]


def test_build_info_gaps_fail(dist: Path) -> None:
    info = json.loads((dist / evidence.BUILD_INFO).read_text())
    info["python"] = {}
    info["build_environment"] = {"build": "1.0"}
    (dist / evidence.BUILD_INFO).write_text(json.dumps(info))
    _resum(dist)
    assert evidence.verify(dist, "0" * 40) == [
        f"build-info.json source commit is not {'0' * 40}",
        "build-info.json does not record the Python version",
        "build-info.json does not record hatchling",
    ]


@pytest.mark.parametrize("key", ["source", "python", "build_environment"])
def test_null_build_info_section_fails(dist: Path, key: str) -> None:
    info = json.loads((dist / evidence.BUILD_INFO).read_text())
    info[key] = None
    (dist / evidence.BUILD_INFO).write_text(json.dumps(info))
    _resum(dist)
    expected = {
        "source": [f"build-info.json source commit is not {COMMIT}"],
        "python": ["build-info.json does not record the Python version"],
        "build_environment": [
            "build-info.json does not record build",
            "build-info.json does not record hatchling",
        ],
    }[key]
    assert evidence.verify(dist, COMMIT) == expected


def test_sdist_version_mismatch_fails(dist: Path) -> None:
    sdist = next(dist.glob("*.tar.gz"))
    sdist.rename(dist / "sumo_qa-9.9.9.tar.gz")
    _resum(dist)
    errors = evidence.verify(dist)
    assert (
        errors[0] == f"sdist version 9.9.9 is not wheel version {_wheel(dist).name.split('-')[1]}"
    )


def test_extra_wheel_fails(dist: Path) -> None:
    (dist / "sumo_qa-0.0.1-py3-none-any.whl").write_bytes(b"other")
    assert evidence.verify(dist) == ["expected one wheel and one sdist, found 2 and 1"]


def test_cli_exit_codes(dist: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert evidence.main(["verify", str(dist), "--commit", COMMIT]) == 0
    assert "release evidence verified" in capsys.readouterr().out
    assert evidence.main(["verify", str(dist), "--commit", "0" * 40]) == 1
    assert "source commit is not" in capsys.readouterr().err
    (dist / evidence.SUMS).unlink()
    assert evidence.main(["record", str(dist)]) == 0
    assert (dist / evidence.SUMS).is_file()
