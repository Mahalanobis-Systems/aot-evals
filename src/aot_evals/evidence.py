"""The evidence a 2.0 eval's numbers rest on, beyond its spec (docs/v2-design.md §6): whether each
run's manifest records the conditions it ran under, whether every (case, trial) it planned has a
final attempt, whether the cases were committed, and whether the agent could see them.

These are the 1.x report gates that survive into 2.0 (G1 manifest integrity, G13 trial
completeness, the committed-cases half of G12, and the isolation checks of G1); report_v2 lists
them under `gates`, keyed by part.
"""

from __future__ import annotations

from .util import git_untracked_or_modified

MANIFEST_CONDITION_FIELDS = ("agent_commit", "evals_commit", "harness", "k")


def manifest_problems(m: dict) -> list[str]:
    """What a run's manifest fails to record, and whether the agent may have seen the answers."""
    problems = [f"run {m.get('run_id')}: manifest has no {f}" for f in MANIFEST_CONDITION_FIELDS
                if not m.get(f)]
    agent = m.get("agent") or {}
    if not (agent.get("model_ids") or agent.get("model_ids_observed")):
        problems.append(f"run {m.get('run_id')}: no model id per call site")
    exposure = m.get("eval_exposure") or {}
    if exposure.get("changed"):
        problems.append(f"run {m.get('run_id')}: eval files changed during the run "
                        f"({', '.join(exposure['changed'][:3])}); re-run with invoke.isolate: true")
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


def untracked_cases(ev) -> list[str]:
    """Case files git doesn't have as committed: they stay out of every number (rule 17)."""
    return git_untracked_or_modified(ev.repo_root, str(ev.p("cases").relative_to(ev.repo_root)))
