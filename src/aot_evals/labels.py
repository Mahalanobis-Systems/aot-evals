"""C9 `label`: human labels per judge, stratified across categories.

Labels live in `evals/checks/judge/<check-id>.labels.jsonl`, committed. Each line carries the
exact input the judge sees (`input`), so calibration can be re-run, on any backend, without the
raw run data, which stays git-ignored. A label is binary and from the human's point of view:
`label: true` means the item passes on this failure mode.

Workflow (Hamel Husain's spreadsheet of labels):
  1. `label queue`  writes `<check-id>.queue.csv` (git-ignored): a stratified sample of items
     from runs, one row per item, with an empty `label` column.
  2. A person fills in `label` (pass/fail) in a spreadsheet, or one at a time in conversation
     with `label add`.
  3. `label import` moves labelled rows into the labels file, after a secret scan.

Each label is assigned to the `dev` or `holdout` split by a hash of its item id (20% holdout):
prompts are iterated against dev errors only, and the holdout slice is checked at the end (E3).
"""

from __future__ import annotations

import csv
import difflib
import hashlib
import json
import random
from collections import defaultdict
from pathlib import Path

from . import stats
from .judges import JudgeSpec, build_input, item_id
from .repo import ALL_CATEGORIES, Evals
from .scrub import scan
from .util import append_jsonl, load_json, now_iso, read_jsonl

QUEUE_FIELDS = ["item_id", "case_id", "category", "run", "trial", "label", "labeller", "note", "input"]
PASS_WORDS = {"pass", "p", "true", "t", "yes", "y", "1", "ok"}
FAIL_WORDS = {"fail", "f", "false", "no", "n", "0"}
HOLDOUT_SHARE = 5  # one in five


def labels_path(ev: Evals, spec: JudgeSpec) -> Path:
    return ev.p("checks", "judge", f"{spec.id}.labels.jsonl")


def queue_path(ev: Evals, spec: JudgeSpec) -> Path:
    return ev.p("checks", "judge", f"{spec.id}.queue.csv")


def split_for(iid: str) -> str:
    return "holdout" if int(hashlib.sha256(iid.encode()).hexdigest(), 16) % HOLDOUT_SHARE == 0 else "dev"


def load_labels(ev: Evals, spec: JudgeSpec) -> list[dict]:
    """The latest label per item (a re-label by anyone replaces the earlier one)."""
    latest: dict[str, dict] = {}
    for rec in read_jsonl(labels_path(ev, spec)):
        latest[rec["item_id"]] = rec
    return list(latest.values())


def labels_sha(ev: Evals, spec: JudgeSpec) -> str | None:
    p = labels_path(ev, spec)
    return hashlib.sha256(p.read_bytes()).hexdigest()[:16] if p.exists() else None


def judge_categories(ev: Evals, spec: JudgeSpec) -> list[str]:
    fm = next((f for f in ev.failure_modes() if f.get("id") == spec.failure_mode), None)
    if fm is None:
        return []
    cats = fm.get("categories") or []
    return ev.category_ids() if ALL_CATEGORIES in cats else list(cats)


def applies_to(ev: Evals, spec: JudgeSpec, case: dict) -> bool:
    return any(fm.get("id") == spec.failure_mode for fm in ev.failure_modes_for_case(case))


# ---- queue -------------------------------------------------------------------------------------

def run_items(ev: Evals, spec: JudgeSpec, run_ids: list[str]) -> list[dict]:
    """Judge inputs for every final, ok attempt in the runs that this judge applies to."""
    cases = {c["id"]: c for c in ev.cases() if c.get("id")}
    out = []
    for rid in run_ids:
        for a in ev.run_records(rid):
            if a.get("kind") != "attempt" or not a.get("final") or a.get("outcome") != "ok":
                continue
            case = cases.get(a["case_id"])
            if not case or not applies_to(ev, spec, case):
                continue
            raw = load_json(ev.p("runs", rid, "raw", f"{a['case_id']}.t{a['trial']}.a{a['attempt']}.json"))
            if raw is None:
                continue
            start = {"world": raw.get("start_world"), "output": None}
            end = {"world": raw.get("end_world"), "output": raw.get("output")}
            ji = build_input(spec, case, start, end)
            out.append({"item_id": item_id(spec, case["id"], ji), "case_id": case["id"],
                        "category": case.get("category"), "run": rid, "trial": a["trial"],
                        "attempt": a["attempt"], "input": ji})
    return out


