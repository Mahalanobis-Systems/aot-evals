"""2.0 measurement (docs/v2-design.md §4, §6; estimators §5; statistics §3): catch and clean pass
rates, the judge floor from max_inflation, the corrections feeding `estimate`, the eval held to
people (report `measurement`, agreement.json's margin-based evidence and labels per kind), and
`trials: auto`.

Every gate here has a fixture that triggers exactly that gate: `measurement.gates` (the report)
and agreement.json's `gates` list one entry per gate that is not met, by id.

The fixture is test_estimand's store (the end-to-end eval on a toy agent whose refund-bug variant
fails a known third of refund cases). For the judge tests its `wrong-end-state` mode is graded by
a command judge that fails a run whose answer is "wrong", and the quantity is that mode's rate,
so the judge feeds θ̂. Its error rates come from labels written to give a chosen confusion matrix.
"""

from __future__ import annotations

import json
import sys

import pytest
import yaml
from test_estimand import DRAW, Store, _baseline, make_store

from aot_evals import cli, stats
from aot_evals.agreement import item_key
from aot_evals.measurement import judge_floor, labels_needed, people_floor
from aot_evals.repo import Evals
from aot_evals.spec import check


@pytest.fixture
def store(tmp_path, monkeypatch) -> Store:
    return make_store(tmp_path, monkeypatch)


JUDGE_PY = '''import json, sys
payload = json.load(sys.stdin)
out = str(payload["input"].get("end.output"))
print(json.dumps({"verdict": "fail" if out == "wrong" else "pass"}))
'''


# ---- stats -------------------------------------------------------------------------------------

def test_rogan_gladen_rate_is_rogan_gladen_for_a_counted_rate():
    a = stats.rogan_gladen(121, 1000, 24, 30, 873, 970)
    b = stats.rogan_gladen_rate(0.121, 0.121 * 0.879 / 1000, 24, 30, 873, 970)
    assert a["point"] == pytest.approx(b["point"]) and a["ci"] == pytest.approx(b["ci"])
    assert b["point"] == pytest.approx(0.03, abs=0.002)  # estimators §5's worked example
    # the labels' own uncertainty stays when the runs are many
    many = stats.rogan_gladen_rate(0.121, 1e-9, 24, 30, 873, 970)
    assert many["se"] == pytest.approx(many["se_from_labels"], rel=1e-4) and many["se"] > 0.01
    assert stats.rogan_gladen_rate(0.3, 0.001, 5, 10, 5, 10) is None  # J = 0


def test_ppi_weighted_never_does_much_worse_than_the_labels():
    # a grader that tracks the labels narrows the interval well below the labels alone
    y = [1, 1, 0, 1, 0, 1, 1, 1, 0, 1] * 3
    good = stats.ppi_weighted(0.70, 0.0004, y, y, [1.0] * len(y))
    assert good["lambda"] > 0.5 and good["se"] < good["labels_only"]["se"]
    # one that doesn't is given no weight: the labels alone
    noise = [1, 0] * 15
    bad = stats.ppi_weighted(0.5, 0.0004, y, noise, [1.0] * len(y))
    assert bad["lambda"] == pytest.approx(0.0, abs=0.05)
    assert bad["point"] == pytest.approx(bad["labels_only"]["point"], abs=0.02)
    # design weights move the labels' mean
    w = stats.ppi_weighted(0.5, 0.0004, [1, 0], [1, 0], [3.0, 1.0])
    assert w["labels_only"]["point"] == pytest.approx(0.75)
    assert stats.ppi_weighted(0.5, 0.01, [1], [1], [1.0]) is None


def test_trials_for_split():
    assert stats.trials_for_split(0.2, 0.0)["k"] == 3  # deterministic cases: the floor of 3
    assert stats.trials_for_split(0.01, 0.24)["k"] == 5  # sqrt(24) = 4.9
    assert stats.trials_for_split(0.01, 0.24, case_cost=4)["k"] == 10  # bounded
    assert stats.trials_for_split(0.0, 0.25) == {**stats.trials_for_split(0.0, 0.25), "k": 10, "bound": "k_max"}


