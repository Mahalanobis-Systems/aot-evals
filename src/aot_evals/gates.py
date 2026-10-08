"""Command exit gates (docs/method.md §4): which command's gate is unmet, and what clears it.

Each gate returns a status:
- `met` / `unmet`;
- `not_applicable`: the gate has nothing to judge (no judge checks, so C9-C11 do not apply);
- `not_implemented`: the command is guidance only for now (C16, C17; docs/method.md §4). These
  never block a later command.

A command refuses to run while a predecessor's gate is unmet (`require`), naming the gate and
the command that clears it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from . import allocate as allocate_mod
from .checks import declares_agent_report
from .repo import ALL_CATEGORIES, CHECK_TYPES, SETS, WORTHS, Evals
from .screen import passes as screen_passes
from .scrub import scan
from .util import (
    ContractError,
    git,
    git_adding_commit,
    git_adding_commits,
    git_strictly_before,
    git_untracked_or_modified,
)

COMMANDS = [
    # id, command, skill, what clears it
    ("C0", "import", "scope"),
    ("C1", "inventory", "scope"),
    ("C2", "taxonomy", "scope"),
    ("C3", "categorize", "scope"),
    ("C4", "decompose", "scope"),
    ("C5", "allocate", "build"),
    ("C6", "author", "build"),
    ("C7", "screen", "build"),
    ("C8", "checks", "build"),
    ("C9", "label", "calibrate"),
    ("C10", "calibrate", "calibrate"),
    ("C11", "reliability", "calibrate"),
    ("C12", "baseline", "run"),
    ("C13", "compare", "run"),
    ("C14", "coverage", "run"),
    ("C15", "redundancy", "run"),
    ("C16", "drift", "run"),
    ("C17", "online", "run"),
    ("C18", "report", "report"),
]
COMMAND_BY_ID = {c[0]: c for c in COMMANDS}
NOT_IMPLEMENTED = {"C16", "C17"}
# Uncalibrated judges may run but never count toward headline numbers (C10, G3), so the judge
# gates do not block a baseline.
NON_BLOCKING = NOT_IMPLEMENTED | {"C9", "C10", "C11"}

REQUIRED_AGENT_FIELDS = ("id", "surface", "triggers", "instructions", "tools", "harness",
                         "models", "version_history", "stable_window", "invoke")
OTHER_IDS = ("other", "misc", "uncategorized", "uncategorised")


@dataclass
class Gate:
    id: str
    status: str  # met | unmet | not_applicable | not_implemented
    problems: list[str] = field(default_factory=list)
    info: list[str] = field(default_factory=list)

    @property
    def command(self) -> str:
        return COMMAND_BY_ID[self.id][1]

    @property
    def skill(self) -> str:
        return COMMAND_BY_ID[self.id][2]

    def as_dict(self) -> dict:
        return {"id": self.id, "command": self.command, "skill": self.skill,
                "status": self.status, "problems": self.problems, "info": self.info}


def _gate(gid: str, problems: list[str], info: list[str] | None = None) -> Gate:
    return Gate(gid, "unmet" if problems else "met", problems, info or [])


# ---- C0-C4: scope ---------------------------------------------------------------------------

def c0(ev: Evals) -> Gate:
    exports = ev.exports()
    if not exports:
        return _gate("C0", ["data/export.manifest.json has no exports; import one "
                            "(aot-evals import <file> --source ... --query ... --window ...)"])
    problems = []
    for e in exports:
        missing = [k for k in ("id", "source", "query", "window", "date") if not e.get(k)]
        if missing:
            problems.append(f"export {e.get('id', '?')}: missing {', '.join(missing)}")
        if not isinstance(e.get("rows"), int):
            problems.append(f"export {e.get('id', '?')}: row count unknown")
    return _gate("C0", problems, [f"{len(exports)} export(s)"])


def c1(ev: Evals) -> Gate:
    a = ev.agent()
    if not a:
        return _gate("C1", ["agent.yaml missing or empty"])
    problems = [f"agent.yaml: {k} missing" for k in REQUIRED_AGENT_FIELDS if not a.get(k)]
    sw = a.get("stable_window") or {}
    if a.get("stable_window") and not (sw.get("since") and sw.get("evidence")):
        problems.append("agent.yaml: stable_window needs `since` and `evidence`")
    models = a.get("models") or {}
    if models and not isinstance(models, dict):
        problems.append("agent.yaml: models must map each call site to the model id it uses")
    elif models and any(not v for v in models.values()):
        problems.append("agent.yaml: a call site has no model id")
    if a.get("models") and not a.get("models_evidence"):
        problems.append("agent.yaml: models_evidence missing (how the model per call site was "
                        "observed: traces, not config)")
    if not (a.get("invoke") or {}).get("command"):
        problems.append("agent.yaml: invoke.command missing")
    cwd = (a.get("invoke") or {}).get("cwd", ".")
    if not (ev.repo_root / str(cwd)).is_dir():
        problems.append(f"agent.yaml: invoke.cwd {cwd!r} is not a directory under the repository "
                        f"root {ev.repo_root} (relative paths start there)")
    ok_run = any((m.get("counts") or {}).get("ok", 0) > 0 for m in ev.runs())
    if not ok_run:
        problems.append("the agent has not yet run end to end from its command "
                        "(aot-evals run --purpose smoke --question '...')")
    return _gate("C1", problems)


def taxonomy_problems(ev: Evals) -> list[str]:
    """Shared by C2 and G5."""
    t = ev.taxonomy()
    if not t:
        return ["taxonomy.yaml missing or empty"]
    problems = []
    src = t.get("source")
    if not src or src == "MISSING":
        problems.append("taxonomy.yaml: no source document named")
    else:
        text = src if isinstance(src, str) else " ".join(str(v) for v in src.values())
        if "evals/cases" in text or text.strip().startswith("cases/"):
            problems.append("taxonomy.yaml: the source is the suite's own cases; coverage "
                            "against it is always 100%")
        if isinstance(src, dict) and src.get("derived_from_cases"):
            problems.append("taxonomy.yaml: declared derived_from_cases")
    if not t.get("read_on"):
        problems.append("taxonomy.yaml: read_on (date the source was read) missing")
    entries = t.get("entries") or []
    if not entries:
        problems.append("taxonomy.yaml: no entries")
    elif any(not e.get("id") for e in entries):
        problems.append("taxonomy.yaml: every entry needs an id")

    in_git = git(["rev-parse", "--is-inside-work-tree"], ev.repo_root) == "true"
    rel_tax = str(ev.p("taxonomy.yaml").relative_to(ev.repo_root))
    if not in_git:
        problems.append("not a git repository: cannot show taxonomy.yaml was committed before "
                        "the first case")
    else:
        tax_commit = git_adding_commit(ev.repo_root, rel_tax)
        if tax_commit is None:
            problems.append("taxonomy.yaml is not committed; commit it before any case")
        else:
            added = git_adding_commits(ev.repo_root, str(ev.p("cases").relative_to(ev.repo_root)))
            case_commits = {added.get(str(p.relative_to(ev.repo_root))) for p in ev.case_paths()} - {None}
            early = [c for c in case_commits if not git_strictly_before(ev.repo_root, tax_commit, c)]
            if early:
                problems.append(f"taxonomy.yaml was not committed before the first case (cases added "
                                f"in {sorted(c[:8] for c in early)}, taxonomy in {tax_commit[:8]})")
    return problems


def c2(ev: Evals) -> Gate:
    return _gate("C2", taxonomy_problems(ev))


def c3(ev: Evals) -> Gate:
    cats = ev.categories()
    if not cats:
        return _gate("C3", ["categories.yaml has no categories"])
    problems = []
    total = 0.0
    other_share = 0.0
    for c in cats:
        cid = c.get("id", "?")
        for k in ("id", "definition", "example"):
            if not c.get(k):
                problems.append(f"category {cid}: {k} missing")
        if c.get("worth") not in WORTHS:
            problems.append(f"category {cid}: worth must be one of {WORTHS}")
        if not isinstance(c.get("simple"), bool):
            problems.append(f"category {cid}: simple must be true or false")
        if c.get("simple") and not c.get("heuristic"):
            problems.append(f"category {cid}: a simple category needs the heuristic that "
                            "identifies it")
        if not isinstance(c.get("cost"), dict) or not c.get("cost"):
            problems.append(f"category {cid}: cost matrix row missing")
        share = c.get("observed_share")
        if not isinstance(share, (int, float)):
            problems.append(f"category {cid}: observed_share not measured")
        else:
            total += share
            if cid in OTHER_IDS or c.get("other"):
                other_share += share
        if not c.get("share_source"):
            problems.append(f"category {cid}: share_source (export id the share was counted "
                            "from) missing")
    if cats and not problems and abs(total - 1.0) > 0.02:
        problems.append(f"observed shares sum to {total:.3f}, not 1")
    if other_share >= 0.10:
        problems.append(f"'Other' is {other_share:.1%} of traffic; must be under 10%")
    return _gate("C3", problems, [f"{len(cats)} categories"])


def c4(ev: Evals) -> Gate:
    fms = ev.failure_modes()
    cats = {c.get("id"): c for c in ev.categories()}
    if not fms:
        return _gate("C4", ["failure_modes.yaml has no failure modes"])
    problems = []
    for fm in fms:
        fid = fm.get("id", "?")
        fcats = fm.get("categories") or []
        if not fcats:
            problems.append(f"failure mode {fid}: no category")
        for c in fcats:
            if c != ALL_CATEGORIES and c not in cats:
                problems.append(f"failure mode {fid}: unknown category {c}")
        if fm.get("check_type") not in CHECK_TYPES:
            problems.append(f"failure mode {fid}: check_type must be one of {CHECK_TYPES}")
        cell = fm.get("cost_cell")
        if not cell:
            problems.append(f"failure mode {fid}: cost_cell missing")
        else:
            for c in fcats:
                row = (cats.get(c) or {}).get("cost") or {}
                if c != ALL_CATEGORIES and c in cats and cell not in row:
                    problems.append(f"failure mode {fid}: category {c}'s cost row has no "
                                    f"'{cell}' cell")
    for cid in cats:
        if ev.budget_for(cid) is None:
            problems.append(f"budgets.yaml: no budget (or default) covers category {cid}")
    return _gate("C4", problems, [f"{len(fms)} failure modes"])


# ---- C5-C8: build ---------------------------------------------------------------------------

def c5(ev: Evals) -> Gate:
    if not ev.p("allocation.yaml").exists():
        return _gate("C5", ["allocation.yaml missing (aot-evals allocate --write)"])
    p = allocate_mod.plan(ev, **_alloc_args(ev))
    problems = []
    for c in p["cells"]:
        if c["status"] == "short":
            problems.append(f"{c['category']} / {c['set']}: {c['have']} of {c['target']} cases; "
                            "fill it, or mark it scheduled or out_of_scope with a reason")
        elif c["status"] in ("scheduled", "out_of_scope") and not c.get("reason"):
            problems.append(f"{c['category']} / {c['set']}: {c['status']} without a reason")
    return _gate("C5", problems)


def _alloc_args(ev: Evals) -> dict:
    a = (ev.allocation().get("assumptions") or {})
    return {"halfwidth": a.get("quality_halfwidth", 0.05),
            "assumed_rate": a.get("assumed_pass_rate", 0.5), "k": a.get("k", 3)}


def case_problems(ev: Evals, case: dict) -> tuple[list[str], list[str]]:
    """(blocking problems, warnings) for one case. Shared by C6 and `validate`."""
    cid = case.get("id", "?")
    problems, warnings = [], []
    cats = set(ev.category_ids())
    fms = {f.get("id") for f in ev.failure_modes()}
    path = Path(case.get("_path", ""))
    if not case.get("id"):
        problems.append(f"{path}: id missing")
    elif path.stem != case["id"]:
        problems.append(f"{path}: id {case['id']!r} does not match the file name")
    if case.get("category") not in cats:
        problems.append(f"case {cid}: category {case.get('category')!r} not in categories.yaml")
    elif case.get("_dir_category") != case.get("category"):
        problems.append(f"case {cid}: stored under cases/{case.get('_dir_category')}/ but its "
                        f"category is {case.get('category')}")
    if case.get("set") not in SETS:
        problems.append(f"case {cid}: set must be one of {SETS} (there is no default)")
    modes = case.get("failure_modes") or []
    if not modes:
        problems.append(f"case {cid}: no failure_modes")
    for m in modes:
        if m not in fms:
            problems.append(f"case {cid}: unknown failure mode {m}")
    prov = case.get("provenance") or {}
    if not prov.get("source"):
        problems.append(f"case {cid}: provenance.source missing")
    if prov.get("export") and prov["export"] not in {e.get("id") for e in ev.exports()}:
        problems.append(f"case {cid}: provenance.export {prov['export']!r} is not in the export "
                        "manifest")
    if not case.get("trigger"):
        problems.append(f"case {cid}: trigger missing")
    if "expected_end_state" not in case:
        problems.append(f"case {cid}: expected_end_state missing")
    if not case.get("taxonomy_entries"):
        warnings.append(f"case {cid}: no taxonomy_entries; it will not count toward coverage")
    text = json.dumps({k: v for k, v in case.items() if not k.startswith("_")})
    for f in scan(text):
        msg = f"case {cid}: possible {f.pattern} ({f.excerpt})"
        (problems if f.kind == "secret" else warnings).append(msg)
    return problems, warnings


def c6(ev: Evals) -> Gate:
    try:
        cases = ev.cases(include_dropped=False)
    except ContractError as e:
        return _gate("C6", [str(e)])
    if not cases:
        return _gate("C6", ["no cases authored"])
    problems, warnings = [], []
    traces: dict[str, tuple] = {}
    for c in cases:
        p, w = case_problems(ev, c)
        problems += p
        warnings += w
        ref = (c.get("provenance") or {}).get("trace_ref")
        if ref:
            other = traces.get(ref)
            if other and other[1] != c.get("set"):
                problems.append(f"cases {other[0]} and {c.get('id')} come from the same trace but "
                                "sit in different sets; the two sets must be disjoint")
            traces[ref] = (c.get("id"), c.get("set"))
    return _gate("C6", problems, warnings + [f"{len(cases)} cases"])


def c7(ev: Evals) -> Gate:
    cases = ev.cases()
    if not cases:
        return _gate("C7", ["no cases to screen"])
    problems = []
    dropped = [c for c in cases if (c.get("screen") or {}).get("dropped")]
    for c in dropped:
        if not c["screen"].get("drop_reason"):
            problems.append(f"case {c.get('id')}: dropped without a reason")
    for c in cases:
        if c in dropped:
            continue
        s = c.get("screen") or {}
        if not s.get("screened_at"):
            problems.append(f"case {c.get('id')}: not screened (aot-evals screen)")
        elif not screen_passes(s):
            why = []
            if s.get("human_read") is not True:
                why.append("no human read")
            if s.get("reference_passes") is not True:
                why.append("reference end state fails its checks")
            if s.get("donothing_fails") is False:
                why.append("a do-nothing agent passes")
            if s.get("claim_sensitive_checks"):
                why.append(f"claim-sensitive checks {s['claim_sensitive_checks']}")
            problems.append(f"case {c.get('id')}: {'; '.join(why) or 'screen incomplete'} "
                            "(fix it or drop it with a reason)")
    rate = len(dropped) / len(cases)
    return _gate("C7", problems, [f"drop rate {len(dropped)}/{len(cases)} = {rate:.0%}"])


def c8(ev: Evals) -> Gate:
    fms = ev.failure_modes()
    if not fms:
        return _gate("C8", ["no failure modes"])
    problems = []
    for fm in fms:
        ctype = fm.get("check_type")
        if ctype == "monitor":
            continue
        checks = fm.get("checks") or []
        if not checks:
            problems.append(f"failure mode {fm.get('id')}: no check")
        for cid in checks:
            t = ev.check_type(cid)
            if t is None:
                problems.append(f"check {cid}: no checks/code/{cid}.py or checks/judge/{cid}.md")
            elif t == "code" and declares_agent_report(ev.code_check_path(cid)):
                problems.append(f"check {cid}: declares USES_AGENT_REPORT (G10)")
            elif t == "judge":
                from .judges import load_spec

                try:
                    spec = load_spec(ev.judge_check_path(cid))
                    problems += spec.problems()
                    if spec.failure_mode != fm.get("id"):
                        problems.append(f"judge {cid}: failure_mode {spec.failure_mode!r} but listed under "
                                        f"{fm.get('id')!r}")
                except ContractError as e:
                    problems.append(str(e))
    side = [fm for fm in fms if fm.get("side_effect") and ALL_CATEGORIES in (fm.get("categories") or [])
            and any(ev.check_type(c) == "code" for c in fm.get("checks") or [])]
    if not side:
        problems.append("no side-effect check: add a failure mode with side_effect: true, "
                        "categories: ['*'] and a code check (nothing changed outside scope)")
    claim = sorted({cid for c in ev.cases(include_dropped=False)
                    for cid in (c.get("screen") or {}).get("claim_sensitive_checks") or []})
    if claim:
        problems.append(f"checks that pass on a bare success claim (G10): {claim}")
    return _gate("C8", problems)


# ---- C9-C11: judges ---------------------------------------------------------------------------

def _judge_specs(ev: Evals) -> tuple[list, list[str]]:
    from .judges import load_spec

    specs, problems = [], []
    for cid in _judge_checks(ev):
        try:
            spec = load_spec(ev.judge_check_path(cid))
        except ContractError as e:
            problems.append(str(e))
            continue
        problems += spec.problems()
        specs.append(spec)
    return specs, problems


def _judge_checks(ev: Evals) -> list[str]:
    return sorted({cid for fm in ev.failure_modes() for cid in fm.get("checks") or []
                   if ev.check_type(cid) == "judge"})


def c9(ev: Evals) -> Gate:
    from .labels import status as label_status

    if not _judge_checks(ev):
        return Gate("C9", "not_applicable", info=["no judge checks"])
    specs, problems = _judge_specs(ev)
    info = []
    for spec in specs:
        st = label_status(ev, spec)
        info.append(f"{spec.id}: {st['labels']} labels ({st['pass']} pass / {st['fail']} fail)")
        if st["labels"] < 60:
            problems.append(f"judge {spec.id}: {st['labels']} labels; at least 60, target 100-200 "
                            "(aot-evals label queue / import)")
        if st["missing_categories"]:
            problems.append(f"judge {spec.id}: no labels for categories {st['missing_categories']} "
                            "(labels must be stratified across categories)")
        if st["labels"] and (not st["pass"] or not st["fail"]):
            problems.append(f"judge {spec.id}: labels are all one class; TPR or TNR cannot be measured")
    return _gate("C9", problems, info)


def c10(ev: Evals) -> Gate:
    from .calibrate import is_current, load_calibration

    if not _judge_checks(ev):
        return Gate("C10", "not_applicable", info=["no judge checks"])
    specs, problems = _judge_specs(ev)
    info = []
    for spec in specs:
        cal = load_calibration(ev, spec)
        if not cal:
            problems.append(f"judge {spec.id}: not calibrated (aot-evals calibrate --judge {spec.id})")
        elif not is_current(ev, spec, cal):
            problems.append(f"judge {spec.id}: calibration is stale (the judge or its labels changed); re-run it")
        elif spec.primary not in (cal.get("backends") or {}):
            problems.append(f"judge {spec.id}: primary backend {spec.primary} not measured")
        elif cal.get("labels", 0) < 60:
            problems.append(f"judge {spec.id}: calibrated on {cal.get('labels')} labels; needs >= 60")
        else:
            m = cal["backends"][spec.primary]
            info.append(f"{spec.id}: {cal['status']} — TPR {_pct(m['tpr'])}, TNR {_pct(m['tnr'])} "
                        f"on {m['labels']} labels "
                        f"({spec.primary}, {m.get('family')}, v{spec.version})")
    return _gate("C10", problems, info)


def _pct(v) -> str:
    return "n/a" if v is None else f"{100 * v:.0f}%"


def c11(ev: Evals) -> Gate:
    from .reliability import load_reliability

    if not _judge_checks(ev):
        return Gate("C11", "not_applicable", info=["no judge checks"])
    specs, problems = _judge_specs(ev)
    for spec in specs:
        rel = load_reliability(ev, spec)
        if not rel:
            problems.append(f"judge {spec.id}: no reliability measurement (aot-evals reliability "
                            f"--judge {spec.id} --backend A --backend B)")
        elif rel.get("judge_sha") != spec.sha():
            problems.append(f"judge {spec.id}: reliability measured on an earlier version; re-run it")
        elif not rel.get("cross_family"):
            problems.append(f"judge {spec.id}: reliability has no cross-family pair")
    return _gate("C11", problems)


# ---- C12: baseline --------------------------------------------------------------------------

MANIFEST_CONDITION_FIELDS = ("agent_commit", "evals_commit", "harness", "k")


def manifest_problems(m: dict) -> list[str]:
    problems = [f"manifest: {f} missing" for f in MANIFEST_CONDITION_FIELDS if not m.get(f)]
    models = (m.get("agent") or {}).get("model_ids") or {}
    if not models:
        problems.append("manifest: no model id per call site")
    exposure = m.get("eval_exposure") or {}
    if exposure.get("changed"):
        problems.append(f"run {m.get('run_id')}: eval files changed during the run "
                        f"({', '.join(exposure['changed'][:3])}); re-run with invoke.isolate: true")
    if exposure.get("mentioned"):
        first = exposure["mentioned"][0]
        problems.append(f"run {m.get('run_id')}: the agent's output names eval files in "
                        f"{len(exposure['mentioned'])} attempt(s), e.g. {first['case_id']}: "
                        f"{', '.join(first['files'])}; it may have read the answers. Re-run with "
                        "invoke.isolate: true")
    return problems


def trial_completeness(ev: Evals, m: dict) -> list[str]:
    recs = [r for r in ev.run_records(m["run_id"]) if r.get("kind") == "attempt"]
    finals = {(r["case_id"], r["trial"]) for r in recs if r.get("final")}
    missing = [(c, t) for c in m.get("case_set", {}).get("ids") or [] for t in range(m.get("k", 0))
               if (c, t) not in finals]
    if missing:
        return [f"run {m['run_id']}: {len(missing)} (case, trial) pairs have no final attempt, "
                f"e.g. {missing[0]}"]
    return []


def c12(ev: Evals) -> Gate:
    base = ev.latest_run("baseline")
    if not base:
        return _gate("C12", ["no finished baseline run (aot-evals run --purpose baseline --k 5)"])
    problems = manifest_problems(base)
    if (base.get("k") or 0) < 3:
        problems.append(f"baseline k={base.get('k')}; k must be 3-5 to see variance")
    problems += trial_completeness(ev, base)
    for cid in ev.category_ids():
        if ev.budget_for(cid) is None:
            problems.append(f"no plane-B budget for category {cid}")
    return _gate("C12", problems, [f"baseline {base['run_id']}"])


# ---- C13-C15: suite measurement ------------------------------------------------------------------

def c13(ev: Evals) -> Gate:
    from .compare import comparison_path, latest_for

    base = ev.latest_run("baseline")
    cands = [m for m in ev.runs("candidate") if m.get("finished")]
    if not base or not cands:
        return Gate("C13", "not_applicable", info=["no candidate run yet (aot-evals run --purpose candidate "
                                                  "--k 5 --variable KIND=VALUE)"])
    latest = cands[-1]["run_id"]
    comp = latest_for(ev, [base["run_id"]])
    if not comp or latest not in comp.get("candidate_runs", []):
        return _gate("C13", [f"candidate {latest} has not been compared with baseline {base['run_id']} "
                             f"(aot-evals compare --candidate {latest})"])
    if comp.get("refused"):
        return _gate("C13", [f"comparison refused: {comp['refused']}"])
    info = [f"{latest}: {comp['verdict']} (+{len(comp['gains'])}/-{len(comp['losses'])}, "
            f"p = {comp['test']['p']:.3g})", str(comparison_path(ev, comp).name)]
    return _gate("C13", [], info)


def c14(ev: Evals) -> Gate:
    problems = taxonomy_problems(ev)
    if problems:
        return _gate("C14", ["coverage refused (G5): " + problems[0]])
    entries = {e.get("id") for e in ev.taxonomy().get("entries") or []}
    missing, unknown = [], []
    for c in ev.cases(include_dropped=False):
        te = c.get("taxonomy_entries") or []
        if not te:
            missing.append(c.get("id"))
        unknown += [f"{c.get('id')}: {e}" for e in te if e not in entries]
    if missing:
        problems.append(f"{len(missing)} case(s) map to no taxonomy entry, e.g. {missing[:5]}")
    if unknown:
        problems.append(f"taxonomy entries not in taxonomy.yaml: {unknown[:5]}")
    return _gate("C14", problems)


def c15(ev: Evals) -> Gate:
    from .suite import redundancy

    red = redundancy(ev)
    if red is None:
        return Gate("C15", "not_applicable", info=["needs at least two agent versions; run a candidate"])
    f = red["discriminating_fraction"]
    info = [f"discriminating fraction {'-' if f is None else f'{100 * f:.0f}%'} "
            f"(threshold {100 * red['threshold']:.0f}%) over {len(red['candidates'])} versions"]
    if red["below_threshold"]:
        p = red["proposal"]
        info.append(f"prune/extend proposal: {p['suite_size']['before']} -> {p['suite_size']['after']} cases "
                    "(aot-evals redundancy)")
    return _gate("C15", [], info)


def c18(ev: Evals) -> Gate:
    from .util import load_json

    r = load_json(ev.p("report", "report.json"))
    if not r:
        return _gate("C18", ["report/report.json missing (aot-evals report)"])
    problems = []
    ids = {g.get("id") for g in r.get("gates") or []}
    missing = [f"G{i}" for i in range(1, 14) if f"G{i}" not in ids]
    if missing:
        problems.append(f"report.json lacks gate status for {missing}")
    latest = ev.latest_run()
    if latest and latest.get("finished", "") > r.get("generated", ""):
        problems.append(f"report.json predates run {latest['run_id']}; regenerate it")
    return _gate("C18", problems)


def evaluate(ev: Evals) -> list[Gate]:
    fns = {"C0": c0, "C1": c1, "C2": c2, "C3": c3, "C4": c4, "C5": c5, "C6": c6, "C7": c7,
           "C8": c8, "C9": c9, "C10": c10, "C11": c11, "C12": c12, "C13": c13, "C14": c14,
           "C15": c15, "C18": c18}
    out = []
    for gid, _, _ in COMMANDS:
        if gid in fns:
            try:
                out.append(fns[gid](ev))
            except ContractError as e:
                out.append(_gate(gid, [str(e)]))
        else:
            out.append(Gate(gid, "not_implemented", info=["guidance only; not yet automated (docs/method.md §4)"]))
    return out


def next_unmet(gates: list[Gate]) -> Gate | None:
    for g in gates:
        if g.status == "unmet":
            return g
    return None


def require(ev: Evals, upto: str) -> list[Gate]:
    """Unmet blocking gates strictly before command `upto` (e.g. 'C12')."""
    order = [c[0] for c in COMMANDS]
    before = set(order[: order.index(upto)])
    return [g for g in evaluate(ev) if g.id in before and g.id not in NON_BLOCKING
            and g.status == "unmet"]


def untracked_cases(ev: Evals) -> list[str]:
    return git_untracked_or_modified(ev.repo_root, str(ev.p("cases").relative_to(ev.repo_root)))
