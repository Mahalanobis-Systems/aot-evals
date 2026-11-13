"""`plan` for a 2.0 eval: how many cases each use case and pool needs, worked out from the decision
rule (docs/v2-design.md §2, "What the generated plan holds"; estimators rules 7 and 8; statistics
§2.3, §3.3, §4.1). It replaces 1.x `allocate`.

1. **The headline need.** The independent cases the decision rule's test needs at its α and power:
   `stats.threshold_n` for a threshold test (with the grader's error written into the test), or
   `stats.paired_n` for a superiority or non-inferiority test (from the share of cases that flip
   between versions), multiplied by the inflation factor of each counted judge (§3.3). A judge
   with no current calibration is planned at `measurement.max_inflation`, the most the spec
   allows it to cost.
2. **Minimums.** Each use case gate's own need (rule 20), and each oversampled use case's factor
   × share × N (`design.quality_set.oversample`).
3. **Allocation.** N cases go by optimum allocation (`stats.optimum_allocation`: weight × spread ÷
   √cost, around the minimums), proportional to the weights until a baseline measures the spreads
   and costs. N is raised until the allocation still holds the headline need once its unequal
   weighting (`stats.allocation_design_effect`) and the clusters' measured design effect are
   counted.

What the plan can't know it says, with the flag that supplies it: before a baseline, a threshold
test needs the rate you expect (`--assumed-rate`) and a paired test the flip rate
(`--flip-rate`, from an A/A rerun or the last comparison). Nothing is assumed silently.
"""

from __future__ import annotations

import math

from . import stats
from .design import case_status
from .repo import POOLS, Eval
from .screen import passes as screen_passes
from .spec import Spec, quantity, use_case_weights, use_cases
from .util import ContractError, dump_yaml, load_yaml, now_iso

PLAN_FILE = "plan.yaml"
STATUSES = ("filled", "short", "scheduled", "out_of_scope")


def _judge_rates(ev: Eval, check_id: str) -> tuple[float, float] | None:
    """A judge's current (catch, clean) from its calibration, primary backend: 1.x calls them
    TNR and TPR. None when uncalibrated or stale."""
    from .calibrate import is_current, load_calibration
    from .judges import load_spec

    try:
        spec = load_spec(ev.judge_check_path(check_id))
    except Exception:
        return None
    cal = load_calibration(ev, spec)
    if not is_current(ev, spec, cal):
        return None
    m = (cal.get("backends") or {}).get(cal.get("primary") or spec.primary or "") or {}
    catch, clean = m.get("catch", m.get("tnr")), m.get("clean", m.get("tpr"))
    if isinstance(catch, (int, float)) and isinstance(clean, (int, float)):
        return float(catch), float(clean)
    return None


def _judges(ev: Eval, spec: Spec, mode: str | None) -> list[str]:
    """The counted judges that grade the quantity: the mode's check, or every counted judge."""
    out = []
    for fm in ev.failure_modes():
        cid = fm.get("check")
        if isinstance(cid, str) and ev.check_type(cid) == "judge" and (mode is None or fm.get("id") == mode):
            out.append(cid)
    return out


