"""Several evals per agent (estimators §1, rules 3, 4, 26, 27; docs/v2-design.md §1, §5): where a
component's eval goes, frames of handoffs, the end-to-end gate on a component change, the
do-nothing screen through judges, and `build` and `components` around the four parts.

Fixtures are the store (examples/store): test_spec's copy of both specs for the spec gates, and
test_estimand's and test_decision's toy agents where something has to run. Every gate fixture
asserts that exactly the issue or gate it targets moves.
"""

from __future__ import annotations

import json
import shutil
import subprocess

import pytest
import yaml
from conftest import FIXTURE
from test_decision import AGENT as DECISION_AGENT
from test_decision import _refunds, _results, _setup
from test_estimand import make_store
from test_measurement import _label_judge, _with_judge
from test_spec import _issues, _spec, _write
from test_spec import store as spec_store  # noqa: F401  (a fixture)

from aot_evals import boundaries, build, cli, components, handoffs, spec
from aot_evals.repo import Evals
from aot_evals.screen import passes


def _agent(ev: Evals) -> dict:
    return yaml.safe_load(ev.p("agent.yaml").read_text())


def _write_agent(ev: Evals, data: dict) -> None:
    ev.p("agent.yaml").write_text(yaml.safe_dump(data, sort_keys=False))


def _comp(data: dict, cid: str = "refund-subagent") -> dict:
    return next(c for c in data["components"] if c["id"] == cid)


# ---- where a component is graded (rule 3) ---------------------------------------------------------

@pytest.mark.parametrize(("c", "placement"), [
    ({"kind": "subagent", "context": "own", "ships_separately": True}, boundaries.OWN_EVAL),
    ({"kind": "subagent", "context": "own", "ships_separately": False}, boundaries.CHECKS),
    ({"kind": "subagent", "context": "own"}, boundaries.UNKNOWN),
    ({"kind": "subagent", "context": "shared", "ships_separately": True}, boundaries.CHECKS),
    ({"kind": "step", "context": "own", "ships_separately": True}, boundaries.CHECKS),
    ({"kind": "route", "context": "own", "ships_separately": True}, boundaries.USE_CASE_GATE),
    ({"kind": "route", "ships_separately": False}, boundaries.USE_CASE),
    ({"context": "own", "ships_separately": True}, boundaries.UNKNOWN),
])
def test_placement(c, placement):
    assert boundaries.placement({"id": "x", **c})["placement"] == placement


# ---- the spec gates: one issue per change to agent.yaml or the frame ------------------------------

def _drop_refund_subagent(a):
    a["components"] = [c for c in a["components"] if c["id"] != "refund-subagent"]


AGENT_MUTATIONS = [
    # (eval, mutate agent.yaml, kind, field)
    ("refunds", _drop_refund_subagent, "missing", "estimand.unit.component"),
    ("refunds", lambda a: _comp(a).update(context="shared"), "invalid", "estimand.unit.component"),
    ("refunds", lambda a: _comp(a).update(kind="route"), "invalid", "estimand.unit.component"),
    ("refunds", lambda a: _comp(a).update(ships_separately=False), "invalid", "estimand.unit.component"),
    ("refunds", lambda a: _comp(a).pop("ships_separately"), "missing",
     "agent.yaml components[refund-subagent].ships_separately"),
    ("refunds", lambda a: _comp(a).pop("context"), "missing", "agent.yaml components[refund-subagent].context"),
    # behind a router, a route whose model ships on its own is a use case gate end to end (rule 20)
    ("end-to-end", lambda a: a["components"].append(
        {"id": "returns-bot", "kind": "route", "ships_separately": True, "use_case": "return"}),
     "missing", "decision_rule.use_case_gates[return]"),
    ("end-to-end", lambda a: a["components"].append(
        {"id": "returns-bot", "kind": "route", "ships_separately": True}), "missing", "estimand.use_cases"),
    ("end-to-end", lambda a: a["components"].append(
        {"id": "credit-bot", "kind": "route", "ships_separately": False, "use_case": "store-credit"}),
     "missing", "estimand.use_cases[store-credit]"),
]


