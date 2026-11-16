"""`aot-evals build` (build.py): a baseline with one generic check, and the component checklist,
on the store (examples/store). Drafting a new agent from its discovery report is test_components'."""

from __future__ import annotations

import json
import shutil

import yaml

from aot_evals import build, cli, components
from aot_evals.repo import Evals

LIGHTEST_MODES = [{"id": build.DEFAULT_MODE, "description": "The world doesn't end as the case expects.",
                   "use_cases": "*", "check": build.DEFAULT_CHECK, "side_effect": True}]


def test_build_run_reaches_a_baseline_with_only_the_generic_check(store_repo, capsys):
    s = store_repo
    # strip the store to the lightest Build: one eval, cases with expected end states, and only the
    # generic check `build` writes
    shutil.rmtree(s.agent / "refund-subagent")
    agent = yaml.safe_load((s.agent / "agent.yaml").read_text())
    agent["components"] = [c for c in agent["components"] if c["id"] != "refund-subagent"]
    (s.agent / "agent.yaml").write_text(yaml.safe_dump(agent, sort_keys=False))
    spec = yaml.safe_load((s.agent / "end-to-end" / "eval.yaml").read_text())
    spec["measurement"]["failure_modes"] = LIGHTEST_MODES
    (s.agent / "end-to-end" / "eval.yaml").write_text(yaml.safe_dump(spec, sort_keys=False))
    code = s.agent / "end-to-end" / "checks" / "code"
    shutil.rmtree(code)
    code.mkdir()
    shutil.copyfile(build.TEMPLATES / "checks" / f"{build.DEFAULT_CHECK}.py", code / f"{build.DEFAULT_CHECK}.py")
    s.commit("the lightest eval")
    capsys.readouterr()
    assert cli.main(["--evals", str(s.agent), "build", "--run"]) == 0
    out = capsys.readouterr().out
    assert "aot-evals serve" in out
    ev = s.ev()
    base = ev.latest_run("baseline")
    assert base and base["k"] == 3
    lines = [r for r in ev.run_records(base["run_id"]) if r.get("kind") == "check"]
    assert lines and all(r["check_id"] == build.DEFAULT_CHECK for r in lines)
    # it is strict: the store's world keeps a log of calls the cases' expected worlds don't
    # reproduce, which is why the template says to replace it with checks on what matters
    assert any(r["passed"] for r in lines)
    assert all("log" in r["detail"] for r in lines if not r["passed"])
    assert (ev.p("report", "report.json")).exists()
    items = {it["item"]: it for it in build.eval_checklist(ev)}
    assert items["A baseline, every case k times"]["done"]


def test_the_generic_check_fails_a_wrong_end_state_and_ignores_the_reply():
    import importlib.util

    spec = importlib.util.spec_from_file_location("c", build.TEMPLATES / "checks" / f"{build.DEFAULT_CHECK}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    case = {"expected_end_state": {"world": {"events": [1, 2]}}}
    assert mod.check({}, {"world": {"events": [1, 2]}, "output": "anything"}, case)[0] is True
    ok, detail = mod.check({}, {"world": {"events": [1]}, "output": "Done! Booked."}, case)
    assert ok is False and "events" in detail
    assert mod.check({}, {"world": None}, {"expected_end_state": {"world": None}})[0] is True


ASSESSMENT = """---
minutes: 4
components:
  engine: {state: partial, note: a CI job runs the agent nightly}
  golden: {state: todo, note: none}
---
# The online store (store)
"""


def test_the_component_checklist_reads_the_evals_and_the_assessment(store_repo):
    s = store_repo
    ev = Evals(s.agent)
    by = {c["id"]: c for c in components.checklist(ev)}
    assert len(by) == len(components.COMPONENTS)
    assert by["golden"]["state"] == "done" and "end-to-end: " in by["golden"]["why"]
    assert by["handoff-frames"]["state"] == "done" and by["boundaries"]["state"] == "done"
    assert by["deterministic"]["state"] == "partial"  # the refund subagent's policy judge counts
    assert by["judges"]["state"] == "done"  # and it is calibrated
    assert by["engine"]["state"] == "todo" and by["grader-ui"]["state"] == "todo"
    assert by["fakes"]["state"] == "done"  # the order system and payments are fakes in env/
    assert by["trace-monitoring"]["state"] == "later"
    # the assessment may say more than the evals do yet, never less
    (s.agent / "discovery.md").write_text(ASSESSMENT)
    by = {c["id"]: c for c in components.checklist(ev)}
    assert by["engine"]["state"] == "partial" and "nightly" in by["engine"]["why"]
    assert by["golden"]["state"] == "done"
    from aot_evals.start import components_html, split_front_matter

    html = components_html(split_front_matter(ASSESSMENT)[0]["components"])
    assert "The components to build" in html and "nightly" in html and "Partly" in html


def test_components_json_matches_the_checklist(store_repo, capsys):
    s = store_repo
    capsys.readouterr()
    assert cli.main(["--evals", str(s.agent), "components", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == components.checklist(Evals(s.agent))
