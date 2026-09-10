# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Loader for the existing promptfoo eval configs.

Slice 1 of #660 deliberately reads the promptfoo YAML schema as-is rather
than hand-converting the matrix: 61 configs converted by hand would be 61
chances to change a scenario while claiming to preserve it, and parity
(slice 3) is only meaningful if both runners read the same source of truth.

What the loader reproduces, because the configs depend on it:

* the SELECTION: `skill-*.yaml` minus `*.gen.yaml` (generator seeds, whose
  own headers say they are not for running evals) minus
  `*.generated-tests.yaml` (gitignored `tests:` include payloads - bare YAML
  lists, not configs). 61 configs. This is DELIBERATELY STRICTER than
  `npm run eval:all`, which globs `skill-*.yaml` and skips only `*.gen.yaml`:
  its own glob would hand `promptfoo eval -c` a generated-tests include file,
  which is not a config, and promptfoo would fail on it. The shell script has
  a latent bug; being bug-compatible with it is not parity.
* `file://` vars, resolved relative to the CONFIG'S OWN directory (paths such
  as `file://../../../skills/<skill>/SKILL.md` escape it by design), with
  promptfoo's own value handling: a `.yaml`/`.yml` target is injected as
  `JSON.stringify(loadYaml(...))` (compact, document key order), every other
  target as trimmed raw text, and every string var then loses ONE terminal
  newline - `renderPrompt` in promptfoo 0.121.20.
* `llm-rubric` assertion VALUES rendered against the resolved case vars, the
  way `runAssertion` does before grading. The judge-time `rubricPrompt` is
  deliberately left alone: its `{{rubric}}`/`{{output}}` are filled by the
  grader in slice 2, not here.
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

import datetime
import fnmatch
import json
import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import yaml

from claude.assertions import JS_WHITESPACE, RubricAssertion, parse_assertion
from claude.templating import expand_var_matrix, render

__all__ = [
    "EvalCase",
    "EvalConfig",
    "MalformedConfigError",
    "Prompt",
    "PROMPTFOO_DIR",
    "REPO_ROOT",
    "TestSpec",
    "build_cases",
    "discover_configs",
    "load_all_configs",
    "load_config",
    "resolve_var_value",
    "strip_terminal_newline",
]

REPO_ROOT = Path(__file__).resolve().parents[3]
PROMPTFOO_DIR = REPO_ROOT / "tests" / "evals" / "promptfoo"

_FILE_URL = "file://"
_SKILL_PREFIX = "sumo-qa-"

# `skill-*.yaml` minus `*.gen.yaml` (generator seeds) minus
# `*.generated-tests.yaml` (gitignored `tests:` include payloads - bare YAML
# lists, not configs). Stricter than `npm run eval:all`, which excludes only
# `*.gen.yaml` and would therefore feed promptfoo a non-config.
_CONFIG_GLOB = "skill-*.yaml"
_NOT_A_CONFIG = (".gen.yaml", ".generated-tests.yaml")

# promptfoo reads a `file://` var whose target ends `.yaml`/`.yml` through
# js-yaml and injects `JSON.stringify(...)` of the result.
_YAML_SUFFIXES = (".yaml", ".yml")

# `String.prototype.trim` strips WhiteSpace + LineTerminator, which is NOT
# Python's `str.strip()` set: JS adds U+FEFF and omits U+001C-U+001F and
# U+0085. It is the same set JavaScript's `\s` matches, so it is defined once,
# in `assertions.py`, where the regex ports splice it into character classes.
_JS_WHITESPACE = JS_WHITESPACE


class MalformedConfigError(ValueError):
    """A YAML file whose top level is not a mapping, so it is not a config."""


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


def _js_date_to_json(moment: datetime.datetime) -> str:
    """`Date#toJSON`: UTC, milliseconds, `Z` suffix."""
    utc = moment if moment.tzinfo is None else moment.astimezone(datetime.timezone.utc)
    return f"{utc.strftime('%Y-%m-%dT%H:%M:%S')}.{utc.microsecond // 1000:03d}Z"


