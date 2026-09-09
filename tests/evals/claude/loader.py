# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Loader for the existing promptfoo eval configs.

Slice 1 of #660 deliberately reads the promptfoo YAML schema as-is rather
than hand-converting the matrix: 63 configs converted by hand would be 63
chances to change a scenario while claiming to preserve it, and parity
(slice 3) is only meaningful if both runners read the same source of truth.

What the loader reproduces, because the configs depend on it:

* `file://` vars, resolved relative to the CONFIG'S OWN directory (paths such
  as `file://../../../skills/<skill>/SKILL.md` escape it by design).
* `disableVarExpansion`, at the top level or under `defaultTest.options`.
* `defaultTest.options.provider` / `.rubricPrompt` judge overrides, carried
  onto every parsed rubric.
* `prompts[].label` (the `A0 - ...` / `A1 - ...` strings the A/B contract
  keys on) and `prompts[].raw` with `{{var}}` interpolation.
* per-test `assert:` entries, which APPEND to the `defaultTest` ones.
* per-test `prompts:` label restriction.
* `tests: file://<include>.yaml`. Two configs point at
  `*.generated-tests.yaml`, which is gitignored and absent from a fresh
  clone; a missing include is recorded as a warning, never an error, so the
  matrix still loads end to end.
"""

from __future__ import annotations

import fnmatch
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from claude.assertions import parse_assertion
from claude.templating import expand_var_matrix, render

__all__ = [
    "EvalCase",
    "EvalConfig",
    "Prompt",
    "PROMPTFOO_DIR",
    "REPO_ROOT",
    "TestSpec",
    "build_cases",
    "discover_configs",
    "load_all_configs",
    "load_config",
    "resolve_var_value",
]

REPO_ROOT = Path(__file__).resolve().parents[3]
PROMPTFOO_DIR = REPO_ROOT / "tests" / "evals" / "promptfoo"

_FILE_URL = "file://"
_SKILL_PREFIX = "sumo-qa-"


@dataclass(frozen=True)
class Prompt:
    label: str
    raw: str


@dataclass(frozen=True)
class TestSpec:
    description: str
    vars: dict[str, Any]
    assertions: tuple[Any, ...] = ()
    prompt_labels: tuple[str, ...] | None = None


@dataclass(frozen=True)
class EvalCase:
    """One fully-resolved (prompt_label, rendered_prompt, assertions) tuple."""

    config_path: Path
    prompt_label: str
    rendered_prompt: str
    assertions: tuple[Any, ...]
    vars: dict[str, Any]
    description: str = ""


@dataclass
class EvalConfig:
    path: Path
    description: str = ""
    providers: Any = None
    prompts: list[Prompt] = field(default_factory=list)
    default_vars: dict[str, Any] = field(default_factory=dict)
    default_assertions: list[Any] = field(default_factory=list)
    tests: list[TestSpec] = field(default_factory=list)
    disable_var_expansion: bool = False
    rubric_prompt: str | None = None
    judge_provider: Any = None
    warnings: list[str] = field(default_factory=list)

    @property
    def is_ab(self) -> bool:
        """A/B control config (`A0`/`A1` arms against the current skill)."""
        return self.path.name.endswith(".ab.yaml")

    def all_assertions(self) -> list[Any]:
        """Default asserts plus every per-test assert, in config order."""
        found = list(self.default_assertions)
        for test in self.tests:
            found.extend(test.assertions)
        return found


def resolve_var_value(value: Any, base_dir: Path) -> Any:
    """Resolve one var value, reading `file://` targets from disk.

    The path is resolved against `base_dir` (the config's own directory), NOT
    the process cwd - that is the whole contract, since every skill body in
    the matrix is loaded through `file://../../../skills/...`.
    """
    if not isinstance(value, str) or not value.startswith(_FILE_URL):
        return value
    target = (base_dir / value[len(_FILE_URL) :]).resolve()
    if not target.is_file():
        raise FileNotFoundError(f"{value} does not resolve to a file (looked in {target})")
    return target.read_text(encoding="utf-8")


def _resolve_vars(raw: Mapping[str, Any] | None, base_dir: Path) -> dict[str, Any]:
    return {key: resolve_var_value(val, base_dir) for key, val in (raw or {}).items()}


def _parse_prompts(raw: Iterable[Any] | None) -> list[Prompt]:
    """Prompts are either bare template strings or `{label, raw}` mappings.

    A bare string has no label in promptfoo either; a positional label keeps
    the runner's `(prompt_label, ...)` tuple total without inventing a name
    that could collide with a real `A0`/`A1` arm.
    """
    prompts: list[Prompt] = []
    for index, item in enumerate(raw or []):
        if isinstance(item, Mapping):
            prompts.append(Prompt(label=str(item["label"]), raw=str(item["raw"])))
        else:
            prompts.append(Prompt(label=f"prompt[{index}]", raw=str(item)))
    return prompts


def _expand_test_includes(
    raw_tests: Any, base_dir: Path, warnings: list[str]
) -> list[Mapping[str, Any]]:
    """Flatten `tests:` into a list of test mappings.

    promptfoo accepts the key as a `file://` string, as a list of test
    mappings, or as a list mixing mappings with `file://` includes - the two
    generator-backed configs use the last form. A missing include (the
    `*.generated-tests.yaml` files are gitignored, so absent from a fresh
    clone) is recorded as a warning and contributes no tests, rather than
    taking the whole matrix load down.
    """
    entries = [raw_tests] if isinstance(raw_tests, str) else list(raw_tests or [])
    expanded: list[Mapping[str, Any]] = []
    for entry in entries:
        if isinstance(entry, str) and entry.startswith(_FILE_URL):
            include = (base_dir / entry[len(_FILE_URL) :]).resolve()
            if include.is_file():
                loaded = yaml.safe_load(include.read_text(encoding="utf-8")) or []
                expanded.extend(loaded)
            else:
                warnings.append(
                    f"tests include {entry} is absent (looked in {include}); "
                    "it contributes 0 tests to this config"
                )
            continue
        expanded.append(entry)
    return expanded


def load_config(path: Path) -> EvalConfig:
    """Load and fully resolve one promptfoo config."""
    path = Path(path)
    base_dir = path.parent
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    warnings: list[str] = []

    default_test = data.get("defaultTest") or {}
    options = default_test.get("options") or {}
    # promptfoo honours either placement; the .ab.yaml configs use the
    # top-level key and the rest use options, so both have to be read.
    disable_var_expansion = bool(
        data.get("disableVarExpansion") or options.get("disableVarExpansion")
    )
    rubric_prompt = options.get("rubricPrompt")
    judge_provider = options.get("provider")

    def _assertions(raw: Iterable[Mapping[str, Any]] | None) -> tuple[Any, ...]:
        return tuple(
            parse_assertion(
                entry,
                base_dir,
                rubric_prompt=rubric_prompt,
                judge_provider=judge_provider,
                config_path=path,
            )
            for entry in (raw or [])
        )

    raw_tests = _expand_test_includes(data.get("tests"), base_dir, warnings)

    tests: list[TestSpec] = []
    for entry in raw_tests:
        prompt_labels = entry.get("prompts")
        tests.append(
            TestSpec(
                description=str(entry.get("description") or ""),
                vars=_resolve_vars(entry.get("vars"), base_dir),
                assertions=_assertions(entry.get("assert")),
                prompt_labels=tuple(prompt_labels) if prompt_labels else None,
            )
        )

    return EvalConfig(
        path=path,
        description=str(data.get("description") or ""),
        providers=data.get("providers"),
        prompts=_parse_prompts(data.get("prompts")),
        default_vars=_resolve_vars(default_test.get("vars"), base_dir),
        default_assertions=list(_assertions(default_test.get("assert"))),
        tests=tests,
        disable_var_expansion=disable_var_expansion,
        rubric_prompt=rubric_prompt,
        judge_provider=judge_provider,
        warnings=warnings,
    )


def discover_configs(
    directory: Path = PROMPTFOO_DIR,
    *,
    skill: str | None = None,
    pattern: str | None = None,
) -> list[Path]:
    """Select configs, optionally scoped by skill name and/or filename glob.

    `skill` accepts either the bare name (`reviewing-before-merge`) or the
    full skill directory name (`sumo-qa-reviewing-before-merge`), and picks up
    every variant config for that skill - the base config, its `.ab.yaml`
    control, and any `-<variant>.yaml` sibling.
    """
    paths = sorted(Path(directory).glob("*.yaml"))
    if pattern:
        paths = [p for p in paths if fnmatch.fnmatch(p.name, pattern)]
    if skill:
        bare = skill[len(_SKILL_PREFIX) :] if skill.startswith(_SKILL_PREFIX) else skill
        prefix = f"skill-{bare}"
        paths = [
            p for p in paths if p.name.startswith(f"{prefix}.") or p.name.startswith(f"{prefix}-")
        ]
    return paths


def load_all_configs(
    directory: Path = PROMPTFOO_DIR,
    *,
    skill: str | None = None,
    pattern: str | None = None,
) -> list[EvalConfig]:
    return [load_config(path) for path in discover_configs(directory, skill=skill, pattern=pattern)]


def build_cases(config: EvalConfig) -> list[EvalCase]:
    """Assemble every (prompt_label, rendered_prompt, assertions) tuple."""
    cases: list[EvalCase] = []
    for test in config.tests:
        merged = {**config.default_vars, **test.vars}
        rows = expand_var_matrix(merged, disable_var_expansion=config.disable_var_expansion)
        prompts = (
            config.prompts
            if test.prompt_labels is None
            else [p for p in config.prompts if p.label in test.prompt_labels]
        )
        assertions = tuple(config.default_assertions) + tuple(test.assertions)
        for prompt in prompts:
            for row in rows:
                cases.append(
                    EvalCase(
                        config_path=config.path,
                        prompt_label=prompt.label,
                        rendered_prompt=render(prompt.raw, row),
                        assertions=assertions,
                        vars=row,
                        description=test.description,
                    )
                )
    return cases
