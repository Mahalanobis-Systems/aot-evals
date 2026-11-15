"""The three phases, how far each eval's number can be trusted, and what changed since its
baseline (docs/method.md §12).

The user meets the method as three phases, each settling some of an eval's four parts
(estimators §1–§6):

- **Assess** settles the estimand: what the agent is for, where its evals go (the context
  boundaries), its use cases with their shares and costs, and the decision each eval drives.
- **Build** settles the sampling design, the checks of the measurement model and the decision
  rule, around the agent contract: the agent runs from a command, the quality set is drawn, each
  failure mode has one counted check, and a baseline has run under the current spec.
- **Judge** settles the rest of the measurement model: the error rates. People label whole runs,
  judges are calibrated, and the eval is held to people.

Trust is per eval, and is read from the same report.json the report writes:

- **untested**: no number yet (no baseline under the current spec, or θ̂ null with its reason);
- **provisional**: a number, but one of these is still open: the spec is incomplete, a counted
  judge does not count yet, the eval is not held to people, or the quality set is smaller than
  the decision rule needs (aot-evals plan);
- **trusted**: every spec field filled, every counted judge within `max_inflation`, the eval
  against people at its floors, and a quality set the decision rule's power calls for.

`aot-evals status` prints it and `status --json` carries it.
"""

from __future__ import annotations

from pathlib import Path

from .repo import Eval, Evals
from .util import ContractError, git_commit_info, git_same_tree, load_json

PHASES = {  # id: (name, the parts it settles, what it does)
    "assess": ("Assess", ("estimand",),
               "what the agent is for, where its evals go, its use cases and what a failure in each costs"),
    "build": ("Build", ("agent contract", "sampling design", "measurement model: the checks", "decision rule"),
              "the agent wired to run, the quality set drawn, a check per failure mode, the decision rule, "
              "a baseline"),
    "judge": ("Judge", ("measurement model: the error rates",),
              "people label whole runs, judges are calibrated, and the eval is held to people"),
}
ORDER = tuple(PHASES)
LEVELS = ("untested", "provisional", "trusted")
MEASURED_PARTS = ("estimand", "design", "measurement")
PART_WORD = {"estimand": "estimand", "design": "sampling design", "measurement": "measurement model",
             "decision_rule": "decision rule"}


def _phase(pid: str, why: str, nxt: str | None) -> dict:
    name, parts, about = PHASES[pid]
    return {"id": pid, "name": name, "settles": list(parts), "about": about, "why": why, "next": nxt,
            "done": [PHASES[p][0] for p in ORDER[:ORDER.index(pid)]]}


def _comparison_flip_rate(ev: Eval) -> float | None:
    """The flip rate of the newest saved comparison, the only measured input a paired rule's plan
    has before someone passes --flip-rate."""
    d = ev.p("report", "comparisons")
    if not d.is_dir():
        return None
    rows = [load_json(p) or {} for p in d.glob("*.json")]
    rows = [r for r in rows if not r.get("refused")]
    rows.sort(key=lambda r: r.get("generated") or "")
    for r in reversed(rows):
        v = (r.get("flips") or {}).get("flip_rate")
        if isinstance(v, (int, float)) and v > 0:
            return float(v)
    return None


def _sized(ev: Eval) -> tuple[bool | None, str]:
    """Whether the quality set holds the cases the decision rule's power calls for (rule 7)."""
    from . import plan as plan_mod

    try:
        p = plan_mod.plan(ev, flip_rate=_comparison_flip_rate(ev))
    except (ContractError, ValueError, ZeroDivisionError):
        return None, "the plan could not be computed (aot-evals plan)"
    head = p.get("headline") or {}
    if head.get("need") is None:
        return None, f"the plan can't size the decision rule yet: {head.get('reason') or 'unknown need'}"
    short = [r for r in p["rows"] if r["pool"] == "quality" and r.get("target") is not None
             and r["drawn"] < r["target"] and r["status"] != "out_of_scope"]
    if short:
        have = sum(r["drawn"] for r in p["rows"] if r["pool"] == "quality")
        want = p["quality_set"].get("total")
        names = ", ".join(f"{r['use_case']} {r['drawn']}/{r['target']}" for r in short)
        return False, (f"the quality set holds {have} drawn cases where the decision rule needs about {want} "
                       f"({names}): aot-evals plan --write, then aot-evals draw")
    return True, "the quality set holds what the decision rule's power calls for"


