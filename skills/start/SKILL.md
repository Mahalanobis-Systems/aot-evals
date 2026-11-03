---
name: start
description: The one command to remember for aot-evals. Says which of the three phases an agent's evals are in (Assess, Build, Judge), how far each kind of task can be trusted, what changed since the baseline, and carries on with the next step - the assessment when there is no discovery report yet (evals/agents/<agent>/discovery.md), otherwise build or judge. Use for "start aot-evals", "set up evals", "build evals for my agent", "where are we with our evals", "what's next", "is this suite any good", or after any change to the agent, its prompt, tools or model.
---

# start

The single entry point. Work out where the evals stand, say so in plain words, and hand over to
the skill for the next step. The method is `${CLAUDE_PLUGIN_ROOT}/docs/method.md`; §4.1 is the
part this skill follows. Pacing and wording: `${CLAUDE_PLUGIN_ROOT}/references/working-in-checkpoints.md`.

CLI: `"${CLAUDE_PLUGIN_ROOT}/bin/aot-evals"`. Call it by that full path: a bare `aot-evals` on
PATH can be an older install of the plugin, and its `status` speaks of gates only. It needs `uv`,
or Python ≥ 3.11 with PyYAML, and installs nothing into the team's project. With several agents in
the repository, pass `--agent <agent>` to every command. Below, `aot-evals` means that full path.

## 1. Which phase

1. Look for an existing suite in either layout: `evals/agents/*/agent.yaml`, or the older
   `evals/*/agent.yaml`. A suite in the older layout works as it is; offer `aot-evals migrate`,
   which moves it to `evals/agents/<agent>/` beside any discovery report (say what moves first,
   with `--dry-run`). **No suite and no `evals/agents/*/discovery.md`:** load `assess` and follow
   it. Stop here.
2. Otherwise run:

   ```bash
   "${CLAUDE_PLUGIN_ROOT}/bin/aot-evals" status
   ```

   It prints the phase, trust per category (untested, provisional, validated, with why), what
   changed since the baseline with the short path back for each change, and the next step.

## 2. Say where things stand, then publish it

Tell the person in three or four plain sentences: the phase, which kinds of task can be trusted
and which can't yet (and why), anything that changed since the baseline, and the next step. Then:

```bash
aot-evals activity --open
aot-evals checkpoint --title "Where <agent>'s evals stand" --open --summary-file - <<'MD'
The same, for someone who knows nothing of the method.
MD
```

Stop and wait for the person, unless they already asked you to carry on.

## 3. Hand over

| `status` says | Load |
|---|---|
| Phase: Build | `build`: the lightest Build first, then upgrades |
| Phase: Judge, and something changed since the baseline | the change's short path (below), then `judge` |
| Phase: Judge, a category is provisional | `judge`: the grader application, labels, agreement |
| Someone asks for a report, dashboard or scorecard | `report` |

**After a change** (status names each; method §4.1 has the table):

- **The agent changed** (prompt, skill, tool, model, harness): say the baseline no longer
  describes it. Run a candidate with one declared variable and compare (`build`, "Compare a
  change"), then have people label only what moved (`aot-evals agreement label queue --changed`,
  or the grader application's "Only what the last change moved").
- **It ran as a candidate and was compared**: it's a decision. Show the gains and losses, have the
  runs that moved labelled, then either run it as the new baseline or put the agent back.
- **A new kind of task** (a new category): checks for it, a baseline that includes it, then labels
  until it clears the floors. The other categories keep their trust.
- **Checks, cases, a judge or the standard changed**: re-grade the labelled runs offline
  (`aot-evals agreement`); a changed judge is recalibrated first. No agent runs needed.

Nothing refuses to run because a step is missing: a missing step lowers trust in the numbers it
covers, and the report greys them with the reason. Say so plainly when it happens.