@pytest.mark.parametrize("eval_id,mutate,kind,field", AGENT_MUTATIONS,
                         ids=[f"{m[0]}:{m[2]}:{m[3]}" for m in AGENT_MUTATIONS])
def test_each_agent_yaml_change_triggers_exactly_its_issue(spec_store, eval_id, mutate, kind, field):  # noqa: F811
    for e in spec_store.evals():
        assert e.spec().complete
    data = _agent(spec_store)
    mutate(data)
    _write_agent(spec_store, data)
    s = spec_store.eval(eval_id).spec()
    assert _issues(s) == [(kind, field)], spec.render(s)
    assert "rule" in (s.missing + s.invalid)[0].why


def test_a_route_with_its_gate_is_complete(spec_store):  # noqa: F811
    data = _agent(spec_store)
    data["components"].append({"id": "refund-router", "kind": "route", "ships_separately": True,
                               "use_case": "refund"})
    _write_agent(spec_store, data)
    assert spec_store.eval("end-to-end").spec().complete  # the store already gates refunds


def _manifest(ev: Evals) -> dict:
    return json.loads(ev.p("data", "export.manifest.json").read_text())


def _set_frame(ev: Evals, handoffs_meta) -> None:
    m = _manifest(ev)
    for x in m["exports"]:
        if x["id"] == "refund-handoffs-2026-10":
            if handoffs_meta is None:
                x.pop("handoffs", None)
            else:
                x["handoffs"] = handoffs_meta
    ev.p("data", "export.manifest.json").write_text(json.dumps(m))


@pytest.mark.parametrize("meta", [None, {"component": "billing-subagent", "from": "support-requests-2026-10"}])
def test_a_component_frame_must_hold_its_handoffs(spec_store, meta):  # noqa: F811
    """Rule 4: a frame imported without its handoffs, or another component's, is missing."""
    _set_frame(spec_store, meta)
    s = spec_store.eval("refunds").spec()
    assert _issues(s) == [("missing", "estimand.population.frame")], spec.render(s)
    assert "rule 4" in s.missing[0].why and "handoffs --from support-requests-2026-10" in s.missing[0].why
    assert s.blocked("draw") and s.blocked("estimate") and not s.blocked("plan")


def test_handoffs_from_an_old_end_to_end_frame_are_a_note(spec_store):  # noqa: F811
    """Rule 26: the end-to-end eval moved to a new frame; the handoffs came from the old one."""
    _set_frame(spec_store, {"component": "refund-subagent", "from": "support-requests-2026-09"})
    s = spec_store.eval("refunds").spec()
    assert s.complete
    assert [(n.field, "rule 26" in n.why) for n in s.notes] == [("estimand.population.frame", True)]


def test_a_boundary_without_its_eval_is_a_note(spec_store):  # noqa: F811
    shutil.rmtree(spec_store.p("refunds"))
    s = spec_store.eval("end-to-end").spec()
    assert s.complete
    assert [n.field for n in s.notes] == ["agent.yaml components[refund-subagent]"]
    assert "init --component refund-subagent" in s.notes[0].why


def test_the_example_inventory_places_each_part():
    from test_spec import STORE

    rows = {r["id"]: r["placement"] for r in boundaries.plan(yaml.safe_load((STORE / "agent.yaml").read_text()))}
    assert rows == {"refund-subagent": boundaries.OWN_EVAL, "order-tools": boundaries.CHECKS}


# ---- frames of handoffs (rule 4) -----------------------------------------------------------------

