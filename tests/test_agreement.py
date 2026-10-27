"""C19 agreement: the suite's verdict on whole runs against a person's.

Acceptance: labelled runs are re-graded with the suite as it is now; a run the person fails and
the suite passes is listed with the person's note; the gate stays open until every dev
disagreement has a cause and the rates clear their floors; a change to a check makes the
measurement stale.
"""

from __future__ import annotations

import csv
import json

import yaml
from test_suite import baseline

from aot_evals import agreement, gates
from aot_evals.repo import Evals


def _gate(repo) -> gates.Gate:
    return next(g for g in gates.evaluate(Evals.find(str(repo.evals))) if g.id == "C19")


def _label_all(repo, fail: dict[str, str]) -> None:
    """Queue one run per case, label it like a person would, and import the CSV."""
    assert repo.cli("agreement", "label", "queue") == 0
    q = json.loads((repo.evals / "data" / "agreement" / "queue.json").read_text())
    assert q["items"] and all("expected_end_state" not in json.dumps(i["input"]) for i in q["items"])
    path = repo.root / "labels.csv"
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=agreement.LABEL_FIELDS)
        w.writeheader()
        for it in q["items"]:
            bad = it["case_id"] in fail
            w.writerow({**it, "label": "fail" if bad else "pass", "labeller": "ana",
                        "note": fail.get(it["case_id"], ""), "input": json.dumps(it["input"])})
    assert repo.cli("agreement", "label", "import", "--csv", str(path)) == 0  # creates labels/
    _small_floors(repo)
    # the split is a hash of the run id; pin every label to dev so the gate's dev rules are exercised
    labels = repo.evals / "labels" / "runs.jsonl"
    rows = [json.loads(line) for line in labels.read_text().splitlines()]
    labels.write_text("".join(json.dumps({**r, "split": "dev"}) + "\n" for r in rows))


def _small_floors(repo) -> None:
    (repo.evals / "labels").mkdir(exist_ok=True)
    (repo.evals / "labels" / "floors.yaml").write_text(yaml.safe_dump(
        {"min_runs": 5, "min_each": 1, "min_catch": 0.5, "min_clean": 0.5}))


def test_c19_needs_a_baseline_then_labels(make_repo):
    repo = make_repo()
    assert _gate(repo).status == "unmet" and "baseline" in _gate(repo).problems[0]
    baseline(repo)
    g = _gate(repo)
    assert g.status == "unmet" and "whole runs labelled" in g.problems[0]


def test_disagreements_are_listed_with_the_note_and_must_be_triaged(make_repo):
    repo = make_repo()
    baseline(repo, break_cases=["book-002"])
    _label_all(repo, {"book-002": "booked the wrong slot", "book-003": "invited the wrong person"})
    repo.cli("agreement")
    res = json.loads((repo.evals / "report" / "agreement.json").read_text())
    by_case = {d["case_id"]: d for d in res["disagreements"]}
    assert "book-002" not in by_case  # the suite fails it too
    d = by_case["book-003"]
    assert d["human"] == "fail" and d["suite"] == "pass" and d["note"] == "invited the wrong person"
    assert res["dev"]["catch"]["k"] == 1 and res["dev"]["catch"]["n"] == 2
    assert any("without a cause" in p for p in _gate(repo).problems)
    (repo.evals / "labels" / "triage.yaml").write_text(yaml.safe_dump(
        {d["item"]: {"cause": "missing-requirement", "note": "no check on the invitee"}}))
    repo.cli("agreement")
    assert _gate(repo).status == "met"


def test_a_changed_check_makes_agreement_stale(make_repo):
    repo = make_repo()
    baseline(repo)
    _label_all(repo, {})
    repo.cli("agreement")
    assert not any("stale" in p for p in _gate(repo).problems)
    check = next((repo.evals / "checks" / "code").glob("*.py"))
    check.write_text(check.read_text() + "\n# edited\n")
    assert any("stale" in p for p in _gate(repo).problems)


def test_regrade_reproduces_the_recorded_code_verdicts(make_repo, capsys):
    repo = make_repo()
    baseline(repo, break_cases=["book-002"])
    ev = Evals.find(str(repo.evals))
    run_id = ev.latest_run("baseline")["run_id"]
    r = agreement.reproduces(ev, run_id)
    assert r["compared"] > 0 and r["differ"] == {}
    rows = agreement.regrade(ev, run_id)
    assert {r["verdict"] for r in rows if "book-002" in r["item"]} == {"fail"}


def test_a_note_holding_a_secret_is_not_imported(make_repo):
    repo = make_repo()
    baseline(repo)
    ev = Evals.find(str(repo.evals))
    item = agreement.finals(ev, [ev.latest_run("baseline")["run_id"]])[0]
    key = agreement.item_key(item["run_id"], item["case_id"], item["trial"], item["attempt"])
    res = agreement.add(ev, key, "fail", "ana", "token sk-ant-api03-" + "a" * 40)
    assert res["added"] == 0 and res["problems"]


def test_labels_made_elsewhere_attach_to_a_run_by_case_and_trial(make_repo):
    repo = make_repo()
    baseline(repo)
    ev = Evals.find(str(repo.evals))
    run_id = ev.latest_run("baseline")["run_id"]
    path = repo.root / "outside.csv"
    path.write_text("case_id,trial,label,note\nbook-001,1,fail,wrong room\nbook-404,0,pass,\n")
    assert repo.cli("agreement", "label", "import", "--csv", str(path), "--by", "ana", "--run", run_id) == 1
    labels = agreement.load_labels(ev)
    assert len(labels) == 1 and labels[0]["item_id"].startswith(f"{run_id}/book-001.t1.a")