def _json_default(value: Any) -> str:
    """Serialise what `JSON.stringify` can but `json.dumps` cannot.

    js-yaml resolves a timestamp scalar to a `Date`, which `JSON.stringify`
    writes as an ISO string; PyYAML resolves it to `datetime`, which
    `json.dumps` refuses. Anything else is a genuine schema divergence and
    must say so rather than serialise to something promptfoo never emits.
    """
    if isinstance(value, datetime.datetime):
        return _js_date_to_json(value)
    if isinstance(value, datetime.date):
        return _js_date_to_json(datetime.datetime(value.year, value.month, value.day))
    raise TypeError(
        f"cannot serialise a YAML {type(value).__name__} the way JSON.stringify would; "
        "the var would not match what promptfoo injects"
    )


def _null_non_finite(value: Any) -> Any:
    """Replace every non-finite float with `None`, the way `JSON.stringify` does.

    js-yaml resolves `.nan`, `.inf` and `-.inf` to `NaN`/`Infinity`, and
    `JSON.stringify` writes all three as `null` (JSON has no literal for
    them). Python's `json.dumps` instead emits the non-standard `NaN`,
    `Infinity` and `-Infinity` tokens, which promptfoo would never inject.

    This has to be a WALK, not a `default=` hook: a float is already
    JSON-serialisable, so `default=` never fires for one.
    """
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, Mapping):
        return {key: _null_non_finite(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_null_non_finite(item) for item in value]
    return value


def _json_stringify(value: Any) -> str:
    """`JSON.stringify(value)`: compact, document key order, literal Unicode."""
    return json.dumps(
        _null_non_finite(value),
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
        default=_json_default,
    )


def resolve_var_value(value: Any, base_dir: Path) -> Any:
    """Resolve one var value, reading `file://` targets from disk.

    The path is resolved against `base_dir` (the config's own directory), NOT
    the process cwd - that is the whole contract, since every skill body in
    the matrix is loaded through `file://../../../skills/...`.

    A `.yaml`/`.yml` target is PARSED and re-emitted as compact JSON, because
    that is what promptfoo does (`vars[varName] =
    JSON.stringify(loadYaml(readFile(...)))`); every other target is raw text
    with JavaScript's `.trim()` applied, again matching `renderPrompt`.
    """
    if not isinstance(value, str) or not value.startswith(_FILE_URL):
        return value
    target = (base_dir / value[len(_FILE_URL) :]).resolve()
    if not target.is_file():
        raise FileNotFoundError(f"{value} does not resolve to a file (looked in {target})")
    text = target.read_text(encoding="utf-8")
    if target.name.endswith(_YAML_SUFFIXES):
        return _json_stringify(yaml.safe_load(text))
    return text.strip(_JS_WHITESPACE)


def strip_terminal_newline(variables: Mapping[str, Any]) -> dict[str, Any]:
    """Drop ONE terminal newline from every string var, as promptfoo does.

    `renderPrompt` runs `vars[key] = vars[key].replace(/\\n$/, '')` over every
    string var immediately before rendering - a single-newline chop, not a
    trim, so an inner blank line survives. It bites both file-backed vars
    (a `SKILL.md` ending in a newline) and the literal block scalars the
    seeds use for `ground_truth_context`.
    """
    return {
        key: value[:-1] if isinstance(value, str) and value.endswith("\n") else value
        for key, value in variables.items()
    }


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
    # No `or {}` here: it would run BEFORE the mapping check and turn every
    # falsy top level - `[]`, `false`, `0`, `""`, `null`, an empty file - into
    # a silently-empty config. An empty or falsy document is NOT a promptfoo
    # config: it carries no `prompts:` and no `providers:`, so promptfoo could
    # not run it either, and accepting it would let a truncated or clobbered
    # file sit in the matrix contributing zero cases while still being counted
    # as one - exactly the short read slice 3's parity claim must not have.
    # This is deliberately NOT the rule `_expand_test_includes` uses: there,
    # `or []` on an empty include is right, because an include legitimately
    # contributes zero tests and the CONFIG around it is still valid.
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, Mapping):
        described = "empty document" if data is None else type(data).__name__
        raise MalformedConfigError(
            f"{path.name} is not a promptfoo config: its top level is a "
            f"{described}, not a mapping (read from {path})"
        )
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


