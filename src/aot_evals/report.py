"""C18 `report`: write `evals/report/report.json` (docs/method.md §8).

Everything here is recomputed from per-trial records; nothing is pre-rounded; unknown values are
`null`, never `0`. The report gates (G1-G13, docs/method.md §10) are evaluated here and decide which
numbers may appear: a refused number is removed or greyed, and its gate says why.
"""

from __future__ import annotations

import json
from collections import defaultdict

from . import stats
from .checks import declares_agent_report
from .gates import manifest_problems, taxonomy_problems, untracked_cases
from .repo import SETS, Evals
from .screen import passes as screen_passes
from .util import now_iso, write_json

SCHEMA = "aot-evals/report@1"


# The fields that name the build that ran (the agent and how it was invoked), as opposed to
# what measured it (cases, checks, judges).
BUILD_FIELDS = ("agent_commit", "harness", "model_ids", "invoke", "fakes_sha256", "simulator")


def manifest_view(m: dict) -> dict:
    """The fields of a manifest that define what was measured and on what."""
    return {
        "agent_commit": m.get("agent_commit"),
        "agent_dirty": m.get("agent_dirty"),
        "harness": m.get("harness"),
        "model_ids": (m.get("agent") or {}).get("model_ids"),
        "model_ids_observed": (m.get("agent") or {}).get("model_ids_observed"),
        "invoke": dict(m.get("invoke") or {}),
        "fakes_sha256": m.get("fakes_sha256"),
        "simulator": m.get("simulator"),
        "case_set": (m.get("case_set") or {}).get("files") or (m.get("case_set") or {}).get("sha256"),
        "checks": m.get("checks"),
        "judges": sorted((j.get("check"), j.get("model"), j.get("judge_sha"), j.get("backend"))
                         for j in m.get("judge_backends") or []),
    }


def build_key(m: dict) -> str:
    v = manifest_view(m)
    return json.dumps({f: v[f] for f in BUILD_FIELDS}, sort_keys=True, default=str)


def run_passes(manifests: list[dict]) -> dict[str, int]:
    """run id -> pass over the suite. Runs of one build with the same k over disjoint case sets
    (a suite split by category to pace a rate-limited runtime) are one pass; a repeat of a case
    starts another. A variance band compares passes, never a pass with a part of one."""
    passes: list[tuple[str, set]] = []
    out = {}
    for m in sorted(manifests, key=lambda m: m.get("started") or ""):
        key = build_key(m) + f"|k={m.get('k')}"
        ids = set((m.get("case_set") or {}).get("ids") or [])
        for i, (k, seen) in enumerate(passes):
            if k == key and not (seen & ids):
                seen |= ids
                out[m["run_id"]] = i
                break
        else:
            passes.append((key, set(ids)))
            out[m["run_id"]] = len(passes) - 1
    return out


class Context:
    """The runs a report covers, with their records indexed for the computations below."""

    def __init__(self, ev: Evals, run_ids: list[str]):
        self.ev = ev
        self.manifests = [m for m in (ev.run_manifest(r) for r in run_ids) if m]
        self.attempts: list[dict] = []
        self.check_lines: list[dict] = []
        for m in self.manifests:
            for r in ev.run_records(m["run_id"]):
                (self.attempts if r.get("kind") == "attempt" else self.check_lines).append(r)
        self.cases = {c["id"]: c for c in ev.cases() if c.get("id")}
        self.untracked = set(untracked_cases(ev))
        self.k = max((m.get("k") or 0 for m in self.manifests), default=None) or None
        self.pass_of = run_passes(self.manifests)
        self.trials_of: dict[str, int] = defaultdict(int)  # case id -> trials planned across runs
        for m in self.manifests:
            for cid in (m.get("case_set") or {}).get("ids") or []:
                self.trials_of[cid] += m.get("k") or 0

        self.checks_by_attempt: dict[tuple, list[dict]] = defaultdict(list)
        for c in self.check_lines:
            self.checks_by_attempt[(c["run_id"], c["case_id"], c["trial"], c["attempt"])].append(c)
        self.judges = judge_states(ev)
        self._recompute_passes()

    def _recompute_passes(self) -> None:
        """A trial's pass, from its check lines: code checks always count; a judge counts only when
        it is calibrated on its current version, and its verdict is re-thresholded with the
        calibrated threshold (G3). The as-written code verdict is kept as `passed_code`."""
        for a in self.attempts:
            a["passed_code"] = a.get("passed")
            if a.get("outcome") != "ok" or a.get("instrument_error") or a["case_id"] not in self.cases:
                continue
            verdicts = []
            for line in self.checks_by_attempt.get((a["run_id"], a["case_id"], a["trial"], a["attempt"]), []):
                if line.get("type") != "judge":
                    verdicts.append(line.get("passed"))
                    continue
                st = self.judges.get(line["check_id"])
                counts = bool(st and st["calibrated"] and line.get("judge_sha") == st["sha"]
                              and line.get("backend") == st["backend"])
                line["counted"] = counts
                if counts:
                    score = line.get("score")
                    line["verdict"] = None if score is None else score >= st["threshold_or_default"]
                    verdicts.append(line["verdict"])
            if any(v is None for v in verdicts):
                a["passed"] = None
                a["instrument_error"] = a.get("instrument_error") or "a counted judge returned no verdict"
            else:
                a["passed"] = all(verdicts) if verdicts else None

    def finals(self) -> list[dict]:
        return [a for a in self.attempts if a.get("final")]

    def gated(self, case_id: str) -> bool:
        """Whether a case may count toward gated numbers: screened (G8) and committed (G12)."""
        case = self.cases.get(case_id)
        if not case or not screen_passes(case.get("screen")):
            return False
        return not any(case["_path"] in u or u.endswith(case["_path"]) for u in self.untracked)


