"""The decision rule of a 2.0 eval (estimators §6; statistics §4; docs/v2-design.md §5, §6):
report.json's `decision` and `comparison`, and `compare` on a 2.0 eval.

**The tests.** Each gate is one of three one-sided tests at the rule's α:

- **threshold**: θ̂ is on the right side of a fixed `bar` (a failure rate below it, a pass rate
  above it). It reads the estimate as the report computed it (corrected where the spec corrects,
  so the judge's measured error is in its interval) and tests its one-sided bound against the bar
  (`stats.bound_test`). When a counted judge feeds an uncorrected estimate, the bar is moved to the
  grader's scale, (1 − clean) + J·bar, as in Feng et al. (2026).
- **superiority**: the candidate is better than the baseline, H0 Δ ≤ 0, by a one-sided sign-flip
  test on the paired per-case deltas (`stats.superiority_test`).
- **non_inferiority**: the candidate is no worse than the baseline by more than `margin`, H0
  Δ ≤ −margin (`stats.non_inferiority_test`, rule 19). A grader with J < 1 shrinks a real change
  to J·Δ, so the margin is tested on the grader's scale at J's lower bound (statistics §3.3).

**Paired deltas** (rule 18). A case's delta is its ŷ under the candidate minus under the
baseline, on the scale where higher is better (negated for a failure rate), over the counted
quality cases both sides scored. Each case carries its design weight in θ̂,
(w_s / Σw) · (1/π_i) / Σ_{j∈s} 1/π_j, so the mean delta is the change in θ̂ itself, and signs flip
per cluster (statistics §2.4, §4.4).

**Each gate's result** is `pass` (the test rejects its null at α), `fail` (the two-sided 1 − 2α
interval sits at or beyond the null on the wrong side: shown worse, shown not better, or shown on
the wrong side of the bar), `insufficient` (neither: more cases decide it, `cases_needed` says
about how many), or `unknown` (nothing to test, with the reason: a spec field missing, no
candidate for a paired test, θ̂ null because a judge does not count, rule 13).

**Gates combine** as the rule says (statistics §4.6, rule 22). `combine: all`: the action needs
every gate (the headline and each use case gate) to pass, an intersection–union test that needs
no correction. `combine: any`: one gate alone triggers it, so its p-values are adjusted (`holm`
or `benjamini_hochberg`) and a gate passes when its adjusted p is at or under α. `also_requires`
(rule 27) must pass either way: each names another eval of the agent and a rule, tested on that
eval's candidate runs for the same change (the same declared variable at the same commit).

**Constraints** (rule 24) are limits on cost and latency per use case, read on the runs decided
on. Gates that pass with a constraint breached are a `trade`: both numbers are reported for a
person to weigh, never folded into θ.

**Looks** (rule 21). `looks: fixed` allows one look per change: each decision with a result is
recorded in `<eval>/report/looks.jsonl`, and deciding the same change again on other runs (cases
or trials added after looking) leaves the result unknown. `sequential` and `optimizer_holdout`
need intervals this version does not compute, so their decisions are unknown, never a pass.

**Which runs compare** (v2-design §5). `compare` refuses when an estimand, design or measurement
hash differs from the current spec's, when the two sides are not one build apart (1.x G7), and
when the decision rule changed since a run was made unless a decision with the new rule's hash was
journaled no later than the first run decided on (`aot-evals log --kind decision`, problem 12).
"""

from __future__ import annotations

import json
from collections import defaultdict

from . import stats
from .measurement import alpha_of, judge_block, lower_bound
from .report import operational
from .report_v2 import Side, _budget
from .spec import DEFAULT_POWER, part_hashes, quantity, use_cases
from .util import ContractError, append_jsonl, now_iso, read_jsonl

RESULTS = ("pass", "fail", "insufficient", "unknown", "trade")
PAIRED = ("superiority", "non_inferiority")
LOOKS_FILE = "looks.jsonl"
# order of precedence when gates that must all pass are combined
_WORST = ("fail", "unknown", "insufficient", "pass")


def _power(spec, rule: dict | None = None) -> float:
    p = (rule or {}).get("power", spec.part("decision_rule").get("power"))
    return p if isinstance(p, (int, float)) and 0 < p < 1 else DEFAULT_POWER


def _alpha(spec, rule: dict | None = None) -> float:
    a = (rule or {}).get("alpha")
    return a if isinstance(a, (int, float)) and 0 < a < 0.5 else alpha_of(spec)


def _z_sum(alpha: float, power: float) -> float:
    return stats._z(1 - alpha) + stats._z(power)


def _gate(name: str, rule: dict, use_case: str | None = None) -> dict:
    return {"gate": name, "use_case": use_case, "test": rule.get("test"), "bar": rule.get("bar"),
            "margin": rule.get("margin"), "alpha": None, "power": None, "result": "unknown",
            "reason": None, "estimate": None, "se": None, "interval": None, "bound": None,
            "boundary": None, "p": None, "p_adjusted": None, "detectable_effect": None,
            "cases_needed": None, "cases_needed_reason": None, "n_cases": None, "n_clusters": None,
            "method": None, "notes": []}


def _unknown(g: dict, why: str) -> dict:
    g.update(result="unknown", reason=why)
    return g


# ---- the grader's scale ----------------------------------------------------------------------

def _feeding_judges(side: Side) -> list[dict]:
    return [r for r in side.meas["failure_modes"] if r["type"] == "judge" and r["feeds_estimate"]]


