"""`coverage`: the bug-finding set against its external coverage list (docs/method.md;
estimators rule 10; statistics §2.5).

The list (`<eval>/coverage.yaml`, named by `design.bug_finding_set.coverage`) comes from a document
outside the cases: the help center, the policy, the tools. Each case names the entries it covers
(`coverage_entries`); the grid is entry × failure mode, the empty cells first, so the next case to
write is the one that fills a hole. Coverage measured against a list made from the cases themselves
is always 100%, so the list must name its source and be committed before the first case.
"""

from __future__ import annotations

from .repo import ALL_USE_CASES, Eval
from .util import git, git_adding_commit, git_adding_commits, git_strictly_before, load_yaml


def coverage_path(ev: Eval):
    bf = ev.spec().part("design").get("bug_finding_set") or {}
    name = bf.get("coverage") if isinstance(bf, dict) else None
    return ev.p(name or "coverage.yaml")


def list_problems(ev: Eval) -> list[str]:
    """Why coverage can't be read against this list: missing, made from the cases, or added after them."""
    path = coverage_path(ev)
    t = load_yaml(path) or {}
    name = path.name
    if not t:
        return [f"{name} missing or empty"]
    problems = []
    src = t.get("source")
    if not src or src == "MISSING":
        problems.append(f"{name}: no source document named")
    else:
        text = src if isinstance(src, str) else " ".join(str(v) for v in src.values())
        if "cases/" in text or (isinstance(src, dict) and src.get("derived_from_cases")):
            problems.append(f"{name}: the source is the eval's own cases; coverage against it is always 100%")
    if not t.get("read_on"):
        problems.append(f"{name}: read_on (the date the source was read) missing")
    entries = t.get("entries") or []
    if not entries:
        problems.append(f"{name}: no entries")
    elif any(not e.get("id") for e in entries):
        problems.append(f"{name}: every entry needs an id")
    root = ev.repo_root
    if git(["rev-parse", "--is-inside-work-tree"], root) != "true":
        return [*problems, f"not a git repository: cannot show {name} was committed before the first case"]
    first = git_adding_commit(root, str(path.relative_to(root)))
    if first is None:
        return [*problems, f"{name} is not committed; commit it before any case"]
    added = git_adding_commits(root, str(ev.p("cases").relative_to(root)))
    commits = {added.get(str(p.relative_to(root))) for p in ev.case_paths()} - {None}
    # the same commit counts: a squash merge folds "the list first, then cases" into one
    early = [c for c in commits if c != first and not git_strictly_before(root, first, c)]
    if early:
        problems.append(f"{name} was not committed before the first case (cases added in "
                        f"{sorted(c[:8] for c in early)}, the list in {first[:8]})")
    return problems


def coverage(ev: Eval) -> dict:
    t = load_yaml(coverage_path(ev)) or {}
    entries = [e["id"] for e in t.get("entries") or [] if isinstance(e, dict) and e.get("id")]
    modes = [fm["id"] for fm in ev.failure_modes()]
    cases = ev.cases(include_dropped=False)
    cells = []
    for entry in entries:
        for fm in ev.failure_modes():
            ids = [c["id"] for c in cases if entry in (c.get("coverage_entries") or [])
                   and (fm["id"] in (c.get("failure_modes") or [])
                        or fm.get("use_cases") == ALL_USE_CASES
                        or c.get("use_case") in (fm.get("use_cases") or []))]
            cells.append({"entry": entry, "failure_mode": fm["id"], "n": len(ids),
                          "bug_finding": sum(1 for c in cases if c["id"] in ids and c.get("pool") == "bug_finding"),
                          "cases": ids})
    cells.sort(key=lambda c: (c["n"] > 0, c["entry"], c["failure_mode"]))
    unknown = sorted({e for c in cases for e in c.get("coverage_entries") or [] if e not in entries})
    return {"eval": ev.id, "list": str(coverage_path(ev).relative_to(ev.root)), "name": t.get("name"),
            "source": t.get("source"), "entries": entries, "failure_modes": modes, "cells": cells,
            "empty_cells": sum(1 for c in cells if c["n"] == 0),
            "entries_without_cases": [e for e in entries if not any(c["n"] for c in cells if c["entry"] == e)],
            "unknown_entries": unknown, "problems": list_problems(ev)}


def render(cov: dict) -> str:
    lines = [f"coverage of {cov['eval']} against {cov['list']} ({cov.get('name') or 'unnamed'})"]
    for p in cov["problems"]:
        lines.append(f"  problem: {p}")
    lines.append(f"  {len(cov['entries'])} entries x {len(cov['failure_modes'])} failure modes, "
                 f"{cov['empty_cells']} empty cells")
    if cov["entries_without_cases"]:
        lines.append(f"  entries with no case yet: {', '.join(cov['entries_without_cases'])}")
    if cov["unknown_entries"]:
        lines.append(f"  cases name entries the list doesn't have: {', '.join(cov['unknown_entries'])}")
    lines.append(f"  {'entry':<24} {'failure mode':<24} {'cases':>5} {'bug-finding':>11}")
    for c in cov["cells"]:
        lines.append(f"  {c['entry']:<24} {c['failure_mode']:<24} {c['n']:>5} {c['bug_finding']:>11}")
    return "\n".join(lines)