def _trace_rows() -> list[dict]:
    rows = []
    for i in range(12):
        uc = "refund" if i < 8 else "order-status"
        row = {"id": f"tr_{i:03d}", "use_case": uc, "template": f"t{i % 3}",
               "trigger": {"type": "message", "text": f"request {i}"}}
        if uc == "refund":
            kind = ["full-refund", "partial-refund", "gift-card"][i % 3]
            row["handoffs"] = [{"to": "refund-subagent", "use_case": kind,
                                "order_template": f"o{i}", "text": f"refund order {i}",
                                "expected_end_state": {"world": None, "output": "ok"}}]
            if i == 0:  # this trace hands off twice: the second is related to the first
                row["handoffs"].append({**row["handoffs"][0], "text": "and the gift card too", "use_case": "gift-card"})
            row["handoffs"].append({"to": "fraud-check", "input": {"trigger": {"type": "handoff", "text": "?"}}})
        rows.append(row)
    return rows


@pytest.fixture
def traced(tmp_path, monkeypatch):
    """The store with an end-to-end frame whose traces record their handoffs, and a refunds eval."""
    s = make_store(tmp_path, monkeypatch)
    (tmp_path / "traces.jsonl").write_text("".join(json.dumps(r) + "\n" for r in _trace_rows()))
    assert s.cli("import", str(tmp_path / "traces.jsonl"), "--id", "support-traces-2026-10", "--source",
                 "fixture", "--query", "all", "--window", "2026-10-01..2026-10-31") == 0
    data = _spec(Evals(s.agent), "end-to-end")
    data["estimand"]["population"]["frame"] = "support-traces-2026-10"
    _write(Evals(s.agent), "end-to-end", data)
    from test_spec import STORE

    (s.agent / "refunds").mkdir()
    shutil.copyfile(STORE / "refunds" / "eval.yaml", s.agent / "refunds" / "eval.yaml")
    return s


def test_handoffs_are_extracted_from_end_to_end_traces(traced, capsys):
    s = traced
    capsys.readouterr()
    assert s.cli("handoffs", eval_id="refunds") == 0
    out = capsys.readouterr().out
    assert "9 handoff(s) into refund-subagent from 8 of 12 trace(s) in support-traces-2026-10" in out
    assert "1 trace(s) hand off more than once" in out and "cluster_key: source_trace" in out
    ev = Evals(s.agent)
    entry = next(x for x in ev.exports() if x["id"] == "refund-handoffs-2026-10")
    h = entry["handoffs"]
    assert h["component"] == "refund-subagent" and h["from"] == "support-traces-2026-10"
    assert h["source_use_cases"] == {"refund": 9} and h["traces"] == 12 and h["multi"] == 1
    assert entry["window"] == "2026-10-01..2026-10-31" and entry["rows"] == 9
    rows = [json.loads(x) for x in ev.p(entry["file"]).read_text().splitlines()]
    first = next(r for r in rows if r["id"] == "tr_000.h0")
    assert first["source_trace"] == "tr_000" and first["source_use_case"] == "refund"
    assert first["trigger"] == {"type": "handoff", "text": "refund order 0"} and "to" not in first
    assert {r["id"] for r in rows} >= {"tr_000.h0", "tr_000.h1"}
    # the frame is now what the component receives: nothing about it is missing
    s2 = ev.eval("refunds").spec()
    assert not [i for i in s2.missing if i.field == "estimand.population.frame"], spec.render(s2)
    # and a second extraction under the same id is refused, not appended
    with pytest.raises(Exception, match="already in data/export.manifest.json"):
        handoffs.extract(ev.eval("refunds"))


def test_drawn_handoff_cases_point_at_their_trace(traced):
    s = traced
    assert s.cli("handoffs", eval_id="refunds") == 0
    assert s.cli("draw", "--n", "full-refund=2", "--n", "partial-refund=2", "--n", "gift-card=2",
                 eval_id="refunds") == 0
    cases = Evals(s.agent).eval("refunds").cases()
    assert cases and all(c["provenance"]["source_trace"] == c["id"].split(".h")[0] for c in cases)
    assert all(c["provenance"]["export"] == "refund-handoffs-2026-10" for c in cases)


