"""C5 `allocate`: size both case sets, show the arithmetic, and record the plan.

- **Error-finding set** (docs/method.md §2.3): flat across categories, at least 10 per category and 3 per
  simple category. Its pass rate is not a quality estimate.
- **Quality-estimate set**: proportional to each category's observed share, sized by the
  interval the owner needs on the share-weighted pass rate (M14).

The minimum detectable effect (M7) is printed for each set before anything runs. The plan goes
to `evals/allocation.yaml`; the owner marks each cell that cannot be filled from traffic as
`scheduled` (synthetic or selector-sourced cases to come) or `out_of_scope` with a reason, and
those marks survive re-allocation.
"""

from __future__ import annotations

import math

from . import stats
from .repo import Evals
from .screen import passes as screen_passes
from .util import dump_yaml, now_iso

EF_PER_CATEGORY = 10
EF_PER_SIMPLE = 3


def plan(ev: Evals, halfwidth: float = 0.05, assumed_rate: float = 0.5, k: int = 3) -> dict:
    cats = ev.categories()
    prior = ev.allocation()
    prior_cells = {(c.get("category"), c.get("set")): c for c in prior.get("cells") or []}
    cases = ev.cases(include_dropped=False)
    counts: dict[tuple[str, str], dict] = {}
    for c in cases:
        key = (c.get("category"), c.get("set"))
        d = counts.setdefault(key, {"n": 0, "screened": 0, "synthetic": 0})
        d["n"] += 1
        d["screened"] += 1 if screen_passes(c.get("screen")) else 0
        d["synthetic"] += 1 if (c.get("provenance") or {}).get("synthetic") else 0

    shares = {c["id"]: c.get("observed_share") for c in cats if c.get("id")}
    share_total = sum(s for s in shares.values() if isinstance(s, (int, float)))
    qe_total = stats.sample_size_for_halfwidth(halfwidth, assumed_rate)

    cells = []
    for c in cats:
        cid = c.get("id")
        if not cid:
            continue
        ef_target = EF_PER_SIMPLE if c.get("simple") else EF_PER_CATEGORY
        share = shares.get(cid)
        if isinstance(share, (int, float)) and share_total > 0:
            qe_target = math.ceil(qe_total * share / share_total) if share > 0 else 0
        else:
            qe_target = None
        for set_name, target in (("error_finding", ef_target), ("quality_estimate", qe_target)):
            have = counts.get((cid, set_name), {"n": 0, "screened": 0, "synthetic": 0})
            old = prior_cells.get((cid, set_name), {})
            if target is not None and have["n"] >= target:
                status = "filled"
            elif old.get("status") in ("scheduled", "out_of_scope"):
                status = old["status"]
            else:
                status = "short"
            cells.append({"category": cid, "set": set_name, "target": target,
                          "have": have["n"], "screened": have["screened"],
                          "synthetic": have["synthetic"], "status": status,
                          "reason": old.get("reason")})

    ef_n = sum(c["target"] for c in cells if c["set"] == "error_finding" and c["target"])
    qe_n = sum(c["target"] for c in cells if c["set"] == "quality_estimate" and c["target"])
    return {
        "generated": now_iso(),
        "assumptions": {"assumed_pass_rate": assumed_rate, "k": k,
                        "quality_halfwidth": halfwidth, "confidence": 0.95, "power": 0.80},
        "error_finding": {
            "rule": f"flat: {EF_PER_CATEGORY} per category, {EF_PER_SIMPLE} per simple category",
            "n": ef_n,
            "mde_unpaired_upper_bound": stats.mde(ef_n, assumed_rate),
            "per_category_ci_halfwidth_at_target": {
                c["category"]: _halfwidth(c["target"], assumed_rate)
                for c in cells if c["set"] == "error_finding"},
            "note": "finds and verifies errors; its pass rate is not a quality estimate",
        },
        "quality_estimate": {
            "rule": (f"n = z^2 p(1-p) / h^2 = 1.96^2 x {assumed_rate} x {1 - assumed_rate} / "
                     f"{halfwidth}^2 = {qe_total}, split by observed share"),
            "n": qe_n,
            "target_ci_halfwidth": halfwidth,
            "mde_unpaired_upper_bound": stats.mde(qe_n, assumed_rate),
            "weights": {k_: (v / share_total if isinstance(v, (int, float)) and share_total else None)
                        for k_, v in shares.items()},
        },
        "cells": cells,
    }


def _halfwidth(n: int | None, p: float) -> float | None:
    if not n:
        return None
    ci = stats.wilson(round(n * p), n)
    return (ci[1] - ci[0]) / 2 if ci else None


def render(p: dict) -> str:
    a = p["assumptions"]
    ef, qe = p["error_finding"], p["quality_estimate"]
    lines = [
        "C5 allocate",
        f"  assumptions: pass rate {a['assumed_pass_rate']}, k={a['k']}, 95% intervals, 80% power",
        "",
        f"  error-finding set: {ef['rule']}",
        f"    N = {ef['n']}; MDE (unpaired, upper bound) = {_pct(ef['mde_unpaired_upper_bound'])}",
        "    per-category 95% CI half-width at target: "
        + ", ".join(f"{k}: ±{_pct(v)}" for k, v in ef["per_category_ci_halfwidth_at_target"].items()),
        "    (this set finds errors; its pass rate is not a quality estimate)",
        "",
        f"  quality-estimate set: {qe['rule']}",
        f"    N = {qe['n']}; target CI ±{_pct(qe['target_ci_halfwidth'])}; "
        f"MDE (unpaired, upper bound) = {_pct(qe['mde_unpaired_upper_bound'])}",
        "",
        f"  {'category':<28} {'set':<17} {'target':>6} {'have':>5} {'screened':>8}  status",
    ]
    for c in p["cells"]:
        t = "?" if c["target"] is None else str(c["target"])
        lines.append(f"  {c['category']:<28} {c['set']:<17} {t:>6} {c['have']:>5} "
                     f"{c['screened']:>8}  {c['status']}{' - ' + c['reason'] if c.get('reason') else ''}")
    return "\n".join(lines)


def _pct(v) -> str:
    return "n/a" if v is None else f"{100 * v:.1f} pts"


def write(ev: Evals, p: dict) -> None:
    header = ("# Written by `aot-evals allocate --write` (C5). Edit only `status` and `reason`:\n"
              "# status is filled | short | scheduled | out_of_scope; scheduled and out_of_scope\n"
              "# need a reason. Everything else is recomputed.\n")
    ev.p("allocation.yaml").write_text(header + dump_yaml(p))
