---
name: build
description: Build, the second of aot-evals' three phases, for engineering. Settles three of an eval's four parts around the agent contract - the sampling design (a frame of real traffic, a quality set drawn at random with each case's inclusion probability, a bug-finding set against a coverage list, cluster keys), the measurement model's checks (one counted check per failure mode, code first, trials) and the decision rule (the test, margin or bar, α, power, gates, constraints) - and finishes the estimand Assess drafted (use cases, shares, costs, the decision, one eval end to end plus one per separately shipped subagent). Ends with a baseline under the current spec and the grader application handed to the people who will label. Also decides on a change to the agent (a candidate run, the paired comparison, the decision). Use when start says the phase is Build, when someone asks to wire an agent up for evals, write eval cases or checks, run a baseline, or compare a change to the agent.
---

# build: the agent contract, the design, the checks and the decision rule

Build is engineering's phase. It ends with each eval of the agent running under a complete spec:
the agent runs from a command, the quality set is drawn from real traffic, every failure mode has
one counted check, the decision rule is written down, and a baseline has run under the current
spec. Then the grader application goes to the people who will label (`judge`).

Nothing refuses to run because a field is missing: an incomplete spec still runs, and the report
nulls the numbers that depend on the missing fields, with the reason. `aot-evals validate` lists
every missing and invalid field; `aot-evals status` says what to do next.

Reference: `${CLAUDE_PLUGIN_ROOT}/docs/method.md` (§3 where evals go, §4 files, §5 the spec, §6
cases, §7 checks, §8 runs). The statistics behind each number:
`${CLAUDE_PLUGIN_ROOT}/docs/statistics.md`. Terms: `${CLAUDE_PLUGIN_ROOT}/docs/estimators.md#terms`.
Pacing, words and the rules you hold the team to: `${CLAUDE_PLUGIN_ROOT}/references/working-in-checkpoints.md`.
`aot-evals` is `"${CLAUDE_PLUGIN_ROOT}/bin/aot-evals"`; pass `--agent <agent>` with several agents
and `--eval <id>` with several evals. Paths start at `<agent>/`, `evals/agents/<agent>/`.

## 1. Draft the evals

```bash
aot-evals build          # creates the evals, drafts what it can, prints each eval's checklist by part
```

From the discovery report it creates the end-to-end eval (`<agent>/end-to-end/`), drafts agent.yaml's
`components` from the report's `boundaries`, and creates an eval for each subagent with its own
context that ships on its own (rule 3). It drafts the use cases from the report (costs left
unstated), the coverage list, and one code check on every case: the world ends as the case expects
(`checks/code/end-state-matches.py`). It prints, per eval, the agent contract and each of the four
parts, done or with its first missing field. Work down that list in the order below. A route
behind a router is a use case end to end, with a use case gate when its model ships on its own;
never give it an eval of its own.

## 2. The agent contract

Read `${CLAUDE_PLUGIN_ROOT}/references/agent-contract.md`. Most agents need a small entry point that
reads the case on stdin and prints the result JSON; set it as `invoke.command` in agent.yaml (a
component eval's own `invoke` lives in its eval.yaml and calls the component with a handoff).

- **Seed and observe** wherever the agent changes state, with the sandbox's fakes in `<agent>/env/`:
  checks grade what `observe` prints, never what the agent says it did. Where the agent can't run
  safely, replay recorded runs (`aot-evals replay`).
- **A call site with tools of its own** (a coding harness, a model with web search) can read the
  repository, cases included: set `invoke.isolate: true`.
- **Run it once**: `aot-evals run --purpose smoke --question "<a real request, scrubbed>"`, and read
  the raw output in `<eval>/runs/<id>/raw/` with the owner.
- The inventory in agent.yaml: the model actually used per call site, from the traces; every tool,
  with credential names only.

## 3. The estimand: finish what Assess drafted

In each eval's `eval.yaml` (`estimand:`), with the owner:

- **Use cases** partition the population: each request belongs to exactly one. Each needs a
  `definition`, an `example` trace and a `share` measured from the frame (`share_source`), summing
  to 1. A situation ("ambiguous", "a tool failed") is not a use case; it is a coverage entry.
- **The cost of a failure** in each use case, as a ratio to the others, stated by the owner.
  `weights: cost` makes θ track the expected cost of failures (statistics §1.1); `weights: traffic`
  is right only when costs are about even, and the spec should say so. An unstated cost is unknown,
  never 1, and leaves θ̂ null.
- **The decision**: `action`, `owner`, `cadence`. A component eval's decision is its own team's,
  never a copy of the end-to-end eval's (rule 1).
- **The unit**: `system` for end-to-end; `component`, `component` and `boundary` for a component
  eval, with the component listed in agent.yaml (§1).

## 4. The sampling design

**The frame.** Import the team's trace export, never a vendor API:

```bash
aot-evals import FILE --source "<system: dataset>" --query "<the filter>" --window 2026-10-01..2026-10-31
```

Set it as `estimand.population.frame`. Each row needs an `id`, a `use_case` and the case fields
(method §6). Offer the operational sweep, which needs no labels: `aot-evals ops --export <id> --field
cost_usd=… --field latency_ms=…`; set the constraints from it later. A **component eval's frame is
the handoffs it receives**, never written by hand: `aot-evals --eval <component eval> handoffs`
extracts them from the end-to-end traces (each row's `handoffs` list), or `import FILE --handoffs-of
COMPONENT` imports handoffs captured as they happened. `handoffs --scan` shows which components the
traces hand off to.

**The coverage list first.** Write `<eval>/coverage.yaml` from a document made for another purpose
(the product spec, the help center's topics, the tool surface), crossed with situations, never from
the cases, and **commit it before any case**: coverage is measured only against a list that came
first. Here, and only here, you may search the web for public benchmarks newer than the catalog, as
a source of grading designs and situations, never of cases.

**The plan, then the draw.** The quality set's size comes from the decision rule (§6), not from a
constant:

```bash
aot-evals plan --assumed-rate 0.92        # threshold rules; paired rules: --flip-rate 0.1 (or after a comparison)
aot-evals plan --write                    # plan.yaml: targets per use case and pool
aot-evals draw --dry-run                  # what the draw would take
aot-evals draw                            # the seeded, stratified draw, with each case's π
```

Before a baseline the plan can't know the rate or the flip rate; say so, and use the owner's best
guess, marked as one. Oversample a small use case that matters (`design.quality_set.oversample`); π
records it and the estimate weights it back down. A trace that can't be used (PII that can't be
scrubbed, a duplicate) leaves the frame with `draw --skip ID --reason "<why>"`, and the next one in
the seeded order replaces it. **Never write, pick or trim a quality case by hand**, and never add
one that wasn't drawn: it would stop the quality set from standing for the traffic.

**The bug-finding set** is written by hand, to find failures: hard and rare cases, the policy
corners, the empty cells of the coverage grid. Start from `${CLAUDE_PLUGIN_ROOT}/templates/case.json`
with `pool: bug_finding`. It never enters θ̂, however many cases it holds.

- **A person confirms every expected end state** (`{"world": …, "output": …}`). Derive expected
  values from the start state (a count, a total, a list of ids), never type them in. Never ship an
  uncorrected model draft as ground truth.
- **Scrub before writing**: names to placeholders, emails to `example.com`, no tokens or keys.
  `aot-evals validate` blocks on secrets and warns on likely PII.
- **Clusters.** Give cases that share a template, a source trace or a fixture the same value of the
  eval's `cluster_key`: they fail together, and the report counts them as one piece of evidence
  (rule 9). Five or fewer clusters can't show a significant change at all. A template that feeds the
  quality set must not feed the bug-finding set (rule 10).

**Screens.** `aot-evals screen`: per case, the reference end state passes, doing nothing fails, a
non-answer fails, and doing nothing while claiming success fails. With a reference answer, add two
or three other correct wordings (`expected_end_state.output_variants`). A person reads each case
(`aot-evals screen --read-by NAME --case ID`). Unscreened or uncommitted cases stay out of θ̂.
Where a use case's end state only a judge can grade, `screen --judges` counts the calibrated judges.
Commit the cases.

## 5. The measurement model: the checks

In `measurement.failure_modes`, one entry per way a run can go wrong, each with **exactly one
counted check** (rule 12); other checks on the same mode go in `diagnostics`.

- **Code first** (rule 14), from `${CLAUDE_PLUGIN_ROOT}/templates/check_code.py`: `check(start, end,
  case) -> (bool, detail)`, graded against the goal on the world `observe` printed, never the
  agent's claim. One failure mode per check (rule 11).
- **Check every fact a prose answer states**: a false number inside a right-sounding answer is the
  failure suites miss most.
- **A side-effect mode on every eval** (`side_effect: true`): something changed that nobody asked
  for.
- **A judge only where code can't decide**, from `${CLAUDE_PLUGIN_ROOT}/templates/check_judge.md`:
  one typed question about one failure mode, from a different model family than the agent. Until the
  Judge phase measures its catch and clean pass rates it does not count, and a judge that feeds the
  quantity leaves θ̂ null. Set `measurement.correction` (`rogan_gladen` when its labels are on past
  runs, `ppi` when people label the report's own runs) and `max_inflation` (default 2.0).
- **The labeling standard** (`<agent>/labels/standard.md`): the rules a person applies when failing
  a run. Fit them with the owner; walk them for every case, each becoming a `requirement` naming the
  checks that decide it, or a line in `rules_not_applicable` with why.
- **Trials**: `trials: 3`, or `auto` to take k from the baseline's variance split. More cases
  usually narrow the interval faster than more trials.

## 6. The decision rule

With the owner, before any candidate runs, in `decision_rule:`:

- **The test**: `non_inferiority` with a `margin` (no worse than today by more than the margin),
  `superiority` (better), or `threshold` with a `bar` (a rate on the right side of a fixed value).
  "No significant difference" is not "no worse" (rule 19).
- **α and power** (defaults 0.05 one-sided and 0.80; 0.025 where a bad change is costly or hard to
  undo), and `looks: fixed`. `sequential` and `optimizer_holdout` are not computed yet and leave the
  decision unknown.
- **Use case gates** for a use case that matters but is too rare to move θ̂, and that someone would
  act on by itself (rule 20); every route whose model ships on its own needs one.
  `combine: all` (every gate must pass) needs no multiplicity correction.
- **`also_requires`** on a component eval: the end-to-end eval with a non-inferiority test (rule 27).
  A better part isn't a better agent.
- **Constraints**: cost per success and latency p90 per use case, from the operational sweep, not
  from guesses. A gain that breaks a budget is a trade.

Commit eval.yaml. A decision rule changed after the results is refused unless it was on record first.

## 7. The baseline, then hand over to Judge

```bash
aot-evals validate         # nothing missing or invalid
aot-evals build --run      # each eval that can run: smoke if needed, a baseline, the report
```

Or per eval: `aot-evals --eval <id> run --purpose baseline`, then `aot-evals --eval <id> report`.
Then `aot-evals status`: each eval should be in Judge, provisional. Re-run `plan --write` now that
the baseline has measured the rates and spreads, and draw more if the quality set is short.

Start the grader application and give each grader their own link:

```bash
aot-evals serve --open     # then add &labeller=NAME to the link for each grader
```

Checkpoint "The loop is running" (`references/working-in-checkpoints.md`): θ̂ with its interval and
weights, the per-use-case table, what the decision rule says and how many cases would decide it,
how much results move between trials, and the link. Then load `judge`.

## 8. Decide on a change

After any change to the prompt, skills, tools, model or harness, commit it and run a candidate with
one declared variable, on the same cases:

```bash
aot-evals --eval <id> run --purpose candidate --variable prompt=<what changed>   # or --model <id>
aot-evals --eval <id> compare
aot-evals --eval <id> agreement label queue --changed      # people label only what moved
```

`compare` refuses runs made under another estimand, design or measurement (re-run the baseline),
and a decision rule changed without a record. Lead with gains and losses, never a net number
alone; then the decision: `pass`, `fail`, `insufficient` (with the cases that would decide it) or
`unknown` (with why), each gate's result, `also_requires`, and any new budget breach. For a
component change, run the same change end to end too: its decision stays unknown until the
end-to-end eval's candidate runs exist. If the change ships, run it as the new baseline.

## 9. Keep the evals current

- **Coverage**: `aot-evals coverage` lists the empty cells against the coverage list; write a case
  or record why it doesn't apply.
- **Expand or revise** (estimators §9): more cases drawn from the same frame and seed, or more
  bug-finding cases, keep the version. A new use case, a new weight, a changed check or a new judge
  is a revision: bump the major version and re-run the baseline.
- **The traffic mix moves**: re-measure the shares on a schedule and after every routing change; a
  routing change means new handoff frames for the component evals (rule 26).
- **Pruning** for cost removes only bug-finding cases, and only while coverage holds; the quality set
  is changed only by drawing again (rule 25).
