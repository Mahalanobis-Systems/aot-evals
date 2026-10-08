---
name: run
description: Commands C12-C17 of aot-evals - run the baseline k=3-5 times with per-trial outcomes and plane-B counters, read the variance band, run the operational sweep (E14) against budgets, compare a candidate with a paired test (gains, losses, McNemar, trade verdicts), audit coverage against the external taxonomy, and measure redundancy with a prune proposal; drift and online evaluation are guidance only for now. Use when status reports C12 unmet, after any prompt/skill/tool/model/harness change, or when someone asks whether a change made the agent better.
user-invocable: false
---

# run: what do the results say, and is the suite any good?

CLI: `"${CLAUDE_PLUGIN_ROOT}/bin/aot-evals"` (on PATH as `aot-evals`).

Paths below start at `<suite>/`, this agent's suite: `evals/agents/<agent>/`, beside its discovery report
(a one-agent repository may keep it in `evals/` itself). When the repository has several agents, pass
`--agent <agent>` to every `aot-evals` command.

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
- **Before the baseline**: the run's size (cases × k), its likely cost, and whether judges run.
- **C12**: the baseline per category, the variance band, and plane B against budgets.
- **C13**: gains and losses, and the verdict.
- **C14**: the empty coverage cells, for the owner to triage.
- **C15**: the prune proposal, for the owner to decide case by case.

For a full diagnostic of any of these, hand over to `report`.

## C12 baseline (E1, the noise floor)

```bash
aot-evals run --purpose baseline --k 5      # k = 3–5; refused below 3
aot-evals report                            # recompute report.json from the run
```

- Run on an **unchanged build**. The manifest records the agent and `evals/` commits and whether
  either is dirty. A dirty tree is not an unchanged build: commit first.
- Each (case, trial, attempt) becomes an `attempt` line in `runs/<id>/outcomes.jsonl`, and each
  check verdict a `check` line. Timeouts, rate limits and crashes are recorded and retried up to
  `max_attempts`. They are never scored as correctness failures and never dropped (G13).
- A run stops after 5 cases in a row end in an operational failure (`--stop-after N`, 0 never
  stops): a provider that has gone silent would otherwise turn every remaining case into a
  timeout, which can cost hours. A stopped run is never `finished`; find out why with the
  user, then run again. If the agent's own runtime is rate-limited (a free model tier), pace the
  run with `--pause-every N --pause-seconds S` rather than splitting it into several runs.
- Judge checks run with their primary backend on every applicable attempt. Calls cost money, so
  tell the user first. Use `--no-judges` for a code-only run, and `aot-evals judge apply` later.
  Only calibrated judges count toward pass rates (G3).
- If you can, run a second baseline on a different day: `aot-evals report --run A --run B`
  combines them, and the variance band then covers day-to-day drift as well.

Then read with the user, per category (never one suite-wide number):
- pass rate with its interval, n and k, labelled with its set;
- `pass^k`: 75% per trial is about 42% at k = 3;
- flaky cases (0 < passes < k): each is a finding to explain, and they set the k budget;
- the **variance band**: no later change inside it may be called an improvement, a regression
  or drift (M5);
- plane B against `budgets.yaml`.

**Gate:** a complete run with a complete manifest, a variance band per category, and a plane-B
baseline against budgets.

## E14 operational sweep

```bash
aot-evals ops                      # plane B for the latest baseline, against budgets
aot-evals ops --run <run-id> --json
```

Plane B is counters, not judgements:
- cost per **successful** task, not per run;
- p50 and p90 latency;
- cache-hit rate;
- errors by outcome code, with Wilson intervals;
- retries and kills.

An operational regression is a finding even when correctness hasn't changed. A cost jump at an
unchanged pass rate usually means a prompt-prefix edit broke the cache. Compare dollars, not
tokens: a tokenizer change alone has moved token counts by about 30%.

## C13 compare (E2): "did my change help?"

```bash
aot-evals run --purpose candidate --k 5 --variable model=claude-haiku-4-5   # one declared variable
aot-evals compare                         # latest candidate vs latest baseline
aot-evals report --candidate <run-id>     # the same comparison inside report.json (P7)
```

- **Declare one variable.** The candidate declares exactly one independent variable, of kind
  `prompt`, `skills`, `instructions`, `code`, `config`, `tools`, `model`, `harness`,
  `environment`/`fakes` or `simulator`.
  - The two manifests may differ only on the fields that kind covers. Anything else is refused
    (G7) and named.
  - `evals/` changes, such as committed runs and labels, never count as an agent change.
  - Commit agent changes before running: a dirty tree is refused, because what ran can't be named.
- **What it reports:**
  - gains and losses as separate case lists, plus cases that moved without flipping;
  - McNemar's exact test on the flips, and a bootstrap CI on the mean per-case delta;
  - the baseline variance band and the MDE (M7);
  - the same breakdown per set and per category;
  - plane-B deltas against budgets.
- **Verdicts:**
  - `better` / `worse`: a significant paired test outside the variance band;
  - `indistinguishable`: everything else, including "2 losses" (it takes at least 6 one-way
    flips to reach p < 0.05);
  - `trade`: better, but with a new budget breach (G11);
  - `worse`: an operational regression beyond budget at unchanged correctness.
- **When you report it:**
  - Lead with gains and losses. Never give a net delta alone.
  - Only the quality-estimate set's numbers may be called quality (G6).

## C14 coverage (E8)

```bash
aot-evals coverage
```

- The matrix is cases per (taxonomy entry × failure mode). Side-effect modes count on every case.
- Empty cells come first, and the authoring queue orders them by worth and cost.
- Triage every empty cell with the owner:
  - **Author a case**: go back to `build` C6.
  - **Not applicable**: record the reason in `taxonomy.yaml` under the entry's
    `not_applicable: {failure-mode: reason}`.
- Coverage is refused (G5) when the list has no external source, or was committed after the cases.

## C15 redundancy (E9)

```bash
aot-evals redundancy            # needs runs of at least two agent versions
```

**Classes.** Each case is always-pass, always-fail or discriminating, by its majority verdict per
version. Repeated runs of one build are pooled, never counted as versions.

**Discriminating fraction (M13).** Below the team's threshold (`discriminating_threshold` in
`allocation.yaml`, default 0.3), the command proposes:
- **keep** every discriminating case, plus every quality-estimate case (pruning those would bias
  the estimate);
- **keep regression guards**: always-pass cases needed so no coverage cell or category goes empty;
- **prune** the remaining always-pass error-finding cases;
- **review** always-fail cases (a broken case, or a persistent bug);
- **re-run every version-to-version paired test** on the pruned suite, to show the detectable
  effect is preserved;
- **list checks** that never fire, or only fire alongside another check (M11).

**Applying it.** The proposal is for the owner, case by case. Apply each accepted prune with
`aot-evals screen --drop <case> --reason "pruned: always-pass, redundant (C15)"`. The
discriminating set moves after every prompt change, so re-run this after one.

## C16–C17 (guidance only; not yet automated)

`aot-evals status` shows these as `later`.

- **C16 drift:**
  - Re-run the frozen set on a schedule and on every prompt, skill, tool, model or harness change.
  - Use the baseline's band as control limits.
  - After a prompt rewrite, re-derive the hard-case set: much of it can change.
- **C17 online:**
  - Roll out shadow → canary → online judging.
  - Sample 1–10% of traffic at high volume, 50–100% at low volume.
  - Exporting scores to the team's observability stack is opt-in.
  - Every new failure mode found online queues an offline case.
