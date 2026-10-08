"""C13 `compare` (E2): did the candidate change correctness or cost, case by case?

Refuses, rather than computes, when the runs measure different things (G7): the two sides'
manifests may differ only on the candidate's declared independent variable. When they are
comparable:

- **paired per case**: each case's pass rate in the baseline and in the candidate. Gains (the
  case's majority verdict flips fail -> pass) and losses (pass -> fail) are listed separately;
  a net delta is never reported alone (M6);
- **McNemar's exact test** on the flips, and a **bootstrap 95% CI** on the mean per-case delta;
- the baseline's **variance band**: a change inside it is not called a change (M5);
- the **minimum detectable effect** at 80% power from the baseline's within-case variance (M7);
- **plane-B deltas** per category against budgets. A correctness gain with a new budget breach
  is a "trade" (G11); an operational regression at unchanged correctness is a "worse".

"""

from __future__ import annotations

import hashlib
import json
import math
import random
import re
from collections import defaultdict

from . import stats
from .repo import SETS, Evals
from .report import BUILD_FIELDS, Context, manifest_view, operational
from .util import now_iso, write_json

# Declared variable (the part before "=" in `run --variable`) -> manifest fields it may change.
VARIABLES = {
    "prompt": {"agent_commit", "invoke"},
    "skills": {"agent_commit", "invoke"},
    "instructions": {"agent_commit", "invoke"},
    "tools": {"agent_commit", "invoke", "fakes_sha256"},
    "code": {"agent_commit", "invoke"},
    "config": {"agent_commit", "invoke"},
    "model": {"agent_commit", "invoke", "model_ids", "model_ids_observed"},
    "harness": {"agent_commit", "invoke", "harness"},
    "environment": {"fakes_sha256"},
    "fakes": {"fakes_sha256"},
    "simulator": {"simulator"},
}
SIGNIFICANCE = 0.05
BOOTSTRAP = 10_000


view = manifest_view


def variable_of(manifests: list[dict]) -> str | None:
    for m in manifests:
        if m.get("declared_variable"):
            return str(m["declared_variable"])
    return None


def allowed_fields(variable: str | None) -> set[str]:
    if not variable:
        return set()
    return VARIABLES.get(variable.split("=", 1)[0].strip().lower(), set())


# Per-item fields: a side's runs may each cover some of the items (runs split by category), so
# they are merged by key and differ only where the same key has a different value.
MERGED = ("case_set", "checks", "judges", "model_ids_observed")


def _keyed(field: str, v) -> dict:
    if field == "judges":
        return {j[0]: list(j[1:]) for j in v or []}
    if field == "model_ids_observed":
        return {site: sorted(models) for site, models in (v or {}).items()}
    return dict(v) if isinstance(v, dict) else {"*": v}


def side_view(side: str, manifests: list[dict]) -> tuple[dict, list[str]]:
    """One view of a side's runs, and what stops them being one measurement of one build. Runs
    of one build over different cases (split by category, to pace a rate-limited runtime) are
    one side; runs of different builds, or that measured a case or check differently, are not."""
    views = [view(m) for m in manifests]
    problems = []
    merged = {f: views[0][f] for f in (*BUILD_FIELDS, "agent_dirty")}
    for m, v in zip(manifests[1:], views[1:], strict=True):
        d = [f for f in BUILD_FIELDS if json.dumps(v[f], sort_keys=True, default=str)
             != json.dumps(merged[f], sort_keys=True, default=str)]
        if d:
            problems.append(f"{side} runs are not one build: {manifests[0]['run_id']} and "
                            f"{m['run_id']} differ on {d}")
    for f in MERGED:
        acc: dict = {}
        for m, v in zip(manifests, views, strict=True):
            for key, val in _keyed(f, v[f]).items():
                if f == "model_ids_observed":
                    acc[key] = sorted(set(acc.get(key, [])) | set(val))
                elif key in acc and acc[key] != val:
                    problems.append(f"{side} runs measured {key!r} differently ({f}): see {m['run_id']}")
                else:
                    acc[key] = val
        merged[f] = acc
    if any(v["agent_dirty"] for v in views):
        problems.append(f"{side} ran with uncommitted agent changes: what ran cannot be named")
    return merged, problems