# ---- the judge floor (statistics §3.3) -------------------------------------------------------

def _cal(catch_k, catch_n, clean_k, clean_n, alpha=0.05):
    from aot_evals.calibrate import catch_clean

    cc = catch_clean({"tn": catch_k, "fp": catch_n - catch_k, "tp": clean_k, "fn": clean_n - clean_k}, alpha)
    return {"status": "calibrated", "reasons": [], **{k: cc[k] for k in
            ("catch", "clean", "catch_lower", "clean_lower", "j")}}


def test_the_floor_reads_inflation_at_the_lower_bounds():
    rate = {"rate": 0.03}
    # estimators §5: the policy judge (0.80, 0.90) is refused at 3% even on many labels
    weak = judge_floor(_cal(800, 1000, 9000, 10000), rate, 2.0, 0.05)
    assert weak["status"] == "refused" and weak["inflation"] == pytest.approx(7.5, abs=0.1)
    # one at 0.95 and 0.99 costs about 1.4x at its point rates, and passes once its labels are many
    strong = judge_floor(_cal(950, 1000, 9900, 10000), rate, 2.0, 0.05)
    assert strong["inflation"] == pytest.approx(1.43, abs=0.01) and strong["status"] == "pass"
    # the same rates on few labels: the lower bounds cost more than twice the cases
    few = judge_floor(_cal(19, 20, 99, 100), rate, 2.0, 0.05)
    assert few["inflation"] == pytest.approx(1.43, abs=0.01) and few["status"] == "refused"
    assert judge_floor({"status": "stale", "reasons": ["x"]}, rate, 2.0, 0.05)["status"] == "stale"
    assert judge_floor(_cal(19, 20, 99, 100), None, 2.0, 0.05)["status"] == "unknown"


def test_people_floors_stated_with_a_margin_or_from_max_inflation(store):
    spec = store.ev().spec()
    # null floors (the store's): max_inflation at the eval's failure rate
    out = people_floor(spec, {"k": 60, "n": 60}, {"k": 300, "n": 300}, {"point": 0.1, "n_trials": 100})
    assert out["status"] == "meets" and out["evidence"]["max_inflation"]["max_inflation"] == 2.0
    assert people_floor(spec, {"k": 6, "n": 10}, {"k": 280, "n": 300},
                        {"point": 0.1, "n_trials": 100})["status"] == "below"
    # stated floors read with the margin: 13 of 15 clears 85% but not by enough (statistics §4.2)
    data = yaml.safe_load((store.eval / "eval.yaml").read_text())
    data["measurement"]["people"]["floors"] = {"catch": 0.85, "clean": 0.75}
    s2 = check(data, "end-to-end")
    out = people_floor(s2, {"k": 13, "n": 15}, {"k": 90, "n": 100}, None)
    assert out["status"] == "below" and "lower bound" in out["reasons"][0]
    assert out["evidence"]["catch"]["n_needed"] == stats.floor_evidence(13, 15, 0.85, 0.10)["n_needed"]
    assert people_floor(s2, {"k": 90, "n": 100}, {"k": 90, "n": 100}, None)["status"] == "meets"


def test_labels_needed_is_fixed_before_looking(store):
    spec = store.ev().spec()
    need = labels_needed(spec)  # auto, null floors: ±10 points at the widest rate
    assert need["fail"]["n"] == need["pass"]["n"] == stats.labels_for_halfwidth(0.5, 0.10)
    data = yaml.safe_load((store.eval / "eval.yaml").read_text())
    data["measurement"]["people"].update(floors={"catch": 0.8, "clean": None}, labels_per_kind="auto")
    need = labels_needed(check(data, "end-to-end"))
    assert need["fail"]["n"] == stats.labels_for_halfwidth(0.8, 0.10) == 60  # statistics §3.4
    data["measurement"]["people"]["labels_per_kind"] = 25
    assert labels_needed(check(data, "end-to-end"))["pass"] == {"n": 25, "source": "measurement.people.labels_per_kind"}


# ---- a judge that feeds θ̂ ------------------------------------------------------------------------

