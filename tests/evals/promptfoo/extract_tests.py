#!/usr/bin/env python3
# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Extract user_prompt-only TestCase array from a gen.yaml into a bare YAML list.

After `promptfoo generate dataset --write -c <skill>.gen.yaml`, the gen.yaml
accumulates new test cases (potentially with the generator fabricating extra
vars despite our --instructions). This post-processor strips all vars except
user_prompt and writes the cleaned tests as a bare YAML list - the shape
promptfoo's `tests: file://...` consumes when inlined into a main eval config.

Usage:
    python tests/evals/promptfoo/extract_tests.py <gen.yaml> <output.yaml>
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__)
        return 2
    gen_path = Path(argv[1])
    out_path = Path(argv[2])
    gen_config = yaml.safe_load(gen_path.read_text(encoding="utf-8")) or {}
    tests = gen_config.get("tests", [])

    clean: list[dict] = []
    for t in tests:
        vars_block = (t or {}).get("vars", {}) or {}
        user_prompt = vars_block.get("user_prompt")
        if not user_prompt:
            continue
        clean.append(
            {
                "description": t.get("description") or "",
                "vars": {"user_prompt": user_prompt},
            }
        )

    out_path.write_text(yaml.safe_dump(clean, sort_keys=False), encoding="utf-8")
    print(f"wrote {len(clean)} tests to {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
