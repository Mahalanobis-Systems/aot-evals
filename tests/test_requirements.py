"""The labelling standard and per-case requirements (requirements.py), on the store's end-to-end eval.

Acceptance: the standard is the agent system's, shared by its evals; a missing standard is named;
a case that skips a rule that applies to its use case without saying why is named; a requirement
decided by no check that runs on the case is named, unless it says why it is unchecked.
"""

from __future__ import annotations

import json

from aot_evals.requirements import (
    author_problems,
    check_problems,
    coverage,
    load_standard,
    rules_for,
    standard_problems,
)

ALL = [{"id": "what", "rule": "does-what-was-asked", "says": "the refund is made, nothing else changes",
        "checks": ["end-state-matches"]},
       {"id": "told", "rule": "says-what-happened", "says": "the reply names the amount",
        "checks": ["reply-matches-order"]},
       {"id": "asks", "rule": "asks-for-the-order-number", "says": "an order number is given; nothing to ask",
        "unchecked": "the request carries its order number"}]


def _case(s, case_id: str, eval_id: str = "end-to-end") -> dict:
    return next(c for c in s.ev(eval_id).cases() if c["id"] == case_id)


def _edit_case(s, case_id: str, fn) -> dict:
    path = next((s.agent / "end-to-end" / "cases").glob(f"*/{case_id}.json"))
    case = json.loads(path.read_text())
    fn(case)
    path.write_text(json.dumps(case, indent=2))
    return _case(s, case_id)


def test_the_store_standard_is_shared_and_its_rules_apply_by_use_case(store_repo):
    s = store_repo
    std = load_standard(s.ev())
    assert std == load_standard(s.ev("refund-subagent"))  # one standard for the agent system
    assert standard_problems(s.ev()) == []
    rules = std["rules"]
    assert [r["id"] for r in rules_for(rules, "refund")] == [
        "does-what-was-asked", "says-what-happened", "asks-for-the-order-number"]
    assert [r["id"] for r in rules_for(rules, "address")] == ["does-what-was-asked", "says-what-happened"]
    assert rules_for([{"id": "x", "says": "y", "use_cases": ["refund"]}], "refund")
    assert not rules_for([{"id": "x", "says": "y", "use_cases": ["refund"]}], "address")


def test_no_standard_is_named(store_repo):
    s = store_repo
    (s.agent / "labels" / "standard.md").unlink()
    assert load_standard(s.ev()) is None
    assert any("no labelling standard" in p for p in standard_problems(s.ev()))


def test_a_rule_that_applies_must_be_cited_or_excused(store_repo):
    s = store_repo
    rules = load_standard(s.ev())["rules"]
    case = _case(s, "tr_1238")
    assert case["use_case"] == "refund"
    assert any("no requirements" in p for p in author_problems(s.ev(), case, rules))
    case = _edit_case(s, "tr_1238", lambda c: c.update(requirements=ALL))
    assert author_problems(s.ev(), case, rules) == []
    case = _edit_case(s, "tr_1238", lambda c: c.update(requirements=ALL[:2]))
    assert author_problems(s.ev(), case, rules) == [
        "case tr_1238: rule asks-for-the-order-number applies to refund but no requirement cites it; "
        "add one, or say why in rules_not_applicable"]
    case = _edit_case(s, "tr_1238", lambda c: c.update(
        rules_not_applicable={"asks-for-the-order-number": "the request carries its order number"}))
    assert author_problems(s.ev(), case, rules) == []
    # the refund-only rule doesn't apply to an address case
    case = _edit_case(s, "tr_1204", lambda c: c.update(requirements=ALL[:2]))
    assert author_problems(s.ev(), case, rules) == []
    assert {r["rule"]: r["cited"] for r in coverage(s.ev())}["asks-for-the-order-number"] == 0


def test_a_requirement_needs_a_check_that_runs_on_the_case(store_repo):
    s = store_repo

    def point_at_wrong_check(c):
        c["requirements"] = [dict(ALL[0], checks=["end-state-matches", "no-such-check"])]
    case = _edit_case(s, "tr_1204", point_at_wrong_check)
    assert [p for p in check_problems(s.ev(), case)] == [
        "case tr_1204: requirement what names check no-such-check, which doesn't run on this case (give a "
        "failure mode of its use case that check, in eval.yaml's measurement.failure_modes)"]

    def unchecked(c):
        c["requirements"][0].pop("checks")
        c["requirements"][0]["unchecked"] = "no check reads the reply yet"
    case = _edit_case(s, "tr_1204", unchecked)
    assert check_problems(s.ev(), case) == []
    case = _edit_case(s, "tr_1204", lambda c: c["requirements"][0].pop("unchecked"))
    assert any("names no check" in p for p in check_problems(s.ev(), case))
