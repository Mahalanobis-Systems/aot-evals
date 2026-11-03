"""`aot-evals build`: the lightest Build, from the discovery report to a baseline (docs/method.md §4.1).

It does the mechanical part and says plainly what is left:

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

import re
import shutil

import yaml

from .repo import ALL_CATEGORIES, Evals
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
    path = ev.p("discovery.md")
    if not path.exists():
        return []
    fm, _ = split_front_matter(path.read_text())
    rows = ((fm.get("grid") or {}).get("rows")) or []
    return [{"name": r.get("task_type"), "share": _share(r.get("share"))} for r in rows if r.get("task_type")]


def situations(ev: Evals) -> list[dict]:
    """The discovery report's grid columns: the situations public benchmarks test."""
    path = ev.p("discovery.md")
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
            cats = [{"id": _slug(t["name"]), "definition": t["name"], "worth": "medium", "simple": False,
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
    tax = load_yaml(ev.p("taxonomy.yaml")) or {}
    cols = situations(ev)
    if not tax.get("entries") and cols and not ev.case_paths():
        from datetime import date

        tax.update({"name": f"Situations to cover for {ev.agent_name}",
                    "source": {"document": "Public agent benchmarks, through the discovery report's golden test "
                               "case grid (references/situations.yaml)", "kind": "other",
                               "path": "discovery.md"},
                    "read_on": date.today().isoformat(), "template": None,
                    "entries": [{"id": f"situation.{c['id']}", "title": c.get("name") or c["id"]} for c in cols]})
        ev.p("taxonomy.yaml").write_text(
            "# Drafted by `aot-evals build` from the situations public benchmarks test. Add the jobs from\n"
            "# a document written for another purpose (product spec, help centre, tool surface).\n"
            "# Commit this before the first case: coverage is measured only against a list that came first.\n"
            + yaml.safe_dump(tax, sort_keys=False))
        done.append(f"drafted the coverage list from the {len(cols)} situations in the discovery report; "
                    "commit taxonomy.yaml before the first case")
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
