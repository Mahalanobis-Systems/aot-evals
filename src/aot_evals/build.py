"""`aot-evals build`: from the discovery report to a baseline, with the fewest decisions.

**2.0** (docs/v2-design.md §1, §7; estimators §1), for an agent folder with 2.0 evals or a new
one. It does the mechanical part and lists, eval by eval and part by part, what the spec still
lacks:

1. creates the end-to-end eval (`init --eval end-to-end`) and the agent's shared files;
2. drafts agent.yaml's `components` from the discovery report's `boundaries`, when agent.yaml lists
   none, and creates an eval for each component the rules give one (a context boundary, decided on
   separately: rule 3), named for the component, its spec left for the owner to fill;
3. drafts the end-to-end eval's use cases from the discovery report's task types, with their
   shares (`share_source: discovery`); costs stay unstated (null), never 1;
4. where an eval's measurement model is still the template's blank, counts one failure mode on every
   case, graded by a generic code check (`checks/code/end-state-matches.py`: the world ends as the
   case expects), which also catches changes nobody asked for (`side_effect: true`);
5. prints the checklist: per eval, the agent contract and the four parts (estimand, sampling design,
   measurement model, decision rule), each done or naming its first missing field, then the
   context boundaries the agent.yaml inventory and the traces show.

With `--run` it runs each eval that can run (smoke, baseline, report). Everything it drafts is a
draft for the owner to confirm.

**1.x**, for a suite that still has its 1.x files (categories.yaml, ...), until `migrate --to 2`:

1. creates whatever the suite is missing (`init`);
2. drafts `categories.yaml` from the discovery report's task types, when there are none yet;
3. when no failure mode exists, adds one that applies to every case, checked by a generic code
   check (`checks/code/end-state-matches.py`: the world ends as the case expects), so cases need
   no check code of their own to start;
4. prints the Build checklist, each item done or not, and the next step.

With `--run` it then runs the agent once, runs the baseline and writes the report, and points at
the grader application. Everything it drafts is marked as a draft for the owner to confirm; what
it can't know (worth, failure costs, the coverage list) stays an upgrade, shown by `status --gates`.
"""

from __future__ import annotations

import json
import re
import shutil

import yaml

from .repo import ALL_CATEGORIES, Eval, Evals
from .scaffold import TEMPLATES, init
from .start import split_front_matter
from .util import dump_yaml, load_yaml

DEFAULT_CHECK = "end-state-matches"
DEFAULT_MODE = "wrong-end-state"


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(s).lower()).strip("-")[:40] or "category"


def _share(v) -> float | None:
    if isinstance(v, (int, float)):
        return float(v) / (100 if v > 1 else 1)
    m = re.match(r"\s*([\d.]+)\s*%", str(v or ""))
    return float(m.group(1)) / 100 if m else None


def task_types(ev: Evals) -> list[dict]:
    """The discovery report's task types (its grid rows): name and share of traffic."""
    path = ev.discovery_path()
    if not path.exists():
        return []
    fm, _ = split_front_matter(path.read_text())
    rows = ((fm.get("grid") or {}).get("rows")) or []
    return [{"name": r.get("task_type"), "share": _share(r.get("share"))} for r in rows if r.get("task_type")]


def situations(ev: Evals) -> list[dict]:
    """The discovery report's grid columns: the situations public benchmarks test."""
    path = ev.discovery_path()
    if not path.exists():
        return []
    fm, _ = split_front_matter(path.read_text())
    from .benchmarks import situations as vocabulary

    names = {v["id"]: v.get("name") for v in vocabulary()}
    return [{"id": c["id"], "name": c.get("name") or names.get(c["id"])}
            for c in ((fm.get("grid") or {}).get("columns") or []) if isinstance(c, dict) and c.get("id")]