def _need(ev: Eval, spec: Spec, rule: dict, *, rate: float | None, flip_rate: float | None,
          kind: str | None, mode: str | None) -> dict:
    """The independent cases one rule needs, with its arithmetic. `rate` is the expected value of
    the quantity (a pass rate for pass_rate, a failure rate for failure_rate)."""
    test = rule.get("test")
    alpha = rule.get("alpha", spec.part("decision_rule").get("alpha"))
    power = rule.get("power", spec.part("decision_rule").get("power"))
    max_inf = spec.part("measurement").get("max_inflation") or 1.0
    out = {"test": test, "alpha": alpha, "power": power, "n_code": None, "inflation": None,
           "judges": [], "need": None, "reason": None}
    if kind is None:
        out["reason"] = "the estimand's quantity is not stated"
        return out
    fail = None if rate is None else (rate if kind == "failure_rate" else 1 - rate)
    judges = _judges(ev, spec, mode if kind == "failure_rate" else None)
    if test == "threshold":
        bar = rule.get("bar")
        if not isinstance(bar, (int, float)):
            out["reason"] = "a threshold test needs its bar"
            return out
        fbar = bar if kind == "failure_rate" else 1 - bar
        if fail is None:
            out["reason"] = ("needs the rate you expect under the alternative: run a baseline, or pass "
                             "--assumed-rate (the expected value of the quantity)")
            return out
        out["n_code"] = stats.threshold_n(fbar, fail, alpha, power)
        if out["n_code"] is None:
            out["reason"] = "the expected rate equals the bar: no test can show it is on one side"
            return out
        factor, n = 1.0, out["n_code"]
        for j in judges:
            r = _judge_rates(ev, j)
            if r is not None:
                nj = stats.threshold_n(fbar, fail, alpha, power, catch=r[0], clean=r[1])
                f = None if nj is None else nj / out["n_code"]
                out["judges"].append({"check": j, "catch": r[0], "clean": r[1], "inflation": f,
                                      "source": "calibration"})
            else:
                f = max_inf
                out["judges"].append({"check": j, "catch": None, "clean": None, "inflation": f,
                                      "source": "uncalibrated: planned at measurement.max_inflation"})
            if f is None:
                out["reason"] = f"judge {j} is no better than chance (J <= 0): no number of cases helps"
                return out
            factor = max(factor, f)
        n = math.ceil(out["n_code"] * factor - 1e-9)
        out.update({"inflation": factor, "need": n,
                    "rule": f"threshold_n(bar {fbar:g}, rate {fail:g}, α {alpha:g}, power {power:g})"})
        return out
    if test in ("superiority", "non_inferiority"):
        margin = rule.get("margin")
        if not isinstance(margin, (int, float)):
            out["reason"] = f"a {test.replace('_', '-')} test needs its margin"
            return out
        if flip_rate is None:
            out["reason"] = ("needs the share of cases that flip between versions: pass --flip-rate, "
                             "from an A/A rerun of the baseline or the last comparison (statistics §4.3)")
            return out
        out["n_code"] = stats.paired_n(flip_rate, margin, alpha, power)
        factor = 1.0
        for j in judges:
            r = _judge_rates(ev, j)
            f = (stats.judge_inflation(fail, r[0], r[1]) if r is not None and fail is not None
                 and 0 < fail < 1 else None)
            src = "calibration" if f is not None else (
                "uncalibrated: planned at measurement.max_inflation" if r is None else
                "no expected failure rate to read it at: planned at measurement.max_inflation")
            if f is None:
                f = max_inf
            out["judges"].append({"check": j, "catch": r[0] if r else None, "clean": r[1] if r else None,
                                  "inflation": f, "source": src})
            factor = max(factor, f)
        out.update({"inflation": factor, "need": math.ceil(out["n_code"] * factor - 1e-9),
                    "rule": f"paired_n(flip rate {flip_rate:g}, margin {margin:g}, α {alpha:g}, power {power:g})"})
        return out
    out["reason"] = "no decision-rule test stated"
    return out


