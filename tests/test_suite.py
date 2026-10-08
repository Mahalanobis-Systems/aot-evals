"""Suite measurement and comparison (C13-C15).

Acceptance: a suite with 80% non-discriminating cases is reported as such, and a prune proposal
shrinks it with no loss of detectable effect.
"""

from __future__ import annotations

import json

from aot_evals import gates
from aot_evals.repo import Evals

BOOKING = ["book-001", "book-002", "book-003", "book-004", "book-005", "book-q01", "book-q02"]


def set_agent(repo, variant: str = "good", break_cases: list[str] | None = None) -> None:
    text = (repo.evals / "agent.yaml").read_text()
    head, _, _ = text.partition("  env:")
    broken = ",".join(break_cases or [])
    env = f'  env: {{AGENT_VARIANT: "{variant}", WORLD_FILE: world.json, AGENT_BREAK: "{broken}"}}\n'
    (repo.evals / "agent.yaml").write_text(head + env)
    repo.commit(f"agent: {variant} {break_cases}")


def baseline(repo, **agent) -> None:
    if agent:
        set_agent(repo, **agent)
    assert repo.cli("run", "--purpose", "baseline", "--k", "3", "--force") == 0


def candidate(repo, variable: str | None = "config=candidate", **agent) -> None:
    set_agent(repo, **agent)
    args = ["run", "--purpose", "candidate", "--k", "3", "--force"]
    if variable:
        args += ["--variable", variable]
    assert repo.cli(*args) == 0


def comparison(repo, *args: str) -> dict:
    repo.cli("compare", *args)
    found = [json.loads(p.read_text()) for p in (repo.evals / "report" / "comparisons").glob("*.json")]
    return max(found, key=lambda c: c["generated"])


def set_budget(repo, **budget) -> None:
    repo.write_yaml("budgets.yaml", {"default": budget, "categories": {}})
    repo.commit("budgets")


def test_two_flips_are_listed_but_not_called_a_regression(make_repo):
    repo = make_repo()
    baseline(repo)
    candidate(repo, break_cases=["book-001", "book-002"])
    c = comparison(repo)
    assert c["paired"] and c["refused"] is None
    assert c["losses"] == ["book-001", "book-002"] and c["gains"] == []
    assert c["test"]["p"] == 0.5 and c["min_flips_for_significance"] == 6
    assert c["verdict"] == "indistinguishable"  # never a net delta alone, and two flips prove nothing
    assert c["net"] < 0 and c["test"]["ci"] is not None
    assert c["mde_at_80_power"] is not None
    assert c["per_set"]["error_finding"]["losses"] == ["book-001", "book-002"]
    assert c["per_set"]["quality_estimate"]["losses"] == []
    c13 = next(g for g in gates.evaluate(Evals(repo.evals)) if g.id == "C13")
    assert c13.status == "met"


def test_broad_regression_is_worse(make_repo):
    repo = make_repo()
    baseline(repo)
    candidate(repo, break_cases=BOOKING)
    c = comparison(repo)
    assert sorted(c["losses"]) == BOOKING
    assert c["test"]["p"] < 0.05 and c["test"]["ci"][1] < 0
    assert c["verdict"] == "worse"
    assert c["per_set"]["quality_estimate"]["losses"] == ["book-q01", "book-q02"]


def test_undeclared_difference_is_refused_by_g7(make_repo):
    repo = make_repo()
    baseline(repo)
    candidate(repo, variable=None, break_cases=["book-001"])
    c = comparison(repo)
    assert c["refused"].startswith("G7") and "invoke" in c["refused"] and c["verdict"] is None
    base = Evals(repo.evals).latest_run("baseline")["run_id"]
    cand = Evals(repo.evals).latest_run("candidate")["run_id"]
    repo.cli("report", "--run", base, "--candidate", cand)
    r = repo.report()
    assert repo.gate(r, "G7")["status"] == "fail"
    assert r["comparison"]["refused"]


def test_a_declared_variable_must_cover_the_difference(make_repo):
    repo = make_repo()
    baseline(repo)
    candidate(repo, variable="simulator=v2", break_cases=["book-001"])
    c = comparison(repo)
    assert c["refused"] and "declared variable 'simulator=v2'" in c["refused"]


