"""`replay`: recorded runs graded through the ordinary contract, with no live agent.

Acceptance: an eval whose agent.yaml points at `aot-evals replay` runs a baseline over recorded
runs; a recorded run that left the world unchanged fails its case; a missing record is an
operational outcome, not a correctness failure; the records, not the invoke, are what the run
records, and replayed costs and latencies are not held to budgets.

The fixture is the store's end-to-end eval (conftest `store_repo`) on three of its cases.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest
import yaml
from conftest import StoreRepo

import aot_evals

CASES = ("tr_1005", "tr_1204", "tr_1144")  # order-status, a refused address change, a return
BROKEN = "tr_1144"  # its recorded run started no return


@pytest.fixture(autouse=True)
def absolute_pythonpath(monkeypatch):
    # The replay commands run in the fixture repo, where a relative PYTHONPATH (as CI sets) finds nothing.
    src = str(Path(aot_evals.__file__).resolve().parents[1])
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join(filter(None, [src, os.environ.get("PYTHONPATH")])))


def _record_all(s: StoreRepo, broken: set[str], missing: set[tuple[str, int]] = frozenset()) -> None:
    d = s.root / "records"
    d.mkdir()
    ev = s.ev()
    for case in ev.cases():
        if case["id"] not in CASES:
            continue
        exp = case["expected_end_state"]
        for t in range(3):
            if (case["id"], t) in missing:
                continue
            world = case["start_state"] if case["id"] in broken else exp["world"]
            (d / f"{case['id']}.t{t}.json").write_text(json.dumps({"answer": exp["output"], "world": world}))
    py = f'"{sys.executable}" -m aot_evals replay'
    path = s.agent / "agent.yaml"
    data = yaml.safe_load(path.read_text())
    data["invoke"] = {"command": [sys.executable, "-m", "aot_evals", "replay", "run", "records"], "cwd": ".",
                      "timeout": 30, "max_attempts": 1, "seed": f"{py} seed records",
                      "observe": f"{py} observe records", "reset_scope": "case"}
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    (s.root / ".gitignore").write_text("world.json\n__pycache__/\nrecords/.replay-state.json\n")
    s.commit("replay the recorded runs")


def _baseline(s: StoreRepo) -> str:
    assert s.cli("run", "--purpose", "baseline", *[a for c in CASES for a in ("--case", c)]) == 0
    return s.ev().runs("baseline")[-1]["run_id"]


def _finals(s: StoreRepo, run: str) -> list[dict]:
    return [a for a in s.ev().run_records(run) if a.get("kind") == "attempt" and a.get("final")]


def test_a_baseline_over_recorded_runs(store_repo):
    s = store_repo
    _record_all(s, broken={BROKEN})
    finals = _finals(s, _baseline(s))
    assert len(finals) == 9 and all(a["outcome"] == "ok" for a in finals)
    assert {a["passed"] for a in finals if a["case_id"] == BROKEN} == {False}
    assert all(a["passed"] for a in finals if a["case_id"] != BROKEN)


def test_a_missing_record_is_operational(store_repo):
    s = store_repo
    _record_all(s, broken=set(), missing={("tr_1005", 1)})
    a = next(a for a in _finals(s, _baseline(s)) if a["case_id"] == "tr_1005" and a["trial"] == 1)
    assert a["outcome"] == "no_output" and a["passed"] is None


def test_a_replay_records_its_records_and_is_not_held_to_budgets(store_repo):
    s = store_repo
    _record_all(s, broken=set())
    first = _baseline(s)
    path = s.agent / "agent.yaml"
    path.write_text(path.read_text().replace("timeout: 30", "timeout: 40"))
    s.commit("a different invoke, the same records")
    second = _baseline(s)
    replays = [s.ev().run_manifest(r)["replay"] for r in (first, second)]
    assert replays[0]["records"] == "records" and replays[0]["sha256"] is not None
    assert replays[0] == replays[1]  # the records, by content, not the invoke around them
    assert s.cli("report", "--run", second) == 0
    rows = [u for u in s.report()["use_cases"] if u["id"] in ("order-status", "address", "return")]
    assert rows and all(u["operational"]["budget_status"] == "not_measured" for u in rows)
