"""Self-test fixtures: each one must trigger exactly the gate it targets.

A good agent, an agent that claims success without changing anything, a flaky agent, an agent
with the same correctness at 3x the cost, an agent that times out a third of the time, and a
taxonomy derived from the suite's own cases. The always-pass judge is in test_judges.py and the
redundant case set in test_suite.py.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from aot_evals import gates
from aot_evals.repo import Evals

PHASE1_GATES = ("G1", "G2", "G5", "G6", "G8", "G10", "G12", "G13")


def failing(report: dict) -> set[str]:
    return {g["id"] for g in report["gates"] if g["status"] == "fail"}


def rows(report: dict, category: str) -> list[dict]:
    return [r for r in report["categories"] if r["id"] == category]


def test_good_agent_clears_every_phase1_gate(make_repo):
    repo = make_repo()
    ev = Evals(repo.evals)
    unmet = [g.id for g in gates.evaluate(ev) if g.status == "unmet"]
    assert unmet == ["C1", "C12", "C18"]  # C1 waits only on the smoke run

    assert repo.cli("run", "--purpose", "smoke", "--case", "book-001") == 0
    assert repo.cli("run", "--purpose", "baseline", "--k", "3") == 0
    assert repo.cli("report") == 0
    r = repo.report()
    assert failing(r) == set()
    assert all(repo.gate(r, g)["status"] == "pass" for g in PHASE1_GATES)
    assert [g.id for g in gates.evaluate(ev) if g.status == "unmet"] == []

    for row in r["categories"]:
        assert row["pass_rate"]["point"] == 1.0
        assert row["pass_rate"]["k"] == 3 and row["pass_rate"]["n"] > 0
        assert row["pass_rate"]["ci"] is not None
        assert row["operational"]["budget_status"] == "within"
        assert row["operational"]["cache_hit_rate"] is not None
    assert r["sets"]["quality_estimate"]["estimate"]["point"] == 1.0
    assert r["coverage"]["list"] == "external"
    assert r["coverage"]["empty_cells"] > 0  # reschedule-meeting has no cases
    assert r["coverage"]["cells"][0]["n"] == 0  # empty cells listed first


def test_baseline_refused_until_cases_are_screened(make_repo, capsys):
    repo = make_repo(screen=False)
    repo.cli("run", "--purpose", "smoke", "--question", "hello")
    try:
        repo.cli("run", "--purpose", "baseline", "--k", "3")
    except SystemExit as e:
        assert "C7 screen" in str(e)
    else:
        raise AssertionError("baseline ran with unscreened cases")


def test_k1_baseline_is_refused_by_the_cli(make_repo):
    repo = make_repo()
    repo.cli("run", "--purpose", "smoke", "--case", "book-001")
    try:
        repo.cli("run", "--purpose", "baseline", "--k", "1")
    except SystemExit as e:
        assert "k >= 3" in str(e)
    else:
        raise AssertionError("k=1 baseline ran")


def test_liar_agent_fails_state_checks(make_repo):
    repo = make_repo(variant="liar")
    assert repo.cli("run", "--purpose", "baseline", "--k", "3", "--force") == 0
    repo.cli("report")
    r = repo.report()
    for row in rows(r, "book-meeting"):
        assert row["pass_rate"]["point"] == 0.0
    for row in rows(r, "nothing-to-do"):
        assert row["pass_rate"]["point"] == 1.0
    assert repo.gate(r, "G10")["status"] == "pass"  # the checks grade state, not the claim


def test_check_that_trusts_the_agents_claim_is_refused_by_g10(make_repo):
    repo = make_repo(variant="liar")
    shutil.copyfile(Path(__file__).parent / "fixtures" / "claims-success.py",
                    repo.evals / "checks/code/claims-success.py")
    fms = repo.yaml("failure_modes.yaml")
    fms["failure_modes"][0]["checks"] = ["claims-success"]
    repo.write_yaml("failure_modes.yaml", fms)
    repo.cli("screen", "--force")
    sensitive = json.loads((repo.evals / "cases/book-meeting/book-001.json").read_text())
    assert sensitive["screen"]["claim_sensitive_checks"] == ["claims-success"]
    repo.commit("naive check")
    repo.cli("run", "--purpose", "baseline", "--k", "3", "--force")
    repo.cli("report")
    r = repo.report()
    assert repo.gate(r, "G10")["status"] == "fail"
    assert "check:claims-success" in repo.gate(r, "G10")["blocks"]
    c8 = next(g for g in gates.evaluate(Evals(repo.evals)) if g.id == "C8")
    assert c8.status == "unmet"


def test_flaky_agent_is_reported_as_flaky(make_repo):
    repo = make_repo(variant="flaky")
    repo.cli("run", "--purpose", "baseline", "--k", "3", "--force")
    repo.cli("report")
    r = repo.report()
    ef = next(row for row in rows(r, "book-meeting") if row["pass_rate"]["set"] == "error_finding")
    assert ef["flaky"] > 0
    assert ef["pass_pow_k"] < ef["pass_rate"]["point"] < 1.0
    assert ef["variance_band"][0] < ef["variance_band"][1]
    assert failing(r) == set()


def test_costly_agent_is_over_budget_at_same_correctness(make_repo):
    repo = make_repo(variant="costly")
    repo.cli("run", "--purpose", "baseline", "--k", "3", "--force")
    repo.cli("report")
    r = repo.report()
    for row in r["categories"]:
        assert row["pass_rate"]["point"] == 1.0
        assert row["operational"]["budget_status"] == "over"
        assert row["operational"]["budget_breaches"][0]["budget"] == "cost_per_success_usd"


def test_timeouts_are_plane_b_never_correctness(make_repo):
    repo = make_repo(variant="slow", timeout=1)
    repo.cli("run", "--purpose", "baseline", "--k", "3", "--force")
    repo.cli("report")
    r = repo.report()
    assert repo.gate(r, "G13")["status"] == "pass"
    timeouts = sum(row["operational"]["outcomes"].get("timeout", 0) for row in r["categories"])
    assert timeouts > 0
    assert sum(row["operational"]["killed"] for row in r["categories"]) == timeouts
    assert sum(row["operational"]["retries"] for row in r["categories"]) > 0
    for row in r["categories"]:
        if row["pass_rate"]:
            assert row["pass_rate"]["point"] == 1.0  # correctness only over ok attempts
    for case in r["cases"]:
        for t in case["trials"]:
            if t["outcome"] == "timeout":
                assert t["passed"] is None


def test_taxonomy_derived_from_cases_is_refused_by_g5(make_repo):
    repo = make_repo()
    tax = repo.yaml("taxonomy.yaml")
    tax["source"] = {"document": "clusters of evals/cases", "kind": "other"}
    repo.write_yaml("taxonomy.yaml", tax)
    repo.commit("taxonomy from cases")
    repo.cli("run", "--purpose", "baseline", "--k", "3", "--force")
    repo.cli("report")
    r = repo.report()
    assert failing(r) == {"G5"}
    assert r["coverage"]["list"] == "MISSING"
    assert r["taxonomy"]["source"] == "MISSING"


def test_taxonomy_committed_after_cases_is_refused_by_g5(make_repo):
    repo = make_repo(taxonomy_first=False)
    repo.cli("run", "--purpose", "baseline", "--k", "3", "--force")
    repo.cli("report")
    r = repo.report()
    assert "G5" in failing(r)


def test_k1_baseline_refused_and_g2_fails(make_repo):
    repo = make_repo()
    repo.cli("run", "--purpose", "candidate", "--k", "1", "--force")
    repo.cli("report", "--run", Evals(repo.evals).latest_run("candidate")["run_id"])
    assert failing(repo.report()) == {"G2"}


def test_unscreened_case_is_excluded_not_hidden(make_repo):
    repo = make_repo()
    path = repo.evals / "cases/book-meeting/book-002.json"
    case = json.loads(path.read_text())
    case["screen"]["human_read"] = None
    path.write_text(json.dumps(case, indent=2))
    repo.commit("unread")
    repo.cli("run", "--purpose", "baseline", "--k", "3", "--force")
    repo.cli("report")
    r = repo.report()
    assert failing(r) == {"G8"}
    ef = next(row for row in rows(r, "book-meeting") if row["pass_rate"]["set"] == "error_finding")
    assert ef["n_cases"] == 4
    assert ef["excluded"]["n_cases"] == 1


def test_ops_sweeps_an_export_before_any_run(make_repo, capsys):
    repo = make_repo()
    capsys.readouterr()
    assert repo.cli("ops", "--export", "traces", "--field", "category=category", "--field",
                    "cost_usd=metrics.cost", "--field", "latency_ms=metrics.duration_ms",
                    "--field", "outcome=status", "--json") == 0
    out = json.loads(capsys.readouterr().out)
    book = out["categories"]["book-meeting"]
    assert book["n_trials"] == 12
    assert book["outcomes"] == {"ok": 10, "error": 2}
    assert book["cost_per_success"] is None  # an export has no correctness


def test_html_shell_is_branded_and_self_contained(make_repo):
    import re

    repo = make_repo()
    repo.cli("run", "--purpose", "baseline", "--k", "3", "--force")
    assert repo.cli("report", "--html", "--title", "How is the toy agent doing?") == 0
    html_path = sorted((repo.evals / "report").glob("report-*.html"))[-1]
    html = html_path.read_text()
    # branded: logo, fonts, palette, attribution
    assert 'src="data:image/png;base64,' in html and 'alt="AOT, the Agent Optimization Toolkit"' in html
    assert html.count("@font-face{") == 5 and "Montserrat" in html and "Roboto" in html
    assert "#225734" in html and ">Mahal Systems</a>" in html
    assert "Mahalanobis Systems" not in html
    # self-contained: nothing is fetched
    assert not re.search(r'(src|href)="https?://(?!mahalsystems\.ai)', html)
    assert "<link" not in html and "@import" not in html and "<script src" not in html
    # the data round-trips, and the panels slot is there for Claude
    data = re.search(r'<script type="application/json" id="data">(.*)</script>', html, re.S).group(1)
    assert json.loads(data.replace("<\\/", "</"))["schema"] == "aot-evals/report@1"
    assert "PANELS:" in html and "How is the toy agent doing?" in html
    # a filled-in report is never overwritten
    html_path.write_text(html.replace("<!-- PANELS:", "<section>filled</section><!-- X:"))
    repo.cli("report", "--html")
    assert "filled" in html_path.read_text()
    assert len(list((repo.evals / "report").glob("report-*.html"))) == 2


def test_a_silent_provider_stops_the_run_instead_of_timing_out_every_case(make_repo, capsys):
    repo = make_repo(variant="silent")
    assert repo.cli("run", "--purpose", "baseline", "--k", "3", "--force", "--stop-after", "3") == 1
    m = Evals(repo.evals).runs("baseline")[-1]
    assert m["stopped"]["cases_done"] == 3 and not m.get("finished")
    assert Evals(repo.evals).latest_run("baseline") is None  # a stopped run is never a baseline
    assert "STOPPED" in capsys.readouterr().out


def test_pause_every_paces_the_run(make_repo):
    from aot_evals import runner

    repo = make_repo()
    ev = Evals(repo.evals)
    pauses: list[float] = []
    m = runner.run(ev, purpose="baseline", k=1, pause_every=3, pause_seconds=7, sleep=pauses.append,
                   log=lambda *_: None)
    n = len(m["case_set"]["ids"])
    assert m["finished"] and pauses == [7] * ((n - 1) // 3)


def test_gate_checks_cost_the_same_git_calls_however_many_cases(make_repo, monkeypatch):
    """C2/C14 once ran one `git log` per case file, so `status` slowed with every case added."""
    from aot_evals import util

    repo = make_repo()
    calls = []
    real = util.git
    monkeypatch.setattr(util, "git", lambda args, cwd: calls.append(args) or real(args, cwd))
    monkeypatch.setattr(gates, "git", util.git)

    def git_calls() -> int:
        calls.clear()
        gates.evaluate(Evals(repo.evals))
        return len(calls)

    before = git_calls()
    src = repo.evals / "cases/book-meeting/book-001.json"
    for i in range(20):
        case = json.loads(src.read_text())
        case["id"] = f"book-extra-{i:02d}"
        (src.parent / f"book-extra-{i:02d}.json").write_text(json.dumps(case))
    repo.commit("twenty more cases")
    assert git_calls() == before

    added = util.git_adding_commits(repo.root, "evals/cases")
    for path in sorted((repo.evals / "cases").glob("*/*.json")):
        rel = str(path.relative_to(repo.root))
        assert added[rel] == util.git_adding_commit(repo.root, rel)