def eval_trust(ev: Eval, report: dict | None = None) -> dict:
    """One eval's phase and trust level, each with its reasons, read from report.json v2."""
    from . import report_v2

    spec = ev.spec()
    out = {"eval": spec.eval_id, "level": "untested", "why": [], "theta": None, "ci": None,
           "conditions": {"spec": spec.complete, "estimate": False, "judges": None, "people": None,
                          "sized": None}}
    runs = report_v2.default_runs(ev)
    if not runs:
        out["why"].append(f"no baseline yet: aot-evals --eval {spec.eval_id} run --purpose baseline")
        out["phase"] = _phase("build", "no baseline has run", _build_next(ev, spec))
        return out
    try:
        r = report if report is not None else report_v2.build(ev, runs)
    except ContractError as e:
        out["why"].append(str(e))
        out["phase"] = _phase("build", "the report could not be read", _build_next(ev, spec))
        return out
    est = r.get("estimate") or {}
    if r.get("refused") or est.get("theta") is None:
        why = r.get("refused") or est.get("null_reason") or "θ̂ is null"
        out["why"].append(why)
        out["phase"] = _phase("build", "no number under the current spec yet", _build_next(ev, spec))
        return out
    out["conditions"]["estimate"] = True
    out["theta"], out["ci"] = est.get("theta"), est.get("ci")
    out["level"] = "provisional"
    why = out["why"]
    if not spec.complete:
        first = (spec.missing or spec.invalid)[0]
        why.append(f"the spec lacks {len(spec.missing)} and has {len(spec.invalid)} invalid field(s), first "
                   f"{first.field}: {first.why} (aot-evals validate)")
    meas = r.get("measurement") or {}
    judge_gates = [g for g in meas.get("gates") or [] if g.get("id") in ("judge_floor", "judge_calibration")]
    out["conditions"]["judges"] = not judge_gates
    for g in judge_gates:
        why.append(g.get("detail") or g["id"])
    people = meas.get("eval_vs_people") or {}
    floor = people.get("floor") or {}
    status = floor.get("status") or "unmeasured"
    out["conditions"]["people"] = status == "meets" and not people.get("stale")
    if status == "unmeasured" or not people.get("labels"):
        why.append("the eval is not held to people yet: label whole runs (aot-evals agreement label queue, or "
                   "aot-evals serve), then aot-evals agreement")
    elif people.get("stale"):
        why.append("the eval against people is stale: aot-evals agreement regrade")
    elif status != "meets":
        reasons = floor.get("reasons") or [f"the eval against people is {status}"]
        why.append("eval against people: " + "; ".join(reasons))
    sized, note = _sized(ev)
    out["conditions"]["sized"] = sized
    if not sized:
        why.append(note)
    if not why:
        out["level"] = "trusted"
        why.append("every spec field filled, every counted judge within max_inflation, the eval held to people "
                   "at its floors, and the quality set the decision rule needs")
    if out["conditions"]["judges"] and out["conditions"]["people"]:
        out["phase"] = _phase("judge", "the error rates are measured; the eval is held to people",
                              None if out["level"] == "trusted" else why[0])
    else:
        out["phase"] = _phase("judge", "a baseline has run under the current spec; the error rates are next",
                              why[0])
    return out


def _build_next(ev: Eval, spec) -> str:
    """Build's next step for one eval, in the order the parts need it."""
    sid = spec.eval_id
    blocking = [i for i in (*spec.missing, *spec.invalid) if {"run", "draw", "estimate"} & set(i.blocks)]
    if blocking:
        return f"fill {blocking[0].field} in {sid}/eval.yaml ({blocking[0].why}); aot-evals validate lists the rest"
    try:
        from .design import case_status

        cases = ev.cases(include_dropped=False)
        drawn = sum(case_status(ev, c)["counts"] for c in cases)
    except ContractError:
        cases, drawn = [], 0
    if not drawn:
        return f"draw the quality set: aot-evals --eval {sid} plan --write, then aot-evals --eval {sid} draw"
    from .screen import passes

    if any(not passes(c.get("screen")) for c in cases):
        return f"screen the cases: aot-evals --eval {sid} screen, and a person reads them (--read-by NAME)"
    return f"commit, then run the baseline: aot-evals --eval {sid} run --purpose baseline"


