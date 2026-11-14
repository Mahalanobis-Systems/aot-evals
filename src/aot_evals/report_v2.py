"""`report` for a 2.0 eval: `<eval>/report/report.json`, schema `aot-evals/report@2`
(docs/v2-design.md §6).

This module writes the keys of the estimand, the sampling design and the measurement model:
`eval`, `spec`, `estimate` (the headline θ̂), `use_cases` (the per-use-case table, the
diagnostic beside it), `design` and `measurement` (each failure mode's grader with its catch and
clean pass rates and its floor, the eval held to people, the variance split; measurement.py).
The decision rule's keys, `decision` and `comparison`, come from decision.py.
Keys may be added within v2, never removed or renamed. Everything is recomputed from per-trial
records, nothing is pre-rounded, and an unknown value is null with its reason, never 0.

**What a trial scores.** A trial's verdict comes from the counted checks of the failure modes that
apply to its case (one check per mode, rule 12); diagnostics are recorded and never counted. For
`pass_rate` the trial's value is 1 when every counted check passed; for `failure_rate:<mode>` it
is 1 when that mode's check failed. A trial missing a counted verdict (an operational failure, a
check that raised, judges switched off) is unscored, never a pass or a fail. A case's value ŷ is
the mean of its scored trials.

**What counts toward θ̂.** Quality cases only (rule 5), with a draw from the spec's frame and seed
(rule 6), screened and committed (rule 17), in runs whose estimand, design and measurement hashes
match the current spec (v2-design §5). θ̂ = Σ w_s μ̂_s with μ̂_s the Hájek mean of ŷ over use case
s and its interval from the clusters (`stats.stratified_hajek`).

**What the grader's error does to it.** A counted judge that feeds the quantity counts only when
its error rates are measured and within `measurement.max_inflation`; otherwise θ̂ is null with
the reason (rule 13). The correction the spec names (`rogan_gladen`, `ppi`) is then applied to
the observed θ̂; `estimate.uncorrected` keeps the number before it.
"""

from __future__ import annotations

from collections import defaultdict
from types import SimpleNamespace

from . import stats
from .design import case_status, clusters, load_draw
from .repo import POOLS, Eval
from .report import correctness, operational, run_passes
from .screen import passes as screen_passes
from .spec import Spec, part_hashes, quantity, use_case_weights, use_cases
from .util import ContractError, now_iso, write_json

SCHEMA = "aot-evals/report@2"
MANIFEST_SCHEMA = "aot-evals/run-manifest@2"
# The parts whose change makes two runs different quantities (v2-design §5); a decision-rule
# change leaves the estimate alone.
MEASURED_PARTS = ("estimand", "design", "measurement")


def default_runs(ev: Eval) -> list[str]:
    """The effective baseline (each case's newest baseline run), else the latest finished run."""
    base = ev.baseline_ids()
    if base:
        return base
    others = [m for m in ev.runs() if m.get("finished") and m.get("purpose") != "smoke"]
    return [others[-1]["run_id"]] if others else []


def refusal(ev: Eval, spec: Spec, manifests: list[dict]) -> str | None:
    """Why these runs' numbers cannot stand for the current spec, or None."""
    now = part_hashes(spec, ev)
    for m in manifests:
        if m.get("schema") != MANIFEST_SCHEMA:
            return (f"run {m.get('run_id')} has a {m.get('schema') or 'pre-2.0'} manifest; a 2.0 eval's "
                    "numbers come from runs made under its eval.yaml")
        then = m.get("spec_sha") or {}
        changed = [p for p in MEASURED_PARTS if then.get(p) != now.get(p)]
        if changed:
            return (f"run {m.get('run_id')} measured under a different {' and '.join(changed)} than the "
                    "current eval.yaml, so its numbers are a different quantity (estimators §9); "
                    "run the baseline again under the current spec")
    return None