NEAR_IDENTICAL = 0.9  # answers at least this similar (difflib ratio) are one item to a labeller


def _answer(it: dict) -> str:
    """What changes between trials of a case: the agent's side of the judge input."""
    inp = it["input"]
    end = {k: v for k, v in inp.items() if k.startswith("end")} or inp
    return " ".join(json.dumps(end, sort_keys=True, ensure_ascii=False).lower().split())


def _distinct(it: dict, picked: list[dict]) -> bool:
    a = _answer(it)
    return all(difflib.SequenceMatcher(None, a, _answer(p)).ratio() < NEAR_IDENTICAL for p in picked)


def make_queue(ev: Evals, spec: JudgeSpec, run_ids: list[str], n: int, seed: int = 0) -> tuple[Path, list[dict]]:
    """Sample by case, not by attempt: one item per case first (cases with no label yet first),
    stratified across categories; then further trials only where a case's answers differ. With
    k = 3, sampling attempts fills the queue with near-identical repeats of one case."""
    labels = load_labels(ev, spec)
    labelled = {r["item_id"] for r in labels}
    by_case: dict[str, list[dict]] = defaultdict(list)
    seen = set()
    for it in run_items(ev, spec, run_ids):
        if it["item_id"] in labelled or it["item_id"] in seen:
            continue  # identical judge inputs are one item
        seen.add(it["item_id"])
        by_case[it["case_id"]].append(it)
    rng = random.Random(seed)
    for v in by_case.values():
        rng.shuffle(v)
    done = defaultdict(list)  # case -> items already labelled or picked
    for r in labels:
        if r.get("case_id") and r.get("input") is not None:
            done[r["case_id"]].append({"input": r["input"]})
    picked: list[dict] = []

    def round_robin(eligible) -> None:
        by_cat: dict[str, list[str]] = defaultdict(list)
        for cid in sorted(by_case, key=lambda c: (bool(done[c]), rng.random())):
            by_cat[by_case[cid][0]["category"] if by_case[cid] else ""].append(cid)
        while len(picked) < n and any(by_cat.values()):
            for cat in sorted(by_cat):
                while by_cat[cat] and len(picked) < n:
                    cid = by_cat[cat].pop(0)
                    it = eligible(cid)
                    if it is not None:
                        picked.append(it)
                        done[cid].append(it)
                        by_case[cid].remove(it)
                        break

    # 1. one item per case not yet labelled
    round_robin(lambda cid: by_case[cid][0] if by_case[cid] and not done[cid] else None)
    # 2. then other trials whose answers differ from everything labelled or picked for that case
    while len(picked) < n:
        before = len(picked)
        round_robin(lambda cid: next((it for it in by_case[cid] if _distinct(it, done[cid])), None))
        if len(picked) == before:
            break
    path = queue_path(ev, spec)
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=QUEUE_FIELDS)
        w.writeheader()
        for it in picked:
            w.writerow({**{k: it.get(k, "") for k in QUEUE_FIELDS if k != "input"},
                        "input": json.dumps(it["input"], ensure_ascii=False)})
    return path, picked


# ---- import / add ------------------------------------------------------------------------------

def parse_label(value: str) -> bool | None:
    v = (value or "").strip().lower()
    if v in PASS_WORDS:
        return True
    if v in FAIL_WORDS:
        return False
    return None


