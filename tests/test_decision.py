"""2.0 decision rules (docs/v2-design.md §5, §6; estimators §6; statistics §4): report.json's
`decision` and `comparison`, and `compare` on a 2.0 eval.

The fixture is test_estimand's store (the end-to-end eval, cost weights, a non-inferiority rule
with a refund gate) on a toy agent with variants that make a known change:

- `good`: every quality case passes;
- `refund-bug`: a known third of refund cases fail (`refund_fails`);
- `address-bug`: every address case fails (address carries 1.6/4.3 of θ);
- `pricey`: as good, at fifty times the cost, over the spec's cost-per-success budget.

A candidate is the same commit with another variant in agent.yaml's `invoke.env`, declared as
`--variable prompt=...`. Every fixture asserts that exactly the gate it targets moves.
"""

from __future__ import annotations

import json
import sys

import pytest
import yaml
from conftest import git
from test_estimand import Store, make_store, refund_fails
from test_measurement import JUDGE_PY, _label_judge, _with_judge

from aot_evals import stats
from aot_evals.decision import looks_path

AGENT = '''import hashlib, json, os, sys
case = json.load(sys.stdin)
v = os.environ.get("AGENT_VARIANT", "good")
cid = case["case_id"]
bad = cid.startswith("bf-")
if v == "refund-bug" and cid.startswith("tr_refund") and int(hashlib.sha256(cid.encode()).hexdigest(), 16) % 3 == 0:
    bad = True
if v == "address-bug" and cid.startswith("tr_address"):
    bad = True
print(json.dumps({"answer": "wrong" if bad else "ok", "usage": {"cost": 0.05 if v == "pricey" else 0.001},
                  "model_ids": {"main": "toy-1"}}))
'''
DRAW = {"order-status": 8, "return": 4, "address": 10, "refund": 10}


@pytest.fixture
def store(tmp_path, monkeypatch) -> Store:
    s = make_store(tmp_path, monkeypatch)
    (s.root / "agent" / "store.py").write_text(AGENT)
    return s


def _spec(s: Store, eval_id: str = "end-to-end") -> dict:
    return yaml.safe_load((s.agent / eval_id / "eval.yaml").read_text())


def _write_spec(s: Store, data: dict, eval_id: str = "end-to-end") -> None:
    (s.agent / eval_id / "eval.yaml").write_text(yaml.safe_dump(data, sort_keys=False))


def _variant(s: Store, variant: str) -> None:
    a = yaml.safe_load((s.agent / "agent.yaml").read_text())
    a["invoke"]["env"]["AGENT_VARIANT"] = variant
    (s.agent / "agent.yaml").write_text(yaml.safe_dump(a))


def _setup(s: Store, variant: str, rule: dict | None = None, cluster_key: str = "id") -> str:
    """Draw, screen and commit the end-to-end eval under `rule`, then run the baseline."""
    data = _spec(s)
    data["design"]["cluster_key"] = cluster_key
    if rule is not None:
        data["decision_rule"].update(rule)
    _write_spec(s, data)
    assert s.cli("draw", *[a for uc, k in DRAW.items() for a in ("--n", f"{uc}={k}")]) == 0
    assert s.cli("screen", "--read-by", "tester", "--all") == 0
    _variant(s, variant)
    s.commit()
    assert s.cli("run", "--purpose", "baseline") == 0
    return s.ev().runs("baseline")[-1]["run_id"]


def _candidate(s: Store, variant: str, variable: str = "prompt=v2", eval_id: str = "end-to-end") -> str:
    _variant(s, variant)
    git(s.root, "add", "-A")
    git(s.root, "commit", "-q", "--allow-empty", "-m", f"candidate {variant}")
    assert s.cli("run", "--purpose", "candidate", "--variable", variable, eval_id=eval_id) == 0
    return [m for m in Evals_of(s).eval(eval_id).runs("candidate") if m.get("finished")][-1]["run_id"]


def Evals_of(s: Store):
    from aot_evals.repo import Evals

    return Evals(s.agent)


