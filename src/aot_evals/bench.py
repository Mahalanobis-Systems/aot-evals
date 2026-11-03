"""The bench of graders (docs/method.md §4.2): what people do in the Judge phase, without an engineer.

The grader application (`aot-evals serve`) and the CLI share this module. Everything it writes is a
plain file in the suite, committed like any other:

- `labels/runs.jsonl`: whole-run labels, one line per (run, labeller); several people may label the
  same run, blind to each other (agreement.per_labeller).
- `labels/rulings.jsonl`: the verdict a person settled on where labellers differed.
- `labels/proposals.yaml`: rules proposed from a pattern of rulings, and whether the owner accepted
  them; an accepted rule is added to `labels/standard.md`.
- `labels/triage.yaml`: a cause for each disagreement between the suite and a person (C19).
- `labels/drafts/<id>.json`: cases a grader drafted, waiting for an engineer to finish.
- a case's `expected_end_state.output_variants`: other correct answers a grader accepted.

Queues are per labeller. A new labeller starts with a warm-up of runs whose answer is settled, and
sees the settled answer after each one; after that, one run in four is a run someone else has
labelled (an overlap, for agreement between people), and the rest are runs nobody has labelled.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path

import yaml

from . import agreement
from .repo import Evals
from .scrub import scan
from .util import dump_yaml, load_json, load_yaml, now_iso, write_json

WARMUP = 5          # runs with a settled answer, shown first to a new labeller
OVERLAP_EVERY = 4   # one queued run in this many is one someone else labelled
WORK_CAUSES = {     # triage causes that need an engineer, and what to do
    "missing-requirement": "add the requirement to the case and a check that decides it",
    "wrong-expectation": "fix the case's expected answer or end state",
    "check-bug": "fix the check that decided wrongly",
    "judge-error": "add the run to the judge's labels and recalibrate it",
}


# ---- the runs people label ----------------------------------------------------------------------

def label_runs(ev: Evals) -> list[str]:
    """The runs whose results people label: the baseline (every category's newest baseline run) and
    the latest candidate after it, last."""
    base = ev.baseline_runs()
    out = [m["run_id"] for m in base]
    newest = max((m.get("finished") or "" for m in base), default="")
    cands = [m for m in ev.runs("candidate") if m.get("finished")]
    if cands and cands[-1]["finished"] > newest:
        out.append(cands[-1]["run_id"])
    return out


def candidate_run(ev: Evals) -> str | None:
    """The latest candidate after the baseline, if any."""
    runs = label_runs(ev)
    base = set(ev.baseline_ids())
    return runs[-1] if runs and runs[-1] not in base else None


def changed_cases(ev: Evals) -> list[str]:
    """Cases whose verdict moved between the baseline and the latest compared candidate."""
    from .compare import latest_for

    base = ev.baseline_ids()
    comp = latest_for(ev, base) if base else None
    if not comp:
        return []
    return sorted(set(comp.get("gains") or []) | set(comp.get("losses") or [])
                  | {m["case"] for m in comp.get("moved") or []})


def settled(ev: Evals) -> dict[str, dict]:
    """item_id -> {label, why}: runs whose answer is settled, by a ruling or by two or more people
    agreeing. These make the warm-up."""
    ruled = agreement.load_rulings(ev)
    out = {iid: {"label": r["label"], "why": f"ruled by {r['by']}" + (f": {r['note']}" if r["note"] else ""),
                 "rule": r.get("rule")} for iid, r in ruled.items()}
    for iid, by in agreement.per_labeller(ev).items():
        if iid in out or len(by) < 2 or len({bool(r["label"]) for r in by.values()}) > 1:
            continue
        lab = bool(next(iter(by.values()))["label"])
        notes = [f"{k}: {r['note']}" for k, r in sorted(by.items()) if r.get("note")]
        out[iid] = {"label": lab, "why": f"{len(by)} people agreed" + (f" ({'; '.join(notes)})" if notes else ""),
                    "rule": None}
    return out


def _item(ev: Evals, cases: dict, a: dict, mode: str) -> dict:
    case = cases[a["case_id"]]
    return {"item_id": agreement.item_key(a["run_id"], a["case_id"], a["trial"], a["attempt"]),
            "case_id": a["case_id"], "category": case.get("category") or "", "run": a["run_id"],
            "trial": a["trial"], "attempt": a["attempt"], "mode": mode,
            "view": agreement.run_view(ev, a["run_id"], a, case)}


def queue(ev: Evals, labeller: str, mode: str = "auto", n: int = 20) -> list[dict]:
    """The next runs for one labeller. `mode`: auto (warm-up, then new runs with an overlap in
    every four), warmup, overlap, new, or changed (only cases whose verdict moved in the latest
    comparison, from the candidate run)."""
    if not labeller:
        raise ValueError("a queue is per labeller: give a name")
    cases = {c["id"]: c for c in ev.cases() if c.get("id")}
    runs = label_runs(ev)
    if mode == "changed":
        cand = candidate_run(ev)
        runs = [cand] if cand else []
    finals = [a for a in agreement.finals(ev, runs) if a["case_id"] in cases]
    if mode == "changed":
        moved = set(changed_cases(ev))
        finals = [a for a in finals if a["case_id"] in moved]
    by = agreement.per_labeller(ev)
    mine = {iid for iid, people in by.items() if labeller in people}
    done_settled = settled(ev)

    def key(a):
        return agreement.item_key(a["run_id"], a["case_id"], a["trial"], a["attempt"])

    pool = [a for a in finals if key(a) not in mine]
    warm = [a for a in pool if key(a) in done_settled]
    overlap = [a for a in pool if key(a) in by and key(a) not in done_settled]
    fresh = [a for a in pool if key(a) not in by]
    # fresh runs: one per case first, cases with the fewest labels first
    per_case = defaultdict(int)
    for people in by.values():
        per_case[next(iter(people.values())).get("case_id")] += 1
    seen, first, rest = set(), [], []
    for a in sorted(fresh, key=lambda a: (per_case[a["case_id"]], a["case_id"], a["trial"])):
        (rest if a["case_id"] in seen else first).append(a)
        seen.add(a["case_id"])
    fresh = first + rest

    if mode == "warmup":
        picked = [(a, "warm-up") for a in warm]
    elif mode == "overlap":
        picked = [(a, "overlap") for a in overlap]
    elif mode in ("new", "changed"):
        picked = [(a, mode) for a in fresh + overlap]
    else:
        picked = [(a, "warm-up") for a in warm[:max(0, WARMUP - len(mine))]]
        n_warm = len(picked)
        o, f = list(overlap), list(fresh)
        while (o or f) and len(picked) < n:
            slot = len(picked) - n_warm
            if o and (slot % OVERLAP_EVERY == OVERLAP_EVERY - 1 or not f):
                picked.append((o.pop(0), "overlap"))
            else:
                picked.append((f.pop(0), "new"))
    return [_item(ev, cases, a, m) for a, m in picked[:n]]


def record_label(ev: Evals, item: dict, label: str, labeller: str, note: str = "") -> dict:
    """One person's label on one run. Returns what was imported, and the settled answer when the
    run was a warm-up (shown only after the label is in, so it can't lead the labeller)."""
    row = {"item_id": item["item_id"], "case_id": item.get("case_id"), "run": item.get("run"),
           "trial": item.get("trial"), "attempt": item.get("attempt"), "label": label,
           "labeller": labeller, "note": note or ""}
    ans = settled(ev).get(item["item_id"])  # before this label: a labeller who differs unsettles it
    res = agreement.import_rows(ev, [row], labeller)
    if ans and item.get("mode") == "warm-up":
        res["settled"] = ans
    return res


# ---- what the suite and people disagree on ----------------------------------------------------------

def suite_disagreements(ev: Evals) -> dict:
    """The latest measurement's disagreements between the suite and a person, each with its triage."""
    res = load_json(agreement.result_path(ev)) or {}
    triage = load_yaml(agreement.triage_path(ev)) or {}
    rows = [{**d, "triage": triage.get(d["item"])} for d in res.get("disagreements") or []]
    stale = bool(res) and agreement.gate_problems(ev, res) and any(
        "stale" in p for p in agreement.gate_problems(ev, res))
    return {"measured_at": res.get("measured_at"), "stale": stale, "items": rows,
            "dev": res.get("dev"), "holdout": res.get("holdout"), "categories": res.get("categories") or {}}


def set_triage(ev: Evals, item: str, cause: str, note: str, by: str) -> dict:
    if cause not in agreement.CAUSES:
        raise ValueError(f"cause must be one of {sorted(agreement.CAUSES)}")
    path = agreement.triage_path(ev)
    data = load_yaml(path) or {}
    data[item] = {"cause": cause, "note": (note or "").strip(), "by": by, "at": now_iso()[:10]}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump_yaml(data))
    return data[item]


def accept_answer(ev: Evals, item: str, by: str) -> dict:
    """A person passed this run and the suite failed it because the answer is worded differently
    from the reference: add the answer to the case's other correct wordings, and triage the
    disagreement as a wrong expectation fixed by that person. No engineer needed."""
    run_id, _, rest = item.partition("/")
    m = re.match(r"(.+)\.t(\d+)\.a(\d+)$", rest)
    if not m:
        raise ValueError(f"not a run item: {item}")
    case_id, trial, attempt = m.group(1), int(m.group(2)), int(m.group(3))
    raw = load_json(ev.p("runs", run_id, "raw", f"{case_id}.t{trial}.a{attempt}.json")) or {}
    answer = raw.get("output")
    if not isinstance(answer, str) or not answer.strip():
        raise ValueError("this run has no answer to accept")
    if any(f.kind == "secret" for f in scan(answer)):
        raise ValueError("the answer holds what looks like a secret; it can't go into a case")
    case = next((c for c in ev.cases() if c.get("id") == case_id), None)
    if case is None:
        raise ValueError(f"no case {case_id}")
    path = ev.p(case["_path"])
    data = json.loads(path.read_text())
    exp = data.setdefault("expected_end_state", {})
    if exp.get("output") is None:
        raise ValueError(f"case {case_id} has no reference answer; another wording has nothing to vary")
    variants = exp.setdefault("output_variants", [])
    if answer not in variants and answer != exp.get("output"):
        variants.append(answer)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    # Screen the case again: every accepted wording must pass every check. If one still fails, the
    # check is bound to one wording, and that is an engineer's fix (a check bug).
    from .screen import run_screen

    row = run_screen(ev, case_ids=[case_id])[0]
    mark = f"variant {variants.index(answer) + 1}:" if answer in variants else None
    still = [f for f in row.get("failing_paraphrases") or [] if mark and f.startswith(mark)]
    if still:
        set_triage(ev, item, "check-bug", f"{by} accepted this answer as correct, and a check still rejects "
                   f"it: {still[0]}", by)
    else:
        set_triage(ev, item, "wrong-expectation", f"answer accepted as another correct wording by {by}", by)
    return {"case": case_id, "variants": len(variants), "check_rejects": still}


# ---- rules from rulings ---------------------------------------------------------------------------

def proposals_path(ev: Evals) -> Path:
    return ev.p("labels", "proposals.yaml")


def proposals(ev: Evals) -> list[dict]:
    return list((load_yaml(proposals_path(ev)) or {}).get("proposals") or [])


def _write_proposals(ev: Evals, items: list[dict]) -> None:
    proposals_path(ev).parent.mkdir(parents=True, exist_ok=True)
    proposals_path(ev).write_text(dump_yaml({"proposals": items}))


def propose_rule(ev: Evals, says: str, categories: list[str], by: str, items: list[str] | None = None,
                 rule_id: str | None = None) -> dict:
    """A grader proposes a rule from a pattern of rulings. The owner accepts or declines it."""
    if not says.strip() or not by:
        raise ValueError("a proposal needs the rule's text and who proposes it")
    items_ = proposals(ev)
    rid = rule_id or re.sub(r"[^a-z0-9]+", "-", says.lower()).strip("-")[:40] or f"rule-{len(items_) + 1}"
    p = {"id": rid, "says": says.strip(), "categories": categories or ["*"], "items": items or [],
         "by": by, "at": now_iso()[:10], "status": "proposed"}
    _write_proposals(ev, [*items_, p])
    return p


def decide_rule(ev: Evals, rule_id: str, accept: bool, by: str) -> dict:
    """The owner accepts (the rule joins labels/standard.md) or declines a proposal."""
    items_ = proposals(ev)
    p = next((x for x in items_ if x["id"] == rule_id and x["status"] == "proposed"), None)
    if p is None:
        raise ValueError(f"no open proposal {rule_id}")
    p.update({"status": "accepted" if accept else "declined", "decided_by": by, "decided_at": now_iso()[:10]})
    _write_proposals(ev, items_)
    if accept:
        src = f"{len(p['items'])} rulings, proposed by {p['by']}, accepted by {by} on {p['decided_at']}"
        add_rule(ev, {"id": p["id"], "says": p["says"], "categories": p["categories"], "from": src})
    return p


def add_rule(ev: Evals, rule: dict) -> None:
    """Add a rule to the standard's front matter, keeping its body and comments."""
    from .requirements import standard_path

    path = standard_path(ev)
    text = path.read_text() if path.exists() else "---\nrules: []\n---\n\n# Labelling standard\n"
    m = re.match(r"---\n(.*?)\n---\n", text, re.S)
    if not m:
        text = f"---\nrules: []\n---\n{text}"
        m = re.match(r"---\n(.*?)\n---\n", text, re.S)
    front, body = m.group(1), text[m.end():]
    meta = yaml.safe_load(front) or {}
    rules = meta.get("rules") or []
    if any(r.get("id") == rule["id"] for r in rules):
        raise ValueError(f"the standard already has a rule {rule['id']}")
    block = yaml.safe_dump([rule], sort_keys=False, allow_unicode=True, width=1000)
    block = "".join(f"  {ln}\n" for ln in block.splitlines())
    tops = [ln for ln in front.splitlines() if ln and not ln.startswith((" ", "#", "-"))]
    if tops and tops[-1].startswith("rules:") and not tops[-1].rstrip().endswith("[]"):
        front = front.rstrip("\n") + "\n" + block.rstrip("\n")  # rules is the last key: append, keep comments
    else:
        meta["rules"] = [*rules, rule]
        front = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True, width=1000).rstrip("\n")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\n{front}\n---\n{body}")


