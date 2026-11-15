"""The evidence an eval's numbers rest on, beyond its spec (docs/method.md): whether each
run's manifest records the conditions it ran under and kept the agent away from the answers,
whether every (case, trial) it planned has a final attempt, whether its cases were screened and
committed, whether its checks grade the world rather than the agent's claim, whether the
coverage list came from outside the cases, and whether it ran enough trials.

`gates` lists them for report.json, keyed by part, each `{id, status, detail}` with a stable id
a fixture can trigger alone:

- agent_contract: `manifest` (with its isolation checks), `trials_complete`;
- design: `screened`, `committed`, `coverage_list`;
- measurement: `independent_reference`, `k`.

`status` is "pass" or "fail", or null when there is nothing to judge (no run to read, no
bug-finding set to cover). They grey nothing by themselves: θ̂ already leaves out the cases
`screened` and `committed` list (rule 17), and a report on runs that fail `manifest` or
`trials_complete` says so beside the number.
"""

from __future__ import annotations

from collections import defaultdict

from .checks import declares_agent_report
from .screen import passes as screen_passes
from .util import git_untracked_or_modified

MANIFEST_CONDITION_FIELDS = ("agent_commit", "evals_commit", "harness", "k")
MIN_K = 3  # a baseline needs k >= 3 to measure the variance within a case (rule 16)


def manifest_problems(m: dict) -> list[str]:
    """What a run's manifest fails to record, and whether the agent may have seen the answers."""
    problems = [f"run {m.get('run_id')}: manifest has no {f}" for f in MANIFEST_CONDITION_FIELDS
                if not m.get(f)]
    agent = m.get("agent") or {}
    if not (agent.get("model_ids") or agent.get("model_ids_observed")):
        problems.append(f"run {m.get('run_id')}: no model id per call site")
    exposure = m.get("eval_exposure") or {}
    # Python rewrites a code check's bytecode cache when it loads an edited check: not an answer
    changed = [p for p in exposure.get("changed") or [] if "__pycache__/" not in p]
    if changed:
        problems.append(f"run {m.get('run_id')}: eval files changed during the run "
                        f"({', '.join(changed[:3])}); re-run with invoke.isolate: true")
    if exposure.get("mentioned"):
        first = exposure["mentioned"][0]
        problems.append(f"run {m.get('run_id')}: the agent's output names eval files in "
                        f"{len(exposure['mentioned'])} attempt(s), e.g. {first['case_id']}: "
                        f"{', '.join(first['files'])}; it may have read the answers. Re-run with "
                        "invoke.isolate: true")
    return problems


def trial_completeness(ev, m: dict) -> list[str]:
    """(case, trial) pairs the run planned that have no final attempt."""
    recs = [r for r in ev.run_records(m["run_id"]) if r.get("kind") == "attempt"]
    finals = {(r["case_id"], r["trial"]) for r in recs if r.get("final")}
    missing = [(c, t) for c in m.get("case_set", {}).get("ids") or [] for t in range(m.get("k", 0))
               if (c, t) not in finals]
    if missing:
        return [f"run {m['run_id']}: {len(missing)} (case, trial) pairs have no final attempt, "
                f"e.g. {missing[0]}"]
    return []


def attempt_gaps(ev, m: dict) -> list[str]:
    """Trials whose attempt numbers skip one: a retry was lost from the record."""
    by_trial: dict[tuple, list[int]] = defaultdict(list)
    for r in ev.run_records(m["run_id"]):
        if r.get("kind") == "attempt":
            by_trial[(r.get("case_id"), r.get("trial"))].append(r.get("attempt"))
    return [f"run {m['run_id']}: {cid} trial {t}: attempts {sorted(a)} are not contiguous from 0"
            for (cid, t), a in by_trial.items() if sorted(a) != list(range(len(a)))]


def untracked_cases(ev) -> list[str]:
    """Case files git doesn't have as committed (untracked, or with uncommitted edits), relative
    to the repository root: they stay out of every number (rule 17)."""
    return git_untracked_or_modified(ev.repo_root, str(ev.p("cases").relative_to(ev.repo_root)))


def uncommitted_case_ids(ev, cases: dict[str, dict], untracked: set[str] | None = None) -> set[str]:
    """The ids of `cases` whose file is untracked or has uncommitted edits."""
    untracked = set(untracked_cases(ev)) if untracked is None else untracked
    return {cid for cid, c in cases.items()
            if str((ev.p(c["_path"])).relative_to(ev.repo_root)) in untracked}


