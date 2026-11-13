"""The measurement model of a 2.0 eval (estimators §5; statistics §3; docs/v2-design.md §4, §6):
how wrong each grader is, whether it may count, how the estimate is corrected for it, and how
many trials each case runs.

**Catch rate and clean pass rate.** Every grader (a judge, or the eval as a whole) is measured
against people's labels as a diagnostic test with failure as the positive: its catch rate (of
the runs a person failed, the share it failed) and its clean pass rate (of the runs a person
passed, the share it passed), each on its own count of labels of that kind (statistics §3.2,
§3.4). 1.x called them TNR and TPR.

**The judge floor** (v2-design §4, decided §10.3). A judge counts only when the cases its errors
cost are within `measurement.max_inflation` (default 2.0) of a code check's, at the eval's
current failure rate on its mode. The inflation factor is q(1 − q) / (J² p(1 − p)), with
q = (1 − clean) + J·p (statistics §3.3, `stats.judge_inflation`), read from the one-sided lower
confidence bounds on catch and clean at the decision rule's α, so a judge measured on few labels
cannot clear it by luck. A judge with no current calibration has unknown error rates and does not
count either (rule 13). Either way, a counted judge that grades the estimand's quantity and does
not count leaves θ̂ null with the reason.

**The eval held to people** (rule 15, statistics §3.6). Whole-run labels (`agreement`) give the
eval's own catch and clean pass rates. Floors are `measurement.people.floors` where stated,
read with the non-inferiority margin `measurement.people.margin` (statistics §4.2: the point
at the floor and the 95% lower bound within the margin of it), and otherwise the same
`max_inflation` reading as for a judge, at the eval's whole-run failure rate. Labels are counted
per kind and the count each kind needs is fixed before looking (`labels_per_kind`, rule 21).

**Corrections** (estimators §7). `rogan_gladen` corrects the observed rate with the grader's
measured rates and widens the interval by their uncertainty (`stats.rogan_gladen_rate`); the
grader is the quantity's judge for `failure_rate:<mode>`, and the eval against people for
`pass_rate`. `ppi` combines the labeled trials with every graded one (`stats.ppi_weighted`).

**Trials** (rule 16). `trials: auto` runs k = 3 until a baseline measures the split of variance
between cases and within them; then k comes from `stats.trials_for_split`.
"""

from __future__ import annotations

from collections import defaultdict

from . import stats
from .spec import DEFAULT_MAX_INFLATION, Spec, quantity, use_cases

K_DEFAULT = 3  # until a baseline measures the variance split (statistics §3.7)


def alpha_of(spec: Spec) -> float:
    a = spec.part("decision_rule").get("alpha")
    return a if isinstance(a, (int, float)) and 0 < a < 0.5 else 0.05


def max_inflation(spec: Spec) -> tuple[float, str]:
    """The limit and where it came from: the spec, or the stated default."""
    v = spec.part("measurement").get("max_inflation")
    if isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 1:
        return float(v), "measurement.max_inflation"
    return DEFAULT_MAX_INFLATION, "default (measurement.max_inflation unset)"


def lower_bound(k: int, n: int, alpha: float) -> float | None:
    """One-sided 1 − α Wilson lower bound on k of n."""
    ci = stats.wilson(k, n, stats._z(1 - alpha)) if n else None
    return ci[0] if ci else None


# ---- what the runs say -----------------------------------------------------------------------

def _design_weights(s, weights: dict, use_case_ids: set[str] | None = None) -> dict[str, float]:
    """Each counted quality case's share of θ̂: (w_s / Σw) · (1/π_i) / Σ_{j∈s} 1/π_j, over the use
    cases given (all with weight, by default). Cases with no scored trial are left out."""
    values = s.case_values({c for c in s.cases if s.counts(c)})
    by_uc: dict[str, list[str]] = defaultdict(list)
    for c in values:
        uc = s.cases[c].get("use_case")
        if (weights or {}).get(uc) and (use_case_ids is None or uc in use_case_ids):
            by_uc[uc].append(c)
    tw = sum(weights[u] for u in by_uc)
    out = {}
    for uc, ids in by_uc.items():
        inv = {c: 1 / s.status[c]["inclusion_prob"] for c in ids}
        tot = sum(inv.values())
        for c in ids:
            out[c] = weights[uc] / tw * inv[c] / tot
    return out