def plan(ev: Eval, assumed_rate: float | None = None, flip_rate: float | None = None,
         total: int | None = None) -> dict:
    spec = ev.spec()
    blocked = [i.as_dict() for i in spec.blocked("plan")]
    rule = spec.part("decision_rule")
    kind, mode = quantity(spec)
    weights, source = use_case_weights(spec)
    ucs = use_cases(spec)
    over = (spec.part("design").get("quality_set") or {}).get("oversample") or {}
    from .report_v2 import measured

    base = measured(ev)
    base_uc = base.get("use_cases") or {}

    def rate_for(uc: str | None) -> tuple[float | None, str | None]:
        if assumed_rate is not None:
            return assumed_rate, "--assumed-rate"
        v = base.get("theta") if uc is None else (base_uc.get(uc) or {}).get("rate")
        return (v, f"baseline {', '.join(base['runs'])}") if v is not None else (None, None)

    r0, r0_src = rate_for(None)
    head = _need(ev, spec, rule, rate=r0, flip_rate=flip_rate, kind=kind, mode=mode)
    head["rate"], head["rate_source"] = r0, r0_src

    gates = []
    for g in rule.get("use_case_gates") or []:
        if not isinstance(g, dict) or g.get("use_case") not in {u["id"] for u in ucs}:
            continue
        r, src = rate_for(g["use_case"])
        n = _need(ev, spec, {**g, "alpha": g.get("alpha", rule.get("alpha")),
                             "power": g.get("power", rule.get("power"))},
                  rate=r, flip_rate=flip_rate, kind=kind, mode=mode)
        gates.append({"use_case": g["use_case"], **n, "rate": r, "rate_source": src})

    cluster_deff = base.get("design_effect") if isinstance(base.get("design_effect"), (int, float)) else 1.0
    strata = {u["id"]: {"weight": (weights or {}).get(u["id"]),
                        "pass_rate": (base_uc.get(u["id"]) or {}).get("rate") if kind == "pass_rate" else
                        (None if (base_uc.get(u["id"]) or {}).get("rate") is None
                         else 1 - base_uc[u["id"]]["rate"]),
                        "cost": (base_uc.get(u["id"]) or {}).get("cost_per_trial")} for u in ucs}
    gate_min = {g["use_case"]: g["need"] for g in gates if g["need"]}

    def minimums(n_total: int) -> dict[str, int]:
        out = dict(gate_min)
        shares = {u["id"]: u.get("share") for u in ucs}
        for uc, f in over.items():
            if isinstance(f, (int, float)) and isinstance(shares.get(uc), (int, float)):
                out[uc] = max(out.get(uc, 0), math.ceil(f * shares[uc] * n_total - 1e-9))
        return out

    alloc, n_total, reason, deff_w = None, None, None, None
    if weights is None:
        reason = "the weights are not all stated (rule 2): nothing to allocate by"
    elif total is not None:
        n_total = total
        alloc = stats.optimum_allocation(strata, n_total, minimums(n_total))
        deff_w = stats.allocation_design_effect(weights, alloc["allocation"]) if alloc else None
    elif head["need"] is None:
        reason = "the headline need is unknown: " + (head["reason"] or "") + "; or pass --total N"
    else:
        n_total = head["need"]
        for _ in range(50):
            alloc = stats.optimum_allocation(strata, n_total, minimums(n_total))
            if alloc is None:
                break
            deff_w = stats.allocation_design_effect(weights, alloc["allocation"])
            want = math.ceil(head["need"] * (deff_w or 1.0) * cluster_deff - 1e-9)
            if want <= n_total:
                break
            n_total = want
    if alloc is None and reason is None and weights is not None:
        reason = "the allocation could not be computed"

    prior = load_yaml(ev.p(PLAN_FILE)) or {}
    marks = {(r.get("use_case"), r.get("pool")): r for r in prior.get("rows") or []}
    try:
        cases = ev.cases(include_dropped=False)
    except ContractError:
        cases = []
    have: dict[tuple, dict] = {}
    for c in cases:
        st = case_status(ev, c)
        d = have.setdefault((st["use_case"], st["pool"]), {"exists": 0, "drawn": 0, "screened": 0})
        d["exists"] += 1
        d["drawn"] += 1 if st["counts"] else 0
        d["screened"] += 1 if screen_passes(c.get("screen")) else 0
    mins = minimums(n_total) if n_total else dict(gate_min)
    rows = []
    for u in ucs:
        uc = u["id"]
        for pool in POOLS:
            h = have.get((uc, pool), {"exists": 0, "drawn": 0, "screened": 0})
            if pool == "quality":
                target = (alloc or {}).get("allocation", {}).get(uc)
                why_min = [w for w, ok in (("gate", uc in gate_min), ("oversample", uc in over)) if ok]
                row = {"use_case": uc, "pool": pool, "share": u.get("share"),
                       "weight": (weights or {}).get(uc), "target": target,
                       "minimum": mins.get(uc), "minimum_from": why_min, **h}
                full = target is not None and h["drawn"] >= target
            else:
                row = {"use_case": uc, "pool": pool, "share": u.get("share"), "weight": None,
                       "target": None, "minimum": None, "minimum_from": [], **h,
                       "rule": "sized by the coverage list it must reach, not by power (statistics §2.5)"}
                full = False
            old = marks.get((uc, pool)) or {}
            if full:
                status = "filled"
            elif old.get("status") in ("scheduled", "out_of_scope"):
                status = old["status"]
            else:
                status = "short" if pool == "quality" else old.get("status") or "short"
            row["status"], row["reason"] = status, old.get("reason")
            rows.append(row)
    return {
        "generated": now_iso(),
        "eval": {"id": spec.eval_id, "version": spec.resolved.get("version")},
        "blocked": blocked,
        "decision_rule": {k: rule.get(k) for k in ("test", "quantity", "bar", "margin", "alpha", "power")},
        "assumptions": {"rate": {"value": r0, "source": r0_src},
                        "flip_rate": {"value": flip_rate, "source": "--flip-rate" if flip_rate is not None else None},
                        "spreads_and_costs": "measured by the baseline" if base_uc else
                        "assumed equal until a baseline (proportional allocation)",
                        "cluster_design_effect": cluster_deff,
                        "total": "--total" if total is not None else "from the headline need"},
        "headline": head,
        "gates": gates,
        "quality_set": {"total": n_total, "weights": weights, "weights_source": source,
                        "allocation_design_effect": deff_w,
                        "method": (alloc or {}).get("method"), "spread": (alloc or {}).get("spread"),
                        "cost": (alloc or {}).get("cost"), "at_minimum": (alloc or {}).get("at_minimum"),
                        "shortfall": (alloc or {}).get("shortfall"), "reason": reason},
        "rows": rows,
    }


