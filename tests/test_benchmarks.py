"""The benchmark catalog is valid, big enough, and matching finds the right entries."""

from __future__ import annotations

import json

from aot_evals import benchmarks, cli


def test_the_catalog_is_valid_and_has_at_least_100_entries():
    entries = benchmarks.load()
    assert benchmarks.validate(entries) == []
    assert len(entries) >= 100


def test_every_workload_in_the_vocabulary_has_a_catalog_entry_or_is_rare():
    entries = benchmarks.load()
    covered = {w for e in entries for w in e["workloads"]}
    # Verticals we list but may not have a benchmark for yet are allowed to be empty.
    rare = {"real-estate", "logistics", "insurance", "manufacturing", "government", "telecom", "hr", "embodied",
            "games"}
    assert benchmarks.WORKLOADS - covered <= rare, benchmarks.WORKLOADS - covered


def test_matching_scores_workload_overlap_above_word_overlap():
    entries = [
        {"id": "a", "name": "A", "year": 2024, "by": "x", "workloads": ["customer-support"],
         "task_types": ["look up an order", "cancel a booking"], "status": "active", "size": 10,
         "fit": "f", "caveats": "c", "good_for": ["baseline"], "grading": ["state-diff"], "data": "synthetic",
         "pii": "none", "license": "MIT", "links": {"paper": "p"}},
        {"id": "b", "name": "B", "year": 2025, "by": "x", "workloads": ["coding"],
         "task_types": ["fix a bug", "look up an order"], "status": "active", "size": None,
         "fit": "f", "caveats": "c", "good_for": ["baseline"], "grading": ["unit-tests"], "data": "synthetic",
         "pii": "none", "license": "MIT", "links": {"paper": "p"}},
        {"id": "s", "name": "S", "year": 2023, "by": "x", "workloads": ["customer-support"],
         "task_types": ["look up an order"], "status": "saturated", "size": 5,
         "fit": "f", "caveats": "c", "good_for": ["baseline"], "grading": ["exact-match"], "data": "synthetic",
         "pii": "none", "license": "MIT", "links": {"paper": "p"}},
    ]
    got = benchmarks.match(entries, ["customer-support"], ["look up an order by id"])
    assert [m["id"] for m in got] == ["a", "b"]  # saturated s is hidden; a wins on the workload tag
    assert got[0]["why"] == {"workloads": ["customer-support"], "words": ["look", "order"]}
    assert [m["id"] for m in benchmarks.match(entries, [], ["look up an order"], include_saturated=True)] \
        == ["b", "a", "s"]  # equal word scores: newest first


def test_the_command_matches_from_the_local_catalog(capsys):
    assert cli.main(["benchmarks", "--workload", "customer-support", "--task", "cancel a booking under policy",
                     "--json"]) == 0
    matches = json.loads(capsys.readouterr().out)
    assert matches and all(m["score"] > 0 for m in matches)
    assert any("tau" in m["id"] for m in matches)
    assert cli.main(["benchmarks", "--validate"]) == 0
