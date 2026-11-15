"""The bench of graders (bench.py, agreement.py) and the grader application (serve.py), on one
eval: the store's end-to-end eval (examples/store).

Acceptance: several people label the same run blind; where they differ the run has no verdict
until someone rules, and the eval can't be held to people meanwhile; a new labeller warms up on
settled runs first; one queued run in four is an overlap; a rule proposed from rulings joins the
agent system's shared standard when the owner accepts it; the application serves one eval and
refuses requests without its session token.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request

import pytest
from conftest import StoreRepo

from aot_evals import agreement, bench, cli


def _baseline(s: StoreRepo, use_case: str = "address"):
    """A baseline of one use case (10 cases, k = 3): enough runs to label, quickly."""
    assert s.cli("run", "--purpose", "baseline", "--use-case", use_case) == 0
    ev = s.ev()
    return ev, ev.latest_run("baseline")["run_id"]


def _items(ev, run_id):
    return [{"item_id": agreement.item_key(run_id, a["case_id"], a["trial"], a["attempt"]),
             "case_id": a["case_id"], "run": run_id, "trial": a["trial"], "attempt": a["attempt"]}
            for a in agreement.finals(ev, [run_id])]


def test_labellers_who_disagree_leave_a_run_without_a_verdict_until_a_ruling(store_repo):
    ev, run_id = _baseline(store_repo)
    it = _items(ev, run_id)[0]
    bench.record_label(ev, it, "pass", "ana")
    assert [r["item_id"] for r in agreement.load_labels(ev)] == [it["item_id"]]
    bench.record_label(ev, it, "fail", "bo", "the address is wrong")
    assert agreement.load_labels(ev) == []  # disputed: counts toward nothing
    d = agreement.disputes(ev)
    assert len(d) == 1 and {x["labeller"] for x in d[0]["labels"]} == {"ana", "bo"}
    assert any("labellers disagree" in p for p in agreement.gate_problems(ev, None))
    pair = agreement.labeller_agreement(ev)[0]
    assert pair["labellers"] == ["ana", "bo"] and pair["n"] == 1 and pair["agree"] == 0

    agreement.add_ruling(ev, it["item_id"], False, "priya", "the address must match exactly")
    assert agreement.disputes(ev) == []
    (v,) = agreement.load_labels(ev)
    assert v["label"] is False and v["ruled"] and v["labellers"] == ["ana", "bo"]
    assert not any("labellers disagree" in p for p in agreement.gate_problems(ev, None))
    # the same person labelling again replaces their own label, not someone else's
    bench.record_label(ev, it, "fail", "ana")
    assert {k: r["label"] for k, r in agreement.per_labeller(ev)[it["item_id"]].items()} == {"ana": False, "bo": False}
    # the labels are the eval's own, not the agent system's
    assert ev.p("labels", "runs.jsonl").exists() and not store_repo.agent.joinpath("labels", "runs.jsonl").exists()


def test_a_new_labeller_warms_up_on_settled_runs_then_gets_overlaps(store_repo):
    ev, run_id = _baseline(store_repo)
    items = _items(ev, run_id)
    for it in items[:2]:  # two settled by agreement
        bench.record_label(ev, it, "pass", "ana")
        bench.record_label(ev, it, "pass", "bo")
    for it in items[2:10]:  # eight labelled by one person
        bench.record_label(ev, it, "pass", "ana")
    q = bench.queue(ev, "cy", n=12)
    assert [x["mode"] for x in q[:2]] == ["warm-up", "warm-up"]
    rest = [x["mode"] for x in q[2:]]
    assert rest[3] == "overlap" and rest.count("overlap") >= 2 and "new" in rest
    assert len({x["item_id"] for x in q}) == len(q)
    assert {x["use_case"] for x in q} == {"address"}
    # the settled answer is shown only after the label is in
    out = bench.record_label(ev, q[0], "fail", "cy")
    assert out["settled"]["label"] is True and "agreed" in out["settled"]["why"]
    # nobody is queued a run they labelled
    assert not {x["item_id"] for x in bench.queue(ev, "ana", n=50)} & {i["item_id"] for i in items[:10]}


def test_a_rule_proposed_from_rulings_joins_the_shared_standard_when_the_owner_accepts(store_repo):
    ev, run_id = _baseline(store_repo)
    for it in _items(ev, run_id)[:3]:
        bench.record_label(ev, it, "pass", "ana")
    std = store_repo.agent / "labels" / "standard.md"  # the agent system's, shared by its evals
    assert ev.standard_path == std
    before = std.read_text()
    p = bench.propose_rule(ev, "An address change names the new address in the reply.", ["address"], "bo")
    assert p["status"] == "proposed" and p["use_cases"] == ["address"] and std.read_text() == before
    assert ev.p("labels", "proposals.yaml").exists()
    bench.decide_rule(ev, p["id"], True, "priya")
    text = std.read_text()
    assert "An address change names the new address in the reply." in text and "accepted by priya" in text
    assert "# What makes a run of the store's support agent pass" in text  # comments kept
    assert text.endswith(before.split("---", 2)[2])  # the body is untouched
    from aot_evals.requirements import load_standard, rules_for

    rules = load_standard(ev)["rules"]
    assert rules[-1]["id"] == p["id"] and rules[-1]["use_cases"] == ["address"]
    assert p["id"] in {r["id"] for r in rules_for(rules, "address")}
    assert p["id"] not in {r["id"] for r in rules_for(rules, "refund")}
    assert len(bench.recheck(ev, p["id"])) == 3  # every labelled run is an address run
    # a rule for another use case flips none of them
    q = bench.propose_rule(ev, "A refund names its amount.", ["refund"], "bo")
    bench.decide_rule(ev, q["id"], True, "priya")
    assert bench.recheck(ev, q["id"]) == []


def test_a_drafted_case_waits_in_the_engineering_inbox(store_repo):
    ev, _ = _baseline(store_repo)
    d = bench.draft_case(ev, "tr_1204", "Please send order A1409 to 9 Oak Road.", "sam")
    assert ev.p("labels", "drafts", f"{d['id']}.json").exists()
    assert d["use_case"] == "address" and d["pool"] == "bug_finding"  # written, not drawn
    assert not ev.p("cases", "address", f"{d['id']}.json").exists()  # not graded until finished
    assert any(x["kind"] == "draft" and x["item"] == d["id"] for x in bench.inbox(ev))
    with pytest.raises(ValueError, match="secret"):
        bench.draft_case(ev, "tr_1204", "token sk-ant-api03-" + "a" * 40, "sam")


def test_label_only_the_cases_a_change_moved(store_repo, capsys):
    s = store_repo
    ev, _ = _baseline(s)
    s.set_env(AGENT_BREAK="tr_1208,tr_1210")
    s.commit("candidate")
    assert s.cli("run", "--purpose", "candidate", "--use-case", "address", "--variable", "prompt=break") == 0
    s.cli("compare")
    assert set(bench.changed_cases(ev)) == {"tr_1208", "tr_1210"}
    capsys.readouterr()
    assert s.cli("agreement", "label", "queue", "--changed") == 0
    q = json.loads(ev.p("data", "agreement", "queue.json").read_text())
    assert {i["case_id"] for i in q["items"]} == {"tr_1208", "tr_1210"}
    assert all("candidate" in i["run"] for i in q["items"])
    assert {x["case_id"] for x in bench.queue(ev, "ana", mode="changed")} == {"tr_1208", "tr_1210"}


def _server(ev, token):
    from http.server import ThreadingHTTPServer

    from aot_evals import serve

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), serve.make_handler(ev, token))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"

    def call(path, body=None, tok=token):
        req = urllib.request.Request(base + path, data=None if body is None else json.dumps(body).encode(),
                                     headers={"X-AOT-Token": tok, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, r.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode()

    return httpd, call


def test_the_application_serves_one_eval_needs_its_token_and_writes_the_eval(store_repo):
    from aot_evals import journal

    ev, run_id = _baseline(store_repo)
    token = "t0ken"
    httpd, call = _server(ev, token)
    try:
        assert call("/")[0] == 403  # the page itself needs ?t=
        code, html = call(f"/?t={token}")
        assert code == 200 and "Grade store · end-to-end" in html and token in html
        assert call("/api/state", tok="nope")[0] == 403
        assert call("/api/act/label", {"item": {}}, tok="nope")[0] == 403
        code, body = call("/api/state")
        st = json.loads(body)
        assert code == 200 and st["eval"] == "end-to-end" and st["evals"] == ["end-to-end", "refund-subagent"]
        assert st["spec"] == {"complete": True, "missing": [], "invalid": []}
        assert st["baseline"] == [run_id] and st["candidate"] is None
        assert st["decision"]["owner"] == "support platform team"
        ucs = {r["id"]: r for r in st["use_cases"]}
        assert list(ucs) == ["order-status", "return", "address", "refund"]
        assert ucs["address"]["cases"] == 10 and ucs["address"]["in_baseline"] == 10
        assert ucs["refund"]["in_baseline"] == 0 and ucs["address"]["labelled_runs"] == 0
        assert st["people"]["labels"] == {"fail": 0, "pass": 0} and st["people"]["labels_needed"]["fail"]
        assert any("not measured" in p for p in st["people"]["problems"])
        assert {c["part"] for c in st["components"]} and st["cases"][0]["use_case"]
        assert {r["id"] for r in st["standard"]["rules"]} >= {"asks-for-the-order-number"}
        code, body = call("/api/queue?labeller=ana")
        item = json.loads(body)["items"][0]
        assert "agent's answer" in item["view"] and "expected_end_state" not in body
        assert item["use_case"] == "address"
        assert call("/api/act/label", {"item": item, "label": "pass"})[0] == 400  # no name
        code, _ = call("/api/act/label", {"item": item, "label": "pass", "labeller": "ana", "by": "ana"})
        assert code == 200
        assert agreement.per_labeller(ev)[item["item_id"]]["ana"]["label"] is True
        code, body = call("/api/act/measure", {"by": "ana"})
        assert code == 200 and "dev" in json.loads(body)
        st = json.loads(call("/api/state")[1])
        assert {r["id"]: r for r in st["use_cases"]}["address"]["labelled_runs"] == 1
        assert not any("not measured" in p for p in st["people"]["problems"])
        code, body = call("/api/act/propose", {"by": "bo", "says": "Name the new address.", "use_cases": ["address"]})
        assert code == 200 and json.loads(body)["use_cases"] == ["address"]
        assert call("/api/act/nonsense", {})[0] == 400
    finally:
        httpd.shutdown()
        httpd.server_close()
    # its actions go to the agent system's shared activity log
    texts = [e["text"] for e in journal.entries(ev)]
    assert "ana labelled " + item["item_id"] + " pass" in texts
    assert store_repo.agent.joinpath("journal", "activity.jsonl").exists()
    assert not ev.p("journal").exists()


def test_serve_needs_an_eval_when_the_agent_has_several(store_repo, monkeypatch):
    from aot_evals import serve

    served = []
    monkeypatch.setattr(serve, "serve", lambda ev, **kw: served.append(ev.id))
    agent = str(store_repo.agent)
    with pytest.raises(SystemExit, match="several evals"):
        cli.main(["--evals", agent, "serve"])
    assert cli.main(["--evals", agent, "--eval", "refund-subagent", "serve"]) == 0
    assert served == ["refund-subagent"]


def test_the_application_shows_the_judges_of_its_eval(store_repo):
    from aot_evals import serve

    ev = store_repo.ev("refund-subagent")
    st = serve.state(ev)
    js = {j["id"]: j for j in st["judges"]}
    assert set(js) == {"policy-judge", "policy-judge-weak"}  # the judges its spec names
    assert js["policy-judge"]["labels"] == 600 and js["policy-judge"]["calibration"] == "calibrated"
    assert st["spec"]["complete"] and st["baseline"] == []
    assert serve.state(store_repo.ev())["judges"] == []  # every end-to-end check is code


def test_accepting_another_correct_answer_adds_a_variant_and_rescreens_the_case(store_repo):
    ev, run_id = _baseline(store_repo)
    it = next(i for i in _items(ev, run_id) if i["case_id"] == "tr_1204")
    path = ev.p("cases", "address", "tr_1204.json")
    case = json.loads(path.read_text())
    reference = case["expected_end_state"].pop("output")
    path.write_text(json.dumps(case, indent=2))
    with pytest.raises(ValueError, match="no reference answer"):
        bench.accept_answer(ev, it["item_id"], "ana")
    case["expected_end_state"]["output"] = "Sorry: A1409 already shipped, so its address can't change."
    path.write_text(json.dumps(case, indent=2))
    out = bench.accept_answer(ev, it["item_id"], "ana")
    case = json.loads(path.read_text())
    assert out["variants"] == 1 and case["expected_end_state"]["output_variants"] == [reference]
    assert case["screen"]["screened_at"] and case["screen"]["human_read"] is True  # the read is kept
    assert out["check_rejects"] == []  # the store's checks read the order system, not the wording
    t = (agreement.load_yaml(agreement.triage_path(ev)) or {})[it["item_id"]]
    assert t["cause"] == "wrong-expectation" and t["by"] == "ana"
    # a fixed expectation needs no engineer
    assert not any(x.get("item") == it["item_id"] for x in bench.inbox(ev))
