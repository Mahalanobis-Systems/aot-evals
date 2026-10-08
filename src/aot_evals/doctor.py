"""`aot-evals doctor`: is everything aot-evals needs here, and what to paste into a bug report.

Prints versions, paths and yes/no checks. It never prints a secret: for credentials it says only
whether the variable named in a judge backend is set.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

from . import __version__
from .util import ContractError


def _which(name: str) -> str | None:
    """Look in the PATH the user's shell had, not the ephemeral environment's."""
    return shutil.which(name, path=os.environ.get("AOT_EVALS_ORIG_PATH") or os.environ.get("PATH"))


def _version(cmd: list[str]) -> str | None:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        return None
    out = (r.stdout or r.stderr).strip().splitlines()
    return out[0] if r.returncode == 0 and out else None


def checks(evals: str | None, agent: str | None) -> list[tuple[str, str, str]]:
    """(status, what, detail) rows; status is ok, warn or FAIL."""
    rows: list[tuple[str, str, str]] = []
    rows.append(("ok", "aot-evals", f"{__version__} ({Path(__file__).resolve().parents[2]})"))
    py_ok = sys.version_info >= (3, 11)
    rows.append(("ok" if py_ok else "FAIL", "python (runs aot-evals)",
                 f"{platform.python_version()} {sys.executable}" + ("" if py_ok else "; needs 3.11+")))
    try:
        import yaml
        rows.append(("ok", "PyYAML", yaml.__version__))
    except ImportError:
        rows.append(("FAIL", "PyYAML", "missing; install uv (https://docs.astral.sh/uv/) or `pip install pyyaml`"))
    try:
        import anthropic
        rows.append(("ok", "anthropic SDK", f"{anthropic.__version__} (only the anthropic judge backend needs it)"))
    except ImportError:
        rows.append(("warn", "anthropic SDK", "missing; only the anthropic judge backend needs it"))
    uv = _which("uv")
    rows.append(("ok" if uv else "warn", "uv", (_version([uv, "--version"]) or uv) if uv else
                 "not found; aot-evals falls back to a Python 3.11+ with PyYAML"))
    git = _which("git")
    rows.append(("ok" if git else "FAIL", "git", _version([git, "--version"]) if git else
                 "not found; runs record commits, and C2 checks the taxonomy predates the cases"))
    rows.append(("ok", "platform", f"{platform.system()} {platform.release()} {platform.machine()}"))

    from .repo import Evals  # after the PyYAML check: the repo module needs it
    try:
        ev = Evals.find(evals, agent)
    except ContractError as e:
        rows.append(("warn", "suite", str(e)))
        return rows
    if not ev.exists():
        rows.append(("warn", "suite", f"none at {ev.root} (fine before `aot-evals init`)"))
        return rows
    rows.append(("ok", "suite", f"{ev.root} (agent {ev.agent_name}, {len(ev.case_paths())} cases)"))
    inside = _version(["git", "-C", str(ev.repo_root), "rev-parse", "--is-inside-work-tree"]) == "true"
    rows.append(("ok" if inside else "warn", "repository",
                 f"{ev.repo_root}" + ("" if inside else " is not a git repository")))
    cwd = (ev.agent().get("invoke") or {}).get("cwd", ".")
    rows.append(("ok" if (ev.repo_root / str(cwd)).is_dir() else "FAIL", "invoke.cwd",
                 f"{cwd!r} from the repository root"))
    from .judges import load_spec
    for path in sorted(ev.p("checks", "judge").glob("*.md")) if ev.p("checks", "judge").is_dir() else []:
        try:
            spec = load_spec(path)
        except ContractError as e:
            rows.append(("FAIL", f"judge {path.stem}", str(e)))
            continue
        for name, cfg in spec.backends.items():
            env = cfg.get("api_key_env") or ("ANTHROPIC_API_KEY" if cfg.get("type") == "anthropic" else None)
            if env:
                rows.append(("ok" if os.environ.get(env) else "warn", f"judge {spec.id}/{name}",
                             f"{env} is {'set' if os.environ.get(env) else 'not set'}"))
    return rows


def render(rows: list[tuple[str, str, str]]) -> str:
    width = max(len(w) for _, w, _ in rows)
    return "\n".join(f"  {st:<4}  {what:<{width}}  {detail}" for st, what, detail in rows)
