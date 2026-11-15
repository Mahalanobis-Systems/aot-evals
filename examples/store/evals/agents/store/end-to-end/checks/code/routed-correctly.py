"""wrong-route: a refund request is handed to the refund subagent, and nothing else is.

Read from the log of calls the fakes keep (env/store_world.py), not from the reply.
"""


def check(start, end, case):
    log = (end.get("world") or {}).get("log", [])
    handed = any(e.get("tool") == "handoff" and e.get("to") == "refund-subagent" for e in log)
    want = case.get("use_case") == "refund"
    if handed == want:
        return True, "handed to the refund subagent" if handed else "not a refund: kept by the orchestrator"
    return False, "a refund request the orchestrator never handed off" if want else "handed to the refund subagent, but it isn't a refund"
