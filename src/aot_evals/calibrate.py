"""C10 `calibrate` (E3) and E5 backend comparison: is each judge right, measured on human labels?

For every backend of a judge, on the same labels:
- TPR = P(judge passes | human says pass) and TNR = P(judge fails | human says fail), separately,
  with Wilson intervals. Raw agreement is never reported: an always-pass judge agrees 95% of the
  time at a 95% base rate (M8).
- Cohen's kappa, the confusion matrix, cost and latency per judgement, errors.
- For a backend that returns a probability (System One), the decision threshold is chosen on the
  labels, maximising TPR + TNR. The reported TPR/TNR use out-of-fold predictions (5-fold,
  stratified), so the threshold is never scored on the labels it was fitted to. ECE and Brier
  score measure whether its probabilities mean anything; it is not trusted until they do.
- The holdout split is reported separately.

A judge is `calibrated` when its primary backend has >= 60 labels with both classes present and
TPR and TNR at or above the judge's floors (`min_tpr`, `min_tnr`, default 0.75). Otherwise it
may run but is greyed and excluded from headline numbers (G3).

Judgements are cached in `<check-id>.judgements.jsonl` (committed) by (backend, model, the
judge's hash with only that backend's config, item), so re-measuring after a label change, or
adding a backend, does not pay for calls already made. A rate-limit error stops that backend's
calls; errors are reported grouped by message.
"""

from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from pathlib import Path

from . import stats
from .judges import Judgement, JudgeSpec, is_rate_limit, judge
from .labels import labels_sha, load_labels
from .repo import Evals
from .util import append_jsonl, load_json, now_iso, read_jsonl, write_json

MIN_LABELS = 60
FOLDS = 5


def judgements_path(ev: Evals, spec: JudgeSpec) -> Path:
    return ev.p("checks", "judge", f"{spec.id}.judgements.jsonl")


def calibration_path(ev: Evals, spec: JudgeSpec) -> Path:
    return ev.p("checks", "judge", f"{spec.id}.calibration.json")


def load_calibration(ev: Evals, spec: JudgeSpec) -> dict | None:
    return load_json(calibration_path(ev, spec))


def _cache_key(spec: JudgeSpec, backend: str, iid: str, run: int = 0) -> str:
    model = spec.backends[backend].get("model")
    return f"{backend}|{model}|{spec.backend_sha(backend)}|{iid}|{run}"


def cached(ev: Evals, spec: JudgeSpec) -> dict[str, dict]:
    return {r["key"]: r for r in read_jsonl(judgements_path(ev, spec)) if r.get("score") is not None}


def group_errors(judged: dict[str, dict]) -> list[tuple[str, int]]:
    """Errors by message, most frequent first."""
    counts = Counter((j.get("error") or "no verdict")[:160] for j in judged.values() if j.get("score") is None)
    return counts.most_common()


def get_judgements(ev: Evals, spec: JudgeSpec, backend: str, labels: list[dict], *, run: int = 0,
                   call: bool = True, log=print) -> dict[str, dict]:
    """item_id -> judgement dict for one backend; calls the backend only for uncached items."""
    cache = cached(ev, spec)
    out = {}
    todo = []
    for r in labels:
        key = _cache_key(spec, backend, r["item_id"], run)
        if key in cache:
            out[r["item_id"]] = cache[key]
        else:
            todo.append((key, r))
    if todo and not call:
        return out
    stopped = None
    for i, (key, r) in enumerate(todo, 1):
        if stopped:
            out[r["item_id"]] = {"item_id": r["item_id"], "backend": backend, "score": None,
                                 "error": f"not called: {backend} stopped after a rate limit"}
            continue
        j: Judgement = judge(spec, backend, r["input"])
        rec = {"key": key, "item_id": r["item_id"], "backend": backend, "run": run,
               "judge_sha": spec.sha(), "date": now_iso(), **j.as_dict()}
        if j.score is not None:
            append_jsonl(judgements_path(ev, spec), rec)
        out[r["item_id"]] = rec
        if is_rate_limit(j.error):
            stopped = j.error
            log(f"  {backend}: stopped after {i} call(s), rate limited: {j.error[:200]}")
        elif i % 20 == 0 or i == len(todo):
            log(f"  {backend}: {i}/{len(todo)} judged")
    called = {r["item_id"] for _, r in todo}
    for msg, n in group_errors({k: v for k, v in out.items() if k in called})[:5]:
        log(f"  {backend}: {n} without a verdict: {msg}")
    return out


