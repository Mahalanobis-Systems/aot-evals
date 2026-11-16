"""The online-store example (examples/store; docs/method.md): what it claims, checked.

- Both specs are complete once the export is imported and the handoffs extracted.
- The shipped quality sets are `draw`s from that export (valid π, the frame's hash), and every case
  passes screening.
- The policy judge's shipped labels (100 failures, 500 passes) let it clear max_inflation 2.0 at a
  3% failure rate, and it counts in the report; the weaker judge is refused at any rate.
- The variants do what the problems say: refund-bug (problem 1), declines-missing-order (problem 2),
  flaky (problem 8) and cheap (problem 11).
"""

from __future__ import annotations

import json

import pytest
from conftest import StoreRepo

from aot_evals.calibrate import load_calibration
from aot_evals.design import case_status
from aot_evals.judges import load_spec
from aot_evals.measurement import judge_floor


def _baseline(s: StoreRepo, eval_id: str, *args: str) -> str:
    assert s.cli("run", "--purpose", "baseline", *args, eval_id=eval_id) == 0
    return s.ev(eval_id).runs("baseline")[-1]["run_id"]


def _candidate(s: StoreRepo, variant: str, eval_id: str, *args: str, variable: str = "prompt=v2") -> str:
    s.set_env(**{"AGENT_VARIANT": variant})
    s.set_env("refund-subagent", AGENT_VARIANT=variant)
    s.commit(f"candidate {variant}")
    assert s.cli("run", "--purpose", "candidate", "--variable", variable, *args, eval_id=eval_id) == 0
    return s.ev(eval_id).runs("candidate")[-1]["run_id"]


def _report(s: StoreRepo, eval_id: str, *cands: str) -> dict:
    assert s.cli("report", *[a for c in cands for a in ("--candidate", c)], eval_id=eval_id) == 0
    return s.report(eval_id)


def _row(r: dict, uc: str) -> dict:
    return next(u for u in r["use_cases"] if u["id"] == uc and u["pool"] == "quality")


def _rate(s: StoreRepo, run: str, uc: str, eval_id: str = "end-to-end") -> float:
    """A use case's μ̂ on one run (the headline needs every use case; the row needs only its own)."""
    assert s.cli("report", "--run", run, eval_id=eval_id) == 0
    return _row(s.report(eval_id), uc)["estimate"]["point"]


def test_the_specs_are_complete_and_the_draws_valid(store_repo, capsys):
    s = store_repo
    for e in ("end-to-end", "refund-subagent"):
        assert s.cli("validate", eval_id=e) == 0, capsys.readouterr().out
        ev = s.ev(e)
        quality = [c for c in ev.cases() if c.get("pool") == "quality"]
        assert quality and all(case_status(ev, c)["counts"] for c in quality)
        assert all(c["screen"]["reference_passes"] for c in ev.cases())
    assert len(s.ev("refund-subagent").cases()) == 71 and len(s.ev().cases()) == 60
    # the frame of refund handoffs is extracted from the end-to-end export (rule 4)
    m = json.loads((s.agent / "data" / "export.manifest.json").read_text())
    h = next(x for x in m["exports"] if x["id"] == "refund-handoffs-2026-10")["handoffs"]
    assert h["component"] == "refund-subagent" and h["traces_with_handoff"] == 160


def test_the_policy_judge_counts_and_the_weaker_one_does_not(store_repo):
    ev = store_repo.ev("refund-subagent")
    rates = {}
    for jid in ("policy-judge", "policy-judge-weak"):
        cal = load_calibration(ev, load_spec(ev.judge_check_path(jid)))
        b = cal["backends"]["local"]
        rates[jid] = (b["catch"], b["clean"], b["labels_per_kind"])
        floor = {k: b[k] for k in ("catch", "clean", "catch_lower", "clean_lower", "j")}
        rates[jid] += (judge_floor({"status": "calibrated", "reasons": [], **floor}, {"rate": 0.03}, 2.0, 0.05),)
    catch, clean, n, floor = rates["policy-judge"]
    assert (catch, clean, n) == (pytest.approx(0.95), pytest.approx(0.99), {"fail": 100, "pass": 500})
    assert floor["status"] == "pass" and floor["inflation_at_lower_bounds"] < 2.0
    catch, clean, n, floor = rates["policy-judge-weak"]
    assert (catch, clean) == (pytest.approx(0.80), pytest.approx(0.90))
    assert floor["status"] == "refused" and floor["inflation"] > 7


