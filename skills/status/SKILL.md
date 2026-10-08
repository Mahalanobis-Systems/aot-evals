---
name: status
description: Phase 2 entry point, after discover has written a discovery report (evals/agents/<agent>/discovery.md); with no discovery report, load discover instead. Designing, building, measuring and iterating a production agent's evals. Reads the state of the repo's evals/ directory, reports which command gate (C0-C18) is unmet, and routes to the skill that clears it (scope, build, calibrate, run, report). Use when a team wants evals for an agent, asks "where are we with our evals", "what's next", or "is this suite any good", or when any other aot-evals skill is unsure where to start.
---

# status

**First:** if no `evals/agents/*/discovery.md` exists in this repository, stop and load
`discover`. It shows the banner, explains the two phases, asks which agent to test, and
writes the discovery report. Come back here only after that.

You help a team build evals for **their own agent**, in their own repository. The method is
`${CLAUDE_PLUGIN_ROOT}/docs/method.md`. Read only the section you need: §1 principles, §2
measurement frame, §3 the files, §4 commands, §6 measurements, §10 gates.

CLI: `"${CLAUDE_PLUGIN_ROOT}/bin/aot-evals"`. It is also on PATH as `aot-evals` while the
plugin is enabled. It needs `uv`, or Python ≥ 3.11 with PyYAML, and installs nothing into the
team's project.

## 1. Read the state, publish it, and stop

```bash
aot-evals status            # each gate C0–C18 and the next unmet one
aot-evals validate          # every problem across all gates
```

Each agent's suite lives in `evals/agents/<agent>/`, beside its discovery report; `<suite>/`
below means that folder. If it has no `agent.yaml` yet, confirm the repository root with the user,
then run `aot-evals --agent <agent> init` there. When the repository has several agents, pass
`--agent <agent>` to every `aot-evals` command. A one-agent repository may keep its suite
in `evals/` itself, and needs no `--agent`.

Then, before any other work, publish where things stand:

```bash
aot-evals activity --open
aot-evals checkpoint --title "Where <agent>'s evals stand" --open --summary-file - <<'EOF'
Two or three short paragraphs: what this plugin will do with the team, the stage they are at,
what has been done, and the single next step. Assume the reader knows nothing of the method.
EOF
```

The page explains every gate in plain words, renders everything the suite already holds, and names
what the next step needs from the owner. Add an `--ask` for each thing you need to start: for C0,
the export file, its source, query and window. Then stop, and tell the person the page's path
and the next step. This page is the team's first result. Never skip it to save time.

## Work in checkpoints

The person follows the work in a browser, not the terminal: `<suite>/journal/activity.html` shows
everything done so far and reloads itself, and each checkpoint page shows what the work has
produced. Work so those pages tell the story, and stop wherever the person should steer.

1. **Open the activity page once per session**: `aot-evals activity --open`. Tell the person
   the path, and that the page updates itself.
2. **Log as you go.** CLI commands log themselves. Log everything else in one line before you
   do it (`aot-evals log "Reading agent/ to find every model call site" --gate C1`). Log what
   you learn with `--kind finding --detail "<evidence>"`. Log each decision with `--kind
   decision --by <name|claude>`, saying whether it is confirmed or inferred.
3. **Save questions for the checkpoint.** Ask in the terminal only when you cannot go on without
   the answer. Log such a question first, with `--kind question`.
4. **Checkpoint, then stop.** Write a checkpoint when a gate clears, or when the work needs the
   owner: a draft to confirm, a number to choose, a cost to approve.

   ```bash
   aot-evals checkpoint --gate C3 --open --ask "<question>" --ask "<question>" --summary-file - <<'EOF'
   What you did and found, in two or three short paragraphs or "- " bullets. Plain words: the
   reader may not know the method. Name the numbers and where they came from.
   EOF
   ```

   End your turn with three lines: the page's path, the headline, and what you need from the
   person. **Don't start the next step until they reply**, even when you asked nothing.

Every skill below follows this pattern. Each one lists its own checkpoints.

## 2. Route

`status` names the first unmet gate and the skill that clears it:

| Gate | Skill | Commands |
|---|---|---|
| C0–C4 | `scope` | import, inventory, taxonomy, categorize, decompose |
| C5–C8 | `build` | allocate, author, screen, checks |
| C9–C11 | `calibrate` | label, calibrate, reliability |
| C12–C17 | `run` | baseline, compare, coverage, redundancy, drift, online (C16–C17 are guidance only for now) |
| C18 | `report` | the report |

Once the person replies to the first checkpoint, load the skill that clears the next unmet gate
and continue. A command does not run while a predecessor's gate is unmet. The CLI refuses and names
the gate. `--force` exists for debugging; it is recorded in the run manifest, so never
use it to hide a gate from the user.

Two exceptions to the order:
- **E14, the operational sweep** (`aot-evals ops`), can run in week one, before any eval exists.
  It needs only an imported export. Offer it early: plane B needs no labels.
- **C9–C11 never block a baseline.** Uncalibrated judges run, but G3 keeps them out of the
  headline numbers. A baseline is usually where the items to label come from.
- **Reports** can always be generated. Each gate's status goes into the report, and a refused
  number is withheld with its reason, never shown silently.

## 3. Rules you hold the team to

1. **Cases come from real traffic and real failures**, not public benchmarks.
2. **Three planes, never combined:** A correctness, B operational (cost, latency, errors), C
   instrument trust. Never fold them into a single score.
3. **Two case sets:** `error_finding` (hard and rare cases; finds bugs) and `quality_estimate`
   (sampled by traffic share). Only the second may be called "quality" (G6).
4. **Grade the end state with code first.** Use a judge only where code cannot decide, and only
   once it is calibrated. Never grade the agent's own report of success (G10).
5. **Every number carries n, k and an interval**, or says why it can't. When a number cannot be
   defended, refuse it and name the gate.
6. **Raw traces and PII never enter git.** Exports live in `<suite>/data/`, which is ignored. Only
   scrubbed, reviewed cases are committed.
7. **Record each claim as confirmed or inferred, with its source.** When config and traces
   disagree, trust the traces.

## 4. The loop

C3–C18 repeat. Two events force re-entry:
- a **prompt rewrite**: most of the hardest cases can change, so re-derive the hard set and
  re-run the baseline;
- a **shift in category mix**: re-open C3 (shares) and C5 (allocation).

When the user changes the agent's prompt, skills, tools, model or harness, say that the baseline
no longer describes the agent, and route to `run`.

## 5. Choosing the strategy per category

Before C4, answer the six questions in
`${CLAUDE_PLUGIN_ROOT}/references/process/agent-properties-framework.md` with the owner, per
category:
1. Is the outcome verifiable?
2. If performance is acceptable, optimise cost or latency?
3. What does drift look like?
4. Can a sandbox be built?
5. If not, what then?
6. If outputs are too subjective, what criteria can be specified?

The answers decide each failure mode's check type (code, judge or monitor-only) and which
experiments (§7, E1–E14) to propose. Run no comparison before E1, the noise floor.

## Reference material

- `${CLAUDE_PLUGIN_ROOT}/references/process/`: the eval-creation process (principles, 3
  phases, 12 steps, the Q1–Q6 framework).
- `${CLAUDE_PLUGIN_ROOT}/references/eval-best-practices.md`: about 40 sourced findings from
  2025–2026.
- `${CLAUDE_PLUGIN_ROOT}/references/agent-contract.md`: how the agent is invoked.
