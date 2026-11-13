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

In a 2.0 eval (docs/v2-design.md §6) the labels, rulings and triage are the eval's own
(`<eval>/labels/`), and the floors come from its spec (`measurement.people`): a stated floor is
read with the non-inferiority margin (statistics §4.2), a null one from `max_inflation` at the
eval's failure rate, as for a judge. Labels are counted per kind against the count each kind
needs, fixed in advance (`labels_per_kind`). agreement.json adds `labels_per_kind`,
`labels_needed`, the margin-based `evidence` that the gate now reads, and `gates`, one entry per
gate that is not met, each with its id (`people_labels`, `people_disputes`, `people_stale`,
`people_floor`, `people_triage`) so a fixture can trigger exactly one.
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


def _v2(ev) -> bool:
    from .repo import Eval

    return isinstance(ev, Eval)


def load_result(ev: Evals) -> dict | None:
    return load_json(result_path(ev))


def is_stale(ev: Evals, result: dict, labels: list[dict] | None = None) -> bool:
    """The eval (cases, checks, judges, their calibrations, the spec) or the labels changed since
    agreement.json was measured."""
    labels = load_labels(ev) if labels is None else labels
    return result.get("suite_sha") != suite_sha(ev) or result.get("labels_sha") != labels_sha(labels)


def floors(ev: Evals) -> dict:
    """`labels/floors.yaml` may set min_catch, min_clean, min_runs, min_each."""
    f = load_yaml(ev.p("labels", "floors.yaml")) or {}
    return {"min_catch": float(f.get("min_catch", MIN_CATCH)), "min_clean": float(f.get("min_clean", MIN_CLEAN)),
            "min_runs": int(f.get("min_runs", MIN_RUNS)), "min_each": int(f.get("min_each", MIN_EACH))}


def item_key(run_id: str, case_id: str, trial: int, attempt: int) -> str:
    return f"{run_id}/{case_id}.t{trial}.a{attempt}"


def rulings_path(ev: Evals) -> Path:
    return ev.p("labels", "rulings.jsonl")


def per_labeller(ev: Evals) -> dict[str, dict[str, dict]]:
    """item_id -> labeller -> that labeller's latest label (a re-label by the same person replaces
    their earlier one; another person's label sits beside it)."""
    out: dict[str, dict[str, dict]] = defaultdict(dict)
    for rec in read_jsonl(labels_path(ev)):
        out[rec["item_id"]][rec.get("labeller") or ""] = rec
    return out


def load_rulings(ev: Evals) -> dict[str, dict]:
    """item_id -> the latest ruling: the verdict a person settled on where labellers differed."""
    latest: dict[str, dict] = {}
    for rec in read_jsonl(rulings_path(ev)):
        latest[rec["item_id"]] = rec
    return latest


def add_ruling(ev: Evals, item: str, label: bool, by: str, note: str = "", rule: str | None = None) -> dict:
    if not by:
        raise ValueError("a ruling needs the name of the person making it")
    rec = {"item_id": item, "label": bool(label), "by": by, "note": (note or "").strip(),
           "rule": rule or None, "at": now_iso()}
    rulings_path(ev).parent.mkdir(parents=True, exist_ok=True)
    append_jsonl(rulings_path(ev), rec)
    return rec


def disputes(ev: Evals) -> list[dict]:
    """Runs whose labellers disagree and that have no ruling yet."""
    ruled = load_rulings(ev)
    out = []
    for iid, by in per_labeller(ev).items():
        if iid in ruled or len({bool(r["label"]) for r in by.values()}) < 2:
            continue
        first = next(iter(by.values()))
        out.append({"item_id": iid, "case_id": first.get("case_id"), "run": first.get("run"),
                    "labels": [{"labeller": k, "label": bool(r["label"]), "note": r.get("note") or ""}
                               for k, r in sorted(by.items())]})
    return out


def load_labels(ev: Evals) -> list[dict]:
    """The verdict per labelled run: a ruling where there is one; otherwise the labellers' label when
    they all agree (the latest record, with every labeller listed). A run the labellers disagree on
    has no verdict until someone rules (`disputes`), so it counts toward nothing."""
    ruled = load_rulings(ev)
    out = []
    for iid, by in per_labeller(ev).items():
        latest = max(by.values(), key=lambda r: r.get("at") or "")
        if iid in ruled:
            r = ruled[iid]
            out.append({**latest, "label": r["label"], "labeller": r["by"], "note": r["note"] or latest.get("note", ""),
                        "ruled": True, "labellers": sorted(by)})
        elif len({bool(r["label"]) for r in by.values()}) == 1:
            out.append({**latest, "labellers": sorted(by)})
    return out


