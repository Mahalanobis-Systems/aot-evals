"""Run the suite: k trials per case, every attempt recorded (C12 baseline; also smoke and
candidate runs).

`runs/<run-id>/outcomes.jsonl` is never aggregated at write time (docs/method.md §3). It holds two kinds
of line:

- `"kind": "attempt"`: one per (case, trial, attempt), with the outcome code and the plane-B
  counters. Retries and operational failures are written like any other attempt (G13).
- `"kind": "check"`: one per (case, check, trial, attempt), with the binary verdict. Kept on
  separate lines so plane-B counters are recorded once per attempt, and so a judge calibrated
  later can append its verdicts without rewriting the file.

`runs/<run-id>/manifest.json` is the condition record. `runs/<run-id>/raw/` holds the agent's
stdout/stderr per attempt; it is git-ignored, and `trace_ref` points into it.
"""

from __future__ import annotations

import json
import platform
import time
from pathlib import Path

from . import __version__, isolation
from .checks import run_check
from .executor import AttemptResult, Executor
from .judging import JudgeRunner
from .outcomes import Outcome
from .repo import Evals
from .util import append_jsonl, git_commit_info, now_iso, run_id_stamp, sha256_file, sha256_tree, write_json

PURPOSES = ("smoke", "baseline", "candidate", "drift", "screen")


def state_diff(before, after, path: str = "", out: list[str] | None = None, limit: int = 50) -> list[str]:
    """A short, human-readable list of what changed between two JSON values."""
    out = [] if out is None else out
    if len(out) >= limit:
        return out
    if isinstance(before, dict) and isinstance(after, dict):
        for k in sorted(set(before) | set(after), key=str):
            p = f"{path}.{k}" if path else str(k)
            if k not in before:
                out.append(f"+ {p} = {_short(after[k])}")
            elif k not in after:
                out.append(f"- {p}")
            else:
                state_diff(before[k], after[k], p, out, limit)
    elif isinstance(before, list) and isinstance(after, list):
        if before != after:
            added = [x for x in after if x not in before]
            removed = [x for x in before if x not in after]
            for x in added[:10]:
                out.append(f"+ {path}[] {_short(x)}")
            for x in removed[:10]:
                out.append(f"- {path}[] {_short(x)}")
            if not added and not removed:
                out.append(f"~ {path} reordered")
    elif before != after:
        out.append(f"~ {path or '(root)'}: {_short(before)} -> {_short(after)}")
    return out[:limit]


def _short(v, n: int = 120) -> str:
    s = json.dumps(v, ensure_ascii=False, sort_keys=True)
    return s if len(s) <= n else s[: n - 1] + "…"


def select_cases(ev: Evals, case_ids: list[str] | None, categories: list[str] | None) -> list[dict]:
    cases = ev.cases(include_dropped=False)
    if case_ids:
        cases = [c for c in cases if c.get("id") in set(case_ids)]
    if categories:
        cases = [c for c in cases if c.get("category") in set(categories)]
    return cases


def build_manifest(ev: Evals, run_id: str, purpose: str, k: int, cases: list[dict],
                   variable: str | None, label: str | None, executor: Executor,
                   agent_cwd: Path | None = None) -> dict:
    agent = ev.agent()
    case_files = [ev.p(c["_path"]) for c in cases if "_path" in c]
    checks = {}
    for c in cases:
        for cid, _ in ev.checks_for_case(c, check_type=None):
            for path in (ev.code_check_path(cid), ev.judge_check_path(cid)):
                if path.exists():
                    checks[cid] = sha256_file(path)[:16]
    agent_git = git_commit_info(agent_cwd or executor.cwd, exclude=ev.evals_dir)
    evals_git = git_commit_info(ev.repo_root, pathspec=str(ev.root.relative_to(ev.repo_root)))
    return {
        "schema": "aot-evals/run-manifest@1",
        "run_id": run_id,
        "purpose": purpose,
        "label": label,
        "declared_variable": variable,
        "started": now_iso(),
        "finished": None,
        "agent": {"id": agent.get("id"), "model_ids": dict(agent.get("models") or {}),
                  "model_ids_observed": {}},
        "agent_commit": agent_git["commit"],
        "agent_dirty": agent_git["dirty"],
        "evals_commit": evals_git["commit"],
        "evals_dirty": evals_git["dirty"],
        "harness": agent.get("harness"),
        "k": k,
        "window": (agent.get("stable_window") or {}).get("since"),
        "judge_backends": _judge_backends(ev, cases),
        "simulator": agent.get("simulator"),
        "fakes_sha256": sha256_tree(ev.p("env")),
        "case_set": {"ids": [c.get("id") for c in cases],
                     "files": {c.get("id"): sha256_file(ev.p(c["_path"]))[:16] for c in cases if "_path" in c},
                     "sha256": _hash_files(case_files, ev.root)},
        "checks": checks,
        "invoke": {**{key: executor.invoke.get(key) for key in
                      ("command", "cwd", "timeout", "setup", "reset", "reset_scope", "seed",
                       "observe", "max_attempts", "isolate")},
                   # env values may be secrets: record the names and a hash, never the values
                   "env_keys": sorted(executor.invoke.get("env") or {}),
                   "env_sha": _env_sha(executor.invoke.get("env"))},
        "tool": {"aot_evals": __version__, "python": platform.python_version()},
        "cost_usd": None,
        "counts": None,
    }


