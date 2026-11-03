"""Phases, trust per category, changes since the baseline, and the next step (trust.py)."""

from __future__ import annotations

import json

from aot_evals import agreement, trust
from aot_evals.repo import Evals


def _label_all(repo, ev, run_id: str, label: str = "pass") -> None:
    rows = [{"item_id": agreement.item_key(run_id, a["case_id"], a["trial"], a["attempt"]),
             "case_id": a["case_id"], "run": run_id, "trial": a["trial"], "attempt": a["attempt"],
             "label": label, "labeller": "tester", "note": ""}
            for a in agreement.finals(ev, [run_id])]
    agreement.import_rows(ev, rows, "tester")


def test_phase_and_next_step_before_and_after_the_baseline(make_repo):
    repo = make_repo()
    ev = Evals(repo.evals)
    ph = trust.phase(ev)
    assert ph["id"] == "build" and ph["done"] == ["assess"]
    nx = trust.next_step(ev)
    assert nx["phase"] == "build" and "smoke" in nx["how"]
    assert all(r["level"] == "untested" for r in trust.trust(ev))
    assert trust.changes(ev) == []  # nothing to compare with yet

    repo.cli("run", "--purpose", "smoke", "--case", "book-001")
    assert "baseline" in trust.next_step(ev)["how"]
    assert repo.cli("run", "--purpose", "baseline", "--k", "3") == 0
    assert trust.phase(ev)["id"] == "judge"
    levels = {r["category"]: r for r in trust.trust(ev)}
    assert levels["book-meeting"]["level"] == "provisional"
    assert "labelled" in levels["book-meeting"]["why"]
    nx = trust.next_step(ev)
    assert nx["phase"] == "judge" and nx.get("category") and "label" in nx["how"]


def test_a_category_is_validated_when_the_suite_agrees_with_a_person(make_repo):
    repo = make_repo()
    ev = Evals(repo.evals)
    repo.cli("run", "--purpose", "smoke", "--case", "book-001")
    assert repo.cli("run", "--purpose", "baseline", "--k", "3") == 0
    run_id = ev.latest_run("baseline")["run_id"]
    # the floors are suite-wide; lower them so the toy suite's 30 runs can clear them
    (ev.p("labels", "floors.yaml")).write_text("min_runs: 10\nmin_each: 1\n")
    _label_all(repo, ev, run_id, "pass")
    agreement.measure(ev, log=lambda *_: None)
    res = json.loads(agreement.result_path(ev).read_text())
    assert set(res["categories"]) == {"book-meeting", "nothing-to-do"}
    levels = {r["category"]: r for r in trust.trust(ev)}
    # every labelled run passes: the suite-wide floor (one of each kind) isn't met, and the
    # category's catch rate has no denominator. Provisional, and the reason says why.
    assert levels["book-meeting"]["level"] == "provisional"
    assert "at least 1 of each" in levels["book-meeting"]["why"]
    assert levels["book-meeting"]["clean"] == 1.0 and levels["book-meeting"]["catch"] is None
    assert levels["book-meeting"]["labelled_runs"] == 21 and levels["nothing-to-do"]["labelled_runs"] == 9


def test_changes_since_the_baseline_name_the_short_path(make_repo):
    repo = make_repo()
    ev = Evals(repo.evals)
    repo.cli("run", "--purpose", "smoke", "--case", "book-001")
    assert repo.cli("run", "--purpose", "baseline", "--k", "3") == 0
    assert trust.changes(ev) == []

    # a check changed: re-grade offline, no agent runs
    path = ev.code_check_path("requested-event-exists")
    path.write_text(path.read_text() + "\n# tightened\n")
    kinds = [c["kind"] for c in trust.changes(ev)]
    assert kinds == ["checks"]
    assert "agreement" in trust.changes(ev)[0]["path"][0]
    assert trust.next_step(ev)["change"] == "checks"

    # a new category: a new use case
    d = ev.p("cases", "reschedule")
    d.mkdir()
    case = json.loads(ev.p("cases", "book-meeting", "book-001.json").read_text())
    case.update({"id": "move-001", "category": "reschedule"})
    (d / "move-001.json").write_text(json.dumps(case))
    cats = repo.yaml("categories.yaml")
    cats["categories"].append({"id": "reschedule", "definition": "move a meeting", "example": "t",
                               "worth": "high", "simple": False, "cost": {"incorrect": "high"},
                               "observed_share": 0.0, "share_source": "traces"})
    repo.write_yaml("categories.yaml", cats)
    ch = {c["kind"]: c for c in trust.changes(ev)}
    assert "new-use-case" in ch and "reschedule" in ch["new-use-case"]["what"]
    levels = {r["category"]: r for r in trust.trust(ev)}
    assert levels["reschedule"]["level"] == "untested"

    # the invocation changed in agent.yaml (an env var, as the demo's candidate does): the agent changed
    a = repo.yaml("agent.yaml")
    a["invoke"]["env"]["AGENT_BREAK"] = "book-002"
    repo.write_yaml("agent.yaml", a)
    assert any(c["kind"] == "agent" and "environment variables" in c["what"] for c in trust.changes(ev))
    a["invoke"]["env"].pop("AGENT_BREAK")
    repo.write_yaml("agent.yaml", a)

    # the agent changed: a candidate run, then label only what changed
    (repo.root / "agent" / "agent.py").write_text((repo.root / "agent" / "agent.py").read_text() + "\n# v2\n")
    assert any(c["kind"] == "agent-uncommitted" for c in trust.changes(ev))
    repo.commit("agent v2")
    ch = {c["kind"]: c for c in trust.changes(ev)}
    assert "agent" in ch and "candidate" in ch["agent"]["path"][0]


def test_status_prints_the_summary_and_the_gate_table_on_request(make_repo, capsys):
    repo = make_repo()
    assert repo.cli("status") == 0
    out = capsys.readouterr().out
    assert "Phase: Build" in out and "Next:" in out and "C0" not in out.split("Upgrades")[0]
    assert repo.cli("status", "--gates") == 0
    assert "C12  baseline" in capsys.readouterr().out
    assert repo.cli("status", "--json") == 0
    data = json.loads(capsys.readouterr().out)
    assert data["phase"]["id"] == "build" and "trust" in data and "gates" in data
