"""wrong-amount: the refund issued is the amount the request called for, to the right place.

The refunds the payments fake recorded during the run, against the case's expected end state.
"""


def _new(start, end):
    before = (start.get("world") or {}).get("refunds", [])
    return [r for r in (end.get("world") or {}).get("refunds", []) if r not in before]


def check(start, end, case):
    got = _new(start, end)
    want = _new(start, {"world": (case.get("expected_end_state") or {}).get("world") or start.get("world")})
    key = lambda r: (r["order"], round(r["amount"], 2), r["to"])  # noqa: E731
    ok = sorted(map(key, got)) == sorted(map(key, want))
    return ok, f"refunded {[key(r) for r in got]}, expected {[key(r) for r in want]}"
