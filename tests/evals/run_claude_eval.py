#!/usr/bin/env python3
# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Entry point for the offline Claude eval runner.

A script rather than a console entry point: the eval harness is not part of
the shipped wheel, and `tests/evals/` needs to stay movable in one piece.
Putting the sys.path bootstrap here keeps the package itself import-clean.

    uv run python tests/evals/run_claude_eval.py --dry-run
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from claude.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
