"""Suites made by earlier versions, as returning users have them (feedback from a real suite).

The shape: the suite in the old layout, evals/<agent>/; a discovery report a later assessment put
in evals/agents/<agent>/; the agent committed before the evals, with the coverage list and the
cases in one squash-merged commit; a baseline run one category at a time, and one category re-run.
Expected: the suite is found and its roots are right, status says Judge, every category has a
baseline, the agent has not changed, and `migrate` joins the two trees.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest
from conftest import FIXTURE, git

from aot_evals import cli, gates, trust
from aot_evals.repo import Evals


@pytest.fixture
def old_repo(tmp_path):
    root = tmp_path / "repo"
    shutil.copytree(FIXTURE, root)
    agent = (root / "evals" / "agent.yaml").read_text()
    (root / "evals" / "agent.yaml").write_text(agent.replace("{PYTHON}", sys.executable).replace("{VARIANT}", "good"))
    shutil.move(root / "evals", root / "_suite")
    (root / "evals").mkdir()
    shutil.move(root / "_suite", root / "evals" / "calendar")
    shutil.copyfile(Path(cli.__file__).parent / "templates" / "evals" / "gitignore",
                    root / "evals" / "calendar" / ".gitignore")
    (root / ".gitignore").write_text("world.json\n")
    new = root / "evals" / "agents" / "calendar"
    new.mkdir(parents=True)
    shutil.move(root / "evals" / "calendar" / "discovery.md", new / "discovery.md")
    git(root, "init", "-q")
    git(root, "add", "-A", "--", ".", ":(exclude)evals")
    git(root, "commit", "-q", "-m", "the agent")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "evals (squash-merged: taxonomy and cases in one commit)")
    suite = root / "evals" / "calendar"
    base = ["--evals", str(suite)]
    assert cli.main([*base, "import", str(root / "traces.jsonl"), "--id", "traces", "--source", "t",
                     "--query", "all", "--window", "2026-09-01..2026-09-30"]) == 0
    assert cli.main([*base, "screen", "--read-by", "t", "--all"]) == 0
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "screened")
    for cat in ("book-meeting", "nothing-to-do", "book-meeting"):  # one category re-run last
        assert cli.main([*base, "run", "--purpose", "baseline", "--k", "3", "--category", cat]) == 0
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "baselines")
    return root


def test_an_old_layout_suite_is_found_with_the_right_roots(old_repo, monkeypatch):
    monkeypatch.chdir(old_repo)
    ev = Evals.find()
    assert ev.root == (old_repo / "evals" / "calendar").resolve() and ev.old_layout
    assert ev.evals_dir == (old_repo / "evals").resolve() and ev.repo_root == old_repo.resolve()
    assert ev.discovery_path() == (old_repo / "evals" / "agents" / "calendar" / "discovery.md").resolve()
    monkeypatch.chdir(old_repo / "evals" / "calendar" / "cases")
    assert Evals.find().root == ev.root
    assert Evals.find(str(old_repo / "evals"), "calendar").root == ev.root  # --evals evals --agent calendar
    # the agent's version excludes all of evals/: the commit that added the suites isn't an agent change
    import subprocess

    from aot_evals.util import git_commit_info

    first = subprocess.run(["git", "rev-list", "--max-parents=0", "HEAD"], cwd=old_repo, capture_output=True,
                           text=True).stdout.strip()
    assert git_commit_info(old_repo, exclude=ev.evals_dir)["commit"] == first
    assert {m["agent_commit"] for m in ev.baseline_runs()} == {first}


def test_status_on_an_old_suite_says_judge_with_every_category_baselined(old_repo, capsys):
    ev = Evals(old_repo / "evals" / "calendar")
    assert len(ev.baseline_runs()) == 2  # the re-run replaced book-meeting's first run, not nothing-to-do's
    assert trust.phase(ev)["id"] == "judge"
    assert {r["category"]: r["level"] for r in trust.trust(ev)} == {"book-meeting": "provisional",
                                                                    "nothing-to-do": "provisional"}
    kinds = [c["kind"] for c in trust.changes(ev)]
    assert "agent" not in kinds and "new-use-case" not in kinds, trust.changes(ev)
    by = {g.id: g for g in gates.evaluate(ev)}
    assert by["C2"].status == "met" and by["C12"].status == "met"
    assert cli.main(["--evals", str(old_repo / "evals" / "calendar"), "status"]) == 0
    io = capsys.readouterr()
    assert "old layout" in io.err and "aot-evals migrate" in io.err
    assert "Phase: Judge" in io.out


def test_migrate_joins_the_old_suite_and_the_discovery_report(old_repo, capsys):
    assert cli.main(["--evals", str(old_repo / "evals"), "migrate", "--dry-run"]) == 0
    assert (old_repo / "evals" / "calendar").exists()
    # both trees have an activity log, as when an assessment ran in the new folder
    new = old_repo / "evals" / "agents" / "calendar" / "journal"
    new.mkdir(parents=True, exist_ok=True)
    (new / "activity.jsonl").write_text('{"ts": "2026-10-08T10:00:00Z", "kind": "step", "text": "assess"}\n')
    old = old_repo / "evals" / "calendar" / "journal"
    old.mkdir(parents=True, exist_ok=True)
    (old / "activity.jsonl").write_text('{"ts": "2026-10-05T10:00:00Z", "kind": "step", "text": "build"}\n')
    assert cli.main(["--evals", str(old_repo / "evals"), "migrate"]) == 0
    out = capsys.readouterr().out
    assert "calendar: evals/calendar/ -> evals/agents/calendar/" in out and "keeps discovery.md" in out
    assert not (old_repo / "evals" / "calendar").exists()
    log = (new / "activity.jsonl").read_text().splitlines()
    assert [ln.split('"text": "')[1][:-2] for ln in log[:2]] == ["build", "assess"]  # merged, in time order
    ev = Evals(old_repo / "evals" / "agents" / "calendar")
    assert (ev.p("agent.yaml")).exists() and ev.p("discovery.md").exists() and not ev.old_layout
    status = git_status(old_repo)
    assert "R  evals/calendar/agent.yaml -> evals/agents/calendar/agent.yaml" in status  # history follows
    assert trust.phase(ev)["id"] == "judge" and len(ev.baseline_runs()) == 2


def git_status(root):
    import subprocess

    return subprocess.run(["git", "status", "--porcelain"], cwd=root, capture_output=True, text=True).stdout


def test_two_runs_started_in_the_same_second_get_their_own_folders(make_repo, monkeypatch):
    from aot_evals import runner

    repo = make_repo()
    ev = Evals(repo.evals)
    monkeypatch.setattr(runner, "run_id_stamp", lambda: "20261103T120000Z")
    for cat in ("book-meeting", "nothing-to-do"):
        assert repo.cli("run", "--purpose", "baseline", "--k", "3", "--category", cat, "--force") == 0
    ids = [m["run_id"] for m in ev.runs("baseline")]
    assert ids == ["20261103T120000Z-baseline", "20261103T120000Z-baseline-2"]
    assert len(ev.baseline_runs()) == 2
    for rid in ids:  # each run's records are its own
        cats = {r["case_id"].split("-")[0] for r in ev.run_records(rid) if r.get("kind") == "attempt"}
        assert len(cats) == 1