def grader_j(side: Side, lower: bool = True) -> tuple[float | None, str]:
    """J of the grader that scores the quantity, and where it came from: 1 for code; the
    quantity judge's for a failure rate; the eval against people's for a pass rate graded by a
    judge (rule 15). At the one-sided lower bounds by default, so a margin read through it is
    conservative. None when it is not measured."""
    kind, mode = quantity(side.spec)
    alpha = side.meas["alpha"]
    if kind == "failure_rate":
        row = next((r for r in side.meas["failure_modes"] if r["id"] == mode), None)
        if row is None or row["type"] == "code":
            return 1.0, "a code check (rule 14)"
        c, s = (row.get("catch_lower"), row.get("clean_lower")) if lower else (row.get("catch"), row.get("clean"))
        if c is None or s is None:
            return None, f"judge {row['check']} has no current calibration"
        return c + s - 1, f"judge {row['check']}'s calibration" + (" at its lower bounds" if lower else "")
    judges = _feeding_judges(side)
    if not judges:
        return 1.0, "every counted check is code (rule 14)"
    every = side.meas["eval_vs_people"].get("all") or {}
    cat, cln = every.get("catch") or {}, every.get("clean") or {}
    if not cat.get("n") or not cln.get("n"):
        return None, ("judges grade this pass rate (" + ", ".join(r["check"] for r in judges) + ") and the eval's "
                      "catch and clean pass rates against people are not measured (rule 15; aot-evals agreement)")
    if lower:
        c, s = lower_bound(cat["k"], cat["n"], alpha), lower_bound(cln["k"], cln["n"], alpha)
    else:
        c, s = cat["k"] / cat["n"], cln["k"] / cln["n"]
    return c + s - 1, "the eval against people" + (" at its lower bounds" if lower else "")


# ---- threshold -------------------------------------------------------------------------------

def _threshold(g: dict, side: Side, point: float | None, se: float | None, corrected: bool,
               n_cases: int, rule: dict) -> dict:
    spec = side.spec
    kind, _ = quantity(spec)
    alpha, power = _alpha(spec, rule), _power(spec, rule)
    g.update(alpha=alpha, power=power, estimate=point, se=se, n_cases=n_cases)
    bar = rule.get("bar")
    if not isinstance(bar, (int, float)):
        return _unknown(g, "a threshold test needs its bar")
    if point is None:
        return g
    direction = "below" if kind == "failure_rate" else "above"
    boundary, scale = float(bar), 1.0
    if not corrected and _feeding_judges(side):
        # an uncorrected estimate is on the grader's scale: so is the bar (Feng et al. 2026)
        j, src = grader_j(side, lower=False)
        if j is None or j <= 0:
            g["notes"].append(f"tested as graded: {src}; the bar is not on the grader's scale")
        else:
            row = (next((r for r in side.meas["failure_modes"] if r["id"] == quantity(spec)[1]), None)
                   if kind == "failure_rate" else None)
            if row is not None:
                clean = row["clean"]
            else:
                cln = (side.meas["eval_vs_people"].get("all") or {}).get("clean") or {}
                clean = cln["k"] / cln["n"]
            fbar = bar if kind == "failure_rate" else 1 - bar
            q0 = (1 - clean) + j * fbar
            boundary, scale = (q0 if kind == "failure_rate" else 1 - q0), j
            g["grader_scale"] = {"j": j, "clean": clean, "source": src, "bar_on_grader_scale": boundary}
            g["notes"].append(f"correction: none, so the bar {bar:g} is read on the grader's scale as "
                              f"{boundary:.4g} ({src}, point rates; their uncertainty is not in the test)")
    bt = stats.bound_test(point, se, boundary, direction, alpha) if se else None
    if bt is None:
        return _unknown(g, "the estimate has no standard error to test with")
    g.update(boundary=boundary, bound=bt["bound"], interval=bt["interval"], p=bt["p"],
             method=f"one-sided normal bound on θ̂ {direction} the bar"
             + (" (on the grader's scale)" if scale != 1.0 else ""), side=direction)
    g["detectable_effect"] = _z_sum(alpha, power) * se / scale
    good_side = point < boundary if direction == "below" else point > boundary
    if bt["passed"]:
        g["result"] = "pass"
    elif bt["shown_wrong_side"]:
        g.update(result="fail", reason=f"θ̂ is shown on the wrong side of the bar: the {1 - 2 * alpha:.0%} "
                                       f"interval [{bt['interval'][0]:.4g}, {bt['interval'][1]:.4g}] does not "
                                       f"reach {boundary:.4g}")
    else:
        g.update(result="insufficient", reason=f"the one-sided {1 - alpha:.0%} bound {bt['bound']:.4g} does "
                                               f"not clear {boundary:.4g}")
    if g["result"] != "pass":
        if good_side:
            g["cases_needed"] = stats.cases_for_spread(n_cases, se, abs(boundary - point), alpha, power)
        else:
            g["cases_needed_reason"] = ("θ̂ is on the wrong side of the bar: at this rate no number of cases "
                                        "shows it on the right side")
    return g


# ---- paired ----------------------------------------------------------------------------------

def _good(kind: str | None) -> float:
    return -1.0 if kind == "failure_rate" else 1.0


