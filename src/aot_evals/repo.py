"""The `evals/` directory (docs/method.md): where each file lives and how it is read.

Readers are lenient (a missing file reads as empty) so that `status` can describe a half-built
directory; `validate` and the gates are where strictness lives.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .util import ContractError, load_json, load_yaml, read_jsonl

ALL_USE_CASES = "*"  # a failure mode that applies to every use case


def _is_suite_dir(d: Path) -> bool:
    """evals/agents/<agent>/: one agent system's folder in a repository that may hold several."""
    return d.parent.name == "agents" and d.parent.parent.name == "evals"


def agent_suites(evals_dir: Path) -> list[Path]:
    d = evals_dir / "agents"
    return sorted(p for p in d.iterdir() if p.is_dir()) if d.is_dir() else []


def is_evals_root(d: Path) -> bool:
    """A repository's top-level evals/ folder rather than one agent's folder."""
    return d.name == "evals" and (d / "agents").is_dir() and not (d / "agent.yaml").exists()


class _Runs:
    """Reading runs/: each eval has its own runs/ folder."""

    def p(self, *parts: str) -> Path:  # pragma: no cover - Eval defines it
        raise NotImplementedError

    def cases(self, include_dropped: bool = True) -> list[dict]:  # pragma: no cover
        raise NotImplementedError

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
        """The effective baseline: for each current case, the newest finished baseline run that
        covers it, oldest first. A re-run of one use case leaves the baseline of the others in
        place; a full re-run replaces them all."""
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


@dataclass
class Evals:
    """An agent system's folder, evals/agents/<agent>/ (docs/method.md): agent.yaml, the
    discovery report, and what its evals share (env/, data/, labels/standard.md, journal/), with
    one folder per eval."""

    root: Path

    @classmethod
    def find(cls, explicit: str | None = None, agent: str | None = None) -> Evals:
        """The agent system to work on: --evals, else found from the working directory upward.
        With several agents in evals/agents/, `agent` names one."""
        if explicit:
            path = Path(explicit).expanduser().resolve()
            if is_evals_root(path):  # --evals evals/ names the folder of agents, not one agent
                return cls.in_evals_dir(path, agent)
            return cls(path)
        here = Path.cwd().resolve()
        for d in (here, *here.parents):
            if _is_suite_dir(d) and (agent is None or d.name == agent):
                return cls(d)
            if (d / "evals").is_dir():
                return cls.in_evals_dir(d / "evals", agent)
            if d.name == "evals" and (d / "agents").is_dir():
                return cls.in_evals_dir(d, agent)
        return cls.in_evals_dir(here / "evals", agent)

    @classmethod
    def in_evals_dir(cls, evals_dir: Path, agent: str | None = None) -> Evals:
        if agent:
            return cls(evals_dir / "agents" / agent)
        suites = agent_suites(evals_dir)
        if len(suites) == 1:
            return cls(suites[0])
        if suites:
            names = ", ".join(s.name for s in suites)
            raise ContractError(f"{evals_dir} holds several agents ({names}); pass --agent NAME")
        raise ContractError(f"no agent under {evals_dir}; run /aot-evals:start first, or "
                            "`aot-evals --agent NAME --eval end-to-end init` to create one")

    # ---- locations -------------------------------------------------------------------------

    @property
    def evals_dir(self) -> Path:
        """The repository's top-level evals/ directory (every agent's folder is inside it)."""
        return self.root.parent.parent if _is_suite_dir(self.root) else self.root

    @property
    def repo_root(self) -> Path:
        """Where agent.yaml's relative paths (invoke.cwd, a command judge's cwd) start."""
        return self.evals_dir.parent

    @property
    def agent_name(self) -> str:
        return self.agent().get("id") or (self.root.name if _is_suite_dir(self.root) else self.repo_root.name)

    def p(self, *parts: str) -> Path:
        return self.root.joinpath(*parts)

    def discovery_path(self) -> Path:
        return self.p("discovery.md")

    def exists(self) -> bool:
        return self.root.is_dir()

    @property
    def env_dir(self) -> Path:
        """The sandbox fakes, hashed into every manifest."""
        return self.p("env")

    @property
    def standard_path(self) -> Path:
        return self.p("labels", "standard.md")

    def agent(self) -> dict:
        return load_yaml(self.p("agent.yaml")) or {}

    def exports(self) -> list[dict]:
        data = load_json(self.p("data", "export.manifest.json"))
        if data is None:
            return []
        if isinstance(data, dict):
            return list(data.get("exports") or [])
        return list(data)

    # ---- evals ------------------------------------------------------------------------------

    def eval_dirs(self) -> list[Path]:
        """The agent's evals: each folder inside it that holds an eval.yaml."""
        if not self.root.is_dir():
            return []
        return sorted(p.parent for p in self.root.glob(f"*/{EVAL_FILE}")
                      if p.parent.name not in SHARED_DIRS)

    @property
    def has_evals(self) -> bool:
        return bool(self.eval_dirs())

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
# Folders of the agent system that its evals share (docs/method.md); never an eval id.
SHARED_DIRS = ("env", "data", "labels", "journal")
# Also reserved: the names of an eval's own folders, and pulled/, which .gitignore leaves out.
RESERVED_EVAL_IDS = (*SHARED_DIRS, "cases", "checks", "runs", "report", "pulled")


