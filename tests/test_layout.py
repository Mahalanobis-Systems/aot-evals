"""Where an agent's evals live: evals/agents/<agent>/ beside its discovery report, several agents
per repository (docs/v2-design.md §1), with paths resolved from the repository root.

Nesting agents by hand (evals/a, evals/b) made invoke.cwd resolve from evals/, and commits to
one agent's evals moved the other agent's agent_commit.
"""

from __future__ import annotations

import json
import shutil

import pytest

from aot_evals import cli
from aot_evals.evidence import manifest_problems
from aot_evals.judges import _repo_root, load_spec
from aot_evals.repo import Evals
from aot_evals.util import ContractError


def test_find_picks_the_only_agent_and_asks_when_there_are_several(tmp_path, monkeypatch):
    (tmp_path / "evals/agents/support").mkdir(parents=True)
    (tmp_path / "evals/agents/support/discovery.md").write_text("# support\n")
    monkeypatch.chdir(tmp_path)
    assert Evals.find().root == (tmp_path / "evals/agents/support").resolve()

    (tmp_path / "evals/agents/billing").mkdir()
    with pytest.raises(ContractError, match="several agents.*--agent"):
        Evals.find()
    assert Evals.find(agent="billing").root == (tmp_path / "evals/agents/billing").resolve()
    # --evals evals/ names the folder of agents, not one agent
    with pytest.raises(ContractError, match="several agents"):
        Evals.find(str(tmp_path / "evals"))
    assert Evals.find(str(tmp_path / "evals"), "billing").root == (tmp_path / "evals/agents/billing").resolve()

    monkeypatch.chdir(tmp_path / "evals/agents/billing")  # inside an agent's folder: that agent
    assert Evals.find().root.name == "billing"


def test_init_creates_the_end_to_end_eval_beside_the_discovery_report(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit, match="--agent NAME"):  # no discovery report and no --agent
        cli.main(["init"])
    assert not (tmp_path / "evals").exists()
    assert cli.main(["--agent", "support", "init"]) == 0
    agent = tmp_path / "evals/agents/support"
    assert (agent / "agent.yaml").exists() and (agent / "labels/standard.md").exists()
    assert (agent / "end-to-end/eval.yaml").exists()
    ev = Evals.find()
    assert ev.root == agent.resolve() and ev.repo_root == tmp_path.resolve()
    assert [e.id for e in ev.evals()] == ["end-to-end"]


def _second_agent(s, name: str = "support-copy"):
    """Another agent system in the same repository: a copy of the store's folder."""
    dst = s.root / "evals" / "agents" / name
    shutil.copytree(s.agent, dst, ignore=shutil.ignore_patterns("runs", "journal", "report"))
    return dst


def test_several_agents_in_one_repository_and_agent_selects_one(store_repo, monkeypatch, capsys):
    s = store_repo
    other = _second_agent(s)
    monkeypatch.chdir(s.root)
    with pytest.raises(SystemExit, match="several agents.*--agent"):
        cli.main(["status"])
    capsys.readouterr()
    assert cli.main(["--agent", "store", "status"]) == 0
    assert f"agent at {s.agent.resolve()}" in capsys.readouterr().out
    assert cli.main(["--agent", "support-copy", "--eval", "end-to-end", "validate"]) == 0
    capsys.readouterr()
    assert cli.main(["--agent", "support-copy", "status"]) == 0
    assert f"agent at {other.resolve()}" in capsys.readouterr().out
    # each agent keeps its own evals and its own log
    assert cli.main(["--agent", "support-copy", "--eval", "end-to-end", "run", "--purpose", "smoke",
                     "--case", "tr_1204"]) == 0
    assert Evals(other).eval("end-to-end").latest_run("smoke")
    assert not s.ev().latest_run("smoke")
    assert (other / "journal" / "activity.jsonl").exists()


