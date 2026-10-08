"""Measuring the suite itself (docs/method.md §2.4): C14 coverage, C15 redundancy, E8 and E9.

**Coverage (M12).** Cases per (taxonomy entry × failure mode), zeros included, against a list
written for another purpose (G5). Empty cells become an authoring queue ordered by worth.

**Redundancy (M13).** Run the suite against two or more agent versions. A case every version
passes, or every version fails, cannot say which version is better. Each case is classified by its
majority verdict per version: always-pass, always-fail or discriminating. Its discrimination index
is the spread of its pass rate across versions. Several runs of one version are pooled; runs of the
same build do not count as different versions, or noise would look like discrimination.

**Prune proposal (E9).** Keep every discriminating case. Of the always-pass cases, keep enough
regression guards that no coverage cell and no category goes empty, and propose pruning the rest.
Always-fail cases go to review: a broken case, or a real persistent bug, but never a silent prune.
Quality-estimate cases are never pruned: that set is sampled by traffic share, and pruning it
would bias the estimate.

Pruning only concordant cases cannot change any version-to-version paired test: McNemar's test
depends on the discordant cases only. The proposal re-runs every pairwise test on the pruned
suite to show it.
"""

from __future__ import annotations

import json
from collections import defaultdict
from itertools import combinations

from .compare import case_rates, majority, mcnemar_exact, min_flips_for_significance, view
from .repo import ALL_CATEGORIES, Evals
from .report import BUILD_FIELDS, Context, check_rows
from .util import load_yaml

DEFAULT_THRESHOLD = 0.3
WORTH_RANK = {"high": 3, "medium": 2, "low": 1}
COST_RANK = {"high": 3, "medium": 2, "low": 1, "none": 0}


# ---- coverage ------------------------------------------------------------------------------------

def authoring_queue(ev: Evals, cells: list[dict]) -> list[dict]:
    """Empty coverage cells, most valuable first: by the worth of the failure mode's categories,
    then by the cost of that failure in their cost matrices."""
    cats = {c["id"]: c for c in ev.categories() if c.get("id")}
    fms = {f["id"]: f for f in ev.failure_modes() if f.get("id")}
    out = []
    for cell in cells:
        if cell["n"] or "not_applicable" in cell:
            continue
        fm = fms.get(cell["failure_mode"]) or {}
        fcats = list(cats) if ALL_CATEGORIES in (fm.get("categories") or []) else fm.get("categories") or []
        worth = max((WORTH_RANK.get(cats.get(c, {}).get("worth"), 0) for c in fcats), default=0)
        cost = max((COST_RANK.get(str((cats.get(c, {}).get("cost") or {}).get(fm.get("cost_cell"))), 0)
                    for c in fcats), default=0)
        out.append({**cell, "categories": fcats, "worth_rank": worth, "cost_rank": cost,
                    "command": "C6 author: write a case for this cell (build)"})
    out.sort(key=lambda c: (-c["worth_rank"], -c["cost_rank"], c["taxonomy_entry"], c["failure_mode"]))
    return out


# ---- versions ------------------------------------------------------------------------------------

VERSION_FIELDS = BUILD_FIELDS


def versions(ev: Evals, run_ids: list[str] | None = None) -> list[dict]:
    """Finished, non-smoke runs grouped into agent versions (identical agent-defining fields)."""
    manifests = [m for m in ev.runs() if m.get("finished") and m.get("purpose") != "smoke"]
    if run_ids:
        manifests = [m for m in manifests if m["run_id"] in run_ids]
    groups: dict[str, list[dict]] = {}
    for m in manifests:
        v = view(m)
        key = json.dumps({f: v[f] for f in VERSION_FIELDS}, sort_keys=True, default=str)
        groups.setdefault(key, []).append(m)
    out = []
    for i, ms in enumerate(groups.values()):
        commit = (ms[0].get("agent_commit") or "uncommitted")[:8]
        var = next((m.get("declared_variable") for m in ms if m.get("declared_variable")), None)
        out.append({"version": f"v{i + 1}:{commit}" + (f":{var}" if var else ""),
                    "runs": [m["run_id"] for m in ms]})
    return out


# ---- redundancy ----------------------------------------------------------------------------------

def threshold_for(ev: Evals) -> float:
    a = load_yaml(ev.p("allocation.yaml")) or {}
    return float(a.get("discriminating_threshold", DEFAULT_THRESHOLD))


