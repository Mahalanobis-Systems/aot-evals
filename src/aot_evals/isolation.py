"""Keep the agent away from the answers (docs/method.md §4: the agent must not see the cases).

evals/ lives in the repository the agent runs in. An agent with a coding harness can grep its
working directory, match a case file and read the expected answer. Two defences:

- `invoke.isolate: true` runs the agent (and its hooks) from a per-run copy of the repository
  that has no evals/ in it, except this suite's env/ (the fakes the hooks need). Tracked and
  untracked files are copied; git-ignored files are copied and git-ignored directories (a
  virtualenv, node_modules) are linked, so the agent's environment still works. The copy is
  deleted when the run ends.
- Every run is checked for exposure, isolated or not: eval files (cases, checks, labels) that
  changed during the run, and agent output that names a case file or the suite's path. Either
  makes the run's manifest a problem (C12), so it cannot become a baseline unnoticed.
"""

from __future__ import annotations

import fnmatch
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from .repo import Evals
from .util import sha256_file

ANSWER_DIRS = ("cases", "checks")


def _git_list(root: Path, *args: str) -> list[str] | None:
    try:
        r = subprocess.run(["git", "ls-files", "-z", *args], cwd=str(root), capture_output=True,
                           timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0:
        return None
    return [p for p in r.stdout.decode(errors="replace").split("\0") if p]


def _keep(rel: str, evals_rel: str, env_rel: str) -> bool:
    """Everything outside evals/, and this suite's env/ inside it."""
    if rel == ".git" or rel.startswith(".git/"):
        return False
    if rel == evals_rel or rel.startswith(evals_rel + "/"):
        return rel.startswith(env_rel + "/")
    return True


def make_copy(ev: Evals, label: str) -> Path:
    """A copy of the repository without the eval answers; returns the copy's repository root."""
    src = ev.repo_root
    evals_rel = str(ev.evals_dir.relative_to(src))
    env_rel = str(ev.p("env").relative_to(src))
    dest = Path(tempfile.mkdtemp(prefix=f"aot-evals-{label}-")) / src.name
    dest.mkdir()
    files = _git_list(src, "--cached", "--others", "--exclude-standard")
    if files is None:  # not a git repository: copy everything outside evals/
        files = [str(p.relative_to(src)) for p in src.rglob("*") if p.is_file() or p.is_symlink()]
        ignored = []
    else:
        ignored = _git_list(src, "--others", "--ignored", "--exclude-standard", "--directory") or []
    for rel in files:
        if not _keep(rel, evals_rel, env_rel):
            continue
        s, d = src / rel, dest / rel
        if not s.exists() and not s.is_symlink():
            continue  # deleted in the working tree
        d.parent.mkdir(parents=True, exist_ok=True)
        if s.is_symlink():
            d.symlink_to(os.readlink(s))
        elif s.is_file():
            shutil.copy2(s, d)
    for rel in ignored:
        rel = rel.rstrip("/")
        if not _keep(rel, evals_rel, env_rel) or (dest / rel).exists():
            continue
        s, d = src / rel, dest / rel
        d.parent.mkdir(parents=True, exist_ok=True)
        if s.is_dir():
            d.symlink_to(s)  # a virtualenv or node_modules: link, don't copy
        elif s.is_file():
            shutil.copy2(s, d)
    return dest


def remove_copy(root: Path) -> None:
    shutil.rmtree(root.parent, ignore_errors=True)


def answer_files(ev: Evals) -> dict[str, str]:
    """rel path -> hash of every file that holds or grades an answer: cases, checks, labels."""
    out = {}
    for d in ANSWER_DIRS:
        base = ev.p(d)
        if base.is_dir():
            for p in sorted(base.rglob("*")):
                if p.is_file() and not p.name.endswith((".queue.csv", ".judgements.jsonl")):
                    out[str(p.relative_to(ev.root))] = sha256_file(p)[:16]
    return out


def changed(before: dict[str, str], after: dict[str, str]) -> list[str]:
    return sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))


def mentions(ev: Evals, text: str | None, case_ids: list[str]) -> list[str]:
    """Eval files that the agent's output names: the suite's cases/ or checks/ path, or a case
    file name. Naming one means the agent found the tests."""
    if not text:
        return []
    suite = str(ev.root.relative_to(ev.repo_root))
    found = [f"{suite}/{d}" for d in ANSWER_DIRS if f"{suite}/{d}" in text]
    found += [f"{cid}.json" for cid in case_ids if f"{cid}.json" in text]
    return found


def tree_snapshot(root: Path, excludes: list[str] | None = None) -> dict[str, str]:
    """rel path -> hash of every file in the working tree, minus .git, evals/ and `excludes`
    (globs, for run outputs). In a git repository: tracked and untracked files, not ignored ones.
    An observe hook that hashes only the agent's own folders misses a file written anywhere
    else, such as an answer.md in the repository root."""
    excludes = list(excludes or [])

    def skip(rel: str) -> bool:
        top = rel.split("/", 1)[0]
        return top in (".git", "evals") or any(fnmatch.fnmatch(rel, g) for g in excludes)

    files = _git_list(root, "--cached", "--others", "--exclude-standard")
    if files is None:
        files = []
        for d, dirs, names in os.walk(root, followlinks=False):
            rel_d = os.path.relpath(d, root)
            dirs[:] = [x for x in dirs if not skip(os.path.normpath(os.path.join(rel_d, x)))]
            files += [os.path.normpath(os.path.join(rel_d, n)) for n in names]
    out = {}
    for rel in sorted(files):
        p = root / rel
        if not skip(rel) and p.is_file():
            out[rel] = sha256_file(p)[:16]
    return out