def judge_states(ev: Evals) -> dict[str, dict]:
    """Per judge check: its spec, current calibration and reliability, and whether it counts."""
    from .calibrate import is_current, load_calibration
    from .judges import load_spec
    from .labels import load_labels
    from .reliability import load_reliability

    out: dict[str, dict] = {}
    for fm in ev.failure_modes():
        for cid in fm.get("checks") or []:
            if cid in out or ev.check_type(cid) != "judge":
                continue
            st = {"spec": None, "sha": None, "backend": None, "calibrated": False, "labels": 0,
                  "cal": None, "rel": None, "metrics": None, "threshold_or_default": 0.5,
                  "reasons": [], "failure_mode": fm.get("id")}
            out[cid] = st
            try:
                spec = load_spec(ev.judge_check_path(cid))
            except Exception as e:
                st["reasons"].append(f"invalid judge spec: {e}")
                continue
            st.update(spec=spec, sha=spec.sha(), backend=spec.primary, labels=len(load_labels(ev, spec)))
            if spec.problems():
                st["reasons"] += spec.problems()
                continue
            cal = load_calibration(ev, spec)
            if not cal:
                st["reasons"].append("not calibrated (C10)")
            elif not is_current(ev, spec, cal):
                st["reasons"].append("calibration is stale: the judge or its labels changed since")
            else:
                st["cal"] = cal
                st["metrics"] = (cal.get("backends") or {}).get(spec.primary)
                if cal.get("primary") != spec.primary:
                    st["reasons"].append(f"calibrated with primary {cal.get('primary')}, now {spec.primary}")
                elif cal.get("status") != "calibrated":
                    st["reasons"] += cal.get("status_reasons") or ["below floors"]
                else:
                    st["calibrated"] = True
                if st["metrics"] and st["metrics"].get("threshold") is not None:
                    st["threshold_or_default"] = st["metrics"]["threshold"]
            rel = load_reliability(ev, spec)
            st["rel"] = rel if rel and rel.get("judge_sha") == spec.sha() else None
    return out


def default_runs(ev: Evals) -> list[str]:
    base = ev.latest_run("baseline")
    if base:
        return [base["run_id"]]
    others = [m for m in ev.runs() if m.get("finished") and m.get("purpose") != "smoke"]
    return [others[-1]["run_id"]] if others else []


# ---- plane A ------------------------------------------------------------------------------

def _passes_by_case(finals: list[dict]) -> dict[str, list[bool]]:
    out: dict[str, list[bool]] = defaultdict(list)
    for a in sorted(finals, key=lambda a: (a["run_id"], a["trial"])):
        if a.get("passed") is not None:
            out[a["case_id"]].append(bool(a["passed"]))
    return out


def correctness(ctx: Context, finals: list[dict], set_name: str) -> dict:
    by_case = _passes_by_case(finals)
    rate = stats.clustered_pass_rate(list(by_case.values()))
    # A case's trials are those of the runs that included it: runs split by category each
    # cover some cases, so summing k over every run left pass^k null.
    complete = [v for c, v in by_case.items() if len(v) == ctx.trials_of.get(c)]
    pass_pow_k = (sum(1 for v in complete if all(v)) / len(complete)) if complete and ctx.k and ctx.k > 1 else None
    pass_pow_k_reason = None
    if pass_pow_k is None and by_case:
        pass_pow_k_reason = ("k = 1: pass^k needs repeated trials" if not ctx.k or ctx.k < 2 else
                             "no case has a scored result on every planned trial (operational "
                             "failures or instrument errors left gaps)")
    flaky = sum(1 for v in by_case.values() if len(v) > 1 and 0 < sum(v) < len(v)) if ctx.k and ctx.k > 1 else None

    per_repeat: dict[tuple, list[bool]] = defaultdict(list)
    for a in finals:
        if a.get("passed") is not None:
            per_repeat[(ctx.pass_of.get(a["run_id"]), a["trial"])].append(bool(a["passed"]))
    rates = [sum(v) / len(v) for v in per_repeat.values() if v]
    band = [min(rates), max(rates)] if len(rates) >= 2 else None
    pass_rate = None
    if rate:
        pass_rate = {"point": rate["point"], "ci": rate["ci"], "n": rate["n"],
                     "n_cases": rate["n_cases"], "k": ctx.k, "set": set_name,
                     "ci_method": rate["ci_method"]}
    return {"pass_rate": pass_rate, "pass_pow_k": pass_pow_k, "pass_pow_k_reason": pass_pow_k_reason,
            "flaky": flaky, "variance_band": band}


