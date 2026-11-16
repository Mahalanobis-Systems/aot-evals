"""Where each eval stands, its trust, the changes since a baseline and the next step per role
(trust.py, docs/method.md)."""

from __future__ import annotations

import json

import yaml
from conftest import StoreRepo

from aot_evals import cli, components, trust
from aot_evals.repo import Evals


def _status(capsys, *argv: str) -> dict:
    assert cli.main([*argv, "status", "--json"]) == 0
    return json.loads(capsys.readouterr().out)


def _roles(t: dict) -> dict:
    return {st["role"]: st["step"] for st in t["next"]}


def test_no_eval_and_no_discovery_report_is_the_owners_discovery(tmp_path, capsys):
    s = _status(capsys, "--evals", str(tmp_path / "evals" / "agents" / "bot"))
    assert s["stands"] == "no discovery report yet"
    assert "/aot-evals:start" in _roles(s)["owner"]
    assert s["evals"] == []


def test_a_discovery_report_without_an_eval_is_engineerings_build(tmp_path, capsys):
    agent = tmp_path / "evals" / "agents" / "bot"
    agent.mkdir(parents=True)
    (agent / "discovery.md").write_text("# Bot\n")
    s = _status(capsys, "--evals", str(agent))
    assert "no eval yet" in s["stands"]
    assert list(_roles(s)) == ["engineering"] and "aot-evals build" in _roles(s)["engineering"]


def test_an_eval_without_a_baseline_is_untested_and_engineering_runs_it(store_repo: StoreRepo):
    t = trust.eval_trust(store_repo.ev("end-to-end"))
    assert t["stands"] == "no baseline has run"
    assert t["level"] == "untested"
    assert "run --purpose baseline" in _roles(t)["engineering"]


def test_a_baseline_makes_the_eval_provisional_and_hands_labelling_to_people(store_repo: StoreRepo, capsys):
    s = store_repo
    assert s.cli("run", "--purpose", "baseline") == 0
    t = trust.eval_trust(s.ev("end-to-end"))
    assert t["stands"] == "a number under the current spec, not yet held to people"
    assert t["level"] == "provisional"
    assert "aot-evals --eval end-to-end serve" in _roles(t)["graders"]
    assert t["theta"] is not None
    assert t["conditions"] == {"spec": True, "estimate": True, "judges": True, "people": False,
                               "sized": None}
    why = " ".join(t["why"])
    assert "not held to people" in why
    # a paired rule is sized from the flip rate, which no comparison has measured yet
    assert "can't size the decision rule yet" in why and "--flip-rate" in why
    # once a comparison has measured it, the plan sizes the rule and the quality set falls short
    comp = s.agent / "end-to-end" / "report" / "comparisons"
    comp.mkdir(parents=True)
    (comp / "c.json").write_text(json.dumps({"generated": "2026-11-14T00:00:00Z", "refused": None,
                                             "candidate_runs": [], "flips": {"flip_rate": 0.05}}))
    t = trust.eval_trust(s.ev("end-to-end"))
    assert t["conditions"]["sized"] is False
    assert "the decision rule needs about" in " ".join(t["why"])
    capsys.readouterr()
    out = _status(capsys, "--evals", str(s.agent), "--eval", "end-to-end")
    assert [e["eval"] for e in out["evals"]] == ["end-to-end"]
    assert out["evals"][0]["complete"] is True  # the spec's fields ride along
    assert cli.main(["--evals", str(s.agent), "status"]) == 0
    text = capsys.readouterr().out
    assert "2 eval(s): 1 untested, 1 provisional" in text
    assert "end-to-end: provisional" in text and "refund-subagent: untested" in text
    assert "next for the people who know what good looks like: label whole runs" in text
    assert "next for engineering:" in text


def test_a_changed_estimand_is_a_revision_since_the_baseline(store_repo: StoreRepo):
    s = store_repo
    assert s.cli("run", "--purpose", "baseline") == 0
    path = s.agent / "end-to-end" / "eval.yaml"
    spec = yaml.safe_load(path.read_text())
    spec["estimand"]["use_cases"][0]["cost"] = 2
    path.write_text(yaml.safe_dump(spec, sort_keys=False))
    ev = Evals(s.agent).eval("end-to-end")
    ch = trust.changes(ev)
    assert [c["kind"] for c in ch] == ["revision"]
    assert ch[0]["parts"] == ["estimand"]
    t = trust.eval_trust(ev)
    assert t["level"] == "untested"
    assert t["stands"] in ("no baseline has run", "no number under the current spec yet")
    assert trust.summary(Evals(s.agent))["evals"][0]["next"][0]["role"] == "engineering"  # the re-run first


def test_a_changed_agent_since_the_baseline_points_at_a_candidate(store_repo: StoreRepo):
    s = store_repo
    assert s.cli("run", "--purpose", "baseline") == 0
    prompt = s.root / "agent" / "store_prompt.md"
    prompt.write_text(prompt.read_text() + "\nBe brief.\n")
    kinds = [c["kind"] for c in trust.changes(s.ev("end-to-end"))]
    assert kinds == ["agent-uncommitted"]
    s.commit("prompt")
    ch = trust.changes(s.ev("end-to-end"))
    assert [c["kind"] for c in ch] == ["agent"]
    assert "--purpose candidate" in ch[0]["next"]


def test_components_rows_carry_their_role(store_repo: StoreRepo):
    rows = components.checklist(Evals(store_repo.agent))
    by = {r["id"]: r for r in rows}
    assert {r["role"] for r in rows} == {"owner", "engineering", "graders"}
    assert by["weighting"]["role"] == "owner"   # the estimand
    assert by["golden"]["role"] == "engineering"       # the sampling design
    assert by["deterministic"]["role"] == "engineering"  # the checks
    assert by["misclassification"]["role"] == "graders"  # the error rates
    assert all(r["group"] == r["part"] for r in rows)  # the grader application reads group
