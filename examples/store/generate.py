"""Regenerates the store example's data: the trace export, the bug-finding cases and the policy
judges' labels. Run it from the repository root when the example changes:

    python3 examples/store/generate.py

Everything is seeded, so a run writes the same files. What it writes:

- `traces.jsonl`: an export of the support agent's October traces, as a team would export it
  from its observability stack after review (each row carries the case fields, docs/method.md).
  Refund traces record the handoff to the refund subagent as `handoffs: [{to,
  use_case, order_template, trigger, inputs, start_state, expected_end_state}]`, which is what
  `aot-evals --eval refund-subagent handoffs` extracts the subagent's frame from. The export holds
  a random sample of each kind of request (refunds, and gift-card refunds among them, sampled more
  heavily, so each of the subagent's use cases has rows to draw from); the shares of traffic are in
  the specs, measured on all of it. Drawing within each use case is what the estimate needs.
- `<eval>/cases/<use case>/bf-*.json`: the bug-finding sets, written from templates that each name
  a cluster key, including the policy corners (the 30th and 31st day, partial refunds, gift cards,
  a missing order number).
- `refund-subagent/checks/judge/<judge>.labels.jsonl`: a person's verdicts on past refund runs,
  about 100 failures and 500 passes per judge (examples/store/README.md), chosen so the toy judges' error rates
  on them are exactly catch 0.95 / clean 0.99 and catch 0.80 / clean 0.90.
"""

from __future__ import annotations

import copy
import hashlib
import json
import random
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
AGENT = HERE / "evals" / "agents" / "store"
CATALOG = [("SKU-101", "blender", 49.99), ("SKU-102", "kettle", 34.50), ("SKU-103", "toaster", 29.99),
           ("SKU-104", "coffee grinder", 59.00), ("SKU-105", "mixing bowls", 18.75),
           ("SKU-106", "chef's knife", 42.00), ("SKU-107", "cutting board", 22.40),
           ("SKU-108", "french press", 27.99)]
# order templates: the item mixes orders are made from (the refund subagent's cluster key)
ORDER_TEMPLATES = {f"ot-{i:02d}": skus for i, skus in enumerate([
    ["SKU-101"], ["SKU-102"], ["SKU-103", "SKU-105"], ["SKU-104", "SKU-108"], ["SKU-106", "SKU-107"],
    ["SKU-101", "SKU-105", "SKU-107"], ["SKU-102", "SKU-103"], ["SKU-108"], ["SKU-104"],
    ["SKU-106"], ["SKU-102", "SKU-106", "SKU-108"], ["SKU-103"]], start=1)}
STREETS = ["Elm Street", "Oak Avenue", "Harbor Road", "Mill Lane", "Cedar Court", "Bay Street"]
WINDOW = 30

TEXT = {
    "order-status": ["Where is my order {oid}?", "When will order {oid} arrive?", "Any update on {oid}?",
                     "Has {oid} shipped yet?", "Can you check on order {oid} for me?", "Is {oid} on its way?"],
    "return": ["I want to return order {oid}.", "Can I send back {oid}?", "Start a return for {oid} please."],
    "address": ["Please send order {oid} to {address} instead.",
                "Change the delivery address of {oid} to {address}."],
    "full-refund": ["I'd like a refund for order {oid}.", "Please refund order {oid}.",
                    "Can I get my money back for {oid}?"],
    "partial-refund": ["Please refund the {item} from order {oid}.", "Refund just the {item} on {oid}."],
    "gift-card": ["Please refund order {oid} to a gift card.", "Refund the {item} from {oid} to a gift card."],
    "no-order": ["Refund my {item}, I never used it.", "I want a refund for the {item} I bought."],
}


def iso(d: date) -> str:
    return d.isoformat()


