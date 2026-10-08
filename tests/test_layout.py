"""Where a suite lives: evals/agents/<agent>/ beside its discovery report, several per repository.

Nesting suites by hand (evals/a, evals/b) made invoke.cwd resolve from evals/, and commits to
one suite moved the other agent's agent_commit.
"""

from __future__ import annotations

import json

import pytest

from aot_evals import cli, gates
from aot_evals.judges import _repo_root, load_spec
from aot_evals.repo import Evals
from aot_evals.util import ContractError

NESTED = "evals/agents/calendar"


def test_find_picks_the_only_agent_and_asks_when_there_are_several(tmp_path, monkeypatch):
    (tmp_path / "evals/agents/support").mkdir(parents=True)
    (tmp_path / "evals/agents/support/discovery.md").write_text("# support\n")
    monkeypatch.chdir(tmp_path)
    assert Evals.find().root == (tmp_path / "evals/agents/support").resolve()

    (tmp_path / "evals/agents/billing").mkdir()
    with pytest.raises(ContractError, match="several agents.*--agent"):
        Evals.find()
    assert Evals.find(agent="billing").root == (tmp_path / "evals/agents/billing").resolve()

    monkeypatch.chdir(tmp_path / "evals/agents/billing")  # inside a suite: that suite
    assert Evals.find().root.name == "billing"


def test_find_keeps_the_one_agent_layout(tmp_path, monkeypatch):
    (tmp_path / "evals").mkdir()
    (tmp_path / "evals/agent.yaml").write_text("id: x\n")
    monkeypatch.chdir(tmp_path)
    ev = Evals.find()
    assert ev.root == (tmp_path / "evals").resolve()
    assert ev.repo_root == tmp_path.resolve() and ev.evals_dir == ev.root


def test_init_creates_the_suite_beside_the_discovery_report(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit, match="--agent NAME"):  # no discovery report and no --agent
        cli.main(["init"])
    assert not (tmp_path / "evals").exists()
    assert cli.main(["--agent", "support", "init"]) == 0
    suite = tmp_path / "evals/agents/support"
    assert (suite / "agent.yaml").exists() and (suite / "cases").is_dir()
    ev = Evals.find()
    assert ev.root == suite.resolve() and ev.repo_root == tmp_path.resolve()


def test_nested_suite_resolves_paths_from_the_repository_root(make_repo):
    repo = make_repo(suite=NESTED)
    ev = Evals(repo.evals)
    assert ev.repo_root == repo.root and ev.evals_dir == repo.root / "evals"
    # invoke.cwd is "." and the agent lives at agent/agent.py in the repository root
    assert repo.cli("run", "--purpose", "smoke", "--case", "book-001") == 0
    smoke = ev.latest_run("smoke")
    assert smoke["counts"].get("ok", 0) == 1
    c1 = next(g for g in gates.evaluate(ev) if g.id == "C1")
    assert not [p for p in c1.problems if "invoke.cwd" in p]


def test_c1_flags_an_invoke_cwd_that_does_not_exist(make_repo):
    repo = make_repo(suite=NESTED)
    text = (repo.evals / "agent.yaml").read_text().replace("cwd: .", "cwd: no-such-dir")
    (repo.evals / "agent.yaml").write_text(text)
    c1 = next(g for g in gates.evaluate(Evals(repo.evals)) if g.id == "C1")
    assert any("invoke.cwd 'no-such-dir'" in p for p in c1.problems)


def test_command_judge_runs_from_the_repository_root(make_repo):
    repo = make_repo(suite=NESTED)
    (repo.evals / "checks/judge").mkdir(parents=True, exist_ok=True)
    path = repo.evals / "checks/judge/j.md"
    path.write_text("---\nid: j\nfailure_mode: x\nversion: 1\nquestion_type: noul\nquestion: q\n"
                    "detects: failure\ninputs: [end.output]\nbackends:\n  mine:\n    type: command\n"
                    "    command: [python, judge.py]\n    cwd: missing\n    model: m\n    family: f\n"
                    "---\nbody\n")
    spec = load_spec(path)
    assert _repo_root(spec) == repo.root.resolve()
    assert any("cwd 'missing'" in p for p in spec.problems())


def test_another_agents_eval_commits_do_not_move_agent_commit(make_repo):
    repo = make_repo(suite=NESTED)
    assert repo.cli("run", "--purpose", "smoke", "--case", "book-001") == 0
    first = Evals(repo.evals).latest_run("smoke")
    other = repo.root / "evals/agents/other"
    other.mkdir(parents=True)
    (other / "notes.md").write_text("another agent's suite\n")
    (repo.root / "evals/scripts").mkdir()
    (repo.root / "evals/scripts/label_page.py").write_text("print('hi')\n")
    repo.commit("evals for another agent")
    assert repo.cli("run", "--purpose", "smoke", "--case", "book-001", "--label", "again") == 0
    runs = [m for m in Evals(repo.evals).runs() if m.get("purpose") == "smoke"]
    second = next(m for m in runs if m["run_id"] != first["run_id"])
    assert second["agent_commit"] == first["agent_commit"], json.dumps([first, second])[:400]


def test_an_agent_that_reads_the_cases_is_caught(make_repo):
    repo = make_repo(variant="peek")  # a coding harness can grep for its own case
    assert repo.cli("run", "--purpose", "baseline", "--k", "3", "--force", "--case", "book-001") == 0
    m = Evals(repo.evals).latest_run("baseline")
    exposure = m["eval_exposure"]
    assert not exposure["isolated"] and exposure["changed"] == ["cases/book-meeting/book-001.json"]
    assert exposure["mentioned"] and exposure["mentioned"][0]["files"] == ["evals/cases", "book-001.json"]
    probs = gates.manifest_problems(m)
    assert any("eval files changed" in p for p in probs) and any("names eval files" in p for p in probs)


def test_an_isolated_run_cannot_see_the_cases(make_repo):
    repo = make_repo(variant="peek", suite=NESTED)
    text = (repo.evals / "agent.yaml").read_text().replace("  cwd: .\n", "  cwd: .\n  isolate: true\n")
    (repo.evals / "agent.yaml").write_text(text)
    repo.commit("isolate")
    assert repo.cli("run", "--purpose", "baseline", "--k", "3", "--force") == 0
    m = Evals(repo.evals).latest_run("baseline")
    assert m["eval_exposure"] == {"isolated": True, "changed": [], "mentioned": []}
    assert m["counts"].get("ok") and not gates.manifest_problems(m)
    assert m["agent_commit"]  # from the repository, not the copy (which has no .git)
    first = json.loads((repo.evals / "runs" / m["run_id"] / "outcomes.jsonl").read_text().splitlines()[0])
    assert first["outcome"] == "ok"


def test_snapshot_covers_the_whole_working_tree(make_repo, monkeypatch, capsys):
    repo = make_repo()
    (repo.root / "answer.md").write_text("written outside the agent's folders\n")
    (repo.root / "out").mkdir()
    (repo.root / "out/run.log").write_text("a run output\n")
    monkeypatch.chdir(repo.root)
    capsys.readouterr()
    assert cli.main(["snapshot", "--exclude", "out/*"]) == 0
    files = json.loads(capsys.readouterr().out)["files"]
    assert "answer.md" in files and "agent/agent.py" in files
    assert not [f for f in files if f.startswith(("evals/", "out/", ".git/"))]
    assert "world.json" not in files  # git-ignored