def _with_judge(s: Store, correction: str = "rogan_gladen", max_inflation: float = 2.0) -> None:
    """wrong-end-state graded by a command judge, and the estimand its failure rate."""
    (s.root / "judge.py").write_text(JUDGE_PY)
    judge = {"id": "end-state-judge", "version": 1, "question_type": "noul", "detects": "failure",
             "question": "The order system ends in another state than the request called for.",
             "inputs": ["end.output"], "primary": "local",
             "backends": {"local": {"type": "command", "command": [sys.executable, str(s.root / "judge.py")],
                                    "family": "toy", "model": "toy-judge"}}}
    d = s.eval / "checks" / "judge"
    d.mkdir(parents=True, exist_ok=True)
    (d / "end-state-judge.md").write_text("---\n" + yaml.safe_dump(judge) + "---\nPass or fail.\n")
    data = yaml.safe_load((s.eval / "eval.yaml").read_text())
    data["estimand"]["quantity"] = "failure_rate:wrong-end-state"
    for fm in data["measurement"]["failure_modes"]:
        if fm["id"] == "wrong-end-state":
            # the code check stays as a diagnostic: reported, never counted (rule 12)
            fm.update(check="end-state-judge", diagnostics=["end-state-matches"])
    data["measurement"].update(correction=correction, max_inflation=max_inflation)
    data["decision_rule"] = {"test": "threshold", "bar": 0.10, "alpha": 0.05, "power": 0.80}
    (s.eval / "eval.yaml").write_text(yaml.safe_dump(data, sort_keys=False))


def _label_judge(s: Store, catch: tuple[int, int], clean: tuple[int, int], run: str | None = None,
                 trials: list[tuple] | None = None) -> None:
    """Labels that give the judge `catch` = (caught, failing labels) and `clean` = (passed,
    passing labels): a run the judge fails is one whose answer is "wrong"."""
    rows = []

    def add(i, out, label, extra=None):
        # item ids name their content: calibrate caches a judge's verdict by item id
        iid = f"{'trial' if extra else 'lab'}-{i}-{out}"
        rows.append({"item_id": iid, "case_id": iid, "label": label, "labeller": "pat",
                     "split": "dev", "input": {"end.output": out}, **(extra or {})})
    i = 0
    for a in trials or []:  # labels on real trials, for PPI: the person agrees with the judge
        case_id, trial, attempt, wrong = a
        add(i, "wrong" if wrong else "ok", not wrong, {"case_id": case_id, "run": run, "trial": trial,
                                                        "attempt": attempt})
        i += 1
    for k in range(catch[1]):
        add(i, "wrong" if k < catch[0] else "ok", False)
        i += 1
    for k in range(clean[1]):
        add(i, "ok" if k < clean[0] else "wrong", True)
        i += 1
    p = s.eval / "checks" / "judge" / "end-state-judge.labels.jsonl"
    p.write_text("".join(json.dumps(r) + "\n" for r in rows))
    assert s.cli("calibrate", "--judge", "end-state-judge") == 0


def _gate_ids(r: dict) -> list[str]:
    return [g["id"] for g in r["measurement"]["gates"] if not g["id"].startswith("people_")]


def test_an_uncalibrated_judge_leaves_the_estimate_null(store):
    _with_judge(store)
    store.commit()
    _baseline(store)
    assert store.cli("report") == 0
    r = store.report()
    assert _gate_ids(r) == ["judge_calibration"]
    est = r["estimate"]
    assert est["theta"] is None and "rule 13" in est["null_reason"] and "end-state-judge" in est["null_reason"]
    assert est["uncorrected"]["theta"] > 0  # the judge's own number, kept beside the null
    fm = next(m for m in r["measurement"]["failure_modes"] if m["id"] == "wrong-end-state")
    assert fm["type"] == "judge" and fm["calibration"] == "uncalibrated" and fm["feeds_estimate"]