def side_differences(a: dict, b: dict) -> list[str]:
    """Build fields that differ, and per-item fields that differ on an item both sides have."""
    def norm(v):
        return json.dumps(v, sort_keys=True, default=str)
    out = [f for f in BUILD_FIELDS if norm(a[f]) != norm(b[f])]
    out += [f for f in MERGED if any(norm(a[f][k]) != norm(b[f][k]) for k in set(a[f]) & set(b[f]))]
    return out


def comparability(base: Context, cand: Context) -> list[str]:
    problems = []
    sides = {}
    for side, ctx in (("baseline", base), ("candidate", cand)):
        if not ctx.manifests:
            problems.append(f"no {side} run")
            continue
        sides[side], p = side_view(side, ctx.manifests)
        problems += p
    if problems:
        return problems
    variable = variable_of(cand.manifests)
    diffs = side_differences(sides["baseline"], sides["candidate"])
    undeclared = [d for d in diffs if d not in allowed_fields(variable)]
    if undeclared:
        hint = (f"declared variable {variable!r} covers {sorted(allowed_fields(variable))}" if variable
                else "the candidate declared no variable (run --variable KIND=VALUE)")
        problems.append(f"manifests differ on {undeclared}; {hint}")
    return problems


# ---- paired statistics ---------------------------------------------------------------------------

def case_rates(ctx: Context, set_name: str | None = None, category: str | None = None) -> dict[str, tuple]:
    out: dict[str, list] = defaultdict(lambda: [0, 0])
    for a in ctx.finals():
        if a.get("passed") is None or not ctx.gated(a["case_id"]):
            continue
        if set_name and a.get("set") != set_name:
            continue
        if category and a.get("category") != category:
            continue
        out[a["case_id"]][0] += 1 if a["passed"] else 0
        out[a["case_id"]][1] += 1
    return {c: (p, n) for c, (p, n) in out.items() if n}


def majority(p: int, n: int) -> bool | None:
    if p * 2 == n:
        return None
    return p * 2 > n


def mcnemar_exact(gains: int, losses: int) -> float:
    n = gains + losses
    if n == 0:
        return 1.0
    k = min(gains, losses)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / 2**n
    return min(1.0, 2 * tail)


def min_flips_for_significance(alpha: float = SIGNIFICANCE) -> int:
    """The fewest one-directional flips McNemar's exact test can call significant, at any N."""
    n = 1
    while mcnemar_exact(n, 0) >= alpha:
        n += 1
    return n


def bootstrap_ci(deltas: list[float], seed: int = 0) -> list[float] | None:
    if len(deltas) < 2:
        return None
    rng = random.Random(seed)
    n = len(deltas)
    means = sorted(sum(deltas[rng.randrange(n)] for _ in range(n)) / n for _ in range(BOOTSTRAP))
    return [means[int(0.025 * BOOTSTRAP)], means[int(0.975 * BOOTSTRAP) - 1]]


def paired(base: dict, cand: dict) -> dict:
    ids = sorted(set(base) & set(cand))
    deltas, gains, losses, moved = [], [], [], []
    for c in ids:
        (pb, nb), (pc, nc) = base[c], cand[c]
        rb, rc = pb / nb, pc / nc
        deltas.append(rc - rb)
        mb, mc = majority(pb, nb), majority(pc, nc)
        if mb is False and mc is True:
            gains.append(c)
        elif mb is True and mc is False:
            losses.append(c)
        elif rc != rb:
            moved.append({"case": c, "baseline": rb, "candidate": rc})
    return {
        "n_cases": len(ids),
        "baseline_only": sorted(set(base) - set(cand)), "candidate_only": sorted(set(cand) - set(base)),
        "gains": gains, "losses": losses, "moved": moved,
        "net": sum(deltas) / len(deltas) if deltas else None,
        "test": {"name": "mcnemar_exact", "p": mcnemar_exact(len(gains), len(losses)),
                 "ci": bootstrap_ci(deltas), "ci_method": "bootstrap over cases, mean per-case delta"},
    }


def band(ctx: Context) -> list[float] | None:
    per_repeat: dict[tuple, list[bool]] = defaultdict(list)
    for a in ctx.finals():
        if a.get("passed") is not None and ctx.gated(a["case_id"]):
            per_repeat[(ctx.pass_of.get(a["run_id"]), a["trial"])].append(bool(a["passed"]))
    rates = [sum(v) / len(v) for v in per_repeat.values() if v]
    return [min(rates), max(rates)] if len(rates) >= 2 else None


