"""`aot-evals migrate`: move suites from the old layout, evals/<agent>/, to evals/agents/<agent>/.

Suites made before several agents per repository lived in evals/<agent>/. Newer versions look
for evals/agents/<agent>/, and an assessment run there may already have put a discovery report
in it. `migrate` moves every file of the old suite into the new folder, with `git mv` for files
git tracks so their history follows them, keeps whatever the new folder already holds (a file
present in both is left where it is and reported), and removes the old folder once it is empty.
Nothing inside a suite changes: runs, labels and calibrations keep their contents.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from .repo import old_suites
from .util import git

# files the CLI writes again from their data, or writes itself
REGENERATED = {"journal/activity.html", "journal/.gitignore", "discovery.html"}
MERGED = {"journal/activity.jsonl"}  # append-only logs: both sides' entries, in time order


def resolve(src: Path, dst: Path, rel: str) -> str | None:
    """How a file present in both trees is settled, or None when it can't be: identical files and
    regenerated pages keep the new copy; the activity logs are merged by time."""
    if src.read_bytes() == dst.read_bytes():
        return "identical"
    if rel in REGENERATED:
        return "regenerated"
    if rel in MERGED:
        return "merged"
    return None


def _merge_jsonl(src: Path, dst: Path) -> None:
    import json

    lines = []
    for f in (src, dst):
        for ln in f.read_text().splitlines():
            if ln.strip():
                try:
                    lines.append((json.loads(ln).get("ts") or "", ln))
                except json.JSONDecodeError:
                    continue
    seen, out = set(), []
    for _, ln in sorted(lines, key=lambda x: x[0]):
        if ln not in seen:
            seen.add(ln)
            out.append(ln)
    dst.write_text("\n".join(out) + "\n")


def plan(evals_dir: Path) -> list[dict]:
    out = []
    for old in old_suites(evals_dir):
        new = evals_dir / "agents" / old.name
        files = sorted(p for p in old.rglob("*") if p.is_file())
        clash = [str(p.relative_to(old)) for p in files if (new / p.relative_to(old)).exists()
                 and resolve(p, new / p.relative_to(old), str(p.relative_to(old))) is None]
        settled = {str(p.relative_to(old)): resolve(p, new / p.relative_to(old), str(p.relative_to(old)))
                   for p in files if (new / p.relative_to(old)).exists()}
        settled = {k: v for k, v in settled.items() if v}
        out.append({"agent": old.name, "from": old, "to": new, "files": len(files), "clash": clash,
                    "settled": settled,
                    "keeps": sorted(str(p.relative_to(new)) for p in new.rglob("*") if p.is_file())
                    if new.exists() else []})
    return out


def _tracked(repo: Path, path: Path) -> bool:
    return git(["ls-files", "--error-unmatch", str(path)], repo) is not None


def run(evals_dir: Path, dry_run: bool = False, log=print) -> list[dict]:
    repo = evals_dir.parent
    steps = plan(evals_dir)
    if not steps:
        log(f"no suites in the old layout under {evals_dir}; nothing to migrate")
        return []
    for st in steps:
        log(f"{st['agent']}: {st['from'].relative_to(repo)}/ -> {st['to'].relative_to(repo)}/ "
            f"({st['files']} files)" + (f"; keeps {', '.join(st['keeps'])} already there" if st["keeps"] else ""))
        for rel, how in st["settled"].items():
            log(f"  both have {rel}: " + {"identical": "the same file; one copy is kept",
                                          "regenerated": "the new copy is kept (it is rewritten from its data)",
                                          "merged": "both logs are merged, in time order"}[how])
        for c in st["clash"]:
            log(f"  both have {c}: the copy in {st['to'].relative_to(repo)}/ is kept; the old one stays "
                f"in {st['from'].relative_to(repo)}/ for you to compare")
        if dry_run:
            continue
        for src in sorted(p for p in st["from"].rglob("*") if p.is_file()):
            rel = src.relative_to(st["from"])
            dst = st["to"] / rel
            if dst.exists():
                how = st["settled"].get(str(rel))
                if how == "merged":
                    _merge_jsonl(src, dst)
                if how:
                    if _tracked(repo, src):
                        git(["rm", "-q", "--cached", str(src)], repo)
                    src.unlink()
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            if _tracked(repo, src) and git(["mv", str(src), str(dst)], repo) is not None:
                continue
            shutil.move(str(src), str(dst))
        for d in sorted((p for p in st["from"].rglob("*") if p.is_dir()), key=lambda p: -len(p.parts)):
            if not any(d.iterdir()):
                d.rmdir()
        if not any(st["from"].iterdir()):
            st["from"].rmdir()
    if not dry_run:
        log("done. Nothing inside the suites changed; review with `git status`, then commit the move.")
    return steps