def paired_units(base: Side, cand: Side, use_case: str | None = None) -> dict:
    """The paired evidence: each counted quality case both sides scored, its delta on the scale
    where higher is better, its design weight and its cluster. For the headline every use case
    with weight must have one (θ is unknown without it); for one use case, its Hájek weights."""
    kind, _ = quantity(base.spec)
    sign = _good(kind)
    weights = base.weights or {}
    counted = {c for c in base.s.cases if base.s.counts(c) and cand.s.counts(c)}
    vb, vc = base.s.case_values(counted), cand.s.case_values(counted)
    ids = sorted(c for c in set(vb) & set(vc)
                 if (use_case is None and weights.get(base.s.cases[c].get("use_case")))
                 or (use_case is not None and base.s.cases[c].get("use_case") == use_case))
    by_uc: dict[str, list[str]] = defaultdict(list)
    for c in ids:
        by_uc[base.s.cases[c]["use_case"]].append(c)
    wanted = [use_case] if use_case else [u["id"] for u in use_cases(base.spec) if weights.get(u["id"])]
    missing = [u for u in wanted if not by_uc.get(u)]
    w_total = sum(weights.get(u, 0) for u in by_uc) if use_case is None else 1.0
    deltas, w, clusters, gains, losses, moved = [], [], [], [], [], []
    for uc, cs in by_uc.items():
        inv = {c: 1 / base.s.status[c]["inclusion_prob"] for c in cs}
        tot = sum(inv.values())
        uc_w = 1.0 if use_case else weights[uc] / w_total
        for c in cs:
            d = sign * (vc[c] - vb[c])
            deltas.append(d)
            w.append(uc_w * inv[c] / tot)
            clusters.append(base.s.status[c]["cluster"])
            gb, gc = (vb[c], vc[c]) if sign > 0 else (1 - vb[c], 1 - vc[c])
            mb = None if gb == 0.5 else gb > 0.5
            mc = None if gc == 0.5 else gc > 0.5
            if mb is False and mc is True:
                gains.append(c)
            elif mb is True and mc is False:
                losses.append(c)
            elif d != 0:
                moved.append({"case": c, "baseline": vb[c], "candidate": vc[c]})
    return {"ids": ids, "deltas": deltas, "weights": w, "clusters": clusters, "missing": missing,
            "gains": sorted(gains), "losses": sorted(losses), "moved": moved,
            "baseline_only": sorted(set(vb) - set(vc)), "candidate_only": sorted(set(vc) - set(vb))}


def _paired(g: dict, base: Side, cand: Side, rule: dict, use_case: str | None = None) -> dict:
    spec = base.spec
    alpha, power = _alpha(spec, rule), _power(spec, rule)
    test = rule.get("test")
    g.update(alpha=alpha, power=power)
    margin = rule.get("margin")
    if not isinstance(margin, (int, float)) or margin <= 0:
        return _unknown(g, f"a {test.replace('_', '-')} test needs its margin")
    u = paired_units(base, cand, use_case)
    g.update(n_cases=len(u["ids"]), n_clusters=len(set(u["clusters"])) if u["ids"] else 0)
    if u["missing"]:
        return _unknown(g, "no case scored on both sides in " + ", ".join(u["missing"])
                        + ": run the baseline and the candidate on the same cases (rule 18)")
    j, src = grader_j(base, lower=True)
    if j is not None and j <= 0:
        return _unknown(g, f"the grader is no better than chance ({src}): a change cannot be seen through it")
    if j is not None and j < 1:
        g["grader_scale"] = {"j": j, "source": src}
        g["notes"].append("assumes the judges err the same way on both versions; when they don't, the "
                          "comparison is biased and more cases don't help (Fiedler 2026)")
    spread = stats.weighted_mean_delta(u["deltas"], u["weights"], u["clusters"])
    se = spread["se"]
    if test == "superiority":
        r = stats.superiority_test(u["deltas"], alpha, clusters=u["clusters"], case_weights=u["weights"])
        null, effect = 0.0, (margin * j if j is not None else None)
        if j is None:
            g["notes"].append(f"the margin can't be put on the grader's scale ({src}): cases_needed is unknown")
    else:
        if j is None:
            return _unknown(g, f"the margin is on the true scale and the grader's J is unknown: {src}")
        r = stats.non_inferiority_test(u["deltas"], margin * j, alpha, clusters=u["clusters"],
                                       case_weights=u["weights"])
        null, effect = -margin * j, margin * j
        if j < 1:
            g["notes"].append(f"margin {margin:g} read on the grader's scale as {margin * j:.4g} (J {j:.3g}, {src})")
    g.update(estimate=r["mean"], se=se, interval=r["interval"], bound=r["lower"], boundary=null, p=r["p"],
             method=r["method"] + ", design-weighted", n_clusters=r["n_clusters"],
             min_attainable_p=r["min_attainable_p"])
    if se is not None and j:
        g["detectable_effect"] = _z_sum(alpha, power) * se / j
    hi = r["interval"][1] if r["interval"] else None
    if r["passed"]:
        g["result"] = "pass"
    elif hi is not None and hi <= null:
        g.update(result="fail", reason=("shown no better than the baseline" if test == "superiority" else
                                        f"shown worse than the margin: the {1 - 2 * alpha:.0%} interval's top "
                                        f"{hi:.4g} is at or below −{effect:.4g}"))
    elif r["interval"] is None and r["min_attainable_p"] > alpha:
        g.update(result="insufficient", reason=f"{r['n_clusters']} clusters: a sign-flip test cannot reach "
                                               f"α {alpha:g} (smallest p {r['min_attainable_p']:.3g})")
    else:
        g.update(result="insufficient", reason=f"p {r['p']:.4g} > α {alpha:g}")
    if g["result"] != "pass":
        if se is None or se == 0:
            g["cases_needed_reason"] = "no case moved between the versions: the spread is not measured yet"
        else:
            g["cases_needed"] = stats.cases_for_spread(len(u["ids"]), se, effect, alpha, power)
    return g