def labeller_agreement(ev: Evals) -> list[dict]:
    """For each pair of labellers: the runs both labelled, how often they agreed, and Cohen's κ."""
    by_person: dict[str, dict[str, bool]] = defaultdict(dict)
    for iid, by in per_labeller(ev).items():
        for who, r in by.items():
            by_person[who][iid] = bool(r["label"])
    people = sorted(by_person)
    out = []
    for i, a in enumerate(people):
        for b in people[i + 1:]:
            both = sorted(set(by_person[a]) & set(by_person[b]))
            if not both:
                continue
            pairs = [(by_person[a][x], by_person[b][x]) for x in both]
            agree = sum(x == y for x, y in pairs)
            n = len(pairs)
            st = stats.agreement_stats(pairs) or {}
            # M34: kappa swings with the pass rate; AC1 and the specific agreements do not
            out.append({"labellers": [a, b], "n": n, "agree": agree, "rate": agree / n,
                        "ci95": stats.wilson(agree, n), "kappa": st.get("kappa"),
                        "ac1": st.get("ac1"), "pass_agreement": st.get("positive_agreement"),
                        "fail_agreement": st.get("negative_agreement"),
                        "differ": [x for x in both if by_person[a][x] != by_person[b][x]]})
    return out


def labels_sha(labels: list[dict]) -> str:
    body = sorted((r["item_id"], r["label"]) for r in labels)
    return hashlib.sha256(json.dumps(body).encode()).hexdigest()[:16]


def suite_sha(ev: Evals) -> str:
    """What the verdict depends on: cases, checks, judge specs and their calibrations."""
    h = hashlib.sha256()
    for sub, pattern in (("cases", "**/*.json"), ("checks/code", "*.py"), ("checks/judge", "*.md"),
                         ("checks/judge", "*.calibration.json"), (".", "failure_modes.yaml"),
                         (".", "eval.yaml")):
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
               seed: int = 0, only_cases: set[str] | None = None) -> tuple[Path, list[dict]]:
    """Runs not yet labelled, `per_case` per case (cases with fewest labels first), shuffled. With
    `only_cases`, only those cases (after a change: the ones whose verdict moved)."""
    cases = {c["id"]: c for c in ev.cases() if c.get("id")}
    labelled = per_labeller(ev)  # a run anyone labelled, agreed or disputed, is not queued again
    done = set(labelled)
    count = defaultdict(int)
    for by in labelled.values():
        count[next(iter(by.values())).get("case_id")] += 1
    by_case: dict[str, list[dict]] = defaultdict(list)
    for a in finals(ev, run_ids):
        if only_cases is not None and a["case_id"] not in only_cases:
            continue
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
              "case_id": a["case_id"],
              "category": cases[a["case_id"]].get("category") or cases[a["case_id"]].get("use_case") or "",
              "run": a["run_id"], "trial": a["trial"], "attempt": a["attempt"], "label": "", "labeller": "",
              "note": "", "input": run_view(ev, a["run_id"], a, cases[a["case_id"]])} for a in picked]
    path = ev.p("data", "agreement", "queue.json")
    write_json(path, {"made_at": now_iso(), "runs": run_ids, "seed": seed, "items": items})
    return path, items


