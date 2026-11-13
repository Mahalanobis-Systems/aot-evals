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


def _is_old_suite_dir(d: Path) -> bool:
    """evals/<agent>/ with its own agent.yaml: the layout suites had before evals/agents/."""
    return d.parent.name == "evals" and d.name != "agents" and (d / "agent.yaml").exists()


def agent_suites(evals_dir: Path) -> list[Path]:
    d = evals_dir / "agents"
    return sorted(p for p in d.iterdir() if p.is_dir()) if d.is_dir() else []


def old_suites(evals_dir: Path) -> list[Path]:
    """Suites in the old layout, evals/<agent>/ (`aot-evals migrate` moves them)."""
    if not evals_dir.is_dir() or (evals_dir / "agent.yaml").exists():
        return []
    return sorted(p for p in evals_dir.iterdir() if p.is_dir() and _is_old_suite_dir(p))


def is_evals_root(d: Path) -> bool:
    """A repository's top-level evals/ folder rather than one agent's suite."""
    return d.name == "evals" and not (d / "agent.yaml").exists() and (
        (d / "agents").is_dir() or bool(old_suites(d)))


@dataclass
class Evals:
    root: Path  # the agent's suite: evals/agents/<agent>/, or evals/ itself in a one-agent repo

    @classmethod
    def find(cls, explicit: str | None = None, agent: str | None = None) -> Evals:
        """The suite to work on. Each agent's suite lives in evals/agents/<agent>/, beside its
        discovery report; with several agents, `agent` names one. A repository whose evals/
        holds agent.yaml directly is a one-agent suite."""
        if explicit:
            path = Path(explicit).expanduser().resolve()
            if is_evals_root(path):  # --evals evals/ names the folder of suites, not one suite
                return cls.in_evals_dir(path, agent)
            return cls(path)
        here = Path.cwd().resolve()
        for d in (here, *here.parents):
            if (_is_suite_dir(d) or _is_old_suite_dir(d)) and (agent is None or d.name == agent):
                return cls(d)
            if (d / "evals").is_dir():
                return cls.in_evals_dir(d / "evals", agent)
            if d.name == "evals" and ((d / "agent.yaml").exists() or (d / "agents").is_dir()):
                return cls.in_evals_dir(d, agent)
        return cls.in_evals_dir(here / "evals", agent)

    @classmethod
    def in_evals_dir(cls, evals_dir: Path, agent: str | None = None) -> Evals:
        old = {p.name: p for p in old_suites(evals_dir)}
        if agent:
            new = evals_dir / "agents" / agent
            # an old-layout suite wins over a new folder that holds nothing but a discovery report
            if agent in old and not (new / "agent.yaml").exists():
                return cls(old[agent])
            return cls(new)
        if (evals_dir / "agent.yaml").exists():
            return cls(evals_dir)
        suites = [s for s in agent_suites(evals_dir) if (s / "agent.yaml").exists() or s.name not in old]
        suites = sorted({s.name: s for s in [*suites, *old.values()]}.values())
        if len(suites) == 1:
            return cls(suites[0])
        if suites:
            names = ", ".join(s.name for s in suites)
            raise ContractError(f"{evals_dir} holds several agents ({names}); pass --agent NAME")
        raise ContractError(f"no agent suite under {evals_dir}; run /aot-evals:start first, or "
                            "`aot-evals --agent NAME init` to create evals/agents/NAME/")

    # ---- locations -------------------------------------------------------------------------

    @property
    def evals_dir(self) -> Path:
        """The repository's top-level evals/ directory (every agent's suite is inside it)."""
        if _is_suite_dir(self.root):
            return self.root.parent.parent
        if _is_old_suite_dir(self.root):
            return self.root.parent
        return self.root

    @property
    def old_layout(self) -> bool:
        return _is_old_suite_dir(self.root)

    @property
    def repo_root(self) -> Path:
        """Where agent.yaml's relative paths (invoke.cwd, a command judge's cwd) start."""
        return self.evals_dir.parent

    @property
    def agent_name(self) -> str:
        return (self.agent().get("id") or (self.root.name if _is_suite_dir(self.root) or self.old_layout
                                           else self.repo_root.name))

    def p(self, *parts: str) -> Path:
        return self.root.joinpath(*parts)

    def discovery_path(self) -> Path:
        """The discovery report: in the suite, or, for an old-layout suite, where an assessment
        made after it put one (evals/agents/<agent>/discovery.md) until `migrate` joins them."""
        own = self.p("discovery.md")
        if own.exists() or not self.old_layout:
            return own
        beside = self.evals_dir / "agents" / self.root.name / "discovery.md"
        return beside if beside.exists() else own

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

    def baseline_runs(self) -> list[dict]:
        """The effective baseline (docs/method.md §4.1): for each current case, the newest finished
        baseline run that covers it, oldest first. A re-run of one category leaves the baseline of
        the others in place; a full re-run replaces them all."""
        runs = [m for m in self.runs("baseline") if m.get("finished")]
        if not runs:
            return []
        try:
            ids = {c.get("id") for c in self.cases(include_dropped=False)}
        except ContractError:
            ids = set()
        covered: set = set()
        picked = []
        for m in reversed(runs):
            cs = set((m.get("case_set") or {}).get("ids") or [])
            if not picked or (cs & ids) - covered:
                picked.append(m)
                covered |= cs
        return list(reversed(picked))

    def baseline_ids(self) -> list[str]:
        return [m["run_id"] for m in self.baseline_runs()]

    def latest_run(self, purpose: str | None = None) -> dict | None:
        runs = [r for r in self.runs(purpose) if r.get("finished")]
        return runs[-1] if runs else None

    # ---- 2.0 evals (docs/v2-design.md §1) --------------------------------------------------

    def eval_dirs(self) -> list[Path]:
        """The agent's 2.0 evals: each folder inside it that holds an eval.yaml."""
        if not self.root.is_dir():
            return []
        return sorted(p.parent for p in self.root.glob(f"*/{EVAL_FILE}")
                      if p.parent.name not in SHARED_DIRS)

    @property
    def has_evals(self) -> bool:
        return bool(self.eval_dirs())

    @property
    def has_v1_suite(self) -> bool:
        """1.x suite files beside the evals (a suite `migrate --to 2` has not converted yet)."""
        return any(self.p(f).exists() for f in V1_FILES)

    def eval(self, eval_id: str | None = None) -> Eval:
        """One eval of this agent. With one eval the id is optional; with several, the eval whose
        folder holds the working directory is the default."""
        dirs = self.eval_dirs()
        if eval_id:
            for d in dirs:
                if d.name == eval_id:
                    return Eval(self, d)
            known = ", ".join(d.name for d in dirs) or "none yet"
            raise ContractError(f"no eval '{eval_id}' in {self.root} (evals: {known}); "
                                f"`aot-evals --eval {eval_id} init` creates it")
        if len(dirs) == 1:
            return Eval(self, dirs[0])
        here = Path.cwd().resolve()
        for d in dirs:
            if here == d.resolve() or d.resolve() in here.parents:
                return Eval(self, d)
        if dirs:
            names = ", ".join(d.name for d in dirs)
            raise ContractError(f"{self.root} holds several evals ({names}); pass --eval ID")
        raise ContractError(f"no eval in {self.root}; `aot-evals --eval end-to-end init` creates "
                            "the end-to-end eval")

    def evals(self) -> list[Eval]:
        return [Eval(self, d) for d in self.eval_dirs()]


