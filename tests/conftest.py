"""Builds a throwaway git repository from examples/store for each test that needs one."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from aot_evals import cli


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True,
                   env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
                        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com",
                        "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"})


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