def test_handoffs_scan_shows_the_boundaries_in_the_traces(traced, capsys):
    capsys.readouterr()
    assert traced.cli("handoffs", "--scan", eval_id="refunds") == 0
    out = capsys.readouterr().out
    assert "refund-subagent" in out and "9 handoff(s) in 8 trace(s)" in out
    assert "fraud-check" in out and "not in agent.yaml's components" in out
    s = handoffs.scan_frame(Evals(traced.agent))
    assert [(r["component"], r["in_agent_yaml"]) for r in s["components"]] == [
        ("refund-subagent", True), ("fraud-check", False)]


def test_handoffs_refuses_a_system_eval(traced):
    with pytest.raises(Exception, match="not a component eval"):
        handoffs.extract(Evals(traced.agent).eval("end-to-end"))


# ---- also_requires: the same change, run end to end (rule 27) -----------------------------------

@pytest.fixture
def two_evals(tmp_path, monkeypatch):
    s = make_store(tmp_path, monkeypatch)
    (s.root / "agent" / "store.py").write_text(DECISION_AGENT)
    _setup(s, "good")
    _refunds(s, tmp_path, judge=False)
    return s


def _refunds_candidate(s, *variable: str) -> str:
    assert s.cli("run", "--purpose", "candidate", *variable, eval_id="refunds") == 0
    return Evals(s.agent).eval("refunds").runs("candidate")[-1]["run_id"]


def _decision(s, rc: str) -> dict:
    assert s.cli("report", "--candidate", rc, eval_id="refunds") == 0
    return json.loads((s.agent / "refunds" / "report" / "report.json").read_text())["decision"]


def test_also_requires_refuses_an_end_to_end_run_with_uncommitted_changes(two_evals):
    """The same commit is the same change only when the tree was clean (comparability, #26)."""
    s = two_evals
    rc = _refunds_candidate(s, "--variable", "prompt=v2")
    (s.root / "agent" / "store.py").write_text((s.root / "agent" / "store.py").read_text() + "# edited\n")
    assert s.cli("run", "--purpose", "candidate", "--variable", "prompt=v2") == 0
    d = _decision(s, rc)
    assert _results(d) == {"headline": "pass", "also_requires:end-to-end": "unknown"}
    assert "uncommitted" in d["also_requires"][0]["reason"]


def test_also_requires_needs_end_to_end_runs_that_reach_the_component(two_evals):
    """The handoff frame says which end-to-end use cases reach the subagent; a candidate end to end
    that ran none of them never ran it."""
    s = two_evals
    ev = Evals(s.agent)
    m = _manifest(ev)
    for x in m["exports"]:
        if x["id"] == "refund-handoffs-2026-10":
            x["handoffs"].update(source_use_cases={"refund": 32})
    ev.p("data", "export.manifest.json").write_text(json.dumps(m))
    rc = _refunds_candidate(s, "--variable", "prompt=v2")
    assert s.cli("run", "--purpose", "candidate", "--variable", "prompt=v2", "--use-case", "order-status") == 0
    d = _decision(s, rc)
    assert _results(d) == {"headline": "pass", "also_requires:end-to-end": "unknown"}
    assert "never ran it" in d["also_requires"][0]["reason"]
    # the same change run on every use case end to end: the gate is tested
    assert s.cli("run", "--purpose", "candidate", "--variable", "prompt=v2") == 0
    d = _decision(s, rc)
    assert _results(d)["also_requires:end-to-end"] == "pass" and d["result"] == "pass"


# ---- the do-nothing screen reads judges (carried from stage 5) ------------------------------------

ONLY_OK_JUDGE = '''import json, sys
payload = json.load(sys.stdin)
print(json.dumps({"verdict": "pass" if str(payload["input"].get("end.output")) == "ok" else "fail"}))
'''


