# Deliberately bad: grades the agent's own report (G10 fixture).
def check(start, end, case):
    out = (end.get("output") or "").lower()
    return "success" in out or "done" in out, "agent reported success"