def test_the_refund_eval_counts_its_judge_and_corrects_the_rate(store_repo):
    s = store_repo
    _baseline(s, "refund-subagent")
    r = _report(s, "refund-subagent")
    fm = next(m for m in r["measurement"]["failure_modes"] if m["id"] == "breaks-policy")
    assert fm["check"] == "policy-judge" and fm["floor"]["status"] == "pass"
    assert fm["floor"]["rate"] > 0.03 and fm["feeds_estimate"]
    est = r["estimate"]
    assert est["theta"] is not None and est["corrected"] and est["quantity"] == "failure_rate:breaks-policy"
    # two day-30 refunds in 40 full refunds: the good subagent refuses what the policy allows
    assert _row(r, "full-refund")["estimate"]["point"] == pytest.approx(0.05)
    assert r["decision"]["headline"]["result"] == "insufficient"  # 60 cases can't show < 5%


def test_refund_bug_makes_refunds_fail_more_often(store_repo):
    """Problem 1: refunds of days 31-35 that the policy refuses."""
    s = store_repo
    base = _baseline(s, "end-to-end", "--use-case", "refund")
    cand = _candidate(s, "refund-bug", "end-to-end", "--use-case", "refund")
    assert _rate(s, cand, "refund") < _rate(s, base, "refund") == 1.0


def test_declines_missing_order_improves_the_part_and_breaks_the_whole(store_repo):
    """Problem 2: the subagent's own policy mistakes fall, refunds end to end get worse, and the
    decision on the subagent is not a pass (rule 27)."""
    s = store_repo
    _baseline(s, "refund-subagent")
    base = _baseline(s, "end-to-end", "--use-case", "refund")
    cand_sub = _candidate(s, "declines-missing-order", "refund-subagent")
    r = _report(s, "refund-subagent", cand_sub)
    assert r["comparison"]["net"] > 0  # fewer policy breaks (the deltas of a failure rate negated)
    cand = _candidate(s, "declines-missing-order", "end-to-end", "--use-case", "refund")
    assert _rate(s, cand, "refund") < _rate(s, base, "refund") - 0.05  # refunds with no order number
    d = _report(s, "refund-subagent", cand_sub)["decision"]
    assert d["result"] != "pass"
    # the candidate fails less, and its judge is still read at the baseline's rate: the floor is
    # fixed before the candidate is looked at, so failing less can't make the decision unknown
    assert d["headline"]["result"] != "unknown", d["headline"]
    assert next(a for a in d["also_requires"] if a["eval"] == "end-to-end")["result"] != "pass"


def test_flaky_varies_between_trials_of_a_case(store_repo):
    """Problem 8: the same case passes on some trials and fails on others."""
    s = store_repo
    s.set_env(AGENT_VARIANT="flaky")
    s.commit("flaky")
    run = _baseline(s, "end-to-end", "--use-case", "order-status")
    by_case: dict[str, set] = {}
    for line in s.ev().run_records(run):
        if line.get("kind") == "check" and line["check_id"] == "reply-matches-order":
            by_case.setdefault(line["case_id"], set()).add(line["passed"])
    assert any(v == {True, False} for v in by_case.values())


def test_the_cheaper_model_costs_less_and_moves_cases_both_ways(store_repo):
    """Problem 11: the cheaper subagent model fixes the day-30 refunds and refunds day 31, which the
    policy refuses, at a quarter of the cost."""
    s = store_repo
    base = _baseline(s, "refund-subagent")
    cand = _candidate(s, "cheap", "refund-subagent", variable="model=toy-refunds-mini")
    ev = s.ev("refund-subagent")
    models = {(json.loads(ev.p("runs", rid, "manifest.json").read_text())["agent"]["model_ids_observed"])["main"][0]
              for rid in (base, cand)}
    assert models == {"toy-refunds-1", "toy-refunds-mini"}
    r = _report(s, "refund-subagent", cand)
    c = r["comparison"]
    assert c["gains"] and c["losses"]  # fixed some cases, broke others