def prepare(ev: Evals) -> list[str]:
    """Steps 1-3. Returns what it did, in plain words. Never overwrites a file with content."""
    done = []
    created = init(ev)
    if created:
        done.append(f"created {len(created)} missing file(s) and folder(s) in {ev.root}")
    cats_path = ev.p("categories.yaml")
    if not ev.categories():
        tts = task_types(ev)
        if tts:
            cats = [{"id": _slug(t["name"]), "definition": t["name"], "worth": "medium",
                     "cost": {"incorrect": "medium"}, "observed_share": t["share"],
                     "share_source": "discovery", "draft": "from the discovery report's task types; "
                     "confirm worth and costs with the owner, and add an example trace"} for t in tts]
            data = load_yaml(cats_path) or {}
            data["categories"] = cats
            cats_path.write_text("# Drafted by `aot-evals build` from discovery.md. The owner confirms each.\n"
                                 + dump_yaml(data))
            for c in cats:
                ev.p("cases", c["id"]).mkdir(parents=True, exist_ok=True)
            done.append(f"drafted {len(cats)} categories from the discovery report's task types: "
                        + ", ".join(c["id"] for c in cats))
    if _draft_coverage(ev, ev.p("taxonomy.yaml"), bool(ev.case_paths())):
        done.append(f"drafted the coverage list from the {len(situations(ev))} situations in the discovery "
                    "report; commit taxonomy.yaml before the first case")
    if not ev.failure_modes():
        fm_path = ev.p("failure_modes.yaml")
        data = load_yaml(fm_path) or {}
        data["failure_modes"] = [{
            "id": DEFAULT_MODE, "description": "The world doesn't end as the case expects",
            "categories": [ALL_CATEGORIES], "side_effect": True, "check_type": "code",
            "checks": [DEFAULT_CHECK], "cost_cell": "incorrect"}]
        fm_path.write_text("# Drafted by `aot-evals build`: one failure mode on every case, checked by a\n"
                           "# generic end-state check. Add failure modes per category as you learn them.\n"
                           + yaml.safe_dump(data, sort_keys=False))
        check = ev.code_check_path(DEFAULT_CHECK)
        if not check.exists():
            check.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(TEMPLATES / "checks" / f"{DEFAULT_CHECK}.py", check)
        done.append("added a check on every case: the world ends as the case expects "
                    f"(checks/code/{DEFAULT_CHECK}.py)")
    return done


def _draft_coverage(ev: Evals, path, has_cases: bool) -> bool:
    """The coverage list (1.x taxonomy.yaml, 2.0 coverage.yaml) from the discovery report's grid
    columns, when it has no entries and no case was written yet."""
    tax = load_yaml(path) or {}
    cols = situations(ev)
    if tax.get("entries") or not cols or has_cases:
        return False
    from datetime import date

    tax.update({"name": f"Situations to cover for {ev.agent_name}",
                "source": {"document": "Public agent benchmarks, through the discovery report's golden test "
                           "case grid (references/situations.yaml)", "kind": "other",
                           "path": "discovery.md"},
                "read_on": date.today().isoformat(), "template": None,
                "entries": [{"id": f"situation.{c['id']}", "title": c.get("name") or c["id"]} for c in cols]})
    path.write_text(
        "# Drafted by `aot-evals build` from the situations public benchmarks test. Add the jobs from\n"
        "# a document written for another purpose (product spec, help centre, tool surface).\n"
        "# Commit this before the first case: coverage is measured only against a list that came first.\n"
        + yaml.safe_dump(tax, sort_keys=False))
    return True


