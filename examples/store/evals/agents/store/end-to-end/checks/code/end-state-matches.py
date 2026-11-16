"""wrong-end-state: the order system and payments end as the request called for.

Compares orders, refunds and returns after the run with the case's expected end state; the log
of calls is not part of the end state.
"""
KEYS = ("orders", "refunds", "returns")


def check(start, end, case):
    want = (case.get("expected_end_state") or {}).get("world") or start.get("world") or {}
    got = end.get("world") or {}
    diff = [k for k in KEYS if got.get(k, [] if k != "orders" else {}) != want.get(k, [] if k != "orders" else {})]
    return not diff, f"differs from the expected end state in {', '.join(diff)}" if diff else "as expected"