def _env_sha(env: dict | None) -> str | None:
    import hashlib

    if not env:
        return None
    return hashlib.sha256(json.dumps(env, sort_keys=True, default=str).encode()).hexdigest()[:16]


def _judge_backends(ev: Evals, cases: list[dict]) -> list[dict]:
    """The condition record for every judge that will run: backend, model, family, version."""
    from .calibrate import is_current, load_calibration
    from .judges import load_spec

    out, seen = [], set()
    for c in cases:
        for cid, _ in ev.checks_for_case(c, check_type="judge"):
            if cid in seen:
                continue
            seen.add(cid)
            try:
                spec = load_spec(ev.judge_check_path(cid))
            except Exception:
                continue
            b = spec.backends.get(spec.primary or "", {})
            cal = load_calibration(ev, spec)
            out.append({"check": cid, "backend": spec.primary, "type": b.get("type"), "model": b.get("model"),
                        "family": b.get("family"), "version": spec.version, "judge_sha": spec.sha(),
                        "calibration": (cal or {}).get("status") if is_current(ev, spec, cal) else "uncalibrated"})
    return out


def _hash_files(paths: list[Path], base: Path) -> str | None:
    import hashlib

    if not paths:
        return None
    h = hashlib.sha256()
    for p in sorted(paths):
        h.update(str(p.relative_to(base)).encode())
        h.update(b"\0")
        h.update(p.read_bytes())
    return h.hexdigest()


def run(ev: Evals, *, purpose: str, k: int, case_ids: list[str] | None = None,
        categories: list[str] | None = None, variable: str | None = None,
        label: str | None = None, adhoc_question: str | None = None,
        log=print, forced: list[str] | None = None, judges: bool = True,
        pause_every: int = 0, pause_seconds: float = 900, stop_after: int = 5,
        sleep=time.sleep) -> dict:
    """Run every case k times. `pause_every` N cases, wait `pause_seconds` (pacing for a
    rate-limited runtime). After `stop_after` cases in a row end in an operational failure
    (timeout, provider error, ...), stop: a provider that has gone silent turns every remaining
    case into a timeout. A stopped run keeps its records but is never `finished`."""
    if purpose not in PURPOSES:
        raise ValueError(f"purpose must be one of {PURPOSES}")
    agent = ev.agent()
    invoke = agent.get("invoke") or {}
    Executor(invoke, ev.repo_root)  # validate agent.yaml before copying anything
    isolated = isolation.make_copy(ev, purpose) if invoke.get("isolate") else None
    try:
        return _run(ev, agent, isolated, purpose=purpose, k=k, case_ids=case_ids,
                    categories=categories, variable=variable, label=label,
                    adhoc_question=adhoc_question, log=log, forced=forced, judges=judges,
                    pause_every=pause_every, pause_seconds=pause_seconds, stop_after=stop_after,
                    sleep=sleep)
    finally:
        if isolated:
            isolation.remove_copy(isolated)


