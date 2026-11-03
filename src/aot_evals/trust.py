"""Phases, trust per category, and what changed since the baseline (docs/method.md §4.1).

The gates (gates.py) say which steps of the method are done. This module reads them the way a
team does: which of the three phases the work is in (assess, build, judge), how far each category's
numbers can be trusted (untested, provisional, validated), what has changed since the last
baseline and the short path back for each kind of change, and the single next step. `aot-evals
status` prints it; `status --json` carries it; the checkpoint pages and the grader application
read the same data.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import agreement
from . import gates as gates_mod
from .repo import Evals
from .util import git_commit_info, git_same_tree, load_json, sha256_file

PHASES = {
    "assess": "Assess: understand the agent, its traffic and its risks, and write the report.",
    "build": "Build: wire the agent, seed cases from real runs, write checks, run the baseline.",
    "judge": "Judge: people label runs, the suite is held to them, and each category earns trust.",
}
LEVELS = ("untested", "provisional", "validated")

# Each kind of change since the baseline: what it invalidates, and the short path back.
PATHS = {
    "agent": ["Run a candidate on the same cases: aot-evals run --purpose candidate --k 5 "
              "--variable KIND=VALUE (or --model ID), then aot-evals compare.",
              "Have a person label only the runs whose verdict changed, and the categories that "
              "are still provisional."],
    "agent-uncommitted": ["Commit the agent before running: a run of an uncommitted build can't be "
                          "named, so it can't be compared."],
    "new-use-case": ["Write a check for the new category's failure modes (checks/code/ first).",
                     "Run a baseline that includes it: aot-evals run --purpose baseline --k 5.",
                     "Label its runs until it clears the floors; until then its numbers say provisional."],
    "cases": ["Screen the new or changed cases: aot-evals screen --read-by NAME --case ID.",
              "Include them in the next baseline; the report excludes unscreened cases (G8)."],
    "checks": ["Re-grade the labelled runs offline, no agent runs needed: aot-evals agreement.",
               "Re-run the baseline only if a check's verdicts should count in a comparison."],
    "judge": ["Recalibrate from cached judgements: aot-evals calibrate --judge ID.",
              "Then re-grade the labelled runs: aot-evals agreement."],
    "standard": ["Recheck the labels the changed rules could flip, then aot-evals agreement."],
    "labels": ["Measure agreement again: aot-evals agreement."],
    "candidate": ["Compare it with the baseline: aot-evals compare."],
    "mixed-baseline": ["Run a full baseline on the current agent, so every category is measured on one "
                       "build: aot-evals run --purpose baseline --k 5."],
    "adopt": ["Have a person label the runs whose verdict moved: aot-evals agreement label queue --changed "
              "(or Label runs › Only what the last change moved, in aot-evals serve).",
              "If the change ships, run it as the new baseline: aot-evals run --purpose baseline --k 5. "
              "If not, put the agent back."],
}


# ---- phase ------------------------------------------------------------------------------------

def discovery_path(ev: Evals) -> Path:
    return ev.discovery_path()


def phase(ev: Evals) -> dict:
    """Which phase the work is in, and why."""
    discovered = discovery_path(ev).exists()
    cases = ev.cases(include_dropped=False)
    base = ev.baseline_ids()
    if base and cases:
        pid, why = "judge", f"the baseline ({' + '.join(base)}) exists; the loop is running"
    elif discovered or cases or ev.agent():
        pid, why = "build", ("no finished baseline yet" if cases else "no cases yet")
    else:
        pid, why = "assess", "no discovery report yet"
    done = [p for p in PHASES if list(PHASES).index(p) < list(PHASES).index(pid)]
    return {"id": pid, "name": pid.capitalize(), "about": PHASES[pid], "why": why, "done": done,
            "discovery_report": str(discovery_path(ev)) if discovered else None}


# ---- trust per category --------------------------------------------------------------------------

def _rate(block: dict | None, key: str):
    return ((block or {}).get(key) or {}).get("rate")


def trust(ev: Evals) -> list[dict]:
    """Per category: untested (no baseline covers it), provisional (numbers print but are not held
    to a person's verdicts yet), or validated (the suite agrees with a person on its runs, C19)."""
    base = ev.baseline_runs()
    result = load_json(agreement.result_path(ev))
    labels = agreement.load_labels(ev)
    suite_problems = agreement.gate_problems(ev, result, labels) if base else []
    f = agreement.floors(ev)
    cases = ev.cases(include_dropped=False)
    covered = {c for m in base for c in (m.get("case_set") or {}).get("ids") or []}
    in_base = {c.get("category") for c in cases if c.get("id") in covered}
    per_cat = (result or {}).get("categories") or {}
    labelled = {}
    for lab in labels:
        cat = next((c.get("category") for c in cases if c.get("id") == lab.get("case_id")), None)
        labelled[cat] = labelled.get(cat, 0) + 1
    out = []
    for cid in ev.category_ids():
        n_cases = sum(c.get("category") == cid for c in cases)
        row = {"category": cid, "n_cases": n_cases, "level": "untested", "catch": None, "clean": None,
               "labelled_runs": labelled.get(cid, 0), "why": ""}
        if not n_cases:
            row["why"] = "no cases yet"
        elif not base or cid not in in_base:
            row["why"] = "no baseline run covers it"
        else:
            dev = (per_cat.get(cid) or {}).get("dev")
            row["catch"], row["clean"] = _rate(dev, "catch"), _rate(dev, "clean")
            row["level"] = "provisional"
            if not row["labelled_runs"]:
                row["why"] = "no run in this category has been labelled by a person"
            elif suite_problems:
                row["why"] = f"across the whole suite, {suite_problems[0]}"
            elif row["catch"] is None or row["clean"] is None:
                row["why"] = "its labelled runs are all one kind, so one rate can't be measured"
            elif row["catch"] < f["min_catch"]:
                row["why"] = f"catch rate {row['catch']:.0%} is below its floor {f['min_catch']:.0%}"
            elif row["clean"] < f["min_clean"]:
                row["why"] = f"clean pass rate {row['clean']:.0%} is below its floor {f['min_clean']:.0%}"
            else:
                row["level"], row["why"] = "validated", "the suite agrees with a person on its runs"
        out.append(row)
    return out


# ---- changes since the baseline ----------------------------------------------------------------

def baseline_view(ev: Evals) -> dict | None:
    """The effective baseline as one record: every case's file hash, every check's and judge's
    fingerprint from the newest baseline run that covers it; the agent from the newest run."""
    runs = ev.baseline_runs()
    if not runs:
        return None
    newest = runs[-1]
    view = {**newest, "run_ids": [m["run_id"] for m in runs], "runs": runs, "files": {}, "checks": {},
            "judges": {}, "has_checks": any("checks" in m for m in runs),
            "finished": max(m.get("finished") or "" for m in runs)}
    for m in runs:  # oldest first, so newer runs overwrite
        view["files"].update((m.get("case_set") or {}).get("files") or {})
        view["checks"].update(m.get("checks") or {})
        for jb in m.get("judge_backends") or []:
            view["judges"][jb.get("check")] = {**jb, "run": m["run_id"]}
    return view


def _listed(names: list[str], n: int = 3) -> str:
    return ", ".join(names[:n]) + (f", +{len(names) - n} more" if len(names) > n else "")


def changes(ev: Evals) -> list[dict]:
    """What differs between the suite and agent now and the effective baseline, as a list of
    {kind, what, path}. Each kind names the short path back (PATHS)."""
    base = baseline_view(ev)
    if not base:
        return []
    out = []

    def add(kind: str, what: str) -> None:
        out.append({"kind": kind, "what": what, "path": PATHS[kind]})

    from .compare import latest_for
    from .report import BUILD_FIELDS, manifest_view

    agent_diff = _agent_diff(ev, base)
    if agent_diff["dirty"]:
        add("agent-uncommitted", "the agent has uncommitted changes")
    if agent_diff["what"]:
        # The current version may already have run as a candidate: then the step is to decide.
        cand = next((m for m in reversed(ev.runs("candidate")) if m.get("finished")
                     and m["finished"] > base["finished"] and not _agent_diff(ev, m)["what"]), None)
        comp = latest_for(ev, base["run_ids"]) if cand else None
        if cand and comp and cand["run_id"] in comp.get("candidate_runs", []):
            add("adopt", f"the agent's current version ran as candidate {cand['run_id']} and was compared "
                         f"with the baseline: {comp.get('verdict')}, {len(comp.get('gains') or [])} gain(s), "
                         f"{len(comp.get('losses') or [])} loss(es)")
        elif not cand:
            add("agent", "; ".join(agent_diff["what"]))
    if len(base["runs"]) > 1:
        newest_commit = base["runs"][-1].get("agent_commit")

        def build(m):
            v = manifest_view(m)
            if v.get("agent_commit") and newest_commit and git_same_tree(
                    ev.repo_root, v["agent_commit"], newest_commit, exclude=ev.evals_dir):
                v = {**v, "agent_commit": newest_commit}  # the same agent, recorded at another commit
            return json.dumps({f: v[f] for f in BUILD_FIELDS}, sort_keys=True, default=str)
        builds = {build(m) for m in base["runs"]}
        if len(builds) > 1:
            add("mixed-baseline", f"the baseline's runs ({_listed(base['run_ids'], 4)}) ran different builds "
                                  "of the agent")

    cases = ev.cases(include_dropped=False)
    base_files = base["files"]
    base_cats = {c.get("category") for c in cases if c.get("id") in base_files}
    new_cats = sorted({c.get("category") for c in cases if c.get("category") not in base_cats} - {None})
    for cat in new_cats:
        n = sum(c.get("category") == cat for c in cases)
        add("new-use-case", f"a new category, {cat}, with {n} case(s) no baseline has run")
    added = [c["id"] for c in cases if c.get("id") not in base_files and c.get("category") in base_cats]
    changed = [c["id"] for c in cases if c.get("id") in base_files
               and sha256_file(ev.p(c["_path"]))[:16] != base_files[c["id"]]]
    removed = [cid for cid in base_files if cid not in {c.get("id") for c in cases}]
    if added or changed or removed:
        bits = [f"{len(x)} {w} ({_listed(x)})" for x, w in ((added, "added"), (changed, "changed"),
                                                           (removed, "dropped")) if x]
        add("cases", "cases since the baseline: " + "; ".join(bits))

    known = {**base["checks"], **{k: None for k in base["judges"] if k not in base["checks"]}}
    now_checks = {}
    for c in cases:
        for cid, _ in ev.checks_for_case(c, check_type=None):
            for path in (ev.code_check_path(cid), ev.judge_check_path(cid)):
                if path.exists():
                    now_checks[cid] = sha256_file(path)[:16]
    diff = sorted(cid for cid in now_checks if base["checks"].get(cid) and now_checks[cid] != base["checks"][cid]
                  and cid not in base["judges"])  # judges are compared by what they decide, below
    # A baseline recorded without check hashes (an older aot-evals) can't say which checks are new.
    new_checks = sorted(cid for cid in now_checks if cid not in known) if base["has_checks"] else []
    if diff or new_checks:
        what = []
        if diff:
            what.append(f"{len(diff)} code check(s) changed ({_listed(diff)})")
        if new_checks:
            what.append(f"{len(new_checks)} new check(s) ({_listed(new_checks)})")
        add("checks", "; ".join(what))

    from .calibrate import is_current, load_calibration
    from .judges import load_spec

    judged: dict[tuple, list[str]] = {}
    for cid, jb in sorted(base["judges"].items()):
        path = ev.judge_check_path(cid or "")
        if not path.exists():
            continue
        try:
            spec = load_spec(path)
        except Exception:
            continue
        if not jb.get("judge_sha") or spec.sha() == jb["judge_sha"]:
            continue
        cal = load_calibration(ev, spec)
        bumped = str(jb.get("version")) != str(spec.version)
        if cal and is_current(ev, spec, cal):
            state = "current" if cal.get("status") == "calibrated" else "failed"
        else:
            state = "stale" if cal else "none"
        judged.setdefault((bumped, state), []).append(spec.id)
    for (bumped, state), ids in sorted(judged.items(), key=lambda kv: (not kv[0][0], kv[0][1])):
        one = len(ids) == 1
        who = f"judge {ids[0]}" if one else f"{len(ids)} judges ({_listed(ids)})"
        what = (f"{who} {'has' if one else 'have'} a new version since the baseline ran" if bumped else
                f"{who} {'differs' if one else 'differ'} from what the baseline ran at the same version: "
                f"{'its' if one else 'their'} question, inputs or backends were edited without a version bump "
                "(bump `version` whenever you edit a judge)")
        they, them, its = ("it", "it", "its") if one else ("they", "them", "their")
        counts = "it counts" if one else "they count"
        how = {"current": f"{its.capitalize()} calibration is current: re-judge the baseline's runs with {them} "
                          "(aot-evals judge apply --judge ID; it judges every baseline run)",
               "failed": f"{its.capitalize()} calibration is current but below the floors: iterate on {its} dev "
                         f"errors and recalibrate (aot-evals calibrate --judge ID). Until then {counts} toward "
                         "no number",
               "stale": f"Recalibrate {them} from cached judgements (aot-evals calibrate --judge ID)",
               "none": f"{they.capitalize()} {'has' if one else 'have'} no calibration yet: label and calibrate "
                       f"(aot-evals label queue --judge ID). Until then {counts} toward no number"}[state]
        out.append({"kind": "judge", "what": what, "path": [how, PATHS["judge"][1]], "judges": ids})

    std = ev.p("labels", "standard.md")
    if base.get("standard_sha") and std.exists() and sha256_file(std)[:16] != base["standard_sha"]:
        add("standard", "the labelling standard changed")

    result = load_json(agreement.result_path(ev))
    labels = agreement.load_labels(ev)
    if result and labels and (result.get("suite_sha") != agreement.suite_sha(ev)
                              or result.get("labels_sha") != agreement.labels_sha(labels)):
        if not any(c["kind"] in ("checks", "judge", "cases") for c in out):
            add("labels", "labels were added since agreement was last measured")

    cands = [m for m in ev.runs("candidate") if m.get("finished") and m["finished"] > base["finished"]]
    if cands:
        comp = latest_for(ev, base["run_ids"])
        pending = [m["run_id"] for m in cands if not comp or m["run_id"] not in comp.get("candidate_runs", [])]
        if pending:
            add("candidate", f"candidate {pending[-1]} has not been compared with the baseline")
    return out


_INVOKE_WORDS = {"command": "its command", "cwd": "the folder it runs in", "env_sha": "its environment variables"}


def _agent_diff(ev: Evals, m: dict) -> dict:
    """How the agent now differs from the agent a run used: {what: [plain-words changes], dirty}."""
    from .runner import _env_sha

    invoke = ev.agent().get("invoke") or {}
    cwd = (ev.repo_root / str(invoke.get("cwd", "."))).resolve()
    g = git_commit_info(cwd, exclude=ev.evals_dir) if cwd.is_dir() else {"commit": None, "dirty": None}
    what = []
    if g["commit"] and m.get("agent_commit") and g["commit"] != m["agent_commit"] \
            and git_same_tree(cwd, m["agent_commit"], g["commit"], exclude=ev.evals_dir) is not True:
        # Different commit ids alone aren't a change: older versions counted commits to other parts
        # of the repository. The agent changed only when its files differ.
        what.append(f"the agent changed (commit {m['agent_commit'][:8]} → {g['commit'][:8]})")
    then_inv = m.get("invoke") or {}
    if (invoke.get("model") or None) != (then_inv.get("model") or None):
        what.append(f"the agent's model setting changed ({then_inv.get('model')} → {invoke.get('model')})")
    now = {"command": invoke.get("command"), "cwd": invoke.get("cwd"), "env_sha": _env_sha(invoke.get("env"))}
    then = {k: then_inv.get(k) for k in now}
    if then != now and any(then.values()):
        words = ", ".join(_INVOKE_WORDS[k] for k in now if now[k] != then[k])
        what.append(f"how agent.yaml runs the agent changed ({words})")
    return {"what": what, "dirty": bool(g["dirty"])}


# ---- the next step ---------------------------------------------------------------------------------

def next_step(ev: Evals, gates: list[gates_mod.Gate] | None = None) -> dict:
    """One plain-words step and the command (or skill) that does it."""
    gates = gates if gates is not None else gates_mod.evaluate(ev)
    by = {g.id: g for g in gates}
    ph = phase(ev)
    if ph["id"] == "assess":
        return {"what": "Write the discovery report: scan the repository, answer three questions "
                        "about the agent, and read its code, tools and traces.",
                "how": "/aot-evals:start", "phase": "assess"}
    if ph["id"] == "build":
        a = ev.agent()
        if not (a.get("invoke") or {}).get("command"):
            return {"what": "Wire the agent so it runs as a command (references/agent-contract.md), "
                            "or point invoke at recorded runs with aot-evals replay.",
                    "how": "edit agent.yaml invoke:", "phase": "build"}
        cases = ev.cases(include_dropped=False)
        if not cases:
            return {"what": "Seed 10 to 20 cases from real runs in the two or three largest "
                            "categories, each with the end state a correct agent leaves behind.",
                    "how": "cases/<category>/<id>.json (templates/case.json)", "phase": "build"}
        unchecked = [c["id"] for c in cases if not ev.checks_for_case(c, check_type=None)]
        if unchecked:
            return {"what": f"Write a check for the {len(unchecked)} case(s) nothing checks yet "
                            f"(e.g. {unchecked[0]}): code on the end state first, a side-effect "
                            "check on every case.",
                    "how": "checks/code/<id>.py (templates/check_code.py)", "phase": "build"}
        if not any((m.get("counts") or {}).get("ok", 0) > 0 for m in ev.runs()):
            return {"what": "Run the agent once end to end from its command.",
                    "how": "aot-evals run --purpose smoke --case <id>", "phase": "build"}
        return {"what": "Run the baseline: every case 3 to 5 times on the committed agent. Then "
                        "start the grader application and hand it to the people who will label.",
                "how": "aot-evals run --purpose baseline --k 5", "phase": "build"}
    ch = changes(ev)
    if ch:
        return {"what": f"Since the baseline, {ch[0]['what']}. {ch[0]['path'][0]}",
                "how": ch[0]["path"][0], "phase": "judge", "change": ch[0]["kind"]}
    for row in trust(ev):
        if row["level"] != "validated":
            how = ("aot-evals agreement label queue --open" if "labelled" in row["why"]
                   else "aot-evals agreement")
            return {"what": f"{row['category']} is {row['level']}: {row['why']}.", "how": how,
                    "phase": "judge", "category": row["category"]}
    for gid, what, how in (
            ("C14", "Find the coverage gaps against the outside list and triage each empty cell.",
             "aot-evals coverage"),
            ("C15", "Find the cases that never tell versions apart and decide what to prune.",
             "aot-evals redundancy"),
            ("C18", "Write the report.", "aot-evals report")):
        g = by.get(gid)
        if g and g.status == "unmet":
            return {"what": what, "how": how, "phase": "judge"}
    return {"what": "Every category is validated and nothing has changed since the baseline. "
                    "Ship changes through candidate runs; the suite is ready for them.",
            "how": "aot-evals run --purpose candidate ...", "phase": "judge"}


# ---- status --------------------------------------------------------------------------------------

def summary(ev: Evals, gates: list[gates_mod.Gate] | None = None) -> dict:
    gates = gates if gates is not None else gates_mod.evaluate(ev)
    return {"phase": phase(ev), "trust": trust(ev), "changes": changes(ev),
            "next": next_step(ev, gates)}


def render(s: dict) -> str:
    ph = s["phase"]
    lines = [f"Phase: {ph['name']} ({ph['why']})", f"  {ph['about']}"]
    if s["trust"]:
        lines.append("\nTrust per category:")
        w = max(len(r["category"]) for r in s["trust"])
        for r in s["trust"]:
            rates = ""
            if r["catch"] is not None or r["clean"] is not None:
                rates = (f"catch {_pct(r['catch'])}, clean pass {_pct(r['clean'])} "
                         f"on {r['labelled_runs']} labelled runs; ")
            lines.append(f"  {r['category']:<{w}}  {r['level']:<12} {rates}{r['why']}")
    if s["changes"]:
        lines.append("\nSince the baseline:")
        for c in s["changes"]:
            lines.append(f"  - {c['what']}")
            for step in c["path"]:
                lines.append(f"      {step}")
    nx = s["next"]
    lines.append(f"\nNext: {nx['what']}")
    if nx.get("how") and nx["how"] not in nx["what"]:
        lines.append(f"  $ {nx['how']}" if nx["how"].startswith("aot-evals") else f"  {nx['how']}")
    return "\n".join(lines)


def _pct(v) -> str:
    return "n/a" if v is None else f"{v:.0%}"