def render(p: dict) -> str:
    h, q = p["headline"], p["quality_set"]
    lines = [f"plan for {p['eval']['id']} {p['eval']['version']}"]
    for b in p["blocked"]:
        lines.append(f"  blocked by {b['field']}: {b['why']}")
    if h["need"] is not None:
        j = f" x {h['inflation']:.2f} (judges)" if h["inflation"] and h["inflation"] > 1 else ""
        lines.append(f"  headline: {h['test']} needs {h['need']} independent cases ({h['rule']}: "
                     f"{h['n_code']}{j})")
    else:
        lines.append(f"  headline: unknown: {h['reason']}")
    for g in p["gates"]:
        lines.append(f"  gate {g['use_case']}: " + (f"{g['need']} cases" if g["need"] else f"unknown: {g['reason']}"))
    if q["total"] is not None:
        d = q["allocation_design_effect"]
        lines.append(f"  quality set: {q['total']} cases, {q['method']}"
                     + (f"; weighting design effect {d:.2f}" if d else ""))
        if q["shortfall"]:
            lines.append(f"  the minimums alone exceed the budget by {q['shortfall']} cases")
    else:
        lines.append(f"  quality set: not sized: {q['reason']}")
    lines.append("")
    lines.append(f"  {'use case':<24} {'pool':<12} {'weight':>7} {'target':>6} {'min':>5} {'have':>5} "
                 f"{'drawn':>5} {'screened':>8}  status")
    for r in p["rows"]:
        def f(v):
            return "-" if v is None else str(v)
        w = "-" if r["weight"] is None else f"{r['weight']:.3f}"
        lines.append(f"  {r['use_case']:<24} {r['pool']:<12} {w:>7} {f(r['target']):>6} {f(r['minimum']):>5} "
                     f"{r['exists']:>5} {r['drawn']:>5} {r['screened']:>8}  {r['status']}"
                     + (f" - {r['reason']}" if r.get("reason") else ""))
    return "\n".join(lines)


def write(ev: Eval, p: dict) -> None:
    header = ("# Written by `aot-evals plan --write` (docs/v2-design.md §2). Edit only `status` and\n"
              "# `reason`: status is filled | short | scheduled | out_of_scope; scheduled and\n"
              "# out_of_scope need a reason. Everything else is recomputed.\n")
    ev.p(PLAN_FILE).write_text(header + dump_yaml(p))
