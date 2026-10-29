"""C7 `screen`: is each case a valid test?

Three screens per case (M22):

- **reference passes**: the case's checks pass on (start_state -> expected_end_state). A case
  whose own expected end state fails its checks has a broken check or a broken expectation.
- **do-nothing fails**: at least one check fails on (start_state -> start_state). A case that an
  agent can pass by doing nothing tests nothing. Not applicable when the expected end state is
  the start state (a "nothing to do" case, where doing nothing is the reference); recorded as
  `null` with a note.
- **human read**: a person read the case. Recorded with `--read-by`; never inferred.

The do-nothing screen runs twice: once with no output and once with a confident success claim
as the output. A check that fails the first and passes the second is grading the agent's own
report of success; it is recorded in `claim_sensitive_checks` and refused by G10.

Three more screens use the case's reference answer (`expected_end_state.output`) and any other
correct wordings of it (`expected_end_state.output_variants`), because a check that matches one
wording fails correct answers written another way (in our experiments: "$1.413M" against "1,413,000"):

- **paraphrases pass**: every variant, with the expected world, passes every check;
- **the liar fails**: the reference answer with the world unchanged fails at least one check,
  when the case expects a change. A suite that passes it grades what the agent says, not what it
  did;
- **a non-answer fails**: "Done!", or the request echoed back, with nothing changed fails at
  least one check. Unlike do-nothing, this applies when no change is expected: a question whose
  answer is "that isn't on record" still needs an answer (in our experiments, a bare "Done!" passed every such
  case in two suites). With `--judges`, calibrated judges count in this screen and the liar's;
- **a wrong number fails**: the reference answer with every number changed fails at least one
  check. Reported, not blocking: it says whether anything checks the answer's numbers, which is
  where every suite in our experiments was blind.

The screens run the checks against the states written in the case. They do not run the agent.
"""

from __future__ import annotations

import json
import re

from .checks import run_check
from .repo import Evals
from .util import now_iso, write_json

SUCCESS_CLAIM = ("Done. I completed everything you asked: all changes were made and verified "
                 "successfully.")


def screen_case(ev: Evals, case: dict, judges=None) -> dict:
    """`judges`, when given, is a callable (start, end) -> [(check_id, passed)] for the case's
    calibrated judges; the non-answer and liar screens then count their verdicts too."""
    checks = ev.checks_for_case(case, check_type="code")
    start_world = case.get("start_state")
    expected = case.get("expected_end_state") or {}
    exp_world = expected.get("world", start_world) if isinstance(expected, dict) else start_world
    exp_output = expected.get("output") if isinstance(expected, dict) else None

    start = {"world": start_world, "output": None}
    ref_end = {"world": exp_world, "output": exp_output}
    nothing_silent = {"world": start_world, "output": ""}
    nothing_claim = {"world": start_world, "output": SUCCESS_CLAIM}

    prior = case.get("screen") or {}
    result = {
        "human_read": prior.get("human_read"),
        "read_by": prior.get("read_by"),
        "reference_passes": None,
        "donothing_fails": None,
        "claim_sensitive_checks": [],
        "failing_reference_checks": [],
        "notes": [],
        "screened_at": now_iso(),
        "dropped": bool(prior.get("dropped", False)),
        "drop_reason": prior.get("drop_reason"),
    }
    if not checks:
        result["notes"].append("no code checks apply to this case")
        return result

    ref = [run_check(cid, ev.code_check_path(cid), start, ref_end, case) for cid, _ in checks]
    silent = [run_check(cid, ev.code_check_path(cid), start, nothing_silent, case) for cid, _ in checks]
    claim = [run_check(cid, ev.code_check_path(cid), start, nothing_claim, case) for cid, _ in checks]

    errored = [r.id for r in ref + silent + claim if r.passed is None]
    if errored:
        result["notes"].append(f"checks raised during screen: {sorted(set(errored))}")
    result["reference_passes"] = all(r.passed is True for r in ref)
    result["failing_reference_checks"] = [f"{r.id}: {r.detail}" for r in ref if r.passed is not True]

    no_change_expected = _same(exp_world, start_world) and not exp_output
    if no_change_expected:
        result["donothing_fails"] = None
        result["notes"].append("expected end state equals start state: doing nothing is the "
                               "reference, so the do-nothing screen does not apply")
    else:
        result["donothing_fails"] = any(r.passed is False for r in silent)
    result["claim_sensitive_checks"] = [
        s.id for s, c in zip(silent, claim, strict=True) if s.passed is False and c.passed is True
    ]

    def run_all(end):
        return [run_check(cid, ev.code_check_path(cid), start, end, case) for cid, _ in checks]

    def fails(end) -> bool:
        if any(r.passed is False for r in run_all(end)):
            return True
        return bool(judges) and any(v is False for _, v in judges(start, end))

    if exp_output:
        trigger = case.get("trigger") or {}
        ask = trigger.get("text") if isinstance(trigger, dict) else str(trigger)
        non_answers = ["Done!", f"Done. {ask or ''}".strip()]
        result["non_answer_fails"] = all(fails({"world": start_world, "output": o}) for o in non_answers)
        if not result["non_answer_fails"]:
            result["notes"].append("a non-answer ('Done!', or the request echoed back) with nothing changed passes"
                                   + ("" if judges else "; if a judge decides this case, screen with --judges"))
    else:
        result["non_answer_fails"] = None

    variants = (expected.get("output_variants") if isinstance(expected, dict) else None) or []
    result["failing_paraphrases"] = [
        f"variant {i + 1}: {r.id}: {r.detail}" for i, v in enumerate(variants)
        for r in run_all({"world": exp_world, "output": v}) if r.passed is not True]
    if exp_output and not _same(exp_world, start_world):
        result["liar_fails"] = fails({"world": start_world, "output": exp_output})
        if not result["liar_fails"]:
            result["notes"].append("the reference answer with nothing changed passes every check: the "
                                   "suite grades what the agent says, not what it did")
    else:
        result["liar_fails"] = None
    numbered = [o for o in [exp_output, *variants] if isinstance(o, str) and NUMBER.search(o)]
    if numbered:
        result["wrong_number_fails"] = all(
            any(r.passed is False for r in run_all({"world": exp_world, "output": wrong_numbers(o)}))
            for o in numbered)
        if not result["wrong_number_fails"]:
            result["notes"].append("an answer with every number wrong passes: nothing checks the answer's numbers")
    else:
        result["wrong_number_fails"] = None
    if result["claim_sensitive_checks"]:
        result["notes"].append("these checks pass when the agent merely claims success (G10)")
    return result


NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


def wrong_numbers(text: str) -> str:
    """Every number in the text changed, keeping its format: 1,413,000 -> 2,413,001; 14:00 -> 25:11."""
    def bump(m):
        digits = m.group(0)
        out, carry = [], True
        for ch in reversed(digits):
            if ch.isdigit() and carry:
                n = int(ch) + 1
                out.append(str(n % 10))
                carry = n == 10
            else:
                out.append(ch)
        changed = "".join(reversed(out))
        first = next(i for i, ch in enumerate(changed) if ch.isdigit())
        return changed[:first] + str((int(changed[first]) + 1) % 10 or 1) + changed[first + 1:]
    return NUMBER.sub(bump, text)


def _same(a, b) -> bool:
    return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def passes(screen: dict | None) -> bool:
    """Whether a case has cleared every screen and counts toward gated numbers (G8)."""
    if not screen or screen.get("dropped"):
        return False
    if screen.get("human_read") is not True or screen.get("reference_passes") is not True:
        return False
    if (screen.get("claim_sensitive_checks") or screen.get("failing_paraphrases")
            or screen.get("liar_fails") is False or screen.get("non_answer_fails") is False):
        return False
    dn = screen.get("donothing_fails")
    if dn is None:
        return any("doing nothing is the reference" in n for n in screen.get("notes") or [])
    return dn is True


def judge_verdicts(ev: Evals, case: dict):
    """(start, end) -> [(check_id, passed)] for the case's calibrated judges (calls cost money)."""
    from .judging import JudgeRunner
    from .report import judge_states

    states = judge_states(ev)
    runner = JudgeRunner(ev)

    def run(start, end):
        out = []
        for cid, fm in ev.checks_for_case(case, check_type="judge"):
            st = states.get(cid) or {}
            if not st.get("calibrated"):
                continue
            line = runner.line(st["spec"], st["backend"], fm.get("id"), case, start, end,
                               {"run_id": "screen", "case_id": case.get("id"), "trial": 0, "attempt": 0})
            score = line.get("score")
            out.append((cid, score >= st["threshold_or_default"] if score is not None else line.get("passed")))
        return out
    return run


def run_screen(ev: Evals, case_ids: list[str] | None = None, read_by: str | None = None,
               drop: str | None = None, reason: str | None = None, judges: bool = False) -> list[dict]:
    """Screen cases and write each result into the case file's `screen` block."""
    rows = []
    for case in ev.cases():
        cid = case.get("id")
        if case_ids and cid not in case_ids:
            continue
        path = ev.p(case["_path"])
        if drop and cid == drop:
            if not reason:
                raise ValueError("--drop needs --reason: every drop is recorded with why")
            screen = dict(case.get("screen") or {})
            screen.update({"dropped": True, "drop_reason": reason, "dropped_at": now_iso()})
        else:
            screen = screen_case(ev, case, judge_verdicts(ev, case) if judges else None)
            if read_by and (not case_ids or cid in case_ids):
                screen["human_read"] = True
                screen["read_by"] = read_by
        case_out = {k: v for k, v in case.items() if not k.startswith("_")}
        case_out["screen"] = screen
        write_json(path, case_out)
        rows.append({"case": cid, "category": case.get("category"), **screen,
                     "passes": passes(screen)})
    return rows
