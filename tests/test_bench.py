"""The bench of graders (bench.py, agreement.py) and the grader application (serve.py).

Acceptance: several people label the same run blind; where they differ the run has no verdict
until someone rules, and C19 stays open; a new labeller warms up on settled runs first; one queued
run in four is an overlap; a rule proposed from rulings joins the standard when the owner accepts
it, and the change is detected; the application refuses requests without its session token.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request

from aot_evals import agreement, bench, trust
from aot_evals.repo import Evals


def _baseline(repo) -> tuple[Evals, str]:
    ev = Evals(repo.evals)
    repo.cli("run", "--purpose", "smoke", "--case", "book-001")
    assert repo.cli("run", "--purpose", "baseline", "--k", "3") == 0
    return ev, ev.latest_run("baseline")["run_id"]


def _items(ev, run_id):
    return [{"item_id": agreement.item_key(run_id, a["case_id"], a["trial"], a["attempt"]),
             "case_id": a["case_id"], "run": run_id, "trial": a["trial"], "attempt": a["attempt"]}
            for a in agreement.finals(ev, [run_id])]


def test_labellers_who_disagree_leave_a_run_without_a_verdict_until_a_ruling(make_repo):
    repo = make_repo()
    ev, run_id = _baseline(repo)
    it = _items(ev, run_id)[0]
    bench.record_label(ev, it, "pass", "ana")
    assert [r["item_id"] for r in agreement.load_labels(ev)] == [it["item_id"]]
    bench.record_label(ev, it, "fail", "bo", "the time is wrong")
    assert agreement.load_labels(ev) == []  # disputed: counts toward nothing
    d = agreement.disputes(ev)
    assert len(d) == 1 and {x["labeller"] for x in d[0]["labels"]} == {"ana", "bo"}
    assert any("labellers disagree" in p for p in agreement.gate_problems(ev, None))
    pair = agreement.labeller_agreement(ev)[0]
    assert pair["labellers"] == ["ana", "bo"] and pair["n"] == 1 and pair["agree"] == 0

    agreement.add_ruling(ev, it["item_id"], False, "priya", "the time must match exactly")
    assert agreement.disputes(ev) == []
    (v,) = agreement.load_labels(ev)
    assert v["label"] is False and v["ruled"] and v["labellers"] == ["ana", "bo"]
    assert not any("labellers disagree" in p for p in agreement.gate_problems(ev, None))
    # the same person labelling again replaces their own label, not someone else's
    bench.record_label(ev, it, "fail", "ana")
    assert {k: r["label"] for k, r in agreement.per_labeller(ev)[it["item_id"]].items()} == {"ana": False, "bo": False}


def test_a_new_labeller_warms_up_on_settled_runs_then_gets_overlaps(make_repo):
    repo = make_repo()
    ev, run_id = _baseline(repo)
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
    # the settled answer is shown only after the label is in
    out = bench.record_label(ev, q[0], "fail", "cy")
    assert out["settled"]["label"] is True and "agreed" in out["settled"]["why"]
    # nobody is queued a run they labelled
    assert not {x["item_id"] for x in bench.queue(ev, "ana", n=50)} & {i["item_id"] for i in items[:10]}


def test_a_rule_proposed_from_rulings_joins_the_standard_when_the_owner_accepts(make_repo):
    repo = make_repo()
    ev, run_id = _baseline(repo)
    for it in _items(ev, run_id)[:3]:
        bench.record_label(ev, it, "pass", "ana")
    std = ev.p("labels", "standard.md")
    before = std.read_text()
    p = bench.propose_rule(ev, "A meeting booked a minute early fails.", ["book-meeting"], "bo")
    assert p["status"] == "proposed" and std.read_text() == before
    assert any(c["kind"] == "standard" for c in trust.changes(ev)) is False
    bench.decide_rule(ev, p["id"], True, "priya")
    text = std.read_text()
    assert "A meeting booked a minute early fails." in text and "accepted by priya" in text
    assert "# What makes a run of the toy calendar agent pass" in text  # comments kept
    assert text.endswith(before.split("---", 2)[2])  # the body is untouched
    from aot_evals.requirements import load_standard

    assert [r["id"] for r in load_standard(ev)["rules"]][-1] == p["id"]
    assert any(c["kind"] == "standard" for c in trust.changes(ev))
    assert len(bench.recheck(ev, p["id"])) >= 1


def test_a_drafted_case_waits_in_the_engineering_inbox(make_repo):
    repo = make_repo()
    ev, _ = _baseline(repo)
    d = bench.draft_case(ev, "book-001", "Book 'Retro' on 2026-10-09 at 16:00", "sam")
    assert ev.p("labels", "drafts", f"{d['id']}.json").exists()
    assert not ev.p("cases", "book-meeting", f"{d['id']}.json").exists()  # not graded until finished
    assert any(x["kind"] == "draft" and x["item"] == d["id"] for x in bench.inbox(ev))
    try:
        bench.draft_case(ev, "book-001", "token sk-ant-api03-" + "a" * 40, "sam")
        raise AssertionError("drafted a secret")
    except ValueError as e:
        assert "secret" in str(e)


def test_label_only_the_cases_a_change_moved(make_repo, capsys):
    repo = make_repo()
    ev, _ = _baseline(repo)
    a = repo.yaml("agent.yaml")
    a["invoke"]["env"]["AGENT_BREAK"] = "book-002,book-003"
    repo.write_yaml("agent.yaml", a)
    repo.commit("candidate")
    assert repo.cli("run", "--purpose", "candidate", "--k", "3", "--variable", "config=break") == 0
    repo.cli("compare")
    assert set(bench.changed_cases(ev)) == {"book-002", "book-003"}
    capsys.readouterr()
    assert repo.cli("agreement", "label", "queue", "--changed") == 0
    q = json.loads(ev.p("data", "agreement", "queue.json").read_text())
    assert {i["case_id"] for i in q["items"]} == {"book-002", "book-003"}
    assert all("candidate" in i["run"] for i in q["items"])
    assert {x["case_id"] for x in bench.queue(ev, "ana", mode="changed")} == {"book-002", "book-003"}
    # the current agent ran as that candidate and was compared: the step is to decide, not to rerun
    kinds = [c["kind"] for c in trust.changes(ev)]
    assert "adopt" in kinds and "agent" not in kinds


def test_the_application_needs_its_token_and_writes_the_suite(make_repo):
    from http.server import ThreadingHTTPServer

    from aot_evals import serve

    repo = make_repo()
    ev, run_id = _baseline(repo)
    token = "t0ken"
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

    try:
        assert call("/")[0] == 403  # the page itself needs ?t=
        code, html = call(f"/?t={token}")
        assert code == 200 and "Grade" in html and token in html
        assert call("/api/state", tok="nope")[0] == 403
        assert call("/api/act/label", {"item": {}}, tok="nope")[0] == 403
        code, body = call("/api/state")
        st = json.loads(body)
        assert code == 200 and st["phase"]["id"] == "judge" and st["trust"]
        code, body = call("/api/queue?labeller=ana")
        item = json.loads(body)["items"][0]
        assert "agent's answer" in item["view"] and "expected_end_state" not in body
        assert call("/api/act/label", {"item": item, "label": "pass"})[0] == 400  # no name
        code, _ = call("/api/act/label", {"item": item, "label": "pass", "labeller": "ana", "by": "ana"})
        assert code == 200
        assert agreement.per_labeller(ev)[item["item_id"]]["ana"]["label"] is True
        code, body = call("/api/act/measure", {"by": "ana"})
        assert code == 200 and "dev" in json.loads(body)
        assert call("/api/act/nonsense", {})[0] == 400
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_accepting_another_correct_answer_adds_a_variant_and_rescreens_the_case(make_repo):
    repo = make_repo()
    ev, run_id = _baseline(repo)
    it = next(i for i in _items(ev, run_id) if i["case_id"] == "book-001")
    try:
        bench.accept_answer(ev, it["item_id"], "ana")
        raise AssertionError("accepted a wording for a case with no reference answer")
    except ValueError as e:
        assert "no reference answer" in str(e)
    path = ev.p("cases", "book-meeting", "book-001.json")
    case = json.loads(path.read_text())
    case["expected_end_state"]["output"] = "Booked 'Sync with Ana' for 2026-10-05 at 14:00."
    path.write_text(json.dumps(case, indent=2))
    out = bench.accept_answer(ev, it["item_id"], "ana")
    case = json.loads(path.read_text())
    assert out["variants"] == 1 and len(case["expected_end_state"]["output_variants"]) == 1
    assert case["screen"]["screened_at"] and case["screen"]["human_read"] is True  # the read is kept
    assert out["check_rejects"] == []  # this suite's checks read the calendar, not the wording
    t = (agreement.load_yaml(agreement.triage_path(ev)) or {})[it["item_id"]]
    assert t["cause"] == "wrong-expectation" and t["by"] == "ana"
    # a fixed expectation needs no engineer
    assert not any(x.get("item") == it["item_id"] for x in bench.inbox(ev))