def claim_trusting_checks(ev) -> list[str]:
    """Counted code checks that declare USES_AGENT_REPORT, or that a case's screen found pass on a
    bare success claim with nothing changed (`independent_reference`)."""
    counted = {fm["check"] for fm in ev.failure_modes() if isinstance(fm.get("check"), str)}
    declared = {c for c in counted if ev.check_type(c) == "code" and declares_agent_report(ev.code_check_path(c))}
    sensitive = {c for case in ev.cases(include_dropped=False)
                 for c in (case.get("screen") or {}).get("claim_sensitive_checks") or [] if c in counted}
    return sorted(declared | sensitive)


def _gate(gid: str, problems: list[str] | None, ok: str) -> dict:
    """problems None: nothing to judge (status null)."""
    if problems is None:
        return {"id": gid, "status": None, "detail": ok}
    return {"id": gid, "status": "fail" if problems else "pass", "detail": "; ".join(problems) or ok}


def gates(ev, manifests: list[dict], cases: dict[str, dict] | None = None,
          untracked: set[str] | None = None) -> dict[str, list[dict]]:
    """The evidence gates on these runs (the reported runs and any candidate's), keyed by part."""
    from .coverage import coverage_path, list_problems

    if cases is None:
        cases = {c["id"]: c for c in ev.cases() if c.get("id")}
    none = "no run to read" if not manifests else None
    in_runs: set[str] = set()
    adhoc: set[str] = set()
    for m in manifests:
        for r in ev.run_records(m["run_id"]):
            if r.get("kind") == "attempt" and r.get("case_id"):
                (in_runs if r["case_id"] in cases else adhoc).add(r["case_id"])

    out: dict[str, list[dict]] = {}
    # agent_contract
    probs = [p for m in manifests for p in manifest_problems(m)]
    out["agent_contract"] = [
        _gate("manifest", None if none else probs, none or
              "every run records its conditions, and the eval files were untouched and unnamed"),
        _gate("trials_complete", None if none else
              [p for m in manifests for p in trial_completeness(ev, m) + attempt_gaps(ev, m)],
              none or "every planned (case, trial) has a final attempt"),
    ]
    # design
    dropped = sorted(cid for cid, c in cases.items() if (c.get("screen") or {}).get("dropped"))
    unscreened = sorted(c for c in in_runs if not screen_passes(cases[c].get("screen"))
                        and c not in dropped)
    note = f"; dropped, left out of every run: {dropped[:10]}" if dropped else ""
    screened = (None if none else
                [f"{len(unscreened)} unscreened case(s) in the runs, left out of every number: "
                 f"{unscreened[:10]}{note}"] if unscreened else [])
    uncommitted = sorted(uncommitted_case_ids(ev, {c: cases[c] for c in in_runs}, untracked))
    committed = None if none else (
        ([f"uncommitted or edited case file(s), left out of every number: {uncommitted[:10]}"]
         if uncommitted else [])
        + ([f"attempts for cases the eval doesn't have: {sorted(adhoc)[:10]}"] if adhoc else []))
    bf = ev.spec().part("design").get("bug_finding_set")
    if not bf and not coverage_path(ev).exists():
        cov = _gate("coverage_list", None, "no bug-finding set, so no coverage list to read")
    else:
        cov = _gate("coverage_list", list_problems(ev),
                    f"{coverage_path(ev).name}: an external list, committed before the first case")
    out["design"] = [
        _gate("screened", screened, none or ("every case in the runs passed its screen" + note)),
        _gate("committed", committed, none or "every case in the runs is committed as it ran"),
        cov,
    ]
    # measurement
    trusting = claim_trusting_checks(ev)
    low = [f"run {m['run_id']} ({m.get('purpose')}): k = {m.get('k')}" for m in manifests
           if m.get("purpose") != "smoke" and not (isinstance(m.get("k"), int) and m["k"] >= MIN_K)]
    out["measurement"] = [
        _gate("independent_reference",
              [f"counted checks that trust the agent's report: {trusting}"] if trusting else [],
              "no counted check passes on a bare success claim"),
        _gate("k", None if none else (
            [f"{'; '.join(low)}: k >= {MIN_K} measures the variance within a case (rule 16)"] if low else []),
            none or f"every run has k >= {MIN_K}"),
    ]
    return out


def failing(g: dict[str, list[dict]]) -> set[str]:
    """The ids of the gates that fail."""
    return {x["id"] for part in g.values() for x in part if x["status"] == "fail"}
