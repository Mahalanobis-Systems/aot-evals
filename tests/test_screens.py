"""Screens on the reference answer (`screen`; docs/method.md): paraphrases pass, the liar fails, a
wrong number fails, a non-answer fails.

Acceptance: a check that matches one wording of the answer fails a correct paraphrase and keeps
the case from counting; an eval that passes the reference answer with nothing changed is
refused; an answer with every number wrong is reported when nothing catches it.

The fixture is the store's end-to-end eval (conftest `store_repo`).
"""

from __future__ import annotations

import json

import yaml
from conftest import StoreRepo

from aot_evals.screen import passes, screen_case

E2E = "end-to-end"

# a diagnostic of wrong-answer that knows one wording of a refund reply
REPLY_CHECK = '''
def check(start, end, case):
    out = end.get("output") or ""
    ok = out.startswith("Refunded")
    return ok, "reply starts 'Refunded'" if ok else "reply does not start 'Refunded'"
'''


def _case(s: StoreRepo, cid: str):
    return next(s.agent.glob(f"{E2E}/cases/*/{cid}.json"))


def _screen(s: StoreRepo, cid: str, judges=None) -> dict:
    ev = s.ev(E2E)
    return screen_case(ev, next(c for c in ev.cases() if c["id"] == cid), judges=judges)


def _setup(s: StoreRepo, variants: list[str]) -> dict:
    """The refund of $27.99 for A1477 (tr_1238), with other wordings of its reply, under a
    diagnostic that knows one wording."""
    (s.agent / E2E / "checks" / "code" / "reply-says-refunded.py").write_text(REPLY_CHECK)
    path = s.agent / E2E / "eval.yaml"
    data = yaml.safe_load(path.read_text())
    next(f for f in data["measurement"]["failure_modes"] if f["id"] == "wrong-answer")["diagnostics"] = [
        "reply-says-refunded"]
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    p = _case(s, "tr_1238")
    case = json.loads(p.read_text())
    assert case["expected_end_state"]["output"] == "Refunded $27.99 for order A1477 to your original payment."
    case["expected_end_state"]["output_variants"] = variants
    p.write_text(json.dumps(case, indent=2))
    return _screen(s, "tr_1238")


def test_a_check_bound_to_one_wording_fails_a_paraphrase(store_repo):
    sc = _setup(store_repo, ["Your $27.99 refund for A1477 is on its way to your original payment."])
    assert sc["failing_paraphrases"] and "reply-says-refunded" in sc["failing_paraphrases"][0]
    assert len(sc["failing_paraphrases"]) == 1  # reply-matches-order reads the amount, not the wording
    assert passes({**sc, "human_read": True}) is False


def test_the_liar_fails_when_the_world_is_checked(store_repo):
    sc = _setup(store_repo, ["Refunded: $27.99 back to your original payment for A1477."])
    assert sc["failing_paraphrases"] == []
    assert sc["liar_fails"] is True  # end-state-matches sees no refund was made
    assert sc["wrong_number_fails"] is True  # $38.00 is not what was refunded
    assert passes({**sc, "human_read": True}) is True


def test_wrong_numbers_are_reported_when_nothing_reads_them(store_repo):
    # a return's reply is checked for saying a return was started, never for the order number
    sc = _screen(store_repo, "tr_1144")
    assert sc["wrong_number_fails"] is False
    assert any("nothing checks the answer's numbers" in n for n in sc["notes"])


def test_a_non_answer_must_fail_even_when_nothing_should_change(store_repo):
    s = store_repo
    # nothing reads the reply: wrong-answer's check passes whatever the agent says
    (s.agent / E2E / "checks" / "code" / "reply-matches-order.py").write_text(
        "def check(start, end, case):\n    return True, 'not read'\n")
    p = _case(s, "tr_1204")  # an address change refused: the order has shipped
    case = json.loads(p.read_text())
    assert case["expected_end_state"]["world"] == case["start_state"]
    sc = _screen(s, "tr_1204")
    assert sc["non_answer_fails"] is False  # nothing reads the reply, so "Done!" passes
    assert any("non-answer" in n for n in sc["notes"])

    sc = _screen(s, "tr_1204", judges=lambda start, end: [
        ("reply-judge", end["output"] != "Done!" and not end["output"].startswith("Done."))])
    assert sc["non_answer_fails"] is True