def cap_warnings(spec: JudgeSpec, pending: dict[str, int]) -> list[str]:
    """A backend's `daily_limit` (calls per day, e.g. a free tier) against the calls about to be
    made. The free Jev tier refuses after about 250 calls a day, less than one calibration round."""
    out = []
    for b, n in pending.items():
        cap = spec.backends.get(b, {}).get("daily_limit")
        if cap and n >= 0.8 * int(cap):
            out.append(f"warning: {b} needs {n} call(s) and allows about {cap} a day; calibrate it "
                       "on fewer labels, over several days, or on a paid tier")
    return out


def pending_calls(ev: Evals, spec: JudgeSpec, backends: list[str]) -> dict[str, int]:
    labels = load_labels(ev, spec)
    cache = cached(ev, spec)
    return {b: sum(1 for r in labels if _cache_key(spec, b, r["item_id"]) not in cache) for b in backends}


# ---- metrics ---------------------------------------------------------------------------------

def confusion(pairs: list[tuple[bool, bool]]) -> dict:
    """pairs of (human_pass, judge_pass); positive class = pass."""
    tp = sum(1 for h, j in pairs if h and j)
    fn = sum(1 for h, j in pairs if h and not j)
    fp = sum(1 for h, j in pairs if not h and j)
    tn = sum(1 for h, j in pairs if not h and not j)
    return {"tp": tp, "fn": fn, "fp": fp, "tn": tn}


def rates(cm: dict) -> dict:
    pos, neg = cm["tp"] + cm["fn"], cm["tn"] + cm["fp"]
    n = pos + neg
    tpr = cm["tp"] / pos if pos else None
    tnr = cm["tn"] / neg if neg else None
    kappa = None
    if n:
        po = (cm["tp"] + cm["tn"]) / n
        pe = ((cm["tp"] + cm["fp"]) * pos + (cm["fn"] + cm["tn"]) * neg) / (n * n)
        kappa = (po - pe) / (1 - pe) if pe < 1 else None
    return {"tpr": tpr, "tpr_ci": _ci(cm["tp"], pos), "tnr": tnr, "tnr_ci": _ci(cm["tn"], neg),
            "kappa": kappa, "n": n, "n_pass": pos, "n_fail": neg}


def _ci(k, n):
    ci = stats.wilson(k, n)
    return list(ci) if ci else None


def best_threshold(scored: list[tuple[float, bool]]) -> float:
    """Threshold maximising TPR + TNR (Youden's J); ties go to the one nearest 0.5."""
    cands = sorted({s for s, _ in scored} | {0.5})
    best, best_key = 0.5, None
    pos = sum(1 for _, h in scored if h)
    neg = len(scored) - pos
    for t in cands:
        tp = sum(1 for s, h in scored if h and s >= t)
        tn = sum(1 for s, h in scored if not h and s < t)
        j = (tp / pos if pos else 0) + (tn / neg if neg else 0)
        key = (round(j, 12), -abs(t - 0.5))
        if best_key is None or key > best_key:
            best, best_key = t, key
    return best


def _folds(items: list[dict], k: int) -> list[list[dict]]:
    """Stratified, deterministic folds by item-id hash."""
    folds = [[] for _ in range(k)]
    for label in (True, False):
        group = sorted((r for r in items if r["label"] is label),
                       key=lambda r: hashlib.sha256(r["item_id"].encode()).hexdigest())
        for i, r in enumerate(group):
            folds[i % k].append(r)
    return folds


def calibration_error(scored: list[tuple[float, bool]], bins: int = 10) -> tuple[float | None, float | None]:
    """(ECE, Brier) of P(pass) against the human label."""
    if not scored:
        return None, None
    brier = sum((s - (1.0 if h else 0.0)) ** 2 for s, h in scored) / len(scored)
    buckets: dict[int, list] = defaultdict(list)
    for s, h in scored:
        buckets[min(int(s * bins), bins - 1)].append((s, h))
    ece = sum(len(b) / len(scored) * abs(sum(s for s, _ in b) / len(b) - sum(1 for _, h in b if h) / len(b))
              for b in buckets.values())
    return ece, brier


