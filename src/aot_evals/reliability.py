"""C11 `reliability` (E4): do a judge's verdicts repeat, and do two model families agree?

Each labelled item is judged in m fresh sessions on each of two or more backends from different
model families. Reported (M9):
- self-consistency per backend: share of items whose m verdicts are identical;
- three-level agreement across every verdict for an item: all agree / a strict
  majority / no majority;
- cross-family agreement between the backends' majority verdicts, with Cohen's kappa;
- next to them, TPR/TNR of each backend's majority verdict on the same human-labelled items.

Reliability is not validity: two families can agree because they share an error. The report keeps
these numbers in their own column group, never in place of TPR/TNR.
"""

from __future__ import annotations

import hashlib
from itertools import combinations
from pathlib import Path

from .calibrate import confusion, get_judgements, load_calibration, rates, threshold_for
from .judges import JudgeSpec
from .labels import load_labels
from .repo import Evals
from .util import load_json, now_iso, write_json


def reliability_path(ev: Evals, spec: JudgeSpec) -> Path:
    return ev.p("checks", "judge", f"{spec.id}.reliability.json")


def load_reliability(ev: Evals, spec: JudgeSpec) -> dict | None:
    return load_json(reliability_path(ev, spec))


def stratified_subset(labels: list[dict], n: int | None) -> list[dict]:
    """Up to n labels, round-robin across (category, label) strata in a fixed order, so a
    subsample keeps both classes and every category (TPR and TNR need both)."""
    ordered = sorted(labels, key=lambda r: hashlib.sha256(r["item_id"].encode()).hexdigest())
    if not n or n >= len(ordered):
        return ordered
    strata: dict[tuple, list[dict]] = {}
    for r in ordered:
        strata.setdefault((r.get("category") or "", bool(r["label"])), []).append(r)
    out: list[dict] = []
    while len(out) < n:
        for key in sorted(strata):
            if strata[key] and len(out) < n:
                out.append(strata[key].pop(0))
    return out


def measure(ev: Evals, spec: JudgeSpec, backends: list[str], m: int = 3, n: int | None = None,
            log=print) -> dict:
    if len(backends) < 2:
        raise ValueError("reliability needs at least two backends")
    families = {spec.backends[b].get("family") for b in backends}
    if len(families) < 2:
        raise ValueError(f"backends {backends} are all one model family ({families}); C11 needs two")
    labels = stratified_subset(load_labels(ev, spec), n)
    if not labels:
        raise ValueError(f"judge {spec.id} has no labels")
    cal = load_calibration(ev, spec)

    verdicts: dict[str, dict[str, list[bool]]] = {b: {} for b in backends}
    for b in backends:
        t = threshold_for(cal, b)
        for run in range(m):
            judged = get_judgements(ev, spec, b, labels, run=run, log=log)
            for r in labels:
                j = judged.get(r["item_id"])
                if j and j.get("score") is not None:
                    verdicts[b].setdefault(r["item_id"], []).append(float(j["score"]) >= (0.5 if t is None else t))

    per_backend = {}
    majority: dict[str, dict[str, bool]] = {}
    for b in backends:
        complete = {i: v for i, v in verdicts[b].items() if len(v) == m}
        consistent = sum(1 for v in complete.values() if len(set(v)) == 1)
        majority[b] = {i: sum(v) * 2 > len(v) for i, v in complete.items() if sum(v) * 2 != len(v)}
        cm = confusion([(r["label"], majority[b][r["item_id"]]) for r in labels if r["item_id"] in majority[b]])
        per_backend[b] = {"family": spec.backends[b].get("family"), "model": spec.backends[b].get("model"),
                          "items": len(complete),
                          "self_consistency": consistent / len(complete) if complete else None,
                          "majority_vs_labels": {**rates(cm), "confusion": cm}}

    levels = {"all": 0, "majority": 0, "none": 0}
    for r in labels:
        allv = [x for b in backends for x in verdicts[b].get(r["item_id"], [])]
        if not allv:
            continue
        k = sum(allv)
        if k in (0, len(allv)):
            levels["all"] += 1
        elif k * 2 == len(allv):
            levels["none"] += 1
        else:
            levels["majority"] += 1
    total = sum(levels.values())

    pairs = []
    for a, b in combinations(backends, 2):
        if spec.backends[a].get("family") == spec.backends[b].get("family"):
            continue
        shared = sorted(set(majority[a]) & set(majority[b]))
        cm = confusion([(majority[a][i], majority[b][i]) for i in shared])  # a as reference
        r = rates(cm)
        agree = (cm["tp"] + cm["tn"]) / len(shared) if shared else None
        pairs.append({"backends": [a, b], "items": len(shared), "agreement": agree, "kappa": r["kappa"]})

    record = {"judge": spec.id, "version": spec.version, "judge_sha": spec.sha(), "measured_at": now_iso(),
              "m": m, "items": len(labels), "backends": per_backend,
              "three_level": {k: (v / total if total else None) for k, v in levels.items()},
              "three_level_counts": levels, "cross_family": pairs,
              "note": "reliability, not validity: agreement between judges can be a shared error"}
    write_json(reliability_path(ev, spec), record)
    return record


def render(rec: dict) -> str:
    def f(v):
        return "-" if v is None else f"{100 * v:.1f}%"
    lines = [f"C11 reliability {rec['judge']} v{rec['version']}: {rec['items']} labelled items × m={rec['m']}",
             f"  {'backend':<12} {'family':<12} {'self-consistency':>16}   | validity (majority vs labels): "
             f"{'TPR':>7} {'TNR':>7}"]
    for b, d in rec["backends"].items():
        mv = d["majority_vs_labels"]
        lines.append(f"  {b:<12} {str(d['family']):<12} {f(d['self_consistency']):>16}   | {'':<30} "
                     f"{f(mv['tpr']):>7} {f(mv['tnr']):>7}")
    tl = rec["three_level"]
    lines.append(f"  three-level agreement: all {f(tl['all'])}, majority {f(tl['majority'])}, none {f(tl['none'])}")
    for p in rec["cross_family"]:
        k = "-" if p["kappa"] is None else f"{p['kappa']:.2f}"
        lines.append(f"  cross-family {p['backends'][0]} vs {p['backends'][1]}: agreement {f(p['agreement'])}, "
                     f"kappa {k} (n={p['items']})")
    lines.append(f"  {rec['note']}")
    return "\n".join(lines)