def test_a_judge_within_max_inflation_counts_and_is_corrected(store):
    _with_judge(store)
    _label_judge(store, (60, 60), (400, 400))
    cal = json.loads((store.eval / "checks" / "judge" / "end-state-judge.calibration.json").read_text())
    m = cal["backends"]["local"]
    assert cal["status"] == "calibrated" and "min_tpr" not in cal
    assert cal["floor"].startswith("measurement.max_inflation")
    assert m["catch"] == 1.0 and m["clean"] == 1.0 and m["labels_per_kind"] == {"fail": 60, "pass": 400}
    assert m["catch"] == m["tnr"] and m["clean"] == m["tpr"]  # 1.x names kept beside them
    store.commit()
    _baseline(store)
    assert store.cli("report") == 0
    r = store.report()
    assert _gate_ids(r) == []
    fm = next(m for m in r["measurement"]["failure_modes"] if m["id"] == "wrong-end-state")
    assert fm["floor"]["status"] == "pass" and fm["inflation_at_lower_bounds"] <= 2.0
    assert fm["labels"] == {"fail": 60, "pass": 400}
    est = r["estimate"]
    assert est["corrected"] and est["correction"] == "rogan_gladen"
    obs, c = est["uncorrected"], est["correction_detail"]
    assert est["theta"] == pytest.approx(max(0.0, (obs["theta"] + c["clean"] - 1) / c["j"]))
    assert est["se"] > obs["se"] * 0.99  # the calibration's uncertainty widens it
    lines = [x for x in store.ev().run_records(r["runs"][0]) if x["kind"] == "check"]
    assert {x["check_id"] for x in lines if not x["counted"]} == {"end-state-matches"}
    assert store.cli("screen", "--judges", "--all", "--read-by", "tester") == 0  # 2.0 judges screen too
    code = next(m for m in r["measurement"]["failure_modes"] if m["id"] == "unrequested-change")
    assert code["type"] == "code" and code["floor"]["status"] == "pass" and code["inflation"] == 1.0


def test_a_judge_over_max_inflation_is_refused(store):
    _with_judge(store)
    _label_judge(store, (8, 10), (90, 100))  # catch 0.80, clean 0.90 (statistics §3.3)
    store.commit()
    _baseline(store)
    assert store.cli("report") == 0
    r = store.report()
    assert _gate_ids(r) == ["judge_floor"]
    fm = next(m for m in r["measurement"]["failure_modes"] if m["id"] == "wrong-end-state")
    assert fm["floor"]["status"] == "refused" and fm["inflation_at_lower_bounds"] > 2.0
    assert fm["catch"] == pytest.approx(0.8) and fm["clean"] == pytest.approx(0.9)
    assert r["estimate"]["theta"] is None and "max_inflation" in r["estimate"]["null_reason"]
    # labels for a 2.0 judge are queued from its eval's runs, by use case; judge apply reads it too
    assert store.cli("label", "queue", "--judge", "end-state-judge", "--n", "5") == 0
    q = (store.eval / "checks" / "judge" / "end-state-judge.queue.csv").read_text()
    assert "refund" in q or "order-status" in q
    assert store.cli("judge", "apply", "--judge", "end-state-judge") == 0


def test_the_limit_is_max_inflation(store):
    """The same judge, with the limit raised far enough, counts: the gate is the limit."""
    _with_judge(store, max_inflation=1000)
    _label_judge(store, (8, 10), (90, 100))
    store.commit()
    _baseline(store)
    assert store.cli("report") == 0
    r = store.report()
    assert _gate_ids(r) == [] and r["estimate"]["theta"] is not None