def test_a_use_case_only_a_judge_grades_passes_screening_with_judges(tmp_path, monkeypatch):
    """The end state of every case is graded by a judge alone: the code checks that remain pass
    anything, so doing nothing passes them. Without --judges no case can clear screening; with
    them, the judge fails the do-nothing run and the case counts."""
    s = make_store(tmp_path, monkeypatch)
    _with_judge(s)
    data = yaml.safe_load((s.eval / "eval.yaml").read_text())
    for fm in data["measurement"]["failure_modes"]:
        fm.pop("diagnostics", None)  # no code check left on the end state
    (s.eval / "eval.yaml").write_text(yaml.safe_dump(data, sort_keys=False))
    (s.root / "judge.py").write_text(ONLY_OK_JUDGE)
    _label_judge(s, (60, 60), (400, 400))
    assert s.cli("draw", "--n", "refund=2", "--n", "order-status=2", "--n", "return=2", "--n", "address=2") == 0
    assert s.cli("screen", "--read-by", "tester", "--all") == 0
    cases = s.ev().cases()
    assert cases and not any(passes(c["screen"]) for c in cases)
    sc = cases[0]["screen"]
    assert sc["donothing_fails"] is False and any("screen with --judges" in n for n in sc["notes"])
    assert s.cli("screen", "--judges", "--read-by", "tester", "--all") == 0
    cases = s.ev().cases()
    assert all(passes(c["screen"]) for c in cases), cases[0]["screen"]
    sc = cases[0]["screen"]
    assert sc["donothing_fails"] is True and sc["reference_passes"] is True


def test_a_judge_that_passes_doing_nothing_still_fails_the_screen(tmp_path, monkeypatch):
    s = make_store(tmp_path, monkeypatch)
    _with_judge(s)  # its judge fails only the answer "wrong", so an empty reply passes it
    data = yaml.safe_load((s.eval / "eval.yaml").read_text())
    for fm in data["measurement"]["failure_modes"]:
        fm.pop("diagnostics", None)
    (s.eval / "eval.yaml").write_text(yaml.safe_dump(data, sort_keys=False))
    _label_judge(s, (60, 60), (400, 400))
    assert s.cli("draw", "--n", "refund=2", "--n", "order-status=1", "--n", "return=1", "--n", "address=1") == 0
    assert s.cli("screen", "--judges", "--read-by", "tester", "--all") == 0
    sc = s.ev().cases()[0]["screen"]
    assert sc["donothing_fails"] is False and sc["reference_passes"] is True and not passes(sc)


# ---- build and components, around the four parts -------------------------------------------------

BOUNDARIES = """boundaries:
  - {id: invite-sender, kind: subagent, context: own, ships_separately: true, use_case: Schedule a meeting,
     owner: mail team}
  - {id: date-parser, kind: step, context: shared}
"""


def test_build_drafts_a_2_0_agent_from_the_discovery_report(tmp_path, capsys):
    agent = tmp_path / "repo" / "evals" / "agents" / "cal"
    agent.mkdir(parents=True)
    text = (FIXTURE / "evals" / "discovery.md").read_text().replace("minutes: 2\n", "minutes: 2\n" + BOUNDARIES, 1)
    (agent / "discovery.md").write_text(text)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path / "repo", check=True)
    assert cli.main(["--evals", str(agent), "build"]) == 0
    out = capsys.readouterr().out
    ev = Evals(agent)
    assert not ev.has_v1_suite and [e.id for e in ev.evals()] == ["end-to-end", "invite-sender"]
    e2e = ev.eval("end-to-end").spec()
    ucs = e2e.part("estimand")["use_cases"]
    assert [(u["id"], u["share"], u["cost"]) for u in ucs] == [
        ("schedule-a-meeting", 0.6, None), ("leave-the-calendar-alone", 0.4, None)]
    assert e2e.part("estimand")["share_source"] == "discovery"
    (fm,) = e2e.part("measurement")["failure_modes"]
    assert fm["check"] == build.DEFAULT_CHECK and fm["side_effect"] is True and fm["use_cases"] == "*"
    assert ev.eval("end-to-end").code_check_path(build.DEFAULT_CHECK).exists()
    cov = yaml.safe_load(ev.p("end-to-end", "coverage.yaml").read_text())
    assert [x["id"] for x in cov["entries"]][:2] == ["situation.unanswerable", "situation.ambiguous"]
    comps = {c["id"]: c for c in boundaries.inventory(ev.agent())}
    assert comps["invite-sender"]["ships_separately"] is True and comps["date-parser"]["context"] == "shared"
    unit = ev.eval("invite-sender").spec().part("estimand")["unit"]
    assert unit == {"kind": "component", "component": "invite-sender", "boundary": None}
    assert "end-to-end:" in out and "invite-sender:" in out and "Context boundaries" in out
    assert "[ ] Estimand" in out and "[x] Measurement model" not in out.split("invite-sender:")[1]
    assert "date-parser runs inside the orchestrator's context" in out
    # running it again changes nothing
    before = {p: p.read_text() for p in agent.rglob("*.yaml")}
    assert cli.main(["--evals", str(agent), "build"]) == 0
    assert {p: p.read_text() for p in agent.rglob("*.yaml")} == before
    assert "drafted" not in capsys.readouterr().out


