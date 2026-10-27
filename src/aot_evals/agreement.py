"""C19 `agreement`: does the suite's verdict on a whole run agree with a person's?

Every other screen looks at a part: C7 at one case's states, C10 at one judge on its one
question. None of them asks whether the suite, all checks together, fails the runs a person
would fail and passes the runs a person would pass. A suite can clear every part and still miss
what matters: a requirement no check looks at (a list presented as complete when it isn't, a
task left unlinked, junk left behind), an expected answer that only matches one wording, a code
check with a bug. This measures the whole.

1. `agreement label queue --run R`: a sample of final attempts, one per case first, written to a
   local page (git-ignored: it carries agent output). A person judges each whole run from
   scratch, pass or fail with a note, seeing the request, the agent's answer and what changed,
   never the checks or the expected state. `labels/standard.md`, if present, is shown as the
   labelling guidance.
2. `agreement label import --csv F`: labels go to `labels/runs.jsonl` (committed; label and
   note only, no agent output). Each run is assigned to dev or holdout by a hash of its id.
3. `agreement`: re-grades every labelled run with the suite as it is now, from the run's raw
   record (`runs/<id>/raw/`), so labels outlive suite versions: fix a check, measure again,
   without re-running the agent. The verdict is the report's: code checks always count, a judge
   only once calibrated. A check that raises, or a counted judge with no verdict, leaves the run
   with no verdict, which counts as wrong either way.
4. Every dev disagreement gets a cause in `labels/triage.yaml`, so each one turns into a fix:
   a missing requirement (C6/C8), a wrong expectation (C6), a check bug (C8), a judge error
   (C10), out of scope, or accepted with a reason.

Writes `report/agreement.json`. Gate C19: enough labels of both kinds, a measurement that is
current for this suite and these labels, dev catch rate and clean pass rate at or above their
floors, and every dev disagreement triaged. Holdout is reported, never iterated on.
"""

from __future__ import annotations

import csv
import hashlib
import json
import random
from collections import defaultdict
from pathlib import Path

from . import stats
from .checks import run_check
from .labels import parse_label, split_for
from .repo import Evals
from .scrub import scan
from .util import append_jsonl, load_json, load_yaml, now_iso, read_jsonl, write_json

MIN_RUNS = 60
MIN_EACH = 15  # labelled runs of each kind: below this, one rate's interval is too wide to act on
MIN_CATCH = 0.85
MIN_CLEAN = 0.85
CAUSES = {
    "missing-requirement": "no check looks at what the person failed it for (C6 requirements, C8 check)",
    "wrong-expectation": "the case's expected answer or state is wrong or too narrow (C6)",
    "check-bug": "a check exists but decides wrongly (C8)",
    "judge-error": "a judge decided wrongly (C10: iterate the judge on its dev errors)",
    "out-of-scope": "the suite deliberately doesn't test this; say why",
    "accepted": "known and left as is; say why",
}
LABEL_FIELDS = ["item_id", "case_id", "category", "run", "trial", "attempt", "label", "labeller", "note", "input"]


def labels_path(ev: Evals) -> Path:
    return ev.p("labels", "runs.jsonl")


def triage_path(ev: Evals) -> Path:
    return ev.p("labels", "triage.yaml")


def result_path(ev: Evals) -> Path:
    return ev.p("report", "agreement.json")


def floors(ev: Evals) -> dict:
    """`labels/floors.yaml` may set min_catch, min_clean, min_runs, min_each."""
    f = load_yaml(ev.p("labels", "floors.yaml")) or {}
    return {"min_catch": float(f.get("min_catch", MIN_CATCH)), "min_clean": float(f.get("min_clean", MIN_CLEAN)),
            "min_runs": int(f.get("min_runs", MIN_RUNS)), "min_each": int(f.get("min_each", MIN_EACH))}


def item_key(run_id: str, case_id: str, trial: int, attempt: int) -> str:
    return f"{run_id}/{case_id}.t{trial}.a{attempt}"


def load_labels(ev: Evals) -> list[dict]:
    """The latest label per run (a re-label replaces the earlier one)."""
    latest: dict[str, dict] = {}
    for rec in read_jsonl(labels_path(ev)):
        latest[rec["item_id"]] = rec
    return list(latest.values())