def mde_from(ctx: Context, rates: dict[str, tuple]) -> float | None:
    if not rates:
        return None
    within = sum((p / n) * (1 - p / n) for p, n in rates.values()) / len(rates)
    k = min(n for _, n in rates.values())
    return stats.mde(len(rates), k=k, within_case_var=within)


# ---- plane B -------------------------------------------------------------------------------------

DELTA_KEYS = ("cost_per_success", "cost_per_run", "latency_p50", "latency_p90", "cache_hit_rate")


def _op(ctx: Context, category: str | None = None) -> dict:
    atts = [a for a in ctx.attempts if category is None or a.get("category") == category]
    return operational(atts, ctx.ev.budget_for(category) if category else None)


def _delta(b: dict, c: dict) -> dict:
    out = {}
    for k in DELTA_KEYS:
        out[k] = c[k] - b[k] if b.get(k) is not None and c.get(k) is not None else None
    eb, ec = b.get("error_rate"), c.get("error_rate")
    out["error_rate"] = ec["point"] - eb["point"] if eb and ec else None
    return out


def operational_comparison(ev: Evals, base: Context, cand: Context) -> dict:
    cats = sorted({a.get("category") for a in base.attempts + cand.attempts if a.get("category")})
    per_cat, regressions = {}, []
    for c in cats:
        ob, oc = _op(base, c), _op(cand, c)
        new = sorted({x["budget"] for x in oc["budget_breaches"]} - {x["budget"] for x in ob["budget_breaches"]})
        for key in new:
            br = next(x for x in oc["budget_breaches"] if x["budget"] == key)
            regressions.append({"category": c, "budget": key, "limit": br["limit"], "candidate": br["actual"]})
        per_cat[c] = {"baseline": {k: ob.get(k) for k in DELTA_KEYS},
                      "candidate": {k: oc.get(k) for k in DELTA_KEYS},
                      "delta": _delta(ob, oc), "candidate_budget_status": oc["budget_status"],
                      "new_breaches": new}
    return {"overall_delta": _delta(_op(base), _op(cand)), "per_category": per_cat,
            "regressions_beyond_budget": regressions}


# ---- the comparison ------------------------------------------------------------------------------

def compare(ev: Evals, baseline_runs: list[str], candidate_runs: list[str]) -> dict:
    base, cand = Context(ev, baseline_runs), Context(ev, candidate_runs)
    out = {
        "generated": now_iso(),
        "baseline": "+".join(baseline_runs), "candidate": "+".join(candidate_runs),
        "baseline_runs": baseline_runs, "candidate_runs": candidate_runs,
        "declared_variable": variable_of(cand.manifests),
        "paired": False, "refused": None, "problems": [],
    }
    problems = comparability(base, cand)
    if problems:
        out.update(refused="G7: " + "; ".join(problems), problems=problems, verdict=None)
        return out

    rb, rc = case_rates(base), case_rates(cand)
    p = paired(rb, rc)
    k = min(base.k or 0, cand.k or 0)
    b_band = band(base)
    width = (b_band[1] - b_band[0]) if b_band else None
    out.update(
        paired=True, **p,
        k={"baseline": base.k, "candidate": cand.k},
        variance_band={"baseline": b_band, "candidate": band(cand)},
        mde_at_80_power=mde_from(base, {c: rb[c] for c in rb if c in rc}),
        min_flips_for_significance=min_flips_for_significance(),
        per_set={s: paired(case_rates(base, set_name=s), case_rates(cand, set_name=s)) for s in SETS},
        per_category={c: paired(case_rates(base, category=c), case_rates(cand, category=c))
                      for c in sorted({a.get("category") for a in base.attempts if a.get("category")})},
    )
    for s in SETS:
        out["per_set"][s]["label"] = ("quality-estimate set" if s == "quality_estimate"
                                      else "error-finding set — not a quality estimate")
    ops = operational_comparison(ev, base, cand)
    out["operational"] = ops
    overall = ops["overall_delta"]
    out["operational_delta"] = {"cost_per_success": overall["cost_per_success"],
                                "latency_p90": overall["latency_p90"], "error_rate": overall["error_rate"]}

    # verdict
    reasons = []
    significant = p["test"]["p"] < SIGNIFICANCE and p["test"]["ci"] is not None and (
        p["test"]["ci"][0] > 0 or p["test"]["ci"][1] < 0)
    inside_band = width is not None and p["net"] is not None and abs(p["net"]) <= width
    if k < 2:
        verdict = None
        reasons.append("G2: k = 1 on one side; no claim of improvement or regression")
    elif not significant or inside_band:
        verdict = "indistinguishable"
        reasons.append("paired test not significant" if not significant else
                       f"net {p['net']:+.3f} is inside the baseline variance band (width {width:.3f})")
    else:
        verdict = "better" if p["net"] > 0 else "worse"
        reasons.append(f"McNemar p = {p['test']['p']:.4f}; CI {p['test']['ci']}")
    if ops["regressions_beyond_budget"] and verdict is not None:
        breaches = ", ".join(f"{r['category']}/{r['budget']}" for r in ops["regressions_beyond_budget"])
        if verdict == "better":
            verdict = "trade"
            reasons.append(f"G11: correctness improved but plane B regressed beyond budget ({breaches})")
        elif verdict == "indistinguishable":
            verdict = "worse"
            reasons.append(f"operational regression beyond budget at unchanged correctness ({breaches})")
        else:
            reasons.append(f"also regressed beyond budget: {breaches}")
    out["verdict"] = verdict
    out["verdict_reasons"] = reasons
    return out