def recheck(ev: Evals, rule_id: str) -> list[str]:
    """Labelled runs an accepted rule could flip: those in its categories, labelled before it."""
    p = next((x for x in proposals(ev) if x["id"] == rule_id and x["status"] == "accepted"), None)
    if p is None:
        return []
    cats = set(p["categories"])
    cases = {c["id"]: c.get("category") for c in ev.cases()}
    return sorted(r["item_id"] for r in agreement.load_labels(ev)
                  if ("*" in cats or cases.get(r.get("case_id")) in cats)
                  and (r.get("at") or "")[:10] <= p["decided_at"])


# ---- cases a grader drafts -------------------------------------------------------------------------

def drafts_dir(ev: Evals) -> Path:
    return ev.p("labels", "drafts")


def draft_case(ev: Evals, like: str, request: str, by: str, answer: str | None = None,
               nothing_changes: bool = False, note: str = "") -> dict:
    """A grader writes a new request in the shape of an existing case. It waits in labels/drafts/
    for an engineer to set its start and expected end state and move it into cases/ (it isn't
    graded until then)."""
    src = next((c for c in ev.cases() if c.get("id") == like), None)
    if src is None:
        raise ValueError(f"no case {like} to model the draft on")
    for text in (request, answer or "", note):
        if any(f.kind == "secret" for f in scan(text)):
            raise ValueError("the draft holds what looks like a secret; scrub it first")
    d = drafts_dir(ev)
    d.mkdir(parents=True, exist_ok=True)
    n = 1 + len(list(d.glob(f"{like}-d*.json")))
    did = f"{like}-d{n}"
    draft = {"id": did, "category": src.get("category"), "like": like, "set": src.get("set"),
             "trigger": {**(src.get("trigger") or {"type": "message"}), "text": request.strip()},
             "reference_answer": (answer or "").strip() or None, "nothing_changes": bool(nothing_changes),
             "note": note.strip(), "by": by, "at": now_iso()[:10],
             "needs": ["start_state and expected_end_state set by an engineer",
                       "requirements walked from the standard", "a screen and a human read"]}
    write_json(d / f"{did}.json", draft)
    return draft


