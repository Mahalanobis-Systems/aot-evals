"""Opt-in live check of the systemone backend against Jev's free route on OpenCode Zen.

    AOT_EVALS_LIVE=1 pytest tests/test_live_systemone.py

Makes six free, unauthenticated calls (rate-limited per IP by the gateway). Skipped by default so
the suite never depends on the network.
"""

from __future__ import annotations

import os

import pytest

from aot_evals import judges

pytestmark = pytest.mark.skipif(os.environ.get("AOT_EVALS_LIVE") != "1", reason="set AOT_EVALS_LIVE=1")

BACKEND = "zen: {type: systemone, model: jev-1.13-free, family: typesafe, base_url: 'https://opencode.ai/zen'}"
QUESTIONS = {
    "noul": "question_type: noul\nquestion: The reply tells the user the date and time of the booked meeting.\n"
            "detects: pass",
    "choice": "question_type: choice\nquestion: Which best describes the reply?\noptions: {complete: states title "
              "date and time, partial: omits the date or time, none: does not confirm a booking}\n"
              "pass_options: [complete]",
    "score": "question_type: score\nquestion: How specific is the confirmation?\n"
             "options: [Vague, Somewhat specific, Fully specific]\npass_min_level: 2",
}
EVENT = {"title": "Sync with Ana", "date": "2026-10-05", "time": "14:00"}


@pytest.mark.parametrize("qt", list(QUESTIONS))
def test_jev_separates_a_complete_reply_from_a_vague_one(qt, tmp_path):
    p = tmp_path / "evals/checks/judge" / f"{qt}.md"
    p.parent.mkdir(parents=True)
    p.write_text(f"---\nid: {qt}\nfailure_mode: x\nversion: 1\ninputs: [end.output, case.inputs.event]\n"
                 f"primary: zen\nbackends:\n  {BACKEND}\n{QUESTIONS[qt]}\n---\n")
    spec = judges.load_spec(p)
    assert not spec.problems()
    good = judges.judge(spec, "zen", {"end.output": "Booked Sync with Ana on 2026-10-05 at 14:00.",
                                      "case.inputs.event": EVENT})
    bad = judges.judge(spec, "zen", {"end.output": "Booked Sync with Ana.", "case.inputs.event": EVENT})
    assert good.error is None and bad.error is None, (good.error, bad.error)
    assert good.score > 0.5 > bad.score
    assert good.tokens_input and good.cost_usd == 0.0