# ---- plane B ------------------------------------------------------------------------------

BUDGET_KEYS = {
    # budgets.yaml key -> (operational field, direction)
    "cost_per_success_usd": ("cost_per_success", "max"),
    "cost_per_run_usd": ("cost_per_run", "max"),
    "latency_p50_ms": ("latency_p50", "max"),
    "latency_p90_ms": ("latency_p90", "max"),
    "error_rate": ("error_rate_point", "max"),
    "tokens_per_run": ("tokens_per_run", "max"),
    "cache_hit_rate_min": ("cache_hit_rate", "min"),
}


def operational(attempts: list[dict], budget: dict | None) -> dict:
    trials = {(a["run_id"], a["case_id"], a["trial"]) for a in attempts}
    n_trials = len(trials)
    costs = [a["cost_usd"] for a in attempts if a.get("cost_usd") is not None]
    total_cost = sum(costs) if costs else None
    successes = sum(1 for a in attempts if a.get("final") and a.get("passed") is True)
    latencies = [a["latency_ms"] for a in attempts if a.get("latency_ms") is not None]

    def total(key):
        vals = [a[key] for a in attempts if a.get(key) is not None]
        return sum(vals) if vals else None

    tin, tout, tcached, tools = (total("tokens_input"), total("tokens_output"),
                                 total("tokens_cached"), total("tool_calls"))
    outcomes: dict[str, int] = defaultdict(int)
    for a in attempts:
        outcomes[a.get("outcome") or "instrument_error"] += 1
    agent_attempts = [a for a in attempts if a.get("outcome") is not None]
    errors = sum(1 for a in agent_attempts if a["outcome"] != "ok")
    err_ci = stats.wilson(errors, len(agent_attempts))
    op = {
        "n_trials": n_trials,
        "n_attempts": len(attempts),
        "cost_total": total_cost,
        "cost_per_run": total_cost / n_trials if total_cost is not None and n_trials else None,
        "cost_per_success": total_cost / successes if total_cost is not None and successes else None,
        "successes": successes,
        "latency_p50": stats.percentile(latencies, 50),
        "latency_p90": stats.percentile(latencies, 90),
        "tokens_input": tin / n_trials if tin is not None and n_trials else None,
        "tokens_output": tout / n_trials if tout is not None and n_trials else None,
        "tokens_per_run": (((tin or 0) + (tout or 0)) / n_trials
                           if (tin is not None or tout is not None) and n_trials else None),
        "cache_hit_rate": tcached / tin if tcached is not None and tin else None,
        "tool_calls": tools / n_trials if tools is not None and n_trials else None,
        "outcomes": dict(outcomes),
        "error_rate": ({"point": errors / len(agent_attempts), "ci": list(err_ci), "n": len(agent_attempts)}
                       if agent_attempts else None),
        "retries": sum(1 for a in attempts if a.get("attempt", 0) > 0),
        "agent_retries": total("retries"),
        "killed": sum(1 for a in attempts if a.get("killed")),
        "budget": budget or {},
        "budget_status": None,
        "budget_breaches": [],
    }
    if budget:
        compared = 0
        for key, limit in budget.items():
            if key not in BUDGET_KEYS or limit is None:
                continue
            field, direction = BUDGET_KEYS[key]
            value = op["error_rate"]["point"] if field == "error_rate_point" and op["error_rate"] else op.get(field)
            if value is None:
                continue
            compared += 1
            if (direction == "max" and value > limit) or (direction == "min" and value < limit):
                op["budget_breaches"].append({"budget": key, "limit": limit, "actual": value})
        if compared:
            op["budget_status"] = "over" if op["budget_breaches"] else "within"
    return op


# ---- sections -----------------------------------------------------------------------------

def category_rows(ctx: Context) -> list[dict]:
    ev = ctx.ev
    cats = {c["id"]: c for c in ev.categories() if c.get("id")}
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for a in ctx.attempts:
        groups[(a.get("category"), a.get("set"))].append(a)
    rows = []
    order = {"high": 0, "medium": 1, "low": 2}
    for (cid, set_name), attempts in sorted(
            groups.items(), key=lambda kv: (order.get((cats.get(kv[0][0]) or {}).get("worth"), 3),
                                            str(kv[0][0]), str(kv[0][1]))):
        if cid is None:
            continue
        cat = cats.get(cid) or {}
        finals = [a for a in attempts if a.get("final")]
        gated_finals = [a for a in finals if ctx.gated(a["case_id"])]
        ungated_finals = [a for a in finals if not ctx.gated(a["case_id"])]
        row = {
            "id": cid,
            "worth": cat.get("worth"),
            "simple": cat.get("simple"),
            "observed_share": cat.get("observed_share"),
            "n_cases": len({a["case_id"] for a in gated_finals}),
            **correctness(ctx, gated_finals, set_name),
            "operational": operational(attempts, ev.budget_for(cid)),
            "excluded": None,
        }
        if ungated_finals:
            ex = correctness(ctx, ungated_finals, set_name)
            row["excluded"] = {"n_cases": len({a["case_id"] for a in ungated_finals}),
                               "reason": "unscreened or uncommitted cases (G8, G12)",
                               "pass_rate": ex["pass_rate"]}
        rows.append(row)
    return rows


