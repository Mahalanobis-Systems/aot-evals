"""`aot-evals migrate --to 2` (docs/v2-design.md §8): a 1.x suite becomes a 2.0 agent folder with one
eval, end-to-end, in each of the three places a 1.x suite can be. The suites are built inline."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
import yaml
from conftest import git

from aot_evals import cli
from aot_evals.repo import Evals

AGENT = """# the agent under test
id: {id}
description: a toy agent
validity:
  task:
  judge:
simulator: null
invoke:
  command: [python3, agent.py]
  timeout: 10
"""
CATEGORIES = {"categories": [
    {"id": "lookup", "definition": "Find a record", "example": "t1", "worth": "high", "simple": True,
     "heuristic": "the request names a record", "cost": {"incorrect": "high"}, "observed_share": 0.7,
     "share_source": "traces"},
    {"id": "write", "definition": "Change a record", "example": "t2", "worth": "medium",
     "cost": {"incorrect": "high"}, "observed_share": 0.3, "share_source": "traces"},
]}
FAILURE_MODES = {"failure_modes": [
    {"id": "wrong-answer", "description": "The answer is wrong", "categories": ["lookup"], "check_type": "code",
     "checks": ["answer-matches", "answer-not-empty"], "cost_cell": "incorrect", "feature": "f", "scenario": "s"},
    {"id": "unfaithful", "description": "Says what the docs don't", "categories": "*", "check_type": "judge",
     "checks": ["judge-faithful"]},
    {"id": "side-effect", "description": "Changed something unasked", "categories": ["*"], "check_type": "code",
     "checks": ["no-side-effects"], "side_effect": True},
    {"id": "slow", "description": "Too slow", "categories": "*", "check_type": "monitor", "checks": []},
]}
BUDGETS = {"default": {"latency_p90_ms": 30000}, "categories": {"write": {"error_rate": 0.02}}}
ALLOCATION = {"assumptions": {"k": 5}, "cells": [
    {"category": "write", "set": "error_finding", "status": "scheduled", "reason": "later"},
    {"category": "lookup", "set": "quality_estimate", "status": "filled", "reason": None}]}
JUDGE = "---\nid: judge-faithful\nversion: 1\nquestion: Faithful?\nmin_tpr: 0.85\nmin_tnr: 0.85\n---\nBody.\n"
CHECK = "def check(start, end, case):\n    return True, ''\n"


def make_v1(root: Path, suite: Path, agent_id: str = "toy", floors: bool = True) -> Path:
    """A small 1.x suite at `suite`, in a git repository at `root`."""
    suite.mkdir(parents=True)
    (suite / "agent.yaml").write_text(AGENT.format(id=agent_id))
    for name, data in (("categories.yaml", CATEGORIES), ("failure_modes.yaml", FAILURE_MODES),
                       ("budgets.yaml", BUDGETS), ("allocation.yaml", ALLOCATION),
                       ("taxonomy.yaml", {"source": "the product spec", "entries": [{"id": "e1"}]})):
        (suite / name).write_text(yaml.safe_dump(data, sort_keys=False))
    for cid in ("answer-matches", "answer-not-empty", "no-side-effects"):
        (suite / "checks" / "code").mkdir(parents=True, exist_ok=True)
        (suite / "checks" / "code" / f"{cid}.py").write_text(CHECK)
    (suite / "checks" / "judge").mkdir(parents=True)
    (suite / "checks" / "judge" / "judge-faithful.md").write_text(JUDGE)
    for uc, cid, s in (("lookup", "l1", "quality_estimate"), ("lookup", "l2", "error_finding"),
                       ("write", "w1", "error_finding")):
        (suite / "cases" / uc).mkdir(parents=True, exist_ok=True)
        (suite / "cases" / uc / f"{cid}.json").write_text(json.dumps(
            {"id": cid, "category": uc, "set": s, "taxonomy_entries": ["e1"], "trigger": {"text": "hi"}}))
    (suite / "labels").mkdir()
    (suite / "labels" / "standard.md").write_text("# Standard\n")
    (suite / "labels" / "runs.jsonl").write_text('{"item_id": "r/l1.t1.a1", "label": true}\n')
    if floors:
        (suite / "labels" / "floors.yaml").write_text("min_catch: 0.8\nmin_clean: 0.9\nmin_each: 20\n")
    (suite / "env").mkdir()
    (suite / "env" / "world.json").write_text("{}")
    (suite / "data").mkdir()
    (suite / "data" / "export.manifest.json").write_text(json.dumps({"exports": [
        {"id": "old", "window": "2026-08-01..2026-08-31"},
        {"id": "traces", "window": "2026-09-01..2026-09-30"}]}))
    (suite / "runs" / "r1").mkdir(parents=True)
    (suite / "runs" / "r1" / "manifest.json").write_text(
        json.dumps({"run_id": "r1", "schema": "aot-evals/run-manifest@1"}))
    (suite / "runs" / "r1" / "raw").mkdir()
    (suite / "runs" / "r1" / "raw" / "x.json").write_text("{}")  # git-ignored: moves with its folder
    (suite / ".gitignore").write_text("runs/*/raw/\n__pycache__/\n")
    (suite / "journal").mkdir()
    (suite / "journal" / "activity.jsonl").write_text('{"ts": "2026-09-01T00:00:00Z", "kind": "note"}\n')
    git(root, "init", "-q")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "1.x suite")
    return suite


def migrate(path: Path, *extra: str) -> int:
    return cli.main(["--evals", str(path), "migrate", "--to", "2", *extra])


def check_migrated(agent: Path, root: Path) -> dict:
    e = agent / "end-to-end"
    spec = yaml.safe_load((e / "eval.yaml").read_text())
    # the estimand: categories become use cases, traffic weights, costs left for the owner
    est = spec["estimand"]
    assert [(u["id"], u["share"], u["cost"]) for u in est["use_cases"]] == [("lookup", 0.7, None), ("write", 0.3, None)]
    assert est["weights"] == "traffic" and est["share_source"] == "traces" and est["quantity"] == "pass_rate"
    assert est["population"] == {"frame": "traces", "window": "2026-09-01/2026-09-30", "environment": "env/"}
    # the measurement model: the first code check counts; a judge-only mode keeps its judge; a monitor
    fms = {f["id"]: f for f in spec["measurement"]["failure_modes"]}
    assert fms["wrong-answer"]["check"] == "answer-matches"
    assert fms["wrong-answer"]["diagnostics"] == ["answer-not-empty"]
    assert fms["wrong-answer"]["use_cases"] == ["lookup"] and "cost_cell" not in fms["wrong-answer"]
    assert fms["unfaithful"]["check"] == "judge-faithful" and fms["unfaithful"]["use_cases"] == "*"
    assert fms["side-effect"]["side_effect"] is True and fms["side-effect"]["use_cases"] == "*"
    assert fms["slow"]["check"] is None and fms["slow"]["monitor"] is True
    assert spec["measurement"]["people"]["floors"] == {"catch": 0.8, "clean": 0.9}
    assert spec["measurement"]["max_inflation"] == 2.0 and spec["measurement"]["trials"] == 3
    rule = spec["decision_rule"]
    assert (rule["test"], rule["alpha"], rule["power"], rule["looks"]) == ("superiority", 0.05, 0.80, "fixed")
    assert rule["constraints"] == {"default": {"latency_p90_ms": 30000}, "use_cases": {"write": {"error_rate": 0.02}}}
    # cases renamed in place
    case = json.loads((e / "cases" / "lookup" / "l1.json").read_text())
    assert case["use_case"] == "lookup" and case["pool"] == "quality" and case["coverage_entries"] == ["e1"]
    assert not {"category", "set", "taxonomy_entries"} & set(case)
    assert json.loads((e / "cases" / "write" / "w1.json").read_text())["pool"] == "bug_finding"
    # the shared parts and the eval's own
    assert (agent / "labels" / "standard.md").exists() and (agent / "env" / "world.json").exists()
    assert (e / "labels" / "runs.jsonl").exists() and (e / "coverage.yaml").exists()
    assert (e / "runs" / "r1" / "manifest.json").exists() and (e / "runs" / "r1" / "raw" / "x.json").exists()
    assert "min_tpr" not in (e / "checks" / "judge" / "judge-faithful.md").read_text()
    a = yaml.safe_load((agent / "agent.yaml").read_text())
    assert "validity" not in a and "simulator" not in a and a["invoke"]["command"] == ["python3", "agent.py"]
    assert "# the agent under test" in (agent / "agent.yaml").read_text()  # comments kept
    assert yaml.safe_load((e / "plan.yaml").read_text())["rows"] == [
        {"use_case": "write", "pool": "bug_finding", "status": "scheduled", "reason": "later"}]
    for f in ("categories.yaml", "failure_modes.yaml", "budgets.yaml", "allocation.yaml", "floors.yaml"):
        assert (agent / "migrated-from-1x" / f).exists()
    assert "*/runs/*/raw/" in (agent / ".gitignore").read_text()
    # tracked files moved with git, so history follows them
    status = subprocess.run(["git", "status", "--porcelain"], cwd=root, capture_output=True, text=True).stdout
    assert "R  " in status or "RM " in status
    # the spec loads, and is missing only what the owner must say
    ev = Evals(agent)
    assert not ev.has_v1_suite
    s = ev.eval("end-to-end").spec()
    assert {i.field for i in s.missing} == {"estimand.decision.action", "estimand.decision.owner",
                                            "decision_rule.margin"}
    assert s.invalid == []
    md = (agent / "MIGRATION.md").read_text()
    for text in ("superiority", "max_inflation", "the newest import", "the request names a record",
                 "`worth` = `high`", "first code check", "no code check: the first judge", "migrated-from-1x"):
        assert text in md, text
    return spec


def test_migrates_the_flat_one_agent_suite(tmp_path):
    root = tmp_path / "repo"
    evals = make_v1(root, root / "evals")
    (evals / "my_script.py").write_text('open("env/world.json")\n')  # a team's own file: left where it is
    (evals / "agents" / "toy").mkdir(parents=True)
    (evals / "agents" / "toy" / "discovery.md").write_text("# Discovery\n")
    assert migrate(evals) == 0
    agent = evals / "agents" / "toy"
    check_migrated(agent, root)
    assert (evals / "my_script.py").exists() and (evals / ".gitignore").exists()
    assert (agent / "discovery.md").read_text() == "# Discovery\n"
    md = (agent / "MIGRATION.md").read_text()
    assert "`my_script.py`: not a 1.x suite file; left where it was" in md
    assert "my_script.py (left in place) names env/" in md
    assert not (evals / "categories.yaml").exists() and not (evals / "cases").exists()


def test_migrates_the_old_layout(tmp_path):
    root = tmp_path / "repo"
    make_v1(root, root / "evals" / "toy")
    assert migrate(root / "evals") == 0
    check_migrated(root / "evals" / "agents" / "toy", root)
    assert not (root / "evals" / "toy").exists()


def test_migrates_in_place_under_agents(tmp_path):
    root = tmp_path / "repo"
    agent = make_v1(root, root / "evals" / "agents" / "toy", floors=False)
    assert migrate(agent) == 0
    spec = yaml.safe_load((agent / "end-to-end" / "eval.yaml").read_text())
    assert spec["measurement"]["people"]["floors"] == {"catch": None, "clean": None}
    assert "85% / 85% floors are not carried over" in (agent / "MIGRATION.md").read_text()
    assert (agent / "end-to-end" / "cases" / "lookup" / "l1.json").exists() and not (agent / "cases").exists()


def test_a_check_shared_by_two_modes_counts_once(tmp_path):
    root = tmp_path / "repo"
    agent = make_v1(root, root / "evals" / "agents" / "toy")
    fm = yaml.safe_load((agent / "failure_modes.yaml").read_text())
    fm["failure_modes"].append({"id": "empty", "categories": "*", "checks": ["answer-matches"]})
    (agent / "failure_modes.yaml").write_text(yaml.safe_dump(fm))
    assert migrate(agent) == 0
    spec = yaml.safe_load((agent / "end-to-end" / "eval.yaml").read_text())
    empty = next(f for f in spec["measurement"]["failure_modes"] if f["id"] == "empty")
    assert empty["check"] is None and empty["diagnostics"] == ["answer-matches"]
    s = Evals(agent).eval("end-to-end").spec()
    assert "measurement.failure_modes[empty].check" in {i.field for i in s.missing}


def test_dry_run_writes_nothing(tmp_path, capsys):
    root = tmp_path / "repo"
    evals = make_v1(root, root / "evals")
    before = sorted(str(p) for p in root.rglob("*") if ".git" not in p.parts)
    assert migrate(evals, "--dry-run") == 0
    assert sorted(str(p) for p in root.rglob("*") if ".git" not in p.parts) == before
    out = capsys.readouterr().out
    assert "dry run" in out and "mode wrong-answer: counts answer-matches" in out


def test_migrate_needs_to_2(tmp_path):
    with pytest.raises(SystemExit, match="--to 2"):
        cli.main(["--evals", str(tmp_path), "migrate"])
