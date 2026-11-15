"""Self-test fixtures on the online store (examples/store): each one triggers exactly the gate it
targets, and the agent variants do what they claim.

report.json v2's `gates` (docs/v2-design.md §6; evidence.py) are the 1.x evidence checks that
survive: `manifest` and `trials_complete` (agent contract), `screened`, `committed` and
`coverage_list` (design), `independent_reference` and `k` (measurement). One fixture per gate
asserts that the set of failing gates is exactly {that gate}; a clean baseline fails none.

The variants: liar (claims success, changes nothing), flaky (a wrong date on about one trial in
four), costly (three times the cost), slow (hangs past the timeout), silent (prints nothing),
peek (reads its own case file). The measurement gates (judges, people) are in test_measurement.py
and the decision's in test_decision.py.
"""

from __future__ import annotations

import json
import math

import yaml
from conftest import StoreRepo, git

from aot_evals import runner
from aot_evals.evidence import failing as failing_ids
from aot_evals.evidence import trial_completeness

TWO = ("--case", "tr_1005", "--case", "tr_1238")  # an order-status request and a refund
STATUS = ["tr_1005", "tr_1006", "tr_1010", "tr_1013"]


def failing(r: dict) -> set[str]:
    return failing_ids(r["gates"])


def gate(r: dict, gid: str) -> dict:
    return next(g for part in r["gates"].values() for g in part if g["id"] == gid)


def baseline(s: StoreRepo, *args: str, eval_id: str = "end-to-end") -> dict:
    assert s.cli("run", "--purpose", "baseline", *(args or TWO), eval_id=eval_id) == 0
    assert s.cli("report", eval_id=eval_id) == 0
    return s.report(eval_id)


def report_on(s: StoreRepo, *runs: str, candidates: tuple[str, ...] = ()) -> dict:
    args = [a for r in runs for a in ("--run", r)] + [a for c in candidates for a in ("--candidate", c)]
    assert s.cli("report", *args) == 0
    return s.report()


def rows(r: dict, uc: str) -> list[dict]:
    return [row for row in r["use_cases"] if row["id"] == uc and row["n_cases"]]


def edit_yaml(path, fn) -> None:
    data = yaml.safe_load(path.read_text())
    fn(data)
    path.write_text(yaml.safe_dump(data, sort_keys=False))


# ---- the gates, one fixture each ---------------------------------------------------------------

def test_a_clean_baseline_fails_no_gate(store_repo):
    r = baseline(store_repo)
    assert failing(r) == set()
    assert set(r["gates"]) == {"agent_contract", "design", "measurement"}
    ids = [g["id"] for part in r["gates"].values() for g in part]
    assert ids == ["manifest", "trials_complete", "screened", "committed", "coverage_list",
                   "independent_reference", "k"]
    assert all(g["status"] == "pass" and g["detail"] for part in r["gates"].values() for g in part)
    # the measurement model's own gates stay where they were, not duplicated here
    assert isinstance(r["measurement"]["gates"], list)


def test_no_run_leaves_the_run_gates_unknown(store_repo):
    assert store_repo.cli("report") == 0
    r = store_repo.report()
    assert {g["id"]: g["status"] for part in r["gates"].values() for g in part} == {
        "manifest": None, "trials_complete": None, "screened": None, "committed": None,
        "coverage_list": "pass", "independent_reference": "pass", "k": None}


def test_a_manifest_without_its_harness_fails_manifest(store_repo):
    s = store_repo
    edit_yaml(s.agent / "agent.yaml", lambda a: a.pop("harness"))
    s.commit("no harness")
    r = baseline(s)
    assert failing(r) == {"manifest"}
    assert "manifest has no harness" in gate(r, "manifest")["detail"]


def test_a_stopped_run_fails_trials_complete(store_repo, monkeypatch):
    s = store_repo
    run_id = _stopped_baseline(s, monkeypatch, ok_cases=3)
    r = report_on(s, run_id)
    assert failing(r) == {"trials_complete"}
    assert "have no final attempt" in gate(r, "trials_complete")["detail"]