def _report(s: Store, *cands: str, eval_id: str = "end-to-end") -> dict:
    args = [a for c in cands for a in ("--candidate", c)]
    assert s.cli("report", *args, eval_id=eval_id) == 0
    return json.loads((s.agent / eval_id / "report" / "report.json").read_text())


def _results(d: dict) -> dict[str, str]:
    """Each gate's result, by name."""
    out = {"headline": d["headline"]["result"]}
    out.update({g["gate"]: g["result"] for g in d["gates"]})
    out.update({f"also_requires:{r['eval']}": r["result"] for r in d["also_requires"]})
    return out


# ---- stats ---------------------------------------------------------------------------------------

def test_weighted_sign_flip_tests_the_weighted_mean():
    d = [0.0] * 40 + [1 / 3] * 3 + [-1 / 3]
    # equal weights are the unweighted tests
    assert stats.non_inferiority_test(d, 0.05, case_weights=[2.0] * 44)["p"] == stats.non_inferiority_test(d, 0.05)["p"]
    assert stats.sign_flip_test(d, case_weights=[1.0] * 44) == stats.sign_flip_test(d)
    # design weights: the mean is sum(W_i d_i), and the interval is for it
    w = [2.0] * 22 + [1.0] * 22
    m = stats.weighted_mean_delta(d, w)
    assert m["mean"] == pytest.approx((3 - 1) / 3 / 66)
    ci = stats.sign_flip_interval(d, alpha=0.10, case_weights=w)
    assert ci[0] < m["mean"] < ci[1]
    # clusters: the standard error counts clusters, not cases
    keyed = stats.weighted_mean_delta(d, None, [str(i // 4) for i in range(44)])
    assert keyed["n_clusters"] == 11 and keyed["se"] > 0
    # superiority: H0 mean <= 0; four gains and nothing else can't reach 5% one-sided (1/16)
    four = stats.superiority_test([1.0] * 4 + [0.0] * 40)
    assert four["p"] == pytest.approx(1 / 16) and not four["passed"]
    ten = stats.superiority_test([1.0] * 10 + [0.0] * 40)
    assert ten["p"] == pytest.approx(1 / 1024) and ten["passed"] and ten["lower"] > 0


def test_bound_test_and_cases_for_spread():
    bt = stats.bound_test(0.01, 0.01, 0.05, "below", 0.05)
    assert bt["passed"] and bt["bound"] == pytest.approx(0.01 + 1.6449 * 0.01, abs=1e-4)
    shown = stats.bound_test(0.20, 0.02, 0.05, "below", 0.05)
    assert not shown["passed"] and shown["shown_wrong_side"]
    near = stats.bound_test(0.04, 0.02, 0.05, "below", 0.05)
    assert not near["passed"] and not near["shown_wrong_side"]
    assert stats.bound_test(0.95, 0.01, 0.90, "above")["passed"]
    # n cases at se 0.02 detect 0.04 when (z_a + z_b) se sqrt(n/N) = 0.04
    n = stats.cases_for_spread(100, 0.02, 0.04, 0.05, 0.80)
    assert n == pytest.approx(100 * ((1.6449 + 0.8416) * 0.02 / 0.04) ** 2, abs=1)
    assert stats.cases_for_spread(100, 0.0, 0.04) is None and stats.cases_for_spread(100, 0.02, -1) is None


def test_the_rate_bound_is_clopper_pearson_at_the_effective_size():
    """Equal weights: the exact binomial test (`threshold_test`), where the normal bound passed 0 of
    32, 3 of 150 and 5 of 200 against a 5% bar."""
    for k, n in ((0, 32), (0, 59), (3, 150), (5, 200), (1, 100)):
        r, e = stats.rate_bound_test(k / n, n, 0.05, "below"), stats.threshold_test(k, n, 0.05)
        assert r["p"] == pytest.approx(e["p"]) and r["bound"] == pytest.approx(e["bound"], abs=1e-9)
        assert r["passed"] == e["passed"] == ((k, n) in ((0, 59), (1, 100)))
    # the normal bound at θ̂'s floored se (stratified_hajek) passed 0 of 32
    floored = stats.stratified_hajek({"u": {"weight": 1, "values": [0.0] * 32, "inclusion_probs": [1.0] * 32}})
    assert stats.bound_test(0.0, floored["se"], 0.05, "below")["passed"] and floored["n_effective"] == 32
    # weights cost cases: Kish's n_eff counts, and the bar is then out of reach of 59
    assert stats.kish_n([1.0] * 59) == pytest.approx(59)
    assert stats.kish_n([2.0] * 30 + [1.0] * 29) < 59
    assert stats.cases_for_rate_bound(0.0, 0.05, "below") == 59
    # n_eff is continuous: 117 cases at design effect 2 are worth 58.5, and 0.95^58.5 < 0.05
    assert stats.cases_for_rate_bound(0.0, 0.05, "below", design_effect=2.0) == 117
    assert stats.cases_for_rate_bound(0.06, 0.05, "below") is None
    up = stats.rate_bound_test(0.95, 40, 0.80, "above")
    assert up["passed"] and up["interval"][0] > 0.80 and not up["shown_wrong_side"]


# ---- paired rules --------------------------------------------------------------------------------

def test_a_paired_rule_without_a_candidate_is_unknown(store):
    _setup(store, "refund-bug")
    d = _report(store)["decision"]
    assert d["result"] == "unknown" and d["subject"]["kind"] == "runs"
    assert "candidate" in d["headline"]["reason"] and d["test"] == "non_inferiority"


def test_an_unchanged_candidate_is_non_inferior(store):
    """NI at margin 2 points and the refund gate at 5: a candidate that changes nothing passes both."""
    _setup(store, "refund-bug")
    c = _candidate(store, "refund-bug")
    r = _report(store, c)
    d = r["decision"]
    assert _results(d) == {"headline": "pass", "use_case:refund": "pass"} and d["result"] == "pass"
    assert d["subject"]["kind"] == "candidate" and d["subject"]["declared_variable"] == "prompt=v2"
    head = d["headline"]
    assert head["estimate"] == 0 and head["boundary"] == pytest.approx(-0.02)
    assert head["n_cases"] == sum(DRAW.values()) and head["p"] < 0.05
    comp = r["comparison"]
    assert comp["paired"] and comp["verdict"] == "indistinguishable" and comp["refused"] is None
    assert comp["gains"] == comp["losses"] == [] and comp["net"] == 0
    assert "variance_band" not in comp


def test_a_regression_fails_non_inferiority(store):
    """address-bug on the candidate: Δθ̂ = −1.6/4.3, far past the 2-point margin."""
    _setup(store, "good")
    c = _candidate(store, "address-bug")
    r = _report(store, c)
    d = r["decision"]
    assert _results(d) == {"headline": "fail", "use_case:refund": "pass"} and d["result"] == "fail"
    assert d["headline"]["estimate"] == pytest.approx(-1.6 / 4.3)
    assert "worse than the margin" in d["headline"]["reason"]
    comp = r["comparison"]
    assert comp["verdict"] == "worse" and len(comp["losses"]) == DRAW["address"]
    assert comp["per_use_case"]["address"]["net"] == pytest.approx(-1.0)
    assert comp["per_use_case"]["address"]["p_adjusted"] is not None


def test_the_refund_gate_alone_blocks(store):
    """A refund regression the headline's wide margin tolerates, and the refund gate does not."""
    _setup(store, "good", rule={"margin": 0.20})
    c = _candidate(store, "refund-bug")
    d = _report(store, c)["decision"]
    refunds = [x["id"] for x in store.ev().cases() if x.get("use_case") == "refund" and x.get("draw")]
    lost = sum(refund_fails(x) for x in refunds) / len(refunds)
    assert lost > 0.05  # the fixture's bug is past the gate's margin
    # a few lost refunds don't show the drop past the margin at the 90% interval, and don't pass
    # it either: the gate holds the change back on its own
    assert _results(d) == {"headline": "pass", "use_case:refund": "insufficient"}
    assert d["result"] == "insufficient" and d["gates"][0]["cases_needed"] > d["gates"][0]["n_cases"]
    assert d["gates"][0]["estimate"] == pytest.approx(-lost)
    # the point estimate is already past the margin: the reason says so, not just "p > α"
    reason = d["gates"][0]["reason"]
    assert reason.startswith(f"the refund pass rate dropped {100 * lost:.3g} points, past the margin of 5")
    assert "too few cases to show it at α 0.05" in reason
    assert d["headline"]["estimate"] == pytest.approx(-lost / 4.3)


def test_superiority_and_clusters(store):
    """Fixing the address bug, ten address cases gain. Counted as ten clusters it is shown better;
    keyed by template (four clusters among them) no test can reach 5% (rule 9)."""
    _setup(store, "address-bug", rule={"test": "superiority", "margin": 0.02, "use_case_gates": []})
    c = _candidate(store, "good")
    r = _report(store, c)
    d = r["decision"]
    assert _results(d) == {"headline": "pass"} and d["result"] == "pass"
    assert d["headline"]["p"] == pytest.approx(1 / 2 ** DRAW["address"])
    assert r["comparison"]["verdict"] == "better" and len(r["comparison"]["gains"]) == DRAW["address"]


def test_clustered_gains_are_insufficient(store):
    _setup(store, "address-bug", rule={"test": "superiority", "margin": 0.02, "use_case_gates": []},
           cluster_key="template")
    c = _candidate(store, "good")
    d = _report(store, c)["decision"]
    head = d["headline"]
    assert _results(d) == {"headline": "insufficient"} and d["result"] == "insufficient"
    assert head["p"] == pytest.approx(1 / 16)  # four address templates
    assert head["n_clusters"] < head["n_cases"]


def test_combine_any_adjusts_with_holm(store):
    _setup(store, "address-bug", rule={"test": "superiority", "margin": 0.02, "combine": "any",
                                       "multiplicity": "holm", "use_case_gates": [
                                           {"use_case": "address", "test": "superiority", "margin": 0.05},
                                           {"use_case": "refund", "test": "superiority", "margin": 0.05}]})
    c = _candidate(store, "good")
    d = _report(store, c)["decision"]
    ps = [d["headline"]["p"]] + [g["p"] for g in d["gates"]]
    assert [d["headline"]["p_adjusted"]] + [g["p_adjusted"] for g in d["gates"]] == pytest.approx(stats.holm(ps))
    # one gate alone acts; refunds didn't move, so that gate is shown no better
    assert d["result"] == "pass" and _results(d)["use_case:refund"] == "fail"


def test_a_budget_breach_with_passing_gates_is_a_trade(store):
    _setup(store, "address-bug", rule={"test": "superiority", "margin": 0.02, "use_case_gates": []})
    c = _candidate(store, "pricey")
    r = _report(store, c)
    d = r["decision"]
    assert _results(d) == {"headline": "pass"} and d["result"] == "trade"
    assert d["constraints"]["status"] == "breached"
    assert {b["budget"] for b in d["constraints"]["breaches"]} == {"cost_per_success_usd"}
    assert all(b["new"] for b in d["constraints"]["breaches"])
    assert r["comparison"]["verdict"] == "trade"


# ---- threshold on the reported runs ----------------------------------------------------------------

def test_threshold_on_the_reported_runs(store):
    # θ̂ 0.93 on cost weights: Kish's n_eff is 27.7 of 32 cases, and the exact bound 0.79
    _setup(store, "refund-bug", rule={"test": "threshold", "bar": 0.75, "margin": None, "use_case_gates": []})
    d = _report(store)["decision"]
    assert _results(d) == {"headline": "pass"} and d["result"] == "pass"
    head = d["headline"]
    assert head["side"] == "above" and head["bound"] > 0.75 and head["detectable_effect"] > 0
    assert head["n_effective"] < head["n_cases"] and "Clopper-Pearson" in head["method"]
    data = _spec(store)
    data["decision_rule"]["bar"] = 0.85
    _write_spec(store, data)
    # the bar moved after the baseline ran: refused until journaled (problem 12)
    d = _report(store)["decision"]
    assert d["result"] == "unknown" and "rule 21" in d["null_reason"]
    assert store.cli("log", "--kind", "decision", "bar to 85%, decided before the next baseline") == 0
    _variant(store, "address-bug")  # a build that is clearly below it
    store.commit("address bug")
    assert store.cli("run", "--purpose", "baseline") == 0
    d = _report(store)["decision"]
    assert _results(d) == {"headline": "fail"} and d["result"] == "fail"
    assert d["headline"]["cases_needed"] is None and "wrong side" in d["headline"]["cases_needed_reason"]


def test_threshold_through_an_uncorrected_judge_reads_the_bar_on_its_scale(store):
    _with_judge(store, correction="none", max_inflation=1000)
    _label_judge(store, (54, 60), (380, 400))
    _setup(store, "refund-bug", rule=None)
    d = _report(store)["decision"]
    head = d["headline"]
    j = 54 / 60 + 380 / 400 - 1
    assert head["grader_scale"]["j"] == pytest.approx(j)
    assert head["boundary"] == pytest.approx((1 - 380 / 400) + j * 0.10)
    assert any("grader's scale" in n for n in head["notes"])


# ---- looks and rule changes ------------------------------------------------------------------------

def test_looks_fixed_allows_one_look(store):
    _setup(store, "refund-bug")
    c1 = _candidate(store, "refund-bug")
    assert _report(store, c1)["decision"]["result"] == "pass"
    assert len(looks_path(store.ev()).read_text().splitlines()) == 1
    assert _report(store, c1)["decision"]["look"]["recorded"]  # the same runs again: not a new look
    assert len(looks_path(store.ev()).read_text().splitlines()) == 1
    assert store.cli("run", "--purpose", "candidate", "--variable", "prompt=v2") == 0
    c2 = store.ev().runs("candidate")[-1]["run_id"]
    d = _report(store, c1, c2)["decision"]
    assert d["result"] == "unknown" and d["look"]["n"] == 2 and "one look per change" in d["null_reason"]
    assert _results(d) == {"headline": "pass", "use_case:refund": "pass"}  # the gates themselves held


def test_sequential_looks_are_never_a_pass(store):
    _setup(store, "refund-bug", rule={"looks": "sequential"})
    c = _candidate(store, "refund-bug")
    r = _report(store, c)
    assert r["decision"]["result"] == "unknown" and "always-valid" in r["decision"]["null_reason"]
    assert any(n["field"] == "decision_rule.looks" for n in r["spec"]["notes"])


def test_a_decision_rule_change_needs_a_journal_entry_first(store):
    _setup(store, "refund-bug")
    c = _candidate(store, "refund-bug")
    data = _spec(store)
    data["decision_rule"]["margin"] = 0.03
    _write_spec(store, data)
    r = _report(store, c)
    assert r["comparison"]["refused"] and "rule 21" in r["comparison"]["refused"]
    assert r["decision"]["result"] == "unknown" and r["estimate"]["theta"] is not None
    # journaled now, after the candidate ran: still refused
    assert store.cli("log", "--kind", "decision", "margin to 3 points") == 0
    entry = [json.loads(x) for x in (store.agent / "journal" / "activity.jsonl").read_text().splitlines()
             if '"decision"' in x][-1]
    assert entry["eval"] == "end-to-end" and entry["spec_sha"]["decision_rule"] == r["spec"]["sha"]["decision_rule"]
    assert _report(store, c)["comparison"]["refused"]
    # a candidate run after the entry compares against the old baseline
    c2 = _candidate(store, "refund-bug", variable="prompt=v3")
    r = _report(store, c2)
    assert r["comparison"]["refused"] is None and r["decision"]["result"] == "pass"


def _git_at(repo, when: str, *args: str) -> None:
    import subprocess

    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@example.com", "GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when,
           "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"}
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, env=env)


def _margin(s: Store, m: float) -> None:
    data = _spec(s)
    data["decision_rule"]["margin"] = m
    _write_spec(s, data)


def test_a_committed_rule_change_counts_when_it_precedes_the_candidate(store):
    """Evals in the agent's repository: a commit of eval.yaml is the record when it is an ancestor
    of the candidate's commit. No journal entry is made."""
    _setup(store, "refund-bug")
    c1 = _candidate(store, "refund-bug")
    _margin(store, 0.03)
    store.commit("margin to 3 points")
    # committed after c1 ran: not an ancestor of its commit
    r = _report(store, c1)
    assert r["comparison"]["refused"] and "committed in eval.yaml" in r["comparison"]["refused"]
    c2 = _candidate(store, "refund-bug", variable="prompt=v3")
    r = _report(store, c2)
    assert r["comparison"]["refused"] is None and r["decision"]["result"] == "pass"
    assert not (store.agent / "journal" / "activity.jsonl").exists() or '"decision"' not in (
        store.agent / "journal" / "activity.jsonl").read_text()
    # an uncommitted edit is no record: the committed rule is the one that counts
    _margin(store, 0.04)
    assert _report(store, c2)["comparison"]["refused"]


def test_a_committed_rule_change_outside_the_agents_repository_counts_by_date(store, tmp_path):
    """Evals in a repository of their own: the agent's commits can't order eval.yaml's, so the
    commit counts when it is dated no later than the first decided run."""
    other = tmp_path / "agent-repo"
    other.mkdir()
    (other / "store.py").write_text(AGENT)
    git(other, "init", "-q")
    git(other, "add", "-A")
    git(other, "commit", "-q", "-m", "agent")
    a = yaml.safe_load((store.agent / "agent.yaml").read_text())
    a["invoke"].update(command=[sys.executable, str(other / "store.py")], cwd=str(other))
    (store.agent / "agent.yaml").write_text(yaml.safe_dump(a))
    _setup(store, "refund-bug")
    assert store.cli("run", "--purpose", "candidate", "--variable", "prompt=v2") == 0
    c1 = store.ev().runs("candidate")[-1]["run_id"]
    assert store.ev().runs("candidate")[-1]["agent_commit"] != store.ev().runs("candidate")[-1]["evals_commit"]
    _margin(store, 0.03)
    git(store.root, "add", "-A")
    _git_at(store.root, "2099-01-01T00:00:00Z", "commit", "-q", "-m", "margin, dated after c1")
    assert "committed in eval.yaml" in _report(store, c1)["comparison"]["refused"]
    _margin(store, 0.04)
    git(store.root, "add", "-A")
    _git_at(store.root, "2026-01-01T00:00:00Z", "commit", "-q", "-m", "margin, dated before c2")
    assert store.cli("run", "--purpose", "candidate", "--variable", "prompt=v3") == 0
    c2 = store.ev().runs("candidate")[-1]["run_id"]
    r = _report(store, c2)
    assert r["comparison"]["refused"] is None and r["decision"]["result"] == "pass"


def test_comparison_refuses_another_measurement(store):
    _setup(store, "refund-bug")
    (store.eval / "checks" / "code" / "no-side-effects.py").write_text(
        "def check(start, end, case):\n    return True, ''\n# changed\n")
    c = _candidate(store, "refund-bug")
    r = _report(store, c)
    assert "measurement" in r["comparison"]["refused"] and r["decision"]["result"] == "unknown"


def test_compare_on_a_2_0_eval(store, capsys):
    _setup(store, "good")
    _candidate(store, "address-bug")
    assert store.cli("compare") == 0
    out = capsys.readouterr().out
    assert "VERDICT: worse" in out and "decision: fail" in out
    saved = list((store.eval / "report" / "comparisons").glob("*.json"))
    assert len(saved) == 1 and json.loads(saved[0].read_text())["decision"]["result"] == "fail"


# ---- the refunds eval: a component eval behind also_requires --------------------------------------

REFUNDS_AGENT = '''import json, sys
case = json.load(sys.stdin)
print(json.dumps({"answer": "ok", "usage": {"cost": 0.001}, "model_ids": {"main": "toy-refunds"}}))
'''
REFUND_FRAME = {"full-refund": 16, "partial-refund": 8, "gift-card": 8}


def _refunds(s: Store, tmp_path, *, judge: bool, frame: dict | None = None) -> None:
    """The store's refunds eval (examples/store), on a toy subagent. With `judge`, breaks-policy is
    graded by the policy judge, calibrated on 20 failure and 100 pass labels at catch 0.95 and
    clean 0.99: the floor refuses it (v2-design §9: it needs about 100 and 500). Without, the
    quantity is the code-checked wrong-amount rate."""
    from test_estimand import END_STATE, PASS, STORE

    d = s.agent / "refunds"
    (d / "checks" / "code").mkdir(parents=True)
    # a real check on the amount, so a do-nothing run fails screening (rule 17)
    (d / "checks" / "code" / "amount-matches.py").write_text(END_STATE)
    (d / "checks" / "code" / "no-side-effects.py").write_text(PASS)
    (s.root / "agent" / "refunds.py").write_text(REFUNDS_AGENT)
    data = yaml.safe_load((STORE / "refunds" / "eval.yaml").read_text())
    data["invoke"] = {"command": [sys.executable, "agent/refunds.py"], "cwd": ".", "timeout": 20}
    if judge:
        (s.root / "judge.py").write_text(JUDGE_PY)
        spec = {"id": "policy-judge", "version": 1, "question_type": "noul", "detects": "failure",
                "question": "The refund breaks the policy.", "inputs": ["end.output"], "primary": "local",
                "backends": {"local": {"type": "command", "command": [sys.executable, str(s.root / "judge.py")],
                                       "family": "toy", "model": "toy-judge"}}}
        (d / "checks" / "judge").mkdir(parents=True)
        (d / "checks" / "judge" / "policy-judge.md").write_text("---\n" + yaml.safe_dump(spec) + "---\nPass or fail.\n")
    else:
        data["estimand"]["quantity"] = data["decision_rule"]["quantity"] = "failure_rate:wrong-amount"
        data["measurement"]["failure_modes"] = [fm for fm in data["measurement"]["failure_modes"]
                                                if fm["id"] != "breaks-policy"]
        data["measurement"]["correction"] = "none"
        data["decision_rule"]["bar"] = 0.30
    if frame is not None:  # every case drawn, weights in proportion: equal design weights
        data["estimand"]["weights"] = {uc: n / sum(frame.values()) for uc, n in frame.items()}
        data["design"].pop("oversample", None)
        data["decision_rule"]["bar"] = 0.05
    frame = frame or REFUND_FRAME
    _write_spec(s, data, "refunds")
    rows = [{"id": f"tr_{uc}_{i:02d}", "use_case": uc, "order_template": f"{uc}-t{i}",
             "trigger": {"type": "handoff", "text": f"refund {uc} {i}"},
             "expected_end_state": {"world": None, "output": "ok"}}
            for uc, n in frame.items() for i in range(n)]
    (tmp_path / "handoffs.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    assert s.cli("import", str(tmp_path / "handoffs.jsonl"), "--id", "refund-handoffs-2026-10", "--source",
                 "fixture", "--query", "all", "--window", "2026-10-01..2026-10-31",
                 "--handoffs-of", "refund-subagent", eval_id="refunds") == 0
    assert s.cli("draw", *[a for uc, n in frame.items() for a in ("--n", f"{uc}={n}")],
                 eval_id="refunds") == 0
    assert s.cli("screen", "--read-by", "tester", "--all", eval_id="refunds") == 0
    if judge:
        rows_ = []
        for k in range(20):
            rows_.append({"item_id": f"lab-f{k}-{'wrong' if k < 19 else 'ok'}", "case_id": f"lab-f{k}",
                          "label": False, "labeller": "pat", "split": "dev",
                          "input": {"end.output": "wrong" if k < 19 else "ok"}})
        for k in range(100):
            rows_.append({"item_id": f"lab-p{k}-{'ok' if k < 99 else 'wrong'}", "case_id": f"lab-p{k}",
                          "label": True, "labeller": "pat", "split": "dev",
                          "input": {"end.output": "ok" if k < 99 else "wrong"}})
        (d / "checks" / "judge" / "policy-judge.labels.jsonl").write_text(
            "".join(json.dumps(r) + "\n" for r in rows_))
        assert s.cli("calibrate", "--judge", "policy-judge", eval_id="refunds") == 0
    s.commit("refunds eval")
    assert s.cli("run", "--purpose", "baseline", eval_id="refunds") == 0


def test_the_store_refunds_judge_is_refused_and_the_decision_unknown(store, tmp_path):
    """v2-design §9: at 20 and 100 labels the policy judge's lower bounds cost more than
    max_inflation 2.0, so θ̂ is null and the decision unknown (rule 13), never a pass."""
    _refunds(store, tmp_path, judge=True)
    r = _report(store, eval_id="refunds")
    fm = next(m for m in r["measurement"]["failure_modes"] if m["id"] == "breaks-policy")
    assert fm["floor"]["status"] == "refused" and fm["labels"] == {"fail": 20, "pass": 100}
    assert r["estimate"]["theta"] is None and "rule 13" in r["estimate"]["null_reason"]
    d = r["decision"]
    assert d["result"] == "unknown" and d["headline"]["result"] == "unknown"
    assert "rule 13" in d["headline"]["reason"] and d["test"] == "threshold"


def test_also_requires_reads_the_end_to_end_eval_for_the_same_change(store, tmp_path):
    _setup(store, "refund-bug")
    _refunds(store, tmp_path, judge=False)
    assert store.cli("run", "--purpose", "candidate", "--variable", "prompt=refunds-v2", eval_id="refunds") == 0
    rc = Evals_of(store).eval("refunds").runs("candidate")[-1]["run_id"]
    # no end-to-end candidate of this change yet: unknown, with the command that makes one
    d = _report(store, rc, eval_id="refunds")["decision"]
    assert _results(d) == {"headline": "pass", "also_requires:end-to-end": "unknown"}
    assert d["result"] == "unknown" and "--eval end-to-end run --purpose candidate" in d["also_requires"][0]["reason"]
    assert store.cli("run", "--purpose", "candidate", "--variable", "prompt=refunds-v2") == 0
    d = _report(store, rc, eval_id="refunds")["decision"]
    assert _results(d) == {"headline": "pass", "also_requires:end-to-end": "pass"} and d["result"] == "pass"
    assert d["also_requires"][0]["gate"]["test"] == "non_inferiority"


@pytest.mark.parametrize(("frame", "result"), [
    ({"full-refund": 16, "partial-refund": 8, "gift-card": 8}, "insufficient"),
    ({"full-refund": 30, "partial-refund": 15, "gift-card": 14}, "pass"),
])
def test_zero_failures_against_a_5_percent_bar_needs_59_cases(store, tmp_path, frame, result):
    """The zero-failure rule (statistics §4.1): no wrong amount in 32 cases leaves the bound at
    8.9%, above a 5% bar; in 59 it is 4.95%. The normal bound passed both."""
    _refunds(store, tmp_path, judge=False, frame=frame)
    d = _report(store, eval_id="refunds")["decision"]
    head = d["headline"]
    n = sum(frame.values())
    assert head["estimate"] == 0 and head["n_effective"] == pytest.approx(n)
    assert head["result"] == result and "Clopper-Pearson" in head["method"]
    assert head["bound"] == pytest.approx(1 - 0.05 ** (1 / n))
    if result == "insufficient":
        assert head["cases_needed"] == 59 and not head["reason"].startswith("θ̂")