def weighted_rate(s, weights: dict | None, value, use_case_ids: set[str] | None = None) -> dict | None:
    """A design-based rate over the counted quality cases: each case's mean of `value(attempt)`
    over its final attempts where it is not None, then the stratified Hájek mean with the
    estimand's weights (renormalized over the use cases that have a scored case). Used for a
    failure mode's own rate and for the eval's whole-run failure rate, which the floors are read
    at. {point, se, n_trials, n_cases, use_cases} or None with no scored case."""
    if not weights:
        return None
    vals: dict[str, list[float]] = defaultdict(list)
    for a in s.finals():
        cid = a["case_id"]
        if not s.counts(cid):
            continue
        uc = s.cases[cid].get("use_case")
        if not weights.get(uc) or (use_case_ids is not None and uc not in use_case_ids):
            continue
        v = value(a)
        if v is not None:
            vals[cid].append(float(v))
    if not vals:
        return None
    strata: dict[str, dict] = {}
    for cid, xs in sorted(vals.items()):
        uc = s.cases[cid]["use_case"]
        d = strata.setdefault(uc, {"weight": weights[uc], "values": [], "inclusion_probs": [], "clusters": []})
        d["values"].append(sum(xs) / len(xs))
        d["inclusion_probs"].append(s.status[cid]["inclusion_prob"])
        d["clusters"].append(s.status[cid]["cluster"])
    r = stats.stratified_hajek(strata)
    if r is None or r["point"] is None:
        return None
    return {"point": r["point"], "se": r["se"], "ci": r["ci"], "n_trials": sum(len(v) for v in vals.values()),
            "n_cases": len(vals), "use_cases": sorted(strata)}


def mode_use_cases(spec: Spec, fm: dict) -> set[str]:
    every = {u["id"] for u in use_cases(spec)}
    ucs = fm.get("use_cases")
    return every if ucs == "*" else {u for u in ucs if u in every} if isinstance(ucs, list) else set()


# ---- a judge: its calibration and its floor --------------------------------------------------

def judge_calibration(ev, check_id: str, alpha: float = 0.05) -> dict:
    """A judge's measured error rates from its current calibration (primary backend), in catch and
    clean pass rates with counts per kind. `status`: calibrated | uncalibrated | stale | invalid."""
    from .calibrate import catch_clean, is_current, load_calibration
    from .judges import load_spec

    out = {"check": check_id, "status": "uncalibrated", "reasons": [], "backend": None,
           "catch": None, "catch_ci": None, "catch_lower": None, "clean": None, "clean_ci": None,
           "clean_lower": None, "labels": {"fail": 0, "pass": 0}, "j": None, "counts": None,
           "measured_at": None}
    try:
        spec = load_spec(ev.judge_check_path(check_id))
    except Exception as e:  # a broken judge file is reported, never fatal
        out.update(status="invalid", reasons=[f"invalid judge spec: {e}"])
        return out
    if spec.problems():
        out.update(status="invalid", reasons=list(spec.problems()))
        return out
    out["backend"] = spec.primary
    cal = load_calibration(ev, spec)
    if not cal:
        out["reasons"].append(f"not calibrated: label runs (aot-evals label queue --judge {check_id}), "
                              f"then aot-evals calibrate --judge {check_id}")
        return out
    if not is_current(ev, spec, cal):
        out.update(status="stale", reasons=["the judge or its labels changed since it was calibrated: "
                                            "a changed judge is a new instrument (rule 13)"])
        return out
    m = (cal.get("backends") or {}).get(spec.primary)
    if not m or cal.get("primary") != spec.primary:
        out["reasons"].append(f"calibrated with primary {cal.get('primary')}, now {spec.primary}")
        return out
    cc = catch_clean(m["confusion"], alpha)
    out.update(catch=cc["catch"], catch_ci=cc["catch_ci"], catch_lower=cc["catch_lower"],
               clean=cc["clean"], clean_ci=cc["clean_ci"], clean_lower=cc["clean_lower"],
               labels=cc["labels_per_kind"], j=cc["j"], measured_at=cal.get("measured_at"),
               counts={"catch_k": cc["catch_k"], "catch_n": cc["labels_per_kind"]["fail"],
                       "clean_k": cc["clean_k"], "clean_n": cc["labels_per_kind"]["pass"]})
    if not cc["labels_per_kind"]["fail"] or not cc["labels_per_kind"]["pass"]:
        out["reasons"].append("labels need both kinds: runs a person failed and runs a person passed")
        return out
    if m.get("errors"):
        out["reasons"].append(f"{m['errors']} label(s) without a verdict from the judge")
        return out
    out["status"] = "calibrated"
    return out