def changes(ev: Eval) -> list[dict]:
    """What changed since the newest baseline run, each with what it invalidates and the way back."""
    from .spec import part_hashes

    base = ev.baseline_runs()
    if not base:
        return []
    newest = base[-1]
    out = []
    now = part_hashes(ev.spec(), ev)
    then = newest.get("spec_sha") or {}
    revised = [p for p in MEASURED_PARTS if then.get(p) != now.get(p)]
    if revised:
        out.append({"kind": "revision", "parts": revised,
                    "what": f"the {' and '.join(PART_WORD[p] for p in revised)} changed since the baseline: a "
                            "revision, so old and new numbers are different quantities (estimators §9)",
                    "next": f"run the baseline again under the current spec: aot-evals --eval {ev.id} run "
                            "--purpose baseline"})
    elif then.get("decision_rule") != now.get("decision_rule"):
        out.append({"kind": "decision_rule", "parts": ["decision_rule"],
                    "what": "the decision rule changed since the baseline",
                    "next": f"commit eval.yaml (or aot-evals --eval {ev.id} log --kind decision \"why\") before "
                            "the candidate runs, or the comparison refuses it (rule 21)"})
    root = _agent_cwd(ev)
    if root is not None and newest.get("agent_commit"):
        info = git_commit_info(root, exclude=ev.evals_dir)
        if info.get("dirty"):
            out.append({"kind": "agent-uncommitted", "parts": [],
                        "what": "the agent has uncommitted changes",
                        "next": "commit the agent before running: a run of an uncommitted build can't be compared"})
        elif info.get("commit") and info["commit"] != newest["agent_commit"] and \
                git_same_tree(root, info["commit"], newest["agent_commit"], exclude=ev.evals_dir) is not True:
            out.append({"kind": "agent", "parts": [],
                        "what": f"the agent changed since the baseline ({newest['agent_commit'][:7]} → "
                                f"{info['commit'][:7]})",
                        "next": f"run a candidate with one declared variable, then compare: aot-evals --eval {ev.id} "
                                f"run --purpose candidate --variable KIND=VALUE; aot-evals --eval {ev.id} compare"})
    finished = newest.get("finished") or ""
    cands = [m for m in ev.runs("candidate") if m.get("finished") and m["finished"] > finished]
    compared = set()
    d = ev.p("report", "comparisons")
    if d.is_dir():
        for p in d.glob("*.json"):
            compared.update((load_json(p) or {}).get("candidate_runs") or [])
    fresh = [m["run_id"] for m in cands if m["run_id"] not in compared]
    if fresh:
        out.append({"kind": "candidate", "parts": [],
                    "what": f"candidate {fresh[-1]} has run and has not been compared",
                    "next": f"aot-evals --eval {ev.id} compare --candidate {fresh[-1]}, then have people label "
                            "what moved (aot-evals agreement label queue --changed)"})
    return out


def _agent_cwd(ev: Eval) -> Path | None:
    inv = ev.agent().get("invoke") or {}
    cwd = inv.get("cwd") or "."
    p = (ev.repo_root / cwd).resolve()
    return p if p.exists() else None


def summary(agent_dir: Evals) -> dict:
    """The agent system's phase (its earliest eval's), each eval's trust, changes and next step."""
    discovered = agent_dir.discovery_path().exists()
    if not agent_dir.exists() or not agent_dir.has_evals:
        if discovered:
            ph = _phase("build", "the discovery report is written; no eval yet",
                        "aot-evals build: the end-to-end eval, and one per component that earns one")
        else:
            ph = _phase("assess", "no discovery report yet",
                        "run the assessment: /aot-evals:start in Claude Code")
        return {"agent": str(agent_dir.root), "phase": ph, "discovery_report": discovered, "evals": []}
    rows = []
    for ev in agent_dir.evals():
        t = eval_trust(ev)
        t["changes"] = changes(ev)
        if t["changes"]:
            t["phase"]["next"] = t["changes"][0]["next"]
        rows.append(t)
    earliest = min(rows, key=lambda t: ORDER.index(t["phase"]["id"]))
    ph = dict(earliest["phase"])
    ph["why"] = f"{earliest['eval']}: {ph['why']}"
    return {"agent": str(agent_dir.root), "phase": ph, "discovery_report": discovered, "evals": rows}


def render(s: dict) -> str:
    ph = s["phase"]
    lines = [f"agent at {s['agent']}",
             f"Phase: {ph['name']}, which settles the {', '.join(ph['settles'])} ({ph['why']})"]
    if ph["done"]:
        lines[-1] += f"; done: {', '.join(ph['done'])}"
    for t in s["evals"]:
        theta = ""
        if t["theta"] is not None:
            ci = t.get("ci") or [None, None]
            lo = f"{ci[0]:.1%}" if isinstance(ci[0], (int, float)) else "?"
            hi = f"{ci[1]:.1%}" if len(ci) > 1 and isinstance(ci[1], (int, float)) else "?"
            theta = f"  θ̂ {t['theta']:.1%} [{lo}, {hi}]"
        lines.append(f"\n  {t['eval']}: {t['phase']['name']}, {t['level']}{theta}")
        for w in t["why"]:
            lines.append(f"    - {w}")
        for c in t.get("changes") or []:
            lines.append(f"    changed: {c['what']}")
            lines.append(f"      → {c['next']}")
        nxt = t["phase"].get("next")
        if nxt and nxt not in t["why"]:
            lines.append(f"    next: {nxt}")
        elif nxt:
            lines.append("    next: the first item above")
    if not s["evals"] and ph.get("next"):
        lines.append(f"next: {ph['next']}")
    return "\n".join(lines)