def test_an_unscreened_case_fails_screened_and_is_excluded_not_hidden(store_repo):
    s = store_repo
    path = s.agent / "end-to-end/cases/order-status/tr_1006.json"
    case = json.loads(path.read_text())
    case["screen"]["human_read"] = None
    path.write_text(json.dumps(case, indent=2))
    s.commit("unread")
    r = baseline(s, "--case", "tr_1005", "--case", "tr_1006")
    assert failing(r) == {"screened"}
    assert "tr_1006" in gate(r, "screened")["detail"]
    row = next(x for x in rows(r, "order-status") if x["pool"] == "quality")
    assert row["n_cases"] == 1 and row["excluded"]["n_cases"] == 1


def test_an_uncommitted_case_edit_fails_committed(store_repo):
    s = store_repo
    path = s.agent / "end-to-end/cases/order-status/tr_1005.json"
    path.write_text(path.read_text() + "\n")
    r = baseline(s)
    assert failing(r) == {"committed"}
    assert "tr_1005" in gate(r, "committed")["detail"]
    assert r["estimate"]["n_cases"] <= 1  # tr_1005 stays out of θ̂


def test_a_coverage_list_made_from_the_cases_fails_coverage_list(store_repo):
    s = store_repo
    edit_yaml(s.agent / "end-to-end/coverage.yaml",
              lambda t: t.update(source={"document": "clusters of cases/", "kind": "other"}))
    s.commit("a list from the cases")
    r = baseline(s)
    assert failing(r) == {"coverage_list"}
    assert "always 100%" in gate(r, "coverage_list")["detail"]


def test_a_check_that_trusts_the_agents_report_fails_independent_reference(store_repo):
    s = store_repo
    check = s.agent / "end-to-end/checks/code/reply-matches-order.py"
    check.write_text(check.read_text() + "\nUSES_AGENT_REPORT = True\n")
    s.commit("a check that declares it reads the agent's report")
    r = baseline(s)
    assert failing(r) == {"independent_reference"}
    assert "reply-matches-order" in gate(r, "independent_reference")["detail"]


def test_a_k1_run_fails_k(store_repo):
    s = store_repo
    assert s.cli("run", "--purpose", "candidate", "--k", "1", "--variable", "prompt=v2", *TWO) == 0
    r = report_on(s, s.ev().runs("candidate")[-1]["run_id"])
    assert failing(r) == {"k"}
    assert "k = 1" in gate(r, "k")["detail"]


def test_a_k1_baseline_is_refused_by_the_cli(store_repo):
    try:
        store_repo.cli("run", "--purpose", "baseline", "--k", "1", *TWO)
    except SystemExit as e:
        assert "k >= 3" in str(e)
    else:
        raise AssertionError("k=1 baseline ran")


def test_the_gates_read_the_candidates_runs_too(store_repo):
    s = store_repo
    base = baseline(s)["runs"]
    assert s.cli("run", "--purpose", "candidate", "--k", "1", "--variable", "prompt=v2", *TWO) == 0
    r = report_on(s, *base, candidates=(s.ev().runs("candidate")[-1]["run_id"],))
    assert failing(r) == {"k"}


# ---- isolation ---------------------------------------------------------------------------------

def test_an_agent_that_reads_its_case_file_fails_manifest_and_isolation_stops_it(store_repo):
    s = store_repo
    s.set_env(AGENT_VARIANT="peek")
    s.commit("peek")
    r = baseline(s, "--case", "tr_1005")
    detail = gate(r, "manifest")["detail"]
    assert "manifest" in failing(r)
    assert "eval files changed during the run" in detail and "names eval files" in detail
    assert "committed" in failing(r)  # it left a mark in the case file

    git(s.root, "checkout", "--", ".")
    edit_yaml(s.agent / "agent.yaml", lambda a: a["invoke"].update(isolate=True))
    s.commit("isolate")
    assert s.cli("run", "--purpose", "baseline", "--case", "tr_1005") == 0
    m = s.ev().runs("baseline")[-1]
    assert m["eval_exposure"] == {"isolated": True, "changed": [], "mentioned": []}
    r = report_on(s, m["run_id"])
    assert failing(r) == set()
    row = next(x for x in rows(r, "order-status") if x["pool"] == "quality")
    assert row["pass_rate"]["point"] == 1.0  # in the copy there is no case file to find


# ---- the variants -------------------------------------------------------------------------------

