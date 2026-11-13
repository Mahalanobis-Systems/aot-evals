"""`init`: create the `evals/` directory (docs/method.md §3) with commented templates, or, with
`--eval`, one 2.0 eval folder and the agent system's shared files (docs/v2-design.md §1)."""

from __future__ import annotations

import shutil
from pathlib import Path

from .repo import RESERVED_EVAL_IDS, Eval, Evals
from .spec import ID_RE, sibling_units
from .util import ContractError

TEMPLATES = Path(__file__).parent / "templates" / "evals"

FILES = {
    "agent.yaml": "agent.yaml",
    "taxonomy.yaml": "taxonomy.yaml",
    "categories.yaml": "categories.yaml",
    "failure_modes.yaml": "failure_modes.yaml",
    "budgets.yaml": "budgets.yaml",
    "labels/standard.md": "standard.md",
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


# ---- 2.0: one folder per eval (docs/v2-design.md §1) -------------------------------------------

# Shared by every eval of the agent system.
AGENT_FILES = {
    "agent.yaml": "agent.yaml",
    "labels/standard.md": "standard.md",
    "data/export.manifest.json": "export.manifest.json",
}
AGENT_DIRS = ("env", "data")
# Each eval's own.
EVAL_DIRS = ("cases", "checks/code", "checks/judge", "labels", "runs", "report")
# The eval folders sit one level down, so the 1.x patterns need a leading */ to reach them.
GITIGNORE_V2 = "*/runs/*/raw/\n*/checks/judge/*.queue.csv\n"

_UNIT_SYSTEM = "    kind: system                   # the whole agent, through agent.yaml's invoke"
_UNIT_COMPONENT = """    kind: component
    component: {component}{pad}# named in agent.yaml
    boundary:                      # the context boundary its handoff crosses"""
_ALSO_SYSTEM = "  also_requires: []               # other evals that must pass for this decision"
_ALSO_COMPONENT = """  also_requires:                   # ships only when the end-to-end eval shows no regression
    - eval: {system}
      test: non_inferiority
      margin:"""
_INVOKE_COMPONENT = """
invoke:                            # calls the component directly, the handoff on stdin (agent contract)
  command: []
  cwd: .                           # relative to the repository root
  timeout: 60
"""


def eval_spec_text(eval_id: str, component: str | None, system_eval: str = "end-to-end") -> str:
    """eval.yaml for a new eval, from the template."""
    text = (TEMPLATES / "eval.yaml").read_text()
    if component:
        unit = _UNIT_COMPONENT.format(component=component, pad=" " * max(1, 23 - len(component)))
        also = _ALSO_COMPONENT.format(system=system_eval)
        invoke = _INVOKE_COMPONENT
    else:
        unit, also, invoke = _UNIT_SYSTEM, _ALSO_SYSTEM, ""
    text = (text.replace("__EVAL__", eval_id).replace("__UNIT__", unit)
            .replace("__ALSO__", also).replace("__INVOKE__", invoke))
    return text.rstrip() + "\n"


def init_eval(ev: Evals, eval_id: str, component: str | None = None) -> list[str]:
    """Create the agent system's shared files and one eval folder, whatever is missing. Never
    overwrites an existing file. Refuses an id that names a shared folder, and a second system
    eval (an agent has one end-to-end eval)."""
    if eval_id in RESERVED_EVAL_IDS or not ID_RE.match(eval_id):
        raise ContractError(f"'{eval_id}' cannot name an eval: use letters, digits, - _ . and not "
                            f"one of {', '.join(RESERVED_EVAL_IDS)}")
    e = Eval(ev, ev.p(eval_id))
    systems = sorted(k for k, v in sibling_units(e).items() if v == "system")
    if not component and systems and not e.spec_path.exists():
        raise ContractError(f"{systems[0]} is already this agent's end-to-end eval; an agent has one. "
                            "For a subagent behind a context boundary, pass --component NAME")

    created = []

    def mkdir(rel: str, base: Path) -> None:
        p = base / rel
        if not p.exists():
            p.mkdir(parents=True)
            (p / ".gitkeep").touch()
            created.append(str(p.relative_to(ev.root)) + "/")

    for d in AGENT_DIRS:
        mkdir(d, ev.root)
    for dest, src in AGENT_FILES.items():
        p = ev.p(dest)
        if not p.exists():
            p.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(TEMPLATES / src, p)
            created.append(dest)
    gi = ev.p(".gitignore")
    if not gi.exists():
        gi.write_text((TEMPLATES / "gitignore").read_text() + GITIGNORE_V2)
        created.append(".gitignore")
    for d in EVAL_DIRS:
        mkdir(d, e.root)
    if not e.spec_path.exists():
        e.spec_path.write_text(eval_spec_text(eval_id, component, systems[0] if systems else "end-to-end"))
        created.append(f"{eval_id}/eval.yaml")
    cov = e.p("coverage.yaml")
    if not cov.exists():
        shutil.copyfile(TEMPLATES / "taxonomy.yaml", cov)
        created.append(f"{eval_id}/coverage.yaml")
    return created