def _run(ev: Evals, agent: dict, isolated: Path | None, *, purpose: str, k: int,
         case_ids, categories, variable, label, adhoc_question, log, forced, judges,
         pause_every, pause_seconds, stop_after, sleep) -> dict:
    invoke = agent.get("invoke") or {}
    executor = Executor(invoke, isolated or ev.repo_root)
    agent_cwd = (ev.repo_root / invoke.get("cwd", ".")).resolve()
    max_attempts = int(invoke.get("max_attempts", 2))

    if adhoc_question is not None:
        cases = [{"id": "adhoc", "category": None, "set": None,
                  "trigger": {"type": "message", "text": adhoc_question}}]
    else:
        cases = select_cases(ev, case_ids, categories)
    if not cases:
        raise ValueError("no cases to run (all dropped, filtered out, or none authored); "
                         "use --question for a smoke run before cases exist")

    run_id = f"{run_id_stamp()}-{purpose}" + (f"-{label}" if label else "")
    run_dir = ev.p("runs", run_id)
    (run_dir / "raw").mkdir(parents=True, exist_ok=True)
    manifest = build_manifest(ev, run_id, purpose, k, [c for c in cases if "_path" in c],
                              variable, label, executor, agent_cwd)
    if isolated:
        log(f"  isolated: the agent runs from {isolated}, a copy without evals/")
    answers_before = isolation.answer_files(ev)
    all_case_ids = [c.get("id") for c in ev.cases() if c.get("id")]
    mentioned: list[dict] = []
    manifest["forced_past_gates"] = forced or []
    write_json(run_dir / "manifest.json", manifest)
    outcomes_path = run_dir / "outcomes.jsonl"
    outcomes_path.touch()

    judge_runner = JudgeRunner(ev, log=log, enabled=judges)
    hook = executor.setup()
    if hook and not hook.ok:
        log(f"warning: setup hook failed: {hook.detail}")

    total_cost = 0.0
    any_cost = False
    counts: dict[str, int] = {}
    observed_models: dict[str, set] = {}

    streak, done, stopped = 0, 0, None
    for trial in range(k):
        if stopped:
            break
        for case in cases:
            if stopped:
                break
            for attempt in range(max_attempts):
                rec, checks, res = _one_attempt(ev, executor, case, trial, attempt, run_id, run_dir,
                                                judge_runner)
                retry = (res is not None and res.outcome.retryable and attempt + 1 < max_attempts)
                rec["final"] = not retry
                seen = isolation.mentions(ev, res and f"{res.stdout}\n{res.stderr}", all_case_ids)
                if seen:
                    rec["eval_mentions"] = seen
                    mentioned.append({"case_id": case.get("id"), "trial": trial, "attempt": attempt,
                                      "files": seen})
                    log(f"  warning: the agent's output names eval files: {', '.join(seen)}")
                append_jsonl(outcomes_path, rec)
                for c in checks:
                    append_jsonl(outcomes_path, c)
                key = rec["outcome"] or "instrument_error"
                counts[key] = counts.get(key, 0) + 1
                if rec["cost_usd"] is not None:
                    total_cost += rec["cost_usd"]
                    any_cost = True
                for site, model in (rec.get("model_ids") or {}).items():
                    observed_models.setdefault(site, set()).add(model)
                mark = {True: "pass", False: "FAIL", None: rec["outcome"] or "instrument_error"}[rec["passed"]]
                log(f"  trial {trial} {case.get('id')} attempt {attempt}: {mark}")
                if not retry:
                    break
            streak = streak + 1 if rec["outcome"] not in (None, Outcome.OK.value) else 0
            done += 1
            if executor.reset_scope == "case":
                h = executor.reset()
                if h and not h.ok:
                    log(f"warning: reset hook failed: {h.detail}")
            if stop_after and streak >= stop_after:
                stopped = (f"{streak} cases in a row ended in an operational failure (last: "
                           f"{rec['outcome']}); is the agent's model or provider answering?")
                log(f"stopped: {stopped}")
            elif pause_every and done % pause_every == 0 and done < k * len(cases):
                log(f"  pausing {pause_seconds:g}s after {done} cases (--pause-every {pause_every})")
                sleep(pause_seconds)
    if executor.reset_scope == "run":
        h = executor.reset()
        if h and not h.ok:
            log(f"warning: reset hook failed: {h.detail}")

    manifest["eval_exposure"] = {"isolated": bool(isolated),
                                 "changed": isolation.changed(answers_before, isolation.answer_files(ev)),
                                 "mentioned": mentioned}
    if stopped:
        manifest["stopped"] = {"reason": stopped, "at": now_iso(), "cases_done": done}
    else:
        manifest["finished"] = now_iso()
    manifest["cost_usd"] = total_cost if any_cost else None
    manifest["counts"] = counts
    manifest["agent"]["model_ids_observed"] = {s: sorted(m) for s, m in observed_models.items()}
    write_json(run_dir / "manifest.json", manifest)
    return manifest


