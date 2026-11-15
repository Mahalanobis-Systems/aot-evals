"""The store's sandbox: fakes for the order system and payments, kept in one JSON file.

The world is `{"orders": {id: order}, "refunds": [...], "returns": [...], "log": [...]}`, in the
file `STORE_WORLD` names (default `world.json`, relative to the working directory). The `seed`
hook writes a case's `start_state` there before every attempt and the `observe` hook prints it
before and after, so the checks grade what the fakes hold, never what the agent says it did.

An order: `{"customer", "status": processing | shipped | delivered, "eta", "delivered",
"address", "payment": card | gift_card, "items": [{"sku", "name", "price"}], "refunded"}`.
Every call the agent makes is appended to `log` (`{"tool", "order", ...}`), so a check can tell a
refund handed to the refund subagent from one the orchestrator never routed.
"""

from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path


def path() -> Path:
    return Path(os.environ.get("STORE_WORLD", "world.json"))


def load() -> dict:
    p = path()
    w = json.loads(p.read_text()) if p.exists() else {}
    for key, empty in (("orders", {}), ("refunds", []), ("returns", []), ("log", [])):
        w.setdefault(key, empty)
    return w


def save(w: dict) -> None:
    path().write_text(json.dumps(w, indent=1, sort_keys=True))


def days_between(a: str, b: str) -> int:
    return (date.fromisoformat(b) - date.fromisoformat(a)).days


# ---- the order system -------------------------------------------------------------------------

def read_order(w: dict, order_id: str) -> dict | None:
    w["log"].append({"tool": "orders.read", "order": order_id})
    return w["orders"].get(order_id)


def change_address(w: dict, order_id: str, address: str) -> bool:
    """Only an order that hasn't shipped can be sent somewhere else."""
    w["log"].append({"tool": "orders.change_address", "order": order_id})
    o = w["orders"].get(order_id)
    if not o or o["status"] != "processing":
        return False
    o["address"] = address
    return True


def start_return(w: dict, order_id: str, today: str) -> bool:
    w["log"].append({"tool": "orders.start_return", "order": order_id})
    o = w["orders"].get(order_id)
    if not o or o["status"] != "delivered" or any(r["order"] == order_id for r in w["returns"]):
        return False
    w["returns"].append({"order": order_id, "opened": today})
    return True


# ---- payments -----------------------------------------------------------------------------------

def refund(w: dict, order_id: str, amount: float, to: str) -> None:
    w["log"].append({"tool": "payments.refund", "order": order_id, "amount": amount, "to": to})
    w["refunds"].append({"order": order_id, "amount": round(amount, 2), "to": to})
    o = w["orders"].get(order_id)
    if o is not None:
        o["refunded"] = round(o.get("refunded", 0) + amount, 2)


def log_handoff(w: dict, to: str, order_id: str | None) -> None:
    w["log"].append({"tool": "handoff", "to": to, "order": order_id})
