"""Judges (docs/v2-design.md §4): labels, calibration in catch and clean pass rates, backends
compared on the same labels, judges applied to past runs, and the backends' wire contracts.

The fixture is the store (conftest `store_repo`), whose refund-subagent eval gets a judge of the
test's own: `reply-names-amount`, which passes a reply that says how much was refunded. It is a
diagnostic of wrong-reply unless a test makes it that mode's counted check. Its System One
backend is a local fake speaking the `POST /v1/systemone` wire contract; its generative backend
is a command stand-in, and the Anthropic backend is exercised against a fake SDK client.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
import subprocess
import sys
import threading
import types
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
import yaml
from conftest import StoreRepo

from aot_evals import judges
from aot_evals.judges import load_spec
from aot_evals.labels import import_rows

EVAL = "refund-subagent"
JUDGE_ID = "reply-names-amount"
AMOUNT = re.compile(r"\$\d+\.\d{2}")

FAKE_LLM = '''"""A stand-in generative judge: right about nine times in ten, deterministically."""
import hashlib, json, re, sys
req = json.load(sys.stdin)
out = req["input"].get("end.output") or ""
ok = bool(re.search(r"\\$\\d+\\.\\d{2}", out))
if int(hashlib.sha256(out.encode()).hexdigest(), 16) % 10 == 0:
    ok = not ok
print(json.dumps({"verdict": "pass" if ok else "fail", "reasoning": "looked for an amount", "cost": 0.002}))
'''

ALWAYS_PASS = '''"""The always-pass self-test judge: agrees with every passing label and catches nothing."""
import json, sys
json.load(sys.stdin)
print(json.dumps({"verdict": "pass", "reasoning": "looks fine", "cost": 0.0001}))
'''


class FakeSystemOne(BaseHTTPRequestHandler):
    """Answers noul questions: p(yes) is high when the reply names an amount, with a little
    deterministic noise and a few confident mistakes, like a real model."""

    calls = 0

    def do_POST(self):  # noqa: N802
        FakeSystemOne.calls += 1
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        m = re.search(r"<end\.output>\n(.*?)\n</end\.output>", body["state"], re.S)
        out = m.group(1) if m else ""
        h = int(hashlib.sha256(out.encode()).hexdigest(), 16)
        p = 0.85 if AMOUNT.search(out) else 0.2
        p += ((h % 11) - 5) / 50
        if h % 17 == 0:
            p = 1 - p
        resp = {"model": body["model"], "answers": {"q": {"type": "noul", "noul": round(p, 3)}},
                "usage": {"input_tokens": len(body["state"]) // 4, "output_tokens": 1}, "cost": "0"}
        data = json.dumps(resp).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


@pytest.fixture(scope="module")
def fake_url():
    server = HTTPServer(("127.0.0.1", 0), FakeSystemOne)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


def _judge_md(url: str, primary: str = "so", extra: str = "") -> str:
    py = sys.executable
    return f"""---
id: {JUDGE_ID}
version: 1
question_type: noul
question: The reply tells the customer how much was refunded.
detects: pass
inputs: [end.output, case.inputs]
primary: {primary}
backends:
{extra}  so:     {{type: systemone, model: jev-test, family: typesafe, base_url: "{url}"}}
  llm:    {{type: command, command: ["{py}", judges/fake_llm.py], model: fake-llm-1, family: fake-llm}}
  always: {{type: command, command: ["{py}", judges/always_pass.py], model: always-pass, family: rubber-stamp}}
---

Pass when the reply names the amount refunded. A reply that only says the refund was made fails.
"""


def judge_path(s: StoreRepo):
    return s.agent / EVAL / "checks" / "judge" / f"{JUDGE_ID}.md"


def install_judge(s: StoreRepo, url: str, primary: str = "so", counted: bool = False) -> None:
    """The test's judge, its stand-in scripts, and its place in the refund eval's measurement
    model: a diagnostic of wrong-reply, or (`counted`) that mode's counted check."""
    (s.root / "judges" / "fake_llm.py").write_text(FAKE_LLM)
    (s.root / "judges" / "always_pass.py").write_text(ALWAYS_PASS)
    judge_path(s).write_text(_judge_md(url, primary))
    path = s.agent / EVAL / "eval.yaml"
    data = yaml.safe_load(path.read_text())
    fm = next(f for f in data["measurement"]["failure_modes"] if f["id"] == "wrong-reply")
    if counted:
        fm.update(check=JUDGE_ID, diagnostics=["reply-matches-refund"])
    else:
        fm["diagnostics"] = [JUDGE_ID]
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    s.commit("judge")


