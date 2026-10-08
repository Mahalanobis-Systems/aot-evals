---
name: scope
description: Commands C0-C4 of aot-evals - import the team's trace export, inventory the agent (agent.yaml, model per call site, stable window, invocation), build the external coverage taxonomy, categorize traces with worth/cost matrix/observed share, and decompose each category into failure modes with check types and plane-B budgets. Use when starting evals for an agent, or when status reports C0-C4 unmet.
user-invocable: false
---

# scope: what the agent does, how it is used, and how it can fail

CLI: `"${CLAUDE_PLUGIN_ROOT}/bin/aot-evals"` (on PATH as `aot-evals`). Run `aot-evals status`
after each step: it checks the exit gate.

Paths below start at `<suite>/`, this agent's suite: `evals/agents/<agent>/`, beside its discovery report
(a one-agent repository may keep it in `evals/` itself). When the repository has several agents, pass
`--agent <agent>` to every `aot-evals` command.

Background: `${CLAUDE_PLUGIN_ROOT}/references/process/phase-1-understand-the-system.md`,
`phase-2-understand-the-usage.md`, and steps 8 and 10 of `phase-3-build-the-evals.md`.

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

Checkpoints in this skill:
- **C0**: what the export holds (fields, join keys, counts), with the E14 operational sweep. This
  is the team's first result, so get here fast.
- **C1**: after the smoke run, with the inventory for the owner to correct.
- **C2**: the drafted taxonomy, for the owner to edit before it is committed.
- **C3**: the drafted categories, with shares, for the owner to confirm, merge and rename, and to
  set worth and costs.
- **C4**: the eval design. Title it `"Eval design for <agent>"`: it is the document the team
  reviews before any case is written.

Throughout, record each claim as **confirmed** (seen in traces, runtime records or code) or
**inferred**, with its source. Where config and traces disagree, the traces win.

## C0 import

The team exports from their observability stack: a trace dump, a dataset download, or CSV/JSONL.
You never call a vendor API. Ask for:
- the source (system and dataset);
- the query or filter used;
- the time window. It must cover the agent's stable window (C1) and give at least 10 runs per
  category.

```bash
aot-evals import path/to/export.jsonl --source "Datadog LLM Obs: prod-agent" \
  --query "service:agent env:prod" --window 2026-07-01..2026-09-30 --id 2026q3-traces
```

The file is copied to `<suite>/data/exports/<id>/`, which is git-ignored. Its manifest entry
(source, query, window, rows, date, sha256) goes in `data/export.manifest.json`, which is
committed. **Gate:** every downstream number traces to a manifest entry.

Then write down the export's real structure: fields, join keys, counts. Check every later
assumption against it. Offer the week-one operational sweep straight away:

```bash
aot-evals ops --export 2026q3-traces --field category=tags.task --field cost_usd=metrics.cost \
  --field latency_ms=duration_ms --field outcome=status --ok-value ok
```

## C1 inventory → `<suite>/agent.yaml`

Fill every field of the template. The decisive ones:
- **`models`: the model actually used per call site.** That includes side calls (routing,
  "should I respond", titles, compaction). Take it from the traces, record how in
  `models_evidence`, and set `model_family`.
- **`version_history` and `stable_window`.** List every behaviour-changing edit: prompt or
  skill, stored runtime prompt, model or provider, harness upgrade. Ask the owner "how long has
  this been stable in production?" and check the answer against the history; `evidence` says how.
- **Does any model call site have its own tools?** A "model call" that is really an agent
  (`opencode run`, `claude -p`, a coding harness, a model with web search) can search the web,
  run commands and read files. Such a harness can answer from web pages retrieval never
  returned, add latency no trace of yours shows, and find and read a case file. Ask the owner and check the harness's own session log. If yes: list those tools under
  `tools`, set `invoke.isolate: true`, and have `observe` record its tool calls per run where the
  harness logs them.
- **`invoke`: how to run it.** Read `${CLAUDE_PLUGIN_ROOT}/references/agent-contract.md`. Most
  agents need a small entry point that reads the case on stdin and prints the result JSON. Add
  `seed`/`observe` hooks wherever the agent changes state. For side effects on files, `observe`
  must cover the whole working tree (`aot-evals snapshot`), not just the agent's folders.
- **The agent must not see the cases.** `evals/` sits in the repository the agent runs in. With
  `invoke.isolate: true` the agent runs from a copy without it. Every run checks for exposure
  either way: eval files changed during the run, or agent output naming a case file, make the
  run a C12 problem.

**Gate:** the agent runs once, end to end, from its command:

```bash
aot-evals run --purpose smoke --question "a real trigger from the export, scrubbed"
```

Read the raw output in `<suite>/runs/<id>/raw/` with the user. Check that `model_ids` matches
`models`.

## C2 taxonomy → `<suite>/taxonomy.yaml`

The coverage list is written **for some other purpose**: the product spec, the API or tool
surface, help-centre topics, a job-task taxonomy, a regulator's duties. Start from
`${CLAUDE_PLUGIN_ROOT}/templates/taxonomies/` if a template fits the agent's vertical. Otherwise
draft the list from that outside source and have the owner edit it.

- Name the source document and the date it was read.
- **Never derive it from `<suite>/cases/`, and never from the categories you are about to build.**
  Coverage against your own cases is always 100% (G5).
- **Commit `taxonomy.yaml` before the first case.** The gate checks git ancestry.

## C3 categorize → `<suite>/categories.yaml`

Sort the export's traces into categories, one category per trace (process step 8):
1. **Heuristics first.** Code rules for the obvious, simple categories (for example "nothing new
   arrived"). Base each rule on the input, not on what the agent did, and cross-check it: a broken
   connection also reports zero new items.
2. **A model for the rest.** Group the remaining traces by what the agent was asked to do and what
   it did. Write a small script that labels every trace in the export and counts each category.
3. **The owner confirms, merges and renames**, sets the `simple` flag and assigns `worth`
   (low/medium/high).
4. **A cost matrix row per category.** For each failure kind (`incorrect`, `unexecuted_claim`,
   `no_response`, `partial`, `slow`, …), the cost is none/low/medium/high.
5. **`observed_share`** comes from the count, with `share_source` set to the export id.

Watch for filters in front of the agent: a "should I respond" gate drops messages before the agent
runs. **Gate:** every category has a definition, example, worth, simple flag, cost row and
measured share; shares sum to 1; "Other" is under 10%.

## C4 decompose → `<suite>/failure_modes.yaml` and `<suite>/budgets.yaml`

Within each category, go feature → scenario → failure mode (Hamel Husain's decomposition). For
each failure mode:
- `check_type`: `code` (decidable from end state), `judge` (needs a calibrated binary judge) or
  `monitor` (no criteria the owner would sign off on; watched online, not evaluated). Use the
  framework's Q1 and Q6.
- `cost_cell`: a key in each of its categories' cost rows.

Always add a **side-effect** mode (`side_effect: true`, `categories: ["*"]`): nothing outside
the request changed, nothing was sent without approval. It runs on every case.

Then set **plane-B budgets** per category, or as a default. Scheduled agents budget cost;
agents someone waits on budget latency. Available keys: `cost_per_success_usd`,
`cost_per_run_usd`, `latency_p50_ms`, `latency_p90_ms`, `error_rate`, `tokens_per_run`,
`cache_hit_rate_min`. Base them on the E14 sweep, not on guesses.

**Gate:** every failure mode names its category, check type and cost cell, and `budgets.yaml`
covers every category. Then go to `build`.