def labels_sha(labels: list[dict]) -> str:
    body = sorted((r["item_id"], r["label"]) for r in labels)
    return hashlib.sha256(json.dumps(body).encode()).hexdigest()[:16]


def suite_sha(ev: Evals) -> str:
    """What the verdict depends on: cases, checks, judge specs and their calibrations."""
    h = hashlib.sha256()
    for sub, pattern in (("cases", "**/*.json"), ("checks/code", "*.py"), ("checks/judge", "*.md"),
                         ("checks/judge", "*.calibration.json"), (".", "failure_modes.yaml")):
        base = ev.p(*sub.split("/"))
        for p in sorted(base.glob(pattern)) if base.exists() else []:
            h.update(str(p.relative_to(ev.evals_dir)).encode())
            h.update(p.read_bytes())
    return h.hexdigest()[:16]


def _raw(ev: Evals, run_id: str, a: dict) -> dict | None:
    return load_json(ev.p("runs", run_id, "raw", f"{a['case_id']}.t{a['trial']}.a{a['attempt']}.json"))


def finals(ev: Evals, run_ids: list[str]) -> list[dict]:
    """Final, scorable attempts with a raw record and a known case."""
    cases = {c["id"] for c in ev.cases() if c.get("id")}
    out = []
    for rid in run_ids:
        for a in ev.run_records(rid):
            if (a.get("kind") == "attempt" and a.get("final") and a.get("outcome") == "ok"
                    and a.get("case_id") in cases and ev.p("runs", rid, "raw",
                                                           f"{a['case_id']}.t{a['trial']}.a{a['attempt']}.json").exists()):
                out.append(a)
    return out


# ---------- the person's side: whole-run labels ----------

def _public_request(case: dict) -> dict:
    """What the agent was asked, as the person needs it to judge: never the expected state."""
    out = {"request": case.get("trigger")}
    if case.get("inputs"):
        out["inputs"] = case["inputs"]
    if case.get("followups"):
        out["follow-ups"] = case["followups"]
    return out


def run_view(ev: Evals, run_id: str, a: dict, case: dict) -> dict:
    from .runner import state_diff

    raw = _raw(ev, run_id, a) or {}
    changed = state_diff(raw.get("start_world"), raw.get("end_world"), limit=200)
    return {**_public_request(case), "agent's answer": raw.get("output"),
            "what changed": "\n".join(changed) if changed else "no change"}


def make_queue(ev: Evals, run_ids: list[str], per_case: int = 1, n: int | None = None,
               seed: int = 0) -> tuple[Path, list[dict]]:
    """Runs not yet labelled, `per_case` per case (cases with fewest labels first), shuffled."""
    cases = {c["id"]: c for c in ev.cases() if c.get("id")}
    labelled = load_labels(ev)
    done = {r["item_id"] for r in labelled}
    count = defaultdict(int)
    for r in labelled:
        count[r.get("case_id")] += 1
    by_case: dict[str, list[dict]] = defaultdict(list)
    for a in finals(ev, run_ids):
        key = item_key(a["run_id"], a["case_id"], a["trial"], a["attempt"])
        if key not in done:
            by_case[a["case_id"]].append(a)
    rng = random.Random(seed)
    picked = []
    for cid in sorted(by_case, key=lambda c: (count[c], c)):
        pool = by_case[cid][:]
        rng.shuffle(pool)
        picked += pool[:per_case]
    rng.shuffle(picked)
    if n is not None:
        picked = picked[:n]
    items = [{"item_id": item_key(a["run_id"], a["case_id"], a["trial"], a["attempt"]),
              "case_id": a["case_id"], "category": cases[a["case_id"]].get("category") or "",
              "run": a["run_id"], "trial": a["trial"], "attempt": a["attempt"], "label": "", "labeller": "",
              "note": "", "input": run_view(ev, a["run_id"], a, cases[a["case_id"]])} for a in picked]
    path = ev.p("data", "agreement", "queue.json")
    write_json(path, {"made_at": now_iso(), "runs": run_ids, "seed": seed, "items": items})
    return path, items


