"""Why an attempt ended, and whether its result may be scored.

An agent may report one of these itself (`outcome` in its stdout); the runner assigns the rest
(timeouts, unparseable output). Only `ok` is scored for correctness. Every other code is plane-B data: kept,
counted, never scored as a correctness failure and never dropped (docs/method.md §2.1, G13).
"""

from __future__ import annotations

from enum import StrEnum


class Outcome(StrEnum):
    OK = "ok"
    MODEL_DISABLED = "model_disabled"
    AUTH_ERROR = "auth_error"
    RATE_LIMITED = "rate_limited"
    BUDGET_EXCEEDED = "budget_exceeded"
    TIMEOUT = "timeout"
    PROVIDER_ERROR = "provider_error"
    NO_OUTPUT = "no_output"
    CLI_MISSING = "cli_missing"
    UNPARSEABLE = "unparseable"

    @property
    def scorable(self) -> bool:
        return self is Outcome.OK

    @property
    def retryable(self) -> bool:
        return self in _RETRYABLE


_RETRYABLE = frozenset(
    {
        Outcome.RATE_LIMITED,
        Outcome.TIMEOUT,
        Outcome.PROVIDER_ERROR,
        Outcome.NO_OUTPUT,
        Outcome.UNPARSEABLE,
    }
)

CODES = tuple(o.value for o in Outcome)