class Scored:
    """The runs a report covers, with each final attempt scored under the current spec."""

    def __init__(self, ev: Eval, run_ids: list[str]):
        self.ev = ev
        self.spec = ev.spec()
        self.manifests = [m for m in (ev.run_manifest(r) for r in run_ids) if m]
        self.kind, self.mode = quantity(self.spec)
        self.attempts: list[dict] = []
        by_attempt: dict[tuple, list[dict]] = defaultdict(list)
        for m in self.manifests:
            for r in ev.run_records(m["run_id"]):
                if r.get("kind") == "attempt":
                    self.attempts.append(r)
                elif r.get("kind") == "check":
                    by_attempt[(r.get("run_id"), r.get("case_id"), r.get("trial"), r.get("attempt"))].append(r)
        try:
            cases = ev.cases()
        except ContractError:
            cases = []
        self.cases = {c["id"]: c for c in cases if c.get("id")}
        self.status = {cid: case_status(ev, c) for cid, c in self.cases.items()}
        for cid, c in self.cases.items():
            c["cluster"] = self.status[cid]["cluster"]  # as correctness() reads it
        from .gates import untracked_cases

        try:
            self.untracked = set(untracked_cases(ev))
        except (ValueError, OSError):
            self.untracked = set()
        self.k = max((m.get("k") or 0 for m in self.manifests), default=0) or None
        self.trials_of: dict[str, int] = defaultdict(int)
        for m in self.manifests:
            for cid in (m.get("case_set") or {}).get("ids") or []:
                self.trials_of[cid] += m.get("k") or 0
        self.pass_of = run_passes(self.manifests)
        for a in self.attempts:
            self._score(a, by_attempt.get((a["run_id"], a["case_id"], a["trial"], a["attempt"]), []))

    def _score(self, a: dict, lines: list[dict]) -> None:
        """Set a["passed"] (every counted check passed) and a["value"] (the quantity) on a final
        attempt, or None for both when a counted verdict is missing."""
        a["passed"] = a["value"] = None
        case = self.cases.get(a["case_id"])
        if not a.get("final") or a.get("outcome") != "ok" or a.get("instrument_error") or case is None:
            return
        verdicts = {ln.get("check_id"): ln.get("passed") for ln in lines if ln.get("counted")}
        wanted = {fm["check"]: fm["id"] for fm in self.ev.failure_modes_for_case(case)
                  if isinstance(fm.get("check"), str)}
        # each counted check's own verdict, for its failure mode's rate (measurement.py)
        a["verdicts"] = {c: verdicts.get(c) for c in wanted}
        if not wanted or any(verdicts.get(c) is None for c in wanted):
            return
        a["passed"] = all(verdicts[c] for c in wanted)
        if self.kind == "pass_rate":
            a["value"] = 1.0 if a["passed"] else 0.0
        elif self.kind == "failure_rate":
            check = next((c for c, m in wanted.items() if m == self.mode), None)
            a["value"] = None if check is None else (0.0 if verdicts[check] else 1.0)

    def finals(self) -> list[dict]:
        return [a for a in self.attempts if a.get("final")]

    def screened(self, cid: str) -> bool:
        """Read by a person and committed: cases with an unverified answer stay out (rule 17)."""
        case = self.cases.get(cid)
        if not case or not screen_passes(case.get("screen")):
            return False
        return not any(case["_path"] in u or u.endswith(case["_path"]) for u in self.untracked)

    def counts(self, cid: str) -> bool:
        return self.screened(cid) and bool(self.status.get(cid, {}).get("counts"))

    def case_values(self, case_ids=None) -> dict[str, float]:
        """ŷ per case: the mean of its scored trials' values."""
        vals: dict[str, list[float]] = defaultdict(list)
        for a in self.finals():
            if a.get("value") is not None and (case_ids is None or a["case_id"] in case_ids):
                vals[a["case_id"]].append(a["value"])
        return {c: sum(v) / len(v) for c, v in vals.items()}

    def ctx(self) -> SimpleNamespace:
        """What the 1.x per-category computations read."""
        return SimpleNamespace(cases=self.cases, trials_of=self.trials_of, k=self.k, pass_of=self.pass_of)


# ---- keys ------------------------------------------------------------------------------------

def eval_key(spec: Spec) -> dict:
    est = spec.part("estimand")
    return {"id": spec.eval_id, "version": spec.resolved.get("version"), "unit": est.get("unit"),
            "quantity": est.get("quantity"), "decision": est.get("decision")}


