"""Judges (C9-C11).

Acceptance: an always-pass judge is caught by TPR/TNR and greyed; a System One and a generative
backend are compared on the same labels. The System One backend is a local fake speaking the
`POST /v1/systemone` wire contract; the generative backend is a command stand-in, and the
Anthropic backend is exercised against a fake SDK client.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
import shutil
import subprocess
import sys
import threading
import types
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from aot_evals import gates, judges
from aot_evals.judges import load_spec
from aot_evals.labels import import_rows
from aot_evals.repo import Evals

JUDGE = Path(__file__).parent / "fixtures" / "judge"


class FakeSystemOne(BaseHTTPRequestHandler):
    """Answers noul questions: p(yes) is high when the reply contains a time, with a little
    deterministic noise and a few confident mistakes, like a real model."""

    calls = 0

    def do_POST(self):  # noqa: N802
        FakeSystemOne.calls += 1
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        m = re.search(r"<end\.output>\n(.*?)\n</end\.output>", body["state"], re.S)
        out = m.group(1) if m else ""
        h = int(hashlib.sha256(out.encode()).hexdigest(), 16)
        p = 0.85 if re.search(r"\d{2}:\d{2}", out) else 0.2
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


def install_judge(repo, url: str, primary: str = "so") -> None:
    """Add the judge failure mode, spec and stand-in judge scripts to a fixture repo."""
    shutil.copytree(JUDGE / "judges", repo.root / "judges")
    text = (JUDGE / "reply-states-time.md").read_text()
    text = text.replace("{FAKE_URL}", url).replace("{PYTHON}", sys.executable)
    text = text.replace("primary: so", f"primary: {primary}")
    (repo.evals / "checks/judge").mkdir(parents=True, exist_ok=True)
    (repo.evals / "checks/judge/reply-states-time.md").write_text(text)
    fms = repo.yaml("failure_modes.yaml")
    fms["failure_modes"].append({"id": "reply-omits-time", "description": "The reply does not say when",
                                 "categories": ["book-meeting"], "check_type": "judge",
                                 "checks": ["reply-states-time"], "cost_cell": "incorrect"})
    repo.write_yaml("failure_modes.yaml", fms)
    for path in (repo.evals / "cases/book-meeting").glob("*.json"):
        case = json.loads(path.read_text())
        case["failure_modes"] = ["meeting-not-booked", "reply-omits-time"]
        path.write_text(json.dumps(case, indent=2))
    repo.commit("judge")


def synth_labels(repo, n_pass: int = 50, n_fail: int = 34) -> None:
    """Labelled items as a person would produce them: replies with and without the time."""
    spec = load_spec(repo.evals / "checks/judge/reply-states-time.md")
    rows = []
    for i in range(n_pass + n_fail):
        ev = {"title": f"Meeting {i}", "date": f"2026-11-{1 + i % 28:02d}",
              "time": f"{9 + i % 8:02d}:{(i * 7) % 60:02d}"}
        passing = i < n_pass
        out = (f"Booked {ev['title']} on {ev['date']} at {ev['time']}." if passing
               else [f"Booked {ev['title']}.", "Done, it's on the calendar.", f"All set for {ev['title']}!"][i % 3])
        rows.append({"case_id": f"synthetic-{i:03d}", "category": "book-meeting", "run": "", "trial": "",
                     "label": "pass" if passing else "fail", "labeller": "ana", "note": "",
                     "input": {"end.output": out, "case.inputs.event": ev}})
    res = import_rows(Evals(repo.evals), spec, rows, None)
    assert res["added"] == n_pass + n_fail, res
    repo.commit("labels")


def judge_row(report: dict) -> dict:
    return next(c for c in report["checks"] if c["id"] == "reply-states-time")


def test_label_queue_and_import_round_trip(make_repo, fake_url):
    repo = make_repo(variant="terse")
    install_judge(repo, fake_url)
    repo.cli("run", "--purpose", "baseline", "--k", "2", "--force")
    lines = [json.loads(x) for x in next((repo.evals / "runs").glob("*baseline")).joinpath("outcomes.jsonl")
             .read_text().splitlines()]
    judged = [x for x in lines if x.get("type") == "judge"]
    assert judged and all(x["backend"] == "so" and x["score"] is not None for x in judged)

    assert repo.cli("label", "queue", "--judge", "reply-states-time", "--n", "20") == 0
    queue = repo.evals / "checks/judge/reply-states-time.queue.csv"
    rows = list(csv.DictReader(queue.open()))
    assert 0 < len(rows) <= 7  # identical judge inputs across trials are one item
    page = repo.evals / "data/labelling/reply-states-time.html"
    data = json.loads(re.search(r'<script type="application/json" id="data">(.*?)</script>',
                                page.read_text(), re.S).group(1))
    assert [i["item_id"] for i in data["items"]] == [r["item_id"] for r in rows]
    assert all(isinstance(i["input"], dict) for i in data["items"])
    ignored = subprocess.run(["git", "check-ignore", "-q", str(page)], cwd=repo.root)
    assert ignored.returncode == 0  # it carries the judge inputs, like the queue
    assert {r["category"] for r in rows} == {"book-meeting"}
    for r in rows:
        r["label"] = "pass" if re.search(r"\d{2}:\d{2}", json.loads(r["input"])["end.output"]) else "fail"
    with queue.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    assert repo.cli("label", "import", "--judge", "reply-states-time", "--csv", str(queue), "--by", "ana") == 0
    labels = [json.loads(x) for x in (repo.evals / "checks/judge/reply-states-time.labels.jsonl")
              .read_text().splitlines()]
    assert len(labels) == len(rows)
    assert {lab["split"] for lab in labels} <= {"dev", "holdout"}
    assert "checks/judge/*.queue.csv" in (repo.evals / ".gitignore").read_text()
    c9 = next(g for g in gates.evaluate(Evals(repo.evals)) if g.id == "C9")
    assert c9.status == "unmet" and "at least 60" in c9.problems[0]


def test_always_pass_judge_is_caught_by_tnr_and_greyed(make_repo, fake_url):
    repo = make_repo(variant="terse")
    install_judge(repo, fake_url, primary="always")
    synth_labels(repo)
    assert repo.cli("calibrate", "--judge", "reply-states-time", "--backend", "always") == 0
    cal = json.loads((repo.evals / "checks/judge/reply-states-time.calibration.json").read_text())
    m = cal["backends"]["always"]
    assert m["tpr"] == 1.0 and m["tnr"] == 0.0
    assert cal["status"] == "uncalibrated" and any("TNR" in r for r in cal["status_reasons"])

    repo.commit("calibration")
    repo.cli("run", "--purpose", "baseline", "--k", "3", "--force")
    repo.cli("report")
    r = repo.report()
    g3 = repo.gate(r, "G3")
    assert g3["status"] == "fail" and "check:reply-states-time" in g3["blocks"] and "TNR" in g3["detail"]
    j = judge_row(r)["judge"]
    assert j["status"] == "uncalibrated" and j["tnr"] == 0.0 and j["labels"] == 84
    # greyed, not counted: the terse agent still books correctly, so the headline is untouched
    for row in r["categories"]:
        assert row["pass_rate"]["point"] == 1.0
    counted = [c for case in r["cases"] for t in case["trials"] for c in t["checks"] if c["type"] == "judge"]
    assert counted and not any(c["counted"] for c in counted)


def test_system_one_and_generative_compared_on_the_same_labels(make_repo, fake_url):
    repo = make_repo()
    install_judge(repo, fake_url)
    synth_labels(repo)
    assert repo.cli("calibrate", "--judge", "reply-states-time") == 0
    cal = json.loads((repo.evals / "checks/judge/reply-states-time.calibration.json").read_text())
    so, llm, always = (cal["backends"][b] for b in ("so", "llm", "always"))
    assert so["labels"] == llm["labels"] == always["labels"] == 84
    assert so["family"] != llm["family"]
    assert so["probabilistic"] and so["threshold"] is not None
    assert so["confidence_calibration"]["ece"] is not None and so["confidence_calibration"]["brier"] is not None
    assert not llm["probabilistic"] and llm["threshold"] is None
    assert so["tpr"] >= 0.75 and so["tnr"] >= 0.75 and llm["tpr"] >= 0.75 and llm["tnr"] >= 0.75
    assert so["cost_per_judgement"] < llm["cost_per_judgement"]
    assert cal["recommendation"]["backend"] == "so"  # E5: cheapest that clears both floors
    assert cal["status"] == "calibrated"
    assert "holdout" in so and so["holdout"]["n"] > 0

    # cached: a second calibration makes no new calls
    before = FakeSystemOne.calls
    repo.cli("calibrate", "--judge", "reply-states-time")
    assert FakeSystemOne.calls == before


def test_calibrated_judge_counts_toward_pass_rates(make_repo, fake_url):
    repo = make_repo(variant="terse")
    install_judge(repo, fake_url)
    synth_labels(repo)
    repo.cli("calibrate", "--judge", "reply-states-time")
    repo.commit("calibration")
    repo.cli("run", "--purpose", "baseline", "--k", "3", "--force")
    repo.cli("report")
    r = repo.report()
    assert repo.gate(r, "G3")["status"] == "pass"
    book = [row for row in r["categories"] if row["id"] == "book-meeting"]
    assert any(row["pass_rate"]["point"] < 1.0 for row in book)  # terse replies now fail
    nothing = [row for row in r["categories"] if row["id"] == "nothing-to-do"]
    assert all(row["pass_rate"]["point"] == 1.0 for row in nothing)
    j = judge_row(r)["judge"]
    assert j["status"] == "calibrated" and j["model_family"] == "typesafe"
    assert j["agent_model_family"] == "toy" and j["threshold"] is not None
    assert r["conditions"]["judge_backends"][0]["check"] == "reply-states-time"
    c10 = next(g for g in gates.evaluate(Evals(repo.evals)) if g.id == "C10")
    assert c10.status == "met"


def test_reliability_reports_cross_family_agreement_next_to_validity(make_repo, fake_url):
    repo = make_repo()
    install_judge(repo, fake_url)
    synth_labels(repo)
    repo.cli("calibrate", "--judge", "reply-states-time")
    assert repo.cli("reliability", "--judge", "reply-states-time", "--backend", "so",
                    "--backend", "llm", "--m", "2") == 0
    rel = json.loads((repo.evals / "checks/judge/reply-states-time.reliability.json").read_text())
    assert rel["m"] == 2 and rel["items"] == 84
    assert rel["backends"]["so"]["self_consistency"] == 1.0  # the fake is deterministic
    assert abs(sum(rel["three_level"].values()) - 1.0) < 1e-9
    assert rel["cross_family"][0]["agreement"] is not None
    assert rel["backends"]["llm"]["majority_vs_labels"]["tpr"] is not None
    c11 = next(g for g in gates.evaluate(Evals(repo.evals)) if g.id == "C11")
    assert c11.status == "met"
    sub = measure_subset(repo, 20)
    assert sub["backends"]["so"]["majority_vs_labels"]["tnr"] is not None  # both classes kept
    with pytest.raises(ValueError, match="one model family"):
        from aot_evals.reliability import measure
        spec = load_spec(repo.evals / "checks/judge/reply-states-time.md")
        spec.meta["backends"]["llm"]["family"] = "typesafe"
        measure(Evals(repo.evals), spec, ["so", "llm"], m=1)


def measure_subset(repo, n):
    from aot_evals.reliability import measure
    spec = load_spec(repo.evals / "checks/judge/reply-states-time.md")
    return measure(Evals(repo.evals), spec, ["so", "llm"], m=1, n=n)


def test_changing_the_judge_makes_its_calibration_stale(make_repo, fake_url):
    repo = make_repo()
    install_judge(repo, fake_url)
    synth_labels(repo)
    repo.cli("calibrate", "--judge", "reply-states-time")
    spec_path = repo.evals / "checks/judge/reply-states-time.md"
    spec_path.write_text(spec_path.read_text().replace("version: 1", "version: 2"))
    c10 = next(g for g in gates.evaluate(Evals(repo.evals)) if g.id == "C10")
    assert c10.status == "unmet" and "stale" in c10.problems[0]
    repo.commit("v2")
    repo.cli("run", "--purpose", "baseline", "--k", "3", "--force")
    repo.cli("report")
    assert "stale" in repo.gate(repo.report(), "G3")["detail"]


def test_judge_apply_to_a_past_run(make_repo, fake_url):
    repo = make_repo()
    install_judge(repo, fake_url)
    repo.cli("run", "--purpose", "baseline", "--k", "2", "--force", "--no-judges")
    out = next((repo.evals / "runs").glob("*baseline")) / "outcomes.jsonl"
    assert '"type": "judge"' not in out.read_text()
    assert repo.cli("judge", "apply", "--judge", "reply-states-time") == 0
    n = out.read_text().count('"type": "judge"')
    assert n == 14  # 7 booking cases x 2 trials
    repo.cli("judge", "apply", "--judge", "reply-states-time")
    assert out.read_text().count('"type": "judge"') == n


def test_pairwise_same_family_generative_judge_is_refused_by_g4(make_repo, fake_url):
    repo = make_repo()
    install_judge(repo, fake_url)
    p = repo.evals / "checks/judge/reply-states-time.md"
    p.write_text(p.read_text().replace("mode: binary", "mode: pairwise").replace(
        "primary: so", "primary: claude").replace(
        "backends:\n", "backends:\n  claude: {type: anthropic, model: claude-opus-5-5, family: toy}\n"))
    repo.commit("pairwise")
    repo.cli("run", "--purpose", "baseline", "--k", "3", "--force", "--no-judges")
    repo.cli("report")
    g4 = repo.gate(repo.report(), "G4")
    assert g4["status"] == "fail" and "check:reply-states-time" in g4["blocks"]


def test_empty_state_is_refused_not_sent(fake_url, tmp_path):
    spec_path = tmp_path / "evals/checks/judge/x.md"
    spec_path.parent.mkdir(parents=True)
    spec_path.write_text((JUDGE / "reply-states-time.md").read_text().replace("{FAKE_URL}", fake_url)
                         .replace("id: reply-states-time", "id: x"))
    spec = load_spec(spec_path)
    j = judges.judge(spec, "so", {"end.output": "", "case.inputs.event": None})
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

    replies = [Resp(json.dumps({"reasoning": "has a time", "answer": "yes"})), Resp("", "refusal")]

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
    spec_path = tmp_path / "evals/checks/judge/reply-states-time.md"
    spec_path.parent.mkdir(parents=True)
    spec_path.write_text((JUDGE / "reply-states-time.md").read_text().replace(
        "backends:\n", "backends:\n  claude: {type: anthropic, model: claude-opus-5-5, family: anthropic}\n"))
    spec = load_spec(spec_path)
    j = judges.judge(spec, "claude", {"end.output": "Booked at 10:00", "case.inputs.event": {}})
    assert j.score == 1.0 and j.reasoning == "has a time"
    assert j.cost_usd == pytest.approx((1000 * 4 + 200 * 20) / 1e6)
    kw = calls[0]
    assert kw["model"] == "claude-opus-5-5"
    assert kw["output_config"]["format"]["schema"]["properties"]["answer"]["enum"] == ["yes", "no"]
    assert "fallbacks" not in kw  # a judge is calibrated per model; no silent fallback
    j = judges.judge(spec, "claude", {"end.output": "x", "case.inputs.event": {}})
    assert j.score is None and "refused" in j.error


def add_backend(repo, name: str, line: str) -> None:
    path = repo.evals / "checks/judge/reply-states-time.md"
    text = path.read_text().replace("backends:\n", f"backends:\n  {name}: {line}\n", 1)
    path.write_text(text)


def test_adding_a_backend_keeps_the_other_backends_cached_judgements(make_repo, fake_url):
    repo = make_repo()
    install_judge(repo, fake_url)
    synth_labels(repo)
    assert repo.cli("calibrate", "--judge", "reply-states-time", "--backend", "so") == 0
    before = FakeSystemOne.calls
    add_backend(repo, "mine", f'{{type: command, command: ["{sys.executable}", judges/fake_llm.py], '
                              "model: other-llm, family: other}")
    assert repo.cli("calibrate", "--judge", "reply-states-time", "--backend", "so") == 0
    assert FakeSystemOne.calls == before


def test_a_rate_limit_stops_the_backend_and_is_reported_by_message(make_repo, fake_url, capsys):
    repo = make_repo()
    install_judge(repo, fake_url)
    synth_labels(repo)
    count = repo.root / "calls.txt"
    (repo.root / "judges/throttled.py").write_text(
        "import json, sys\njson.load(sys.stdin)\n"
        f"open({str(count)!r}, 'a').write('x')\n"
        "print(json.dumps({'error': 'HTTP 429 from https://opencode.ai/zen: FreeUsageLimitError'}))\n")
    add_backend(repo, "capped", f'{{type: command, command: ["{sys.executable}", judges/throttled.py], '
                                "model: jev-free, family: typesafe, daily_limit: 50}")
    capsys.readouterr()
    assert repo.cli("calibrate", "--judge", "reply-states-time", "--backend", "capped", "--dry-run") == 0
    assert "allows about 50 a day" in capsys.readouterr().err
    assert repo.cli("calibrate", "--judge", "reply-states-time", "--backend", "capped") == 0
    assert count.read_text() == "x"  # one call, not 84
    cal = json.loads((repo.evals / "checks/judge/reply-states-time.calibration.json").read_text())
    msgs = dict(cal["backends"]["capped"]["error_messages"])
    assert msgs["HTTP 429 from https://opencode.ai/zen: FreeUsageLimitError"] == 1
    assert any("stopped after a rate limit" in m and n == 83 for m, n in msgs.items())


def test_command_judge_is_told_which_way_yes_points(tmp_path):
    seen = tmp_path / "payload.json"
    script = tmp_path / "echo.py"
    script.write_text(f"import json, sys\nopen({str(seen)!r}, 'w').write(sys.stdin.read())\n"
                      "print(json.dumps({'verdict': 'fail'}))\n")
    (tmp_path / "evals/checks/judge").mkdir(parents=True)
    path = tmp_path / "evals/checks/judge/claims.md"
    path.write_text("---\nid: claims\nfailure_mode: x\nversion: 1\nquestion_type: noul\n"
                    "question: The answer makes a claim the documents do not cover.\ndetects: failure\n"
                    f'inputs: [end.output]\nbackends:\n  mine: {{type: command, command: ["{sys.executable}", '
                    f'"{script}"], model: m, family: f}}\n---\n\nFail when a claim is not in the documents.\n')
    spec = load_spec(path)
    j = judges.judge(spec, "mine", {"end.output": "Caching is free."})
    assert j.score == 0.0
    payload = json.loads(seen.read_text())
    assert payload["spec"]["detects"] == "failure" and "yes is a FAIL" in payload["spec"]["yes_means"]
    assert "Fail when a claim" in payload["spec"]["guidance"]
    assert "Caching is free." in payload["prompt"] and "Guidance:" in payload["prompt"]


def test_label_queue_samples_cases_then_only_trials_whose_answers_differ(tmp_path, monkeypatch):
    from aot_evals import labels

    (tmp_path / "evals/checks/judge").mkdir(parents=True)
    path = tmp_path / "evals/checks/judge/j.md"
    path.write_text("---\nid: j\nfailure_mode: x\nversion: 1\nquestion_type: noul\nquestion: q\n"
                    "detects: pass\ninputs: [end.output]\nbackends:\n  a: {type: command, command: [x], "
                    "model: m, family: f}\n---\n")
    spec = load_spec(path)
    answers = {
        "same": ["Booked Standup on 2026-11-02 at 10:00.", "Booked Standup on 2026-11-02 at 10:00!",
                 "booked standup on 2026-11-02 at 10:00."],
        "differs": ["Booked Review on 2026-11-03 at 15:00.", "I could not find a free slot; nothing was booked.",
                    "Done."],
        "other": ["Nothing to do.", "Nothing to do here.", "Nothing to do."],
    }
    items = [{"item_id": f"{c}-{t}", "case_id": c, "category": "cat-a" if c != "other" else "cat-b",
              "run": "r", "trial": t, "attempt": 0, "input": {"end.output": a}}
             for c, trials in answers.items() for t, a in enumerate(trials)]
    monkeypatch.setattr(labels, "run_items", lambda *a: items)
    _, picked = labels.make_queue(Evals(tmp_path / "evals"), spec, ["r"], n=20)
    assert {p["case_id"] for p in picked[:3]} == {"same", "differs", "other"}  # one per case first
    assert sorted(p["case_id"] for p in picked) == ["differs", "differs", "differs", "other", "same"]