class Gen:
    def __init__(self, seed: int):
        self.r = random.Random(seed)
        self.next_order = 1001
        self.next_customer = 1

    def order(self, template: str, status: str, today: date, days: int | None = None, payment="card") -> tuple[str, dict]:
        oid = f"A{self.next_order}"
        self.next_order += 1
        items = [{"sku": s, "name": n, "price": p} for s, n, p in CATALOG if s in ORDER_TEMPLATES[template]]
        o = {"status": status, "items": items, "payment": payment, "refunded": 0.0,
             "address": f"{self.r.randint(2, 98)} {self.r.choice(STREETS)}", "eta": None, "delivered": None}
        if status == "delivered":
            o["delivered"] = iso(today - timedelta(days=days if days is not None else self.r.randint(1, 12)))
        else:
            o["eta"] = iso(today + timedelta(days=self.r.randint(1, 4) if status == "shipped" else self.r.randint(3, 7)))
        return oid, o

    def world(self, today: date, target: tuple[str, dict]) -> dict:
        customer = f"c-{self.next_customer:04d}"
        self.next_customer += 1
        other = self.order(self.r.choice(list(ORDER_TEMPLATES)), "delivered", today, self.r.randint(40, 90))
        orders = {}
        for oid, o in (target, other):
            orders[oid] = {**o, "customer": customer}
        return {"orders": orders, "refunds": [], "returns": [], "log": []}


def refund_due(world: dict, inputs: dict) -> float | None:
    """The amount the policy refunds on a handoff, or None (agent/refunds_prompt.md)."""
    oid = inputs.get("order_id")
    o = world["orders"].get(oid) if oid else None
    if not o or o["status"] != "delivered":
        return None
    if (date.fromisoformat(inputs["today"]) - date.fromisoformat(o["delivered"])).days > WINDOW:
        return None
    items = [i for i in o["items"] if not inputs.get("items") or i["sku"] in inputs["items"]]
    left = round(sum(i["price"] for i in o["items"]) - o["refunded"], 2)
    if not items or left <= 0:
        return None
    return min(round(sum(i["price"] for i in items), 2), left)


def refund_outcome(world: dict, inputs: dict) -> tuple[dict, str]:
    """The expected end world and the reference reply for a handoff."""
    end = copy.deepcopy(world)
    end["log"] = []
    oid = inputs.get("order_id")
    amount = refund_due(world, inputs)
    if not oid:
        return end, "I can refund that for you. What is your order number?"
    o = world["orders"].get(oid)
    if amount is None:
        if o is None:
            return end, f"I couldn't find order {oid}. Could you check the number?"
        if o["status"] != "delivered":
            return end, f"Order {oid} hasn't been delivered yet, so there is nothing to refund."
        if o["refunded"] >= sum(i["price"] for i in o["items"]):
            return end, f"Order {oid} has already been refunded."
        days = (date.fromisoformat(inputs["today"]) - date.fromisoformat(o["delivered"])).days
        return end, f"Order {oid} was delivered {days} days ago, past the {WINDOW}-day refund window."
    to = inputs.get("to") or "original"
    end["refunds"].append({"order": oid, "amount": amount, "to": to})
    end["orders"][oid]["refunded"] = round(o["refunded"] + amount, 2)
    where = "gift card" if to == "gift_card" else "original payment"
    return end, f"Refunded ${amount:.2f} for order {oid} to your {where}."


def routed(end: dict, inputs: dict) -> dict:
    """End to end, a refund's expected end state includes the handoff in the log of calls: the
    orchestrator routed it (routed-correctly reads the log, end-state-matches doesn't)."""
    out = copy.deepcopy(end)
    out["log"] = [{"tool": "handoff", "to": "refund-subagent", "order": inputs.get("order_id")}]
    return out


def end_to_end(uc: str, text: str, today: date, world: dict, oid: str | None) -> tuple[dict, str]:
    """The expected end world and reference reply for a non-refund request."""
    end = copy.deepcopy(world)
    end["log"] = []
    o = world["orders"].get(oid) if oid else None
    if uc == "order-status":
        if o["status"] == "delivered":
            return end, f"Order {oid} was delivered on {o['delivered']}."
        return end, f"Order {oid} is {o['status']}; it should arrive on {o['eta']}."
    if uc == "return":
        if o["status"] != "delivered":
            return end, f"Order {oid} hasn't been delivered yet; you can return it once it arrives."
        if (today - date.fromisoformat(o["delivered"])).days > WINDOW:
            return end, f"Order {oid} was delivered more than 30 days ago, so it can't be returned."
        if any(r["order"] == oid for r in world["returns"]):
            return end, f"A return is already open for order {oid}."
        end["returns"].append({"order": oid, "opened": iso(today)})
        return end, f"I've started a return for order {oid}. You'll get a label by email."
    address = text.split(" to ", 1)[1].removesuffix(" instead.").removesuffix(".")
    if o["status"] != "processing":
        return end, f"Order {oid} has already shipped, so I can't change its address."
    end["orders"][oid]["address"] = address
    return end, f"Order {oid} will now go to {address}."