def _all_config_paths(directory: Path) -> list[Path]:
    """Every real config in `directory`, before any `skill`/`pattern` filter."""
    return sorted(
        p for p in Path(directory).glob(_CONFIG_GLOB) if not p.name.endswith(_NOT_A_CONFIG)
    )


def discover_configs(
    directory: Path = PROMPTFOO_DIR,
    *,
    skill: str | None = None,
    pattern: str | None = None,
) -> list[Path]:
    """Select configs, optionally scoped by skill name and/or filename glob.

    The base selection is `skill-*.yaml` minus `*.gen.yaml` (generator
    seeds) minus `*.generated-tests.yaml` (a `tests:` include payload - a bare
    YAML list - which would both inflate the count and blow up `load_config`).

    That last exclusion makes this selection deliberately STRICTER than
    `npm run eval:all`, whose glob skips only `*.gen.yaml` and so would pass
    `promptfoo eval -c` a generated-tests include file and fail on it. The
    runner is not bug-compatible with that; excluding non-configs is the
    correct behaviour, and the two selections agree on every real config.

    `skill` accepts either the bare name (`reviewing-before-merge`) or the
    full skill directory name (`sumo-qa-reviewing-before-merge`), and picks up
    every variant config for that skill - the base config, its `.ab.yaml`
    control, and any `-<variant>.yaml` sibling.

    It must NAME a config, though, not merely prefix one. Matching on the
    hyphen boundary alone let `reviewing` select the whole
    `reviewing-before-merge` family, so a mistyped or shell-truncated
    `--skill` produced a confident, non-empty, WRONG matrix rather than
    failing. A value that names no config selects nothing, which is the
    caller's unknown-skill path.
    """
    paths = _all_config_paths(directory)
    if pattern:
        paths = [p for p in paths if fnmatch.fnmatch(p.name, pattern)]
    if skill:
        bare = skill[len(_SKILL_PREFIX) :] if skill.startswith(_SKILL_PREFIX) else skill
        prefix = f"skill-{bare}"
        # The stem is the filename up to its first dot, so a config and its
        # `.ab.yaml` control contribute the same stem. Validate against the
        # unfiltered selection: a `pattern` narrowing the matrix must not
        # make an otherwise-real skill name look unknown.
        if prefix not in {p.name.split(".", 1)[0] for p in _all_config_paths(directory)}:
            return []
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


def _render_rubrics(assertions: tuple[Any, ...], variables: Mapping[str, Any]) -> tuple[Any, ...]:
    """Render every `llm-rubric` VALUE against this case's resolved vars.

    promptfoo does the same in `runAssertion`
    (`renderedValue = nunjucks.renderString(renderedValue, resolvedVars)`)
    before handing the rubric to the judge, and 65 of the 66 live rubrics
    carry `{{expected_shape}}` / `{% for ap in anti_patterns %}` syntax.

    `rubric_prompt` is pointedly NOT rendered here: its `{{rubric}}` and
    `{{output}}` are judge-time substitutions that `matchesLlmRubric` fills,
    and slice 2 (#662) owns them.
    """
    return tuple(
        replace(assertion, rubric=render(assertion.rubric, variables))
        if isinstance(assertion, RubricAssertion)
        else assertion
        for assertion in assertions
    )


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
        # Resolve each row once: the newline chop and the rubric rendering are
        # per-CASE-vars, not per-prompt, exactly as promptfoo orders them.
        resolved = [
            (row, _render_rubrics(assertions, row))
            for row in (strip_terminal_newline(r) for r in rows)
        ]
        for prompt in prompts:
            for row, row_assertions in resolved:
                cases.append(
                    EvalCase(
                        config_path=config.path,
                        prompt_label=prompt.label,
                        rendered_prompt=render(prompt.raw, row),
                        assertions=row_assertions,
                        vars=row,
                        description=test.description,
                    )
                )
    return cases
