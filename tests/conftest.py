"""Builds a throwaway git repository from examples/store for each test that needs one."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from aot_evals import cli

FIXTURE = Path(__file__).parents[1] / "examples" / "calendar"


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True,
                   env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
                        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com",
                        "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"})


class Repo:
    def __init__(self, root: Path, suite: str = "evals"):
        self.root = root
        self.suite = suite
        self.evals = root / suite

    def cli(self, *args: str) -> int:
        return cli.main(["--evals", str(self.evals), *args])

    def yaml(self, name: str) -> dict:
        return yaml.safe_load((self.evals / name).read_text())

    def write_yaml(self, name: str, data) -> None:
        (self.evals / name).write_text(yaml.safe_dump(data, sort_keys=False))

    def commit(self, msg: str, *paths: str) -> None:
        git(self.root, "add", *(paths or ["-A"]))
        git(self.root, "commit", "-q", "-m", msg)

    def report(self) -> dict:
        import json

        return json.loads((self.evals / "report" / "report.json").read_text())

    def gate(self, report: dict, gid: str) -> dict:
        return next(g for g in report["gates"] if g["id"] == gid)


def build_repo(tmp: Path, variant: str = "good", timeout: int = 5, taxonomy_first: bool = True,
               screen: bool = True, suite: str = "evals") -> Repo:
    """`suite` is where the fixture's suite goes: evals/ (one agent), or evals/agents/<agent>/."""
    root = tmp / "repo"
    shutil.copytree(FIXTURE, root)
    if suite != "evals":
        (root / suite).parent.mkdir(parents=True)
        shutil.move(root / "evals", root / "_suite")
        shutil.move(root / "_suite", root / suite)
    agent = (root / suite / "agent.yaml").read_text()
    agent = agent.replace("{PYTHON}", sys.executable).replace("{VARIANT}", variant)
    agent = agent.replace("timeout: 3", f"timeout: {timeout}")
    (root / suite / "agent.yaml").write_text(agent)
    (root / ".gitignore").write_text("world.json\n")
    shutil.copyfile(Path(cli.__file__).parent / "templates" / "evals" / "gitignore",
                    root / suite / ".gitignore")
    git(root, "init", "-q")
    repo = Repo(root, suite)
    if taxonomy_first:
        repo.commit("taxonomy", f"{suite}/taxonomy.yaml", "docs")
    assert repo.cli("import", str(root / "traces.jsonl"), "--id", "traces", "--source",
                    "fixture traces", "--query", "all", "--window", "2026-09-01..2026-09-30") == 0
    if screen:
        assert repo.cli("screen", "--read-by", "tester", "--all", "--force") == 0
    assert repo.cli("allocate", "--write", "--force", "--mark-short", "out_of_scope",
                    "--reason", "fixture is deliberately small") == 0
    repo.commit("evals")
    return repo


STORE = Path(__file__).parents[1] / "examples" / "store"
STORE_AGENT = "evals/agents/store"


class StoreRepo:
    """examples/store in a fresh repository: both frames imported, every case screened, committed."""

    def __init__(self, root: Path):
        self.root = root
        self.agent = root / STORE_AGENT

    def cli(self, *args: str, eval_id: str = "end-to-end") -> int:
        return cli.main(["--evals", str(self.agent), "--eval", eval_id, *args])

    def ev(self, eval_id: str = "end-to-end"):
        from aot_evals.repo import Evals

        return Evals(self.agent).eval(eval_id)

    def set_env(self, eval_id: str | None = None, **env: str) -> None:
        """Set invoke.env (agent.yaml's, or a component eval's own) for the next run."""
        path = self.agent / (f"{eval_id}/eval.yaml" if eval_id else "agent.yaml")
        data = yaml.safe_load(path.read_text())
        data["invoke"]["env"].update(env)
        path.write_text(yaml.safe_dump(data, sort_keys=False))

    def commit(self, msg: str = "evals") -> None:
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "--allow-empty", "-m", msg)

    def report(self, eval_id: str = "end-to-end") -> dict:
        import json

        return json.loads((self.agent / eval_id / "report" / "report.json").read_text())


def build_store(tmp: Path, screen: bool = True) -> StoreRepo:
    root = tmp / "store"
    shutil.copytree(STORE, root, ignore=shutil.ignore_patterns("__pycache__"))
    (root / ".gitignore").write_text("world.json\n__pycache__/\n")
    git(root, "init", "-q")
    s = StoreRepo(root)
    s.commit("the store and its specs")
    assert s.cli("import", str(root / "traces.jsonl"), "--id", "support-requests-2026-10", "--source",
                 "store traces", "--query", "all", "--window", "2026-10-01..2026-10-31") == 0
    assert s.cli("handoffs", eval_id="refund-subagent") == 0
    if screen:
        for e in ("end-to-end", "refund-subagent"):
            assert s.cli("screen", "--read-by", "tester", "--all", eval_id=e) == 0
    s.commit("imported and screened")
    return s


@pytest.fixture
def store_repo(tmp_path, monkeypatch) -> StoreRepo:
    monkeypatch.chdir(tmp_path)
    return build_store(tmp_path)


@pytest.fixture(autouse=True)
def no_telemetry(tmp_path_factory, monkeypatch):
    """Tests never send telemetry, and never touch the real settings folder."""
    monkeypatch.setenv("AOT_EVALS_TELEMETRY", "0")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path_factory.mktemp("config")))


@pytest.fixture
def make_repo(tmp_path):
    def _make(**kw) -> Repo:
        return build_repo(tmp_path, **kw)
    return _make