def _budget(spec: Spec, uc: str) -> dict | None:
    con = spec.part("decision_rule").get("constraints")
    if not isinstance(con, dict):
        return None
    default = con.get("default") if isinstance(con.get("default"), dict) else {}
    per = (con.get("use_cases") or {}).get(uc) if isinstance(con.get("use_cases"), dict) else None
    out = {**default, **(per if isinstance(per, dict) else {})}
    return out or None


def estimate(s: Scored, refused: str | None, weights: dict | None, source: str | None,
             meas: dict | None = None) -> dict:
    spec = s.spec
    out = {"theta": None, "ci": None, "ci_method": None, "se": None, "quantity": spec.part("estimand").get("quantity"),
           "weights": weights, "weights_source": source, "estimator": "hajek", "corrected": False,
           "correction": spec.part("measurement").get("correction"), "uncorrected": None,
           "n_cases": 0, "n_clusters": 0, "k": s.k, "null_reason": None}
    blocked = spec.blocked("estimate")
    if blocked:
        out["null_reason"] = "the spec does not say what the number means: " + ", ".join(
            sorted({i.field for i in blocked}))
        return out
    if weights is None:
        out["null_reason"] = "the weights are not all stated (rule 2)"
        return out
    if not s.manifests:
        out["null_reason"] = "no run yet: aot-evals run --purpose baseline"
        return out
    if refused:
        out["null_reason"] = refused
        return out
    counted = {cid for cid in s.cases if s.counts(cid)}
    values = s.case_values(counted)
    strata = {}
    for u in use_cases(spec):
        uc = u["id"]
        ids = sorted(c for c in values if s.cases[c].get("use_case") == uc)
        strata[uc] = {"weight": weights.get(uc), "values": [values[c] for c in ids],
                      "inclusion_probs": [s.status[c]["inclusion_prob"] for c in ids],
                      "clusters": [s.status[c]["cluster"] for c in ids]}
    r = stats.stratified_hajek(strata)
    used = [c for c in values if weights.get(s.cases[c].get("use_case"))]
    out["n_cases"] = len(used)
    out["n_clusters"] = len({s.status[c]["cluster"] for c in used})
    if r is None:
        out["null_reason"] = "the weights sum to 0"
        return out
    if r["missing"]:
        out["null_reason"] = ("no scored quality case in " + ", ".join(r["missing"])
                              + ": θ is unknown without them (aot-evals draw, then run)")
        return out
    observed = {"point": r["point"], "ci": r["ci"], "se": r["se"]}
    out.update({"theta": r["point"], "ci": r["ci"], "ci_method": r["ci_method"], "se": r["se"],
                "uncorrected": {"theta": r["point"], "ci": r["ci"], "se": r["se"]}})
    if meas is None:
        return out
    from .measurement import correct, judge_block

    why = judge_block(meas)
    if why:
        out.update({"theta": None, "ci": None, "se": None, "null_reason": why})
        return out
    c = correct(s, meas, weights, observed)
    out.update(c)
    if c.get("corrected"):
        out["ci_method"] = (c.get("correction_detail") or {}).get("method") or out["ci_method"]
    return out


def _row_correction(s: Scored, est: dict | None, meas: dict | None) -> dict | None:
    """A use case's μ̂ corrected by Rogan-Gladen, when that is the spec's correction and its
    grader is measured (the correction is linear, so each row corrects on its own). PPI corrects
    θ̂ as a whole: its rows stay uncorrected (null)."""
    if not est or est.get("point") is None or meas is None or meas.get("correction") != "rogan_gladen":
        return None
    kind, mode = quantity(s.spec)
    var = (est.get("se") or 0.0) ** 2
    if kind == "failure_rate":
        row = next((r for r in meas["failure_modes"] if r["id"] == mode), None)
        if not row or row["type"] != "judge":
            return None
        from .measurement import judge_calibration

        c = judge_calibration(s.ev, row["check"], meas["alpha"])["counts"]
        return stats.rogan_gladen_rate(est["point"], var, c["catch_k"], c["catch_n"], c["clean_k"],
                                       c["clean_n"]) if c else None
    a = meas["eval_vs_people"].get("all") or {}
    cat, cln = a.get("catch") or {}, a.get("clean") or {}
    if not cat.get("n") or not cln.get("n"):
        return None
    r = stats.rogan_gladen_rate(1 - est["point"], var, cat["k"], cat["n"], cln["k"], cln["n"])
    return None if r is None else {**r, "point": 1 - r["point"], "ci": [1 - r["ci"][1], 1 - r["ci"][0]],
                                   "note": "corrected on the failure rate 1 − μ̂"}


