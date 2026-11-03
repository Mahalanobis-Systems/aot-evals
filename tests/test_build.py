"""The lightest Build (build.py): from a discovery report to a baseline with one generic check."""

from __future__ import annotations

import json
import shutil
import subprocess

from conftest import FIXTURE

from aot_evals import build, cli, gates, trust
from aot_evals.repo import Evals


def test_build_drafts_categories_and_a_check_from_the_discovery_report(tmp_path, capsys):
    suite = tmp_path / "repo" / "evals" / "agents" / "cal"
    suite.mkdir(parents=True)
    shutil.copyfile(FIXTURE / "evals" / "discovery.md", suite / "discovery.md")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path / "repo", check=True)
    assert cli.main(["--evals", str(suite), "build"]) == 0
    out = capsys.readouterr().out
    ev = Evals(suite)
    assert [c["id"] for c in ev.categories()] == ["schedule-a-meeting", "leave-the-calendar-alone"]
    assert [c["observed_share"] for c in ev.categories()] == [0.6, 0.4]
    assert all(c["draft"] for c in ev.categories())
    assert (suite / "cases" / "schedule-a-meeting").is_dir()
    (fm,) = ev.failure_modes()
    assert fm["checks"] == [build.DEFAULT_CHECK] and fm["categories"] == ["*"]
    assert ev.code_check_path(build.DEFAULT_CHECK).exists()
    assert "[ ] The agent runs as a command" in out and "[x] Categories" in out
    tax = ev.taxonomy()
    assert [e["id"] for e in tax["entries"]] == ["situation.unanswerable", "situation.ambiguous",
                                                 "situation.forbidden", "situation.multi-turn",
                                                 "situation.tool-error"]
    assert "commit taxonomy.yaml before the first case" in out
    assert not gates.taxonomy_problems(ev) or all("commit" in p or "git" in p for p in gates.taxonomy_problems(ev))
    assert trust.phase(ev)["id"] == "build"
    # running it again changes nothing
    before = (suite / "categories.yaml").read_text()
    assert cli.main(["--evals", str(suite), "build"]) == 0
    assert (suite / "categories.yaml").read_text() == before
    assert "drafted" not in capsys.readouterr().out


def test_build_run_reaches_a_baseline_with_only_the_generic_check(make_repo, capsys):
    repo = make_repo()
    ev = Evals(repo.evals)
    # strip the suite to the lightest Build: cases with expected end states, no checks of its own
    shutil.rmtree(repo.evals / "checks" / "code")
    (repo.evals / "failure_modes.yaml").write_text("failure_modes: []\n")
    for p in (repo.evals / "cases").rglob("*.json"):
        c = json.loads(p.read_text())
        c["failure_modes"] = []
        p.write_text(json.dumps(c, indent=2))
    repo.commit("the lightest suite")
    assert repo.cli("build") == 0
    capsys.readouterr()
    repo.commit("build drafts")
    assert repo.cli("build", "--run") == 0
    out = capsys.readouterr().out
    assert "aot-evals serve" in out
    base = ev.latest_run("baseline")
    assert base and base["k"] == 3
    lines = [r for r in ev.run_records(base["run_id"]) if r.get("kind") == "check"]
    assert lines and all(r["check_id"] == build.DEFAULT_CHECK for r in lines)
    assert all(r["passed"] for r in lines)  # the good toy agent ends every case as expected
    assert trust.phase(ev)["id"] == "judge"
    assert "C12" not in {g.id for g in gates.evaluate(ev) if g.status == "unmet"}


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


def test_the_component_checklist_reads_the_suite_and_the_assessment(make_repo):
    from aot_evals import components

    repo = make_repo()
    ev = Evals(repo.evals)
    by = {c["id"]: c for c in components.checklist(ev)}
    assert len(by) == len(components.COMPONENTS)
    assert by["golden"]["state"] == "done" and by["deterministic"]["state"] == "done"
    assert by["engine"]["state"] == "todo" and by["grader-ui"]["state"] == "todo"
    assert by["judges"]["state"] == "n/a"  # every check is code
    assert by["fakes"]["state"] == "n/a"  # the seed hook sets up the world
    assert by["trace-monitoring"]["state"] == "later"
    # the assessment may say more than the suite does yet, never less
    d = ev.p("discovery.md")
    text = d.read_text().replace("minutes: 2\n", "minutes: 2\ncomponents:\n  engine: {state: partial, note: a CI "
                                 "job runs the agent nightly}\n  golden: {state: todo, note: none}\n", 1)
    d.write_text(text)
    by = {c["id"]: c for c in components.checklist(ev)}
    assert by["engine"]["state"] == "partial" and "nightly" in by["engine"]["why"]
    assert by["golden"]["state"] == "done"
    from aot_evals.start import components_html, split_front_matter

    html = components_html(split_front_matter(text)[0]["components"])
    assert "The components to build" in html and "nightly" in html and "Partly" in html