# ---- one rule on one eval ------------------------------------------------------------------------

def _use_case_estimate(side: Side, uc: str) -> tuple[float | None, float | None, bool, int]:
    """A use case's μ̂ for its own threshold gate: Rogan–Gladen corrected when the spec corrects
    that way, else its Hájek mean with the variance floor θ̂ uses (stats.stratified_hajek)."""
    row = next((r for r in side.rows() or [] if r["id"] == uc and r["pool"] == "quality"), None)
    if row is None:
        return None, None, False, 0
    if row.get("estimate_corrected"):
        c = row["estimate_corrected"]
        return c["point"], c["se"], True, row["n_cases"]
    counted = {c for c in side.s.cases if side.s.counts(c) and side.s.cases[c].get("use_case") == uc}
    vals = side.s.case_values(counted)
    ids = sorted(vals)
    h = stats.stratified_hajek({uc: {"weight": 1.0, "values": [vals[c] for c in ids],
                                     "inclusion_probs": [side.s.status[c]["inclusion_prob"] for c in ids],
                                     "clusters": [side.s.status[c]["cluster"] for c in ids]}})
    if not h or h["point"] is None:
        return None, None, False, 0
    return h["point"], h["se"], False, len(ids)


def evaluate(name: str, rule: dict, base: Side, cand: Side | None, use_case: str | None = None) -> dict:
    """One gate: `rule` ({test, bar | margin, alpha?, power?}) on the decided runs (the
    candidate, else the reported runs)."""
    g = _gate(name, rule, use_case)
    test = rule.get("test")
    decided = cand or base
    g["alpha"], g["power"] = _alpha(base.spec, rule), _power(base.spec, rule)
    if decided.refused:
        return _unknown(g, decided.refused)
    if cand is not None and base.refused:
        return _unknown(g, base.refused)
    why = judge_block(decided.meas) or (judge_block(base.meas) if cand else None)
    if why:
        return _unknown(g, why)
    if test == "threshold":
        if use_case is None:
            est = decided.est
            if est["theta"] is None:
                return _unknown(g, est["null_reason"])
            return _threshold(g, decided, est["theta"], est["se"], bool(est.get("corrected")), est["n_cases"], rule)
        point, se, corrected, n = _use_case_estimate(decided, use_case)
        if point is None:
            return _unknown(g, f"no scored quality case in {use_case}")
        return _threshold(g, decided, point, se, corrected, n, rule)
    if test in PAIRED:
        if cand is None:
            return _unknown(g, f"a {test.replace('_', '-')} test compares a candidate with the baseline: "
                               "aot-evals run --purpose candidate --variable KIND=VALUE, then report --candidate "
                               "or compare")
        if use_case is None and (base.est["theta"] is None or cand.est["theta"] is None):
            return _unknown(g, base.est["null_reason"] or cand.est["null_reason"])
        return _paired(g, base, cand, rule, use_case)
    return _unknown(g, "no decision-rule test stated")


# ---- several evals ---------------------------------------------------------------------------

def _subject(cand: Side | None, base: Side) -> dict:
    """What is being decided: the change a candidate's runs carry, else the build reported."""
    side = cand or base
    variable = next((m.get("declared_variable") for m in side.manifests if m.get("declared_variable")), None)
    commits = sorted({m.get("agent_commit") for m in side.manifests if m.get("agent_commit")})
    return {"kind": "candidate" if cand else "runs", "declared_variable": variable,
            "agent_commit": commits[0] if len(commits) == 1 else commits or None, "runs": side.run_ids,
            "baseline_runs": base.run_ids if cand else None}


def _required(ev, req: dict, base: Side, cand: Side | None) -> dict:
    """One `also_requires` entry: the other eval's headline under the rule stated here, on that
    eval's runs of the same change (rule 27)."""
    name = req.get("eval")
    out = {"eval": name, "test": req.get("test"), "margin": req.get("margin"), "bar": req.get("bar"),
           "result": "unknown", "reason": None, "runs": None, "baseline_runs": None, "p": None}
    try:
        other = ev.agent_system.eval(name)
    except ContractError as e:
        out["reason"] = str(e)
        return out
    rule = {k: req[k] for k in ("test", "margin", "bar", "alpha", "power") if req.get(k) is not None}
    rule.setdefault("alpha", _alpha(other.spec()))
    rule.setdefault("power", _power(other.spec()))
    from .report_v2 import default_runs

    if cand is None:
        if rule.get("test") in PAIRED:
            out["reason"] = f"{name}'s {rule['test'].replace('_', '-')} test needs a candidate run of this change"
            return out
        runs = default_runs(other)
        if not runs:
            out["reason"] = f"no run of {name} yet"
            return out
        g = evaluate(f"also_requires:{name}", rule, Side(other, runs), None)
        out.update(result=g["result"], reason=g["reason"], runs=runs, p=g["p"], gate=g)
        return out
    subj = _subject(cand, base)
    theirs = [m["run_id"] for m in other.runs("candidate") if m.get("finished")
              and m.get("declared_variable") == subj["declared_variable"]
              and m.get("agent_commit") == subj["agent_commit"]]
    base_runs = default_runs(other)
    if not theirs or not other.baseline_ids():
        out["reason"] = (f"no {'candidate' if not theirs else 'baseline'} run of {name} for this change "
                         f"(variable {subj['declared_variable']!r} at commit {subj['agent_commit']}): "
                         f"aot-evals --eval {name} run --purpose "
                         + (f"candidate --variable {subj['declared_variable']}" if not theirs else "baseline"))
        return out
    ob, oc = Side(other, base_runs), Side(other, theirs)
    problems = comparability_problems(other, ob, oc)
    if problems:
        out.update(reason=f"{name}: " + "; ".join(problems), runs=theirs, baseline_runs=base_runs)
        return out
    g = evaluate(f"also_requires:{name}", rule, ob, oc)
    out.update(result=g["result"], reason=g["reason"], runs=theirs, baseline_runs=base_runs, p=g["p"], gate=g)
    return out