def test_the_liar_agent_fails_the_state_checks(store_repo):
    s = store_repo
    s.set_env(AGENT_VARIANT="liar")
    s.commit("liar")
    r = baseline(s, "--use-case", "return")
    assert failing(r) == set()  # the checks grade the order system, not the claim
    for row in rows(r, "return"):
        assert row["pass_rate"]["point"] == 0.0
    run = r["runs"][0]
    state = [ln["passed"] for ln in s.ev().run_records(run)
             if ln.get("kind") == "check" and ln["check_id"] == "end-state-matches"]
    assert False in state


def test_the_flaky_agent_is_reported_as_flaky(store_repo):
    s = store_repo
    s.set_env(AGENT_VARIANT="flaky")
    s.commit("flaky")
    r = baseline(s, "--use-case", "order-status")
    assert failing(r) == set()
    row = next(x for x in rows(r, "order-status") if x["pool"] == "quality")
    assert row["flaky"] > 0
    assert row["pass_pow_k"] < row["pass_rate"]["point"] < 1.0
    vc = row["variance_components"]
    assert vc["within_case"] > 0 and vc["se_double_trials"] < vc["se_now"]
    assert row["zero_failure_bound"] is None
    assert r["measurement"]["variance"]["within"] > 0


def test_the_costly_agent_breaches_its_budget_at_the_same_correctness(store_repo):
    s = store_repo
    # the store's budget is $0.03 per success; the toy's order-status answer costs $0.0015
    edit_yaml(s.agent / "end-to-end/eval.yaml", lambda d: d["decision_rule"]["constraints"].update(
        use_cases={"order-status": {"cost_per_success_usd": 0.003}}))
    s.commit("a tight budget for order status")
    one_each = [a for c in ("tr_1005", "tr_1144", "tr_1204", "tr_1238") for a in ("--case", c)]
    base = baseline(s, *one_each)
    assert all(x["operational"]["budget_status"] == "within" for x in rows(base, "order-status"))
    s.set_env(AGENT_VARIANT="costly")
    s.commit("costly")
    assert s.cli("run", "--purpose", "candidate", "--variable", "prompt=costly", *one_each) == 0
    cand = s.ev().runs("candidate")[-1]["run_id"]
    r = report_on(s, *base["runs"], candidates=(cand,))
    assert failing(r) == set()
    c = r["comparison"]
    assert c["paired"] and c["gains"] == [] and c["losses"] == []
    assert c["verdict"] == "worse"  # a budget newly breached at unchanged θ
    assert [(b["use_case"], b["budget"], b["new"]) for b in c["constraints"]["breaches"]] == [
        ("order-status", "cost_per_success_usd", True)]
    assert r["decision"]["constraints"]["status"] == "breached"
    alone = report_on(s, cand)
    for row in rows(alone, "order-status"):
        assert row["pass_rate"]["point"] == 1.0
        assert row["operational"]["budget_status"] == "over"
        assert row["operational"]["budget_breaches"][0]["budget"] == "cost_per_success_usd"


def test_timeouts_are_operational_never_correctness(store_repo):
    s = store_repo
    s.set_env(AGENT_VARIANT="slow")
    edit_yaml(s.agent / "agent.yaml", lambda a: a["invoke"].update(timeout=1))
    s.commit("slow")
    r = baseline(s, *[a for c in STATUS[:3] for a in ("--case", c)])
    assert gate(r, "trials_complete")["status"] == "pass"
    ops = [x["operational"] for x in r["use_cases"] if x["operational"]["n_attempts"]]
    timeouts = sum(o["outcomes"].get("timeout", 0) for o in ops)
    assert timeouts > 0
    assert sum(o["killed"] for o in ops) == timeouts
    assert sum(o["retries"] for o in ops) > 0
    for row in rows(r, "order-status"):
        assert row["pass_rate"]["point"] == 1.0  # correctness only over ok attempts
    for a in s.ev().run_records(r["runs"][0]):
        if a.get("kind") == "attempt" and a["outcome"] == "timeout":
            assert a["passed"] is None