def floor_rate(observed: dict | None, cal: dict) -> dict | None:
    """The failure rate a floor is read at: the observed rate corrected for the grader's point
    rates (Rogan-Gladen), kept at least half a failure away from 0 and 1 over the trials it
    rests on, since at exactly 0 any false flag costs infinitely many cases."""
    if not observed or observed.get("point") is None:
        return None
    p = observed["point"]
    if cal.get("catch") is not None and cal.get("clean") is not None and cal.get("j") and cal["j"] > 0:
        p = (p + cal["clean"] - 1) / cal["j"]
    edge = 0.5 / max(1, observed.get("n_trials") or 1)
    return {"rate": min(1 - edge, max(edge, p)), "corrected_point": p, "edge": edge}


def judge_floor(cal: dict, rate: dict | None, limit: float, alpha: float) -> dict:
    """Whether a judge may count: its inflation factor at the rate, from its one-sided lower
    bounds on catch and clean at α, at or under `limit` (v2-design §4). `status` is pass |
    refused | uncalibrated | stale | invalid | unknown (no scored run to read the rate at)."""
    out = {"status": None, "reason": None, "max_inflation": limit, "rate": None, "inflation": None,
           "inflation_at_lower_bounds": None, "alpha": alpha}
    if cal["status"] != "calibrated":
        out.update(status=cal["status"] if cal["status"] in ("stale", "invalid") else "uncalibrated",
                   reason="; ".join(cal["reasons"]) or "not calibrated")
        return out
    if rate is None:
        out.update(status="unknown", reason="no scored run yet to read the failure rate at; plan counts "
                   "the judge at max_inflation")
        return out
    p = rate["rate"]
    out["rate"] = p
    out["inflation"] = stats.judge_inflation(p, cal["catch"], cal["clean"])
    lb = stats.judge_inflation(p, cal["catch_lower"], cal["clean_lower"])
    out["inflation_at_lower_bounds"] = lb
    if lb is None:
        out.update(status="refused", reason=f"at its lower bounds (catch {cal['catch_lower']:.3f}, clean "
                   f"{cal['clean_lower']:.3f}) J is at or below 0: no number of cases helps")
    elif lb > limit:
        out.update(status="refused", reason=f"costs {lb:.2f}x the cases of a code check at a {p:.1%} failure "
                   f"rate, read at its lower bounds, over the limit of {limit:g}x (statistics §3.3); more "
                   "labels of the short kind raise its lower bounds, a better judge raises its rates")
    else:
        out.update(status="pass", reason=f"{lb:.2f}x at a {p:.1%} failure rate, within {limit:g}x")
    return out


# ---- the eval against people -----------------------------------------------------------------

def people_settings(spec: Spec) -> dict:
    p = spec.part("measurement").get("people")
    p = p if isinstance(p, dict) else {}
    fl = p.get("floors") if isinstance(p.get("floors"), dict) else {}
    margin = p.get("margin") if isinstance(p.get("margin"), (int, float)) else 0.10
    return {"floors": {"catch": fl.get("catch"), "clean": fl.get("clean")}, "margin": margin,
            "labels_per_kind": p.get("labels_per_kind", "auto")}


def labels_needed(spec: Spec) -> dict:
    """How many whole-run labels of each kind the eval needs, fixed before looking (rule 21):
    a stated number, or with `auto` the Wilson ±margin size at the stated floor, or at 50% (the
    widest) where the floor comes from max_inflation (statistics §3.4, §4.2)."""
    ps = people_settings(spec)
    lpk, margin = ps["labels_per_kind"], ps["margin"]
    out = {}
    for kind, name in (("fail", "catch"), ("pass", "clean")):
        if isinstance(lpk, int) and not isinstance(lpk, bool):
            out[kind] = {"n": lpk, "source": "measurement.people.labels_per_kind"}
            continue
        floor = ps["floors"][name]
        at = floor if isinstance(floor, (int, float)) else 0.5
        out[kind] = {"n": stats.labels_for_halfwidth(at, margin),
                     "source": f"auto: a 95% interval of ±{margin:g} at "
                               + ("the floor" if floor is not None else "a 50% rate, the widest") + f" ({at:g})"}
    return out