# ---- constraints -----------------------------------------------------------------------------

def constraints(base: Side, cand: Side | None) -> dict:
    """Budgets per use case on the decided runs (rule 24; statistics §4.8): a limit holds
    whatever θ says. A breach the baseline did not have is marked new."""
    spec = base.spec
    decided = cand or base
    replay = bool(decided.manifests) and all(m.get("replay") for m in decided.manifests)
    breaches, compared, budgets = [], 0, {}
    for u in use_cases(spec):
        uc = u["id"]
        b = _budget(spec, uc)
        if not b:
            continue
        budgets[uc] = b
        op = operational([a for a in decided.s.attempts if a.get("use_case") == uc], b, replay=replay)
        before = set()
        if cand is not None:
            ob = operational([a for a in base.s.attempts if a.get("use_case") == uc], b, replay=replay)
            before = {x["budget"] for x in ob["budget_breaches"]}
        if op["budget_status"] not in (None, "not_measured"):
            compared += 1
        for x in op["budget_breaches"]:
            breaches.append({"use_case": uc, "budget": x["budget"], "limit": x["limit"], "actual": x["actual"],
                             "new": None if cand is None else x["budget"] not in before})
    if not budgets:
        status = "none"
    elif breaches:
        status = "breached"
    elif compared:
        status = "met"
    else:
        status = "not_measured"
    return {"status": status, "breaches": breaches, "budgets": budgets,
            "note": "point values against each limit; costs are skewed, so read them with their spread "
                    "(statistics §4.8)" if budgets else None}


# ---- looks -----------------------------------------------------------------------------------

def looks_path(ev):
    return ev.p("report", LOOKS_FILE)


def _look_key(rule_sha: str | None, subject: dict) -> str:
    return json.dumps({"decision_rule": rule_sha, "variable": subject.get("declared_variable"),
                       "agent_commit": subject.get("agent_commit"), "kind": subject.get("kind")}, sort_keys=True)


def look(ev, rule_sha: str | None, subject: dict) -> dict:
    """This decision's look at its change: how many distinct sets of runs the same change has
    been decided on under the same rule, counting this one."""
    key = _look_key(rule_sha, subject)
    runs = sorted(subject.get("runs") or [])
    prior = [x for x in read_jsonl(looks_path(ev)) if x.get("key") == key]
    other = [x for x in prior if sorted(x.get("runs") or []) != runs]
    sets = {json.dumps(sorted(x.get("runs") or [])) for x in other}
    return {"n": len(sets) + 1, "recorded": any(sorted(x.get("runs") or []) == runs for x in prior),
            "prior": [{"ts": x.get("ts"), "runs": x.get("runs"), "result": x.get("result")} for x in other],
            "key": key}


def record_look(ev, decision: dict) -> bool:
    """Append this decision to the looks ledger when it has a result and is a new look. Called by
    the commands that write a decision (`report`, `compare`), never by `build`."""
    lk = decision.get("look") or {}
    if decision.get("result") in (None, "unknown") or lk.get("recorded") or not lk.get("key"):
        return False
    append_jsonl(looks_path(ev), {"ts": now_iso(), "key": lk["key"], "runs": decision["subject"]["runs"],
                                  "result": decision["result"]})
    return True


# ---- comparability ---------------------------------------------------------------------------

def rule_change_problem(ev, manifests: list[dict], decided: list[dict]) -> str | None:
    """When the decision rule changed since a run was made, the change must be journaled before
    the first run decided on (v2-design §5; problem 12, rule 21). None when it is."""
    from . import journal

    now = part_hashes(ev.spec(), ev).get("decision_rule")
    changed = [m["run_id"] for m in manifests if (m.get("spec_sha") or {}).get("decision_rule") != now]
    if not changed:
        return None
    first = min((m.get("started") or "" for m in decided), default="")
    for e in journal.entries(ev.agent_system):
        if (e.get("kind") == "decision" and e.get("eval") == ev.id
                and (e.get("spec_sha") or {}).get("decision_rule") == now and (e.get("ts") or "~") <= first):
            return None
    return (f"the decision rule changed since run {changed[0]} was made, and no decision for the current rule "
            f"is journaled before the first run decided on ({first}): moving a bar or margin after seeing "
            "results inflates false passes (problem 12, rule 21). If it was decided before looking, journal it "
            f"(aot-evals --eval {ev.id} log --kind decision \"why\") and run the candidate again")