def synth_labels(s: StoreRepo, n_pass: int = 50, n_fail: int = 34) -> None:
    """Labelled items as a person would produce them: replies with and without the amount."""
    spec = load_spec(judge_path(s))
    rows = []
    for i in range(n_pass + n_fail):
        inputs = {"order_id": f"A{7000 + i}", "items": None, "to": "original", "today": "2026-10-20"}
        passing = i < n_pass
        out = (f"Refunded ${10 + i * 1.37:.2f} for order {inputs['order_id']} to your original payment."
               if passing else [f"Refunded order {inputs['order_id']}.", f"Done, {inputs['order_id']} is refunded.",
                                f"All set for {inputs['order_id']}!"][i % 3])
        rows.append({"case_id": f"synthetic-{i:03d}", "use_case": "full-refund", "run": "", "trial": "",
                     "label": "pass" if passing else "fail", "labeller": "ana", "note": "",
                     "input": {"end.output": out, "case.inputs": inputs}})
    res = import_rows(s.ev(EVAL), spec, rows, None)
    assert res["added"] == n_pass + n_fail, res
    s.commit("labels")


def calibration(s: StoreRepo) -> dict:
    return json.loads(judge_path(s).with_name(f"{JUDGE_ID}.calibration.json").read_text())


# Five refund cases, one of which the good subagent gets wrong (the 30th day is refused): enough
# to put the policy judge's floor rate well above 3%, so it passes its floor on these runs.
CASES = ("tr_1232.h0", "tr_1235.h0", "bf-window-30", "bf-no-order-number", "bf-not-delivered")


def _run(s: StoreRepo, *args: str) -> str:
    sel = [a for c in CASES for a in ("--case", c)]
    assert s.cli("run", "--purpose", "baseline", *sel, *args, eval_id=EVAL) == 0
    return s.ev(EVAL).runs("baseline")[-1]["run_id"]


def _gates(r: dict) -> list[tuple[str, str | None]]:
    return [(g["id"], g.get("check")) for g in r["measurement"]["gates"] if not g["id"].startswith("people_")]


def test_label_queue_and_import_round_trip(store_repo, fake_url):
    s = store_repo
    install_judge(s, fake_url)
    rid = _run(s)
    ev = s.ev(EVAL)
    lines = ev.run_records(rid)
    judged = [x for x in lines if x.get("kind") == "check" and x.get("check_id") == JUDGE_ID]
    assert judged and all(x["backend"] == "so" and x["score"] is not None and x["counted"] is False
                          for x in judged)

    assert s.cli("label", "queue", "--judge", JUDGE_ID, "--n", "20", eval_id=EVAL) == 0
    queue = judge_path(s).with_name(f"{JUDGE_ID}.queue.csv")
    rows = list(csv.DictReader(queue.open()))
    assert 0 < len(rows) <= len(CASES)  # identical judge inputs across trials are one item
    page = ev.p("data", "labelling", f"{JUDGE_ID}.html")
    data = json.loads(re.search(r'<script type="application/json" id="data">(.*?)</script>',
                                page.read_text(), re.S).group(1))
    assert [i["item_id"] for i in data["items"]] == [r["item_id"] for r in rows]
    assert all(isinstance(i["input"], dict) for i in data["items"])
    assert {r["use_case"] for r in rows} <= {"full-refund", "partial-refund", "gift-card"}
    for r in rows:
        r["label"] = "pass" if AMOUNT.search(json.loads(r["input"])["end.output"]) else "fail"
    with queue.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    assert s.cli("label", "import", "--judge", JUDGE_ID, "--csv", str(queue), "--by", "ana", eval_id=EVAL) == 0
    labels = [json.loads(x) for x in judge_path(s).with_name(f"{JUDGE_ID}.labels.jsonl").read_text().splitlines()]
    assert len(labels) == len(rows)
    assert {lab["split"] for lab in labels} <= {"dev", "holdout"}
    assert {lab["use_case"] for lab in labels} <= {"full-refund", "partial-refund", "gift-card"}


