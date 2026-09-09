# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Nunjucks-subset template rendering for the offline Claude eval runner.

promptfoo renders `prompts[].raw` and rubric bodies through nunjucks. The
live matrix uses exactly two constructs:

* `{{ var }}` interpolation (with or without inner spaces), and
* `{% for item in list %}...{% endfor %}` over a list-valued var.

That subset is implemented here rather than pulling a Jinja dependency in:
Jinja's `{{ list }}` renders a Python `repr` (`['a', 'b']`) where nunjucks
renders JavaScript's `String(array)` (`a,b`), and its boolean rendering is
`True`/`False` rather than `true`/`false`. Reproducing promptfoo's output
byte-for-byte is the whole point of the port, so the value-to-string rules
below mirror JavaScript, not Python.

Unknown vars render as the empty string, which is what nunjucks does with an
undefined value; braces that are not a placeholder are left untouched.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

__all__ = ["render", "to_text", "expand_var_matrix"]

_PLACEHOLDER = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")
_FOR_BLOCK = re.compile(
    r"\{%\s*for\s+([A-Za-z_][A-Za-z0-9_]*)\s+in\s+([A-Za-z_][A-Za-z0-9_]*)\s*%\}"
    r"(.*?)"
    r"\{%\s*endfor\s*%\}",
    re.DOTALL,
)


def to_text(value: Any) -> str:
    """Render one var value the way JavaScript's `String()` would.

    A list joins on `,` (no space), booleans are lowercase, `None` is empty.
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple)):
        return ",".join(to_text(item) for item in value)
    return str(value)


def render(template: str, variables: Mapping[str, Any]) -> str:
    """Render `template` against `variables`.

    For-loops are expanded first so that the loop variable is in scope for the
    `{{ item }}` placeholders inside the body.
    """

    def _expand_loop(match: re.Match[str]) -> str:
        loop_var, source_var, body = match.group(1), match.group(2), match.group(3)
        items = variables.get(source_var)
        if items is None:
            return ""
        if not isinstance(items, (list, tuple)):
            items = [items]
        rendered = []
        for item in items:
            scope = dict(variables)
            scope[loop_var] = item
            rendered.append(render(body, scope))
        return "".join(rendered)

    expanded = _FOR_BLOCK.sub(_expand_loop, template)
    return _PLACEHOLDER.sub(lambda m: to_text(variables.get(m.group(1))), expanded)


def expand_var_matrix(
    variables: Mapping[str, Any], *, disable_var_expansion: bool
) -> list[dict[str, Any]]:
    """Reproduce promptfoo's list-var expansion.

    With expansion ON (promptfoo's default) a list-valued var produces one
    test per item, across the cartesian product of every list-valued var.
    With `disableVarExpansion` set, the list reaches the template intact so
    a `{% for %}` block can iterate it. Every config in the live matrix sets
    the flag, which is why the anti-pattern lists survive into the rubrics.
    """
    if disable_var_expansion:
        return [dict(variables)]

    rows: list[dict[str, Any]] = [{}]
    for name, value in variables.items():
        if isinstance(value, list):
            rows = [{**row, name: item} for row in rows for item in value]
        else:
            rows = [{**row, name: value} for row in rows]
    return rows