def write_page(ev: Evals) -> Path:
    from .brand import page
    from .label_page import SCRIPT
    from .markdown import render as md

    q = load_json(ev.p("data", "agreement", "queue.json"))
    if not q:
        raise FileNotFoundError("no queue; run `aot-evals agreement label queue --run RUN` first")
    items = q["items"]
    queue_sha = hashlib.sha256(json.dumps([i["item_id"] for i in items]).encode()).hexdigest()[:12]
    std = ev.p("labels", "standard.md")
    guidance = md(std.read_text()) if std.exists() else (
        "<p>A run passes only if a competent assistant with the same tools would be satisfied with the "
        "result: every stated fact true, every write right and complete, nothing left behind, and a "
        "question asked only when it resolves the real ambiguity. Write down the rules you apply in "
        "<code>labels/standard.md</code> so the next labeller applies the same ones.</p>")
    data = {"judge": "whole-runs", "version": "", "queue_sha": queue_sha, "fields": LABEL_FIELDS, "items": items}
    body = f"""
<style>
.lp-bar {{ display: flex; flex-wrap: wrap; align-items: center; gap: 10px 16px; margin: 12px 0; }}
.lp-bar input {{ font: inherit; padding: 4px 6px; }}
.lp-progress {{ flex: 1; min-width: 160px; height: 8px; background: var(--rule); }}
.lp-progress span {{ display: block; height: 8px; background: var(--forest); width: 0; }}
.lp-meta {{ color: var(--grey-muted); font-size: 13px; margin: 6px 0 10px; }}
.lp-fields {{ display: grid; grid-template-columns: 1fr; gap: 16px; }}
.lp-field h3 {{ font-size: 13px; margin: 0 0 4px; color: var(--forest); }}
.lp-field pre {{ white-space: pre-wrap; word-break: break-word; margin: 0; max-height: 70vh; overflow: auto; }}
.lp-actions {{ display: flex; flex-wrap: wrap; gap: 10px; align-items: center; margin: 16px 0; }}
.lp-actions button {{ font: inherit; padding: 8px 16px; border: 2px solid var(--forest); background: transparent;
  color: var(--forest); cursor: pointer; }}
.lp-actions button.on {{ background: var(--forest); color: #fff; }}
.lp-actions textarea {{ font: inherit; flex: 1; min-width: 240px; min-height: 2.4em; }}
.lp-keys {{ font-size: 12px; color: var(--grey-muted); }}
</style>
<section class="panel">
  <h2>Did the agent do what was asked, correctly?</h2>
  {guidance}
  <p class="muted">Judge each run from scratch. No check's verdict and no expected answer is shown. For a
  fail, say what went wrong: the note is what turns a disagreement into a fix.</p>
</section>
<section class="panel">
  <div class="lp-bar">
    <label>Labeller <input id="labeller" placeholder="your name"></label>
    <span id="count"></span>
    <div class="lp-progress"><span id="progress"></span></div>
    <button id="download" type="button">Download CSV</button>
  </div>
  <div class="lp-meta" id="meta"></div>
  <div class="lp-fields" id="fields"></div>
  <div class="lp-actions">
    <button id="prev" type="button">&larr; Previous</button>
    <button id="pass" type="button">Pass (p)</button>
    <button id="fail" type="button">Fail (f)</button>
    <button id="next" type="button">Next &rarr;</button>
    <textarea id="note" placeholder="Note (n): what went wrong, or what is unclear"></textarea>
  </div>
  <p class="lp-keys">Labels are saved in this browser as you go. When done, Download CSV and run
  <code>aot-evals agreement label import --csv &lt;the downloaded file&gt;</code>.</p>
</section>
"""
    path = ev.p("data", "agreement", "label.html")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(page("Label whole runs", "AOT evals agreement", f"{len(items)} runs", body,
                         data=data, script=SCRIPT))
    return path


def _record(row: dict, label: bool, labeller: str) -> dict:
    return {"item_id": row["item_id"], "run": row.get("run"), "case_id": row.get("case_id"),
            "trial": int(row["trial"]) if str(row.get("trial", "")).strip() else None,
            "attempt": int(row["attempt"]) if str(row.get("attempt", "")).strip() else None,
            "label": label, "labeller": labeller, "note": (row.get("note") or "").strip(),
            "split": split_for(row["item_id"]), "at": now_iso()}