def refund_request(g: Gen, sub_uc: str, today: date, *, days: int | None = None, missing: bool = False,
                   template: str | None = None, partial_gift: bool | None = None, status: str = "delivered"):
    """(customer text, world, handoff inputs, order_template, request template)."""
    multi = [t for t, s in ORDER_TEMPLATES.items() if len(s) > 1]
    if template is None:
        template = g.r.choice(multi if sub_uc == "partial-refund" else list(ORDER_TEMPLATES))
    if days is None:
        u = g.r.random()
        days = g.r.randint(1, 29) if u < 0.80 else 30 if u < 0.835 else g.r.randint(31, 35) if u < 0.95 else g.r.randint(36, 60)
    oid, o = g.order(template, status, today, days, payment="gift_card" if sub_uc == "gift-card" else "card")
    world = g.world(today, (oid, o))
    items_by_sku = {i["sku"]: i for i in o["items"]}
    item = items_by_sku[g.r.choice(list(items_by_sku))]
    if sub_uc == "gift-card" and partial_gift is None:
        partial_gift = len(items_by_sku) > 1 and g.r.random() < 0.5
    kind = "no-order" if missing else sub_uc
    i = g.r.randrange(len(TEXT[kind]))
    if sub_uc == "gift-card" and not missing:
        i = 1 if partial_gift else 0
    form = TEXT[kind][i]
    if missing:
        text = form.format(item=item["name"])
        inputs = {"order_id": None, "items": None, "to": "original", "today": iso(today)}
    elif sub_uc == "partial-refund":
        text = form.format(oid=oid, item=item["name"])
        inputs = {"order_id": oid, "items": [item["sku"]], "to": "original", "today": iso(today)}
    elif sub_uc == "gift-card":
        text = form.format(oid=oid, item=item["name"])
        inputs = {"order_id": oid, "items": [item["sku"]] if partial_gift else None, "to": "gift_card",
                  "today": iso(today)}
    else:
        text = form.format(oid=oid)
        inputs = {"order_id": oid, "items": None, "to": "original", "today": iso(today)}
    return text, world, inputs, template, f"refund-{kind}-t{i + 1}"


