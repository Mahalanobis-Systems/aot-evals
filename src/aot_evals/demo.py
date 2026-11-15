"""`aot-evals demo [DIR]`: the online store (examples/store; docs/v2-design.md §9), to try aot-evals
in a few minutes.

It copies the example (a support agent, its refund subagent, fakes for the order system and
payments, a trace export, two eval specs with drawn quality sets, bug-finding sets and a calibrated
policy judge) into a new git repository, then runs the loop a team runs on its own agent: import
the traces, extract the refund handoffs, screen the cases, run a baseline of each eval, then a
candidate of the refund subagent that improves its own eval and breaks refunds end to end
(docs/problems.md, problem 2), and decide on it. Nothing calls a model or a network service, and
nothing outside DIR is touched. Afterwards, open Claude Code in DIR to explore it with the skills.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "examples" / "store"
AGENT = "evals/agents/store"
FRAME = "support-requests-2026-10"
GIT_ID = ["-c", "user.name=aot-evals demo", "-c", "user.email=demo@example.invalid"]


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *GIT_ID, *args], cwd=repo, check=True, capture_output=True)


def _variant(dest: Path, variant: str) -> None:
    """Set AGENT_VARIANT for the whole agent and for the refund subagent's own eval."""
    for rel in (f"{AGENT}/agent.yaml", f"{AGENT}/refund-subagent/eval.yaml"):
        path = dest / rel
        data = yaml.safe_load(path.read_text())
        data["invoke"]["env"]["AGENT_VARIANT"] = variant
        path.write_text(yaml.safe_dump(data, sort_keys=False))


def make(dest: Path) -> Path:
    """Copy the example into `dest` as a fresh git repository; return the agent's folder."""
    if dest.exists() and any(dest.iterdir()):
        raise FileExistsError(f"{dest} already exists and is not empty; pass another directory")
    shutil.copytree(EXAMPLE, dest, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__"))
    (dest / ".gitignore").write_text("world.json\n__pycache__/\n")
    _git(dest, "init", "-q")
    # the coverage lists come from the help center, before any case (rule 10)
    _git(dest, "add", "docs", f"{AGENT}/end-to-end/coverage.yaml", f"{AGENT}/refund-subagent/coverage.yaml")
    _git(dest, "commit", "-q", "-m", "Coverage lists from the help center and the refund policy")
    _git(dest, "add", "-A")
    _git(dest, "commit", "-q", "-m", "The store's support agent, its refund subagent and their evals")
    return dest / AGENT


def run(dest: Path, cli_main, log=print) -> int:
    agent = make(dest)

    def step(text: str, *args: str, eval_id: str | None = None, ok=(0,)) -> None:
        argv = ["--evals", str(agent), *(["--eval", eval_id] if eval_id else []), *args]
        log(f"\n== {text}\n$ aot-evals {' '.join(argv[2:])}")
        code = cli_main(argv)
        if code not in (*ok, None):
            raise RuntimeError(f"`aot-evals {' '.join(argv[2:])}` exited {code}")

    step("Import the exported traces, with their provenance", "import", str(dest / "traces.jsonl"),
         "--id", FRAME, "--source", "the store's support traces", "--query", "all",
         "--window", "2026-10-01..2026-10-31", eval_id="end-to-end")
    step("The refund subagent's frame: the handoffs in those traces (rule 4)", "handoffs",
         eval_id="refund-subagent")
    step("Both specs are complete", "validate")
    for e in ("end-to-end", "refund-subagent"):
        step(f"Screen every case of {e} (a person has read them)", "screen", "--read-by", "demo", "--all",
             eval_id=e)
    _git(dest, "add", "-A")
    _git(dest, "commit", "-q", "-m", "Screened")
    for e in ("end-to-end", "refund-subagent"):
        step(f"The baseline of {e}, k = 3", "run", "--purpose", "baseline", "--label", "demo", eval_id=e)
        step(f"{e}'s report", "report", eval_id=e)
    _variant(dest, "declines-missing-order")
    _git(dest, "commit", "-q", "-am", "Refund subagent: the new prompt (declines handoffs with no order number)")
    for e in ("refund-subagent", "end-to-end"):
        step(f"The candidate on {e}, one declared change", "run", "--purpose", "candidate", "--variable",
             "prompt=refunds-v2", "--label", "demo", eval_id=e)
    step("The end-to-end comparison", "compare", eval_id="end-to-end", ok=(0, 1))
    step("The decision on the refund subagent's change (rule 27: the whole agent has the last word)",
         "compare", eval_id="refund-subagent", ok=(0, 1))
    log(f"""
Demo ready in {dest}

  activity log   {agent / 'journal' / 'activity.html'}
  reports        {agent / 'end-to-end' / 'report' / 'report.json'}
                 {agent / 'refund-subagent' / 'report' / 'report.json'}
  comparisons    {agent / 'refund-subagent' / 'report' / 'comparisons'}

The refund subagent's new prompt breaks the refund policy less often on its own eval, and declines
the refund requests that arrive without an order number instead of asking for it, so refunds end
to end get worse (docs/problems.md, problem 2). Next: open Claude Code in {dest} with the plugin
enabled and ask "should we ship the refund team's change?". Delete the folder when you are done.""")
    return 0