def quality_estimate(ctx: Context, gate_ok: bool) -> dict | None:
    if not gate_ok:
        return None
    cats = {c["id"]: c for c in ctx.ev.categories() if c.get("id")}
    strata = []
    weights = {}
    for cid, cat in cats.items():
        share = cat.get("observed_share")
        finals = [a for a in ctx.finals() if a.get("category") == cid and a.get("set") == "quality_estimate"
                  and a.get("passed") is not None and ctx.gated(a["case_id"])]
        if not isinstance(share, (int, float)) or not finals:
            continue
        # Size each stratum by cases, not trials: trials of one case are not independent.
        per_case = _passes_by_case(finals)
        strata.append((share, sum(sum(v) / len(v) for v in per_case.values()), len(per_case)))
        weights[cid] = share
    est = stats.weighted_estimate(strata)
    if est:
        wsum = sum(weights.values())
        est["weights"] = {k: v / wsum for k, v in weights.items()}
        est["missing_categories"] = sorted(set(cats) - set(weights))
    return est


def check_rows(ctx: Context) -> list[dict]:
    ev = ctx.ev
    fm_of = {}
    for fm in ev.failure_modes():
        for cid in fm.get("checks") or []:
            fm_of.setdefault(cid, fm)
    final_keys = {(a["run_id"], a["case_id"], a["trial"], a["attempt"]) for a in ctx.finals()}
    fires: dict[str, int] = defaultdict(int)
    sole: dict[str, int] = defaultdict(int)
    evaluated: dict[str, int] = defaultdict(int)
    for key, lines in ctx.checks_by_attempt.items():
        if key not in final_keys:
            continue
        def verdict(line):
            return line.get("verdict") if line.get("type") == "judge" else line.get("passed")
        failed = [line["check_id"] for line in lines if verdict(line) is False]
        for line in lines:
            if verdict(line) is None:
                continue
            evaluated[line["check_id"]] += 1
            if verdict(line) is False:
                fires[line["check_id"]] += 1
                if len(failed) == 1:
                    sole[line["check_id"]] += 1
    rows = []
    for cid, fm in sorted(fm_of.items()):
        ctype = ev.check_type(cid)
        judge = None
        if ctype == "judge":
            judge = judge_block(ctx, cid)
        rows.append({
            "id": cid, "type": ctype, "failure_mode": fm.get("id"),
            "trigger_rate": fires[cid] / evaluated[cid] if evaluated[cid] else None,
            "sole_failure_rate": sole[cid] / fires[cid] if fires[cid] else None,
            "evaluations": evaluated[cid] or None,
            "judge": judge,
        })
    return rows


def judge_block(ctx: Context, cid: str) -> dict:
    st = ctx.judges.get(cid) or {}
    spec, m, rel = st.get("spec"), st.get("metrics") or {}, st.get("rel") or {}
    backend_cfg = spec.backends.get(spec.primary, {}) if spec else {}
    rel_b = (rel.get("backends") or {}).get(st.get("backend")) or {}
    cross = [p for p in rel.get("cross_family") or [] if st.get("backend") in p["backends"]]
    lines = [line for line in ctx.check_lines if line.get("check_id") == cid and line.get("cost_usd") is not None]
    return {
        "backend": backend_cfg.get("type"), "backend_name": st.get("backend"),
        "model": backend_cfg.get("model"), "model_family": backend_cfg.get("family"),
        "agent_model_family": ctx.ev.agent().get("model_family"),
        "version": spec.version if spec else None, "mode": spec.mode if spec else None,
        "tpr": m.get("tpr"), "tpr_ci": m.get("tpr_ci"), "tnr": m.get("tnr"), "tnr_ci": m.get("tnr_ci"),
        "labels": st.get("labels", 0), "kappa": m.get("kappa"), "confusion": m.get("confusion"),
        "threshold": m.get("threshold"), "holdout": m.get("holdout"),
        "self_consistency": rel_b.get("self_consistency"),
        "cross_family": cross[0]["agreement"] if cross else None,
        "cross_family_kappa": cross[0]["kappa"] if cross else None,
        "three_level": rel.get("three_level"),
        "confidence_calibration": m.get("confidence_calibration") or {"ece": None, "brier": None},
        "cost_per_judgement": m.get("cost_per_judgement"),
        "run_cost_usd": sum(line["cost_usd"] for line in lines) if lines else None,
        "backends_compared": {b: {k: v.get(k) for k in ("type", "model", "family", "tpr", "tnr", "kappa",
                                                          "cost_per_judgement", "labels")}
                              for b, v in ((st.get("cal") or {}).get("backends") or {}).items()},
        "recommendation": (st.get("cal") or {}).get("recommendation"),
        "status": "calibrated" if st.get("calibrated") else "uncalibrated",
        "status_reasons": st.get("reasons") or [],
    }


