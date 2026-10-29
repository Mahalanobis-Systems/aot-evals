---
name: run
description: Commands C12-C17 and C19 of aot-evals - run the baseline k=3-5 times with per-trial outcomes and plane-B counters, read the variance band, check the suite's verdicts on whole runs against a person's (C19 agreement: catch and clean pass rates, every disagreement triaged), run the operational sweep (E14) against budgets, compare a candidate with a paired test (gains, losses, McNemar, trade verdicts), audit coverage against the external taxonomy, and measure redundancy with a prune proposal; drift and online evaluation are guidance only for now. Use when status reports C12 unmet, after any prompt/skill/tool/model/harness change, or when someone asks whether a change made the agent better.
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
- **C19**: the whole-run labelling page is ready; stop until the labels are in. Then the
  agreement table and every disagreement with its proposed cause, for the owner to confirm.
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
  user, then carry it on with `aot-evals run --resume <run_id>` rather than starting over. The
  same applies to a run whose process died. Resume is refused if the agent, the suite, the env or
  the judges changed since the run started; then start a new run. Pairs that ended in an
  operational failure before the stop are kept as recorded, not run again. If the agent's own runtime is rate-limited (a free model tier), pace the
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

## C19 agreement: does the suite fail what a person would fail?

Every earlier screen looks at a part: C7 at one case's states, C10 at one judge's narrow
question. A suite can clear all of them and still pass runs a person would fail, because no check
looks at what the person failed them for, or fail correct runs because an expected answer only
matches one wording. In our experiments a calibrated suite caught 69% of the failures a person found while
plain Claude Code caught 73–82%; every miss traced to a part nobody had checked against a whole
run. C19 measures the whole.

```bash
aot-evals agreement label queue --open          # one run per case from the latest baseline
# the person labels each whole run pass/fail with a note, on the page; then Download CSV
aot-evals agreement label import --csv <file> --by <name>
aot-evals agreement                             # re-grade the labelled runs; rates and disagreements
aot-evals agreement regrade --reproduces --run <baseline>   # can recorded runs be re-graded?
```

- **Who labels.** Only a person, from scratch: the page shows the request, the answer and what
  changed, never the checks or the expected state. The standard (`labels/standard.md`) is the
  guidance; when the person makes a new ruling, add it there.
- **How many.** At least 60 runs with 15 of each kind (`labels/floors.yaml` changes this). One
  per case first; add a second trial per case where the agent's runs differ.
- **Re-grading.** Labels are about the agent's runs, not the suite, so they outlive suite
  versions: `aot-evals agreement` re-grades every labelled run from its raw record with the suite
  as it is now. Judges reuse recorded verdicts for their current version; `--call-judges` calls
  them for the rest (costs money; say so first). Run `regrade --reproduces` once: a code check
  that gives a different verdict on the raw record reads something besides (start, end, case),
  such as the live system, and must be fixed before its verdicts can be trusted.
- **Every dev disagreement gets a cause** in `labels/triage.yaml`:

  ```yaml
  <run>/<case>.t3.a0: {cause: missing-requirement, note: "no check that the list is complete"}
  ```

  Causes: `missing-requirement` (add the requirement and its check: C6, C8),
  `wrong-expectation` (fix the case: C6), `check-bug` (C8), `judge-error` (iterate the judge on
  its dev errors: C10), `out-of-scope` or `accepted`, each with why. Propose a cause for each,
  then confirm them with the owner at the checkpoint. Fix the suite, not the labels: a label
  changes only when the person changes their mind.
- **Holdout.** One run in five is held out by a hash of its id. Iterate on dev disagreements only;
  report holdout once the dev floors are met. If holdout is much worse, the fixes were fitted to
  dev. Label a fresh batch before claiming anything new.

**Gate:** enough labels of both kinds, a measurement current for this suite and these labels, dev
catch rate and clean pass rate at or above their floors (85% by default), and every dev
disagreement triaged. Until then the report fails G14, and every comparison is marked
provisional.

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
