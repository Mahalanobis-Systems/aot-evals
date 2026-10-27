"""C7 screens on the reference answer: paraphrases pass, the liar fails, a wrong number fails.

Acceptance: a check that matches one wording of the answer fails a correct paraphrase and keeps
the case from counting; a suite that passes the reference answer with nothing changed is
refused; an answer with every number wrong is reported when nothing catches it.
"""

from __future__ import annotations

import json

from aot_evals.repo import Evals
from aot_evals.screen import screen_case

REPLY_CHECK = '''
def check(start, end, case):
    out = end.get("output") or ""
    return "14:00" in out, "reply names 14:00" if "14:00" in out else "reply does not name 14:00"
'''


def _setup(repo, variants: list[str]) -> dict:
    (repo.evals / "checks" / "code" / "reply-names-time.py").write_text(REPLY_CHECK)
    fms = repo.yaml("failure_modes.yaml")
    fms["failure_modes"][0]["checks"].append("reply-names-time")
    repo.write_yaml("failure_modes.yaml", fms)
    path = next((repo.evals / "cases").glob("*/book-001.json"))
    case = json.loads(path.read_text())
    case["expected_end_state"]["output"] = "Booked 'Sync with Ana' for 14:00."
    case["expected_end_state"]["output_variants"] = variants
    path.write_text(json.dumps(case, indent=2))
    ev = Evals.find(str(repo.evals))
    return screen_case(ev, next(c for c in ev.cases() if c["id"] == "book-001"))


def test_a_check_bound_to_one_wording_fails_a_paraphrase(make_repo):
    s = _setup(make_repo(), ["Done: Sync with Ana is on the calendar at 2 pm."])
    assert s["failing_paraphrases"] and "reply-names-time" in s["failing_paraphrases"][0]


def test_the_liar_fails_when_the_world_is_checked(make_repo):
    s = _setup(make_repo(), ["Sync with Ana is booked at 14:00."])
    assert s["failing_paraphrases"] == []
    assert s["liar_fails"] is True  # requested-event-exists sees nothing was booked
    assert s["wrong_number_fails"] is True  # 25:11 is not 14:00


def test_wrong_numbers_are_reported_when_nothing_reads_them(make_repo):
    repo = make_repo()
    path = next((repo.evals / "cases").glob("*/book-001.json"))
    case = json.loads(path.read_text())
    case["expected_end_state"]["output"] = "Booked for 14:00."
    path.write_text(json.dumps(case, indent=2))
    ev = Evals.find(str(repo.evals))
    s = screen_case(ev, next(c for c in ev.cases() if c["id"] == "book-001"))
    assert s["wrong_number_fails"] is False
    assert any("nothing checks the answer's numbers" in n for n in s["notes"])