def coverage(ev: Evals, g5_ok: bool) -> dict:
    t = ev.taxonomy()
    entries = [e.get("id") for e in t.get("entries") or [] if e.get("id")]
    fms = [f.get("id") for f in ev.failure_modes() if f.get("id")]
    counts: dict[tuple, int] = defaultdict(int)
    for c in ev.cases(include_dropped=False):
        # every mode the case is checked against, including side-effect modes that run on all cases
        modes = [fm.get("id") for fm in ev.failure_modes_for_case(c)]
        for e in c.get("taxonomy_entries") or []:
            for m in modes:
                counts[(e, m)] += 1
    # E8 triage: an entry may declare failure modes that cannot occur for it, with a reason.
    na = {e.get("id"): dict(e.get("not_applicable") or {}) for e in t.get("entries") or [] if e.get("id")}
    cells = []
    for e in entries:
        for m in fms:
            cell = {"taxonomy_entry": e, "failure_mode": m, "n": counts[(e, m)]}
            if m in na.get(e, {}):
                cell["not_applicable"] = na[e][m] or "declared not applicable"
            cells.append(cell)
    cells.sort(key=lambda c: (c["n"] > 0 or "not_applicable" in c, c["taxonomy_entry"], c["failure_mode"]))
    return {"list": "external" if g5_ok else "MISSING",
            "source": _taxonomy_source(t),
            "empty_cells": sum(1 for c in cells if c["n"] == 0 and "not_applicable" not in c),
            "not_applicable_cells": sum(1 for c in cells if "not_applicable" in c),
            "cells": cells}


def _taxonomy_source(t: dict) -> str:
    src = t.get("source")
    if not src:
        return "MISSING"
    if isinstance(src, dict):
        return str(src.get("document") or src.get("url") or src.get("path") or "MISSING")
    return str(src)


def case_rows(ctx: Context) -> list[dict]:
    by_case: dict[str, list[dict]] = defaultdict(list)
    for a in ctx.attempts:
        by_case[a["case_id"]].append(a)
    rows = []
    for cid, attempts in sorted(by_case.items()):
        case = ctx.cases.get(cid) or {}
        s = case.get("screen") or {}
        trials = []
        for a in sorted(attempts, key=lambda a: (a["run_id"], a["trial"], a["attempt"])):
            lines = ctx.checks_by_attempt.get((a["run_id"], cid, a["trial"], a["attempt"]), [])
            trials.append({
                "run": a["run_id"], "trial": a["trial"], "attempt": a["attempt"],
                "final": a.get("final"), "outcome": a.get("outcome"), "passed": a.get("passed"),
                "error": a.get("error") or None, "instrument_error": a.get("instrument_error"),
                "checks": [{"id": line["check_id"], "type": line.get("type"),
                            "passed": line.get("verdict") if line.get("type") == "judge" else line.get("passed"),
                            "counted": line.get("counted", True), "score": line.get("score"),
                            "detail": line.get("detail")} for line in lines],
                "operational": {k: a.get(k) for k in ("cost_usd", "latency_ms", "tokens_input",
                                                      "tokens_output", "tokens_cached",
                                                      "tool_calls", "retries", "killed")},
                "state_diff": a.get("state_diff"), "trace_ref": a.get("trace_ref"),
            })
        prov = case.get("provenance") or {}
        rows.append({
            "id": cid, "set": case.get("set"), "category": case.get("category"),
            "provenance": prov.get("source"), "synthetic": prov.get("synthetic"),
            "gated": ctx.gated(cid),
            "screen": {"human_read": s.get("human_read"),
                       "reference_passes": s.get("reference_passes"),
                       "donothing_fails": s.get("donothing_fails")},
            "inputs": case.get("inputs"), "trigger": case.get("trigger"),
            "start_state": case.get("start_state"),
            "expected_end_state": case.get("expected_end_state"),
            "trials": trials,
        })
    return rows


# ---- gates G1-G13 ---------------------------------------------------------------------------

def _g(gid: str, ok: bool | None, detail: str, blocks: list[str]) -> dict:
    status = {True: "pass", False: "fail", None: "not_applicable"}[ok]
    return {"id": gid, "status": status, "detail": detail, "blocks": blocks}


