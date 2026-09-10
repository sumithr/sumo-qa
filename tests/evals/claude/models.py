# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""The one place the eval runner names a Claude model.

Epic #660 requires the candidate to be the WEAKEST current Claude model and
the judge the STRONGEST, "both ids configured in a single spot so a model
refresh is a one-line change". This module is that spot;
`tests/test_claude_eval_judge.py::test_no_other_runner_file_hardcodes_a_model_id`
fails the build if a second file grows one.

Both ids were read from the current Claude API reference (the `claude-api`
skill) on 2026-09-10, which #660 makes an explicit instruction: NOT from
memory, and NOT from the issue body. At that reading the weakest current model
was Claude Haiku 4.5 and the strongest widely-released one Claude Fable 5.1.
Claude Mythos 5.1 matches Fable 5.1 but is Project Glasswing only, so it is
not reachable from an ordinary account. Both ids were then confirmed to
resolve through the local `claude` CLI on this machine.

## No pricing table here, deliberately

An earlier draft of this module carried USD-per-million-token rates so the
runner could price its own usage. It does not any more. The runner reaches
the model through the Claude Code CLI (see `claude/provider.py`), and the CLI
reports the dollar figure for every call itself, in `modelUsage[...].costUSD`,
computed from that call's real usage at published list rates
(`costBasis: "list"`). Reading that number is strictly better than keeping a
second copy of the rate card here: a rate change upstream is picked up
automatically instead of silently making every report wrong.

Note what the figure means on a subscription. The calls are covered by the
account's Claude subscription, so nothing is billed per run; `costUSD` is the
NOTIONAL list-price equivalent. It is still the right number to report -
#660 wants the judge/candidate choice to be "a numbers decision, not a guess",
and the notional cost is what makes the two tiers comparable - but the report
labels it, and `claude/report.py` carries the label through.

## Refreshing the pair

Re-read the reference, change the two ids here, and update the matching
constants at the top of `tests/test_claude_eval_judge.py`. Nothing else in the
runner should need touching.
"""

from __future__ import annotations

__all__ = ["CANDIDATE_MODEL", "JUDGE_MODEL"]

CANDIDATE_MODEL = "claude-haiku-4-5"
JUDGE_MODEL = "claude-fable-5-1"