def measure_backend(spec: JudgeSpec, backend: str, labels: list[dict], judged: dict[str, dict]) -> dict:
    items = [r for r in labels if r["item_id"] in judged and judged[r["item_id"]].get("score") is not None]
    errors = len(labels) - len(items)
    scored = [(float(judged[r["item_id"]]["score"]), bool(r["label"])) for r in items]
    probabilistic = any(0.0 < s < 1.0 for s, _ in scored)
    dev = [r for r in items if r.get("split") != "holdout"]
    holdout = [r for r in items if r.get("split") == "holdout"]

    def score_of(r):
        return float(judged[r["item_id"]]["score"])

    if probabilistic and len(dev) >= FOLDS * 2:
        oof: dict[str, bool] = {}
        folds = _folds(dev, FOLDS)
        for i, fold in enumerate(folds):
            train = [r for j, f in enumerate(folds) if j != i for r in f]
            t = best_threshold([(score_of(r), r["label"]) for r in train])
            for r in fold:
                oof[r["item_id"]] = score_of(r) >= t
        threshold = best_threshold([(score_of(r), r["label"]) for r in dev])
        method = f"threshold chosen on dev labels; TPR/TNR from {FOLDS}-fold out-of-fold predictions"
    else:
        threshold = 0.5 if not probabilistic else best_threshold([(score_of(r), r["label"]) for r in dev])
        oof = {r["item_id"]: score_of(r) >= threshold for r in dev}
        method = "fixed verdicts (no threshold to fit)" if not probabilistic else "threshold fit on all dev labels"

    pred = {**oof, **{r["item_id"]: score_of(r) >= threshold for r in holdout}}
    cm_all = confusion([(r["label"], pred[r["item_id"]]) for r in items])
    cm_hold = confusion([(r["label"], pred[r["item_id"]]) for r in holdout])
    ece, brier = calibration_error(scored) if probabilistic else (None, None)
    costs = [judged[r["item_id"]].get("cost_usd") for r in items if judged[r["item_id"]].get("cost_usd") is not None]
    lats = [judged[r["item_id"]].get("latency_ms") for r in items if judged[r["item_id"]].get("latency_ms") is not None]
    cfg = spec.backends[backend]
    r_all = rates(cm_all)
    return {
        "backend": backend, "type": cfg.get("type"), "model": cfg.get("model"), "family": cfg.get("family"),
        "labels": len(items), "errors": errors, "probabilistic": probabilistic,
        "error_messages": [[msg, n] for msg, n in group_errors(
            {r["item_id"]: judged.get(r["item_id"], {"score": None, "error": "not judged"}) for r in labels})],
        "threshold": threshold if probabilistic else None, "method": method,
        **r_all, "confusion": cm_all,
        "holdout": {**rates(cm_hold), "confusion": cm_hold},
        "confidence_calibration": {"ece": ece, "brier": brier},
        "cost_per_judgement": sum(costs) / len(costs) if costs else None,
        "latency_ms_mean": sum(lats) / len(lats) if lats else None,
    }


def status_of(spec: JudgeSpec, m: dict | None) -> tuple[str, list[str]]:
    if m is None:
        return "uncalibrated", ["primary backend not measured"]
    why = []
    if m["labels"] < MIN_LABELS:
        why.append(f"{m['labels']} labels < {MIN_LABELS}")
    if not m["n_pass"] or not m["n_fail"]:
        why.append("labels need both passing and failing items")
    if m["tpr"] is not None and m["tpr"] < spec.min_tpr:
        why.append(f"TPR {m['tpr']:.2f} < {spec.min_tpr}")
    if m["tnr"] is not None and m["tnr"] < spec.min_tnr:
        why.append(f"TNR {m['tnr']:.2f} < {spec.min_tnr}")
    if m["errors"]:
        top = (m.get("error_messages") or [[None]])[0][0]
        why.append(f"{m['errors']} item(s) without a verdict" + (f" (most: {top})" if top else ""))
    return ("uncalibrated" if why else "calibrated"), why