def evaluate_gates(ctx: Context) -> list[dict]:
    ev = ctx.ev
    gates = []

    # G1: condition record
    if not ctx.manifests:
        gates.append(_g("G1", False, "no run to report on", ["report"]))
    else:
        probs = [p for m in ctx.manifests for p in manifest_problems(m)]
        gates.append(_g("G1", not probs, "; ".join(probs) or "condition record complete", ["report"]))

    # G2: k = 1
    if ctx.k is None:
        gates.append(_g("G2", None, "no runs", []))
    else:
        gates.append(_g("G2", ctx.k > 1, f"k = {ctx.k}", ["improvement", "regression", "drift"]))

    # G3: judges under 60 labels, or not calibrated (TPR/TNR below floor, stale, unmeasured)
    if not ctx.judges:
        gates.append(_g("G3", None, "no judge checks", []))
    else:
        bad = {cid: st for cid, st in ctx.judges.items() if not st["calibrated"]}
        detail = "; ".join(f"{cid}: {st['labels']} labels, " + ", ".join(st["reasons"] or ["uncalibrated"])
                           for cid, st in bad.items())
        gates.append(_g("G3", not bad, detail or "every judge calibrated on >= 60 labels by TPR/TNR",
                        [f"check:{cid}" for cid in bad]))

    # G4: a generative judge from the agent's own family doing pairwise or preference grading
    agent_family = ev.agent().get("model_family")
    pairwise = {cid: st for cid, st in ctx.judges.items() if st["spec"] and st["spec"].mode == "pairwise"}
    if not pairwise:
        gates.append(_g("G4", None, "no pairwise or preference judge in use", []))
    else:
        same = []
        for cid, st in pairwise.items():
            b = st["spec"].backends.get(st["backend"], {})
            if (b.get("type") != "systemone" and agent_family and b.get("family") == agent_family
                    and not st["spec"].meta.get("same_family_justification")):
                same.append(cid)
        gates.append(_g("G4", not same, f"same-family generative pairwise judges: {same}" if same else
                        "pairwise judges are a different family from the agent, or justified",
                        [f"check:{c}" for c in same]))

    # G5: coverage list
    tp = taxonomy_problems(ev)
    gates.append(_g("G5", not tp, "; ".join(tp) or f"external list: {_taxonomy_source(ev.taxonomy())}",
                    ["coverage"]))

    # G6: quality from the error-finding set
    qe_cases = [c for c in ctx.cases.values() if c.get("set") == "quality_estimate" and ctx.gated(c["id"])]
    shares_traced = all(c.get("share_source") in {e.get("id") for e in ev.exports()}
                        for c in ev.categories())
    g6_ok = bool(qe_cases) and shares_traced
    detail = ("quality-estimate set present, weights traced to exports" if g6_ok else
              "no screened quality-estimate cases" if not qe_cases else
              "category shares do not trace to an export (share_source)")
    gates.append(_g("G6", g6_ok, detail + "; error-finding numbers are never called quality",
                    [] if g6_ok else ["quality"]))

    # G7: comparison without a paired test
    gates.append(_g("G7", None, "no comparison in this report", []))

    # G8: unscreened cases
    in_run = {a["case_id"] for a in ctx.attempts if a["case_id"] in ctx.cases}
    unscreened = sorted(c for c in in_run if not screen_passes(ctx.cases[c].get("screen")))
    gates.append(_g("G8", not unscreened,
                    f"{len(unscreened)} unscreened case(s) excluded from gated numbers: "
                    f"{unscreened[:10]}" if unscreened else "every case in the run passed the screen",
                    [f"case:{c}" for c in unscreened]))

    # G9: simulated user not reported per simulator
    sims = {m.get("simulator") for m in ctx.manifests if m.get("simulator")}
    gates.append(_g("G9", None if not sims else len(sims) == 1,
                    "no simulated user" if not sims else f"simulators: {sorted(map(str, sims))}",
                    [] if len(sims) <= 1 else ["aggregate"]))

    # G10: checks relying on the agent's own report
    declared = [c for fm in ev.failure_modes() for c in fm.get("checks") or []
                if ev.check_type(c) == "code" and declares_agent_report(ev.code_check_path(c))]
    sensitive = sorted({c for case in ctx.cases.values()
                        for c in (case.get("screen") or {}).get("claim_sensitive_checks") or []})
    bad = sorted(set(declared) | set(sensitive))
    gates.append(_g("G10", not bad, f"checks that trust the agent's report: {bad}" if bad else
                    "no check passes on a bare success claim", [f"check:{c}" for c in bad]))

    # G11: "better" while plane B regressed
    gates.append(_g("G11", None, "no comparison in this report", []))

    # G12: numbers that do not trace to an export or a committed case
    uncommitted = sorted(c for c in in_run if any(ctx.cases[c]["_path"] in u or u.endswith(ctx.cases[c]["_path"])
                                                  for u in ctx.untracked))
    adhoc = sorted({a["case_id"] for a in ctx.attempts if a["case_id"] not in ctx.cases})
    untraced = [c["id"] for c in ev.categories()
                if c.get("share_source") not in {e.get("id") for e in ev.exports()}]
    problems = []
    if uncommitted:
        problems.append(f"uncommitted or modified cases: {uncommitted[:10]}")
    if adhoc:
        problems.append(f"records for cases not in evals/cases: {adhoc[:10]}")
    if untraced:
        problems.append(f"observed shares not traced to an export: {untraced}")
    gates.append(_g("G12", not problems, "; ".join(problems) or "every number traces to a "
                    "committed case or an export", [f"case:{c}" for c in uncommitted + adhoc] +
                    (["quality"] if untraced else [])))

    # G13: retries / operational failures missing or scored
    g13 = []
    for a in ctx.attempts:
        if a.get("outcome") not in (None, "ok") and a.get("passed") is not None:
            g13.append(f"{a['case_id']} t{a['trial']} a{a['attempt']}: {a['outcome']} scored as correctness")
    by_trial: dict[tuple, list[int]] = defaultdict(list)
    for a in ctx.attempts:
        by_trial[(a["run_id"], a["case_id"], a["trial"])].append(a["attempt"])
    for key, att in by_trial.items():
        if sorted(att) != list(range(len(att))):
            g13.append(f"{key}: attempts {sorted(att)} are not contiguous from 0 (an attempt is missing)")
    for m in ctx.manifests:
        from .gates import trial_completeness
        g13 += trial_completeness(ev, m)
    gates.append(_g("G13", None if not ctx.manifests else not g13,
                    "; ".join(g13[:5]) or "every attempt recorded; only ok attempts scored",
                    ["plane_a", "plane_b"] if g13 else []))
    return gates


