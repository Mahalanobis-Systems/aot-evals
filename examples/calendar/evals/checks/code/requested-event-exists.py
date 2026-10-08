def check(start, end, case):
    want = case["inputs"]["event"]
    events = (end["world"] or {}).get("events", [])
    n = sum(1 for e in events if e == want)
    return n == 1, f"{n} matching event(s) for {want}"