def write_page(ev: Evals) -> Path:
    from .brand import _esc, page
    from .label_page import SCRIPT
    from .markdown import render as md

    q = load_json(ev.p("data", "agreement", "queue.json"))
    if not q:
        raise FileNotFoundError("no queue; run `aot-evals agreement label queue --run RUN` first")
    items = q["items"]
    queue_sha = hashlib.sha256(json.dumps([i["item_id"] for i in items]).encode()).hexdigest()[:12]
    from .requirements import load_standard

    std = load_standard(ev)
    rules = "".join(f"<li><strong>{_esc(r.get('id', ''))}</strong>: {_esc(r.get('says', ''))}</li>"
                    for r in (std or {}).get("rules") or [])
    guidance = (md(std["body"]) + (f"<ul>{rules}</ul>" if rules else "")) if std else (
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


def import_rows(ev: Evals, rows: list[dict], default_labeller: str | None, run_id: str | None = None) -> dict:
    """With `run_id`, rows that give only case_id and trial (labels made outside this tool) are
    attached to that run's final attempt of the case and trial."""
    added = skipped = 0
    problems = []
    labels_path(ev).parent.mkdir(parents=True, exist_ok=True)
    finals_of = {}
    if run_id:
        finals_of = {(a["case_id"], int(a["trial"])): a for a in finals(ev, [run_id])}
    for row in rows:
        if not row.get("item_id") and run_id:
            a = finals_of.get((row.get("case_id"), int(row.get("trial") or -1)))
            if a is None:
                problems.append(f"{row.get('case_id')} trial {row.get('trial')}: no final attempt in {run_id}")
                continue
            row = {**row, "item_id": item_key(run_id, a["case_id"], a["trial"], a["attempt"]), "run": run_id,
                   "attempt": a["attempt"]}
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


def import_csv(ev: Evals, path: Path, labeller: str | None, run_id: str | None = None) -> dict:
    with path.open(newline="") as f:
        return import_rows(ev, list(csv.DictReader(f)), labeller, run_id)


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
        v2 = _v2(self.ev)
        for cid, fm in self.ev.checks_for_case(case, check_type="code"):
            cr = run_check(cid, self.ev.code_check_path(cid), start, end, case)
            lines.append({"check_id": cid, "type": "code", "counted": self.ev.counted(cid, fm) if v2 else True,
                          "passed": cr.passed, "detail": cr.detail})
        for cid, fm in self.ev.checks_for_case(case, check_type="judge"):
            st = self.judges.get(cid) or {}
            # 2.0: the eval is measured as it is built, every counted check included; whether a
            # judge may count toward θ̂ is its floor, read by the report (measurement.judge_floor)
            counted = self.ev.counted(cid, fm) if v2 else bool(st.get("calibrated"))
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
        case = g.cases.get(lab["case_id"]) or {}
        rows.append({"item": lab["item_id"], "case_id": lab["case_id"],
                     "category": case.get("category") or case.get("use_case"),
                     "split": lab.get("split") or split_for(lab["item_id"]),
                     "human": human, "suite": res["verdict"], "note": lab.get("note") or "",
                     "failing": [f"{c['check_id']}: {c['detail'][:200]}" for c in res["checks"]
                                 if c["counted"] and c["passed"] is not True]})
    dev = [r for r in rows if r["split"] == "dev"]
    hold = [r for r in rows if r["split"] == "holdout"]
    disagreements = [{**r, "triage": triage.get(r["item"])} for r in rows if r["suite"] != r["human"]]
    by_cat = {}
    for r in rows:
        by_cat.setdefault(r["category"], []).append(r)
    categories = {cat: {"dev": _rates([r for r in rs if r["split"] == "dev"]),
                        "holdout": _rates([r for r in rs if r["split"] == "holdout"])}
                  for cat, rs in sorted(by_cat.items(), key=lambda kv: str(kv[0]))}
    result = {"measured_at": now_iso(), "suite_sha": suite_sha(ev), "labels_sha": labels_sha(labels),
              "floors": floors(ev), "dev": _rates(dev), "holdout": _rates(hold), "all": _rates(rows),
              "categories": categories,
              "judge_calls": g.calls, "labels_without_a_run": missing,
              "disagreements": sorted(disagreements, key=lambda d: (d["split"], d["human"], d["case_id"]))}
    result["evidence"] = evidence(result)
    result["human_anchored"] = human_anchored(ev, g, rows, labels)
    if _v2(ev):
        result.update(measure_v2(ev, result, labels))
    result["problems"] = gate_problems(ev, result, labels)
    write_json(result_path(ev), result)
    return result


def measure_v2(ev, result: dict, labels: list[dict]) -> dict:
    """The 2.0 keys of agreement.json: floors from the spec, labels per kind against the count
    each kind needs, and the margin-based evidence the gate reads (measurement.people_floor)."""
    from . import measurement as ms
    from .report_v2 import Scored, default_runs
    from .spec import use_case_weights

    spec = ev.spec()
    n_fail = sum(not r["label"] for r in labels)
    need = ms.labels_needed(spec)
    runs = default_runs(ev)
    rate = None
    if runs:
        s = Scored(ev, runs)
        weights, _ = use_case_weights(spec)
        rate = ms.weighted_rate(s, weights,
                                lambda a: None if a.get("passed") is None else (0.0 if a["passed"] else 1.0))
    dev = result.get("dev") or {}
    fl = ms.people_floor(spec, dev.get("catch") or {}, dev.get("clean") or {}, rate)
    ps = ms.people_settings(spec)
    return {"floors": {**ps["floors"], "margin": ps["margin"], "labels_per_kind": ps["labels_per_kind"],
                       "source": "measurement.people (eval.yaml)"},
            "labels_per_kind": {"fail": n_fail, "pass": len(labels) - n_fail},
            "labels_needed": need, "eval_failure_rate": rate, "evidence": {**fl, "split": "dev"}}


def evidence(result: dict, margin: float = 0.10) -> dict:
    """M35, informational: does each dev rate clear its floor with enough runs behind it?

    The gate reads the point estimate. This adds the non-inferiority reading proposed in
    docs/statistics.md: the 95% lower bound within `margin` of the floor, and how many runs of
    that kind a rate at today's level would need to get there. Suite-wide and per category.
    """
    f = result.get("floors") or {}

    def one(block: dict | None) -> dict:
        out = {}
        for name, floor in (("catch", f.get("min_catch", MIN_CATCH)), ("clean", f.get("min_clean", MIN_CLEAN))):
            r = (block or {}).get(name) or {}
            out[name] = stats.floor_evidence(r.get("k", 0), r.get("n", 0), floor, margin)
        return out

    return {"margin": margin, "dev": one(result.get("dev")),
            "categories": {c: one((v or {}).get("dev")) for c, v in (result.get("categories") or {}).items()},
            "note": "informational; the gate reads the point estimate (docs/statistics.md §6)"}


def human_anchored(ev: Evals, g: Grader, rows: list[dict], labels: list[dict]) -> dict | None:
    """M33: the pass rate a person would give the labeled runs' whole population, from a few
    labels and the suite's verdict on every run (PPI++, stats.ppi_mean).

    The population is every final attempt of the runs the labels come from. Each is graded by
    the suite as it is now (offline, cached judge verdicts only). Valid when the labeled
    attempts are a random sample of that population; the queue takes one attempt per case
    first, so cases count about equally.
    """
    run_ids = sorted({lab.get("run") for lab in labels if lab.get("run")})
    if not run_ids or len(rows) < 2:
        return None
    labeled = {r["item"]: r for r in rows if r["suite"] is not None}
    unl, no_verdict = [], 0
    for rid in run_ids:
        for a in finals(ev, [rid]):
            if item_key(rid, a["case_id"], a["trial"], a["attempt"]) in labeled:
                continue
            v = g.grade(rid, a)["verdict"]
            if v is None:
                no_verdict += 1
                continue
            unl.append(1.0 if v == "pass" else 0.0)
    lab = list(labeled.values())
    est = stats.ppi_mean(unl, [1.0 if r["suite"] == "pass" else 0.0 for r in lab],
                         [1.0 if r["human"] == "pass" else 0.0 for r in lab])
    if est is None:
        return None
    return {**est, "runs": run_ids, "unlabeled_without_verdict": no_verdict,
            "suite_pass_rate": sum(unl) / len(unl) if unl else None,
            "assumption": "labeled attempts are a random sample of these runs' final attempts"}


def gates_v2(ev, result: dict | None, labels: list[dict]) -> list[dict]:
    """The eval-against-people gates of a 2.0 eval, one entry per gate that is not met."""
    out = []
    n_fail = sum(not r["label"] for r in labels)
    have = {"fail": n_fail, "pass": len(labels) - n_fail}
    if result and result.get("labels_needed"):
        need = result["labels_needed"]
    else:
        from .measurement import labels_needed

        need = labels_needed(ev.spec())
    short = [f"{have[k]} of {need[k]['n']} {'failing' if k == 'fail' else 'passing'}" for k in ("fail", "pass")
             if (need.get(k) or {}).get("n") and have[k] < need[k]["n"]]
    if short:
        out.append({"id": "people_labels", "detail": "whole-run labels per kind: " + ", ".join(short)
                    + " (fixed before looking: measurement.people.labels_per_kind; aot-evals agreement label queue)"})
    open_disputes = disputes(ev)
    if open_disputes:
        out.append({"id": "people_disputes", "detail": f"{len(open_disputes)} labelled run(s) where labellers "
                    f"disagree and nobody has ruled, e.g. {open_disputes[0]['item_id']} (aot-evals agreement rule)"})
    if result is None:
        return out
    if is_stale(ev, result, labels):
        out.append({"id": "people_stale", "detail": "agreement is stale: the eval or the labels changed since "
                    "it was measured (aot-evals agreement)"})
    ev_ = result.get("evidence") or {}
    if ev_.get("status") == "below":
        out.append({"id": "people_floor", "detail": "; ".join(ev_.get("reasons") or [])})
    untriaged = [d["item"] for d in result.get("disagreements") or []
                 if d["split"] == "dev" and (d.get("triage") or {}).get("cause") not in CAUSES]
    if untriaged:
        out.append({"id": "people_triage", "detail": f"{len(untriaged)} dev disagreement(s) without a cause in "
                    f"labels/triage.yaml, e.g. {untriaged[0]}"})
    return out


def gate_problems(ev: Evals, result: dict | None, labels: list[dict] | None = None) -> list[str]:
    labels = load_labels(ev) if labels is None else labels
    if _v2(ev):
        gs = gates_v2(ev, result, labels)
        if result is not None:
            result["gates"] = gs
        unmeasured = [] if result is not None else ["agreement not measured (aot-evals agreement)"]
        return [g["detail"] for g in gs] + unmeasured
    f = floors(ev)
    problems = []
    n_fail = sum(not r["label"] for r in labels)
    n_pass = sum(bool(r["label"]) for r in labels)
    if len(labels) < f["min_runs"] or min(n_fail, n_pass) < f["min_each"]:
        problems.append(f"{len(labels)} whole runs labelled ({n_fail} fail, {n_pass} pass); needs "
                        f"{f['min_runs']} with at least {f['min_each']} of each (aot-evals agreement label queue)")
    open_disputes = disputes(ev)
    if open_disputes:
        problems.append(f"{len(open_disputes)} labelled run(s) where labellers disagree and nobody has "
                        f"ruled, e.g. {open_disputes[0]['item_id']} (aot-evals serve, or aot-evals agreement rule)")
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
    judge_labels = sum(1 for p in ev.p("checks", "judge").glob("*.labels.jsonl") for _ in read_jsonl(p)) \
        if ev.p("checks", "judge").exists() else 0
    if judge_labels and not load_labels(ev):
        info.append(f"{judge_labels} per-judge labels exist; those calibrate judges. Whole-run labels, which "
                    "hold the suite as a whole to people, are separate and start from zero")
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
    for name, label in (("catch", "catch rate"), ("clean", "clean pass rate")):
        if "labels_needed" in result:  # 2.0: the margin evidence is the gate, listed under problems
            break
        e = ((result.get("evidence") or {}).get("dev") or {}).get(name)
        if e and e["meets_point"] and not e["meets_margin"]:
            lines.append(f"evidence: dev {label} {e['point']:.0%} clears its floor on {e['n']} runs, but its 95% "
                         f"lower bound is {e['lower']:.0%}; about {e['n_needed']} runs of that kind would put it "
                         f"within {e['margin']:.0%} of the floor (informational, docs/statistics.md §6)")
    h = result.get("human_anchored")
    if h:
        lines.append(f"human-anchored pass rate: {h['point']:.0%} (95% {h['ci'][0]:.0%}–{h['ci'][1]:.0%}) from "
                     f"{h['n_labeled']} labels and {h['n_unlabeled']} unlabeled runs; labels alone: "
                     f"{h['labels_only']['point']:.0%}" + (f", the suite alone: {h['suite_pass_rate']:.0%}"
                                                          if h.get("suite_pass_rate") is not None else ""))
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
    if "labels_needed" in result:
        have, need = result["labels_per_kind"], result["labels_needed"]
        lines.append(f"labels per kind: {have['fail']} failing of {need['fail']['n']}, {have['pass']} passing of "
                     f"{need['pass']['n']} ({need['fail']['source']})")
        e = result.get("evidence") or {}
        lines.append(f"against its floors (dev, margin {e.get('margin', 0):.0%}): {e.get('status')}")
        lines += [f"problem: [{g['id']}] {g['detail']}" for g in result.get("gates") or []] or [
            "the eval meets people's labels"]
        return "\n".join(lines)
    lines += [f"problem: {p}" for p in result["problems"]] or ["C19 met"]
    return "\n".join(lines)