def people_floor(spec: Spec, catch: dict, clean: dict, fail_rate: dict | None) -> dict:
    """The eval's own catch and clean pass rates against its floors (rule 15). `catch` and
    `clean` are {k, n} on whole-run labels. Stated floors are read with the margin (statistics
    §4.2, `stats.floor_evidence`); a null floor means max_inflation, as for a judge, at the eval's
    whole-run failure rate. `status`: meets | below | unmeasured | unknown."""
    ps = people_settings(spec)
    limit, limit_src = max_inflation(spec)
    alpha = alpha_of(spec)
    out = {"margin": ps["margin"], "floors": ps["floors"], "evidence": {}, "status": None, "reasons": []}
    stated = {name: ps["floors"][name] for name in ("catch", "clean") if ps["floors"][name] is not None}
    for name, r in (("catch", catch), ("clean", clean)):
        if name in stated:
            e = stats.floor_evidence(r.get("k", 0), r.get("n", 0), stated[name], ps["margin"])
            out["evidence"][name] = e
            if e is None:
                out["reasons"].append(f"no labels of the kind {name} is read on")
            elif not e["meets_margin"]:
                out["reasons"].append(
                    f"{'catch rate' if name == 'catch' else 'clean pass rate'} {e['point']:.0%} on {e['n']} labels "
                    + (f"is below its floor {e['floor']:.0%}" if not e["meets_point"] else
                       f"clears its floor {e['floor']:.0%} but its 95% lower bound {e['lower']:.0%} is more than "
                       f"{ps['margin']:.0%} below it (about {e['n_needed']} labels of that kind would do)"))
    missing = [n for n in ("catch", "clean") if n not in stated]
    if missing:
        n_f, n_p = catch.get("n", 0), clean.get("n", 0)
        e = {"max_inflation": limit, "source": limit_src, "alpha": alpha, "rate": None,
             "inflation_at_lower_bounds": None, "floors_for": missing}
        if n_f and n_p and fail_rate is not None:
            c_lo, p_lo = lower_bound(catch["k"], n_f, alpha), lower_bound(clean["k"], n_p, alpha)
            cal = {"catch": catch["k"] / n_f, "clean": clean["k"] / n_p}
            cal["j"] = cal["catch"] + cal["clean"] - 1
            fr = floor_rate(fail_rate, cal)
            e.update(rate=fr["rate"], catch_lower=c_lo, clean_lower=p_lo,
                     inflation=stats.judge_inflation(fr["rate"], cal["catch"], cal["clean"]),
                     inflation_at_lower_bounds=stats.judge_inflation(fr["rate"], c_lo, p_lo))
            lb = e["inflation_at_lower_bounds"]
            if lb is None or lb > limit:
                out["reasons"].append(
                    "the eval against people " + ("is no better than chance at its lower bounds" if lb is None
                                                  else f"costs {lb:.2f}x the cases of a perfect grader at a "
                                                       f"{fr['rate']:.1%} failure rate, over {limit:g}x"))
        elif n_f and n_p:
            e["reason"] = "no scored run yet to read the eval's failure rate at"
        out["evidence"]["max_inflation"] = e
    if not catch.get("n") or not clean.get("n"):
        out["status"] = "unmeasured"
    elif out["reasons"]:
        out["status"] = "below"
    elif missing and out["evidence"]["max_inflation"].get("inflation_at_lower_bounds") is None:
        out["status"] = "unknown"
    else:
        out["status"] = "meets"
    return out


# ---- trials ------------------------------------------------------------------------------------

def variance(s) -> dict | None:
    """The split of the quantity's variance between cases and within them, over the counted
    quality cases' scored trials (statistics §3.7), with the k it implies (rule 16)."""
    by_case: dict[str, list[float]] = defaultdict(list)
    for a in s.finals():
        if a.get("value") is not None and s.counts(a["case_id"]):
            by_case[a["case_id"]].append(a["value"])
    vc = stats.variance_components([v for _, v in sorted(by_case.items())])
    if vc is None:
        return None
    k = stats.trials_for_split(vc["between_case"], vc["within_case"])
    return {"icc": vc["icc"], "between": vc["between_case"], "within": vc["within_case"],
            "n_cases": vc["n_cases"], "mean_k": vc["mean_k"], "se_now": vc["se_now"],
            "se_double_cases": vc["se_double_cases"], "se_double_trials": vc["se_double_trials"],
            "k_recommended": k["k"] if k else None, "k_optimum": k["k_optimum"] if k else None,
            "k_rule": ("k* = sqrt(case_cost × within / between), clamped to [3, 10]; case_cost = 1: a new "
                       "case is taken to cost one trial more than its trials (Cochran 1977 §10.6)"),
            "method": vc["method"]}