def comparability_problems(ev, base: Side, cand: Side) -> list[str]:
    from .compare import comparability

    problems = []
    for side, s in (("baseline", base), ("candidate", cand)):
        if not s.manifests:
            problems.append(f"no {side} run")
        elif s.refused:
            problems.append(f"{side}: {s.refused}")
    if problems:
        return problems
    problems += comparability(base.s, cand.s)
    why = rule_change_problem(ev, base.manifests + cand.manifests, cand.manifests)
    if why:
        problems.append(why)
    return problems


# ---- comparison ------------------------------------------------------------------------------

def _pct(v: float | None) -> str:
    return "-" if v is None else f"{100 * v:+.2f} pts"


def comparison(ev, base: Side, cand: Side) -> dict:
    """report.json's `comparison` for a 2.0 eval: 1.x's paired comparison, with the change in
    θ̂ design-weighted, its verdict from the two-sided sign-flip test per cluster at 2α (so
    "better" is exactly a superiority test passing at α), and no variance band."""
    spec = base.spec
    alpha = alpha_of(spec)
    kind, _ = quantity(spec)
    from .compare import variable_of

    out = {"generated": now_iso(), "baseline": "+".join(base.run_ids), "candidate": "+".join(cand.run_ids),
           "baseline_runs": base.run_ids, "candidate_runs": cand.run_ids,
           "declared_variable": variable_of(cand.manifests), "quantity": spec.part("estimand").get("quantity"),
           "scale": "higher is better" + (" (the failure rate's deltas negated)" if kind == "failure_rate" else ""),
           "paired": False, "refused": None, "problems": [], "verdict": None, "verdict_reasons": [],
           "theta": {"baseline": base.est["theta"], "candidate": cand.est["theta"]}}
    problems = comparability_problems(ev, base, cand)
    if problems:
        out.update(refused="; ".join(problems), problems=problems)
        return out
    u = paired_units(base, cand)
    k = {"baseline": base.s.k, "candidate": cand.s.k}
    out.update(n_cases=len(u["ids"]), baseline_only=u["baseline_only"], candidate_only=u["candidate_only"],
               gains=u["gains"], losses=u["losses"], moved=u["moved"], k=k,
               flips=stats.flip_summary(len(u["gains"]), len(u["losses"]), len(u["ids"])))
    if u["missing"] or not u["ids"]:
        out["verdict_reasons"].append("no paired case in " + (", ".join(u["missing"]) or "any use case"))
        return out
    spread = stats.weighted_mean_delta(u["deltas"], u["weights"], u["clusters"])
    p = stats.sign_flip_test(u["deltas"], clusters=u["clusters"], case_weights=u["weights"])
    ci = stats.sign_flip_interval(u["deltas"], clusters=u["clusters"], alpha=2 * alpha, case_weights=u["weights"])
    summary = stats.cluster_summary(u["clusters"])
    out.update(paired=True, net=spread["mean"], se=spread["se"], n_clusters=spread["n_clusters"],
               test={"name": "sign_flip", "p": p, "two_sided_at": 2 * alpha, "ci": ci,
                     "ci_level": 1 - 2 * alpha, "ci_method": "sign-flip test inverted, per cluster, design-weighted",
                     "min_attainable_p": stats.min_attainable_p(spread["n_clusters"]), "regime": summary.get("regime")},
               detectable_effect=(_z_sum(alpha, _power(spec)) * spread["se"]) if spread["se"] else None,
               mcnemar_midp=stats.mcnemar_midp(len(u["gains"]), len(u["losses"])))
    per = {}
    for uc_ in use_cases(spec):
        uc = uc_["id"]
        x = paired_units(base, cand, uc)
        if not x["ids"]:
            per[uc] = {"n_cases": 0, "net": None, "p": None}
            continue
        sp = stats.weighted_mean_delta(x["deltas"], x["weights"], x["clusters"])
        per[uc] = {"n_cases": len(x["ids"]), "gains": x["gains"], "losses": x["losses"], "net": sp["mean"],
                   "se": sp["se"], "p": stats.sign_flip_test(x["deltas"], clusters=x["clusters"],
                                                             case_weights=x["weights"])}
    mult = spec.part("decision_rule").get("multiplicity")
    method = mult if mult in ("holm", "benjamini_hochberg") else "benjamini_hochberg"
    ucs = list(per)
    adj = (stats.holm if method == "holm" else stats.benjamini_hochberg)([per[c]["p"] for c in ucs])
    for c, q in zip(ucs, adj, strict=True):
        per[c]["p_adjusted"] = q
    out["per_use_case"] = per
    out["per_use_case_adjustment"] = (f"{method}: the rows are diagnostics, read as a list of findings "
                                      "(statistics §4.6)")
    out["bug_finding"] = _bug_finding(base, cand)
    cons = constraints(base, cand)
    out["constraints"] = cons
    reasons = out["verdict_reasons"]
    if min(k["baseline"] or 0, k["candidate"] or 0) < 2:
        reasons.append("k = 1 on one side: no claim of improvement or regression")
        return out
    if p is not None and p <= 2 * alpha and spread["mean"] != 0:
        verdict = "better" if spread["mean"] > 0 else "worse"
        reasons.append(f"sign-flip p = {p:.4g} (two-sided, at {2 * alpha:g}); Δθ̂ {_pct(spread['mean'])}")
    else:
        verdict = "indistinguishable"
        reasons.append(f"sign-flip p = {p:.4g} (two-sided) > {2 * alpha:g}" if p is not None else "no test")
    new = [b for b in cons["breaches"] if b.get("new")]
    if new:
        names = ", ".join(f"{b['use_case']}/{b['budget']}" for b in new)
        if verdict == "better":
            verdict = "trade"
            reasons.append(f"better on θ, and a budget newly breached ({names}): weigh both (rule 24)")
        elif verdict == "indistinguishable":
            verdict = "worse"
            reasons.append(f"a budget newly breached at unchanged θ ({names})")
        else:
            reasons.append(f"also newly breached: {names}")
    out["verdict"] = verdict
    people = [g for g in base.meas["gates"] if g["id"].startswith("people_")]
    out["provisional"] = (f"the eval's agreement with people on whole runs is not established: {people[0]['detail']}"
                          if people else None)
    return out


