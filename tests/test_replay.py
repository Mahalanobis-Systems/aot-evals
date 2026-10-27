"""`replay`: recorded runs graded through the ordinary contract, with no live agent.

Acceptance: a suite whose agent.yaml points at `aot-evals replay` runs a baseline over recorded
runs; a recorded run that left the world unchanged fails its case; a missing record is an
operational outcome, not a correctness failure.
"""

from __future__ import annotations

import json
import sys

from aot_evals.repo import Evals


def _record_all(repo, broken: set[str], missing: set[str] = frozenset()) -> None:
    d = repo.root / "records"
    d.mkdir()
    for path in (repo.evals / "cases").glob("*/*.json"):
        case = json.loads(path.read_text())
        for t in range(3):
            if (case["id"], t) in missing:
                continue
            world = case["start_state"] if case["id"] in broken else case["expected_end_state"]["world"]
            (d / f"{case['id']}.t{t}.json").write_text(json.dumps({"answer": "Done.", "world": world}))
    py = f'"{sys.executable}" -m aot_evals replay'
    agent = (repo.evals / "agent.yaml").read_text()
    head, _, _ = agent.partition("invoke:")
    (repo.evals / "agent.yaml").write_text(head + f"""invoke:
  command: ["{sys.executable}", "-m", aot_evals, replay, run, records]
  cwd: .
  timeout: 30
  max_attempts: 1
  seed: '{py} seed records'
  observe: '{py} observe records'
  reset_scope: case
""")
    (repo.root / ".gitignore").write_text("world.json\nrecords/.replay-state.json\n")
    repo.commit("replay the recorded runs")


def _finals(repo) -> list[dict]:
    ev = Evals.find(str(repo.evals))
    run = ev.latest_run("baseline")["run_id"]
    return [a for a in ev.run_records(run) if a.get("kind") == "attempt" and a.get("final")]


def test_a_baseline_over_recorded_runs(make_repo):
    repo = make_repo()
    _record_all(repo, broken={"book-002"})
    assert repo.cli("run", "--purpose", "baseline", "--k", "3", "--force") == 0
    finals = _finals(repo)
    assert len(finals) == 30 and all(a["outcome"] == "ok" for a in finals)
    assert {a["passed"] for a in finals if a["case_id"] == "book-002"} == {False}
    assert all(a["passed"] for a in finals if a["case_id"] != "book-002")


def test_a_missing_record_is_operational(make_repo):
    repo = make_repo()
    _record_all(repo, broken=set(), missing={("book-001", 1)})
    repo.cli("run", "--purpose", "baseline", "--k", "3", "--force")
    a = next(a for a in _finals(repo) if a["case_id"] == "book-001" and a["trial"] == 1)
    assert a["outcome"] == "no_output" and a["passed"] is None