def test_better_correctness_beyond_cost_budget_is_a_trade(make_repo):
    repo = make_repo()
    set_budget(repo, cost_per_run_usd=0.004, latency_p90_ms=10000, error_rate=0.5)
    baseline(repo, break_cases=BOOKING)
    candidate(repo, variant="costly")
    c = comparison(repo)
    assert sorted(c["gains"]) == BOOKING
    assert c["verdict"] == "trade"
    assert {r["budget"] for r in c["operational"]["regressions_beyond_budget"]} == {"cost_per_run_usd"}
    base = Evals(repo.evals).latest_run("baseline")["run_id"]
    repo.cli("report", "--run", base)  # picks up the saved comparison
    g11 = repo.gate(repo.report(), "G11")
    assert g11["status"] == "fail" and "trade" in g11["detail"]


def test_operational_regression_at_same_correctness_is_worse(make_repo):
    repo = make_repo()
    set_budget(repo, cost_per_run_usd=0.004, latency_p90_ms=10000, error_rate=0.5)
    baseline(repo)
    candidate(repo, variant="costly")
    c = comparison(repo)
    assert c["gains"] == [] and c["losses"] == []
    assert c["verdict"] == "worse"
    assert any("operational regression" in r for r in c["verdict_reasons"])
    assert c["operational_delta"]["cost_per_success"] > 0


def test_redundant_suite_is_reported_and_pruned_without_losing_detectable_effect(make_repo):
    repo = make_repo()
    baseline(repo)
    candidate(repo, break_cases=["book-001", "book-002"])  # the versions differ on 2 of 10 cases
    assert repo.cli("redundancy") == 0
    repo.cli("report", "--run", Evals(repo.evals).latest_run("baseline")["run_id"])
    r = repo.report()["redundancy"]
    assert len(r["candidates"]) == 2
    assert (r["always_pass"], r["always_fail"], r["discriminating"]) == (8, 0, 2)
    assert r["discriminating_fraction"] == 0.2 and r["below_threshold"]

    p = r["proposal"]
    assert p["keep_discriminating"] == ["book-001", "book-002"]
    assert set(p["keep_quality_estimate"]) == {"book-q01", "book-q02", "none-q01"}  # never pruned
    assert set(p["prune"]) == {"book-003", "book-004", "book-005", "none-001", "none-002"}
    assert p["suite_size"] == {"before": 10, "after": 5}
    assert p["detectable_effect"]["preserved"]
    test = p["detectable_effect"]["pairwise_tests"][0]
    assert test["before"] == test["after"] == {"gains": 0, "losses": 2, "p": 0.5}
    assert abs(p["share_of_run_cost_saved"] - 0.5) < 1e-9

    c15 = next(g for g in gates.evaluate(Evals(repo.evals)) if g.id == "C15")
    assert c15.status == "met" and "20%" in c15.info[0]
    assert any("prune" in a["action"] for a in repo.report()["next_actions"])


def test_coverage_cell_or_category_keeps_a_regression_guard(make_repo):
    repo = make_repo()
    # move the only quality-estimate "nothing" case out, so nothing-to-do needs a guard
    path = repo.evals / "cases/nothing-to-do/none-q01.json"
    case = json.loads(path.read_text())
    case["set"] = "error_finding"
    path.write_text(json.dumps(case, indent=2))
    repo.commit("none-q01 to error-finding")
    baseline(repo)
    candidate(repo, break_cases=["book-001"])
    repo.cli("redundancy")
    from aot_evals.suite import redundancy
    p = redundancy(Evals(repo.evals))["proposal"]
    assert len(p["keep_regression_guards"]) == 1
    assert p["keep_regression_guards"][0].startswith("none-")


def test_repeats_of_one_build_are_not_two_versions(make_repo):
    repo = make_repo(variant="flaky")
    baseline(repo)
    baseline(repo)
    from aot_evals.suite import redundancy
    assert redundancy(Evals(repo.evals)) is None
    c15 = next(g for g in gates.evaluate(Evals(repo.evals)) if g.id == "C15")
    assert c15.status == "not_applicable"


