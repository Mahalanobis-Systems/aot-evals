"""The `evals/` directory (docs/method.md §3): where each file lives and how it is read.

Readers are lenient (a missing file reads as empty) so that `status` can describe a half-built
directory; `validate` and the gates are where strictness lives.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .util import ContractError, load_json, load_yaml, read_jsonl

SETS = ("error_finding", "quality_estimate")
WORTHS = ("low", "medium", "high")
CHECK_TYPES = ("code", "judge", "monitor")
ALL_CATEGORIES = "*"


def _is_suite_dir(d: Path) -> bool:
    """evals/agents/<agent>/: one agent's suite in a repository that may hold several."""
    return d.parent.name == "agents" and d.parent.parent.name == "evals"


def agent_suites(evals_dir: Path) -> list[Path]:
    d = evals_dir / "agents"
    return sorted(p for p in d.iterdir() if p.is_dir()) if d.is_dir() else []


@dataclass
class Evals:
    root: Path  # the agent's suite: evals/agents/<agent>/, or evals/ itself in a one-agent repo

    @classmethod
    def find(cls, explicit: str | None = None, agent: str | None = None) -> Evals:
        """The suite to work on. Each agent's suite lives in evals/agents/<agent>/, beside its
        discovery report; with several agents, `agent` names one. A repository whose evals/
        holds agent.yaml directly is a one-agent suite."""
        if explicit:
            return cls(Path(explicit).expanduser().resolve())
        here = Path.cwd().resolve()
        for d in (here, *here.parents):
            if _is_suite_dir(d) and (agent is None or d.name == agent):
                return cls(d)
            if (d / "evals").is_dir():
                return cls.in_evals_dir(d / "evals", agent)
            if d.name == "evals" and ((d / "agent.yaml").exists() or (d / "agents").is_dir()):
                return cls.in_evals_dir(d, agent)
        return cls.in_evals_dir(here / "evals", agent)

    @classmethod
    def in_evals_dir(cls, evals_dir: Path, agent: str | None = None) -> Evals:
        if agent:
            return cls(evals_dir / "agents" / agent)
        if (evals_dir / "agent.yaml").exists():
            return cls(evals_dir)
        suites = agent_suites(evals_dir)
        if len(suites) == 1:
            return cls(suites[0])
        if suites:
            names = ", ".join(s.name for s in suites)
            raise ContractError(f"{evals_dir / 'agents'} holds several agents ({names}); "
                                "pass --agent NAME")
        raise ContractError(f"no agent suite under {evals_dir}; run /aot-evals:start first, or "
                            "`aot-evals --agent NAME init` to create evals/agents/NAME/")

    # ---- locations -------------------------------------------------------------------------

    @property
    def evals_dir(self) -> Path:
        """The repository's top-level evals/ directory (every agent's suite is inside it)."""
        return self.root.parent.parent if _is_suite_dir(self.root) else self.root

    @property
    def repo_root(self) -> Path:
        """Where agent.yaml's relative paths (invoke.cwd, a command judge's cwd) start."""
        return self.evals_dir.parent

    @property
    def agent_name(self) -> str:
        return (self.agent().get("id") or (self.root.name if _is_suite_dir(self.root)
                                           else self.repo_root.name))

    def p(self, *parts: str) -> Path:
        return self.root.joinpath(*parts)

    def exists(self) -> bool:
        return self.root.is_dir()

    # ---- configuration files ---------------------------------------------------------------

    def agent(self) -> dict:
        return load_yaml(self.p("agent.yaml")) or {}

    def taxonomy(self) -> dict:
        return load_yaml(self.p("taxonomy.yaml")) or {}

    def categories(self) -> list[dict]:
        data = load_yaml(self.p("categories.yaml")) or {}
        return list(data.get("categories") or [])

    def category_ids(self) -> list[str]:
        return [c.get("id") for c in self.categories() if c.get("id")]

    def failure_modes(self) -> list[dict]:
        data = load_yaml(self.p("failure_modes.yaml")) or {}
        return list(data.get("failure_modes") or [])

    def budgets(self) -> dict:
        return load_yaml(self.p("budgets.yaml")) or {}

    def budget_for(self, category: str) -> dict | None:
        b = self.budgets()
        per = (b.get("categories") or {}).get(category)
        default = b.get("default")
        if per is None and default is None:
            return None
        return {**(default or {}), **(per or {})}

    def allocation(self) -> dict:
        return load_yaml(self.p("allocation.yaml")) or {}

    def exports(self) -> list[dict]:
        data = load_json(self.p("data", "export.manifest.json"))
        if data is None:
            return []
        if isinstance(data, dict):
            return list(data.get("exports") or [])
        return list(data)

    # ---- cases and checks ------------------------------------------------------------------

    def case_paths(self) -> list[Path]:
        d = self.p("cases")
        return sorted(d.glob("*/*.json")) if d.exists() else []

    def cases(self, include_dropped: bool = True) -> list[dict]:
        out = []
        for path in self.case_paths():
            case = load_json(path)
            if not isinstance(case, dict):
                raise ContractError(f"{path}: a case must be a JSON object")
            case["_path"] = str(path.relative_to(self.root))
            case["_dir_category"] = path.parent.name
            if not include_dropped and (case.get("screen") or {}).get("dropped"):
                continue
            out.append(case)
        return out

    def code_check_path(self, check_id: str) -> Path:
        return self.p("checks", "code", f"{check_id}.py")

    def judge_check_path(self, check_id: str) -> Path:
        return self.p("checks", "judge", f"{check_id}.md")

    def check_type(self, check_id: str) -> str | None:
        if self.code_check_path(check_id).exists():
            return "code"
        if self.judge_check_path(check_id).exists():
            return "judge"
        return None

    def judge_labels(self, check_id: str) -> list[dict]:
        return read_jsonl(self.p("checks", "judge", f"{check_id}.labels.jsonl"))

    def failure_modes_for_case(self, case: dict) -> list[dict]:
        """The failure modes a case is checked against: its own, plus every mode that applies to
        all categories (side-effect checks run on every case)."""
        wanted = set(case.get("failure_modes") or [])
        out = []
        for fm in self.failure_modes():
            cats = fm.get("categories") or []
            if fm.get("id") in wanted or ALL_CATEGORIES in cats:
                out.append(fm)
        return out

    def checks_for_case(self, case: dict, check_type: str | None = "code") -> list[tuple[str, dict]]:
        """(check_id, failure_mode) pairs for a case, de-duplicated, optionally by type."""
        seen = set()
        out = []
        for fm in self.failure_modes_for_case(case):
            for cid in fm.get("checks") or []:
                if cid in seen:
                    continue
                if check_type and self.check_type(cid) != check_type:
                    continue
                seen.add(cid)
                out.append((cid, fm))
        return out

    # ---- runs ------------------------------------------------------------------------------

    def run_dirs(self) -> list[Path]:
        d = self.p("runs")
        if not d.exists():
            return []
        return sorted(p for p in d.iterdir() if (p / "manifest.json").exists())

    def run_manifest(self, run_id: str) -> dict | None:
        return load_json(self.p("runs", run_id, "manifest.json"))

    def run_records(self, run_id: str) -> list[dict]:
        return read_jsonl(self.p("runs", run_id, "outcomes.jsonl"))

    def runs(self, purpose: str | None = None) -> list[dict]:
        out = []
        for d in self.run_dirs():
            m = load_json(d / "manifest.json") or {}
            if purpose is None or m.get("purpose") == purpose:
                out.append(m)
        return out

    def latest_run(self, purpose: str | None = None) -> dict | None:
        runs = [r for r in self.runs(purpose) if r.get("finished")]
        return runs[-1] if runs else None