def traces(seed: int = 7) -> list[dict]:
    g = Gen(seed)
    counts = {"order-status": 140, "return": 60, "address": 30, "refund": 160}
    rows = []
    n = 1000
    for uc, k in counts.items():
        for _ in range(k):
            today = date(2026, 10, 1) + timedelta(days=g.r.randint(0, 30))
            tid = f"tr_{n}"
            n += 1
            meta = {"latency_ms": g.r.randint(900, 4200), "cost_usd": round(g.r.uniform(0.001, 0.004), 4)}
            if uc == "refund":
                sub = g.r.choices(["full-refund", "partial-refund", "gift-card"], [0.70, 0.18, 0.12])[0]
                missing = g.r.random() < 0.20
                text, world, inputs, ot, tmpl = refund_request(g, sub, today, missing=missing)
                end, reply = refund_outcome(world, inputs)
                rows.append({"id": tid, "use_case": "refund", "template": tmpl, **meta,
                             "trigger": {"type": "message", "text": text},
                             "inputs": {"today": iso(today), "customer": world["orders"][next(iter(world["orders"]))]["customer"]},
                             "start_state": world,
                             "expected_end_state": {"world": routed(end, inputs), "output": reply},
                             "handoffs": [{"to": "refund-subagent", "use_case": sub, "order_template": ot,
                                           "trigger": {"type": "handoff", "text": f"Refund request: {text}"},
                                           "inputs": inputs, "start_state": world,
                                           "expected_end_state": {"world": end, "output": reply}}]})
                continue
            if uc == "order-status":
                status = g.r.choices(["processing", "shipped", "delivered"], [0.3, 0.5, 0.2])[0]
                oid, o = g.order(g.r.choice(list(ORDER_TEMPLATES)), status, today)
            elif uc == "return":
                u = g.r.random()
                status = "delivered" if u < 0.92 else "shipped"
                days = g.r.randint(1, 30) if u < 0.80 else g.r.randint(31, 45)
                oid, o = g.order(g.r.choice(list(ORDER_TEMPLATES)), status, today, days)
            else:
                status = "processing" if g.r.random() < 0.75 else "shipped"
                oid, o = g.order(g.r.choice(list(ORDER_TEMPLATES)), status, today)
            world = g.world(today, (oid, o))
            i = g.r.randrange(len(TEXT[uc]))
            text = TEXT[uc][i].format(oid=oid, address=f"{g.r.randint(100, 999)} {g.r.choice(STREETS)}")
            end, reply = end_to_end(uc, text, today, world, oid)
            rows.append({"id": tid, "use_case": uc, "template": f"{uc}-t{i + 1}", **meta,
                         "trigger": {"type": "message", "text": text},
                         "inputs": {"today": iso(today), "customer": world["orders"][oid]["customer"]},
                         "start_state": world, "expected_end_state": {"world": end, "output": reply}})
    return rows


# ---- bug-finding sets ---------------------------------------------------------------------------

E2E_FMS = ["wrong-answer", "wrong-end-state", "unrequested-change", "wrong-route"]
REFUND_FMS = ["breaks-policy", "wrong-amount", "unrequested-change", "wrong-reply"]


def bf_case(cid, uc, cluster_field, cluster, fms, coverage, text, inputs, world, end, reply, ttype="message"):
    return {"id": cid, "use_case": uc, "pool": "bug_finding", cluster_field: cluster,
            "failure_modes": fms, "coverage_entries": coverage,
            "provenance": {"source": "template", "template": cluster, "synthetic": True},
            "trigger": {"type": ttype, "text": text}, "inputs": inputs, "start_state": world, "followups": [],
            "expected_end_state": {"world": end, "output": reply}}


def e2e_bug_finding(seed: int = 11) -> list[dict]:
    g = Gen(seed)
    g.next_order = 7001
    today = date(2026, 10, 20)
    out = []

    def plain(cid, uc, tmpl, coverage, text_fn, status="delivered", days=None, world_fn=None):
        oid, o = g.order("ot-03", status, today, days)
        world = g.world(today, (oid, o))
        if world_fn:
            world_fn(world, oid)
        text = text_fn(oid)
        end, reply = end_to_end(uc, text, today, world, oid)
        out.append(bf_case(cid, uc, "template", tmpl, E2E_FMS, coverage, text,
                           {"today": iso(today), "customer": world["orders"][oid]["customer"]}, world, end, reply))

    # an order number that doesn't exist
    oid = "A9999"
    world = g.world(today, g.order("ot-01", "shipped", today))
    out.append(bf_case("bf-status-not-found", "order-status", "template", "bf-not-found", E2E_FMS,
                       ["order-status", "not-found"], f"Where is my order {oid}?",
                       {"today": iso(today), "customer": "c-9999"}, world,
                       {**copy.deepcopy(world), "log": []}, f"I couldn't find order {oid}. Could you check the number?"))
    plain("bf-status-delivered", "order-status", "bf-status-delivered", ["order-status"],
          lambda o: f"Has {o} shipped yet?", "delivered", 2)
    plain("bf-return-day-30", "return", "bf-return-window", ["return", "window-edge"],
          lambda o: f"I want to return order {o}.", "delivered", 30)
    plain("bf-return-day-31", "return", "bf-return-window", ["return", "not-allowed", "window-edge"],
          lambda o: f"I want to return order {o}.", "delivered", 31)
    plain("bf-return-twice", "return", "bf-return-twice", ["return", "not-allowed"],
          lambda o: f"Start a return for {o} please.", "delivered", 5,
          world_fn=lambda w, o: w["returns"].append({"order": o, "opened": "2026-10-18"}))
    plain("bf-return-not-delivered", "return", "bf-return-not-delivered", ["return", "not-allowed"],
          lambda o: f"Can I send back {o}?", "shipped")
    plain("bf-address-shipped", "address", "bf-address-shipped", ["address", "not-allowed"],
          lambda o: f"Please send order {o} to 401 Bay Street instead.", "shipped")
    plain("bf-address-processing", "address", "bf-address-processing", ["address"],
          lambda o: f"Change the delivery address of {o} to 77 Mill Lane.", "processing")
    for cid, tmpl, cov, kw in [
        ("bf-refund-day-31", "bf-refund-window", ["refund", "not-allowed", "window-edge"], {"days": 31}),
        ("bf-refund-day-30", "bf-refund-window", ["refund", "window-edge"], {"days": 30}),
        ("bf-refund-no-number", "bf-refund-no-number", ["refund", "missing-information"], {"missing": True, "days": 4}),
        ("bf-refund-gift-partial", "bf-refund-gift-partial", ["refund", "gift-card", "partial"],
         {"days": 6, "template": "ot-03", "partial_gift": True}),
    ]:
        sub = "gift-card" if "gift" in cid else "full-refund"
        text, world, inputs, _, _ = refund_request(g, sub, today, **kw)
        end, reply = refund_outcome(world, inputs)
        out.append(bf_case(cid, "refund", "template", tmpl, E2E_FMS, cov, text,
                           {"today": iso(today), "customer": world["orders"][next(iter(world["orders"]))]["customer"]},
                           world, routed(end, inputs), reply))
    return out


