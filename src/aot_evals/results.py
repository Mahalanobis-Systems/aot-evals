"""What the report, the comparison and the operational sweep share (report.py, decision.py,
compare.py, ops.py): which build a run measured, the runs' records indexed by attempt, each judge's
state, a pass rate with its interval over clusters, and the operational numbers against budgets.

Everything is recomputed from per-trial records; nothing is pre-rounded; unknown values are
`null`, never `0`.
"""

from __future__ import annotations

import json
from collections import defaultdict

from . import stats
from .evidence import untracked_cases
from .repo import Evals
from .screen import passes as screen_passes

# The fields that name the build that ran (the agent and how it was invoked), as opposed to
# what measured it (cases, checks, judges).
BUILD_FIELDS = ("agent_commit", "harness", "model_ids", "invoke", "fakes_sha256")


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
    (a suite split by use case to pace a rate-limited runtime) are one pass; a repeat of a case
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
        calibrated threshold. The as-written code verdict is kept as `passed_code`."""
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
        """Whether a case may count toward gated numbers: screened (`screened`) and committed (`committed`)."""
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
        # the mode's counted check and its diagnostics (rule 12)
        ids = (([fm["check"]] if isinstance(fm.get("check"), str) else [])
               + [d for d in fm.get("diagnostics") or [] if isinstance(d, str)])
        for cid in ids:
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
                st["reasons"].append("not calibrated")
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


# ---- plane A ------------------------------------------------------------------------------

def _passes_by_case(finals: list[dict]) -> dict[str, list[bool]]:
    out: dict[str, list[bool]] = defaultdict(list)
    for a in sorted(finals, key=lambda a: (a["run_id"], a["trial"])):
        if a.get("passed") is not None:
            out[a["case_id"]].append(bool(a["passed"]))
    return out


def _cluster_keys(ctx: Context, case_ids) -> list[str | None] | None:
    """Each case's `cluster` (template, source trace or seed), or None when no case has one."""
    keys = [(ctx.cases.get(c) or {}).get("cluster") for c in case_ids]
    return keys if any(k is not None for k in keys) else None


def correctness(ctx: Context, finals: list[dict], set_name: str) -> dict:
    by_case = _passes_by_case(finals)
    keys = _cluster_keys(ctx, list(by_case))
    rate = stats.clustered_pass_rate(list(by_case.values()), keys)
    # A case's trials are those of the runs that included it: runs split by use case each
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
        if "n_clusters" in rate:
            pass_rate["n_clusters"] = rate["n_clusters"]
    # M30: with no failure seen, how high could the failure rate still be? Counted over cases,
    # since trials of one case are not independent; over clusters when cases carry one, since a
    # clean result can't show how correlated a cluster's cases are (all-or-nothing is assumed).
    clean = bool(by_case) and all(all(v) for v in by_case.values())
    units = rate.get("n_clusters", len(by_case)) if rate else len(by_case)
    zero_bound = stats.zero_failure_bound(units) if clean else None
    return {"pass_rate": pass_rate, "pass_pow_k": pass_pow_k, "pass_pow_k_reason": pass_pow_k_reason,
            "flaky": flaky, "variance_band": band, "zero_failure_bound": zero_bound,
            "zero_failure_bound_basis": (("clusters" if keys else "cases") if clean else None),
            "clusters": stats.cluster_summary(keys) if keys else None,
            # M31: how much of the noise is case difficulty and how much run-to-run
            "variance_components": stats.variance_components(list(by_case.values()))}


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


def operational(attempts: list[dict], budget: dict | None, replay: bool = False) -> dict:
    if replay:
        # replayed records: their cost, latency and errors describe the replay, not the agent
        return {"n_trials": len({(a["run_id"], a["case_id"], a["trial"]) for a in attempts}),
                "n_attempts": len(attempts), "not_measured": "recorded runs replayed: plane B describes "
                "the replay, not the agent", "budget": budget or {}, "budget_status": "not_measured",
                "budget_breaches": []}
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