def import_rows(ev: Evals, rows: list[dict], default_labeller: str | None) -> dict:
    added = skipped = 0
    problems = []
    labels_path(ev).parent.mkdir(parents=True, exist_ok=True)
    for row in rows:
        label = parse_label(row.get("label") or "")
        if label is None:
            skipped += 1
            continue
        labeller = (row.get("labeller") or "").strip() or default_labeller
        if not labeller:
            problems.append(f"{row.get('item_id')}: no labeller (pass --by)")
            continue
        if scan(row.get("note") or ""):
            problems.append(f"{row.get('item_id')}: the note looks like it holds a secret; not imported")
            continue
        append_jsonl(labels_path(ev), _record(row, label, labeller))
        added += 1
    return {"added": added, "skipped_unlabelled": skipped, "problems": problems}


def import_csv(ev: Evals, path: Path, labeller: str | None) -> dict:
    with path.open(newline="") as f:
        return import_rows(ev, list(csv.DictReader(f)), labeller)


def add(ev: Evals, item: str, label: str, labeller: str, note: str | None) -> dict:
    run_id, rest = item.split("/", 1)
    case_id, t, a = rest.rsplit(".", 2)
    row = {"item_id": item, "run": run_id, "case_id": case_id, "trial": t.lstrip("t"), "attempt": a.lstrip("a"),
           "label": label, "note": note or ""}
    return import_rows(ev, [row], labeller)


# ---------- the suite's side: re-grade a recorded run ----------

class Grader:
    """The suite's verdict on recorded attempts, with the suite as it is now. Judge verdicts are
    reused from the run's own lines, or from the re-grade cache, when the judge's sha and backend
    match; otherwise the judge is called only when `call_judges` is set."""

    def __init__(self, ev: Evals, call_judges: bool = False, log=print):
        from .judging import JudgeRunner
        from .report import judge_states

        self.ev = ev
        self.call_judges = call_judges
        self.cases = {c["id"]: c for c in ev.cases() if c.get("id")}
        self.judges = judge_states(ev)
        self.runner = JudgeRunner(ev, log=log)
        self.cache_path = ev.p("data", "agreement", "judgements.jsonl")
        self.cache: dict[tuple, dict] = {}
        for line in read_jsonl(self.cache_path):
            self.cache[(line["item"], line["check_id"], line.get("judge_sha"), line.get("backend"))] = line
        self._recorded: dict[str, dict[tuple, dict]] = {}
        self.calls = 0

    def _recorded_lines(self, run_id: str) -> dict[tuple, dict]:
        if run_id not in self._recorded:
            idx = {}
            for r in self.ev.run_records(run_id):
                if r.get("kind") == "check" and r.get("type") == "judge":
                    k = (r["case_id"], r["trial"], r["attempt"], r["check_id"], r.get("judge_sha"), r.get("backend"))
                    idx[k] = r
            self._recorded[run_id] = idx
        return self._recorded[run_id]

    def grade(self, run_id: str, a: dict) -> dict:
        case = self.cases[a["case_id"]]
        raw = _raw(self.ev, run_id, a)
        key = item_key(run_id, a["case_id"], a["trial"], a["attempt"])
        if raw is None:
            return {"item": key, "verdict": None, "why": "raw record missing", "checks": []}
        start = {"world": raw.get("start_world"), "output": None}
        end = {"world": raw.get("end_world"), "output": raw.get("output")}
        lines = []
        for cid, _ in self.ev.checks_for_case(case, check_type="code"):
            cr = run_check(cid, self.ev.code_check_path(cid), start, end, case)
            lines.append({"check_id": cid, "type": "code", "counted": True, "passed": cr.passed, "detail": cr.detail})
        for cid, fm in self.ev.checks_for_case(case, check_type="judge"):
            st = self.judges.get(cid) or {}
            counted = bool(st.get("calibrated"))
            line = self._judge_line(run_id, a, key, case, cid, fm, st, start, end) if st.get("spec") else None
            if line is None:
                lines.append({"check_id": cid, "type": "judge", "counted": counted, "passed": None,
                              "detail": "not judged (no cached verdict; pass --call-judges)"})
                continue
            score = line.get("score")
            verdict = (score >= st.get("threshold_or_default", 0.5)) if score is not None else line.get("passed")
            lines.append({"check_id": cid, "type": "judge", "counted": counted, "passed": verdict,
                          "detail": (line.get("detail") or "")[:500]})
        counted = [ln["passed"] for ln in lines if ln["counted"]]
        if any(v is False for v in counted):
            verdict = "fail"
        elif any(v is None for v in counted) or not counted:
            verdict = None
        else:
            verdict = "pass"
        return {"item": key, "verdict": verdict, "checks": lines}

    def _judge_line(self, run_id, a, key, case, cid, fm, st, start, end) -> dict | None:
        sha, backend = st["sha"], st["backend"]
        rec = self._recorded_lines(run_id).get((a["case_id"], a["trial"], a["attempt"], cid, sha, backend))
        if rec:
            return rec
        if (key, cid, sha, backend) in self.cache:
            return self.cache[(key, cid, sha, backend)]
        if not self.call_judges:
            return None
        ids = {"run_id": run_id, "case_id": a["case_id"], "trial": a["trial"], "attempt": a["attempt"]}
        line = self.runner.line(st["spec"], backend, fm.get("id"), case, start, end, ids)
        line = {**line, "item": key}
        append_jsonl(self.cache_path, line)
        self.cache[(key, cid, sha, backend)] = line
        self.calls += 1
        return line