def refund_bug_finding(seed: int = 13) -> list[dict]:
    g = Gen(seed)
    g.next_order = 8001
    today = date(2026, 10, 22)
    out = []
    for cid, sub, tmpl, cov, kw in [
        ("bf-window-30", "full-refund", "bf-window-30", ["full-refund", "window-edge"], {"days": 30}),
        ("bf-window-30-partial", "partial-refund", "bf-window-30", ["partial-refund", "window-edge"], {"days": 30}),
        ("bf-window-31", "full-refund", "bf-window-31", ["full-refund", "not-allowed", "window-edge"], {"days": 31}),
        ("bf-window-35", "full-refund", "bf-window-31", ["full-refund", "not-allowed", "window-edge"], {"days": 35}),
        ("bf-partial-one-of-three", "partial-refund", "bf-partial", ["partial-refund"], {"days": 3, "template": "ot-06"}),
        ("bf-partial-one-of-two", "partial-refund", "bf-partial", ["partial-refund"], {"days": 9, "template": "ot-04"}),
        ("bf-gift-partial-cents", "gift-card", "bf-gift-partial", ["gift-card", "partial-refund"],
         {"days": 5, "template": "ot-03", "partial_gift": True}),
        ("bf-gift-whole", "gift-card", "bf-gift-whole", ["gift-card"], {"days": 12, "template": "ot-07", "partial_gift": False}),
        ("bf-no-order-number", "full-refund", "bf-no-order", ["full-refund", "missing-information"], {"missing": True, "days": 2}),
        ("bf-not-delivered", "full-refund", "bf-not-delivered", ["full-refund", "not-allowed"], {"status": "shipped"}),
    ]:
        text, world, inputs, _, _ = refund_request(g, sub, today, **kw)
        end, reply = refund_outcome(world, inputs)
        out.append(bf_case(cid, sub, "order_template", tmpl, REFUND_FMS, cov, f"Refund request: {text}",
                           inputs, world, end, reply, ttype="handoff"))
    # already refunded in full
    text, world, inputs, _, _ = refund_request(g, "full-refund", today, days=8)
    o = world["orders"][inputs["order_id"]]
    o["refunded"] = round(sum(i["price"] for i in o["items"]), 2)
    world["refunds"].append({"order": inputs["order_id"], "amount": o["refunded"], "to": "original"})
    end, reply = refund_outcome(world, inputs)
    out.append(bf_case("bf-already-refunded", "full-refund", "order_template", "bf-refunded", REFUND_FMS,
                       ["full-refund", "not-allowed"], f"Refund request: {text}", inputs, world, end, reply, ttype="handoff"))
    return out


