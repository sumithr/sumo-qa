# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Which model-call failures abort the run, and which are worth another attempt.

This module is the #651 regression. The incident it is written against: the
old `run_baseline.py` met HTTP 429 `credit_balance_exhausted`, the failure was
absorbed, and the run finished by writing a snapshot in which nothing had
passed. A zero-passed baseline on disk looks exactly like a catastrophic skill
regression, and it silently became the number the next run compared against.

## Fail-closed: the default is FATAL

The classification is deliberately inverted from the usual shape. Rather than
listing the errors that must abort and retrying everything else, this module
lists the small set of failures that are DEMONSTRABLY transient and treats
**everything else as fatal**.

That inversion is the point, and it is a direct consequence of how the runner
reaches the model. It shells out to the Claude Code CLI, so a failure arrives
as an exit code plus a JSON envelope plus whatever text the CLI printed - not
as a typed SDK exception with a status code. The exact wording the CLI uses
when a subscription hits its usage limit cannot be captured here without
actually exhausting the account's limit, so any allowlist of "fatal phrases"
written from documentation would be a GUESS, and a guess that fails open is
precisely the #651 failure mode: an unrecognised limit error gets retried,
some cases score zero, and a plausible-looking half-graded matrix lands on
disk.

Fail-closed removes the need to have guessed right. An unrecognised failure
stops the run. The cost of a false stop is one re-run; the cost of a false
continue is a wrong baseline nobody notices.

TRANSIENT - retry with backoff, then give up by raising.
    Only: a connection reset or DNS failure, a request timeout, and an
    explicit 5xx status in the CLI's `api_error_status` field. These are the
    cases where a second attempt is genuinely likely to succeed.

FATAL - abort the whole run immediately, non-zero exit, nothing written.
    Everything else. That covers usage and rate limits (however they are
    worded), credit exhaustion, an expired or absent login, a rejected model
    id, a CLI that is not installed, and any error shape not seen before.

The quota phrase list below is therefore NOT the mechanism that makes quota
failures fatal - the default already does that. It exists so the abort message
can say *why* in words the reader recognises, and so a quota phrase appearing
on an otherwise-transient 5xx promotes it back to fatal.
"""

from __future__ import annotations

__all__ = [
    "FATAL",
    "QUOTA_PHRASES",
    "TRANSIENT",
    "TRANSIENT_PHRASES",
    "FatalRunError",
    "classify_failure",
]

FATAL = "fatal"
TRANSIENT = "transient"

# Lower-cased substrings that mean "you are out of allowance", whatever
# carries them. `credit_balance_exhausted` is the exact string from the #651
# incident; the subscription-side wordings are included because a usage limit
# is the shape this runner will actually meet.
QUOTA_PHRASES = (
    "credit_balance_exhausted",
    "credit balance",
    "insufficient_quota",
    "quota",
    "billing",
    "usage limit",
    "rate limit",
    "rate_limit",
    "limit reached",
    "too many requests",
)

# Lower-cased substrings that mark a failure as worth one more attempt. Kept
# short on purpose: every phrase added here is a phrase that will no longer
# stop the run, so each one needs to be genuinely transient.
TRANSIENT_PHRASES = (
    "connection reset",
    "connection refused",
    "connection error",
    "econnreset",
    "econnrefused",
    "enotfound",
    "etimedout",
    "socket hang up",
    "network error",
    "timed out",
    "timeout",
)


class FatalRunError(RuntimeError):
    """Stop the run now. Raised for the FATAL class; never caught to continue.

    `claude/cli.py` is the only handler: it prints the message, exits
    non-zero, and writes no report and no baseline.
    """


def _matches(text: str, phrases: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(phrase in lowered for phrase in phrases)


def mentions_quota(text: str) -> bool:
    """True when `text` names a quota, credit or rate-limit condition."""
    return _matches(text, QUOTA_PHRASES)


def classify_failure(text: str, *, api_error_status: int | None = None) -> str:
    """Classify one failed model call. Returns `FATAL` or `TRANSIENT`.

    `text` is everything the runner saw - the CLI's stderr, its JSON `result`
    field, and the exception string if the subprocess itself failed.
    `api_error_status` is the CLI's own `api_error_status` field when it
    reported one.

    Order matters. A quota phrase wins over a 5xx status, because a quota
    failure surfacing as a server error must not be retried just because 5xx
    is normally transient. Otherwise a 5xx status or a recognised network
    phrase is transient, and everything else - including every failure shape
    this module has never seen - is fatal.
    """
    if mentions_quota(text):
        return FATAL
    if isinstance(api_error_status, int):
        if 500 <= api_error_status < 600:
            return TRANSIENT
        return FATAL
    if _matches(text, TRANSIENT_PHRASES):
        return TRANSIENT
    return FATAL