def test_ppi_combines_the_labeled_trials_with_every_graded_one(store):
    _with_judge(store, correction="ppi")
    _label_judge(store, (60, 60), (400, 400))
    store.commit()
    m = _baseline(store)
    ev = store.ev()
    finals = [a for a in ev.run_records(m["run_id"]) if a["kind"] == "attempt" and a.get("final")
              and a["case_id"].startswith("tr_")]
    picked = finals[::3]
    raw = {a["case_id"]: json.loads((store.eval / "runs" / m["run_id"] / "raw" /
                                     f"{a['case_id']}.t{a['trial']}.a{a['attempt']}.json").read_text())
           for a in picked}
    _label_judge(store, (60, 60), (400, 400), run=m["run_id"],
                 trials=[(a["case_id"], a["trial"], a["attempt"], raw[a["case_id"]]["output"] == "wrong")
                         for a in picked])
    assert store.cli("report") == 0
    r = store.report()
    est, pa = r["estimate"], r["measurement"]["person_anchored"]["ppi"]
    assert est["corrected"] and est["correction"] == "ppi" and pa["n_labeled"] == len(picked)
    assert est["theta"] == pytest.approx(pa["point"]) and pa["labels_from"] == "judge end-state-judge's labels"
    # the person agrees with the judge on every labeled trial: the estimate is the judge's
    assert est["theta"] == pytest.approx(est["uncorrected"]["theta"], abs=1e-9)
    assert pa["se"] <= pa["labels_only"]["se"] + 1e-12


def test_calibrate_and_label_status_speak_catch_and_clean(store, capsys):
    _with_judge(store)
    _label_judge(store, (8, 10), (90, 100))
    out = capsys.readouterr().out
    assert "catch" in out and "clean" in out and "TPR" not in out
    assert store.cli("label", "status", "--judge", "end-state-judge") == 0
    out = capsys.readouterr().out
    assert "10 failing, 100 passing" in out and "max_inflation" in out


def test_min_tpr_on_a_2_0_judge_is_a_note(store):
    _with_judge(store)
    p = store.eval / "checks" / "judge" / "end-state-judge.md"
    p.write_text(p.read_text().replace("version: 1\n", "version: 1\nmin_tpr: 0.8\n"))
    spec = Evals(store.agent).eval("end-to-end").spec()
    assert any(n.field == "checks/judge/end-state-judge.md" and "min_tpr" in n.why for n in spec.notes)


# ---- the eval against people: agreement.json and its gates ------------------------------------

def _people(s: Store, *, labels_per_kind=3, floors=None, flip: int = 0, dispute: bool = False) -> dict:
    """A baseline, then whole-run labels on its final attempts that agree with the eval's verdict
    (bar `flip` of the failing ones), measured with `agreement`."""
    data = yaml.safe_load((s.eval / "eval.yaml").read_text())
    # stated floors low enough that a handful of labels meets them; the max_inflation reading
    # on few labels is tested on its own (test_people_floors_stated_with_a_margin_or_from_max_inflation)
    data["measurement"]["people"] = {"floors": floors or {"catch": 0.5, "clean": 0.5}, "margin": 0.10,
                                     "labels_per_kind": labels_per_kind}
    (s.eval / "eval.yaml").write_text(yaml.safe_dump(data, sort_keys=False))
    s.commit()
    m = _baseline(s)
    ev = s.ev()
    recs = ev.run_records(m["run_id"])
    finals = [a for a in recs if a["kind"] == "attempt" and a.get("final")]
    failed = {(r["case_id"], r["trial"]) for r in recs if r["kind"] == "check" and r["passed"] is False}
    flipped = 0
    for a in finals:
        bad = (a["case_id"], a["trial"]) in failed
        human = "fail" if bad else "pass"
        if bad and flipped < flip:
            human, flipped = "pass", flipped + 1
        item = item_key(m["run_id"], a["case_id"], a["trial"], a["attempt"])
        assert s.cli("agreement", "label", "add", "--item", item,
                     "--label", human, "--by", "pat") == 0
    if dispute:
        a = next(x for x in finals if (x["case_id"], x["trial"]) not in failed)
        s.cli("agreement", "label", "add", "--item", item_key(m["run_id"], a["case_id"], a["trial"], a["attempt"]),
              "--label", "fail", "--by", "sam")
    s.cli("agreement")
    return json.loads((s.eval / "report" / "agreement.json").read_text())


def _triage_all(s: Store, result: dict) -> None:
    (s.eval / "labels" / "triage.yaml").write_text(yaml.safe_dump(
        {d["item"]: {"cause": "check-bug", "note": "fixture"} for d in result["disagreements"]}))


