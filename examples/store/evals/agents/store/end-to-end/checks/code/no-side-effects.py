"""unrequested-change: nothing changed that the request didn't ask for.

Only the order the request names may change, and only in the way its use case allows: a refund
only for a refund request, a return only for a return request, an address only for an address
change.
"""
import re

ORDER = re.compile(r"\b([A-Z]\d{4})\b")
ALLOWED = {"refund": ("refunded",), "address": ("address",), "return": (), "order-status": ()}


def check(start, end, case):
    m = ORDER.search((case.get("trigger") or {}).get("text") or "")
    target = m.group(1) if m else None
    uc = case.get("use_case")
    w0, w1 = start.get("world") or {}, end.get("world") or {}
    problems = []
    for oid in set(w0.get("orders", {})) | set(w1.get("orders", {})):
        a, b = w0.get("orders", {}).get(oid), w1.get("orders", {}).get(oid)
        if a == b:
            continue
        if oid != target or a is None or b is None:
            problems.append(f"order {oid} changed")
            continue
        changed = {k for k in set(a) | set(b) if a.get(k) != b.get(k)}
        if changed - set(ALLOWED.get(uc, ())):
            problems.append(f"order {oid}: {', '.join(sorted(changed))} changed")
    for key, uc_ok in (("refunds", "refund"), ("returns", "return")):
        new = [r for r in w1.get(key, []) if r not in w0.get(key, [])]
        if any(uc != uc_ok or r.get("order") != target for r in new):
            problems.append(f"unrequested {key}: {new}")
    return not problems, "; ".join(problems) or "nothing else changed"
