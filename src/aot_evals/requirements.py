"""The labelling standard and each case's requirements (C6, C8).

Our experiments comparing aot-evals with plain Claude Code found that a suite whose checks each
decide correctly can still miss most of what makes a person fail a run, because nobody wrote
down what a correct run must do. Checks were derived
from failure modes per category ("the expected change happened"), and nothing asked, case by
case, whether the list was complete, the task was attached, or the answer's numbers were true.

`labels/standard.md` holds the rules a person applies when labelling (C9, C19), with the
categories each rule applies to. Every case carries `requirements`: what a correct run of that
case must do, in plain words, each naming the checks that decide it:

    "requirements": [
      {"id": "invitee", "rule": "writes-right", "says": "the invite goes to Ana only",
       "checks": ["attendees-match"]},
      {"id": "reply-true", "rule": "facts-true", "says": "the time in the reply is 14:00",
       "unchecked": "no check reads the reply yet; tracked in triage"}
    ],
    "rules_not_applicable": {"connected": "nothing to connect: one event, no people records"}

C6: every case in a rule's categories cites the rule in a requirement, or says why not.
C8: every requirement names at least one check that applies to the case, or says why it is
unchecked. An unchecked requirement is allowed, and visible: it is a known gap, not a hidden one.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from .repo import ALL_CATEGORIES, Evals
from .util import ContractError


def standard_path(ev: Evals) -> Path:
    return ev.p("labels", "standard.md")


def load_standard(ev: Evals) -> dict | None:
    """{"rules": [...], "body": str} or None when there is no standard."""
    path = standard_path(ev)
    if not path.exists():
        return None
    text = path.read_text()
    if not text.startswith("---"):
        return {"rules": [], "body": text}
    try:
        _, front, body = text.split("---", 2)
    except ValueError as e:
        raise ContractError(f"{path}: unterminated front matter") from e
    meta = yaml.safe_load(front) or {}
    return {"rules": meta.get("rules") or [], "body": body}


def rules_for(rules: list[dict], category: str | None) -> list[dict]:
    return [r for r in rules if ALL_CATEGORIES in (r.get("categories") or [ALL_CATEGORIES])
            or category in (r.get("categories") or [])]


def standard_problems(ev: Evals) -> list[str]:
    std = load_standard(ev)
    if std is None:
        return ["no labelling standard: write labels/standard.md (start from the template "
                "`aot-evals init` writes), the rules a person applies when failing a run"]
    problems = []
    seen = set()
    for r in std["rules"]:
        if not r.get("id") or not r.get("says"):
            problems.append(f"labels/standard.md: every rule needs an id and says ({r})")
        elif r["id"] in seen:
            problems.append(f"labels/standard.md: rule {r['id']} listed twice")
        seen.add(r.get("id"))
    if not std["rules"]:
        problems.append("labels/standard.md: no rules in its front matter")
    return problems


def author_problems(ev: Evals, case: dict, rules: list[dict]) -> list[str]:
    """C6: the case says what a correct run must do, rule by rule."""
    cid = case.get("id", "?")
    reqs = case.get("requirements")
    if not reqs:
        return [f"case {cid}: no requirements (what a correct run of this case must do, per the standard)"]
    problems = []
    known = {r["id"] for r in rules if r.get("id")}
    ids = set()
    for q in reqs:
        if not isinstance(q, dict) or not q.get("id") or not q.get("says"):
            problems.append(f"case {cid}: every requirement needs an id and says")
            continue
        if q["id"] in ids:
            problems.append(f"case {cid}: requirement {q['id']} listed twice")
        ids.add(q["id"])
        if q.get("rule") and q["rule"] not in known:
            problems.append(f"case {cid}: requirement {q['id']} cites rule {q['rule']!r}, not in labels/standard.md")
    cited = {q.get("rule") for q in reqs if isinstance(q, dict)}
    na = case.get("rules_not_applicable") or {}
    for r in rules_for(rules, case.get("category")):
        if r["id"] not in cited and not str(na.get(r["id"]) or "").strip():
            problems.append(f"case {cid}: rule {r['id']} applies to {case.get('category')} but no requirement "
                            f"cites it; add one, or say why in rules_not_applicable")
    return problems


def check_problems(ev: Evals, case: dict) -> list[str]:
    """C8: each requirement is decided by a check that runs on this case, or is marked unchecked."""
    cid = case.get("id", "?")
    applies = {c for c, _ in ev.checks_for_case(case, check_type=None)}
    problems = []
    for q in case.get("requirements") or []:
        if not isinstance(q, dict) or not q.get("id"):
            continue
        checks = q.get("checks") or []
        if not checks and not str(q.get("unchecked") or "").strip():
            problems.append(f"case {cid}: requirement {q['id']} names no check; add one or say why in unchecked")
        for c in checks:
            if c not in applies:
                problems.append(f"case {cid}: requirement {q['id']} names check {c}, which doesn't run on this "
                                "case (list its failure mode in the case, and the check under that failure mode)")
    return problems


def coverage(ev: Evals) -> list[dict]:
    """Per rule: cases it applies to, cases that cite it, cases where it is checked."""
    std = load_standard(ev) or {"rules": []}
    out = []
    cases = ev.cases(include_dropped=False)
    for r in std["rules"]:
        applicable = [c for c in cases if r in rules_for(std["rules"], c.get("category"))]
        cited = [c for c in applicable if any(q.get("rule") == r["id"] for q in c.get("requirements") or [])]
        checked = [c for c in cited if any(q.get("rule") == r["id"] and q.get("checks")
                                           for q in c.get("requirements") or [])]
        out.append({"rule": r["id"], "applies": len(applicable), "cited": len(cited), "checked": len(checked)})
    return out
