---
name: judge
description: Judge, the third of aot-evals' three phases, for the people who know what good looks like (product owners, experts, end users) and whoever facilitates them. Runs the grader application (aot-evals serve), where graders label whole runs blind, settle disagreements with rulings, hold the suite to their verdicts (catch rate and clean pass rate per category), give every disagreement a cause, accept other correct answers, propose rules for the labelling standard, and label and calibrate AI judges; and says what goes back to engineering. Use when start says the phase is Judge, when someone wants to label runs, onboard a grader, calibrate or update a judge, or asks whether the suite agrees with people.
---

# judge: hold the suite to what people decide

Judge is the graders' phase. Its goal is that every category is **validated**: the suite fails
what people fail and passes what they pass, at or above the floors (85% by default), measured on
runs nobody fitted the suite to. Graders do it in the grader application, without an engineer,
until a fix to the agent or a check is needed; those go to the engineering inbox.

Method: `${CLAUDE_PLUGIN_ROOT}/docs/method.md` §4.2 (the bench and the application), §5 (judges).
Pacing and words: `${CLAUDE_PLUGIN_ROOT}/references/working-in-checkpoints.md`. Backends:
`${CLAUDE_PLUGIN_ROOT}/references/judge-backends.md`.

## 1. Start the application and onboard the graders

```bash
aot-evals serve --open
```

It prints a link with a session token, and listens on 127.0.0.1 only. Give each grader their own
link by adding `&labeller=NAME`. For graders on other machines, use `--host 0.0.0.0` on a network
you trust: anyone with the link can label. Everything they do is written to the suite's files;
commit them like any other change.

Tell each new grader, in one message: the labelling standard (`labels/standard.md`) in plain words;
that they judge each run from scratch, with no check verdict or expected answer shown; that a fail
needs a note saying what went wrong; and that their first runs are a warm-up whose settled answer
they see after each label.

## 2. What graders do, tab by tab

- **Label runs.** "Next for me" gives a warm-up, then runs nobody has labelled, with one in four
  that someone else labelled so agreement between people can be measured. After a change to the
  agent, "Only what the last change moved" labels just the cases whose verdict flipped.
- **Agreement, between people.** Where labellers differ, the run has no verdict until someone
  rules. The ruling's reason is what the next grader sees in their warm-up, so write it for them.
  Low agreement between people (κ under about 0.6) means the standard is unclear: fix the
  standard before the suite.
- **Agreement, the suite against people.** "Re-grade" re-checks every labelled run from its record
  with the suite as it is now: no agent runs, no judge calls. Each disagreement needs a cause:
  - `wrong-expectation`: the case expected one wording or state too narrowly. When the person
    passed the run, "This answer is also correct" adds it as another correct answer and screens
    the case again. If a check still rejects it, it becomes a check bug for engineering.
  - `missing-requirement`: nothing checks what the person failed it for (engineering adds the
    requirement and its check).
  - `check-bug`: a check decides wrongly (engineering).
  - `judge-error`: an AI judge decided wrongly (section 4).
  - `out-of-scope` or `accepted`, each with why.

  Fix the suite, not the labels: a label changes only when its labeller changes their mind.
- **Rules.** When rulings keep going the same way, propose the pattern as a rule. The owner accepts
  it into the standard, and the runs it could flip are listed for a recheck.
- **Judges.** Label items for each AI judge (pass means the item doesn't show the failure the judge
  is for), then recalibrate. Recalibrating calls the judge only for items it hasn't judged yet; the
  application shows the number of calls and asks before spending anything.
- **Engineering inbox.** Drafted cases, triaged disagreements that need a fix to a case or check,
  and changes to the agent that need running. Hand it to engineering as it is.

Checkpoint when a category's agreement is first measured, and when one becomes validated.

## 3. When a category isn't validated yet

`aot-evals status` says why for each category. The usual reasons, and what to do:

| Why | Do |
|---|---|
| No run in it has been labelled | Label: at least 60 runs suite-wide, with 15 of each kind (`labels/floors.yaml` changes this) |
| Labellers disagree on runs nobody has ruled on | Rule on them in Agreement |
| The measurement is stale | Re-grade |
| A rate is below its floor | Read the dev disagreements by cause and fix the biggest cause first |
| Dev disagreements without a cause | Give each a cause |

One run in five is held out by a hash of its id. Fix only what the dev runs show, and look at the
holdout once the dev rates clear the floors. If holdout is much worse, the fixes were fitted to
dev: label a fresh batch before claiming anything.

## 4. AI judges: calibrate, update, trust

A judge is a check for one failure mode, asking one binary, typed question. Until it is calibrated
it runs and is recorded, but it never counts toward a headline number.

```bash
aot-evals label queue --judge <id> --n 120 --open   # or the Judges tab
aot-evals calibrate --judge <id> --dry-run          # the calls it would make; say the cost first
aot-evals calibrate --judge <id>                    # every backend, on the same labels
aot-evals reliability --judge <id> --backend <a> --backend <b> --m 3
```

- **Labels:** 100 to 200 per judge, stratified across its categories, with both kinds present.
  Under 60, the interval is too wide to act on. If the baseline rarely fails on this mode, add
  items from another run (an older version, a deliberately weakened prompt) with `--run`.
- **Read TPR and TNR separately**, each with its interval, never raw agreement. A probabilistic
  backend's threshold is chosen on the labels; don't route on its confidence until ECE and the
  Brier score say it means something. Set `primary` to the cheapest backend that clears both
  floors.
- **Updating a judge:** read the dev items it gets wrong, change the question, options or inputs,
  bump `version`, and recalibrate. Cached judgements for the old version aren't reused. A
  disagreement triaged `judge-error` comes here: add the run's judge input to the judge's labels
  and iterate.
- **Reliability is not validity.** Two judges agreeing can be a shared error. Calibrated judges
  aren't a validated suite either; that is the whole-run agreement above.
- A generative judge comes from a different model family from the agent's.