# ---- assembly -----------------------------------------------------------------------------

def build(ev: Evals, run_ids: list[str] | None = None, candidate_runs: list[str] | None = None) -> dict:
    from . import compare as compare_mod
    from . import suite

    run_ids = run_ids or default_runs(ev)
    ctx = Context(ev, run_ids)
    agent = ev.agent()
    gates = evaluate_gates(ctx)
    comparison = (compare_mod.compare(ev, run_ids, candidate_runs) if candidate_runs
                  else compare_mod.latest_for(ev, run_ids) if run_ids else None)
    if comparison:
        gates = [g for g in gates if g["id"] not in ("G7", "G11")]
        gates += comparison_gates(comparison)
        gates.sort(key=lambda g: int(g["id"][1:]))
    status = {g["id"]: g["status"] for g in gates}

    declared_models = dict(agent.get("models") or {})
    observed = {}
    for m in ctx.manifests:
        for site, ids in ((m.get("agent") or {}).get("model_ids_observed") or {}).items():
            observed.setdefault(site, set()).update(ids)
    exports = ev.exports()
    m0 = ctx.manifests[-1] if ctx.manifests else {}
    costs = [m.get("cost_usd") for m in ctx.manifests if m.get("cost_usd") is not None]
    report = {
        "schema": SCHEMA,
        "generated": now_iso(),
        "refused": None,
        "runs": [m["run_id"] for m in ctx.manifests],
        "agent": {"id": agent.get("id"),
                  "stable_window_since": (agent.get("stable_window") or {}).get("since"),
                  "model_ids": declared_models,
                  "model_ids_observed": {k: sorted(v) for k, v in observed.items()},
                  "model_family": agent.get("model_family")},
        "conditions": {
            "agent_commit": m0.get("agent_commit"), "agent_dirty": m0.get("agent_dirty"),
            "evals_commit": m0.get("evals_commit"), "evals_dirty": m0.get("evals_dirty"),
            "harness": m0.get("harness"), "k": ctx.k,
            "judge_backends": m0.get("judge_backends") or [], "simulator": m0.get("simulator"),
            "judge_cost_usd": _judge_cost(ctx),
            "fakes_sha256": m0.get("fakes_sha256"),
            "cost_usd": sum(costs) if costs else None,
            "started": min((m.get("started") for m in ctx.manifests), default=None),
            "finished": max((m.get("finished") or "" for m in ctx.manifests), default=None) or None,
            "data_exports": [{"id": e.get("id"), "source": e.get("source"),
                              "window": e.get("window"), "rows": e.get("rows")} for e in exports],
        },
        "regime": "offline",
        "taxonomy": {"name": ev.taxonomy().get("name"),
                     "source": _taxonomy_source(ev.taxonomy()) if status["G5"] == "pass" else "MISSING",
                     "read_on": ev.taxonomy().get("read_on"),
                     "entries": [e.get("id") for e in ev.taxonomy().get("entries") or []]},
        "sets": {s: {"n": sum(1 for c in ctx.cases.values() if c.get("set") == s and ctx.gated(c["id"]))}
                 for s in SETS},
        "categories": None,
        "checks": check_rows(ctx),
        "coverage": coverage(ev, status["G5"] == "pass"),
        "redundancy": suite.redundancy(ev),
        "comparison": comparison,
        "online": None,
        "validity": _validity(agent),
        "gates": gates,
        "cases": None,
        "next_actions": None,
    }
    report["sets"]["quality_estimate"]["weights_source"] = (
        "categories.yaml observed_share" if status["G6"] == "pass" else None)
    report["sets"]["quality_estimate"]["estimate"] = quality_estimate(ctx, status["G6"] == "pass")
    report["sets"]["error_finding"]["note"] = "error-finding set — not a quality estimate"
    for s in SETS:  # M7, from this run's within-case variance
        report["sets"][s]["mde_at_80_power"] = compare_mod.mde_from(ctx, compare_mod.case_rates(ctx, set_name=s))
    report["coverage"]["authoring_queue"] = suite.authoring_queue(ev, report["coverage"]["cells"])

    if status["G1"] == "fail":
        report["refused"] = "G1: no condition record; only gates and conditions are reported"
        return report
    report["cases"] = case_rows(ctx)
    report["next_actions"] = None
    if status["G13"] == "fail":
        report["refused"] = "G13: attempts missing or operational failures scored; plane A and B numbers withheld"
        return report
    report["categories"] = category_rows(ctx)
    report["next_actions"] = next_actions(ev, report)
    return report