def test_the_label_queue_and_page_are_git_ignored(store_repo, fake_url):
    s = store_repo
    install_judge(s, fake_url)
    _run(s)
    assert s.cli("label", "queue", "--judge", JUDGE_ID, "--n", "5", eval_id=EVAL) == 0
    ev = s.ev(EVAL)
    for path in (judge_path(s).with_name(f"{JUDGE_ID}.queue.csv"), ev.p("data", "labelling", f"{JUDGE_ID}.html")):
        # each carries the judge inputs, which hold agent output
        assert subprocess.run(["git", "check-ignore", "-q", str(path)], cwd=s.root).returncode == 0, path


def test_always_pass_judge_is_caught_by_its_catch_rate_and_does_not_count(store_repo, fake_url):
    s = store_repo
    install_judge(s, fake_url, primary="always", counted=True)
    synth_labels(s)
    assert s.cli("calibrate", "--judge", JUDGE_ID, "--backend", "always", eval_id=EVAL) == 0
    cal = calibration(s)
    m = cal["backends"]["always"]
    assert m["clean"] == 1.0 and m["catch"] == 0.0 and m["j"] == 0.0
    assert m["labels_per_kind"] == {"fail": 34, "pass": 50}
    # labels of both kinds and a verdict on each: calibrated; the floor is what refuses it
    assert cal["status"] == "calibrated" and "min_tpr" not in cal
    assert cal["recommendation"] is None  # its lower bounds give no finite inflation

    s.commit("calibration")
    _run(s)
    assert s.cli("report", eval_id=EVAL) == 0
    r = s.report(EVAL)
    assert _gates(r) == [("judge_floor", JUDGE_ID)]
    fm = next(x for x in r["measurement"]["failure_modes"] if x["id"] == "wrong-reply")
    assert fm["floor"]["status"] == "refused" and fm["catch"] == 0.0 and fm["labels"] == {"fail": 34, "pass": 50}
    assert not fm["feeds_estimate"]  # a judge on another mode than the quantity's leaves θ̂ alone
    counted = [x for x in s.ev(EVAL).run_records(r["runs"][0]) if x.get("check_id") == JUDGE_ID]
    assert counted and all(x["counted"] for x in counted)


def test_system_one_and_generative_compared_on_the_same_labels(store_repo, fake_url):
    s = store_repo
    install_judge(s, fake_url)
    synth_labels(s)
    assert s.cli("calibrate", "--judge", JUDGE_ID, eval_id=EVAL) == 0
    cal = calibration(s)
    so, llm, always = (cal["backends"][b] for b in ("so", "llm", "always"))
    assert so["labels"] == llm["labels"] == always["labels"] == 84
    assert so["family"] != llm["family"]
    assert so["probabilistic"] and so["threshold"] is not None
    assert so["confidence_calibration"]["ece"] is not None and so["confidence_calibration"]["brier"] is not None
    assert not llm["probabilistic"] and llm["threshold"] is None
    for b in (so, llm):
        assert b["catch"] >= 0.75 and b["clean"] >= 0.75 and b["labels_per_kind"] == {"fail": 34, "pass": 50}
        assert b["catch"] == b["tnr"] and b["clean"] == b["tpr"]  # the 1.x names kept beside them
    assert so["cost_per_judgement"] < llm["cost_per_judgement"]
    # the backend whose lower bounds cost the fewest cases at 3%; never the rubber stamp
    rec = cal["recommendation"]["backend"]
    best = min(("so", "llm"), key=lambda b: cal["backends"][b]["inflation_at_lower_bounds"]["0.03"])
    assert rec == best
    assert cal["status"] == "calibrated"
    assert "holdout" in so and so["holdout"]["n"] > 0

    # cached: a second calibration makes no new calls
    before = FakeSystemOne.calls
    s.cli("calibrate", "--judge", JUDGE_ID, eval_id=EVAL)
    assert FakeSystemOne.calls == before


