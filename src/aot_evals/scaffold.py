"""`init`: create the `evals/` directory (docs/method.md §3) with commented templates."""

from __future__ import annotations

import shutil
from pathlib import Path

from .repo import Evals

TEMPLATES = Path(__file__).parent / "templates" / "evals"

FILES = {
    "agent.yaml": "agent.yaml",
    "taxonomy.yaml": "taxonomy.yaml",
    "categories.yaml": "categories.yaml",
    "failure_modes.yaml": "failure_modes.yaml",
    "budgets.yaml": "budgets.yaml",
    ".gitignore": "gitignore",
    "data/export.manifest.json": "export.manifest.json",
}
DIRS = ("cases", "checks/code", "checks/judge", "env", "data", "runs", "report")


def init(ev: Evals) -> list[str]:
    """Create whatever is missing. Never overwrites an existing file."""
    created = []
    for d in DIRS:
        p = ev.p(d)
        if not p.exists():
            p.mkdir(parents=True)
            keep = p / ".gitkeep"
            keep.touch()
            created.append(str(Path(d) / ""))
    for dest, src in FILES.items():
        p = ev.p(dest)
        if not p.exists():
            p.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(TEMPLATES / src, p)
            created.append(dest)
    return created