def comparison_gates(c: dict) -> list[dict]:
    """G7 and G11, decided by a comparison."""
    if c.get("refused"):
        g7 = _g("G7", False, c["refused"], ["comparison"])
    else:
        g7 = _g("G7", True, f"paired McNemar test; manifests differ only on {c.get('declared_variable') or 'nothing'}",
                [])
    regs = ((c.get("operational") or {}).get("regressions_beyond_budget")) or []
    if c.get("refused") or c.get("verdict") is None:
        g11 = _g("G11", None, "no verdict", [])
    elif c["verdict"] == "trade":
        g11 = _g("G11", False, "correctness improved but plane B regressed beyond budget: reported as a trade",
                 ["better"])
    else:
        g11 = _g("G11", True, "no 'better' verdict with a plane-B regression beyond budget"
                 + (f" ({len(regs)} budget regressions noted)" if regs else ""), [])
    return [g7, g11]


def next_actions(ev: Evals, r: dict) -> list[dict]:
    """P13: what to do next, each with the command that clears it."""
    from . import gates as gates_mod

    acts = []
    for g in gates_mod.evaluate(ev):
        if g.status == "unmet" and g.id != "C18":
            acts.append({"action": f"clear {g.id} {g.command}", "why": (g.problems or [""])[0],
                         "command": f"skill {g.skill}"})
    for q in (r.get("coverage") or {}).get("authoring_queue", [])[:5]:
        acts.append({"action": f"author a case for {q['taxonomy_entry']} × {q['failure_mode']}",
                     "why": "empty coverage cell (E8)", "command": "skill build (C6)"})
    for c in r.get("checks") or []:
        j = c.get("judge")
        if j and j["status"] != "calibrated":
            why = "; ".join(j["status_reasons"]) or "uncalibrated"
            acts.append({"action": f"calibrate judge {c['id']}", "why": why,
                         "command": f"aot-evals label queue --judge {c['id']}; aot-evals calibrate --judge {c['id']}"})
    for row in r.get("categories") or []:
        if row.get("flaky"):
            acts.append({"action": f"explain {row['flaky']} flaky case(s) in {row['id']}",
                         "why": "0 < passes < k (M4)", "command": "inspect P9 / P12"})
        if row["operational"].get("budget_status") == "over":
            acts.append({"action": f"{row['id']} is over budget",
                         "why": ", ".join(b["budget"] for b in row["operational"]["budget_breaches"]),
                         "command": "aot-evals ops"})
        if row.get("excluded"):
            acts.append({"action": f"screen {row['excluded']['n_cases']} case(s) in {row['id']}",
                         "why": row["excluded"]["reason"], "command": "aot-evals screen"})
    red = r.get("redundancy")
    if red and red.get("below_threshold"):
        acts.append({"action": f"prune {len(red['proposal']['prune'])} redundant case(s)",
                     "why": f"discriminating fraction {red['discriminating_fraction']:.0%} < {red['threshold']:.0%}",
                     "command": "aot-evals redundancy"})
    if red is None:
        acts.append({"action": "run a second agent version", "why": "redundancy needs at least two candidates",
                     "command": "aot-evals run --purpose candidate --k 5 --variable KIND=VALUE"})
    return acts


def _judge_cost(ctx: Context) -> float | None:
    costs = [line["cost_usd"] for line in ctx.check_lines
             if line.get("type") == "judge" and line.get("cost_usd") is not None]
    return sum(costs) if costs else None


def _validity(agent: dict) -> dict:
    v = agent.get("validity") or {}
    stages = {k: v.get(k) for k in ("task", "simulator", "judge")}
    known = [x for x in stages.values() if isinstance(x, (int, float))]
    return {"stages": stages, "compounded": _prod(known) if known else None}


def _prod(xs):
    out = 1.0
    for x in xs:
        out *= x
    return out


def write(ev: Evals, report: dict) -> str:
    path = ev.p("report", "report.json")
    write_json(path, report)
    return str(path)
