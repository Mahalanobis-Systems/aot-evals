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
    out = json.loads(capsys.readouterr().out)
    matches = out["matches"]
    assert matches and all(m["score"] > 0 for m in matches)
    assert any("tau" in m["id"] for m in matches)
    assert {s["id"] for s in out["situations"]} >= {"forbidden", "multi-turn"}
    assert cli.main(["benchmarks", "--validate"]) == 0


def test_the_situations_vocabulary_points_at_catalog_entries_that_tag_it_back():
    vocab = benchmarks.situations()
    entries = {e["id"]: e for e in benchmarks.load()}
    ids = [s["id"] for s in vocab]
    assert len(ids) == len(set(ids)) and {"unanswerable", "ambiguous", "forbidden", "multi-turn"} <= set(ids)
    for s in vocab:
        for k in ("name", "short", "meaning", "catches", "check"):
            assert isinstance(s.get(k), str) and s[k], (s["id"], k)
        assert isinstance(s.get("universal"), bool)
        assert s["from"], s["id"]
        for eid in s["from"]:
            assert eid in entries, (s["id"], eid)
            assert s["id"] in entries[eid].get("situations", []), (s["id"], eid)


def test_situations_for_the_grid_are_the_universal_ones_plus_what_the_matches_test():
    vocab = [{"id": "u", "name": "U", "short": "s", "universal": True, "catches": "c", "check": "k"},
             {"id": "x", "name": "X", "short": "s", "universal": False, "catches": "c", "check": "k"},
             {"id": "y", "name": "Y", "short": "s", "universal": False, "catches": "c", "check": "k"}]
    matches = [{"name": "A", "situations": ["x"]}, {"name": "B", "situations": ["x", "u"]}, {"name": "C"}]
    got = benchmarks.situations_for(matches, vocab)
    assert [(s["id"], s["tested_by"]) for s in got] == [("u", ["B"]), ("x", ["A", "B"])]
    assert "applies to nearly every agent" in benchmarks.render(
        [{**m, "year": 2025, "by": "b", "score": 1, "status": "active", "fit": "f", "caveats": "c",
          "good_for": [], "grading": [], "data": "synthetic", "pii": "none", "license": "MIT", "links": {},
          "why": {"workloads": [], "words": []}} for m in matches[2:]], vocab)