def trials_for_run(ev) -> dict:
    """k for the next run of a 2.0 eval: the spec's number, or for `auto` the k the baseline's
    variance split recommends, else 3 until there is one (rule 16; v2-design §5)."""
    t = ev.spec().part("measurement").get("trials")
    if isinstance(t, int) and not isinstance(t, bool):
        return {"spec": t, "k": t, "source": "measurement.trials"}
    if t != "auto":
        return {"spec": t, "k": K_DEFAULT, "source": "default: measurement.trials is not a number"}
    from .report_v2 import Scored, default_runs, refusal

    runs = default_runs(ev)
    s = Scored(ev, runs) if runs else None
    v = variance(s) if s and not refusal(ev, ev.spec(), s.manifests) else None
    if v is None or v["k_recommended"] is None:
        return {"spec": "auto", "k": K_DEFAULT,
                "source": "auto: 3 until a baseline under this spec measures the variance split"}
    return {"spec": "auto", "k": v["k_recommended"], "source": f"auto: from the variance split of {', '.join(runs)}",
            "icc": v["icc"]}


# ---- the report's measurement key and the correction -----------------------------------------

def section(s, weights: dict | None, refused: str | None) -> dict:
    """report.json's `measurement` (v2-design §6) and what the estimate needs from it."""
    from . import agreement as ag

    ev, spec = s.ev, s.spec
    alpha = alpha_of(spec)
    limit, limit_src = max_inflation(spec)
    kind, mode = quantity(spec)
    modes = []
    gates = []
    for fm in ev.failure_modes():
        cid = fm.get("check") if isinstance(fm.get("check"), str) else None
        ctype = ev.check_type(cid) if cid else None
        ucs = mode_use_cases(spec, fm)
        obs = None if refused or not cid else weighted_rate(
            s, weights, lambda a, c=cid: None if (a.get("verdicts") or {}).get(c) is None
            else (0.0 if a["verdicts"][c] else 1.0), ucs)
        row = {"id": fm["id"], "check": cid, "type": ctype, "monitor": bool(fm.get("monitor")),
               "use_cases": sorted(ucs), "observed_rate": obs, "catch": None, "clean": None, "j": None,
               "labels": None, "inflation": None, "floor": None, "corrected_rate": None,
               "feeds_estimate": kind == "pass_rate" or (kind == "failure_rate" and fm["id"] == mode)}
        if ctype == "code":
            row.update(catch=1.0, clean=1.0, j=1.0, inflation=1.0,
                       floor={"status": "pass", "reason": "a code check has no error to correct (rule 14)"},
                       corrected_rate=obs)
        elif ctype == "judge":
            cal = judge_calibration(ev, cid, alpha)
            fr = floor_rate(obs, cal)
            fl = judge_floor(cal, fr, limit, alpha)
            fl["max_inflation_source"] = limit_src
            row.update(catch=cal["catch"], catch_ci=cal["catch_ci"], catch_lower=cal["catch_lower"],
                       clean=cal["clean"], clean_ci=cal["clean_ci"], clean_lower=cal["clean_lower"],
                       j=cal["j"], labels=cal["labels"], calibration=cal["status"],
                       inflation=fl["inflation"], inflation_at_lower_bounds=fl["inflation_at_lower_bounds"],
                       floor=fl)
            if obs is not None and cal["counts"] and cal["status"] == "calibrated":
                c = cal["counts"]
                row["corrected_rate"] = stats.rogan_gladen_rate(
                    obs["point"], (obs["se"] or 0.0) ** 2, c["catch_k"], c["catch_n"], c["clean_k"], c["clean_n"])
            if fl["status"] != "pass":
                gates.append({"id": "judge_floor" if fl["status"] in ("refused", "unknown") else "judge_calibration",
                              "check": cid, "status": fl["status"], "detail": f"judge {cid}: {fl['reason']}",
                              "feeds_estimate": row["feeds_estimate"]})
        modes.append(row)

    # the eval against people: from agreement.json when it is current for this eval and labels
    result = ag.load_result(ev)
    stale = ag.is_stale(ev, result) if result else None
    labels = ag.load_labels(ev)
    n_fail = sum(1 for r in labels if not r["label"])
    whole = None if refused else weighted_rate(
        s, weights, lambda a: None if a.get("passed") is None else (0.0 if a["passed"] else 1.0))
    people = {"labels": {"fail": n_fail, "pass": len(labels) - n_fail}, "labels_needed": labels_needed(spec),
              "measured_at": (result or {}).get("measured_at"), "stale": stale, "failure_rate": whole}
    if result and not stale:
        dev, every = result.get("dev") or {}, result.get("all") or {}
        people.update(catch=dev.get("catch"), clean=dev.get("clean"),
                      all={"catch": every.get("catch"), "clean": every.get("clean")},
                      split="dev: the floor reads the split disagreements are fixed on, as in 1.x; `all` "
                            "feeds the correction",
                      floor=people_floor(spec, dev.get("catch") or {}, dev.get("clean") or {}, whole),
                      problems=list(result.get("problems") or []), gates=list(result.get("gates") or []))
        for g in result.get("gates") or []:
            gates.append({**g, "detail": f"eval against people: {g['detail']}"})
    else:
        people.update(catch=None, clean=None, all=None, floor=None, problems=[], gates=[])
        gates.append({"id": "people_unmeasured" if not result else "people_stale",
                      "detail": "eval against people: " + (
                          "not measured: label whole runs (aot-evals agreement label queue), then aot-evals "
                          "agreement" if not result else "agreement.json is stale: the eval or its labels "
                          "changed since (aot-evals agreement)")})

    pairs = ag.labeller_agreement(ev)
    agree = {"pairs": [{k: p.get(k) for k in ("labellers", "n", "agree", "kappa", "ac1", "pass_agreement",
                                               "fail_agreement")} for p in pairs],
             "note": "read κ only near a 50% pass rate; AC1 and the agreement on fails hold up when most "
                     "runs pass (statistics §3.6)"} if pairs else None
    return {"failure_modes": modes, "max_inflation": limit, "max_inflation_source": limit_src, "alpha": alpha,
            "correction": spec.part("measurement").get("correction"), "eval_vs_people": people,
            "person_anchored": None, "variance": None if refused else variance(s), "people": agree,
            "trials": trials_for_run(ev), "gates": gates}


