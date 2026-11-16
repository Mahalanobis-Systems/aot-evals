"""`aot-evals coverage` on the store (docs/method.md; estimators rule 10): the
bug-finding set against its external coverage list, entry x failure mode, the empty cells
first. A list committed after the cases is a problem, since a list written from the cases always
covers them; the report's `coverage_list` gate reads the same problems (test_fixtures.py)."""

from __future__ import annotations

import json
import shutil

from conftest import git

from aot_evals.coverage import list_problems


def test_coverage_of_the_store_lists_the_empty_cells_first(store_repo, capsys):
    s = store_repo
    capsys.readouterr()
    assert s.cli("coverage", "--json") == 0
    cov = json.loads(capsys.readouterr().out)
    assert cov["problems"] == [] and cov["list"] == "coverage.yaml"
    assert len(cov["cells"]) == len(cov["entries"]) * len(cov["failure_modes"])
    ns = [c["n"] for c in cov["cells"]]
    assert ns == sorted(ns, key=lambda n: n > 0)  # the empty cells first
    assert cov["empty_cells"] == ns.count(0)
    assert sum(c["bug_finding"] for c in cov["cells"]) > 0
    assert s.cli("coverage") == 0
    assert "entry" in capsys.readouterr().out


def test_a_list_committed_after_the_cases_is_a_problem(store_repo, capsys):
    s = store_repo
    # a history where the list really arrives after the cases
    shutil.rmtree(s.root / ".git")
    git(s.root, "init", "-q")
    rel = str((s.agent / "end-to-end" / "coverage.yaml").relative_to(s.root))
    git(s.root, "add", "-A")
    git(s.root, "reset", "-q", "--", rel)
    git(s.root, "commit", "-q", "-m", "cases first")
    s.commit("the list, after the cases")
    problems = list_problems(s.ev())
    assert len(problems) == 1 and "was not committed before the first case" in problems[0]
    capsys.readouterr()
    assert s.cli("coverage") == 1
    assert "problem: coverage.yaml was not committed before the first case" in capsys.readouterr().out


def test_the_list_in_the_same_commit_as_the_cases_counts(store_repo):
    """A squash merge folds "the list first, then the cases" into one commit: build_store commits
    the store's cases and its lists together."""
    assert list_problems(store_repo.ev()) == []
    assert list_problems(store_repo.ev("refund-subagent")) == []


def test_an_uncommitted_list_is_a_problem(store_repo):
    s = store_repo
    shutil.rmtree(s.root / ".git")
    git(s.root, "init", "-q")
    rel = str((s.agent / "end-to-end" / "coverage.yaml").relative_to(s.root))
    git(s.root, "add", "-A")
    git(s.root, "reset", "-q", "--", rel)
    git(s.root, "commit", "-q", "-m", "no list")
    assert list_problems(s.ev()) == ["coverage.yaml is not committed; commit it before any case"]
