"""Loading and running code checks (`evals/checks/code/<check-id>.py`).

A code check is a module with one function:

    def check(start: dict, end: dict, case: dict) -> tuple[bool, str]

`start` and `end` have the same shape: {"world": <observed state or None>, "output": <the
agent's deliverable text, or None before the run>}. A check decides from the world wherever the
world can decide (docs/method.md §1, principle 3); it reads `output` only when the output is itself the
deliverable. It never reads the agent's claim that it succeeded (G10): the screen (C7) tests
for that by running every check against an unchanged world plus a confident success claim.

A module may set `USES_AGENT_REPORT = True` to declare that it trusts the agent's report; G10
then refuses it.
"""

from __future__ import annotations

import importlib.util
import traceback
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

_cache: dict[tuple[str, float], ModuleType] = {}


@dataclass
class CheckResult:
    id: str
    passed: bool | None  # None: the check itself errored (an instrument failure, plane C)
    detail: str

    def as_dict(self) -> dict:
        return {"id": self.id, "passed": self.passed, "detail": self.detail}


def load(path: Path) -> ModuleType:
    key = (str(path), path.stat().st_mtime)
    if key in _cache:
        return _cache[key]
    spec = importlib.util.spec_from_file_location(f"aot_evals_check_{path.stem}", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if not callable(getattr(mod, "check", None)):
        raise ImportError(f"{path} has no check(start, end, case) function")
    _cache[key] = mod
    return mod


def declares_agent_report(path: Path) -> bool:
    try:
        return bool(getattr(load(path), "USES_AGENT_REPORT", False))
    except Exception:
        return False


def run_check(check_id: str, path: Path, start: dict, end: dict, case: dict) -> CheckResult:
    try:
        mod = load(path)
        result = mod.check(start, end, _public(case))
    except Exception as e:  # a crashing check is reported, never scored as an agent failure
        tb = traceback.format_exception_only(type(e), e)[-1].strip()
        return CheckResult(check_id, None, f"check raised: {tb}")
    if isinstance(result, tuple):
        passed, detail = (result + ("",))[:2]
    else:
        passed, detail = result, ""
    if not isinstance(passed, bool):
        return CheckResult(check_id, None, f"check returned {type(passed).__name__}, not bool")
    return CheckResult(check_id, passed, str(detail)[:2000])


def _public(case: dict) -> dict:
    return {k: v for k, v in case.items() if not k.startswith("_")}