def _bug_finding(base: Side, cand: Side) -> dict:
    """Bug-finding cases' flips, listed apart: they find failures and never enter Δθ̂ (rule 5)."""
    kind, _ = quantity(base.spec)
    ok = {c for c in base.s.cases if base.s.status[c]["pool"] == "bug_finding" and base.s.screened(c)}
    vb, vc = base.s.case_values(ok), cand.s.case_values(ok)
    sign = _good(kind)
    fixed = sorted(c for c in set(vb) & set(vc) if sign * (vc[c] - vb[c]) > 0)
    broke = sorted(c for c in set(vb) & set(vc) if sign * (vc[c] - vb[c]) < 0)
    return {"n_cases": len(set(vb) & set(vc)), "better": fixed, "worse": broke,
            "note": "bug-finding cases: read each flip; they never enter θ̂ (rule 5)"}


# ---- the decision ----------------------------------------------------------------------------

def _combine(gates: list[dict], combine: str, multiplicity: str, alpha: float) -> tuple[str, list[str]]:
    reasons = []
    if combine == "any" and len(gates) > 1:
        ps = [g["p"] for g in gates]
        adj = (stats.holm(ps) if multiplicity == "holm" else stats.benjamini_hochberg(ps)
               if multiplicity == "benjamini_hochberg" else ps)
        for g, q in zip(gates, adj, strict=True):
            g["p_adjusted"] = q
            if g["result"] == "pass" and (q is None or q > alpha):
                g["result"] = "insufficient"
                g["reason"] = f"adjusted p {q:.4g} > α {alpha:g} ({multiplicity}; one gate alone acts, rule 22)"
        if any(g["result"] == "pass" for g in gates):
            return "pass", [f"{next(g['gate'] for g in gates if g['result'] == 'pass')} passes alone (combine: any)"]
        if all(g["result"] == "fail" for g in gates):
            return "fail", ["every gate fails"]
        order = ("unknown", "insufficient", "fail")
    else:
        order = _WORST
    for res in order:
        hit = [g for g in gates if g["result"] == res]
        if hit:
            reasons += [f"{g['gate']}: {g['reason']}" for g in hit if g.get("reason")]
            return res, reasons
    return "pass", reasons


def decide(ev, base: Side, cand: Side | None, comp: dict | None = None) -> dict:
    """report.json's `decision` (v2-design §6)."""
    spec = base.spec
    rule = spec.part("decision_rule")
    alpha, power = alpha_of(spec), _power(spec)
    combine = rule.get("combine") if rule.get("combine") in ("all", "any") else "all"
    mult = rule.get("multiplicity") or "none"
    subject = _subject(cand, base)
    rule_sha = part_hashes(spec, ev).get("decision_rule")
    out = {"test": rule.get("test"), "quantity": rule.get("quantity"), "bar": rule.get("bar"),
           "margin": rule.get("margin"), "alpha": alpha, "power": power, "looks": rule.get("looks"),
           "combine": combine, "multiplicity": mult, "subject": subject, "result": "unknown",
           "reasons": [], "null_reason": None, "interval": None, "detectable_effect": None,
           "cases_needed": None, "headline": None, "gates": [], "also_requires": [],
           "constraints": None, "look": None, "refused": None}
    blocked = spec.blocked("decision")
    if blocked:
        out["null_reason"] = "the spec does not state the decision rule fully: " + ", ".join(
            sorted({i.field for i in blocked}))
        return out
    if cand is not None and comp is not None and comp.get("refused"):
        out.update(refused=comp["refused"], null_reason=f"the runs do not compare: {comp['refused']}")
        return out
    if cand is None:
        why = rule_change_problem(ev, base.manifests, base.manifests) if base.manifests else None
        if why:
            out.update(refused=why, null_reason=why)
            return out
    head = evaluate("headline", rule, base, cand)
    out.update(headline=head, interval=head["interval"], detectable_effect=head["detectable_effect"],
               cases_needed=head["cases_needed"])
    gates = [head]
    for g in rule.get("use_case_gates") or []:
        if isinstance(g, dict) and g.get("use_case"):
            gates.append(evaluate(f"use_case:{g['use_case']}", g, base, cand, use_case=g["use_case"]))
    result, reasons = _combine(gates, combine, mult, alpha)
    out["gates"] = gates[1:]
    reqs = [_required(ev, r, base, cand) for r in rule.get("also_requires") or [] if isinstance(r, dict)]
    out["also_requires"] = reqs
    if reqs and result == "pass":
        res2, why2 = _combine([{**r, "gate": f"also_requires:{r['eval']}"} for r in reqs], "all", "none", alpha)
        if res2 != "pass":
            result, reasons = res2, why2
    elif reqs:
        reasons += [f"also_requires:{r['eval']}: {r['result']}" for r in reqs if r["result"] != "pass"]
    out["constraints"] = constraints(base, cand)
    looks = rule.get("looks") or "fixed"
    lk = look(ev, rule_sha, subject)
    out["look"] = {k: lk[k] for k in ("n", "prior", "recorded", "key")}
    if looks != "fixed":
        result = "unknown"
        reasons = [f"looks: {looks} needs an always-valid interval (statistics §4.7) that this version does not "
                   "compute; decide with looks: fixed, or wait for it (never a pass on unplanned looks, rule 21)"]
    elif lk["n"] > 1 and result != "unknown":
        first = lk["prior"][0]
        result = "unknown"
        reasons = [f"looks: fixed allows one look per change, and this change was decided on other runs before "
                   f"({first['ts']}, runs {', '.join(first['runs'] or [])}: {first['result']}). Adding cases or "
                   "trials after looking and deciding again inflates false passes (rule 21): fix the size first, "
                   "then run a fresh candidate"]
    if result == "pass" and out["constraints"]["status"] == "breached":
        result = "trade"
        reasons.append("every gate passes and a constraint is breached: weigh both (rule 24): "
                       + ", ".join(f"{b['use_case']}/{b['budget']} {b['actual']:.4g} > {b['limit']:g}"
                                   for b in out["constraints"]["breaches"]))
    out["result"], out["reasons"] = result, reasons
    if result == "unknown":
        out["null_reason"] = "; ".join(reasons) or head["reason"]
    return out


