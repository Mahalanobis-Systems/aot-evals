"""The store's refund subagent: a toy that speaks the agent contract (references/agent-contract.md).

The orchestrator hands it a refund request (`--handoff`: the case is the handoff, as the
refund-subagent eval replays it). stdin's `inputs` carry what the orchestrator wrote:
`{"order_id": "A1234" | null, "items": [sku, ...] | null, "to": "original" | "gift_card",
"today": "2026-10-20"}`. It applies the refund policy (refunds_prompt.md) through the payments
fake in env/ and prints its reply.

AGENT_VARIANT switches what it does wrong (docs/problems.md):

  good                    counts the 30th day after delivery as outside the window (a refund the
                          policy allows is refused), and rounds a partial gift-card refund down
                          to whole dollars
  refund-bug              as good, and also refunds days 31 to 35 (problem 1: refunds fail about
                          three times as often)
  declines-missing-order  the new prompt: the window is right, but a handoff with no order number
                          is declined instead of asking for one (problem 2)
  cheap                   a cheaper model (problem 11): the window is right, but a partial refund
                          of several items refunds only the first; a quarter of the cost

Any other variant (they belong to the orchestrator) behaves as good.
"""

from __future__ import annotations

import json
import math
import os
import sys
from pathlib import Path

ENV = Path(os.environ.get("STORE_ENV", "evals/agents/store/env"))
sys.path.insert(0, str(ENV))
import store_world as w_  # noqa: E402

VARIANT = os.environ.get("AGENT_VARIANT", "good")
WINDOW = 30  # days after delivery, the 30th included


def last_day(variant: str) -> int:
    """The last day after delivery this version refunds."""
    if variant == "refund-bug":
        return 35
    if variant in ("declines-missing-order", "cheap"):
        return WINDOW
    return WINDOW - 1  # good: off by one


def decide(world: dict, inputs: dict, variant: str) -> tuple[float | None, str]:
    """(amount to refund, or None to refund nothing; the reply)."""
    oid = inputs.get("order_id")
    if not oid:
        if variant == "declines-missing-order":
            return None, "I can't process a refund without an order. Request declined."
        return None, "I can refund that for you. What is your order number?"
    order = w_.read_order(world, oid)
    if order is None:
        return None, f"I couldn't find order {oid}. Could you check the number?"
    if order["status"] != "delivered":
        return None, f"Order {oid} hasn't been delivered yet, so there is nothing to refund."
    days = w_.days_between(order["delivered"], inputs["today"])
    if days > last_day(variant):
        return None, f"Order {oid} was delivered {days} days ago, past the {WINDOW}-day refund window."
    skus = inputs.get("items")
    items = [i for i in order["items"] if not skus or i["sku"] in skus]
    if variant == "cheap" and skus and len(items) > 1:
        items = items[:1]
    if not items:
        return None, f"None of those items are on order {oid}."
    amount = round(sum(i["price"] for i in items), 2)
    left = round(sum(i["price"] for i in order["items"]) - order.get("refunded", 0), 2)
    if left <= 0:
        return None, f"Order {oid} has already been refunded."
    amount = min(amount, left)
    to = inputs.get("to") or "original"
    if variant != "declines-missing-order" and variant != "cheap" and to == "gift_card" and skus:
        amount = math.floor(amount)
    return amount, f"Refunded ${amount:.2f} for order {oid} to your {'gift card' if to == 'gift_card' else 'original payment'}."


def main() -> None:
    case = json.load(sys.stdin)
    inputs = case.get("inputs") or {}
    world = w_.load()
    amount, reply = decide(world, inputs, VARIANT)
    if amount is not None:
        w_.refund(world, inputs["order_id"], amount, inputs.get("to") or "original")
    w_.save(world)
    cheap = VARIANT == "cheap"
    print(json.dumps({"answer": reply,
                      "usage": {"tokens_input": 1400, "tokens_output": 80, "tokens_cached": 1100,
                                "cost": 0.0002 if cheap else 0.0008, "tool_calls": 2},
                      "model_ids": {"main": "toy-refunds-mini" if cheap else "toy-refunds-1"}}))


if __name__ == "__main__":
    main()
