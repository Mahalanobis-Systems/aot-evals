"""wrong-reply: the reply says what the payments system did.

A refund issued is named with its amount; when none was, the reply says why; a handoff with no
order number asks for one.
"""
REFUSAL = ("can't", "cannot", "couldn't", "isn't", "hasn't", "already", "past the", "not ", "none of")


def check(start, end, case):
    reply = (end.get("output") or "")
    oid = (case.get("inputs") or {}).get("order_id")
    new = [r for r in (end.get("world") or {}).get("refunds", []) if r not in (start.get("world") or {}).get("refunds", [])]
    if new:
        amount = f"${sum(r['amount'] for r in new):.2f}"
        return amount in reply, f"refunded {amount}; the reply {'says so' if amount in reply else 'does not'}"
    if not oid:
        ok = "order number" in reply.lower()
        return ok, "asks for the order number" if ok else "no order number, and the reply doesn't ask for one"
    ok = any(w in reply.lower() for w in REFUSAL)
    return ok, "no refund; the reply " + ("says why" if ok else "does not say why")