def redundancy(ev: Evals, run_ids: list[str] | None = None, threshold: float | None = None) -> dict | None:
    vs = versions(ev, run_ids)
    if len(vs) < 2:
        return None
    threshold = threshold_for(ev) if threshold is None else threshold
    ctxs = {v["version"]: Context(ev, v["runs"]) for v in vs}
    rates = {name: case_rates(ctx) for name, ctx in ctxs.items()}
    cases = {c["id"]: c for c in ev.cases(include_dropped=False) if c.get("id")}

    per_case = []
    for cid in sorted(set().union(*[set(r) for r in rates.values()])):
        seen = {v: r[cid] for v, r in rates.items() if cid in r}
        if len(seen) < 2:
            per_case.append({"case": cid, "class": "unclassified", "index": None,
                             "reason": "ran on fewer than two versions"})
            continue
        majorities = {v: majority(p, n) for v, (p, n) in seen.items()}
        pr = [p / n for p, n in seen.values()]
        if all(m is True for m in majorities.values()):
            cls = "always_pass"
        elif all(m is False for m in majorities.values()):
            cls = "always_fail"
        else:
            cls = "discriminating"
        case = cases.get(cid, {})
        per_case.append({"case": cid, "class": cls, "index": max(pr) - min(pr),
                         "category": case.get("category"), "set": case.get("set"),
                         "rates": {v: p / n for v, (p, n) in seen.items()}})

    classified = [c for c in per_case if c["class"] != "unclassified"]
    counts = {k: sum(1 for c in classified if c["class"] == k)
              for k in ("always_pass", "always_fail", "discriminating")}
    fraction = counts["discriminating"] / len(classified) if classified else None
    out = {"candidates": [v["version"] for v in vs], "versions": vs, **counts,
           "unclassified": len(per_case) - len(classified),
           "discriminating_fraction": fraction, "threshold": threshold,
           "below_threshold": fraction is not None and fraction < threshold,
           "per_case": sorted(per_case, key=lambda c: (c["index"] is None, -(c["index"] or 0), c["case"]))}
    out["proposal"] = proposal(ev, out, rates, Context(ev, [r for v in vs for r in v["runs"]]))
    return out


def proposal(ev: Evals, red: dict, rates: dict[str, dict], all_ctx: Context) -> dict:
    cases = {c["id"]: c for c in ev.cases(include_dropped=False) if c.get("id")}
    for c in cases.values():  # cells as coverage counts them, side-effect modes included
        c["_modes"] = [fm.get("id") for fm in ev.failure_modes_for_case(c)]
    by = {c["case"]: c for c in red["per_case"]}
    keep, prune, review, guards = [], [], [], []
    covered = defaultdict(int)  # (entry, fm) -> kept cases
    for cid, row in by.items():
        is_qe = (cases.get(cid) or {}).get("set") == "quality_estimate"
        if row["class"] in ("discriminating", "unclassified") or is_qe:
            keep.append(cid)
            _cover(covered, cases.get(cid))
        elif row["class"] == "always_fail":
            review.append(cid)
            _cover(covered, cases.get(cid))
    # Regression guards: always-pass cases that keep a coverage cell or a category non-empty.
    kept_cats = {cases[c].get("category") for c in keep + review if c in cases}
    candidates = sorted((c for c, r in by.items() if r["class"] == "always_pass"
                         and (cases.get(c) or {}).get("set") != "quality_estimate"),
                        key=lambda c: c)
    for cid in candidates:
        case = cases.get(cid) or {}
        cells = _cells(case)
        needed = any(covered[cell] == 0 for cell in cells) or case.get("category") not in kept_cats
        if needed:
            guards.append(cid)
            _cover(covered, case)
            kept_cats.add(case.get("category"))
        else:
            prune.append(cid)

    pruned_set = set(prune)
    checks = []
    for pair in combinations(rates, 2):
        before = _flips(rates[pair[0]], rates[pair[1]], set())
        after = _flips(rates[pair[0]], rates[pair[1]], pruned_set)
        checks.append({"versions": list(pair), "before": before, "after": after,
                       "preserved": before["gains"] == after["gains"] and before["losses"] == after["losses"]})

    cost_saved = None
    costs = defaultdict(list)
    for a in all_ctx.attempts:
        if a.get("cost_usd") is not None:
            costs[a["case_id"]].append(a["cost_usd"])
    if costs:
        per_trial = {c: sum(v) / len(v) for c, v in costs.items()}
        total = sum(per_trial.values())
        cost_saved = (sum(per_trial.get(c, 0.0) for c in prune) / total) if total else None

    check_props = []
    for row in check_rows(all_ctx):
        if row["evaluations"] and row["trigger_rate"] == 0:
            check_props.append({"check": row["id"], "why": f"never fired in {row['evaluations']} evaluations (M11)"})
        elif row["trigger_rate"] and row["sole_failure_rate"] == 0:
            check_props.append({"check": row["id"], "why": "only ever fires together with another check (M11)"})

    n_before = len(by)
    n_after = n_before - len(prune)
    return {
        "keep_discriminating": sorted(c for c in keep if by[c]["class"] == "discriminating"),
        "keep_quality_estimate": sorted(c for c in keep if (cases.get(c) or {}).get("set") == "quality_estimate"
                                        and by[c]["class"] != "discriminating"),
        "keep_regression_guards": sorted(guards),
        "prune": sorted(prune),
        "review_always_fail": sorted(review),
        "suite_size": {"before": n_before, "after": n_after},
        "share_of_run_cost_saved": cost_saved,
        "detectable_effect": {
            "preserved": all(c["preserved"] for c in checks),
            "pairwise_tests": checks,
            "min_flips_for_significance": min_flips_for_significance(),
            "why": ("pruned cases are concordant across every version, so every paired test between "
                    "versions (which depends only on discordant cases) is unchanged"),
        },
        "check_prune_candidates": check_props,
        "how_to_apply": "aot-evals screen --drop <case> --reason 'pruned: always-pass, redundant (C15)'; "
                        "the owner decides, case by case",
    }