def _labeled_trials(s, spec: Spec) -> tuple[dict, str]:
    """(run_id, case_id, trial, attempt) -> the person's value of the quantity, and where it came
    from: whole-run labels for pass_rate, the quantity judge's own labels for failure_rate."""
    from . import agreement as ag

    kind, mode = quantity(spec)
    out = {}
    if kind == "pass_rate":
        for r in ag.load_labels(s.ev):
            out[(r.get("run"), r.get("case_id"), r.get("trial"), r.get("attempt"))] = 1.0 if r["label"] else 0.0
        return out, "whole-run labels (agreement)"
    fm = next((f for f in s.ev.failure_modes() if f.get("id") == mode), {})
    cid = fm.get("check")
    if not isinstance(cid, str) or s.ev.check_type(cid) != "judge":
        return out, "none"
    from .judges import load_spec
    from .labels import load_labels as judge_labels

    try:
        js = load_spec(s.ev.judge_check_path(cid))
    except Exception:
        return out, "none"
    for r in judge_labels(s.ev, js):
        if r.get("run") and r.get("case_id") is not None and r.get("trial") is not None:
            out[(r["run"], r["case_id"], r["trial"], r.get("attempt") or 0)] = 0.0 if r["label"] else 1.0
    return out, f"judge {cid}'s labels"


