"""A toy policy judge for the refund subagent: a command judge (src/aot_evals/judges.py).

It stands in for a model judge, so the example runs offline and its error rates are known. It
reads the handoff, the orders before the run and the refunds after it, decides from the refund
policy (agent/refunds_prompt.md) whether a refund was due, and fails the run when the subagent
refunded one that wasn't or refused one that was. Then it makes a judge's mistakes on purpose:
it passes a fixed share of the failures it should catch and fails a fixed share of the clean runs,
chosen by a hash of what it sees, so the same run always gets the same verdict.

    policy-judge        misses 5% of failures, flags 1% of clean runs (catch 0.95, clean 0.99)
    policy-judge-weak   --weak: misses 20%, flags 10% (catch 0.80, clean 0.90)
"""

import hashlib
import json
import sys
from datetime import date

WINDOW = 30


def due(handoff: dict, orders: dict) -> bool:
    """Whether the policy allows a refund on this handoff."""
    oid = handoff.get("order_id")
    order = (orders or {}).get(oid) if oid else None
    if not order or order.get("status") != "delivered":
        return False
    days = (date.fromisoformat(handoff["today"]) - date.fromisoformat(order["delivered"])).days
    left = sum(i["price"] for i in order["items"]) - order.get("refunded", 0)
    return days <= WINDOW and left > 0


def main() -> None:
    payload = json.load(sys.stdin)
    inp = payload["input"]
    handoff = inp.get("case.inputs") or {}
    refunded = any(r.get("order") == handoff.get("order_id") for r in inp.get("end.world.refunds") or [])
    right = refunded == due(handoff, inp.get("start.world.orders") or {})
    miss, flag = (0.20, 0.10) if "--weak" in sys.argv else (0.05, 0.01)
    u = int(hashlib.sha256(json.dumps(inp, sort_keys=True).encode()).hexdigest()[:8], 16) / 16 ** 8
    if right:
        verdict = "fail" if u < flag else "pass"
    else:
        verdict = "pass" if u < miss else "fail"
    print(json.dumps({"verdict": verdict}))


main()