def use_case_rows(s: Scored, weights: dict | None, meas: dict | None = None) -> list[dict]:
    spec = s.spec
    replay = bool(s.manifests) and all(m.get("replay") for m in s.manifests)
    rows = []
    ctx = s.ctx()
    for u in use_cases(spec):
        uc = u["id"]
        for pool in POOLS:
            attempts = [a for a in s.attempts if a.get("use_case") == uc and a.get("pool") == pool]
            finals = [a for a in attempts if a.get("final")]
            ok = (lambda c: s.counts(c)) if pool == "quality" else s.screened
            kept = [a for a in finals if ok(a["case_id"])]
            left = [a for a in finals if not ok(a["case_id"])]
            pis = [s.status[c]["inclusion_prob"] for c in s.cases
                   if s.cases[c].get("use_case") == uc and s.status[c]["pool"] == pool
                   and s.status[c]["inclusion_prob"] is not None] if pool == "quality" else []
            row = {"id": uc, "pool": pool, "share": u.get("share"), "cost": u.get("cost"),
                   "weight": (weights or {}).get(uc) if pool == "quality" else None,
                   "inclusion_prob_range": [min(pis), max(pis)] if pis else None,
                   "n_cases": len({a["case_id"] for a in kept if a.get("passed") is not None}),
                   "estimate": None,
                   **correctness(ctx, kept, pool),
                   "operational": operational(attempts, _budget(spec, uc), replay=replay),
                   "excluded": None}
            if pool == "quality":
                vals = s.case_values({a["case_id"] for a in kept})
                ids = sorted(vals)
                row["estimate"] = stats.hajek_mean([vals[c] for c in ids],
                                                   [s.status[c]["inclusion_prob"] for c in ids],
                                                   [s.status[c]["cluster"] for c in ids])
                row["estimate_corrected"] = _row_correction(s, row["estimate"], meas)
            else:
                row["note"] = "bug-finding cases: they find failures and never enter θ̂ (rule 5)"
            if left:
                why = ("not drawn from the spec's frame and seed, unscreened or uncommitted (rules 6, 17)"
                       if pool == "quality" else "unscreened or uncommitted (rule 17)")
                row["excluded"] = {"n_cases": len({a["case_id"] for a in left}), "reason": why,
                                   "pass_rate": correctness(ctx, left, pool)["pass_rate"]}
            rows.append(row)
    return rows


def design_key(s: Scored) -> dict:
    spec = s.spec
    design = spec.part("design")
    qs = design.get("quality_set") if isinstance(design.get("quality_set"), dict) else {}
    bf = design.get("bug_finding_set") if isinstance(design.get("bug_finding_set"), dict) else {}
    statuses = list(s.status.values())
    quality = [x for x in statuses if x["pool"] == "quality"]
    log = load_draw(s.ev)
    cl = clusters(s.ev, statuses)
    by_cluster: dict[str, list[float]] = defaultdict(list)
    for c, v in s.case_values({x["id"] for x in quality if s.counts(x["id"])}).items():
        by_cluster[s.status[c]["cluster"]].append(v)
    deff, icc, why = None, None, None
    if not by_cluster:
        why = "no scored quality case yet"
    elif all(len(v) == 1 for v in by_cluster.values()):
        deff, icc = 1.0, None
        why = "every cluster holds one case"
    else:
        od = stats.overdispersion_test(list(by_cluster.values()))
        icc = od["icc"] if od else None
        if icc is None:
            why = "the cluster ICC could not be estimated"
        else:
            sizes = [len(v) for v in by_cluster.values()]
            deff = stats.design_effect(sum(sizes) / len(sizes), max(0.0, min(1.0, icc)))
    return {
        "quality": {"n": len(quality), "drawn": sum(1 for x in quality if x["counts"]),
                    "frame": (spec.part("estimand").get("population") or {}).get("frame")
                    if isinstance(spec.part("estimand").get("population"), dict) else None,
                    "seed": qs.get("seed"), "oversample": qs.get("oversample"),
                    "strata": log.get("strata"), "skips": list(log.get("skips") or []),
                    "refused": [{"id": x["id"], "problems": x["problems"]} for x in quality if x["problems"]]},
        "bug_finding": {"n": sum(1 for x in statuses if x["pool"] == "bug_finding"),
                        "coverage": bf.get("coverage")},
        "clusters": {**cl, "cluster_key": design.get("cluster_key"), "design_effect": deff,
                     "icc": icc, "design_effect_reason": why},
        "cases_without_pool": [x["id"] for x in statuses if x["pool"] not in POOLS],
    }