def test_an_agent_resolves_paths_from_the_repository_root(store_repo):
    s = store_repo
    ev = s.ev()
    assert ev.repo_root == s.root and ev.evals_dir == s.root / "evals"
    assert ev.agent_system.root == s.agent and ev.root == s.agent / "end-to-end"
    # invoke.cwd is "." and the agent lives at agent/store.py in the repository root
    assert s.cli("run", "--purpose", "smoke", "--case", "tr_1204") == 0
    assert s.ev().latest_run("smoke")["counts"].get("ok", 0) == 1
    # the component eval's own invoke resolves from the same root
    assert s.cli("run", "--purpose", "smoke", "--case", "tr_1231.h0", eval_id="refund-subagent") == 0
    assert s.ev("refund-subagent").latest_run("smoke")["counts"].get("ok", 0) == 1


def test_command_judge_runs_from_the_repository_root(store_repo):
    s = store_repo
    path = s.agent / "end-to-end/checks/judge/j.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("---\nid: j\nfailure_mode: x\nversion: 1\nquestion_type: noul\nquestion: q\n"
                    "detects: failure\ninputs: [end.output]\nbackends:\n  mine:\n    type: command\n"
                    "    command: [python, judge.py]\n    cwd: missing\n    model: m\n    family: f\n"
                    "---\nbody\n")
    spec = load_spec(path)
    assert _repo_root(spec) == s.root.resolve()
    assert any("cwd 'missing'" in p for p in spec.problems())


def test_another_agents_eval_commits_do_not_move_agent_commit(store_repo):
    s = store_repo
    assert s.cli("run", "--purpose", "smoke", "--case", "tr_1204") == 0
    first = s.ev().latest_run("smoke")
    other = s.root / "evals/agents/other"
    other.mkdir(parents=True)
    (other / "notes.md").write_text("another agent's evals\n")
    (s.root / "evals/scripts").mkdir()
    (s.root / "evals/scripts/label_page.py").write_text("print('hi')\n")
    s.commit("evals for another agent")
    assert s.cli("run", "--purpose", "smoke", "--case", "tr_1204", "--label", "again") == 0
    runs = s.ev().runs("smoke")
    second = next(m for m in runs if m["run_id"] != first["run_id"])
    assert second["agent_commit"] == first["agent_commit"], json.dumps([first, second])[:400]


def test_an_agent_that_reads_the_cases_is_caught(store_repo):
    s = store_repo
    s.set_env(AGENT_VARIANT="peek")  # a coding harness can grep for its own case
    s.commit("peek")
    assert s.cli("run", "--purpose", "baseline", "--case", "tr_1204") == 0
    m = s.ev().latest_run("baseline")
    exposure = m["eval_exposure"]
    assert not exposure["isolated"] and exposure["changed"] == ["cases/address/tr_1204.json"]
    assert exposure["mentioned"] and "tr_1204.json" in exposure["mentioned"][0]["files"]
    probs = manifest_problems(m)
    assert any("eval files changed" in p for p in probs) and any("names eval files" in p for p in probs)


def test_an_isolated_run_cannot_see_the_cases(store_repo):
    s = store_repo
    s.set_env(AGENT_VARIANT="peek")
    path = s.agent / "agent.yaml"
    path.write_text(path.read_text().replace("  cwd: .\n", "  cwd: .\n  isolate: true\n"))
    s.commit("isolate")
    assert s.cli("run", "--purpose", "baseline", "--use-case", "address") == 0
    m = s.ev().latest_run("baseline")
    assert m["eval_exposure"] == {"isolated": True, "changed": [], "mentioned": []}
    assert m["counts"].get("ok") and not manifest_problems(m)
    assert m["agent_commit"]  # from the repository, not the copy (which has no .git)
    first = next(r for r in s.ev().run_records(m["run_id"]) if r["kind"] == "attempt")
    assert first["outcome"] == "ok"


def test_snapshot_covers_the_whole_working_tree(store_repo, monkeypatch, capsys):
    s = store_repo
    (s.root / "answer.md").write_text("written outside the agent's folders\n")
    (s.root / "out").mkdir()
    (s.root / "out/run.log").write_text("a run output\n")
    monkeypatch.chdir(s.root)
    capsys.readouterr()
    assert cli.main(["snapshot", "--exclude", "out/*"]) == 0
    files = json.loads(capsys.readouterr().out)["files"]
    assert "answer.md" in files and "agent/store.py" in files
    assert not [f for f in files if f.startswith(("evals/", "out/", ".git/"))]
    assert "world.json" not in files  # git-ignored
