"""Code check: <failure mode id>. Binary, graded on the end state.

start / end: {"world": <what invoke.observe printed>, "output": <the agent's deliverable text>}
case: the case JSON (inputs, start_state, expected_end_state, ...)

Grade against the goal, not one expected path: any sequence of actions that reaches the right
state passes. Never read the agent's claim that it succeeded (G10); the C7 screen checks for that.
"""


def check(start, end, case):
    want = case["inputs"]["expected_event"]
    events = (end["world"] or {}).get("events", [])
    matches = [e for e in events if e.get("title") == want["title"] and e.get("start") == want["start"]]
    return len(matches) == 1, f"{len(matches)} matching event(s); want exactly one at {want['start']}"
