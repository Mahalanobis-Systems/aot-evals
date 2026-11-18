---
name: judge
description: Judge, the role of the people who know what good looks like in aot-evals (experts, support staff, end users) and whoever facilitates them, working alongside the owner and engineering. Settles the measurement model's error rates. Runs the grader application (aot-evals serve), where graders label whole runs blind, settle disagreements with rulings, hold the eval to their verdicts (its catch rate and clean pass rate against its floors), give every disagreement a cause, accept other correct answers, propose rules for the labeling standard, and label and calibrate AI judges until each counts within max_inflation; and says what goes back to engineering. Use when start says the graders have the next step, when someone wants to label runs, onboard a grader, calibrate or update a judge, or asks whether the eval agrees with people.
---

# judge: measure how wrong the grader is

Judge is the role of the people who know what good looks like: experts, support staff, end users.
They settle one of an eval's four parts, the **measurement model's error rates**, and they can
start as soon as an eval has runs to label, while engineering is still adding cases and checks.

A grader (a check, a judge, or the eval as a whole) is measured by its confusion matrix against
people's labels: the 2×2 table of its verdicts against theirs, with a failure as the positive (TP,
FP, FN, TN in `${CLAUDE_PLUGIN_ROOT}/docs/estimators.md#terms`). Read down its columns, that gives
two numbers: its **catch rate** (of the runs a person fails, the share it fails) and its **clean
pass rate** (of the runs a person passes, the share it passes). Its off-diagonal cells, the false
positives and false negatives, are the disagreements that each need a cause. An eval is **trusted** when its spec is complete, every
counted judge counts, the eval against people meets its floors, and the quality set is the size its
decision rule needs (`aot-evals status`). Graders do this in the grader application, without an
engineer, until a fix to the agent, a case or a check is needed; those go to the engineering inbox.

**Speak in consequences.** You do the statistics; graders and owners get what they mean: "label
about 30 more runs that failed before the catch rate means anything", "this judge needs about 80
more labeled failures before its scores count", "the eval and your reviewers disagree mostly on
refunds: fix that check first". Explain intervals, bounds or inflation only when asked, and then
point to `${CLAUDE_PLUGIN_ROOT}/docs/statistics.md`.

Reference: `${CLAUDE_PLUGIN_ROOT}/docs/method.md` §7 (checks, judges and labels) and §11 (the
gates); why each count holds, when asked: `${CLAUDE_PLUGIN_ROOT}/docs/statistics.md` §3.2–§3.6 and
§4.2. Terms: `${CLAUDE_PLUGIN_ROOT}/docs/estimators.md#terms`. Pacing and words:
`${CLAUDE_PLUGIN_ROOT}/references/working-in-checkpoints.md`. Backends:
`${CLAUDE_PLUGIN_ROOT}/references/judge-backends.md`. `aot-evals` is
`"${CLAUDE_PLUGIN_ROOT}/bin/aot-evals"`; the application serves one eval at a time, so pass
`--eval <id>` when the agent has several.

## 1. Start the application and onboard the graders

```bash
aot-evals --eval <id> serve --open
```

It prints a link with a session token and listens on 127.0.0.1 only. Give each grader their own
link by adding `&labeller=NAME`. For graders on other machines, use `--host 0.0.0.0` on a network
you trust: anyone with the link can label. Everything they do is written to the eval's files;
commit them like any other change.

Tell each new grader, in one message: the labeling standard (`<agent>/labels/standard.md`) in plain
words; that they judge each whole run from scratch, with no check verdict or expected answer shown;
that a fail needs a note saying what went wrong; and that their first runs are a warm-up whose
settled answer they see after each label.

## 2. Decide how many labels before looking

The eval's floors are in its spec (`measurement.people`): a stated `floors: {catch, clean}`, or null
for the `max_inflation` reading, with a `margin` (default 0.10). With `labels_per_kind: auto` the
count of each kind (failed runs, passed runs) is fixed from the margin before anyone looks:
`aot-evals --eval <id> agreement label status` says how many of each are needed and how many exist.
Labels count per kind, so 60 labels with 2 failures measure the catch rate on 2 runs. Collect that
many, then read the rates once: labeling until a rate clears is how an eval gets trusted by luck
(problem 12). Labels come from the queue, which draws them; runs picked because they looked wrong
would bias the person-anchored rate.

## 3. What graders do, tab by tab

- **Label runs.** "Next for me" gives a warm-up, then runs nobody has labeled, with one in four that
  someone else labeled so agreement between people can be measured. After a change to the agent,
  "Only what the last change moved" labels just the cases whose verdict flipped.
- **Agreement, between people.** Where labelers differ, the run has no verdict until someone rules;
  the ruling's reason is what the next grader sees in their warm-up, so write it for them. Read
  agreement **on failures**, not overall: two people who agree on 90 of 100 runs can agree on none of
  the failures. Gwet's AC1 and the specific agreements say this; κ misleads when most runs pass. Low
  agreement on failures means the standard is unclear: fix the standard before the eval.