def _record(spec: JudgeSpec, row: dict, label: bool, labeller: str) -> dict:
    ji = row["input"] if isinstance(row["input"], dict) else json.loads(row["input"])
    iid = row.get("item_id") or item_id(spec, row["case_id"], ji)
    return {"item_id": iid, "case_id": row["case_id"], "category": row.get("category") or None,
            "label": label, "labeller": labeller, "date": now_iso()[:10],
            "note": row.get("note") or None, "split": split_for(iid),
            "source": {"run": row.get("run") or None, "trial": _int(row.get("trial"))},
            "judge_version": spec.version, "input": ji}


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def import_rows(ev: Evals, spec: JudgeSpec, rows: list[dict], default_labeller: str | None) -> dict:
    added, skipped, refused = 0, [], []
    for i, row in enumerate(rows, 2):
        label = parse_label(row.get("label", ""))
        if label is None:
            if (row.get("label") or "").strip():
                skipped.append(f"row {i}: label {row['label']!r} is not pass/fail")
            continue
        labeller = (row.get("labeller") or "").strip() or default_labeller
        if not labeller:
            skipped.append(f"row {i}: no labeller (fill the column or pass --by)")
            continue
        rec = _record(spec, row, label, labeller)
        secrets = [f for f in scan(json.dumps(rec["input"])) if f.kind == "secret"]
        if secrets:
            refused.append(f"row {i} ({rec['item_id']}): possible {secrets[0].pattern}; scrub it first")
            continue
        append_jsonl(labels_path(ev, spec), rec)
        added += 1
    return {"added": added, "skipped": skipped, "refused": refused}


def import_csv(ev: Evals, spec: JudgeSpec, path: Path, labeller: str | None) -> dict:
    with path.open(newline="") as f:
        rows = list(csv.DictReader(f))
    return import_rows(ev, spec, rows, labeller)


def add(ev: Evals, spec: JudgeSpec, iid: str, label: str, labeller: str, note: str | None) -> dict:
    q = queue_path(ev, spec)
    if not q.exists():
        raise FileNotFoundError(f"{q}: no queue; run `aot-evals label queue --judge {spec.id}` first")
    with q.open(newline="") as f:
        row = next((r for r in csv.DictReader(f) if r["item_id"] == iid), None)
    if row is None:
        raise KeyError(f"item {iid} is not in {q.name}")
    row["label"], row["note"] = label, note or ""
    return import_rows(ev, spec, [row], labeller)


# ---- status (M10) ------------------------------------------------------------------------------

def status(ev: Evals, spec: JudgeSpec) -> dict:
    labels = load_labels(ev, spec)
    n_pass = sum(1 for r in labels if r["label"])
    n_fail = len(labels) - n_pass
    by_cat: dict[str, dict] = {c: {"pass": 0, "fail": 0} for c in judge_categories(ev, spec)}
    for r in labels:
        d = by_cat.setdefault(r.get("category") or "(none)", {"pass": 0, "fail": 0})
        d["pass" if r["label"] else "fail"] += 1

    def halfwidth(k):
        ci = stats.wilson(round(k * 0.8), k) if k else None  # at a rate of 0.8, a typical good judge
        return (ci[1] - ci[0]) / 2 if ci else None

    return {
        "judge": spec.id, "labels": len(labels), "pass": n_pass, "fail": n_fail,
        "holdout": sum(1 for r in labels if r.get("split") == "holdout"),
        "labellers": sorted({r["labeller"] for r in labels}),
        "by_category": by_cat,
        "missing_categories": sorted(c for c, d in by_cat.items() if d["pass"] + d["fail"] == 0),
        "tpr_ci_halfwidth": halfwidth(n_pass), "tnr_ci_halfwidth": halfwidth(n_fail),
        "status": ("usable" if len(labels) >= 100 else "minimum" if len(labels) >= 60 else "uncalibrated"),
    }


def render_status(s: dict) -> str:
    def pct(v):
        return "n/a" if v is None else f"±{100 * v:.0f} pts"
    lines = [f"{s['judge']}: {s['labels']} labels ({s['pass']} pass / {s['fail']} fail; "
             f"{s['holdout']} holdout) — {s['status']} (M10: <60 uncalibrated, 100–200 usable)",
             f"  TPR interval at this n: {pct(s['tpr_ci_halfwidth'])}; TNR: {pct(s['tnr_ci_halfwidth'])}",
             f"  labellers: {', '.join(s['labellers']) or '-'}"]
    for c, d in sorted(s["by_category"].items()):
        lines.append(f"  {c:<28} pass {d['pass']:>4}  fail {d['fail']:>4}")
    if s["missing_categories"]:
        lines.append(f"  no labels yet for: {', '.join(s['missing_categories'])}")
    return "\n".join(lines)