def regrade(ev: Evals, run_id: str, call_judges: bool = False, log=print) -> list[dict]:
    """Every final attempt of a run, graded by the suite as it is now."""
    g = Grader(ev, call_judges=call_judges, log=log)
    return [g.grade(run_id, a) for a in finals(ev, [run_id])]


def reproduces(ev: Evals, run_id: str) -> dict:
    """Do the code checks give the same verdicts on the raw records as they did during the run? A
    check that differs reads something besides (start, end, case), such as the live system at
    grading time, and can't be re-graded or trusted on a recorded run."""
    recorded = {}
    for r in ev.run_records(run_id):
        if r.get("kind") == "check" and r.get("type") == "code":
            recorded[(r["case_id"], r["trial"], r["attempt"], r["check_id"])] = r.get("passed")
    g = Grader(ev)
    differ = defaultdict(int)
    compared = 0
    for a in finals(ev, [run_id]):
        for ln in g.grade(run_id, a)["checks"]:
            k = (a["case_id"], a["trial"], a["attempt"], ln["check_id"])
            if ln["type"] == "code" and k in recorded:
                compared += 1
                if recorded[k] != ln["passed"]:
                    differ[ln["check_id"]] += 1
    return {"run": run_id, "compared": compared, "differ": dict(differ)}


# ---------- agreement ----------

def _rates(rows: list[dict]) -> dict:
    fails = [r for r in rows if r["human"] == "fail"]
    passes = [r for r in rows if r["human"] == "pass"]
    caught = sum(r["suite"] == "fail" for r in fails)
    clean = sum(r["suite"] == "pass" for r in passes)

    def rate(k, n):
        return {"rate": k / n if n else None, "ci95": stats.wilson(k, n), "k": k, "n": n}
    out = {"runs": len(rows), "human_fail": len(fails), "human_pass": len(passes),
           "catch": rate(caught, len(fails)), "clean": rate(clean, len(passes)),
           "no_verdict": sum(r["suite"] is None for r in rows)}
    c, p = out["catch"]["rate"], out["clean"]["rate"]
    out["balanced"] = (c + p) / 2 if c is not None and p is not None else None
    return out


def measure(ev: Evals, call_judges: bool = False, log=print) -> dict:
    labels = load_labels(ev)
    g = Grader(ev, call_judges=call_judges, log=log)
    triage = load_yaml(triage_path(ev)) or {}
    rows, missing = [], []
    for lab in labels:
        run_id = lab.get("run")
        a = next((r for r in ev.run_records(run_id) if r.get("kind") == "attempt"
                  and r.get("case_id") == lab.get("case_id") and r.get("trial") == lab.get("trial")
                  and r.get("attempt") == lab.get("attempt")), None) if run_id else None
        if a is None or lab.get("case_id") not in g.cases:
            missing.append(lab["item_id"])
            continue
        res = g.grade(run_id, a)
        human = "pass" if lab["label"] else "fail"
        rows.append({"item": lab["item_id"], "case_id": lab["case_id"],
                     "split": lab.get("split") or split_for(lab["item_id"]),
                     "human": human, "suite": res["verdict"], "note": lab.get("note") or "",
                     "failing": [f"{c['check_id']}: {c['detail'][:200]}" for c in res["checks"]
                                 if c["counted"] and c["passed"] is not True]})
    dev = [r for r in rows if r["split"] == "dev"]
    hold = [r for r in rows if r["split"] == "holdout"]
    disagreements = [{**r, "triage": triage.get(r["item"])} for r in rows if r["suite"] != r["human"]]
    result = {"measured_at": now_iso(), "suite_sha": suite_sha(ev), "labels_sha": labels_sha(labels),
              "floors": floors(ev), "dev": _rates(dev), "holdout": _rates(hold), "all": _rates(rows),
              "judge_calls": g.calls, "labels_without_a_run": missing,
              "disagreements": sorted(disagreements, key=lambda d: (d["split"], d["human"], d["case_id"]))}
    result["problems"] = gate_problems(ev, result, labels)
    write_json(result_path(ev), result)
    return result


