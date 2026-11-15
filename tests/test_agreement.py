"""`agreement`: the eval's verdict on whole runs against a person's (rule 15; docs/v2-design.md §6).

Acceptance: labelled runs are re-graded with the eval as it is now; a run the person fails and
the eval passes is listed with the person's note; the eval is held to people until every dev
disagreement has a cause; a change to a check makes the measurement stale.

The fixture is the store's end-to-end eval (conftest `store_repo`) on four of its cases, one per
use case, with `AGENT_BREAK` making the order-status one go wrong. The gates each have a fixture
of their own in test_measurement.py; here each test triggers at most the gate it is about.
"""

from __future__ import annotations

import csv
import json

import pytest
import yaml
from conftest import StoreRepo

from aot_evals import agreement

CASES = ("tr_1005", "tr_1204", "tr_1238", "tr_1144")  # order-status, address, refund, return
BROKEN = "tr_1005"


def _people_spec(s: StoreRepo) -> None:
    """Floors low enough, and one label of each kind enough, that a handful of labels meets
    them: only the gate a test is about is left open."""
    path = s.agent / "end-to-end" / "eval.yaml"
    data = yaml.safe_load(path.read_text())
    data["measurement"]["people"] = {"floors": {"catch": 0.1, "clean": 0.1}, "margin": 0.10, "labels_per_kind": 1}
    path.write_text(yaml.safe_dump(data, sort_keys=False))


def baseline(s: StoreRepo, broken: bool = False) -> str:
    _people_spec(s)
    if broken:
        s.set_env(AGENT_BREAK=BROKEN)
    s.commit("baseline")
    assert s.cli("run", "--purpose", "baseline", *[a for c in CASES for a in ("--case", c)]) == 0
    return s.ev().runs("baseline")[-1]["run_id"]


def _gate_ids(s: StoreRepo) -> list[str]:
    ev = s.ev()
    return [g["id"] for g in agreement.gates(ev, agreement.load_result(ev), agreement.load_labels(ev))]


def _label_all(s: StoreRepo, fail: dict[str, str]) -> None:
    """Queue one run per case, label it like a person would, and import the CSV."""
    assert s.cli("agreement", "label", "queue") == 0
    ev = s.ev()
    q = json.loads(ev.p("data", "agreement", "queue.json").read_text())
    assert len(q["items"]) == len(CASES)
    assert all("expected_end_state" not in json.dumps(i["input"]) for i in q["items"])
    assert {i["use_case"] for i in q["items"]} == {"order-status", "address", "refund", "return"}
    path = s.root / "labels.csv"
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=agreement.LABEL_FIELDS)
        w.writeheader()
        for it in q["items"]:
            bad = it["case_id"] in fail
            w.writerow({**it, "label": "fail" if bad else "pass", "labeller": "ana",
                        "note": fail.get(it["case_id"], ""), "input": json.dumps(it["input"])})
    assert s.cli("agreement", "label", "import", "--csv", str(path)) == 0  # creates labels/
    # the split is a hash of the run id; pin every label to dev so the dev rules are exercised
    labels = agreement.labels_path(ev)
    rows = [json.loads(line) for line in labels.read_text().splitlines()]
    labels.write_text("".join(json.dumps({**r, "split": "dev"}) + "\n" for r in rows))


def test_agreement_needs_a_baseline_then_labels(store_repo):
    s = store_repo
    with pytest.raises(SystemExit, match="run a baseline first"):
        s.cli("agreement", "label", "queue")
    baseline(s)
    problems = agreement.gate_problems(s.ev(), None)
    assert any("whole-run labels per kind: 0 of 1 failing, 0 of 1 passing" in p for p in problems)
    assert problems[-1] == "agreement not measured (aot-evals agreement)"


def test_disagreements_are_listed_with_the_note_and_must_be_triaged(store_repo):
    s = store_repo
    baseline(s, broken=True)
    _label_all(s, {BROKEN: "gave the wrong arrival date", "tr_1204": "changed the wrong order"})
    assert s.cli("agreement") == 1  # a gate is open
    res = agreement.load_result(s.ev())
    by_case = {d["case_id"]: d for d in res["disagreements"]}
    assert BROKEN not in by_case  # the eval fails it too
    d = by_case["tr_1204"]
    assert d["human"] == "fail" and d["suite"] == "pass" and d["note"] == "changed the wrong order"
    assert d["use_case"] == "address"
    assert res["dev"]["catch"]["k"] == 1 and res["dev"]["catch"]["n"] == 2
    assert res["use_cases"]["address"]["dev"]["catch"]["n"] == 1
    assert res["labels_per_kind"] == {"fail": 2, "pass": 2} and res["evidence"]["status"] == "meets"
    # labels on one run per case, combined with the eval's verdict on the other trials
    h = res["human_anchored"]
    assert h["n_labeled"] == res["all"]["runs"] - res["all"]["no_verdict"]
    assert h["n_unlabeled"] > 0 and 0 <= h["ci"][0] <= h["point"] <= h["ci"][1] <= 1
    assert [g["id"] for g in res["gates"]] == ["people_triage"]
    assert "without a cause" in res["gates"][0]["detail"]
    agreement.triage_path(s.ev()).write_text(yaml.safe_dump(
        {d["item"]: {"cause": "missing-requirement", "note": "no check on which order changed"}}))
    assert s.cli("agreement") == 0
    assert agreement.load_result(s.ev())["gates"] == [] and _gate_ids(s) == []


def test_a_changed_check_makes_agreement_stale(store_repo):
    s = store_repo
    baseline(s)
    _label_all(s, {})
    s.cli("agreement")
    assert "people_stale" not in _gate_ids(s)
    check = s.agent / "end-to-end" / "checks" / "code" / "routed-correctly.py"
    check.write_text(check.read_text() + "\n# edited\n")
    assert "people_stale" in _gate_ids(s)


def test_regrade_reproduces_the_recorded_code_verdicts(store_repo):
    s = store_repo
    run_id = baseline(s, broken=True)
    ev = s.ev()
    r = agreement.reproduces(ev, run_id)
    assert r["compared"] > 0 and r["differ"] == {}
    rows = agreement.regrade(ev, run_id)
    assert {r["verdict"] for r in rows if f"/{BROKEN}." in r["item"]} == {"fail"}
    assert {r["verdict"] for r in rows if f"/{BROKEN}." not in r["item"]} == {"pass"}


def test_a_note_holding_a_secret_is_not_imported(store_repo):
    s = store_repo
    run_id = baseline(s)
    ev = s.ev()
    item = agreement.finals(ev, [run_id])[0]
    key = agreement.item_key(item["run_id"], item["case_id"], item["trial"], item["attempt"])
    res = agreement.add(ev, key, "fail", "ana", "token sk-ant-api03-" + "a" * 40)
    assert res["added"] == 0 and res["problems"]


def test_labels_made_elsewhere_attach_to_a_run_by_case_and_trial(store_repo):
    s = store_repo
    run_id = baseline(s)
    path = s.root / "outside.csv"
    path.write_text("case_id,trial,label,note\ntr_1204,1,fail,wrong address\ntr_9999,0,pass,\n")
    assert s.cli("agreement", "label", "import", "--csv", str(path), "--by", "ana", "--run", run_id) == 1
    labels = agreement.load_labels(s.ev())
    assert len(labels) == 1 and labels[0]["item_id"].startswith(f"{run_id}/tr_1204.t1.a")