def calibrate(ev: Evals, spec: JudgeSpec, backends: list[str] | None = None, *, call: bool = True,
              log=print) -> dict:
    labels = load_labels(ev, spec)
    if not labels:
        raise ValueError(f"judge {spec.id} has no labels (C9: aot-evals label queue/import)")
    backends = backends or list(spec.backends)
    prior = load_calibration(ev, spec) or {}
    # Keep earlier backend measurements only if neither the judge nor the labels changed since.
    results = dict(prior.get("backends") or {}) if is_current(ev, spec, prior) else {}
    for b in backends:
        judged = get_judgements(ev, spec, b, labels, call=call, log=log)
        results[b] = measure_backend(spec, b, labels, judged)
    primary = spec.primary
    st, why = status_of(spec, results.get(primary))
    record = {
        "judge": spec.id, "version": spec.version, "judge_sha": spec.sha(),
        "labels_sha": labels_sha(ev, spec), "labels": len(labels), "measured_at": now_iso(),
        "primary": primary, "status": st, "status_reasons": why,
        "min_tpr": spec.min_tpr, "min_tnr": spec.min_tnr, "backends": results,
        "recommendation": recommend(spec, results),
    }
    write_json(calibration_path(ev, spec), record)
    return record


def recommend(spec: JudgeSpec, results: dict) -> dict | None:
    """E5: the cheapest backend that clears both floors; ties to the higher TPR + TNR."""
    ok = [m for m in results.values() if m["tpr"] is not None and m["tnr"] is not None
          and m["tpr"] >= spec.min_tpr and m["tnr"] >= spec.min_tnr and m["labels"] >= MIN_LABELS]
    if not ok:
        return None
    best = min(ok, key=lambda m: (m["cost_per_judgement"] if m["cost_per_judgement"] is not None else float("inf"),
                                  -(m["tpr"] + m["tnr"])))
    return {"backend": best["backend"],
            "why": "cheapest backend that clears both floors" + (
                "" if best["cost_per_judgement"] is not None else " (cost unknown for some backends)")}


def is_current(ev: Evals, spec: JudgeSpec, cal: dict | None) -> bool:
    return bool(cal) and cal.get("judge_sha") == spec.sha() and cal.get("labels_sha") == labels_sha(ev, spec)


def render(record: dict) -> str:
    def f(v, pct=True):
        if v is None:
            return "-"
        return f"{100 * v:.1f}%" if pct else f"{v:.3f}"

    def ci(c):
        return f"[{100 * c[0]:.0f}, {100 * c[1]:.0f}]" if c else ""

    lines = [f"C10 calibrate {record['judge']} v{record['version']}: {record['labels']} labels — "
             f"primary {record['primary']}: {record['status'].upper()}"
             + (f" ({'; '.join(record['status_reasons'])})" if record["status_reasons"] else ""),
             f"  {'backend':<12} {'family':<12} {'TPR':>7} {'95% CI':>10} {'TNR':>7} {'95% CI':>10} "
             f"{'kappa':>6} {'thresh':>7} {'ECE':>6} {'$/judgement':>12} {'ms':>6} {'err':>4}"]
    for b, m in record["backends"].items():
        cost = "-" if m["cost_per_judgement"] is None else f"${m['cost_per_judgement']:.5f}"
        ms = "-" if m["latency_ms_mean"] is None else f"{m['latency_ms_mean']:.1f}"
        lines.append(f"  {b:<12} {str(m['family']):<12} {f(m['tpr']):>7} {ci(m['tpr_ci']):>10} "
                     f"{f(m['tnr']):>7} {ci(m['tnr_ci']):>10} {f(m['kappa'], False):>6} "
                     f"{f(m['threshold'], False):>7} {f(m['confidence_calibration']['ece'], False):>6} "
                     f"{cost:>12} {ms:>6} {m['errors']:>4}")
        c, h = m["confusion"], m["holdout"]
        lines.append(f"  {'':<12} all: tp {c['tp']} fn {c['fn']} fp {c['fp']} tn {c['tn']}; "
                     f"holdout (n={h['n']}): TPR {f(h['tpr'])} TNR {f(h['tnr'])}")
    rec = record.get("recommendation")
    lines.append(f"  E5: {'use ' + rec['backend'] + ' — ' + rec['why'] if rec else 'no backend clears both floors'}")
    lines.append("  (raw agreement is not reported: it hides an always-pass judge)")
    return "\n".join(lines)


def threshold_for(cal: dict | None, backend: str) -> float | None:
    if not cal:
        return None
    m = (cal.get("backends") or {}).get(backend)
    return m.get("threshold") if m else None


def judge_verdict(score: float | None, threshold: float | None) -> bool | None:
    if score is None:
        return None
    return score >= (0.5 if threshold is None else threshold)