def gate_problems(ev: Evals, result: dict | None, labels: list[dict] | None = None) -> list[str]:
    labels = load_labels(ev) if labels is None else labels
    f = floors(ev)
    problems = []
    n_fail = sum(not r["label"] for r in labels)
    n_pass = sum(bool(r["label"]) for r in labels)
    if len(labels) < f["min_runs"] or min(n_fail, n_pass) < f["min_each"]:
        problems.append(f"{len(labels)} whole runs labelled ({n_fail} fail, {n_pass} pass); needs "
                        f"{f['min_runs']} with at least {f['min_each']} of each (aot-evals agreement label queue)")
    if result is None:
        problems.append("agreement not measured (aot-evals agreement)")
        return problems
    if result.get("suite_sha") != suite_sha(ev) or result.get("labels_sha") != labels_sha(labels):
        problems.append("agreement is stale: the suite or the labels changed since it was measured "
                        "(aot-evals agreement)")
    dev = result.get("dev") or {}
    for name, floor in (("catch", f["min_catch"]), ("clean", f["min_clean"])):
        r = (dev.get(name) or {}).get("rate")
        if r is not None and r < floor:
            label = "catch rate" if name == "catch" else "clean pass rate"
            problems.append(f"dev {label} {r:.0%} is below its floor {floor:.0%}")
    untriaged = [d["item"] for d in result.get("disagreements") or []
                 if d["split"] == "dev" and (d.get("triage") or {}).get("cause") not in CAUSES]
    if untriaged:
        problems.append(f"{len(untriaged)} dev disagreement(s) without a cause in labels/triage.yaml, "
                        f"e.g. {untriaged[0]}")
    return problems


def status(ev: Evals) -> tuple[list[str], list[str]]:
    """(problems, info) for gate C19."""
    result = load_json(result_path(ev))
    problems = gate_problems(ev, result)
    info = []
    if result:
        for split in ("dev", "holdout"):
            s = result.get(split) or {}
            c, p = (s.get("catch") or {}).get("rate"), (s.get("clean") or {}).get("rate")
            if c is not None or p is not None:
                info.append(f"{split}: catch {_pct(c)}, clean pass {_pct(p)} on {s.get('runs')} runs")
    return problems, info


def _pct(v) -> str:
    return "n/a" if v is None else f"{v:.0%}"


def render(result: dict) -> str:
    lines = []
    for split in ("dev", "holdout"):
        s = result[split]
        if not s["runs"]:
            continue
        c, p = s["catch"], s["clean"]

        def fmt(x):
            ci = x["ci95"]
            return "n/a" if x["rate"] is None else f"{x['rate']:.0%} ({x['k']}/{x['n']}, 95% {ci[0]:.0%}–{ci[1]:.0%})"
        lines.append(f"{split}: {s['runs']} runs · catch {fmt(c)} · clean pass {fmt(p)} · no verdict {s['no_verdict']}")
    dev = [d for d in result["disagreements"] if d["split"] == "dev"]
    if dev:
        lines.append(f"dev disagreements ({len(dev)}):")
        for d in dev:
            t = (d.get("triage") or {}).get("cause") or "UNTRIAGED"
            why = d["failing"][0] if d["failing"] else "(no check failed)"
            lines.append(f"  [{t}] {d['item']}: person {d['human']}, suite {d['suite']} | {why}"
                         + (f" | note: {d['note'][:160]}" if d["note"] else ""))
    hold = sum(d["split"] == "holdout" for d in result["disagreements"])
    if hold:
        lines.append(f"holdout disagreements: {hold} (not listed: fix dev errors only)")
    lines += [f"problem: {p}" for p in result["problems"]] or ["C19 met"]
    return "\n".join(lines)
