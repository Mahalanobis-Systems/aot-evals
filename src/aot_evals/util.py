"""File, hashing and git helpers shared by every command."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:
    import yaml

    class _Loader(yaml.SafeLoader):
        """SafeLoader that keeps dates as the strings the team wrote (they go into JSON)."""

    _Loader.yaml_implicit_resolvers = {
        k: [(tag, rx) for tag, rx in v if tag != "tag:yaml.org,2002:timestamp"]
        for k, v in yaml.SafeLoader.yaml_implicit_resolvers.items()
    }
except ImportError:  # pragma: no cover - the bin/aot-evals wrapper provides it via uv
    yaml = None


class ContractError(Exception):
    """A file in evals/ is missing or malformed."""


def now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_id_stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def load_yaml(path: Path) -> Any:
    if yaml is None:
        raise ContractError("PyYAML is not available; run aot-evals through its bin/ wrapper")
    try:
        return yaml.load(path.read_text(), Loader=_Loader)  # noqa: S506 - a SafeLoader
    except FileNotFoundError:
        return None
    except yaml.YAMLError as e:
        raise ContractError(f"{path}: invalid YAML: {e}") from e


def dump_yaml(data: Any) -> str:
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=100)


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return None
    except json.JSONDecodeError as e:
        raise ContractError(f"{path}: invalid JSON: {e}") from e


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for i, line in enumerate(path.read_text().splitlines(), 1):
        if line.strip():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError as e:
                raise ContractError(f"{path}:{i}: invalid JSON line: {e}") from e
    return out


def append_jsonl(path: Path, record: dict) -> None:
    with path.open("a") as f:
        f.write(json.dumps(record, ensure_ascii=False, sort_keys=False) + "\n")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sha256_tree(root: Path, base: Path | None = None) -> str | None:
    """Hash of every file under root (path and content), or None if root has no files."""
    if not root.exists():
        return None
    base = base or root
    h = hashlib.sha256()
    files = sorted(p for p in root.rglob("*") if p.is_file() and "__pycache__" not in p.parts)
    if not files:
        return None
    for p in files:
        h.update(str(p.relative_to(base)).encode())
        h.update(b"\0")
        h.update(p.read_bytes())
    return h.hexdigest()


def git(args: list[str], cwd: Path) -> str | None:
    try:
        r = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, timeout=30)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def git_commit_info(cwd: Path, pathspec: str | None = None, exclude: Path | None = None) -> dict:
    """The commit a directory is at, and whether it has uncommitted changes.

    With a pathspec, `commit` is the last commit that touched it, so `evals_commit` moves only
    when evals/ does. With `exclude` (the evals/ directory, when it lives inside the agent's
    repository), the agent's commit and dirty flag ignore it: committing a run or a label must
    not look like a change to the agent."""
    if git(["rev-parse", "--is-inside-work-tree"], cwd) != "true":
        return {"commit": None, "dirty": None}
    if pathspec:
        commit = git(["log", "-1", "--format=%H", "--", pathspec], cwd) or None
        status = git(["status", "--porcelain", "--", pathspec], cwd)
        return {"commit": commit, "dirty": bool(status) if status is not None else None}
    spec = ["."]
    if exclude is not None:
        try:
            rel = exclude.resolve().relative_to(cwd.resolve())
            spec.append(f":(exclude){rel}")
        except ValueError:
            pass  # evals/ is outside the agent's tree; nothing to exclude
    commit = git(["log", "-1", "--format=%H", "--", *spec], cwd) or git(["rev-parse", "HEAD"], cwd)
    status = git(["status", "--porcelain", "--untracked-files=no", "--", *spec], cwd)
    return {"commit": commit, "dirty": bool(status) if status is not None else None}


def git_adding_commit(cwd: Path, pathspec: str) -> str | None:
    """The earliest commit that added pathspec, or None if it was never committed."""
    out = git(["log", "--diff-filter=A", "--format=%H", "--", pathspec], cwd)
    return out.split()[-1] if out else None


def git_adding_commits(cwd: Path, pathspec: str) -> dict[str, str]:
    """path (relative to cwd) -> the earliest commit that added it, for every file under pathspec,
    in one `git log`. One call per file made `status` slower with every case added."""
    out = git(["-c", "core.quotePath=false", "log", "--diff-filter=A", "--no-renames", "--relative",
               "--format=%x00%H", "--name-only", "--", pathspec], cwd)
    added: dict[str, str] = {}
    commit = None
    for line in (out or "").splitlines():
        if line.startswith("\0"):
            commit = line[1:]
        elif line and commit:
            added[line] = commit  # newest first, so the last one seen is the earliest
    return added


def git_strictly_before(cwd: Path, a: str, b: str) -> bool:
    """Whether commit a is an ancestor of commit b and not b itself."""
    if a == b:
        return False
    try:
        r = subprocess.run(["git", "merge-base", "--is-ancestor", a, b], cwd=str(cwd),
                           capture_output=True, timeout=30)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    return r.returncode == 0


def git_untracked_or_modified(cwd: Path, pathspec: str) -> list[str]:
    out = git(["status", "--porcelain", "--untracked-files=all", "--", pathspec], cwd)
    if out is None:
        return []
    return [line[3:] for line in out.splitlines() if line.strip()]


def get_path(obj: Any, dotted: str) -> Any:
    """Read a dotted path (a.b.0.c) out of nested dicts and lists; None when absent."""
    cur = obj
    for part in dotted.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        elif isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
            cur = cur[int(part)]
        else:
            return None
    return cur