def test_a_calibrated_judge_counts_and_its_verdicts_are_recorded(store_repo, fake_url):
    s = store_repo
    install_judge(s, fake_url, counted=True)
    synth_labels(s, n_pass=300, n_fail=100)
    assert s.cli("calibrate", "--judge", JUDGE_ID, "--backend", "so", eval_id=EVAL) == 0
    s.commit("calibration")
    rid = _run(s)
    lines = [x for x in s.ev(EVAL).run_records(rid) if x.get("check_id") == JUDGE_ID]
    assert lines and all(x["threshold"] is not None and x["judge_family"] == "typesafe" for x in lines)
    assert s.cli("report", eval_id=EVAL) == 0
    fm = next(x for x in s.report(EVAL)["measurement"]["failure_modes"] if x["id"] == "wrong-reply")
    assert fm["type"] == "judge" and fm["calibration"] == "calibrated"
    assert fm["labels"] == {"fail": 100, "pass": 300} and fm["catch"] is not None
    # the mode's rate as judged, corrected for the judge's measured catch and clean rates
    corr = fm["corrected_rate"]
    assert fm["observed_rate"] is not None and corr is not None
    assert 0 <= corr["ci"][0] <= corr["point"] <= corr["ci"][1] <= 1


def test_reliability_reports_cross_family_agreement_next_to_validity(store_repo, fake_url):
    s = store_repo
    install_judge(s, fake_url)
    synth_labels(s)
    s.cli("calibrate", "--judge", JUDGE_ID, eval_id=EVAL)
    assert s.cli("reliability", "--judge", JUDGE_ID, "--backend", "so", "--backend", "llm", "--m", "2",
                 eval_id=EVAL) == 0
    rel = json.loads(judge_path(s).with_name(f"{JUDGE_ID}.reliability.json").read_text())
    assert rel["m"] == 2 and rel["items"] == 84
    assert rel["backends"]["so"]["self_consistency"] == 1.0  # the fake is deterministic
    assert abs(sum(rel["three_level"].values()) - 1.0) < 1e-9
    assert rel["cross_family"][0]["agreement"] is not None
    assert rel["backends"]["llm"]["majority_vs_labels"]["tpr"] is not None

    from aot_evals.reliability import measure

    spec = load_spec(judge_path(s))
    sub = measure(s.ev(EVAL), spec, ["so", "llm"], m=1, n=20)
    assert sub["backends"]["so"]["majority_vs_labels"]["tnr"] is not None  # both kinds kept
    spec.meta["backends"]["llm"]["family"] = "typesafe"
    with pytest.raises(ValueError, match="one model family"):
        measure(s.ev(EVAL), spec, ["so", "llm"], m=1)


def test_changing_the_judge_makes_its_calibration_stale(store_repo, fake_url):
    s = store_repo
    install_judge(s, fake_url, counted=True)
    synth_labels(s, n_pass=300, n_fail=100)
    s.cli("calibrate", "--judge", JUDGE_ID, "--backend", "so", eval_id=EVAL)
    path = judge_path(s)
    path.write_text(path.read_text().replace("version: 1", "version: 2"))
    s.commit("judge v2")
    _run(s)
    assert s.cli("report", eval_id=EVAL) == 0
    r = s.report(EVAL)
    assert _gates(r) == [("judge_calibration", JUDGE_ID)]
    fm = next(x for x in r["measurement"]["failure_modes"] if x["id"] == "wrong-reply")
    assert fm["calibration"] == "stale" and "rule 13" in fm["floor"]["reason"]


def test_judge_apply_to_a_past_run(store_repo):
    s = store_repo
    rid = _run(s, "--no-judges")
    out = s.ev(EVAL).p("runs", rid, "outcomes.jsonl")
    assert '"type": "judge"' not in out.read_text()
    assert s.cli("judge", "apply", "--judge", "policy-judge", eval_id=EVAL) == 0
    n = out.read_text().count('"check_id": "policy-judge"')
    assert n == len(CASES) * 3
    s.cli("judge", "apply", "--judge", "policy-judge", eval_id=EVAL)
    assert out.read_text().count('"check_id": "policy-judge"') == n


