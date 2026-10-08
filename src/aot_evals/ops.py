"""E14 operational sweep: plane B only. No labels, judges or cases needed.

Two sources:
- runs: budgets vs actuals per category for one or more runs (the same numbers as report P4);
- an export (C0): per-row cost, latency, tokens and outcome read from an imported trace dump
  through a field mapping, so a team can see plane B in week one, before any eval exists.
"""

from __future__ import annotations

from collections import defaultdict

from .importer import export_file, iter_rows
from .repo import Evals
from .report import Context, operational
from .util import get_path

EXPORT_FIELDS = ("category", "cost_usd", "latency_ms", "tokens_input", "tokens_output",
                 "tokens_cached", "tool_calls", "outcome", "killed")


def from_runs(ev: Evals, run_ids: list[str]) -> dict:
    ctx = Context(ev, run_ids)
    by_cat: dict[str, list[dict]] = defaultdict(list)
    for a in ctx.attempts:
        by_cat[a.get("category") or "(none)"].append(a)
    return {"source": {"runs": run_ids},
            "categories": {c: operational(atts, ev.budget_for(c)) for c, atts in sorted(by_cat.items())}}


def from_export(ev: Evals, export_id: str, mapping: dict[str, str], ok_values: list[str]) -> dict:
    unknown = set(mapping) - set(EXPORT_FIELDS)
    if unknown:
        raise ValueError(f"unknown field(s) {sorted(unknown)}; map any of {EXPORT_FIELDS}")
    path = export_file(ev, export_id)
    by_cat: dict[str, list[dict]] = defaultdict(list)
    for i, row in enumerate(iter_rows(path)):
        rec = {"run_id": export_id, "case_id": f"row{i}", "trial": 0, "attempt": 0, "final": True,
               "passed": None}
        for field in EXPORT_FIELDS:
            if field not in mapping:
                rec[field] = None
                continue
            v = get_path(row, mapping[field])
            if field in ("cost_usd", "latency_ms"):
                v = _num(v, float)
            elif field in ("tokens_input", "tokens_output", "tokens_cached", "tool_calls"):
                v = _num(v, int)
            elif field == "outcome" and v is not None:
                v = "ok" if str(v) in ok_values else str(v)
            elif field == "killed":
                v = str(v).lower() in ("1", "true", "yes")
            rec[field] = v
        if "outcome" not in mapping:
            rec["outcome"] = "ok"
        by_cat[str(rec.get("category") or "(uncategorised)")].append(rec)
    return {"source": {"export": export_id, "mapping": mapping},
            "note": "cost per success needs correctness, which an export does not have",
            "categories": {c: operational(r, ev.budget_for(c)) for c, r in sorted(by_cat.items())}}


def _num(v, kind):
    try:
        return kind(float(v)) if kind is int else kind(v)
    except (TypeError, ValueError):
        return None


def render(result: dict) -> str:
    lines = [f"E14 operational sweep  {result['source']}"]
    if result.get("note"):
        lines.append(f"  note: {result['note']}")
    hdr = (f"  {'category':<26} {'trials':>6} {'$/run':>9} {'$/success':>10} {'p50 ms':>8} "
           f"{'p90 ms':>8} {'cache':>6} {'err rate':>9} {'retries':>7} {'killed':>6}  budget")
    lines.append(hdr)
    for cat, op in result["categories"].items():
        er = op.get("error_rate") or {}
        status = op.get("budget_status") or "no budget"
        if op.get("budget_breaches"):
            status += ": " + ", ".join(f"{b['budget']} {_fmt(b['actual'])} > {_fmt(b['limit'])}"
                                       if b['budget'] != 'cache_hit_rate_min' else
                                       f"{b['budget']} {_fmt(b['actual'])} < {_fmt(b['limit'])}"
                                       for b in op["budget_breaches"])
        lines.append(
            f"  {cat:<26} {op['n_trials']:>6} {_fmt(op['cost_per_run'], '$'):>9} "
            f"{_fmt(op['cost_per_success'], '$'):>10} {_fmt(op['latency_p50'], d=0):>8} "
            f"{_fmt(op['latency_p90'], d=0):>8} {_fmt(op['cache_hit_rate'], '%'):>6} "
            f"{_fmt(er.get('point'), '%'):>9} {op['retries']:>7} {op['killed']:>6}  {status}")
        if er.get("ci"):
            lines.append(f"  {'':<26} error rate 95% CI [{_fmt(er['ci'][0], '%')}, "
                         f"{_fmt(er['ci'][1], '%')}], n={er['n']} attempts; outcomes {op['outcomes']}")
    return "\n".join(lines)


def _fmt(v, kind: str = "", d: int = 4) -> str:
    if v is None:
        return "-"
    if kind == "$":
        return f"${v:.4f}"
    if kind == "%":
        return f"{100 * v:.1f}%"
    return f"{v:.{d}f}" if isinstance(v, float) else str(v)
