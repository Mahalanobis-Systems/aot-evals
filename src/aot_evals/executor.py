"""Run the agent under test: the agent contract (references/agent-contract.md).

The case goes to the agent's command as one JSON object on stdin; the agent prints one JSON
object on stdout. stdin carries `question`, `context`, `model`, `timeout`, `case_id`, `trial`,
and the rest of the case: `trigger`, `inputs`, `start_state`, `followups`, `attempt`.

stdout: `answer`, optional `usage.tokens_input` / `usage.tokens_output` /
`usage.cost`, `outcome`, `error`. Also read when present: `usage.tokens_cached`,
`usage.tool_calls`, `usage.retries`, `model_ids` (per call site), `trace_id`.

Beside `setup`/`reset`, two optional hooks make state-diff grading possible:
`seed` (per case, case JSON on stdin) puts the world into the case's start state, and
`observe` prints the world as JSON. Checks grade what `observe` returns, never what the agent
says it did (G10).
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from .outcomes import Outcome

# bin/aot-evals runs this package inside an ephemeral uv environment, which prepends that
# environment to PATH and sets VIRTUAL_ENV. The agent must run in the team's own environment,
# so the wrapper saves the originals and they are restored here.
_RESTORE = {"PATH": "AOT_EVALS_ORIG_PATH", "VIRTUAL_ENV": "AOT_EVALS_ORIG_VIRTUAL_ENV",
            "PYTHONPATH": "AOT_EVALS_ORIG_PYTHONPATH"}


def agent_env(extra: dict | None = None) -> dict[str, str]:
    env = dict(os.environ)
    for var, saved in _RESTORE.items():
        if saved in env:
            original = env.pop(saved)
            if original:
                env[var] = original
            else:
                env.pop(var, None)
    for k in ("UV_RUN_RECURSION_DEPTH", "AOT_EVALS_ROOT"):
        env.pop(k, None)
    env.update({k: str(v) for k, v in (extra or {}).items()})
    return env


def _argv(command) -> list[str]:
    if isinstance(command, str):
        return shlex.split(command)
    return [str(x) for x in command]


def _parse_json_stdout(stdout: str) -> dict | None:
    start = stdout.find("{")
    if start == -1:
        return None
    try:
        obj, _ = json.JSONDecoder().raw_decode(stdout[start:])
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None


@dataclass
class AttemptResult:
    outcome: Outcome
    error: str
    answer: str | None
    latency_ms: float
    cost_usd: float | None = None
    tokens_input: int | None = None
    tokens_output: int | None = None
    tokens_cached: int | None = None
    tool_calls: int | None = None
    agent_retries: int | None = None
    model_ids: dict = field(default_factory=dict)
    trace_id: str | None = None
    killed: bool = False
    stdout: str = ""
    stderr: str = ""


@dataclass
class HookResult:
    ok: bool
    stdout: str
    detail: str


class Executor:
    def __init__(self, invoke: dict, repo_root: Path):
        if not invoke or not invoke.get("command"):
            raise ValueError("agent.yaml: invoke.command is required")
        self.invoke = invoke
        self.command = _argv(invoke["command"])
        self.cwd = (repo_root / invoke.get("cwd", ".")).resolve()
        self.timeout = int(invoke.get("timeout", 60))
        self.hook_timeout = int(invoke.get("hook_timeout", max(self.timeout, 60)))
        self.reset_scope = invoke.get("reset_scope", "case")
        if self.reset_scope not in ("case", "run"):
            raise ValueError("agent.yaml: invoke.reset_scope must be 'case' or 'run'")
        self.env = agent_env(invoke.get("env"))
        self.model = str(invoke.get("model") or "")
        self._setup_ran = False

    # ---- hooks -----------------------------------------------------------------------------

    def _hook(self, name: str, stdin: str | None = None) -> HookResult | None:
        cmd = self.invoke.get(name)
        if not cmd:
            return None
        try:
            r = subprocess.run(cmd if isinstance(cmd, str) else shlex.join(_argv(cmd)),
                               shell=True, cwd=str(self.cwd), input=stdin, capture_output=True,
                               text=True, timeout=self.hook_timeout, env=self.env)
        except subprocess.TimeoutExpired:
            return HookResult(False, "", f"{name} timed out after {self.hook_timeout}s")
        if r.returncode != 0:
            return HookResult(False, r.stdout, f"{name} exited {r.returncode}: {r.stderr.strip()[:300]}")
        return HookResult(True, r.stdout, "")

    def setup(self) -> HookResult | None:
        if self._setup_ran:
            return None
        self._setup_ran = True
        return self._hook("setup")

    def reset(self) -> HookResult | None:
        return self._hook("reset")

    def seed(self, case: dict) -> HookResult | None:
        return self._hook("seed", json.dumps(_public(case)))

    def observe(self) -> tuple[dict | list | None, str]:
        """The world as JSON, or (None, reason) when it cannot be observed."""
        h = self._hook("observe")
        if h is None:
            return None, "no observe hook"
        if not h.ok:
            return None, h.detail
        try:
            return json.loads(h.stdout), ""
        except json.JSONDecodeError:
            return None, "observe did not print JSON"

    @property
    def observes(self) -> bool:
        return bool(self.invoke.get("observe"))

    # ---- the agent -------------------------------------------------------------------------

    def payload(self, case: dict, trial: int, attempt: int) -> dict:
        trigger = case.get("trigger") or {}
        question = trigger.get("text") if isinstance(trigger, dict) else str(trigger)
        return {
            "question": question or "",
            "context": [],
            "model": self.model,
            "timeout": self.timeout,
            "case_id": case.get("id"),
            "trial": str(trial),
            "attempt": attempt,
            "trigger": trigger,
            "inputs": case.get("inputs") or {},
            "start_state": case.get("start_state"),
            "followups": case.get("followups") or [],
        }

    def run(self, payload: dict) -> AttemptResult:
        subs = {"question": payload["question"], "model": self.model, "timeout": str(self.timeout),
                "case_id": str(payload["case_id"]), "trial": payload["trial"]}
        argv = [tok.format(**subs) if "{" in tok else tok for tok in self.command]
        start = time.monotonic()
        try:
            r = subprocess.run(argv, input=json.dumps(payload), capture_output=True, text=True,
                               timeout=self.timeout, cwd=str(self.cwd), env=self.env)
        except subprocess.TimeoutExpired as e:
            return AttemptResult(Outcome.TIMEOUT, f"timed out after {self.timeout}s", None,
                                 self.timeout * 1000.0, killed=True,
                                 stdout=_text(e.stdout), stderr=_text(e.stderr))
        except FileNotFoundError as e:
            return AttemptResult(Outcome.CLI_MISSING, str(e), None, 0.0)
        latency_ms = (time.monotonic() - start) * 1000
        return _parse_result(r, latency_ms)


def _text(b) -> str:
    if b is None:
        return ""
    return b.decode(errors="replace") if isinstance(b, bytes) else str(b)


def _int(v) -> int | None:
    try:
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _float(v) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _parse_result(r: subprocess.CompletedProcess, latency_ms: float) -> AttemptResult:
    payload = _parse_json_stdout(r.stdout)
    if payload is None:
        err = (r.stderr or r.stdout).strip()[:300]
        if r.returncode != 0:
            return AttemptResult(Outcome.PROVIDER_ERROR, err or f"exit code {r.returncode}", None,
                                 latency_ms, stdout=r.stdout, stderr=r.stderr)
        if not r.stdout.strip():
            return AttemptResult(Outcome.NO_OUTPUT, err, None, latency_ms, stdout=r.stdout,
                                 stderr=r.stderr)
        return AttemptResult(Outcome.UNPARSEABLE, err, None, latency_ms, stdout=r.stdout,
                             stderr=r.stderr)

    error = str(payload.get("error") or payload.get("llm_error") or "")
    raw = str(payload.get("outcome") or Outcome.OK)
    try:
        outcome = Outcome(raw)
    except ValueError:
        outcome, error = Outcome.PROVIDER_ERROR, error or f"unknown outcome {raw!r}"
    if outcome is Outcome.OK and r.returncode != 0:
        outcome, error = Outcome.PROVIDER_ERROR, error or f"exit code {r.returncode}"

    usage = payload.get("usage") or {}
    model_ids = payload.get("model_ids") or {}
    if not isinstance(model_ids, dict):
        model_ids = {}
    answer = payload.get("answer")
    return AttemptResult(
        outcome=outcome,
        error=error,
        answer=None if answer is None else str(answer),
        latency_ms=latency_ms,
        cost_usd=_float(usage.get("cost")),
        tokens_input=_int(usage.get("tokens_input")),
        tokens_output=_int(usage.get("tokens_output")),
        tokens_cached=_int(usage.get("tokens_cached")),
        tool_calls=_int(usage.get("tool_calls")),
        agent_retries=_int(usage.get("retries")),
        model_ids={str(k): str(v) for k, v in model_ids.items()},
        trace_id=str(payload["trace_id"]) if payload.get("trace_id") else None,
        killed=bool(payload.get("killed", False)),
        stdout=r.stdout,
        stderr=r.stderr,
    )


def _public(case: dict) -> dict:
    return {k: v for k, v in case.items() if not k.startswith("_")}
