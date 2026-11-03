"""The components of an agent's optimization loop, as a checklist (docs/method.md §4.3).

The architecture behind every Mahal Systems engagement names the parts a graded environment
needs around an agent: a safe place to run it, golden test cases, a grader application and a
bench of graders, calibrated judges, synthetic cases, an evaluation engine, objective monitoring,
and the testing and modeling that make numbers defensible. This module is that list, each part
with the phase that builds it and the command that does, and a status read from the suite.

The Assess report may set a component's state before a suite exists (`components:` in
discovery.md's front matter, keyed by id); once the suite holds evidence, the suite's own reading
wins wherever it says more than the report did. `aot-evals components` prints the list; `status
--json`, the checkpoint pages and the grader application carry it.
"""

from __future__ import annotations

from .repo import Evals
from .start import split_front_matter
from .util import load_json

# (group, id, name, phase, how aot-evals covers it)
COMPONENTS = [
    ("Agent eval infrastructure", "sandbox", "Harness and sandbox runtime", "build",
     "the agent contract and invoke.isolate (references/agent-contract.md)"),
    ("Agent eval infrastructure", "fakes", "Mock API services, staging accounts, a safe database", "build",
     "fakes in env/, hashed into every run manifest"),
    ("Agent eval infrastructure", "replay", "Record and replay", "build", "aot-evals replay"),
    ("Agent eval infrastructure", "seeded", "Self-hosted, seeded, realistic and anonymized data", "build",
     "the seed and observe hooks; scrubbed cases"),
    ("Golden test cases", "golden", "Cases broken down by categories", "build", "cases/<category>/"),
    ("Golden test cases", "deterministic", "Deterministic checks first", "build", "checks/code/"),
    ("Golden test cases", "holdouts", "Private holdouts", "judge", "the hash-assigned 20% holdout of labels"),
    ("Grader UI", "grader-ui", "Each problem graded like a test, with the reason", "judge", "aot-evals serve"),
    ("Bench of graders", "calibration-set", "A calibration set first", "judge", "the warm-up on settled runs"),
    ("Bench of graders", "two-blind", "Two blind labels per run", "judge", "overlaps in every labeller's queue"),
    ("Bench of graders", "pool", "Graders sourced from customer and expert pools", "judge",
     "per-grader links (&labeller=NAME); people, not software"),
    ("LLM judges", "judges", "Judges calibrated on human labels", "judge", "aot-evals calibrate"),
    ("LLM judges", "qualitative", "Qualitative dimensions", "judge", "judge specs in checks/judge/"),
    ("Synthetic test cases", "synthetic", "Synthetic cases generated from golden cases, validated by graders",
     "judge", "drafted cases (labels/drafts/) and synthetic: true cases"),
    ("Evaluation engine", "engine", "Golden test and judge evals", "build", "aot-evals run"),
    ("Evaluation engine", "change-scoping", "Change scoping against the test sets", "judge",
     "aot-evals status (what changed) and agreement label queue --changed"),
    ("Evaluation engine", "ab", "A/B and blue-green tests", "judge",
     "aot-evals compare; online tests are guidance only"),
    ("Evaluation engine", "trace-monitoring", "Trace monitoring", "judge", "C16-C17, guidance only for now"),
    ("Objective monitoring", "weighting", "Value and traffic weighting", "build",
     "category worth and observed share; the quality-estimate set"),
    ("Objective monitoring", "business", "Business alignment", "assess", "the discovery report's business context"),
    ("Objective monitoring", "distribution", "Distribution change detection", "judge", "C16, guidance only for now"),
    ("Agent testing and modeling", "significance", "Significance testing", "build",
     "aot-evals compare (McNemar, bootstrap)"),
    ("Agent testing and modeling", "noise-floor", "Noise floor and k", "build", "a baseline at k = 3 to 5"),
    ("Agent testing and modeling", "misclassification", "Misclassification analysis", "judge",
     "agreement: every disagreement with a cause"),
    ("Agent testing and modeling", "runner", "Test runner and isolated compute", "build",
     "aot-evals run, with invoke.isolate"),
]
STATES = ("done", "partial", "todo", "later", "n/a")


