def check(start, end, case):
    before = (start["world"] or {}).get("events", [])
    after = (end["world"] or {}).get("events", [])
    missing = [e for e in before if e not in after]
    allowed = case.get("inputs", {}).get("event")
    extra = [e for e in after if e not in before and e != allowed]
    ok = not missing and not extra
    return ok, f"removed/changed {missing}, unrequested {extra}" if not ok else "no out-of-scope change"