def test_coverage_lists_empty_cells_with_the_most_valuable_first(make_repo, capsys):
    repo = make_repo()
    tax = repo.yaml("taxonomy.yaml")
    tax["entries"][1]["not_applicable"] = {"meeting-not-booked": "leaving the calendar alone books nothing"}
    repo.write_yaml("taxonomy.yaml", tax)
    capsys.readouterr()
    assert repo.cli("coverage", "--json") == 0
    cov = json.loads(capsys.readouterr().out)
    q = cov["authoring_queue"]
    assert q[0]["taxonomy_entry"] == "reschedule-meeting" and q[0]["failure_mode"] == "meeting-not-booked"
    assert all(c["n"] == 0 for c in q)
    assert cov["not_applicable_cells"] == 1
    assert not any(c["taxonomy_entry"] == "leave-alone" and c["failure_mode"] == "meeting-not-booked" for c in q)
    c14 = next(g for g in gates.evaluate(Evals(repo.evals)) if g.id == "C14")
    assert c14.status == "met"


def test_candidate_must_declare_its_variable(make_repo):
    repo = make_repo()
    baseline(repo)
    try:
        repo.cli("run", "--purpose", "candidate", "--k", "3")
    except SystemExit as e:
        assert "--variable" in str(e)
    else:
        raise AssertionError("candidate ran without a declared variable")


def test_comparison_file_name_stays_short_with_many_runs(tmp_path):
    from aot_evals.compare import comparison_path

    ev = Evals(tmp_path / "evals")
    runs = [f"2026-10-06T1{i}-00-00Z-candidate-support-top-k-8-category-half-{i}" for i in range(6)]
    comp = {"candidate": "+".join(runs), "baseline": "+".join(r.replace("candidate", "baseline") for r in runs),
            "declared_variable": "config=top_k 8"}
    name = comparison_path(ev, comp).name
    assert len(name) < 64 and name.startswith("config-top_k-8-")  # joined run ids: OSError, file name too long
    assert name != comparison_path(ev, {**comp, "candidate": runs[0]}).name


def split_runs(repo, purpose: str, *extra: str) -> list[str]:
    """One build, run category by category (to pace a throttled model)."""
    ids = []
    for cat in ("book-meeting", "nothing-to-do"):
        assert repo.cli("run", "--purpose", purpose, "--k", "3", "--force", "--category", cat,
                        "--label", cat, *extra) == 0
        ids.append(Evals(repo.evals).latest_run(purpose)["run_id"])
    return ids


def test_runs_of_one_build_split_by_category_are_compared_as_one(make_repo):
    repo = make_repo()
    base = split_runs(repo, "baseline")
    set_agent(repo, break_cases=["book-001", "book-002", "book-003", "book-004", "book-005"])
    cand = split_runs(repo, "candidate", "--variable", "config=candidate")
    args = [x for b in base for x in ("--baseline", b)] + [x for c in cand for x in ("--candidate", c)]
    c = comparison(repo, *args)
    assert c["refused"] is None, c["problems"]  # not refused for case_set/checks/judges
    assert c["n_cases"] == len(Evals(repo.evals).cases()) and len(c["losses"]) == 5
    assert c["variance_band"]["baseline"] is not None

    assert repo.cli("report", "--run", base[0], "--run", base[1]) == 0
    for row in repo.report()["categories"]:
        if row["pass_rate"]:
            assert row["pass_pow_k"] is not None and row["pass_pow_k_reason"] is None


def test_split_runs_of_different_builds_are_still_refused(make_repo):
    repo = make_repo()
    assert repo.cli("run", "--purpose", "baseline", "--k", "3", "--force", "--category", "book-meeting") == 0
    first = Evals(repo.evals).latest_run("baseline")["run_id"]
    set_agent(repo, break_cases=["book-001"])
    assert repo.cli("run", "--purpose", "baseline", "--k", "3", "--force", "--category", "nothing-to-do",
                    "--label", "later") == 0
    second = Evals(repo.evals).latest_run("baseline")["run_id"]
    candidate(repo)
    assert "baseline runs are not one build" in comparison(repo, "--baseline", first, "--baseline", second)["refused"]


def test_pass_pow_k_says_why_it_is_null(make_repo):
    repo = make_repo()
    assert repo.cli("run", "--purpose", "baseline", "--k", "1", "--force") == 0
    assert repo.cli("report") == 0
    rows = [r for r in repo.report()["categories"] if r["pass_rate"]]
    assert rows and all(r["pass_pow_k"] is None and r["pass_pow_k_reason"].startswith("k = 1") for r in rows)