- **Agreement, the eval against people.** "Re-grade" re-checks every labeled run from its record
  with the checks as they stand: no agent runs, no judge calls. Every dev disagreement needs a
  cause:
  - `wrong-expectation`: the case expected one wording or state too narrowly. When the person passed
    the run, "This answer is also correct" adds it as another correct answer and screens the case
    again; if a check still rejects it, it becomes a check bug for engineering.
  - `missing-requirement`: nothing checks what the person failed it for (engineering adds a failure
    mode or a requirement and its check).
  - `check-bug`: a code check decides wrongly (engineering).
  - `judge-error`: an AI judge decided wrongly (§5).
  - `out-of-scope` or `accepted`, each with why.

  Fix the eval, not the labels: a label changes only when its labeler changes their mind.
- **Rules.** When rulings keep going the same way, propose the pattern as a rule. The owner accepts
  it into the shared standard, and the runs it could flip are listed for a recheck.
- **Judges.** Label items for each AI judge, then recalibrate (§5). The application shows the number
  of new judge calls and asks before spending anything.
- **Engineering inbox.** Drafted cases, triaged disagreements that need a fix to a case or a check,
  and changes to the agent that need running. Hand it to engineering as it is.

Checkpoint when the eval against people is first measured, and when an eval becomes trusted.

## 4. When the eval isn't trusted yet

`aot-evals status` lists each open reason with its command. The ones graders clear:

| Status says | Do |
|---|---|
| The eval is not held to people yet | Label whole runs to the count of each kind (§2), then `aot-evals --eval <id> agreement` |
| Labelers disagree on runs nobody has ruled on | Rule on them in Agreement |
| The eval against people is stale | Re-grade (the checks or the labels changed since it was measured) |
| A rate is below its floor | Read the dev disagreements by cause and fix the biggest cause first |
| A rate clears its floor but its lower bound is more than the margin below it | Label the short kind: `agreement` says about how many more would do |
| Dev disagreements without a cause | Give each a cause |
| A judge doesn't count (`judge_floor`, `judge_calibration`) | §5 |

One run in five is held out by a hash of its id. Fix only what the dev runs show, and look at the
holdout once the dev rates clear the floors. If holdout is much worse, the fixes were fitted to dev:
label a fresh batch before claiming anything.

When a rate clears its floor on too few runs, say it in plain words ("87% of 15 failing runs could
really be as low as 62%; label about 40 more failing runs") and don't present the eval as settled.
`agreement` also prints the **person-anchored pass rate**: the labels combined with the eval's
verdict on every other run (prediction-powered inference). It is the closest thing to "what people
would say" and the number to quote to an owner beside θ̂.

## 5. AI judges: label, calibrate, count

A judge is a check for one failure mode that asks one typed question. Until its catch and clean
pass rates are measured it runs and is recorded, but it never counts, and a judge that feeds the
eval's quantity leaves θ̂ null.

```bash
aot-evals --eval <id> label queue --judge <jid> --n 120 --open   # or the Judges tab
aot-evals --eval <id> label status --judge <jid>                 # labels per kind, and how many each needs
aot-evals --eval <id> calibrate --judge <jid> --dry-run          # the calls it would make; say the cost first
aot-evals --eval <id> calibrate --judge <jid>                    # catch and clean pass rates per backend
aot-evals --eval <id> reliability --judge <jid> --backend <a> --backend <b> --m 3
```

- **Labels per kind.** The catch rate rests only on items a person failed, the clean pass rate only
  on items a person passed; at a rate of 0.8, ±10 points needs about 60 of that kind. For a rare
  failure, the clean pass rate matters most: put most labels on passing items once the catch rate
  has enough failures behind it. If the baseline rarely fails on this mode, add items from another
  run (an older version, a deliberately weakened prompt) with `--run`; catch rate is about true
  failures, wherever they come from.
- **Does it count?** `aot-evals --eval <id> report` reads each counted judge against
  `measurement.max_inflation`: how many times more cases its errors cost than a code check's, at
  its lower bounds and the eval's failure rate on its mode. A judge good enough for common failures
  can be refused for rare ones. More labels of the short kind raise its lower bounds; a better
  question or backend raises its rates.
- **Read catch and clean pass rates separately**, each with its interval, never raw agreement: at a
  95% pass rate a judge that always says "pass" agrees with people 95% of the time and catches
  nothing. A probabilistic backend's threshold is chosen on the labels; don't route on its
  confidence until ECE and the Brier score say it means something. Set `primary` to the cheapest
  backend that counts.
- **Updating a judge**: read the dev items it gets wrong, change the question, options or inputs,
  bump `version`, and recalibrate. A changed judge is a new instrument with unknown error rates, and
  a revision of the eval: its baseline is run again. A disagreement triaged `judge-error` comes here:
  add the run's judge input to the judge's labels and iterate.
- **Reliability is not validity.** A judge that agrees with itself, or with a judge from another
  family, hasn't shown that it's right; only labels show that. Calibrated judges aren't a trusted
  eval either: that is the eval against people above.
- A generative judge comes from a different model family than the agent's, and a pairwise one judges
  both orders.

## 6. What goes back to engineering

Say it as a list, each with its cause and the cases it came from: check bugs and missing
requirements (new or fixed checks), wrong expectations a check still rejects, drafted cases, judges
that don't count and what would make them count, and the eval's open trust reasons that only
engineering can clear (a short quality set: `plan --write` and `draw`; a spec field). Labeling
goes on meanwhile. Load `build` when the person asking is the one who will make the fixes.
