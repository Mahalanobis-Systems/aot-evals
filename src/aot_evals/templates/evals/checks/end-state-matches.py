"""Code check: the world ends exactly as the case expects (`aot-evals build` writes this).

The lightest check there is, so a first pass reaches a baseline without writing check code: it
compares what `observe` printed after the run with the case's `expected_end_state.world`. Any
sequence of actions that reaches that state passes; it never reads the agent's reply.

It is strict. Where the world holds values a correct run can't reproduce (ids, timestamps, the
order of a list), replace it with checks that look at what matters, one per failure mode.
"""


def check(start, end, case):
    want = (case.get("expected_end_state") or {}).get("world")
    if want is None:
        return True, "the case states no expected world; nothing to compare (add one, or another check)"
    got = end.get("world")
    if got == want:
        return True, "the world ends as expected"
    if isinstance(want, dict) and isinstance(got, dict):
        keys = sorted(k for k in set(want) | set(got) if want.get(k) != got.get(k))
        return False, f"differs from the expected end state at: {', '.join(map(str, keys[:8]))}"
    return False, "differs from the expected end state"
