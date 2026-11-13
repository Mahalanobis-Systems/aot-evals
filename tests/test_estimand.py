"""2.0 estimand and design (docs/v2-design.md §3, §5, §6): `draw`, `plan`, the case fields, the v2
run manifest and report.json v2's `eval`, `spec`, `estimate`, `use_cases` and `design`.

The fixture is the store's end-to-end eval (examples/store) on a small agent that answers "ok",
with a frame of 70 traces. AGENT_VARIANT=refund-bug fails a known third of refund cases, so θ̂
can be checked by hand: refunds carry 1/4.3 of θ under cost weights (estimators §3).
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path

import pytest
import yaml
from conftest import git

from aot_evals import cli, stats
from aot_evals.design import case_status
from aot_evals.repo import Evals

STORE = Path(__file__).parents[1] / "examples" / "store" / "evals" / "agents" / "store"
FRAME = {"order-status": 40, "return": 20, "address": 10, "refund": 10}
DRAW = {"order-status": 8, "return": 4, "address": 4, "refund": 6}

AGENT = '''import hashlib, json, os, sys
case = json.load(sys.stdin)
bad = (os.environ.get("AGENT_VARIANT") == "refund-bug" and case["case_id"].startswith("tr_refund")
       and int(hashlib.sha256(case["case_id"].encode()).hexdigest(), 16) % 3 == 0)
if case["case_id"].startswith("bf-"):
    bad = True
print(json.dumps({"answer": "wrong" if bad else "ok", "usage": {"cost": 0.001},
                  "model_ids": {"main": "toy-1"}}))
'''
END_STATE = '''def check(start, end, case):
    want = (case.get("expected_end_state") or {}).get("output")
    return end.get("output") == want, f"output {end.get('output')!r}, wanted {want!r}"
'''
PASS = "def check(start, end, case):\n    return True, ''\n"


def refund_fails(case_id: str) -> bool:
    return case_id.startswith("tr_refund") and int(hashlib.sha256(case_id.encode()).hexdigest(), 16) % 3 == 0


class Store:
    def __init__(self, root: Path):
        self.root = root
        self.agent = root / "evals" / "agents" / "store"
        self.eval = self.agent / "end-to-end"

    def cli(self, *args: str, eval_id: str = "end-to-end") -> int:
        return cli.main(["--evals", str(self.agent), "--eval", eval_id, *args])

    def commit(self, msg: str = "evals") -> None:
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", msg)

    def report(self) -> dict:
        return json.loads((self.eval / "report" / "report.json").read_text())

    def ev(self):
        return Evals(self.agent).eval("end-to-end")

    def case(self, use_case: str, cid: str) -> dict:
        return json.loads((self.eval / "cases" / use_case / f"{cid}.json").read_text())

    def write_case(self, use_case: str, case: dict) -> None:
        d = self.eval / "cases" / use_case
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{case['id']}.json").write_text(json.dumps(case, indent=2))


@pytest.fixture
def store(tmp_path, monkeypatch) -> Store:
    return make_store(tmp_path, monkeypatch)


def make_store(tmp_path, monkeypatch) -> Store:
    """The store's end-to-end eval in a fresh repository, its frame imported (shared with
    test_measurement)."""
    root = tmp_path / "repo"
    (root / "agent").mkdir(parents=True)
    (root / "agent" / "store.py").write_text(AGENT)
    s = Store(root)
    s.eval.mkdir(parents=True)
    shutil.copyfile(STORE / "end-to-end" / "eval.yaml", s.eval / "eval.yaml")
    (s.agent / "agent.yaml").write_text(yaml.safe_dump({
        "id": "store", "invoke": {"command": [sys.executable, "agent/store.py"], "cwd": ".", "timeout": 20,
                                  "env": {"AGENT_VARIANT": "refund-bug"}}}))
    (s.agent / "env").mkdir()
    (s.agent / "env" / "orders.json").write_text("{}")
    code = s.eval / "checks" / "code"
    code.mkdir(parents=True)
    for cid in ("reply-matches-order", "no-side-effects", "routed-correctly"):
        (code / f"{cid}.py").write_text(PASS)
    (code / "end-state-matches.py").write_text(END_STATE)
    rows = [{"id": f"tr_{uc}_{i:02d}", "use_case": uc, "template": f"{uc}-t{i % 4}",
             "trigger": {"type": "message", "text": f"{uc} request {i}"},
             "expected_end_state": {"world": None, "output": "ok"}, "latency": 100 + i}
            for uc, n in FRAME.items() for i in range(n)]
    rows.append({"id": "tr_misc_00", "trigger": {"type": "message", "text": "?"}})  # no use case
    (tmp_path / "frame.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    shutil.copyfile(Path(cli.__file__).parent / "templates" / "evals" / "gitignore", s.agent / ".gitignore")
    git(root, "init", "-q")
    monkeypatch.chdir(root)
    assert s.cli("import", str(tmp_path / "frame.jsonl"), "--id", "support-requests-2026-10",
                 "--source", "fixture", "--query", "all", "--window", "2026-10-01..2026-10-31") == 0
    return s


def _draw(s: Store, **n) -> int:
    return s.cli("draw", *[a for uc, k in (n or DRAW).items() for a in ("--n", f"{uc}={k}")])


# ---- draw ------------------------------------------------------------------------------------

def test_draw_is_seeded_stratified_and_records_pi(store):
    assert _draw(store) == 0
    ev = store.ev()
    quality = [c for c in ev.cases() if c.get("pool") == "quality"]
    by_uc = {uc: [c for c in quality if c["use_case"] == uc] for uc in FRAME}
    assert {uc: len(v) for uc, v in by_uc.items()} == DRAW
    for uc, cs in by_uc.items():
        for c in cs:
            assert c["draw"]["inclusion_prob"] == DRAW[uc] / FRAME[uc]  # π = n / N, oversampling included
            assert c["draw"]["frame"] == "support-requests-2026-10" and c["draw"]["seed"] == 2026
            assert c["cluster"] == c["template"] and c["_path"].startswith(f"cases/{uc}/")
            assert c["provenance"]["trace_ref"] == c["id"] and "latency" not in c
    log = json.loads((store.eval / "draw.json").read_text())
    assert log["strata"]["refund"] == {"frame_size": 10, "n": 6, "inclusion_prob": 0.6, "replaced": []}
    assert log["frame_rows"]["unassigned"] == 1
    # the same seed draws the same traces, in any repository
    order = stats.draw_order([f"tr_refund_{i:02d}" for i in range(10)], 2026, "refund")
    assert sorted(c["id"] for c in by_uc["refund"]) == sorted(order[:6])


def test_drawing_more_extends_the_same_draw(store):
    assert _draw(store) == 0
    first = {c["id"] for c in store.ev().cases() if c.get("use_case") == "refund"}
    assert _draw(store, refund=8) == 0
    after = {c["id"]: c for c in store.ev().cases() if c.get("use_case") == "refund"}
    assert first < set(after) and len(after) == 8  # an expansion keeps every case it had
    assert all(c["draw"]["inclusion_prob"] == 0.8 for c in after.values())


def test_a_skip_is_logged_and_replaced_from_the_seeded_order(store):
    assert _draw(store) == 0
    order = stats.draw_order([f"tr_refund_{i:02d}" for i in range(10)], 2026, "refund")
    gone = order[2]
    assert store.cli("draw", "--skip", gone, "--n", "refund=6") == 2  # needs a reason
    assert store.cli("draw", "--skip", gone, "--reason", "PII", "--n", "refund=6") == 1  # would remove a case
    assert store.cli("draw", "--skip", gone, "--reason", "PII", "--n", "refund=6", "--prune") == 0
    ids = sorted(c["id"] for c in store.ev().cases() if c.get("use_case") == "refund")
    assert ids == sorted([x for x in order if x != gone][:6])  # the next in order, not a hand pick
    log = json.loads((store.eval / "draw.json").read_text())
    assert log["skips"][0]["trace_id"] == gone and log["skips"][0]["reason"] == "PII"
    assert log["strata"]["refund"]["frame_size"] == 9 and log["strata"]["refund"]["replaced"] == [gone]
    assert all(c["draw"]["inclusion_prob"] == 6 / 9 for c in store.ev().cases() if c.get("use_case") == "refund")


def test_draw_refuses_to_drop_cases_without_prune(store):
    assert _draw(store) == 0
    assert _draw(store, refund=4) == 1  # shrinking would remove two drawn cases
    assert len([c for c in store.ev().cases() if c.get("use_case") == "refund"]) == 6
    assert _draw(store, refund=4) == 1 and store.cli("draw", "--n", "refund=4", "--prune") == 0
    assert len([c for c in store.ev().cases() if c.get("use_case") == "refund"]) == 4


def test_draw_leaves_hand_written_cases_alone(store):
    store.write_case("refund", {"id": "q-hand", "use_case": "refund", "pool": "quality"})
    store.write_case("refund", {"id": "bf-1", "use_case": "refund", "pool": "bug_finding"})
    assert _draw(store) == 0 and _draw(store, refund=3) == 1  # shrinking still needs --prune
    assert store.cli("draw", "--n", "refund=3", "--prune") == 0
    ids = {c["id"] for c in store.ev().cases() if c.get("use_case") == "refund"}
    assert {"q-hand", "bf-1"} <= ids and len(ids) == 5  # refused from θ̂, never deleted by draw


def test_draw_refuses_an_incomplete_design(store):
    spec = yaml.safe_load((store.eval / "eval.yaml").read_text())
    del spec["design"]["quality_set"]["seed"]
    (store.eval / "eval.yaml").write_text(yaml.safe_dump(spec, sort_keys=False))
    assert _draw(store) == 2


# ---- case fields (v2-design §3) ------------------------------------------------------------------

def test_case_fields_decide_what_may_count(store):
    assert _draw(store) == 0
    ev = store.ev()
    drawn = next(c for c in ev.cases() if c.get("use_case") == "refund")
    assert case_status(ev, drawn)["counts"]
    hand = {"id": "q-hand", "use_case": "refund", "pool": "quality", "trigger": {"text": "x"}}
    old = {"id": "old", "category": "refund", "set": "quality_estimate"}
    reseeded = {**{k: v for k, v in drawn.items() if not k.startswith("_")}, "id": "reseeded",
                "draw": {**drawn["draw"], "seed": 1}}
    bf = {"id": "bf-x", "use_case": "refund", "pool": "bug_finding", "draw": drawn["draw"]}
    for c in (hand, old, reseeded, bf):
        store.write_case("refund", c)
    st = {c["id"]: case_status(ev, c) for c in ev.cases()}
    assert not st["q-hand"]["counts"] and "never by hand" in st["q-hand"]["problems"][0]
    assert any("`category` is a 1.x field" in p for p in st["old"]["problems"])
    assert any("seed 1" in p for p in st["reseeded"]["problems"])
    assert st["bf-x"]["problems"] == [] and not st["bf-x"]["counts"] and st["bf-x"]["notes"]
    assert st["bf-x"]["cluster"] == "bf-x"  # no cluster key value: its own cluster
    assert store.cli("validate") == 1


# ---- run and report ------------------------------------------------------------------------------

def _baseline(store: Store) -> dict:
    assert _draw(store) == 0
    store.write_case("refund", {"id": "bf-1", "use_case": "refund", "pool": "bug_finding", "template": "refund-t0",
                                "trigger": {"type": "message", "text": "refund outside the window"},
                                "expected_end_state": {"world": None, "output": "ok"}})
    store.write_case("refund", {"id": "q-hand", "use_case": "refund", "pool": "quality",
                                "trigger": {"type": "message", "text": "x"},
                                "expected_end_state": {"world": None, "output": "ok"}})
    assert store.cli("screen", "--read-by", "tester", "--all") == 0
    store.commit()
    assert store.cli("run", "--purpose", "baseline") == 0
    return store.ev().runs("baseline")[-1]


def test_run_writes_a_v2_manifest_and_v2_attempt_lines(store):
    m = _baseline(store)
    assert m["schema"] == "aot-evals/run-manifest@2" and m["k"] == 3  # k from measurement.trials
    assert m["eval"] == {"id": "end-to-end", "version": "1.0"}
    assert set(m["spec_sha"]) == {"estimand", "design", "measurement", "decision_rule"}
    assert all(m["spec_sha"].values()) and "simulator" not in m and "unmet_gates" not in m
    pis = m["case_set"]["inclusion_prob"]
    assert pis["q-hand"] is None and "bf-1" not in pis
    assert {v for k, v in pis.items() if k.startswith("tr_refund")} == {0.6}
    assert m["fakes_sha256"]  # the shared env/, hashed into every run
    attempts = [r for r in store.ev().run_records(m["run_id"]) if r["kind"] == "attempt"]
    assert attempts and all("use_case" in a and "pool" in a and "category" not in a and "set" not in a
                            for a in attempts)
    checks = [r for r in store.ev().run_records(m["run_id"]) if r["kind"] == "check"]
    assert checks and all(c["counted"] for c in checks)


def test_report_v2_estimate_is_the_weighted_hajek_mean(store):
    _baseline(store)
    assert store.cli("report") == 0
    r = store.report()
    assert r["schema"] == "aot-evals/report@2" and r["refused"] is None
    assert r["eval"]["quantity"] == "pass_rate" and r["eval"]["unit"] == {"kind": "system"}
    assert r["spec"]["complete"] and set(r["spec"]["sha"]) == {"estimand", "design", "measurement", "decision_rule"}
    est = r["estimate"]
    w = est["weights"]
    assert w["refund"] == pytest.approx(1 / 4.3) and w["address"] == pytest.approx(1.6 / 4.3)
    assert est["weights_source"] == "cost" and est["estimator"] == "hajek" and est["corrected"] is False
    refunds = [c["id"] for c in store.ev().cases() if c.get("use_case") == "refund" and c.get("draw")]
    mu_refund = 1 - sum(refund_fails(c) for c in refunds) / len(refunds)
    assert mu_refund < 1  # the fixture's bug shows
    assert est["theta"] == pytest.approx(1 - w["refund"] * (1 - mu_refund))  # bf-1 and q-hand left out
    assert est["n_cases"] == sum(DRAW.values()) and est["k"] == 3
    assert est["n_clusters"] == len({c["cluster"] for c in store.ev().cases() if c.get("draw")})
    assert est["ci"][0] < est["theta"] <= est["ci"][1] <= 1
    rows = {(x["id"], x["pool"]): x for x in r["use_cases"]}
    assert set(rows) == {(uc, p) for uc in FRAME for p in ("quality", "bug_finding")}
    q = rows[("refund", "quality")]
    assert q["weight"] == pytest.approx(1 / 4.3) and q["share"] == 0.02 and q["cost"] == 50
    assert q["inclusion_prob_range"] == [0.6, 0.6] and q["estimate"]["point"] == pytest.approx(mu_refund)
    assert q["excluded"]["n_cases"] == 1  # q-hand: quality without a draw
    bf = rows[("refund", "bug_finding")]
    assert bf["n_cases"] == 1 and bf["pass_rate"]["point"] == 0.0 and bf["weight"] is None
    d = r["design"]
    assert d["quality"]["n"] == sum(DRAW.values()) + 1 and d["quality"]["drawn"] == sum(DRAW.values())
    assert d["quality"]["refused"][0]["id"] == "q-hand" and d["quality"]["seed"] == 2026
    assert d["bug_finding"] == {"n": 1, "coverage": "coverage.yaml"}
    assert d["clusters"]["shared_with_bug_finding"] == (["refund-t0"] if any(
        c.get("template") == "refund-t0" for c in store.ev().cases() if c.get("draw")) else [])
    assert d["clusters"]["design_effect"] is not None and d["clusters"]["cluster_key"] == "template"


def test_report_refuses_runs_made_under_another_measurement(store):
    _baseline(store)
    (store.eval / "checks" / "code" / "no-side-effects.py").write_text(PASS + "# changed\n")
    assert store.cli("report") == 0
    r = store.report()
    assert "measurement" in r["refused"] and r["estimate"]["theta"] is None
    assert r["estimate"]["null_reason"] == r["refused"] and r["use_cases"] is None


def test_a_decision_rule_change_leaves_the_estimate(store):
    _baseline(store)
    spec = yaml.safe_load((store.eval / "eval.yaml").read_text())
    spec["decision_rule"]["margin"] = 0.03
    (store.eval / "eval.yaml").write_text(yaml.safe_dump(spec, sort_keys=False))
    assert store.cli("report") == 0
    r = store.report()
    assert r["refused"] is None and r["estimate"]["theta"] is not None


def test_estimate_is_null_with_its_reason(store):
    assert store.cli("report") == 0
    assert store.report()["estimate"]["null_reason"].startswith("no run yet")
    spec = yaml.safe_load((store.eval / "eval.yaml").read_text())
    spec["estimand"]["use_cases"][3]["cost"] = None
    (store.eval / "eval.yaml").write_text(yaml.safe_dump(spec, sort_keys=False))
    assert store.cli("report") == 0
    est = store.report()["estimate"]
    assert est["theta"] is None and "estimand.use_cases[refund].cost" in est["null_reason"]


# ---- plan --------------------------------------------------------------------------------------

def test_plan_sizes_from_the_decision_rule_and_allocates(store):
    assert store.cli("plan", "--write") == 0
    p = yaml.safe_load((store.eval / "plan.yaml").read_text())
    assert p["headline"]["need"] is None and "--flip-rate" in p["headline"]["reason"]
    assert all(r["target"] is None for r in p["rows"])

    assert store.cli("plan", "--flip-rate", "0.05", "--write") == 0
    p = yaml.safe_load((store.eval / "plan.yaml").read_text())
    need = stats.paired_n(0.05, 0.02, 0.05, 0.80)
    assert p["headline"]["need"] == need and p["headline"]["inflation"] == 1.0  # code checks only
    gate = stats.paired_n(0.05, 0.05, 0.05, 0.80)
    assert p["gates"] == [{**p["gates"][0], "use_case": "refund", "need": gate}]
    q = {r["use_case"]: r for r in p["rows"] if r["pool"] == "quality"}
    total = p["quality_set"]["total"]
    assert sum(r["target"] for r in q.values()) == total >= need
    assert q["refund"]["target"] >= gate and "gate" in q["refund"]["minimum_from"]
    assert q["address"]["target"] >= 2 * 0.08 * total  # oversample: 2 x its share
    # proportional to the weights until a baseline measures spreads and costs
    assert p["quality_set"]["spread"] == "assumed_equal"
    # the allocation's unequal weighting is paid for in N
    alloc = {uc: r["target"] for uc, r in q.items()}
    assert total >= need * stats.allocation_design_effect(p["quality_set"]["weights"], alloc) - 1
    assert all(r["target"] is None and r["rule"] for r in p["rows"] if r["pool"] == "bug_finding")


def test_plan_keeps_status_marks_and_takes_a_total(store):
    assert store.cli("plan", "--total", "40", "--write", "--mark-short", "scheduled", "--reason", "next week") == 0
    p = yaml.safe_load((store.eval / "plan.yaml").read_text())
    assert p["quality_set"]["total"] == 40 and sum(r["target"] for r in p["rows"] if r["pool"] == "quality") == 40
    assert store.cli("plan", "--total", "40", "--write") == 0
    p = yaml.safe_load((store.eval / "plan.yaml").read_text())
    assert all(r["status"] == "scheduled" and r["reason"] == "next week" for r in p["rows"])
    assert store.cli("draw") == 0  # draws plan.yaml's targets
    n = {r["use_case"]: r["target"] for r in p["rows"] if r["pool"] == "quality"}
    got = {uc: len([c for c in store.ev().cases() if c.get("use_case") == uc]) for uc in FRAME}
    assert got == {uc: min(n[uc], FRAME[uc]) for uc in FRAME}


def test_plan_for_a_threshold_test_counts_the_judge(store, tmp_path):
    """The refund eval: policy errors under 5%, planned against a true rate of 1%. Its policy judge
    has no calibration, so it is planned at max_inflation (2.0): twice the code check's 123."""
    ref = store.agent / "refunds"
    ref.mkdir()
    shutil.copyfile(STORE / "refunds" / "eval.yaml", ref / "eval.yaml")
    (ref / "checks" / "code").mkdir(parents=True)
    (ref / "checks" / "judge").mkdir(parents=True)
    for cid in ("amount-matches", "no-side-effects"):
        (ref / "checks" / "code" / f"{cid}.py").write_text(PASS)
    (ref / "checks" / "judge" / "policy-judge.md").write_text("---\nid: policy-judge\n---\nIs it policy?\n")
    assert store.cli("plan", "--assumed-rate", "0.01", "--json", eval_id="refunds") == 0
    p = __import__("aot_evals.plan", fromlist=["plan"]).plan(Evals(store.agent).eval("refunds"),
                                                              assumed_rate=0.01)
    h = p["headline"]
    assert h["n_code"] == stats.threshold_n(0.05, 0.01) == 123
    assert h["judges"][0]["check"] == "policy-judge" and h["inflation"] == 2.0 and h["need"] == 246
    assert not p["blocked"]  # its frame is not imported, which blocks draw and estimate, not plan
