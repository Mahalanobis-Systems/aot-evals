"""Running judge checks on run attempts: during a run, or afterwards (`aot-evals judge apply`).

A judge check line is a `kind: check` line with `type: judge`, plus the backend, model, judge
version and hash, the score P(pass), the threshold used, and the judge's cost. The verdict is
recorded whether or not the judge is calibrated; the report decides whether it counts (G3).
"""

from __future__ import annotations

from .calibrate import is_current, load_calibration, threshold_for
from .judges import JudgeSpec, build_input, credentials_missing, judge, load_spec
from .repo import Evals
from .util import append_jsonl, load_json


class JudgeRunner:
    def __init__(self, ev: Evals, log=print, enabled: bool = True):
        self.ev = ev
        self.log = log
        self.enabled = enabled
        self._specs: dict[str, JudgeSpec | None] = {}
        self._warned: set[str] = set()

    def spec(self, check_id: str) -> JudgeSpec | None:
        if check_id not in self._specs:
            path = self.ev.judge_check_path(check_id)
            try:
                s = load_spec(path)
                self._specs[check_id] = None if s.problems() else s
                if s.problems():
                    self._warn(check_id, f"judge {check_id} skipped: {s.problems()[0]}")
            except Exception as e:  # a broken spec is reported, never fatal to a run
                self._specs[check_id] = None
                self._warn(check_id, f"judge {check_id} skipped: {e}")
        return self._specs[check_id]

    def _warn(self, key: str, msg: str) -> None:
        if key not in self._warned:
            self._warned.add(key)
            self.log(f"warning: {msg}")

    def lines(self, case: dict, start: dict, end: dict, ids: dict) -> list[dict]:
        if not self.enabled:
            return []
        out = []
        for cid, fm in self.ev.checks_for_case(case, check_type="judge"):
            spec = self.spec(cid)
            if spec is None:
                continue
            backend = spec.primary
            missing = credentials_missing(spec.backends[backend])
            if missing:
                self._warn(cid + "|cred", f"judge {cid} skipped: {missing} is not set")
                continue
            out.append(self.line(spec, backend, fm.get("id"), case, start, end, ids))
        return out

    def line(self, spec: JudgeSpec, backend: str, failure_mode: str | None, case: dict, start: dict,
             end: dict, ids: dict) -> dict:
        cal = load_calibration(self.ev, spec)
        threshold = threshold_for(cal, backend) if is_current(self.ev, spec, cal) else None
        j = judge(spec, backend, build_input(spec, case, start, end))
        return {"kind": "check", **ids, "check_id": spec.id, "failure_mode": failure_mode,
                "type": "judge", "passed": j.passed(threshold), "score": j.score, "threshold": threshold,
                "backend": backend, "judge_model": j.model, "judge_family": j.family,
                "judge_version": spec.version, "judge_sha": spec.sha(),
                "cost_usd": j.cost_usd, "latency_ms": j.latency_ms,
                "detail": j.error or (j.reasoning or "")[:2000]}


def apply_to_run(ev: Evals, check_id: str, run_id: str, backend: str | None = None, log=print) -> dict:
    """Judge every final ok attempt of a past run that the judge applies to. Skips attempts that
    already have a line from this judge version and backend."""
    jr = JudgeRunner(ev, log=log)
    spec = jr.spec(check_id)
    if spec is None:
        raise ValueError(f"judge {check_id} is missing or invalid; see aot-evals validate")
    backend = backend or spec.primary
    missing = credentials_missing(spec.backends[backend])
    if missing:
        raise ValueError(f"{missing} is not set")
    records = ev.run_records(run_id)
    if not records:
        raise ValueError(f"run {run_id} has no records")
    done = {(r["case_id"], r["trial"], r["attempt"]) for r in records
            if r.get("kind") == "check" and r.get("check_id") == check_id
            and r.get("judge_sha") == spec.sha() and r.get("backend") == backend}
    cases = {c["id"]: c for c in ev.cases() if c.get("id")}
    path = ev.p("runs", run_id, "outcomes.jsonl")
    n = skipped = 0
    for a in records:
        if a.get("kind") != "attempt" or not a.get("final") or a.get("outcome") != "ok":
            continue
        case = cases.get(a["case_id"])
        if case is None or not any(cid == check_id for cid, _ in ev.checks_for_case(case, check_type="judge")):
            continue
        key = (a["case_id"], a["trial"], a["attempt"])
        if key in done:
            skipped += 1
            continue
        raw = load_json(ev.p("runs", run_id, "raw", f"{a['case_id']}.t{a['trial']}.a{a['attempt']}.json"))
        if raw is None:
            log(f"warning: no raw item for {key}; the run predates judge support or raw/ was cleaned")
            continue
        fm = next((f.get("id") for cid, f in ev.checks_for_case(case, check_type="judge") if cid == check_id), None)
        line = jr.line(spec, backend, fm, case, {"world": raw.get("start_world"), "output": None},
                       {"world": raw.get("end_world"), "output": raw.get("output")},
                       {"run_id": run_id, "case_id": a["case_id"], "trial": a["trial"], "attempt": a["attempt"]})
        append_jsonl(path, line)
        n += 1
    return {"judged": n, "already_judged": skipped}