EVAL_FILE = "eval.yaml"
# Folders of the agent system that its evals share (docs/v2-design.md §1); never an eval id.
SHARED_DIRS = ("env", "data", "labels", "journal")
# Also reserved: the 1.x suite's folders, so an eval never collides with one before `migrate`.
RESERVED_EVAL_IDS = (*SHARED_DIRS, "cases", "checks", "runs", "report", "pulled")
V1_FILES = ("categories.yaml", "failure_modes.yaml", "taxonomy.yaml", "allocation.yaml")


@dataclass
class Eval:
    """One eval of an agent system: evals/agents/<agent>/<eval>/ (docs/v2-design.md §1).

    Its cases, checks, judges, labels, runs and report are its own; the sandbox (`env/`), the
    frames (`data/`), the labeling standard and the journal belong to the agent system."""

    agent: Evals
    root: Path

    @property
    def id(self) -> str:
        return self.root.name

    def p(self, *parts: str) -> Path:
        """A path inside this eval's folder."""
        return self.root.joinpath(*parts)

    def shared(self, *parts: str) -> Path:
        """A path in the agent system's folder, shared by its evals."""
        return self.agent.p(*parts)

    @property
    def spec_path(self) -> Path:
        return self.p(EVAL_FILE)

    @property
    def env_dir(self) -> Path:
        return self.shared("env")

    @property
    def standard_path(self) -> Path:
        return self.shared("labels", "standard.md")

    @property
    def repo_root(self) -> Path:
        """Where `invoke.cwd` starts, as for agent.yaml."""
        return self.agent.repo_root

    def exports(self) -> list[dict]:
        return self.agent.exports()

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

    def spec(self):
        """The eval spec, loaded and validated (`spec.Spec`)."""
        from .spec import load

        return load(self)