def comparison_path(ev: Evals, comp: dict):
    """A short, stable name: the declared variable and a hash of both sides' run ids. Joining
    the run ids themselves overflowed the file-name limit with six candidate runs."""
    sides = f"{comp['candidate']}|{comp['baseline']}"
    digest = hashlib.sha256(sides.encode()).hexdigest()[:12]
    label = re.sub(r"[^A-Za-z0-9._-]+", "-", comp.get("declared_variable") or "candidate")[:40].strip("-")
    return ev.p("report", "comparisons", f"{label or 'candidate'}-{digest}.json")


def save(ev: Evals, comp: dict) -> str:
    path = comparison_path(ev, comp)
    write_json(path, comp)
    return str(path)


def latest_for(ev: Evals, baseline_runs: list[str]) -> dict | None:
    d = ev.p("report", "comparisons")
    if not d.exists():
        return None
    key = "+".join(baseline_runs)
    found = []
    for f in d.glob("*.json"):
        c = json.loads(f.read_text())
        if c.get("baseline") == key:
            found.append(c)
    return max(found, key=lambda c: c.get("generated", "")) if found else None


def render(c: dict) -> str:
    lines = [f"C13 compare  candidate {c['candidate']}  vs  baseline {c['baseline']}",
             f"  declared variable: {c.get('declared_variable') or '-'}"]
    if c.get("refused"):
        lines.append(f"  REFUSED {c['refused']}")
        return "\n".join(lines)

    def pct(v):
        return "-" if v is None else f"{100 * v:+.1f} pts"

    def num(v, unit=""):
        return "-" if v is None else f"{v:+.4g}{unit}"
    t = c["test"]
    ci = t["ci"]
    mde = "-" if c["mde_at_80_power"] is None else f"{100 * c['mde_at_80_power']:.1f} pts"
    lines += [
        f"  paired over {c['n_cases']} cases, k = {c['k']}",
        f"  gains  ({len(c['gains'])}): {', '.join(c['gains']) or '-'}",
        f"  losses ({len(c['losses'])}): {', '.join(c['losses']) or '-'}",
        f"  moved without flipping: {len(c['moved'])}",
        f"  net {pct(c['net'])}, 95% CI [{pct(ci[0]) if ci else '-'}, {pct(ci[1]) if ci else '-'}], "
        f"McNemar exact p = {t['p']:.4f}",
        f"  baseline variance band {c['variance_band']['baseline']}; MDE at 80% power "
        f"{mde}; "
        f"at least {c['min_flips_for_significance']} one-way flips needed",
    ]
    for d in c["per_set"].values():
        if d["n_cases"]:
            lines.append(f"  {d['label']}: {d['n_cases']} cases, +{len(d['gains'])} / -{len(d['losses'])}, "
                         f"net {pct(d['net'])}")
    od = c["operational_delta"]
    lines.append(f"  plane B deltas: cost/success {num(od['cost_per_success'], ' USD')}, "
                 f"p90 latency {num(od['latency_p90'], ' ms')}, error rate {pct(od['error_rate'])}")
    for r in c["operational"]["regressions_beyond_budget"]:
        lines.append(f"    new budget breach: {r['category']} {r['budget']} {r['candidate']} > {r['limit']}")
    lines.append(f"  VERDICT: {c['verdict']}  ({'; '.join(c['verdict_reasons'])})")
    return "\n".join(lines)