def checklist(ev: Evals) -> list[dict]:
    """The lightest Build, item by item: {item, done, detail}."""
    from .replay import records_dir

    a = ev.agent()
    invoke = a.get("invoke") or {}
    cases = ev.cases(include_dropped=False)
    per_cat = {}
    for c in cases:
        per_cat[c.get("category")] = per_cat.get(c.get("category"), 0) + 1
    with_state = [c for c in cases if (c.get("expected_end_state") or {}).get("world") is not None
                  or (c.get("expected_end_state") or {}).get("output") is not None]
    unchecked = [c["id"] for c in cases if not ev.checks_for_case(c, check_type=None)]
    ok_run = any((m.get("counts") or {}).get("ok", 0) > 0 for m in ev.runs())
    base = ev.latest_run("baseline")
    wired = bool(invoke.get("command"))
    return [
        {"item": "The agent runs as a command, or recorded runs stand in for it",
         "done": wired, "detail": ("replays " + records_dir(invoke)) if records_dir(invoke) else
         (" ".join(map(str, invoke.get("command"))) if wired else
          "set invoke.command in agent.yaml (references/agent-contract.md), or replay recorded runs")},
        {"item": "Categories: what people ask the agent to do", "done": bool(ev.categories()),
         "detail": ", ".join(ev.category_ids()) or "none; they come from the discovery report's task types"},
        {"item": "10 to 20 cases from real runs, each with its expected end state",
         "done": len(with_state) >= 10 or (bool(cases) and len(with_state) == len(cases) and len(cases) >= 3),
         "detail": (", ".join(f"{k}: {v}" for k, v in sorted(per_cat.items(), key=lambda kv: str(kv[0])))
                    or "none yet") + (f"; {len(cases) - len(with_state)} without an expected end state"
                                      if len(with_state) < len(cases) else "")},
        {"item": "A check on every case", "done": bool(cases) and not unchecked,
         "detail": f"{len(unchecked)} case(s) nothing checks, e.g. {unchecked[0]}" if unchecked else
         ("every case" if cases else "no cases yet")},
        {"item": "The agent has run once end to end", "done": ok_run or bool(records_dir(invoke)),
         "detail": "aot-evals run --purpose smoke --case <id>"},
        {"item": "A baseline: every case 3 to 5 times", "done": bool(base),
         "detail": base["run_id"] if base else "aot-evals run --purpose baseline --k 5"},
        {"item": "The grader application, handed to the people who will label",
         "done": bool(base) and ev.p("labels", "runs.jsonl").exists(),
         "detail": "aot-evals serve (send each grader the link with &labeller=NAME)"},
    ]


def render(done: list[str], items: list[dict]) -> str:
    lines = [f"- {d}" for d in done]
    if lines:
        lines.append("")
    lines.append("The lightest Build:")
    for it in items:
        lines.append(f"  [{'x' if it['done'] else ' '}] {it['item']}")
        lines.append(f"      {it['detail']}")
    return "\n".join(lines)


def ready_to_run(items: list[dict]) -> list[str]:
    """What still stands in the way of `--run`: the first four items."""
    return [it["item"] for it in items[:4] if not it["done"]]


def run(ev: Evals, cli_main, k: int = 3, log=print) -> int:
    base = ["--evals", str(ev.root)]
    items = checklist(ev)
    missing = ready_to_run(items)
    if missing:
        log("Not ready to run yet: " + "; ".join(missing))
        return 1
    if not items[4]["done"]:
        first = ev.cases(include_dropped=False)[0]["id"]
        log(f"\n$ aot-evals run --purpose smoke --case {first}")
        if cli_main([*base, "run", "--purpose", "smoke", "--case", first]) not in (0, None):
            return 1
    log(f"\n$ aot-evals run --purpose baseline --k {k}")
    if cli_main([*base, "run", "--purpose", "baseline", "--k", str(k)]) not in (0, None):
        return 1
    log("\n$ aot-evals report")
    cli_main([*base, "report"])
    log("\nThe loop is running. Next: start the grader application and send each grader the link:\n"
        "  aot-evals serve --open")
    return 0


# ---- 2.0: around the four parts (docs/v2-design.md §7) -----------------------------------------

SYSTEM_EVAL = "end-to-end"
PARTS = (("estimand", "Estimand: what number, about what, for which decision"),
         ("design", "Sampling design: which cases, drawn how"),
         ("measurement", "Measurement model: how wrong the grader is"),
         ("decision_rule", "Decision rule: when to act"))

# The template's blank use case and failure modes (templates/evals/eval.yaml), replaced only while
# they are exactly as the template wrote them.
_BLANK_USE_CASES = re.compile(
    r"(  use_cases:[^\n]*\n)    - id:\s*\n      definition:\s*\n      example:[^\n]*\n"
    r"      share:\s*\n      cost:[^\n]*\n(  share_source:)[^\n]*\n")