def _loose_spec(tmp_path, name: str, text: str):
    """A judge file in an eval's checks/judge/ of an agent folder, outside any fixture."""
    path = tmp_path / "evals" / "agents" / "a" / "e" / "checks" / "judge" / f"{name}.md"
    path.parent.mkdir(parents=True)
    path.write_text(text)
    return load_spec(path)


def test_empty_state_is_refused_not_sent(fake_url, tmp_path):
    spec = _loose_spec(tmp_path, JUDGE_ID, _judge_md(fake_url))
    j = judges.judge(spec, "so", {"end.output": "", "case.inputs": None})
    assert j.score is not None  # "<end.output>" tags are present, so the state is not empty
    j = judges.judge(spec, "so", {})
    assert j.score is None and "empty" in j.error


def test_anthropic_backend_parses_structured_verdicts_and_refusals(monkeypatch, tmp_path):
    calls = []

    class Usage:
        input_tokens, output_tokens = 1000, 200

    class Block:
        type = "text"

        def __init__(self, text):
            self.text = text

    class Resp:
        def __init__(self, text, stop="end_turn"):
            self.content = [Block(text)]
            self.stop_reason = stop
            self.stop_details = types.SimpleNamespace(category="cyber") if stop == "refusal" else None
            self.usage = Usage()

    replies = [Resp(json.dumps({"reasoning": "names an amount", "answer": "yes"})), Resp("", "refusal")]

    class Messages:
        def create(self, **kw):
            calls.append(kw)
            return replies.pop(0)

    class APIStatusError(Exception):
        pass

    fake = types.SimpleNamespace(Anthropic=lambda **kw: types.SimpleNamespace(messages=Messages()),
                                 RateLimitError=APIStatusError, APIStatusError=APIStatusError,
                                 APIConnectionError=APIStatusError)
    monkeypatch.setitem(sys.modules, "anthropic", fake)
    spec = _loose_spec(tmp_path, JUDGE_ID, _judge_md(
        "http://127.0.0.1:9", extra="  claude: {type: anthropic, model: claude-opus-5-5, family: anthropic}\n"))
    j = judges.judge(spec, "claude", {"end.output": "Refunded $10.00", "case.inputs": {}})
    assert j.score == 1.0 and j.reasoning == "names an amount"
    assert j.cost_usd == pytest.approx((1000 * 4 + 200 * 20) / 1e6)
    kw = calls[0]
    assert kw["model"] == "claude-opus-5-5"
    assert kw["output_config"]["format"]["schema"]["properties"]["answer"]["enum"] == ["yes", "no"]
    assert "fallbacks" not in kw  # a judge is calibrated per model; no silent fallback
    j = judges.judge(spec, "claude", {"end.output": "x", "case.inputs": {}})
    assert j.score is None and "refused" in j.error


def add_backend(s: StoreRepo, name: str, line: str) -> None:
    path = judge_path(s)
    path.write_text(path.read_text().replace("backends:\n", f"backends:\n  {name}: {line}\n", 1))


def test_adding_a_backend_keeps_the_other_backends_cached_judgements(store_repo, fake_url):
    s = store_repo
    install_judge(s, fake_url)
    synth_labels(s)
    assert s.cli("calibrate", "--judge", JUDGE_ID, "--backend", "so", eval_id=EVAL) == 0
    before = FakeSystemOne.calls
    add_backend(s, "mine", f'{{type: command, command: ["{sys.executable}", judges/fake_llm.py], '
                           "model: other-llm, family: other}")
    assert s.cli("calibrate", "--judge", JUDGE_ID, "--backend", "so", eval_id=EVAL) == 0
    assert FakeSystemOne.calls == before


