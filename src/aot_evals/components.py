"""The components of an agent's optimization loop, as a checklist, grouped by the part of an eval
each serves (estimators §1–§6; docs/v2-design.md §7).

An eval is an estimator with four parts: the estimand, the sampling design, the measurement model
and the decision rule. Around them sits what lets the agent run at all: the agent contract and a
sandbox. Every component of the loop serves one of those, so the list is grouped by them, each
component with the command that builds it and a status read from the agent's evals (2.0) or its
suite (1.x).

The Assess report may set a component's state before any eval exists (`components:` in
discovery.md's front matter, keyed by id); once the evals hold evidence, their own reading wins
wherever it says more than the report did. `aot-evals components` prints the list; `status
--json`, the checkpoint pages and the grader application carry it.
"""

from __future__ import annotations

from .repo import Evals
from .start import split_front_matter
from .util import ContractError, load_json

CONTRACT = "Agent contract and sandbox"
ESTIMAND = "Estimand"
DESIGN = "Sampling design"
MEASUREMENT = "Measurement model"
DECISION = "Decision rule"
PARTS = (CONTRACT, ESTIMAND, DESIGN, MEASUREMENT, DECISION)

# (part, id, name, how aot-evals covers it)
COMPONENTS = [
    (CONTRACT, "sandbox", "Harness and sandbox runtime",
     "the agent contract and invoke.isolate (references/agent-contract.md)"),
    (CONTRACT, "fakes", "Mock API services, staging accounts, a safe database",
     "fakes in env/, hashed into every run manifest"),
    (CONTRACT, "replay", "Record and replay", "aot-evals replay"),
    (CONTRACT, "seeded", "Self-hosted, seeded, realistic and anonymized data",
     "the seed and observe hooks; scrubbed cases"),
    (CONTRACT, "runner", "Test runner and isolated compute", "aot-evals run, with invoke.isolate"),
    (CONTRACT, "engine", "An eval engine that runs every eval", "aot-evals run, a baseline per eval"),
    (ESTIMAND, "business", "The decision each eval drives, and its owner", "estimand.decision in each eval.yaml"),
    (ESTIMAND, "boundaries", "Context boundaries: one eval end to end, one per component decided on separately",
     "agent.yaml components; aot-evals init --component (rule 3)"),
    (ESTIMAND, "weighting", "Use cases with their shares and the cost of a failure",
     "estimand.use_cases and weights (rule 2)"),
    (ESTIMAND, "distribution", "Distribution change detection",
     "shares measured again on a schedule (rule 26); not automated yet"),
    (DESIGN, "golden", "A quality set drawn at random from real traffic, with π",
     "aot-evals draw (rules 5, 6)"),
    (DESIGN, "handoff-frames", "Each component eval drawn from the handoffs it receives",
     "aot-evals handoffs, from end-to-end traces (rule 4)"),
    (DESIGN, "synthetic", "A bug-finding set against a coverage list", "pool: bug_finding cases; coverage.yaml"),
    (DESIGN, "holdouts", "Private holdouts", "the hash-assigned 20% holdout of labels"),
    (MEASUREMENT, "deterministic", "Code checks first, one counted check per failure mode",
     "checks/code/; measurement.failure_modes (rules 11, 12, 14)"),
    (MEASUREMENT, "judges", "Judges within max_inflation, from their catch and clean pass rates",
     "aot-evals calibrate (rule 13)"),
    (MEASUREMENT, "qualitative", "Qualitative dimensions", "judge specs in checks/judge/"),
    (MEASUREMENT, "grader-ui", "Each run graded like a test, with the reason", "aot-evals serve"),
    (MEASUREMENT, "calibration-set", "A calibration set first", "the warm-up on settled runs"),
    (MEASUREMENT, "two-blind", "Two blind labels per run", "overlaps in every labeller's queue"),
    (MEASUREMENT, "pool", "Graders sourced from customer and expert pools",
     "per-grader links (&labeller=NAME); people, not software"),
    (MEASUREMENT, "misclassification", "The whole eval held to people", "aot-evals agreement (rule 15)"),
    (MEASUREMENT, "noise-floor", "Trials per case from the variance split", "measurement.trials (rule 16)"),
    (DECISION, "significance", "A decision rule per eval, powered", "decision_rule; aot-evals plan (rule 7)"),
    (DECISION, "ab", "Paired comparisons of a changed agent", "aot-evals compare (rule 18)"),
    (DECISION, "change-scoping", "A component change gated on the end-to-end eval",
     "decision_rule.also_requires (rule 27)"),
    (DECISION, "trace-monitoring", "Trace monitoring", "not automated yet"),
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
    base_runs = ev.baseline_runs()
    base = base_runs[-1] if base_runs else None
    by = agreement.per_labeller(ev)
    labellers = {k for people in by.values() for k in people}
    overlapped = sum(len(p) >= 2 for p in by.values())
    judges = gates._judge_checks(ev)
    gs = {g.id: g for g in gates.evaluate(ev)}
    cal = gs.get("C10")
    compared = gs.get("C13") is not None and gs["C13"].status == "met"
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
    put("engine", "done" if base else "todo",
        f"baseline {' + '.join(m['run_id'] for m in base_runs)}" if base else "no baseline yet")
    put("change-scoping", "done" if compared else "partial" if base else "todo",
        "a change was compared and its moved cases can be labelled alone" if compared else
        "status names every change since the baseline; no change has been compared yet" if base else
        "needs a baseline")
    put("ab", "done" if compared else "partial" if comps else "todo",
        f"{len(comps)} candidate run(s)" + ("" if compared or not comps else ", the latest not compared yet"))
    put("trace-monitoring", "later", "not automated yet")
    weighted = all(isinstance(c.get("observed_share"), (int, float)) and c.get("worth") for c in ev.categories())
    put("weighting", "done" if ev.categories() and weighted else "partial" if ev.categories() else "todo",
        "worth and share on every category" if weighted and ev.categories() else "some categories lack worth or share")
    put("business", "done" if ev.discovery_path().exists() else "todo", "discovery.md")
    put("distribution", "later", "not automated yet")
    put("significance", "done" if compared else "todo",
        "the latest comparison has its paired test" if compared else "no comparison yet")
    ks = sorted({m.get("k") or 0 for m in base_runs})
    put("noise-floor", "done" if base_runs and min(ks) >= 3 else "partial" if base_runs else "todo",
        (f"k = {', '.join(map(str, ks))}: 3 to 5 trials per case shows how much results move by chance; "
         "5 narrows the band" if base_runs else "no baseline yet"))
    res = load_json(agreement.result_path(ev)) or {}
    put("misclassification", "done" if res and not agreement.gate_problems(ev, res) else "partial" if res else "todo",
        f"{len(res.get('disagreements') or [])} disagreement(s) measured" if res else "not measured yet")
    isolated = bool(inv.get("isolate") or records_dir(inv))
    put("runner", "done" if base and isolated else "partial" if inv.get("command") else "todo",
        "isolated from the eval files" if isolated else "runs in the repository, beside the eval files "
        "(set invoke.isolate: true)")
    put(*_boundaries(ev, {}))
    put("handoff-frames", "n/a", "a 1.x suite is one eval; `migrate --to 2`, then a component eval per boundary")
    return out


def _boundaries(agent_dir: Evals, units: dict[str, str]) -> tuple[str, str, str]:
    """agent.yaml's components, each placed (rule 3), and whether each that earns an eval has one."""
    from . import boundaries

    agent = agent_dir.agent()
    if "components" not in agent:
        return ("boundaries", "todo", "agent.yaml lists no components: name each subagent, route and "
                "shared step, or `components: []` for one context")
    rows = boundaries.plan(agent)
    if not rows:
        return ("boundaries", "done", "one context: the end-to-end eval covers it")
    unknown = [r["id"] for r in rows if r["placement"] == boundaries.UNKNOWN]
    owed = [r["id"] for r in rows if r["placement"] == boundaries.OWN_EVAL and r["id"] not in units]
    word = {boundaries.OWN_EVAL: "own eval", boundaries.USE_CASE_GATE: "use case gate",
            boundaries.USE_CASE: "use case", boundaries.CHECKS: "checks end to end", boundaries.UNKNOWN: "?"}
    why = ", ".join(f"{r['id']}: {word[r['placement']]}" for r in rows)
    if unknown:
        return ("boundaries", "partial", f"{why}; not placed yet: {', '.join(unknown)}")
    if owed:
        return ("boundaries", "partial", f"{why}; no eval yet for {', '.join(owed)} "
                f"(aot-evals init --component {owed[0]})")
    return ("boundaries", "done", why)


def _from_evals(ev: Evals) -> dict[str, tuple[str, str]]:
    """id -> (state, evidence), read from a 2.0 agent's evals (docs/v2-design.md §1)."""
    from . import agreement
    from .calibrate import is_current, load_calibration
    from .design import case_status
    from .judges import load_spec
    from .replay import records_dir

    evals = ev.evals()
    out: dict[str, tuple[str, str]] = {}

    def put(cid, state, why):
        out[cid] = (state, why)

    def share(pred) -> tuple[list[str], list[str]]:
        yes = [e.id for e in evals if pred(e)]
        return yes, [e.id for e in evals if e.id not in yes]

    def state(yes, no) -> str:
        return "done" if yes and not no else "partial" if yes else "todo"

    def names(ids):
        return ", ".join(ids) or "none"

    inv = ev.agent().get("invoke") or {}
    specs = {e.id: e.spec() for e in evals}
    units = {}
    for e in evals:
        unit = specs[e.id].part("estimand").get("unit") or {}
        if isinstance(unit, dict) and unit.get("kind") == "component":
            units[unit.get("component")] = e.id
    wired = [e.id for e in evals if (e.agent().get("invoke") or {}).get("command")]
    put("sandbox", state(wired, [e.id for e in evals if e.id not in wired]),
        f"runs from its command: {names(wired)}" + (", isolated" if inv.get("isolate") else ""))
    env_dir = ev.p("env")
    env_files = [p for p in env_dir.rglob("*") if p.is_file() and p.name != ".gitkeep"] if env_dir.exists() else []
    put("fakes", "done" if env_files else "n/a" if inv.get("seed") else "todo",
        f"{len(env_files)} fake or fixture file(s) in env/, shared by every eval" if env_files else
        "the seed hook sets up the world" if inv.get("seed") else "nothing in env/ and no seed hook")
    put("replay", "done" if records_dir(inv) else "n/a", "replays " + records_dir(inv) if records_dir(inv)
        else "the agent runs live")
    put("seeded", "done" if inv.get("seed") and inv.get("observe") else "partial" if inv.get("observe") else "todo",
        "seed and observe hooks" if inv.get("seed") else "no seed hook")
    isolated = bool(inv.get("isolate") or records_dir(inv))
    put("runner", "done" if isolated else "partial" if inv.get("command") else "todo",
        "isolated from the eval files" if isolated else "runs in the repository, beside the eval files "
        "(set invoke.isolate: true)")
    yes, no = share(lambda e: bool(e.baseline_runs()))
    put("engine", state(yes, no), f"a baseline in {names(yes)}" + (f"; none in {names(no)}" if no else ""))

    def clean(e, prefix):
        return not any(i.field.startswith(prefix) for i in (*specs[e.id].missing, *specs[e.id].invalid))

    yes, no = share(lambda e: clean(e, "estimand.decision"))
    put("business", state(yes, no), f"a decision and owner in {names(yes)}"
        + (f"; missing in {names(no)}" if no else ""))
    put(*_boundaries(ev, units))
    yes, no = share(lambda e: clean(e, "estimand.use_cases") and clean(e, "estimand.weights"))
    put("weighting", state(yes, no), f"use cases with shares and weights in {names(yes)}"
        + (f"; incomplete in {names(no)}" if no else ""))
    put("distribution", "later", "shares are measured again by hand (rule 26)")

    statuses = {}
    for e in evals:
        try:
            statuses[e.id] = [case_status(e, c) for c in e.cases(include_dropped=False)]
        except ContractError:  # a case file that isn't JSON: validate names it
            statuses[e.id] = []
    yes, no = share(lambda e: any(x["counts"] for x in statuses[e.id]))
    put("golden", state(yes, no), "; ".join(f"{e.id}: {sum(x['counts'] for x in statuses[e.id])} drawn"
                                            for e in evals) or "no evals yet")
    comps = [e for e in evals if e.id in units.values()]
    if not comps:
        put("handoff-frames", "n/a", "no component evals")
    else:
        def has_frame(e):
            frame = (specs[e.id].part("estimand").get("population") or {}).get("frame")
            entry = next((x for x in ev.exports() if isinstance(x, dict) and x.get("id") == frame), None)
            return bool(entry and isinstance(entry.get("handoffs"), dict))
        yes = [e.id for e in comps if has_frame(e)]
        no = [e.id for e in comps if e.id not in yes]
        put("handoff-frames", state(yes, no), f"handoff frames in {names(yes)}"
            + (f"; none yet in {names(no)} (aot-evals --eval {no[0]} handoffs)" if no else ""))
    bf = {e.id: sum(x["pool"] == "bug_finding" for x in statuses[e.id]) for e in evals}
    put("synthetic", "partial" if any(bf.values()) else "todo",
        "; ".join(f"{k}: {v} bug-finding" for k, v in bf.items()) or "no evals yet")
    labels = {}
    for e in evals:
        try:
            labels[e.id] = agreement.load_labels(e)
        except Exception:
            labels[e.id] = []
    hold = sum(r.get("split") == "holdout" for rows in labels.values() for r in rows)
    put("holdouts", "done" if hold >= 5 else "partial" if hold else "todo", f"{hold} held-out labelled runs")

    counted, code, judges = 0, 0, []
    for e in evals:
        for fm in e.failure_modes():
            cid = fm.get("check")
            if not isinstance(cid, str):
                continue
            counted += 1
            t = e.check_type(cid)
            code += t == "code"
            if t == "judge":
                judges.append((e, cid))
    put("deterministic", "done" if counted and code == counted else "partial" if code else "todo",
        f"{code} of {counted} counted checks are code")
    current = 0
    for e, cid in judges:
        try:
            spec = load_spec(e.judge_check_path(cid))
            cal = load_calibration(e, spec)
            current += bool(cal and is_current(e, spec, cal) and cal.get("status") == "calibrated")
        except Exception:
            continue
    put("judges", "n/a" if not judges else "done" if current == len(judges) else "partial",
        "no AI judges: every counted check is code" if not judges else
        f"{current} of {len(judges)} counted judge(s) calibrated; the report reads each against max_inflation")
    put("qualitative", "n/a" if not judges else "done", f"{len(judges)} judge(s)")
    by = {}
    for e in evals:
        try:
            by.update({(e.id, k): v for k, v in agreement.per_labeller(e).items()})
        except Exception:
            continue
    labellers = {k for people in by.values() for k in people}
    overlapped = sum(len(p) >= 2 for p in by.values())
    put("grader-ui", "done" if by else "todo", f"{len(by)} runs labelled" if by else "aot-evals serve, not used yet")
    put("calibration-set", "done" if overlapped >= 5 else "partial" if overlapped else "todo",
        f"{overlapped} runs labelled by two or more people")
    put("two-blind", "done" if overlapped >= 15 else "partial" if overlapped else "todo",
        f"{overlapped} runs labelled by two or more people")
    put("pool", "done" if len(labellers) >= 2 else "partial" if labellers else "todo", f"{len(labellers)} labeller(s)")
    measured = [e.id for e in evals if load_json(agreement.result_path(e))]
    put("misclassification", state(measured, [e.id for e in evals if e.id not in measured]),
        f"held to people in {names(measured)}" if measured else "no eval held to people yet (aot-evals agreement)")
    ks = sorted({m.get("k") or 0 for e in evals for m in e.baseline_runs()})
    put("noise-floor", "done" if ks and min(ks) >= 3 else "partial" if ks else "todo",
        f"k = {', '.join(map(str, ks))}" if ks else "no baseline yet")
    yes, no = share(lambda e: not specs[e.id].blocked("decision"))
    put("significance", state(yes, no), f"a complete decision rule in {names(yes)}"
        + (f"; incomplete in {names(no)}" if no else ""))
    compared = [e.id for e in evals if e.p("report", "comparisons").is_dir()
                and any(e.p("report", "comparisons").iterdir())]
    put("ab", "done" if compared else "partial" if any(e.runs("candidate") for e in evals) else "todo",
        f"compared in {names(compared)}" if compared else "no comparison yet")
    if not comps:
        put("change-scoping", "n/a", "no component evals: every change is decided end to end")
    else:
        yes = [e.id for e in comps if not any(i.field.startswith("decision_rule.also_requires")
                                              for i in (*specs[e.id].missing, *specs[e.id].invalid))]
        no = [e.id for e in comps if e.id not in yes]
        put("change-scoping", state(yes, no), f"gated on the end-to-end eval: {names(yes)}"
            + (f"; not yet: {names(no)}" if no else ""))
    put("trace-monitoring", "later", "not automated yet")
    return out


def checklist(ev: Evals) -> list[dict]:
    report = {}
    path = ev.discovery_path()
    if path.exists():
        fm, _ = split_front_matter(path.read_text())
        report = fm.get("components") or {}
    if not ev.exists():
        suite = {}
    elif ev.has_evals and not ev.has_v1_suite:
        suite = _from_evals(ev)
    else:
        suite = _from_suite(ev)
    rank = {"done": 3, "partial": 2, "later": 1, "todo": 0, "n/a": 0}
    out = []
    for part, cid, name, how in COMPONENTS:
        st, why = suite.get(cid, ("todo", ""))
        r = report.get(cid)
        if isinstance(r, dict) and r.get("state") in STATES and rank[r["state"]] > rank.get(st, 0):
            st, why = r["state"], r.get("note") or why
        out.append({"group": part, "part": part, "id": cid, "name": name, "how": how, "state": st, "why": why})
    return out


def render(items: list[dict]) -> str:
    mark = {"done": "x", "partial": "~", "todo": " ", "later": "-", "n/a": "/"}
    lines, group = [], None
    for it in items:
        if it["group"] != group:
            group = it["group"]
            lines.append(f"\n{group}")
        lines.append(f"  [{mark[it['state']]}] {it['name']}: {it['why']}")
    lines.append("\n[x] done  [~] partly  [ ] not yet  [-] not automated yet  [/] doesn't apply")
    return "\n".join(lines).lstrip("\n")
