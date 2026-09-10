# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Offline input-token estimate for the dry run.

Slice 1 makes no API call, so it has no tokenizer and no usage report. The
estimate below is the standard character-based approximation (about four
characters per token for English prose), rounded up, which is enough for the
dry run's job: showing the shape and relative cost of the matrix before any
spend. It is an ESTIMATE and is labelled as one wherever it is printed.

Slice 2 (#662) reports real input/output token counts from the API response;
when it lands, the dry run keeps this estimate and the live run reports the
measured figure, so the two are never confused.
"""

from __future__ import annotations

import math

__all__ = ["CHARS_PER_TOKEN", "ESTIMATE_METHOD", "estimate_tokens"]

CHARS_PER_TOKEN = 4
ESTIMATE_METHOD = (
    "offline character-based estimate: ceil(len(text) / 4), the common "
    "approximation for English prose. No tokenizer, no network. Slice 2 "
    "replaces it with the API's reported usage for live runs."
)


def estimate_tokens(text: str) -> int:
    """Approximate the input tokens `text` would cost."""
    if not text:
        return 0
    return math.ceil(len(text) / CHARS_PER_TOKEN)