def _one_attempt(ev: Evals, executor: Executor, case: dict, trial: int, attempt: int,
                 run_id: str, run_dir: Path, judge_runner: JudgeRunner | None = None
                 ) -> tuple[dict, list[dict], AttemptResult | None]:
    base = {"kind": "attempt", "run_id": run_id, "case_id": case.get("id"),
            "category": case.get("category"), "set": case.get("set"), "trial": trial,
            "attempt": attempt, "started": now_iso()}
    empty_ops = {"cost_usd": None, "tokens_input": None, "tokens_output": None,
                 "tokens_cached": None, "latency_ms": None, "tool_calls": None, "retries": None,
                 "killed": False, "model": None, "model_ids": {}, "judge_model": None}

    adhoc = "_path" not in case  # a smoke trigger with no case: nothing to seed or observe
    observes = executor.observes and not adhoc
    if not adhoc:
        h = executor.seed(case)
        if h and not h.ok:
            return ({**base, **empty_ops, "outcome": None, "error": "",
                     "instrument_error": f"seed failed: {h.detail}", "passed": None,
                     "state_diff": None, "trace_ref": None}, [], None)

    if observes:
        start_world, why = executor.observe()
        if start_world is None:
            return ({**base, **empty_ops, "outcome": None, "error": "",
                     "instrument_error": f"observe (before) failed: {why}", "passed": None,
                     "state_diff": None, "trace_ref": None}, [], None)
    else:
        start_world = case.get("start_state")

    res = executor.run(executor.payload(case, trial, attempt))
    raw_name = f"{case.get('id')}.t{trial}.a{attempt}.txt"
    (run_dir / "raw" / raw_name).write_text(
        f"# outcome: {res.outcome}\n# error: {res.error}\n# --- stdout\n{res.stdout}\n# --- stderr\n{res.stderr}\n")
    trace_ref = res.trace_id or f"raw/{raw_name}"

    models = res.model_ids or {}
    rec = {**base,
           "outcome": str(res.outcome), "error": res.error, "instrument_error": None,
           "passed": None,
           "cost_usd": res.cost_usd, "tokens_input": res.tokens_input,
           "tokens_output": res.tokens_output, "tokens_cached": res.tokens_cached,
           "latency_ms": round(res.latency_ms, 1), "tool_calls": res.tool_calls,
           "retries": res.agent_retries, "killed": res.killed or res.outcome is Outcome.TIMEOUT,
           "model": next(iter(models.values()), executor.model or None), "model_ids": models,
           "judge_model": None, "state_diff": None, "trace_ref": trace_ref}

    if not res.outcome.scorable:
        return rec, [], res  # plane-B data only; never scored (G13)

    if observes:
        end_world, why = executor.observe()
        if end_world is None:
            rec["instrument_error"] = f"observe (after) failed: {why}"
            return rec, [], res
    else:
        end_world = None
    rec["state_diff"] = "\n".join(state_diff(start_world, end_world)) if observes else None

    start = {"world": start_world, "output": None}
    end = {"world": end_world, "output": res.answer}
    # What judges need to grade this attempt later (judge apply, label queue). Git-ignored.
    write_json(run_dir / "raw" / f"{case.get('id')}.t{trial}.a{attempt}.json",
               {"output": res.answer, "start_world": start_world, "end_world": end_world})
    ids = {"run_id": run_id, "case_id": case.get("id"), "trial": trial, "attempt": attempt}
    check_lines = []
    verdicts = []
    for cid, fm in ev.checks_for_case(case, check_type="code"):
        cr = run_check(cid, ev.code_check_path(cid), start, end, case)
        verdicts.append(cr.passed)
        check_lines.append({"kind": "check", **ids, "check_id": cid,
                            "failure_mode": fm.get("id"), "type": "code",
                            "passed": cr.passed, "detail": cr.detail})
    judge_lines = judge_runner.lines(case, start, end, ids) if (judge_runner and not adhoc) else []
    check_lines += judge_lines
    # `passed` here is the code checks' verdict. Judge verdicts are on their own lines; the report
    # decides which judges count (calibrated ones only, G3) and recomputes each trial's pass.
    if any(v is None for v in verdicts):
        rec["instrument_error"] = "a check raised; see its check line"
    elif not adhoc:
        rec["passed"] = all(verdicts) if verdicts else None
        if not verdicts and not ev.checks_for_case(case, check_type="judge"):
            rec["instrument_error"] = "no checks apply to this case"
    return rec, check_lines, res
