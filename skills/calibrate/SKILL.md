---
name: calibrate
description: Commands C9-C11 of aot-evals - collect stratified human labels per judge (spreadsheet or one at a time), calibrate each binary judge by TPR/TNR with thresholds chosen on labels (never raw agreement), compare System One, generative and custom backends on the same labels (E5), and measure self-consistency and cross-family agreement (C11). Use when an agent's evals include judge checks, when choosing between a System One model such as Jev and an LLM judge, or when status reports C9-C11 unmet.
user-invocable: false
---

# calibrate: can the checks that need a model be trusted?

CLI: `"${CLAUDE_PLUGIN_ROOT}/bin/aot-evals"` (on PATH as `aot-evals`). Backend details:
`${CLAUDE_PLUGIN_ROOT}/references/judge-backends.md`.

Paths below start at `<suite>/`, this agent's suite: `evals/agents/<agent>/`, beside its discovery report
(a one-agent repository may keep it in `evals/` itself). When the repository has several agents, pass
`--agent <agent>` to every `aot-evals` command.

A judge is a check for **one failure mode**, asking **one binary, typed question**. Until it is
calibrated, it runs and its verdicts are recorded, but it never counts toward a headline number.
G3 greys it out in the report.

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
- **C9**: the labelling queue is ready, with how to fill it in. Stop until the labels are in.
- **Before any call that costs money**: the number of calls and the likely cost (`--dry-run`).
- **C10**: the calibration table and the backend E5 recommends, for the owner to accept.
- **C11**: the reliability results.

## 0. The judge spec (written in C8)

Copy `${CLAUDE_PLUGIN_ROOT}/templates/check_judge.md` to `<suite>/checks/judge/<check-id>.md`.
- **`question`**: one observable claim. For `noul`, set `detects` to say whether "yes" means the
  failure is present or the requirement is met.
- **`inputs`**: only what the judge needs, for example `[end.output, case.inputs.source]`.
  Never the agent's own claim that it succeeded (G10).
- **`backends`**:
  - the default is a **System One** backend, which is about $0.0004 per case;
  - add a **generative** backend from a *different family* than the agent;
  - optionally add a `command` backend for whatever the team already runs.
- **`primary`** is the backend whose verdicts count. E5 picks it (step 2).
- **`version`**: bump it on any change. A changed judge makes its calibration stale.

Judge calls cost money. `aot-evals run` judges every applicable attempt with the primary backend,
and `--no-judges` skips judging. Before any command that calls models, run
`aot-evals calibrate --judge X --dry-run`, then tell the user the number of calls and the likely
cost.

## 1. C9 label

```bash
aot-evals label queue --judge <id> --n 120 --open      # one item per case first, then differing trials
# the person labels on the page (<suite>/data/labelling/<id>.html): question, guidance and each
# input side by side, p / f keys; then Download CSV
aot-evals label import --judge <id> --csv <downloaded file>
aot-evals label status                                 # M10: counts, classes, interval widths
```

The queue is also `<suite>/checks/judge/<id>.queue.csv`, for a person who would rather fill the
`label` column in a spreadsheet. `aot-evals label page --judge <id> --open` rewrites the page from
it. Both are git-ignored: they carry the judge inputs.

- **Who labels.** Only a person labels. You can present items one at a time and record each
  answer with `aot-evals label add --judge <id> --item <item_id> --label pass --by <name>`, but
  never enter a label the person didn't give.
- **How many.** Target 100–200 labels per judge, stratified across every category the failure
  mode applies to, with both classes present. Under 60, the interval is too wide to act on (G3).
- **Where items come from.** If the baseline rarely fails on this mode, the labels will be almost
  all "pass" and TNR cannot be measured. Add items from other runs (an older version, a candidate,
  a deliberately degraded prompt) with `--run`.
- **Holdout.** Labels are split 80/20 into dev and holdout automatically. While iterating, look
  only at dev errors.

The queue file holds unreviewed agent output, so it is git-ignored. Labels are committed: each
holds exactly the judge input that was labelled, after a secret scan.

## 2. C10 calibrate, with E3 and E5

```bash
aot-evals calibrate --judge <id> --dry-run     # calls it would make
aot-evals calibrate --judge <id>               # every backend, on the same labels
```

Read the table with the user:
- **TPR and TNR are separate rates, each with a 95% interval.** Never report raw agreement.
- **κ and the confusion matrix.**
- **Holdout rates**, reported separately from dev.
- **For a probabilistic backend:**
  - the threshold is chosen on the labels and scored out of fold;
  - **ECE and the Brier score** show whether its probabilities mean anything. Until they do,
    don't route on its confidence.
- **Cost per judgement and latency.**
- **E5:** the line naming the cheapest backend that clears both floors. Set `primary` to it.

A judge is `calibrated` when its primary backend has at least 60 labels and TPR ≥ `min_tpr` and
TNR ≥ `min_tnr` (0.75 by default; the owner sets them in the judge file). An always-pass judge shows
TNR 0% and stays greyed.

**Iterating the judge:**
1. Read the dev items it gets wrong.
2. Change the question, options or inputs.
3. Bump `version`.
4. Re-run `calibrate`. Cached judgements for the old version are not reused.

When dev looks good, check holdout once. If holdout is much worse, the question has been fitted to
the dev labels. Rubrics drift as you grade (EvalGen), so the version history is part of the record.

## 3. C11 reliability (E4)

```bash
aot-evals reliability --judge <id> --backend jev --backend claude --m 3
```

Each item is judged in *m* fresh sessions on each backend. The two backends must be from
different families; System One versus generative is a good pair. The command reports:
- self-consistency per backend;
- three-level agreement (all / majority / none);
- cross-family agreement with κ;
- next to these, each backend's TPR/TNR on the same labelled items.

**Reliability is not validity.** Two judges agreeing can be a shared error, which is why the
report gives reliability its own column group and never uses it in place of TPR/TNR.

## 4. After calibration

- `aot-evals judge apply --judge <id> --run <run>` judges a run made before calibration, or made
  with `--no-judges`. The report re-thresholds stored scores with the calibrated threshold.
- `aot-evals report` uses a calibrated judge's verdicts when it computes pass rates, so P8 shows
  the judge in full.
- Re-calibrate after any change to the judge or its labels. `aot-evals status` flags stale
  calibrations under C10.