def _from_suite(ev: Evals) -> dict[str, tuple[str, str]]:
    """id -> (state, evidence), for what the suite itself shows."""
    from . import agreement, gates
    from .replay import records_dir

    a = ev.agent()
    inv = a.get("invoke") or {}
    cases = ev.cases(include_dropped=False)
    code = [c for c in cases if ev.checks_for_case(c, check_type="code")]
    base = ev.latest_run("baseline")
    by = agreement.per_labeller(ev)
    labellers = {k for people in by.values() for k in people}
    overlapped = sum(len(p) >= 2 for p in by.values())
    judges = gates._judge_checks(ev)
    cal = next((g for g in gates.evaluate(ev) if g.id == "C10"), None)
    comps = [m for m in ev.runs("candidate") if m.get("finished")]
    out: dict[str, tuple[str, str]] = {}

    def put(cid, state, why):
        out[cid] = (state, why)

    put("sandbox", "done" if inv.get("command") and (inv.get("isolate") or inv.get("seed")) else
        "partial" if inv.get("command") else "todo",
        "runs from its command" + (", isolated" if inv.get("isolate") else "") + (", seeded" if inv.get("seed") else "")
        if inv.get("command") else "no invoke.command yet")
    env_dir = ev.p("env")
    env_files = [p for p in env_dir.rglob("*") if p.is_file() and p.name != ".gitkeep"] if env_dir.exists() else []
    if env_files:
        put("fakes", "done", f"{len(env_files)} fake or fixture file(s) in env/")
    elif inv.get("seed"):
        put("fakes", "n/a", "the seed hook sets up the world; no fakes in env/")
    else:
        put("fakes", "todo", "nothing in env/ and no seed hook")
    put("replay", "done" if records_dir(inv) else "n/a", "replays " + records_dir(inv) if records_dir(inv)
        else "the agent runs live")
    put("seeded", "done" if inv.get("seed") and inv.get("observe") else "partial" if inv.get("observe") else "todo",
        "seed and observe hooks" if inv.get("seed") else "no seed hook")
    put("golden", "done" if len(cases) >= 10 else "partial" if cases else "todo",
        f"{len(cases)} cases in {len({c.get('category') for c in cases})} categories")
    put("deterministic", "done" if cases and len(code) == len(cases) else "partial" if code else "todo",
        f"{len(code)} of {len(cases)} cases have a code check")
    hold = sum((r.get("split") == "holdout") for r in agreement.load_labels(ev))
    put("holdouts", "done" if hold >= 5 else "partial" if hold else "todo", f"{hold} held-out labelled runs")
    put("grader-ui", "done" if by else "todo", f"{len(by)} runs labelled" if by else "aot-evals serve, not used yet")
    warm = sum(1 for _ in agreement.load_rulings(ev)) + overlapped
    put("calibration-set", "done" if warm >= 5 else "partial" if warm else "todo", f"{warm} settled runs")
    put("two-blind", "done" if overlapped >= 15 else "partial" if overlapped else "todo",
        f"{overlapped} runs labelled by two or more people")
    put("pool", "done" if len(labellers) >= 2 else "partial" if labellers else "todo",
        f"{len(labellers)} labeller(s)")
    put("judges", "n/a" if not judges else "done" if cal and cal.status == "met" else "partial",
        "no AI judges: every check is code" if not judges else (cal.info or cal.problems or [""])[0] if cal else "")
    put("qualitative", "n/a" if not judges else "done", f"{len(judges)} judge(s)")
    synth = sum(bool((c.get("provenance") or {}).get("synthetic")) for c in cases)
    drafts = len(list(ev.p("labels", "drafts").glob("*.json"))) if ev.p("labels", "drafts").exists() else 0
    put("synthetic", "partial" if synth or drafts else "todo", f"{synth} synthetic case(s), {drafts} draft(s)")
    put("engine", "done" if base else "todo", f"baseline {base['run_id']}" if base else "no baseline yet")
    put("change-scoping", "done" if base else "todo", "status compares everything with the baseline")
    put("ab", "done" if comps else "todo", f"{len(comps)} candidate run(s)")
    put("trace-monitoring", "later", "not automated yet")
    weighted = all(isinstance(c.get("observed_share"), (int, float)) and c.get("worth") for c in ev.categories())
    put("weighting", "done" if ev.categories() and weighted else "partial" if ev.categories() else "todo",
        "worth and share on every category" if weighted and ev.categories() else "some categories lack worth or share")
    put("business", "done" if ev.p("discovery.md").exists() else "todo", "discovery.md")
    put("distribution", "later", "not automated yet")
    put("significance", "done" if comps else "todo", "paired tests on every comparison")
    put("noise-floor", "done" if base and (base.get("k") or 0) >= 3 else "todo",
        f"k = {base.get('k')}" if base else "no baseline yet")
    res = load_json(agreement.result_path(ev)) or {}
    put("misclassification", "done" if res and not agreement.gate_problems(ev, res) else "partial" if res else "todo",
        f"{len(res.get('disagreements') or [])} disagreement(s) measured" if res else "not measured yet")
    isolated = bool(inv.get("isolate") or records_dir(inv))
    put("runner", "done" if base and isolated else "partial" if inv.get("command") else "todo",
        "isolated from the eval files" if isolated else "runs in the repository, beside the eval files "
        "(set invoke.isolate: true)")
    return out


def checklist(ev: Evals) -> list[dict]:
    report = {}
    path = ev.p("discovery.md")
    if path.exists():
        fm, _ = split_front_matter(path.read_text())
        report = fm.get("components") or {}
    suite = _from_suite(ev) if ev.exists() else {}
    rank = {"done": 3, "partial": 2, "later": 1, "todo": 0, "n/a": 0}
    out = []
    for group, cid, name, phase, how in COMPONENTS:
        st, why = suite.get(cid, ("todo", ""))
        r = report.get(cid)
        if isinstance(r, dict) and r.get("state") in STATES and rank[r["state"]] > rank.get(st, 0):
            st, why = r["state"], r.get("note") or why
        out.append({"group": group, "id": cid, "name": name, "phase": phase, "how": how, "state": st, "why": why})
    return out


def render(items: list[dict]) -> str:
    mark = {"done": "x", "partial": "~", "todo": " ", "later": "-", "n/a": "/"}
    lines, group = [], None
    for it in items:
        if it["group"] != group:
            group = it["group"]
            lines.append(f"\n{group}")
        lines.append(f"  [{mark[it['state']]}] {it['name']} ({it['phase']}) {it['why']}")
    lines.append("\n[x] done  [~] partly  [ ] not yet  [-] not automated yet  [/] doesn't apply")
    return "\n".join(lines).lstrip("\n")
