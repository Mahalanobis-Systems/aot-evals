"""Builds a throwaway git repo from examples/calendar for each test."""

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