def drafts(ev: Evals) -> list[dict]:
    d = drafts_dir(ev)
    return [load_json(p) for p in sorted(d.glob("*.json"))] if d.exists() else []


# ---- the engineering inbox --------------------------------------------------------------------------

def inbox(ev: Evals) -> list[dict]:
    """What the Judge phase needs from engineering: triaged disagreements whose cause is a fix to
    the suite, drafted cases, and changes to the agent only an engineer can run."""
    from . import trust

    out = []
    for d in suite_disagreements(ev)["items"]:
        t = d.get("triage") or {}
        if t.get("cause") in WORK_CAUSES and "accepted as another correct wording" not in (t.get("note") or ""):
            out.append({"kind": t["cause"], "item": d["item"], "case": d["case_id"],
                        "what": WORK_CAUSES[t["cause"]], "note": t.get("note") or d.get("note") or "",
                        "by": t.get("by")})
    for dr in drafts(ev):
        out.append({"kind": "draft", "item": dr["id"], "case": dr["like"],
                    "what": "finish the drafted case and move it into cases/",
                    "note": (dr.get("trigger") or {}).get("text", ""), "by": dr["by"]})
    for c in trust.changes(ev):
        if c["kind"] in ("agent", "agent-uncommitted", "new-use-case", "cases", "checks", "candidate", "adopt"):
            out.append({"kind": c["kind"], "item": None, "case": None, "what": c["path"][0],
                        "note": c["what"], "by": None})
    return out