# ---- rendering -------------------------------------------------------------------------------

def render_comparison(c: dict) -> str:
    lines = [f"compare  candidate {c['candidate']}  vs  baseline {c['baseline']}",
             f"  declared variable: {c.get('declared_variable') or '-'};  {c['quantity']} ({c['scale']})"]
    if c.get("refused"):
        lines.append(f"  REFUSED {c['refused']}")
        return "\n".join(lines)
    if c.get("provisional"):
        lines.append(f"  PROVISIONAL {c['provisional']}")
    lines += [f"  paired over {c.get('n_cases', 0)} cases in {c.get('n_clusters', 0)} clusters, k = {c.get('k')}",
              f"  gains  ({len(c.get('gains') or [])}): {', '.join(c.get('gains') or []) or '-'}",
              f"  losses ({len(c.get('losses') or [])}): {', '.join(c.get('losses') or []) or '-'}",
              f"  moved without flipping: {len(c.get('moved') or [])}"]
    if c.get("paired"):
        t = c["test"]
        ci = t["ci"]
        lines.append(f"  Δθ̂ {_pct(c['net'])}, {t['ci_level']:.0%} CI "
                     f"[{_pct(ci[0]) if ci else '-'}, {_pct(ci[1]) if ci else '-'}], sign-flip p = {t['p']:.4g}"
                     + (f"; detectable at 80% power: {100 * c['detectable_effect']:.1f} pts"
                        if c.get("detectable_effect") else ""))
        for uc, row in (c.get("per_use_case") or {}).items():
            if row["n_cases"]:
                lines.append(f"    {uc}: {row['n_cases']} cases, net {_pct(row['net'])}, p {row['p']:.4g}"
                             f" (adjusted {row['p_adjusted']:.4g})")
        bf = c.get("bug_finding") or {}
        if bf.get("n_cases"):
            lines.append(f"  bug-finding (never in θ̂): {len(bf['better'])} better, {len(bf['worse'])} worse "
                         f"of {bf['n_cases']}")
        for b in (c.get("constraints") or {}).get("breaches") or []:
            lines.append(f"    budget breach{' (new)' if b.get('new') else ''}: {b['use_case']} {b['budget']} "
                         f"{b['actual']:.4g} > {b['limit']:g}")
    lines.append(f"  VERDICT: {c['verdict']}  ({'; '.join(c['verdict_reasons'])})")
    return "\n".join(lines)


def render_decision(d: dict) -> str:
    head = d.get("headline") or {}
    lines = [f"  decision: {d['result']}  ({d['test']}"
             + (f", bar {d['bar']:g}" if isinstance(d.get("bar"), (int, float)) and d["test"] == "threshold" else "")
             + (f", margin {d['margin']:g}" if isinstance(d.get("margin"), (int, float)) and d["test"] != "threshold"
                else "") + f", α {d['alpha']:g}, combine {d['combine']})"]
    if head.get("estimate") is not None and head.get("interval"):
        lo, hi = head["interval"]
        lines.append(f"    headline {head['result']}: {head['estimate']:.4g} [{lo:.4g}, {hi:.4g}], p "
                     f"{head['p']:.4g}" + (f"; about {head['cases_needed']} cases would decide it"
                                           if head.get("cases_needed") else ""))
    for g in d.get("gates") or []:
        lines.append(f"    {g['gate']} {g['result']}" + (f": {g['reason']}" if g.get("reason") else ""))
    for r in d.get("also_requires") or []:
        lines.append(f"    also_requires {r['eval']} {r['result']}" + (f": {r['reason']}" if r.get("reason") else ""))
    if (d.get("constraints") or {}).get("status") not in (None, "none"):
        lines.append(f"    constraints {d['constraints']['status']}")
    for r in d.get("reasons") or []:
        lines.append(f"    - {r}")
    return "\n".join(lines)