_BLANK_MODES = re.compile(
    r"(  failure_modes:[^\n]*\n)    - id:\s*\n      description:\s*\n      use_cases: \"\*\"\n"
    r"      check:\s*\n      diagnostics: \[\][^\n]*\n    - id: unrequested-change\n[^\n]*\n"
    r"      use_cases: \"\*\"\n      check:\s*\n      side_effect: true[^\n]*\n")


def is_v2(ev: Evals) -> bool:
    """Whether build works in 2.0 terms: the agent has 2.0 evals, or no 1.x suite files yet."""
    if ev.has_evals:
        return not ev.has_v1_suite
    return not ev.has_v1_suite and not ev.case_paths()


def _q(v) -> str:
    return json.dumps(v, ensure_ascii=False)


def _draft_components(ev: Evals) -> list[dict]:
    """agent.yaml's `components`, drafted from the discovery report's `boundaries` when it lists none."""
    from . import boundaries

    agent = ev.agent()
    found = boundaries.from_discovery(ev.discovery_path())
    if "components" in agent or not found:
        return []
    lines = ["", "# Drafted by `aot-evals build` from discovery.md's context boundaries (estimators §1).",
             "# The owner confirms each: kind, context, and whether it ships on its own.",
             "components:"]
    for c in found:
        lines.append(f"  - id: {_q(c['id'])}")
        for k in boundaries.FIELDS[1:]:
            if c.get(k) is not None:
                lines.append(f"    {k}: {_q(c[k])}")
    path = ev.p("agent.yaml")
    path.write_text(path.read_text().rstrip("\n") + "\n" + "\n".join(lines) + "\n")
    return found


def _draft_use_cases(e: Eval) -> int:
    text = e.spec_path.read_text()
    if not _BLANK_USE_CASES.search(text):
        return 0
    tts = [t for t in task_types(e.agent_system) if t.get("name")]
    if not tts:
        return 0
    ids, rows = set(), []
    for t in tts:
        uid = _slug(t["name"])
        while uid in ids:
            uid += "-2"
        ids.add(uid)
        rows.append(f"    - id: {uid}\n      definition: {_q(t['name'])}\n      example:                     "
                    f"# a trace id from the frame\n      share: {t['share'] if t['share'] is not None else ''}\n"
                    f"      cost:                        # what one failure costs, relative to the others\n")
    block = "".join(rows)
    new = _BLANK_USE_CASES.sub(lambda m: m.group(1) + block + m.group(2)
                               + " discovery                # drafted from discovery.md's task types; "
                               "measure the shares on the frame\n", text, count=1)
    e.spec_path.write_text(new)
    return len(rows)


def _draft_measurement(e: Eval) -> bool:
    text = e.spec_path.read_text()
    if not _BLANK_MODES.search(text):
        return False
    block = (f"    - id: {DEFAULT_MODE}\n      description: The world doesn't end as the case expects, or "
             "something changed that it didn't ask for.\n      use_cases: \"*\"\n"
             f"      check: {DEFAULT_CHECK}           # drafted by `aot-evals build`: one generic code check\n"
             "      side_effect: true            # it compares the whole world, so it also catches "
             "unrequested changes\n")
    e.spec_path.write_text(_BLANK_MODES.sub(lambda m: m.group(1) + block, text, count=1))
    check = e.code_check_path(DEFAULT_CHECK)
    if not check.exists():
        check.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(TEMPLATES / "checks" / f"{DEFAULT_CHECK}.py", check)
    return True


