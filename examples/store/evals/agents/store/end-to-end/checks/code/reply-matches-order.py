"""wrong-answer: the reply says what the order system holds, and what it did.

Read from the order system after the run (the end world), never from the agent's own claims: an
order-status reply names the arrival date (or the delivery date); a reply about a change names
what changed; when nothing changed it says why; a request with no order number asks for one.
"""
import re

ORDER = re.compile(r"\b([A-Z]\d{4})\b")
REFUSAL = ("can't", "cannot", "couldn't", "isn't", "hasn't", "already", "past the", "not ")


def check(start, end, case):
    text = (case.get("trigger") or {}).get("text") or ""
    reply = end.get("output") or ""
    m = ORDER.search(text)
    if not m:
        ok = "order number" in reply.lower()
        return ok, "asks for the order number" if ok else "no order number given, and the reply doesn't ask for one"
    oid = m.group(1)
    before = (start.get("world") or {}).get("orders", {}).get(oid)
    after = (end.get("world") or {}).get("orders", {}).get(oid)
    if after is None:
        ok = oid in reply and any(w in reply.lower() for w in REFUSAL)
        return ok, f"order {oid} doesn't exist; the reply {'says so' if ok else 'does not say so'}"
    uc = case.get("use_case")
    if uc == "order-status":
        want = after["delivered"] if after["status"] == "delivered" else after["eta"]
        return want in reply, f"reply {'names' if want in reply else 'does not name'} {want}"
    new_refunds = [r for r in (end.get("world") or {}).get("refunds", [])
                   if r not in (start.get("world") or {}).get("refunds", []) and r["order"] == oid]
    new_returns = [r for r in (end.get("world") or {}).get("returns", [])
                   if r not in (start.get("world") or {}).get("returns", []) and r["order"] == oid]
    moved = before is not None and before.get("address") != after.get("address")
    if new_refunds:
        amount = f"${sum(r['amount'] for r in new_refunds):.2f}"
        return amount in reply, f"refunded {amount}; the reply {'says so' if amount in reply else 'does not'}"
    if new_returns:
        ok = "return" in reply.lower() and not any(w in reply.lower() for w in REFUSAL)
        return ok, "a return was opened; the reply " + ("says so" if ok else "does not say so")
    if moved:
        ok = after["address"] in reply
        return ok, f"the address changed; the reply {'names' if ok else 'does not name'} it"
    ok = any(w in reply.lower() for w in REFUSAL)
    return ok, "nothing changed; the reply " + ("says why" if ok else "does not say why")