def correct(s, meas: dict, weights: dict, observed: dict) -> dict:
    """The correction the spec names, applied to the observed θ̂ ({point, se, ci}). Returns the
    keys to merge into `estimate`: theta/ci/se corrected, or theta None with null_reason when the
    correction needs a measurement that is missing; `corrected` and how."""
    spec = s.spec
    corr = spec.part("measurement").get("correction")
    kind, mode = quantity(spec)
    judges = sorted({r["check"] for r in meas["failure_modes"] if r["type"] == "judge" and r["feeds_estimate"]})
    base = {"theta": observed["point"], "ci": observed["ci"], "se": observed["se"], "corrected": False,
            "correction": corr}
    if corr in (None, "none"):
        base["corrected_reason"] = ("correction: none; counted judges (" + ", ".join(judges) + ") are taken "
                                    "as they graded" if judges else "correction: none")
        return base
    if kind == "failure_rate":
        row = next((r for r in meas["failure_modes"] if r["id"] == mode), None)
        if row is None or row["type"] != "judge":
            base["corrected_reason"] = "the quantity's check is code: it has no error to correct (rule 14)"
            return base
    if corr == "rogan_gladen":
        if kind == "failure_rate":
            c = judge_calibration(s.ev, row["check"], meas["alpha"])["counts"]
            grader = f"judge {row['check']}"
            if not c:
                return {**base, "theta": None, "ci": None, "se": None,
                        "null_reason": f"rogan_gladen needs {grader}'s calibration (aot-evals calibrate)"}
            r = stats.rogan_gladen_rate(observed["point"], observed["se"] ** 2, c["catch_k"], c["catch_n"],
                                        c["clean_k"], c["clean_n"])
            if r is None:
                return {**base, "theta": None, "ci": None, "se": None,
                        "null_reason": f"{grader} is no better than chance (J <= 0): its rate cannot be corrected"}
            return {**base, "theta": r["point"], "ci": r["ci"], "se": r["se"], "corrected": True,
                    "correction_detail": {**r, "grader": grader}}
        people = meas["eval_vs_people"]
        cat, cln = (people.get("all") or {}).get("catch") or {}, (people.get("all") or {}).get("clean") or {}
        if not cat.get("n") or not cln.get("n"):
            return {**base, "theta": None, "ci": None, "se": None,
                    "null_reason": "rogan_gladen on a pass rate needs the eval's catch and clean pass rates "
                                   "against people, current for this eval (aot-evals agreement)"}
        r = stats.rogan_gladen_rate(1 - observed["point"], observed["se"] ** 2, cat["k"], cat["n"], cln["k"], cln["n"])
        if r is None:
            return {**base, "theta": None, "ci": None, "se": None,
                    "null_reason": "the eval is no better than chance against people (J <= 0)"}
        return {**base, "theta": 1 - r["point"], "ci": [1 - r["ci"][1], 1 - r["ci"][0]], "se": r["se"],
                "corrected": True, "correction_detail": {**r, "grader": "the eval against people",
                                                         "note": "on the failure rate 1 − θ"}}
    if corr == "ppi":
        labeled, source = _labeled_trials(s, spec)
        dw = _design_weights(s, weights)
        n_trials: dict[str, int] = defaultdict(int)
        for a in s.finals():
            if a.get("value") is not None and a["case_id"] in dw:
                n_trials[a["case_id"]] += 1
        y, f, w = [], [], []
        for a in s.finals():
            key = (a["run_id"], a["case_id"], a["trial"], a["attempt"])
            if a.get("value") is None or a["case_id"] not in dw or key not in labeled:
                continue
            y.append(labeled[key])
            f.append(a["value"])
            w.append(dw[a["case_id"]] / n_trials[a["case_id"]])
        r = stats.ppi_weighted(observed["point"], observed["se"] ** 2, y, f, w)
        if r is None:
            return {**base, "theta": None, "ci": None, "se": None,
                    "null_reason": f"ppi needs at least two scored quality trials with a person's label ({source}; "
                                   f"{len(y)} so far): label runs drawn by the queue"}
        meas["person_anchored"] = {"ppi": {**r, "labels_from": source,
                                           "assumption": "the labeled trials are a random sample of the scored "
                                                         "quality trials (statistics §3.6)"}}
        return {**base, "theta": r["point"], "ci": r["ci"], "se": r["se"], "corrected": True,
                "correction_detail": {"method": r["method"], "lambda": r["lambda"], "n_labeled": r["n_labeled"],
                                      "labels_from": source}}
    return base


def judge_block(meas: dict) -> str | None:
    """Why θ̂ cannot count a judge that feeds it, or None."""
    bad = [g for g in meas["gates"] if g["id"] in ("judge_floor", "judge_calibration") and g.get("feeds_estimate")]
    if not bad:
        return None
    return ("; ".join(g["detail"] for g in bad)
            + " (rule 13: its numbers count once its error rates are measured and within max_inflation)")