def test_a_silent_provider_stops_the_run_instead_of_timing_out_every_case(store_repo, capsys):
    s = store_repo
    s.set_env(AGENT_VARIANT="silent")
    s.commit("silent")
    assert s.cli("run", "--purpose", "baseline", "--stop-after", "3", "--use-case", "order-status") == 1
    m = s.ev().runs("baseline")[-1]
    assert m["stopped"]["cases_done"] == 3 and not m.get("finished")
    assert s.ev().latest_run("baseline") is None  # a stopped run is never a baseline
    assert "STOPPED" in capsys.readouterr().out


def test_pause_every_paces_the_run(store_repo):
    pauses: list[float] = []
    m = runner.run(store_repo.ev(), purpose="baseline", k=1, case_ids=STATUS, pause_every=3,
                   pause_seconds=7, sleep=pauses.append, log=lambda *_: None)
    assert m["finished"] and pauses == [7] * ((len(STATUS) - 1) // 3)


# ---- resume -----------------------------------------------------------------------------------

def _stopped_baseline(s: StoreRepo, monkeypatch, ok_cases: int) -> str:
    """A k=3 baseline of four order-status cases whose provider goes silent after `ok_cases`
    (case, trial) pairs, so it stops partway."""
    from aot_evals.executor import AttemptResult, Executor
    from aot_evals.outcomes import Outcome

    real, calls = Executor.run, []

    def flaky(self, payload):
        calls.append(payload)
        if len({(p["case_id"], p["trial"]) for p in calls}) <= ok_cases:
            return real(self, payload)
        return AttemptResult(Outcome.TIMEOUT, "timed out", None, 1000.0, killed=True)

    monkeypatch.setattr(Executor, "run", flaky)
    m = runner.run(s.ev(), purpose="baseline", k=3, case_ids=STATUS, stop_after=2, log=lambda *_: None)
    monkeypatch.setattr(Executor, "run", real)
    assert m["stopped"] and not m["finished"]
    return m["run_id"]


def _attempts(ev, run_id: str) -> list[dict]:
    return [r for r in ev.run_records(run_id) if r.get("kind") == "attempt"]


def _refused(ev, run_id: str) -> str:
    try:
        runner.resume(ev, run_id, log=lambda *_: None)
    except ValueError as e:
        return str(e)
    raise AssertionError("resumed")


def test_a_stopped_run_resumes_in_place_and_counts_as_a_complete_baseline(store_repo, monkeypatch):
    s = store_repo
    ev = s.ev()
    run_id = _stopped_baseline(s, monkeypatch, ok_cases=4)
    assert trial_completeness(ev, ev.run_manifest(run_id))  # pairs missing before resume
    before = _attempts(ev, run_id)
    done_before = {(a["case_id"], a["trial"]) for a in before if a["final"]}

    assert s.cli("run", "--resume", run_id) == 0
    m = ev.run_manifest(run_id)
    assert m["finished"] and "stopped" not in m
    assert [set(r) for r in m["resumed"]] == [{"at", "pairs_done_before"}]
    assert m["resumed"][0]["pairs_done_before"] == len(done_before)
    assert [r["run_id"] for r in ev.runs()] == [run_id]  # same run, no new one

    after = _attempts(ev, run_id)
    assert after[:len(before)] == before  # appended, never rewritten
    keys = [(a["case_id"], a["trial"], a["attempt"]) for a in after]
    assert len(keys) == len(set(keys))
    assert not {(a["case_id"], a["trial"]) for a in after[len(before):]} & done_before

    # totals come from every record, both processes
    assert sum(m["counts"].values()) == len(after)
    assert m["counts"]["timeout"] == sum(a["outcome"] == "timeout" for a in after)
    assert m["cost_usd"] == math.fsum(a["cost_usd"] for a in after if a["cost_usd"] is not None)
    assert m["agent"]["model_ids_observed"] == {"main": ["toy-orchestrator-1"]}

    assert trial_completeness(ev, m) == []
    assert ev.latest_run("baseline")["run_id"] == run_id
    assert failing(report_on(s, run_id)) == set()
    assert "finished" in _refused(ev, run_id)


def test_resume_refused_when_the_agent_commit_changed(store_repo, monkeypatch):
    s = store_repo
    ev = s.ev()
    run_id = _stopped_baseline(s, monkeypatch, ok_cases=2)
    agent = s.root / "agent" / "store.py"
    agent.write_text(agent.read_text() + "\n# v2\n")
    s.commit("agent v2")
    n = len(ev.run_records(run_id))
    why = _refused(ev, run_id)
    assert "agent commit" in why and "mix two versions" in why
    assert len(ev.run_records(run_id)) == n and ev.run_manifest(run_id)["stopped"]


def test_resume_refused_when_env_or_cases_changed(store_repo, monkeypatch):
    s = store_repo
    run_id = _stopped_baseline(s, monkeypatch, ok_cases=2)
    s.set_env(AGENT_VARIANT="costly")
    case = s.agent / "end-to-end/cases/order-status/tr_1005.json"
    case.write_text(case.read_text() + "\n")
    why = _refused(s.ev(), run_id)
    assert "env sha" in why and "case set changed (edited: tr_1005)" in why


def _with_env_files(s: StoreRepo) -> None:
    """A committed fake under env/ and a git-ignored observe dump beside it, as an agent that
    writes its last observation under env/ on every attempt would leave it."""
    env = s.agent / "env"
    (env / "fake_crm.py").write_text("RECORDS = 3\n")
    with (s.agent / ".gitignore").open("a") as f:
        f.write("env/observe/\n")
    (env / "observe").mkdir()
    (env / "observe" / "last.json").write_text('{"attempt": 1}\n')
    s.commit("env fakes")


def test_resume_ignores_git_ignored_files_under_env(store_repo, monkeypatch):
    s = store_repo
    _with_env_files(s)
    ev = s.ev()
    run_id = _stopped_baseline(s, monkeypatch, ok_cases=2)
    (s.agent / "env" / "observe" / "last.json").write_text('{"attempt": 7}\n')
    assert s.cli("run", "--resume", run_id) == 0
    m = ev.run_manifest(run_id)
    assert m["finished"] and trial_completeness(ev, m) == []


def test_resume_refused_when_a_tracked_env_file_has_uncommitted_edits(store_repo, monkeypatch):
    s = store_repo
    _with_env_files(s)
    run_id = _stopped_baseline(s, monkeypatch, ok_cases=2)
    (s.agent / "env" / "fake_crm.py").write_text("RECORDS = 4\n")
    assert "env/ fakes changed" in _refused(s.ev(), run_id)


def test_resume_drops_a_truncated_last_line(store_repo, monkeypatch):
    s = store_repo
    ev = s.ev()
    run_id = _stopped_baseline(s, monkeypatch, ok_cases=3)
    path = ev.p("runs", run_id, "outcomes.jsonl")
    with path.open("a") as f:
        f.write('{"kind": "attempt", "case_id": "tr_10')  # the process died mid-write
    assert s.cli("run", "--resume", run_id) == 0
    assert path.read_text().endswith("}\n")
    m = ev.run_manifest(run_id)
    assert m["finished"] and trial_completeness(ev, m) == []


def test_resume_redoes_a_pair_whose_last_attempt_is_not_final(store_repo, monkeypatch):
    from aot_evals.util import append_jsonl

    s = store_repo
    ev = s.ev()
    run_id = _stopped_baseline(s, monkeypatch, ok_cases=3)
    finals = {(a["case_id"], a["trial"]) for a in _attempts(ev, run_id) if a["final"]}
    m = ev.run_manifest(run_id)
    pair = next((c, t) for t in range(3) for c in m["case_set"]["ids"] if (c, t) not in finals)
    # the process died after a retryable attempt, before its retry
    append_jsonl(ev.p("runs", run_id, "outcomes.jsonl"),
                 {"kind": "attempt", "run_id": run_id, "case_id": pair[0], "trial": pair[1],
                  "attempt": 0, "outcome": "rate_limited", "final": False, "passed": None,
                  "cost_usd": 0.5, "model_ids": {}})
    assert s.cli("run", "--resume", run_id) == 0
    tries = [a for a in _attempts(ev, run_id) if (a["case_id"], a["trial"]) == pair]
    assert [(a["attempt"], a["final"]) for a in tries] == [(0, False), (1, True)]
    assert tries[1]["outcome"] == "ok"
    m = ev.run_manifest(run_id)
    assert m["counts"]["rate_limited"] == 1 and m["cost_usd"] > 0.5  # counted from the records
    assert trial_completeness(ev, m) == []