def prepare_v2(ev: Evals) -> list[str]:
    """Steps 1-4. Returns what it did, in plain words. Never overwrites what someone wrote."""
    from . import boundaries
    from .scaffold import init_eval

    done = []
    if not ev.has_evals:
        created = init_eval(ev, SYSTEM_EVAL)
        done.append(f"created the end-to-end eval ({SYSTEM_EVAL}/eval.yaml) and {len(created) - 1} other "
                    f"missing file(s) and folder(s) in {ev.root}")
    drafted = _draft_components(ev)
    if drafted:
        done.append("drafted agent.yaml's components from the discovery report's context boundaries: "
                    + ", ".join(c["id"] for c in drafted))
    units = {}
    for e in ev.evals():
        unit = e.spec().part("estimand").get("unit") or {}
        if isinstance(unit, dict) and unit.get("kind") == "component":
            units[unit.get("component")] = e.id
    for row in boundaries.plan(ev.agent()):
        if row["placement"] == boundaries.OWN_EVAL and row["id"] not in units:
            if ev.p(row["id"]).exists():
                continue
            init_eval(ev, row["id"], row["id"])
            done.append(f"created {row['id']}/eval.yaml for {row['id']}: a context boundary, decided on "
                        "separately (rule 3); its frame is the handoffs it receives (aot-evals --eval "
                        f"{row['id']} handoffs)")
    for e in ev.evals():
        unit = e.spec(reload=True).part("estimand").get("unit") or {}
        if isinstance(unit, dict) and unit.get("kind") == "system":
            n = _draft_use_cases(e)
            if n:
                done.append(f"drafted {n} use cases in {e.id}/eval.yaml from the discovery report's task "
                            "types; confirm each share and state what a failure costs")
        if isinstance(unit, dict) and unit.get("kind") == "system" and _draft_coverage(
                ev, e.p("coverage.yaml"), bool(e.case_paths())):
            done.append(f"drafted {e.id}/coverage.yaml from the {len(situations(ev))} situations in the discovery "
                        "report: the list the bug-finding set is checked against; commit it before the first case")
        if _draft_measurement(e):
            done.append(f"added a check on every case of {e.id}: the world ends as the case expects "
                        f"({e.id}/checks/code/{DEFAULT_CHECK}.py)")
        e.spec(reload=True)
    return done


def _part_of(field: str) -> str:
    f = field.split(".", 1)[0].split("[", 1)[0]
    if f == "agent.yaml components":
        return "estimand"
    return f if f in dict(PARTS) else "contract"


def eval_checklist(e: Eval) -> list[dict]:
    """One eval, item by item: {part, item, done, detail}."""
    from .design import case_status
    from .screen import passes

    s = e.spec(reload=True)
    issues: dict[str, list] = {}
    for i in (*s.invalid, *s.missing):
        issues.setdefault(_part_of(i.field), []).append(i)
    unit = s.part("estimand").get("unit") or {}
    component = isinstance(unit, dict) and unit.get("kind") == "component"
    invoke = e.agent().get("invoke") or {}
    try:
        cases = e.cases(include_dropped=False)
    except Exception:
        cases = []
    st = [case_status(e, c) for c in cases]
    drawn = sum(x["counts"] for x in st)
    bug = sum(x["pool"] == "bug_finding" for x in st)
    screened = sum(passes(c.get("screen")) for c in cases)
    base = e.baseline_runs()

    def first(part):
        got = issues.get(part) or []
        return f"{got[0].field}: {got[0].why}" + (f" (+{len(got) - 1} more)" if len(got) > 1 else "") if got else None

    where = "eval.yaml's invoke" if component else "agent.yaml's invoke"
    items = [
        {"part": "contract", "item": f"The {'component' if component else 'agent'} runs as a command ({where})",
         "done": bool(invoke.get("command")) and not issues.get("contract"),
         "detail": first("contract") or (" ".join(map(str, invoke.get("command") or [])) or
                                         f"set invoke.command in {where} (references/agent-contract.md)")},
    ]
    for part, title in PARTS:
        items.append({"part": part, "item": title, "done": not issues.get(part),
                      "detail": first(part) or "every field filled"})
    items += [
        {"part": "design", "item": "A quality set drawn from the frame, with π (aot-evals draw)",
         "done": drawn > 0, "detail": f"{drawn} drawn case(s) that count, {bug} bug-finding"
         if cases else (f"aot-evals --eval {e.id} handoffs, then draw" if component else
                        f"aot-evals --eval {e.id} import FILE --id <frame>, then draw")},
        {"part": "measurement", "item": "Every case screened and read by a person",
         "done": bool(cases) and screened == len(cases),
         "detail": f"{screened} of {len(cases)} pass every screen" + (
             "; a judge-graded use case needs screen --judges" if any(
                 e.checks_for_case(c, check_type="judge") for c in cases) else "")
         if cases else "no cases yet"},
        {"part": "decision_rule", "item": "A baseline, every case k times", "done": bool(base),
         "detail": " + ".join(m["run_id"] for m in base) if base else
         f"aot-evals --eval {e.id} run --purpose baseline"},
    ]
    return items