# ---- the policy judges' labels --------------------------------------------------------------------

def judge_u(inp: dict) -> float:
    """The toy judge's hash (judges/policy_judge.py): the same number it draws its mistakes from."""
    return int(hashlib.sha256(json.dumps(inp, sort_keys=True).encode()).hexdigest()[:8], 16) / 16 ** 8


def labels(judge_id: str, miss: float, flag: float, n_fail: int, n_pass: int, k_missed: int, k_flagged: int,
           seed: int) -> list[dict]:
    """A person's labels on past refund runs: n_fail runs that broke the policy (k_missed of which the
    judge passes) and n_pass that didn't (k_flagged of which it fails)."""
    import sys

    sys.path.insert(0, str(HERE.parents[1] / "src"))
    from aot_evals.judges import item_id  # the ids the judges' labels are keyed by

    g = Gen(seed)
    g.next_order = 20001
    want = {(False, True): k_missed, (False, False): n_fail - k_missed, (True, False): k_flagged,
            (True, True): n_pass - k_flagged}
    got: dict[tuple, list[dict]] = {k: [] for k in want}
    n = 0
    while any(len(got[k]) < want[k] for k in want):
        n += 1
        today = date(2026, 9, 1) + timedelta(days=g.r.randint(0, 29))
        sub = g.r.choices(["full-refund", "partial-refund", "gift-card"], [0.8, 0.15, 0.05])[0]
        text, world, inputs, _, _ = refund_request(g, sub, today, missing=g.r.random() < 0.2)
        due = refund_due(world, inputs)
        broke = g.r.random() < 0.5  # a run that got the decision wrong: refunded what wasn't due, or the reverse
        end = copy.deepcopy(world)
        if (due is not None) != broke:
            amt = due if due is not None else round(sum(i["price"] for i in world["orders"][inputs["order_id"]]["items"]), 2) \
                if inputs.get("order_id") else None
            if amt is None:
                continue  # nothing to refund wrongly without an order
            end["refunds"].append({"order": inputs["order_id"], "amount": amt, "to": inputs["to"]})
        inp = {"case.inputs": inputs, "start.world.orders": world["orders"], "end.world.refunds": end["refunds"]}
        u = judge_u(inp)
        label = not broke
        judged_pass = (u >= flag) if label else (u < miss)
        key = (label, judged_pass)
        if len(got[key]) >= want[key]:
            continue
        cid = f"lab-{n:05d}"
        got[key].append({"item_id": item_id(None, cid, inp), "case_id": cid, "label": label,
                         "labeller": "refunds-reviewer", "split": "dev", "input": inp,
                         "note": None if label else "the decision breaks the refund policy"})
    rows = [r for k in want for r in got[k]]
    random.Random(seed).shuffle(rows)
    return rows


def write_cases(eval_id: str, cases: list[dict]) -> None:
    for c in cases:
        d = AGENT / eval_id / "cases" / c["use_case"]
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{c['id']}.json").write_text(json.dumps(c, indent=2) + "\n")


def main() -> None:
    rows = traces()
    (HERE / "traces.jsonl").write_text("".join(json.dumps(r, sort_keys=True, separators=(",", ":")) + "\n"
                                              for r in rows))
    write_cases("end-to-end", e2e_bug_finding())
    write_cases("refund-subagent", refund_bug_finding())
    judge_dir = AGENT / "refund-subagent" / "checks" / "judge"
    for jid, miss, flag, k_missed, k_flagged, seed in (("policy-judge", 0.05, 0.01, 5, 5, 21),
                                                       ("policy-judge-weak", 0.20, 0.10, 20, 50, 23)):
        rows_ = labels(jid, miss, flag, 100, 500, k_missed, k_flagged, seed)
        (judge_dir / f"{jid}.labels.jsonl").write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows_))
    print(f"wrote {len(rows)} traces, the bug-finding cases and the judges' labels")


if __name__ == "__main__":
    main()