def _cells(case: dict) -> list[tuple]:
    modes = case.get("_modes", case.get("failure_modes")) or []
    return [(e, m) for e in case.get("taxonomy_entries") or [] for m in modes]


def _cover(covered: dict, case: dict | None) -> None:
    for cell in _cells(case or {}):
        covered[cell] += 1


def _flips(a: dict, b: dict, exclude: set) -> dict:
    gains = losses = 0
    for c in set(a) & set(b):
        if c in exclude:
            continue
        ma, mb = majority(*a[c]), majority(*b[c])
        if ma is False and mb is True:
            gains += 1
        elif ma is True and mb is False:
            losses += 1
    return {"gains": gains, "losses": losses, "p": mcnemar_exact(gains, losses)}


def render_redundancy(r: dict | None) -> str:
    if r is None:
        return "C15 redundancy: needs at least two agent versions (runs that differ in the agent itself)"
    f = r["discriminating_fraction"]
    p = r["proposal"]
    lines = [f"C15 redundancy over {len(r['candidates'])} versions: {', '.join(r['candidates'])}",
             f"  always-pass {r['always_pass']}, always-fail {r['always_fail']}, discriminating "
             f"{r['discriminating']} (unclassified {r['unclassified']})",
             f"  discriminating fraction {'-' if f is None else f'{100 * f:.0f}%'} "
             f"(threshold {100 * r['threshold']:.0f}%){' — BELOW THRESHOLD' if r['below_threshold'] else ''}",
             f"  prune proposal: {p['suite_size']['before']} -> {p['suite_size']['after']} cases; "
             f"prune {p['prune'] or '-'}",
             f"    keep discriminating {p['keep_discriminating'] or '-'}; regression guards "
             f"{p['keep_regression_guards'] or '-'}; quality-estimate (never pruned) "
             f"{p['keep_quality_estimate'] or '-'}",
             f"    review (always-fail) {p['review_always_fail'] or '-'}",
             f"    detectable effect preserved: {p['detectable_effect']['preserved']} "
             f"({len(p['detectable_effect']['pairwise_tests'])} pairwise tests re-run on the pruned suite)"]
    if p["share_of_run_cost_saved"] is not None:
        lines.append(f"    run cost saved: {100 * p['share_of_run_cost_saved']:.0f}%")
    for c in p["check_prune_candidates"]:
        lines.append(f"    check {c['check']}: {c['why']}")
    lines.append(f"  apply: {p['how_to_apply']}")
    return "\n".join(lines)


def render_coverage(cov: dict) -> str:
    lines = [f"C14 coverage against {cov['source']} ({cov['list']}): {cov['empty_cells']} empty of "
             f"{len(cov['cells'])} cells"]
    if cov["list"] == "MISSING":
        lines.append("  refused (G5): the coverage list has no external source, or was committed after the cases")
        return "\n".join(lines)
    entries = sorted({c["taxonomy_entry"] for c in cov["cells"]})
    fms = sorted({c["failure_mode"] for c in cov["cells"]})
    n = {(c["taxonomy_entry"], c["failure_mode"]): c["n"] for c in cov["cells"]}
    na = {(c["taxonomy_entry"], c["failure_mode"]) for c in cov["cells"] if "not_applicable" in c}
    width = max([len(e) for e in entries] + [14])
    lines.append("  " + " " * width + "  " + "  ".join(f"{m[:14]:>14}" for m in fms))
    for e in entries:
        lines.append(f"  {e:<{width}}  " + "  ".join(f"{(n[(e, m)] or ('n/a' if (e, m) in na else '·')):>14}"
                                                     for m in fms))
    if cov.get("authoring_queue"):
        lines.append("  authoring queue (E8), most valuable first:")
        for q in cov["authoring_queue"][:10]:
            lines.append(f"    {q['taxonomy_entry']} × {q['failure_mode']}  (categories {q['categories']})")
    return "\n".join(lines)