def boundary_items(ev: Evals) -> list[dict]:
    """The context boundaries: agent.yaml's inventory, each placed, and what the traces show."""
    from . import boundaries, handoffs

    rows = boundaries.plan(ev.agent())
    units = {}
    for e in ev.evals():
        unit = e.spec().part("estimand").get("unit") or {}
        if isinstance(unit, dict) and unit.get("kind") == "component":
            units[unit.get("component")] = e.id
    out = []
    if "components" not in ev.agent():
        out.append({"item": "The parts of the system and their context boundaries (agent.yaml components)",
                    "done": False, "detail": "none listed: name each subagent, route and shared step, so "
                    "each is graded where it belongs (rule 3); an agent with one context lists `components: []`"})
    for r in rows:
        done = r["placement"] != boundaries.UNKNOWN and (r["placement"] != boundaries.OWN_EVAL or r["id"] in units)
        out.append({"item": f"{r['id']} ({r.get('kind') or 'kind?'}, {r.get('context') or 'context?'} context)",
                    "done": done, "detail": r["why"] + (f"; eval: {units[r['id']]}" if r["id"] in units else "")})
    try:
        scan = handoffs.scan_frame(ev)
    except Exception:
        scan = None
    for r in (scan or {}).get("components") or []:
        if not r["in_agent_yaml"]:
            out.append({"item": f"{r['component']}: {r['handoffs']} handoff(s) in the traces", "done": False,
                        "detail": r["why"]})
    return out


def render_v2(done: list[str], ev: Evals) -> str:
    lines = [f"- {d}" for d in done]
    if lines:
        lines.append("")
    for e in ev.evals():
        lines.append(f"{e.id}:")
        for it in eval_checklist(e):
            lines.append(f"  [{'x' if it['done'] else ' '}] {it['item']}")
            lines.append(f"      {it['detail']}")
    b = boundary_items(ev)
    if b:
        lines.append("Context boundaries (where the evals go):")
        for it in b:
            lines.append(f"  [{'x' if it['done'] else ' '}] {it['item']}")
            lines.append(f"      {it['detail']}")
    return "\n".join(lines)


def ready_v2(e: Eval) -> list[str]:
    """What still stands in the way of running an eval: the agent contract, a blocked run, cases."""
    out = [it["detail"] for it in eval_checklist(e)[:1] if not it["done"]]
    out += [f"{i.field}: {i.why}" for i in e.spec().blocked("run")]
    if not e.case_paths():
        out.append("no cases yet")
    return out


def run_v2(ev: Evals, cli_main, log=print) -> int:
    base = ["--evals", str(ev.root)]
    ran, rc = 0, 0
    for e in ev.evals():
        missing = ready_v2(e)
        if missing:
            log(f"{e.id}: not ready to run yet: " + "; ".join(dict.fromkeys(missing)))
            rc = 1
            continue
        args = [*base, "--eval", e.id]
        if not any((m.get("counts") or {}).get("ok", 0) > 0 for m in e.runs()):
            first = e.cases(include_dropped=False)[0]["id"]
            log(f"\n$ aot-evals --eval {e.id} run --purpose smoke --case {first}")
            if cli_main([*args, "run", "--purpose", "smoke", "--case", first]) not in (0, None):
                return 1
        log(f"\n$ aot-evals --eval {e.id} run --purpose baseline")
        if cli_main([*args, "run", "--purpose", "baseline"]) not in (0, None):
            return 1
        log(f"\n$ aot-evals --eval {e.id} report")
        cli_main([*args, "report"])
        ran += 1
    if ran:
        log("\nThe loop is running. Next: label whole runs in the grader application (aot-evals serve), "
            "so each eval can be held to people (rule 15).")
    return rc if not ran else 0
