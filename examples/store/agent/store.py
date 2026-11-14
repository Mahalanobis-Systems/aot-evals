"""The online store's support agent: a toy orchestrator that speaks the agent contract
(references/agent-contract.md). Nothing calls a model or a network service.

It reads the customer's message (`question`), routes it, and answers order-status, return and
address requests with the order tools (the order-system fake in env/). A refund request is
handed to the refund subagent (agent/refunds.py), a program of its own with its own prompt and
model: the orchestrator writes the handoff (`{order_id, items, to, today}`), logs it, runs the
subagent through the same contract, and passes its reply on.

AGENT_VARIANT switches a self-test behavior (the refund variants are the subagent's; see its
docstring):

  good      answers as it should
  liar      says it is done without calling any tool
  flaky     gives a wrong arrival date on about one trial in four of an order-status request
  costly    as good, at three times the cost
  slow      hangs past the timeout on about a third of attempts
  silent    prints nothing, like an agent whose model provider has stopped answering
  peek      searches its working directory for its own case file, as a coding harness might; if
            it finds one it says so and leaves a mark in it

AGENT_BREAK (comma-separated case ids) makes exactly those cases go wrong, in any variant: a
second version that differs from the first on a known set of cases.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import time
from datetime import date, timedelta
from pathlib import Path

ENV = Path(os.environ.get("STORE_ENV", "evals/agents/store/env"))
sys.path.insert(0, str(ENV))
import store_world as w_  # noqa: E402

VARIANT = os.environ.get("AGENT_VARIANT", "good")
BREAK = {c for c in os.environ.get("AGENT_BREAK", "").split(",") if c}
SUBAGENT = Path(__file__).with_name("refunds.py")
ORDER = re.compile(r"\b([A-Z]\d{4})\b")
ADDRESS = re.compile(r"\bto (\d+ [^.?!]+?)(?: instead)?[.?!]?$")


def bucket(*parts, n: int = 6) -> int:
    return int(hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest(), 16) % n


def route(text: str) -> str:
    t = text.lower()
    if "refund" in t or "money back" in t:
        return "refund"
    if "return" in t or "send back" in t:
        return "return"
    if "address" in t or ADDRESS.search(text):
        return "address"
    return "order-status"


def status_reply(order_id: str, order: dict | None, shift: int = 0) -> str:
    if order is None:
        return f"I couldn't find order {order_id}. Could you check the number?"
    if order["status"] == "delivered":
        return f"Order {order_id} was delivered on {order['delivered']}."
    eta = (date.fromisoformat(order["eta"]) + timedelta(days=shift)).isoformat()
    return f"Order {order_id} is {order['status']}; it should arrive on {eta}."


def handoff(world: dict, case: dict, order_id: str | None, text: str) -> tuple[str, float, dict]:
    """Write the handoff, run the refund subagent on it, and return its reply, cost and models."""
    items = None
    order = w_.read_order(world, order_id) if order_id else None
    if order:
        named = [i["sku"] for i in order["items"] if i["name"].lower() in text.lower()]
        items = named or None
    to = "gift_card" if "gift card" in text.lower() else "original"
    inputs = {"order_id": order_id, "items": items, "to": to, "today": case["inputs"]["today"]}
    w_.log_handoff(world, "refund-subagent", order_id)
    w_.save(world)
    payload = {**case, "question": f"Refund request: {text}", "inputs": inputs,
               "trigger": {"type": "handoff", "text": f"Refund request: {text}"}}
    r = subprocess.run([sys.executable, str(SUBAGENT), "--handoff"], input=json.dumps(payload),
                       capture_output=True, text=True, timeout=30, env=os.environ.copy())
    out = json.loads(r.stdout[r.stdout.find("{"):]) if "{" in r.stdout else {}
    world.clear()
    world.update(w_.load())
    return (out.get("answer") or "Sorry, I couldn't process the refund.",
            (out.get("usage") or {}).get("cost") or 0.0, out.get("model_ids") or {})


def main() -> None:
    case = json.load(sys.stdin)
    if VARIANT == "silent":
        return
    if VARIANT == "peek":
        for found in Path(".").rglob(f"{case['case_id']}.json"):
            with found.open("a") as f:
                f.write("\n")
            print(json.dumps({"answer": f"Read the expected answer in {found}.",
                              "model_ids": {"main": "toy-orchestrator-1"}}))
            return
    if VARIANT == "slow" and bucket(case["case_id"], case["trial"], case["attempt"]) < 2:
        time.sleep(30)
    model = case.get("model") or "toy-orchestrator-1"
    cost = 0.0015 * (3 if VARIANT == "costly" else 1)
    usage = {"tokens_input": 2100, "tokens_output": 90, "tokens_cached": 1600, "tool_calls": 1}
    text = case.get("question") or ""
    if VARIANT == "liar" or case["case_id"] in BREAK:
        print(json.dumps({"answer": "Done! That's all taken care of.", "usage": {**usage, "cost": cost,
                          "tool_calls": 0}, "model_ids": {"main": model}}))
        return
    world = w_.load()
    m = ORDER.search(text)
    order_id = m.group(1) if m else None
    kind = route(text)
    models = {"main": model}
    if kind == "refund":
        reply, sub_cost, sub_models = handoff(world, case, order_id, text)
        cost += sub_cost
        models["refund-subagent"] = sub_models.get("main")
    elif order_id is None:
        reply = "Could you give me the order number?"
    elif kind == "order-status":
        flaky = VARIANT == "flaky" and bucket(case["case_id"], case["trial"], n=4) == 0
        reply = status_reply(order_id, w_.read_order(world, order_id), shift=2 if flaky else 0)
    elif kind == "return":
        order = w_.read_order(world, order_id)
        today = case["inputs"]["today"]
        if order is None:
            reply = f"I couldn't find order {order_id}."
        elif order["status"] != "delivered":
            reply = f"Order {order_id} hasn't been delivered yet; you can return it once it arrives."
        elif w_.days_between(order["delivered"], today) > 30:
            reply = f"Order {order_id} was delivered more than 30 days ago, so it can't be returned."
        elif w_.start_return(world, order_id, today):
            reply = f"I've started a return for order {order_id}. You'll get a label by email."
        else:
            reply = f"A return is already open for order {order_id}."
    else:  # address
        a = ADDRESS.search(text)
        if a and w_.change_address(world, order_id, a.group(1).strip()):
            reply = f"Order {order_id} will now go to {a.group(1).strip()}."
        else:
            reply = f"Order {order_id} has already shipped, so I can't change its address."
    w_.save(world)
    print(json.dumps({"answer": reply, "usage": {**usage, "cost": round(cost, 6)}, "model_ids": models}))


if __name__ == "__main__":
    main()
