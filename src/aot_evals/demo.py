"""`aot-evals demo [DIR]`: a toy agent with a finished suite, to try aot-evals in a few minutes.

It copies examples/calendar (a toy calendar agent, its product spec, exported traces and a
reviewed suite) into a new git repository, then runs the loop a team runs on its own agent:
import, screen, allocate, a smoke run, a k = 3 baseline, a candidate that breaks two cases, the
paired comparison, and the report. Nothing calls a model or a network service, and nothing
outside DIR is touched. Afterwards, open Claude Code in DIR to explore it with the skills.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "examples" / "calendar"
TEMPLATES = Path(__file__).parent / "templates" / "evals"
SUITE = "evals/agents/calendar"
GIT_ID = ["-c", "user.name=aot-evals demo", "-c", "user.email=demo@example.invalid"]


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *GIT_ID, *args], cwd=repo, check=True, capture_output=True)


def _agent_yaml(repo: Path, broken: str = "") -> None:
    path = repo / SUITE / "agent.yaml"
    text = path.read_text()
    head, _, _ = text.partition("  env:")
    path.write_text(head + f'  env: {{AGENT_VARIANT: good, WORLD_FILE: world.json, AGENT_BREAK: "{broken}"}}\n')


def make(dest: Path) -> Path:
    """Copy the example into `dest` as a fresh git repository; return the suite directory."""
    if dest.exists() and any(dest.iterdir()):
        raise FileExistsError(f"{dest} already exists and is not empty; pass another directory")
    shutil.copytree(EXAMPLE, dest, dirs_exist_ok=True)
    suite = dest / SUITE
    suite.parent.mkdir(parents=True)
    shutil.move(dest / "evals", dest / "_suite")
    shutil.move(dest / "_suite", suite)
    text = (suite / "agent.yaml").read_text()
    (suite / "agent.yaml").write_text(text.replace("{PYTHON}", "python3").replace("{VARIANT}", "good")
                                      .replace("timeout: 3", "timeout: 20"))
    _agent_yaml(dest)
    (dest / ".gitignore").write_text("world.json\n")
    shutil.copyfile(TEMPLATES / "gitignore", suite / ".gitignore")
    _git(dest, "init", "-q")
    _git(dest, "add", f"{SUITE}/taxonomy.yaml", "docs")  # the coverage list predates the cases (G5)
    _git(dest, "commit", "-q", "-m", "Coverage list from the product spec")
    _git(dest, "add", "-A")
    _git(dest, "commit", "-q", "-m", "The toy calendar agent and its eval suite")
    return suite


def run(dest: Path, cli_main, log=print) -> int:
    suite = make(dest)
    base = ["--evals", str(suite)]

    def step(text: str, *args: str) -> None:
        log(f"\n== {text}\n$ aot-evals {' '.join(args)}")
        code = cli_main([*base, *args])
        if code not in (0, None):
            raise RuntimeError(f"`aot-evals {' '.join(args)}` exited {code}")

    step("C0: import the exported traces, with their provenance",
         "import", str(dest / "traces.jsonl"), "--id", "traces", "--source", "toy calendar traces",
         "--query", "all", "--window", "2026-09-01..2026-09-30")
    step("C1: the agent runs end to end", "run", "--purpose", "smoke", "--case", "book-001")
    step("C5: size both case sets", "allocate", "--write", "--mark-short", "out_of_scope",
         "--reason", "the demo suite is deliberately small")
    step("C7: screen every case (a person has read them)", "screen", "--read-by", "demo", "--all")
    _git(dest, "add", "-A")
    _git(dest, "commit", "-q", "-m", "Screened and allocated")
    step("C12: the baseline, k = 3", "run", "--purpose", "baseline", "--k", "3", "--label", "demo")
    _agent_yaml(dest, broken="book-002,book-003")
    _git(dest, "commit", "-q", "-am", "Candidate: a config change that books two meetings at the wrong time")
    step("C13: a candidate with one declared change", "run", "--purpose", "candidate", "--k", "3",
         "--variable", "config=break-two", "--label", "demo")
    log("\n== C13: the paired comparison")
    cli_main([*base, "compare"])  # exits 1 only when refused; the verdict is the point here
    step("C18: report.json", "report")
    step("A checkpoint page for the owner", "checkpoint", "--gate", "C13", "--title", "The aot-evals demo",
         "--summary", "A toy calendar agent, a k = 3 baseline, and a candidate that books two meetings at "
         "the wrong time. The paired comparison lists the two losses; with so few cases it cannot call "
         "the change significant, and says so.")
    log(f"""
Demo ready in {dest}

  activity log  {suite / 'journal' / 'activity.html'}
  checkpoint    {suite / 'report' / 'checkpoints'}
  report data   {suite / 'report' / 'report.json'}

Next: open Claude Code in {dest} with the plugin enabled and ask "where are we with our evals?",
or "write a report on why the candidate regressed". Delete the folder when you are done.""")
    return 0