def test_a_rate_limit_stops_the_backend_and_is_reported_by_message(store_repo, fake_url, capsys):
    s = store_repo
    install_judge(s, fake_url)
    synth_labels(s)
    count = s.root / "calls.txt"
    (s.root / "judges" / "throttled.py").write_text(
        "import json, sys\njson.load(sys.stdin)\n"
        f"open({str(count)!r}, 'a').write('x')\n"
        "print(json.dumps({'error': 'HTTP 429 from https://opencode.ai/zen: FreeUsageLimitError'}))\n")
    add_backend(s, "capped", f'{{type: command, command: ["{sys.executable}", judges/throttled.py], '
                             "model: jev-free, family: typesafe, daily_limit: 50}")
    capsys.readouterr()
    assert s.cli("calibrate", "--judge", JUDGE_ID, "--backend", "capped", "--dry-run", eval_id=EVAL) == 0
    assert "allows about 50 a day" in capsys.readouterr().err
    assert s.cli("calibrate", "--judge", JUDGE_ID, "--backend", "capped", eval_id=EVAL) == 0
    assert count.read_text() == "x"  # one call, not 84
    msgs = dict(calibration(s)["backends"]["capped"]["error_messages"])
    assert msgs["HTTP 429 from https://opencode.ai/zen: FreeUsageLimitError"] == 1
    assert any("stopped after a rate limit" in m and n == 83 for m, n in msgs.items())


def test_command_judge_is_told_which_way_yes_points(tmp_path):
    seen = tmp_path / "payload.json"
    script = tmp_path / "echo.py"
    script.write_text(f"import json, sys\nopen({str(seen)!r}, 'w').write(sys.stdin.read())\n"
                      "print(json.dumps({'verdict': 'fail'}))\n")
    spec = _loose_spec(tmp_path, "claims", (
        "---\nid: claims\nversion: 1\nquestion_type: noul\n"
        "question: The answer makes a claim the documents do not cover.\ndetects: failure\n"
        f'inputs: [end.output]\nbackends:\n  mine: {{type: command, command: ["{sys.executable}", '
        f'"{script}"], model: m, family: f}}\n---\n\nFail when a claim is not in the documents.\n'))
    j = judges.judge(spec, "mine", {"end.output": "Caching is free."})
    assert j.score == 0.0
    payload = json.loads(seen.read_text())
    assert payload["spec"]["detects"] == "failure" and "yes is a FAIL" in payload["spec"]["yes_means"]
    assert "Fail when a claim" in payload["spec"]["guidance"]
    assert "Caching is free." in payload["prompt"] and "Guidance:" in payload["prompt"]


def test_label_queue_samples_cases_then_only_trials_whose_answers_differ(store_repo, monkeypatch):
    from aot_evals import labels

    s = store_repo
    spec = _loose_spec(s.root / "elsewhere", "j", (
        "---\nid: j\nversion: 1\nquestion_type: noul\nquestion: q\n"
        "detects: pass\ninputs: [end.output]\nbackends:\n  a: {type: command, command: [x], "
        "model: m, family: f}\n---\n"))
    answers = {
        "same": ["Refunded $64.40 for order A1001.", "Refunded $64.40 for order A1001!",
                 "refunded $64.40 for order a1001."],
        "differs": ["Refunded $12.00 for order A1002.", "Order A1002 was delivered 31 days ago, past the window.",
                    "Done."],
        "other": ["What is your order number?", "What's your order number?", "What is your order number?"],
    }
    items = [{"item_id": f"{c}-{t}", "case_id": c, "use_case": "full-refund" if c != "other" else "gift-card",
              "run": "r", "trial": t, "attempt": 0, "input": {"end.output": a}}
             for c, trials in answers.items() for t, a in enumerate(trials)]
    monkeypatch.setattr(labels, "run_items", lambda *a: items)
    monkeypatch.setattr(labels, "queue_path", lambda ev, sp: s.root / "q.csv")
    _, picked = labels.make_queue(s.ev(EVAL), spec, ["r"], n=20)
    assert {p["case_id"] for p in picked[:3]} == {"same", "differs", "other"}  # one per case first
    assert sorted(p["case_id"] for p in picked) == ["differs", "differs", "differs", "other", "same"]