def test_build_run_reaches_a_baseline_per_eval(tmp_path, monkeypatch, capsys):
    s = make_store(tmp_path, monkeypatch)
    assert s.cli("draw", "--n", "refund=2", "--n", "order-status=2", "--n", "return=2", "--n", "address=2") == 0
    assert s.cli("screen", "--read-by", "tester", "--all") == 0
    s.commit()
    capsys.readouterr()
    assert cli.main(["--evals", str(s.agent), "build", "--run"]) == 0
    out = capsys.readouterr().out
    # agent.yaml places the refund subagent at an eval of its own: build creates it, not ready to run
    assert (s.agent / "refund-subagent" / "eval.yaml").exists()
    assert "refund-subagent: not ready to run yet" in out
    assert Evals(s.agent).eval("end-to-end").baseline_runs()
    assert (s.eval / "report" / "report.json").exists()


def test_the_component_checklist_reads_the_evals(tmp_path, monkeypatch):
    s = make_store(tmp_path, monkeypatch)
    ev = Evals(s.agent)
    by = {c["id"]: c for c in components.checklist(ev)}
    assert len(by) == len(components.COMPONENTS)
    assert [c["part"] for c in components.checklist(ev)][0] == components.CONTRACT
    assert {c["part"] for c in components.checklist(ev)} == set(components.PARTS)
    assert by["boundaries"]["state"] == "partial" and "no eval yet for refund-subagent" in by["boundaries"]["why"]
    assert by["handoff-frames"]["state"] == "n/a" and by["change-scoping"]["state"] == "n/a"
    assert by["deterministic"]["state"] == "done" and by["judges"]["state"] == "n/a"
    assert by["golden"]["state"] == "todo" and by["engine"]["state"] == "todo"
    assert cli.main(["--evals", str(s.agent), "init", "--component", "refund-subagent"]) == 0
    by = {c["id"]: c for c in components.checklist(Evals(s.agent))}
    assert by["boundaries"]["state"] == "done"
    assert by["handoff-frames"]["state"] == "todo" and "handoffs" in by["handoff-frames"]["why"]
    assert by["change-scoping"]["state"] == "todo"  # its also_requires has no margin yet


def test_the_discovery_page_shows_where_the_evals_go():
    from aot_evals.start import discovery_body, split_front_matter

    text = (FIXTURE / "evals" / "discovery.md").read_text().replace("minutes: 2\n", "minutes: 2\n" + BOUNDARIES, 1)
    fm, body = split_front_matter(text)
    html = discovery_body(fm, body, "cal")
    assert "Where the evals go" in html and "An eval of its own" in html and "Checks in the end-to-end eval" in html


def test_the_component_eval_runs_its_own_invoke(two_evals):
    """A component eval invokes the component, never the system (v2-design §2)."""
    m = Evals(two_evals.agent).eval("refunds").runs("baseline")[-1]
    assert m["invoke"]["command"][-1] == "agent/refunds.py"
    e2e = Evals(two_evals.agent).eval("end-to-end").runs("baseline")[-1]
    assert e2e["invoke"]["command"][-1] == "agent/store.py"
