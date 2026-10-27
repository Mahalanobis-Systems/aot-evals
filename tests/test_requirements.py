"""The labelling standard and per-case requirements (C6, C8).

Acceptance: a suite with no standard, or a case that skips a rule that applies to its category
without saying why, leaves C6 open; a requirement decided by no check that runs on the case
leaves C8 open, unless it says why it is unchecked.
"""

from __future__ import annotations

import json

from aot_evals import gates
from aot_evals.repo import Evals


def _gate(repo, gid: str) -> gates.Gate:
    return next(g for g in gates.evaluate(Evals.find(str(repo.evals))) if g.id == gid)


def _edit_case(repo, case_id: str, fn) -> None:
    path = next((repo.evals / "cases").glob(f"*/{case_id}.json"))
    case = json.loads(path.read_text())
    fn(case)
    path.write_text(json.dumps(case, indent=2))


def test_the_calendar_suite_meets_c6_and_c8(make_repo):
    repo = make_repo()
    assert _gate(repo, "C6").status == "met"
    assert _gate(repo, "C8").status == "met"


def test_no_standard_leaves_c6_open(make_repo):
    repo = make_repo()
    (repo.evals / "labels" / "standard.md").unlink()
    assert any("no labelling standard" in p for p in _gate(repo, "C6").problems)


def test_a_rule_that_applies_must_be_cited_or_excused(make_repo):
    repo = make_repo()
    _edit_case(repo, "book-001", lambda c: c.update(requirements=[r for r in c["requirements"]
                                                                  if r["rule"] != "writes-right"]))
    assert any("book-001: rule writes-right applies" in p for p in _gate(repo, "C6").problems)
    _edit_case(repo, "book-001", lambda c: c.update(rules_not_applicable={"writes-right": "covered elsewhere"}))
    assert _gate(repo, "C6").status == "met"


def test_a_requirement_needs_a_check_that_runs_on_the_case(make_repo):
    repo = make_repo()

    def point_at_wrong_check(c):
        c["requirements"][0]["checks"] = ["requested-event-exists", "no-such-check"]
    _edit_case(repo, "none-001", point_at_wrong_check)
    assert any("none-001: requirement nothing-else names check no-such-check" in p
               for p in _gate(repo, "C8").problems)

    def unchecked(c):
        c["requirements"][0].pop("checks")
        c["requirements"][0]["unchecked"] = "no check reads the reply yet"
    _edit_case(repo, "none-001", unchecked)
    assert _gate(repo, "C8").status == "met"