def test_the_eval_meets_people(store):
    r = _people(store)
    assert r["gates"] == [] and r["problems"] == []
    assert r["labels_per_kind"]["fail"] >= 3 and r["labels_needed"]["fail"]["n"] == 3
    assert r["evidence"]["status"] == "meets" and r["floors"]["margin"] == 0.10
    assert store.cli("report") == 0
    people = store.report()["measurement"]["eval_vs_people"]
    assert people["catch"]["rate"] == 1.0 and people["clean"]["rate"] == 1.0 and people["floor"]["status"] == "meets"
    assert [g for g in store.report()["measurement"]["gates"]] == []


def test_gate_people_labels(store):
    r = _people(store, labels_per_kind=500)
    assert [g["id"] for g in r["gates"]] == ["people_labels"]
    assert "of 500 failing" in r["gates"][0]["detail"]


def test_gate_people_floor(store):
    r = _people(store, floors={"catch": 0.95, "clean": 0.5}, flip=2)
    _triage_all(store, r)
    store.cli("agreement")
    r = json.loads((store.eval / "report" / "agreement.json").read_text())
    assert [g["id"] for g in r["gates"]] == ["people_floor"]
    assert r["evidence"]["status"] == "below" and "catch rate" in r["gates"][0]["detail"]


def test_gate_people_triage(store):
    r = _people(store, floors={"catch": 0.10, "clean": 0.10}, flip=4)
    dev = [d for d in r["disagreements"] if d["split"] == "dev"]
    assert dev, "the fixture needs a dev disagreement"
    assert [g["id"] for g in r["gates"]] == ["people_triage"]
    _triage_all(store, r)
    store.cli("agreement")
    assert json.loads((store.eval / "report" / "agreement.json").read_text())["gates"] == []


def test_gate_people_disputes(store):
    r = _people(store, dispute=True)
    assert [g["id"] for g in r["gates"]] == ["people_disputes"]


def test_gate_people_stale(store):
    _people(store)
    (store.eval / "checks" / "code" / "routed-correctly.py").write_text("def check(start, end, case):\n"
                                                                         "    return True, 'changed'\n")
    assert store.cli("report") == 0
    gates = store.report()["measurement"]["gates"]
    assert [g["id"] for g in gates] == ["people_stale"]


def test_unmeasured_people_is_its_own_gate(store):
    _baseline(store)
    assert store.cli("report") == 0
    assert [g["id"] for g in store.report()["measurement"]["gates"]] == ["people_unmeasured"]


# ---- trials: auto (rule 16) ----------------------------------------------------------------------

def test_trials_auto(store):
    data = yaml.safe_load((store.eval / "eval.yaml").read_text())
    data["measurement"]["trials"] = "auto"
    (store.eval / "eval.yaml").write_text(yaml.safe_dump(data, sort_keys=False))
    store.commit()
    m = _baseline(store)
    assert m["k"] == 3 and m["trials"]["spec"] == "auto" and m["trials"]["source"].startswith("auto: 3 until")
    assert store.cli("report") == 0
    v = store.report()["measurement"]["variance"]
    assert v["within"] == 0.0 and v["k_recommended"] == 3  # a deterministic agent: no trial noise
    assert store.cli("run", "--purpose", "baseline") == 0
    m2 = store.ev().runs("baseline")[-1]
    assert m2["k"] == 3 and m2["trials"]["source"].startswith("auto: from the variance split")


def test_report_measurement_key_shape(store):
    _baseline(store)
    assert store.cli("report") == 0
    meas = store.report()["measurement"]
    assert set(meas) >= {"failure_modes", "eval_vs_people", "person_anchored", "variance", "people", "gates",
                         "max_inflation", "correction", "trials"}
    assert {m["id"] for m in meas["failure_modes"]} == {"wrong-answer", "wrong-end-state", "unrequested-change",
                                                        "wrong-route"}
    assert all(m["type"] == "code" and m["floor"]["status"] == "pass" for m in meas["failure_modes"])
    assert meas["eval_vs_people"]["labels"] == {"fail": 0, "pass": 0}
    assert meas["variance"]["n_cases"] == sum(DRAW.values())


def test_v2_commands_accept_measurement(store):
    assert cli.V2_READY >= {"label", "calibrate", "agreement", "judge"}
