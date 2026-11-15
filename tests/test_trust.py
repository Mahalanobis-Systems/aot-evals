"""The phases, trust per eval and the changes since a baseline (trust.py, docs/method.md §12)."""

from __future__ import annotations

import json

import yaml
from conftest import StoreRepo

from aot_evals import cli, components, trust
from aot_evals.repo import Evals


def _status(capsys, *argv: str) -> dict:
    assert cli.main([*argv, "status", "--json"]) == 0
    return json.loads(capsys.readouterr().out)


def test_no_eval_and_no_discovery_report_is_assess(tmp_path, capsys):
    s = _status(capsys, "--evals", str(tmp_path / "evals" / "agents" / "bot"))
    assert s["phase"]["id"] == "assess"
    assert s["phase"]["settles"] == ["estimand"]
    assert s["evals"] == []


def test_a_discovery_report_without_an_eval_is_build(tmp_path, capsys):
    agent = tmp_path / "evals" / "agents" / "bot"
    agent.mkdir(parents=True)
    (agent / "discovery.md").write_text("# Bot\n")
    s = _status(capsys, "--evals", str(agent))
    assert s["phase"]["id"] == "build"
    assert s["phase"]["done"] == ["Assess"]
    assert "aot-evals build" in s["phase"]["next"]


def test_an_eval_without_a_baseline_is_build_and_untested(store_repo: StoreRepo):
    t = trust.eval_trust(store_repo.ev("end-to-end"))
    assert t["phase"]["id"] == "build"
    assert t["level"] == "untested"
    assert "run --purpose baseline" in t["phase"]["next"]


def test_a_baseline_moves_the_eval_to_judge_provisional_with_its_reasons(store_repo: StoreRepo, capsys):
    s = store_repo
    assert s.cli("run", "--purpose", "baseline") == 0
    t = trust.eval_trust(s.ev("end-to-end"))
    assert t["phase"]["id"] == "judge"
    assert t["level"] == "provisional"
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
    assert out["evals"][0]["complete"] is True  # the spec's fields ride along, as before
    assert out["phase"]["id"] == "build"  # the agent's phase is its earliest eval's: refund-subagent has no baseline
    assert cli.main(["--evals", str(s.agent), "status"]) == 0
    text = capsys.readouterr().out
    assert "end-to-end: Judge, provisional" in text
    assert "refund-subagent: Build, untested" in text


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
    assert t["level"] == "untested" and t["phase"]["id"] == "build"


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


def test_components_rows_carry_their_phase(store_repo: StoreRepo):
    rows = components.checklist(Evals(store_repo.agent))
    by = {r["id"]: r for r in rows}
    assert {r["phase"] for r in rows} == {"assess", "build", "judge"}
    assert by["weighting"]["phase"] == "assess"   # the estimand
    assert by["golden"]["phase"] == "build"       # the sampling design
    assert by["deterministic"]["phase"] == "build"  # the checks
    assert by["misclassification"]["phase"] == "judge"  # the error rates
    assert all(r["group"] == r["part"] for r in rows)  # the grader application reads group