class Side:
    """One set of runs scored under the current spec, with what the report computes on it: the
    refusal, the measurement model, the estimate and the per-use-case rows. A comparison and a
    decision read two sides scored the same way."""

    def __init__(self, ev: Eval, run_ids: list[str]):
        from .measurement import section

        self.ev = ev
        self.spec = ev.spec()
        self.s = Scored(ev, run_ids)
        self.weights, self.source = use_case_weights(self.spec)
        self.refused = refusal(ev, self.spec, self.s.manifests)
        self.meas = section(self.s, self.weights, self.refused)
        self.est = estimate(self.s, self.refused, self.weights, self.source, self.meas)
        self._rows: list[dict] | None = None

    @property
    def manifests(self) -> list[dict]:
        return self.s.manifests

    @property
    def run_ids(self) -> list[str]:
        return [m["run_id"] for m in self.s.manifests]

    def rows(self) -> list[dict] | None:
        if self.refused:
            return None
        if self._rows is None:
            self._rows = use_case_rows(self.s, self.weights, self.meas)
        return self._rows


def build(ev: Eval, run_ids: list[str] | None = None, candidate_runs: list[str] | None = None) -> dict:
    """report.json v2. With `candidate_runs`, adds the paired comparison against the reported
    (baseline) runs and decides on the candidate; without, `decision` decides a threshold rule
    on the reported runs and leaves a paired rule unknown until there is a candidate."""
    from . import decision as decision_mod

    spec = ev.spec()
    run_ids = run_ids if run_ids is not None else default_runs(ev)
    base = Side(ev, run_ids)
    cand = Side(ev, candidate_runs) if candidate_runs else None
    report = {
        "schema": SCHEMA,
        "generated": now_iso(),
        "refused": base.refused,
        "runs": base.run_ids,
        "eval": eval_key(spec),
        "spec": {**spec.as_dict(), "sha": part_hashes(spec, ev)},
        "estimate": base.est,
        "use_cases": base.rows(),
        "design": design_key(base.s),
        "measurement": base.meas,
    }
    comparison = decision_mod.comparison(ev, base, cand) if cand else None
    report["comparison"] = comparison
    report["decision"] = decision_mod.decide(ev, base, cand, comparison)
    return report


def write(ev: Eval, report: dict) -> str:
    path = ev.p("report", "report.json")
    write_json(path, report)
    return str(path)


def measured(ev: Eval) -> dict:
    """What a baseline has measured, for `plan`: θ̂, each use case's μ̂ and cost per trial, and
    the clusters' design effect. Empty without a baseline run under the current spec."""
    runs = default_runs(ev)
    if not runs:
        return {}
    r = build(ev, runs)
    if r["refused"]:
        return {}
    out = {"runs": r["runs"], "theta": r["estimate"]["theta"],
           "design_effect": r["design"]["clusters"]["design_effect"], "use_cases": {}}
    for row in r["use_cases"] or []:
        if row["pool"] != "quality":
            continue
        out["use_cases"][row["id"]] = {"rate": (row["estimate"] or {}).get("point"),
                                       "cost_per_trial": row["operational"].get("cost_per_run")}
    return out