POOLS = ("quality", "bug_finding")


@dataclass
class Eval(_Runs):
    """One eval of an agent system: evals/agents/<agent>/<eval>/ (docs/method.md).

    Its cases, checks, judges, labels, runs and report are its own; the sandbox (`env/`), the
    frames (`data/`), the labeling standard and the journal belong to the agent system.

    The runner, the judges and isolation read it through `cases`, `checks_for_case`, `agent` and
    the runs: the failure modes come from the spec's measurement model, and a mode applies to a
    case through the case's use case."""

    agent_system: Evals
    root: Path
    _spec: object = field(default=None, init=False, repr=False, compare=False)

    @property
    def agent_dir(self) -> Evals:
        return self.agent_system

    def agent(self) -> dict:
        """agent.yaml, with a component eval's own `invoke` in place of the system's (docs/method.md)."""
        data = dict(self.agent_system.agent())
        unit = (self.spec().part("estimand").get("unit") or {})
        own = self.spec().resolved.get("invoke")
        if isinstance(unit, dict) and unit.get("kind") == "component":
            # never the system's invoke: a component eval runs the component on its handoffs
            data["invoke"] = own if isinstance(own, dict) else {}
        return data

    @property
    def evals_dir(self) -> Path:
        return self.agent_system.evals_dir

    @property
    def agent_name(self) -> str:
        return self.agent_system.agent_name

    @property
    def id(self) -> str:
        return self.root.name

    def p(self, *parts: str) -> Path:
        """A path inside this eval's folder."""
        return self.root.joinpath(*parts)

    def shared(self, *parts: str) -> Path:
        """A path in the agent system's folder, shared by its evals."""
        return self.agent_system.p(*parts)

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
        return self.agent_system.repo_root

    def exports(self) -> list[dict]:
        return self.agent_system.exports()

    def budget_for(self, use_case: str | None) -> dict | None:
        """A use case's budgets: decision_rule.constraints' default, overridden per use case."""
        c = self.spec().part("decision_rule").get("constraints") or {}
        if not isinstance(c, dict):
            return None
        per = (c.get("use_cases") or {}).get(use_case) if use_case else None
        default = c.get("default")
        if per is None and default is None:
            return None
        return {**(default or {}), **(per or {})}

    # ---- cases -----------------------------------------------------------------------------

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
            case["_dir_use_case"] = path.parent.name
            if not include_dropped and (case.get("screen") or {}).get("dropped"):
                continue
            out.append(case)
        return out

    # ---- failure modes and checks (the measurement model) ---------------------------------

    def failure_modes(self) -> list[dict]:
        fms = self.spec().part("measurement").get("failure_modes")
        return [f for f in fms if isinstance(f, dict) and f.get("id")] if isinstance(fms, list) else []

    def failure_modes_for_case(self, case: dict) -> list[dict]:
        """The modes that apply to a case: those whose use cases include its use case. Every
        case of a use case is graded the same way, drawn or written (docs/method.md)."""
        uc = case.get("use_case")
        out = []
        for fm in self.failure_modes():
            ucs = fm.get("use_cases")
            if ucs == ALL_USE_CASES or (isinstance(ucs, list) and uc in ucs):
                out.append(fm)
        return out

    def checks_for_case(self, case: dict, check_type: str | None = "code") -> list[tuple[str, dict]]:
        """(check_id, failure_mode) for each counted check and each diagnostic that applies to a
        case. `counted(check_id, fm)` says which is which (rule 12)."""
        seen, out = set(), []
        for fm in self.failure_modes_for_case(case):
            ids = ([fm["check"]] if isinstance(fm.get("check"), str) else []) + [
                d for d in (fm.get("diagnostics") or []) if isinstance(d, str)]
            for cid in ids:
                if cid in seen or (check_type and self.check_type(cid) != check_type):
                    continue
                seen.add(cid)
                out.append((cid, fm))
        return out

    @staticmethod
    def counted(check_id: str, fm: dict) -> bool:
        """Whether a check is the one that counts for its failure mode, not a diagnostic."""
        return fm.get("check") == check_id

    def judge_labels(self, check_id: str) -> list[dict]:
        return read_jsonl(self.p("checks", "judge", f"{check_id}.labels.jsonl"))

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

    def spec(self, reload: bool = False):
        """The eval spec, loaded and validated (`spec.Spec`), read once per Eval."""
        from .spec import load

        if self._spec is None or reload:
            self._spec = load(self)
        return self._spec
