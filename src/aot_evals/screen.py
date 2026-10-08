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

The screens run the checks against the states written in the case. They do not run the agent.
"""

from __future__ import annotations

import json

from .checks import run_check
from .repo import Evals
from .util import now_iso, write_json

SUCCESS_CLAIM = ("Done. I completed everything you asked: all changes were made and verified "
                 "successfully.")


def screen_case(ev: Evals, case: dict) -> dict:
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
    if result["claim_sensitive_checks"]:
        result["notes"].append("these checks pass when the agent merely claims success (G10)")
    return result


def _same(a, b) -> bool:
    return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def passes(screen: dict | None) -> bool:
    """Whether a case has cleared every screen and counts toward gated numbers (G8)."""
    if not screen or screen.get("dropped"):
        return False
    if screen.get("human_read") is not True or screen.get("reference_passes") is not True:
        return False
    if screen.get("claim_sensitive_checks"):
        return False
    dn = screen.get("donothing_fails")
    if dn is None:
        return any("doing nothing is the reference" in n for n in screen.get("notes") or [])
    return dn is True


def run_screen(ev: Evals, case_ids: list[str] | None = None, read_by: str | None = None,
               drop: str | None = None, reason: str | None = None) -> list[dict]:
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
            screen = screen_case(ev, case)
            if read_by and (not case_ids or cid in case_ids):
                screen["human_read"] = True
                screen["read_by"] = read_by
        case_out = {k: v for k, v in case.items() if not k.startswith("_")}
        case_out["screen"] = screen
        write_json(path, case_out)
        rows.append({"case": cid, "category": case.get("category"), **screen,
                     "passes": passes(screen)})
    return rows
