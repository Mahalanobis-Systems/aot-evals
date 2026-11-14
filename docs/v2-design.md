# aot-evals 2.0 design

*Working design for building aot-evals 2.0; once 2.0 ships, [method.md](method.md) and the
reference pages take over from it. It turns the model in [estimators.md](estimators.md) into
files, fields and outputs. Until 2.0 is released, method.md describes 1.x. Terms follow
[estimators.md](estimators.md#terms); "spec" here always means an eval's `eval.yaml`.*

Every field below traces to one of the four parts of an eval (estimand, sampling design,
measurement model, decision rule) or to the agent contract. A field that traces to neither is
process, and is kept only where a part needs it.

**What does not change.** The agent contract ([agent-contract.md](../references/agent-contract.md))
is untouched: the stdin and stdout fields, the hooks (`setup`, `seed`, `observe`, `reset`), the
outcome codes in `outcomes.py`, and the per-result field names (`case_id`, `trial`, `attempt`,
`outcome`, `cost_usd`, `tokens_input`, `tokens_output`, `latency_ms`, `model`, `judge_model`). An
agent that runs under 1.x runs under 2.0 unchanged. Only the suite around it changes.

## Contents

1. [Layout](#1-layout)
2. [The eval spec: eval.yaml](#2-the-eval-spec-evalyaml)
3. [Cases](#3-cases)
4. [Checks and judges](#4-checks-and-judges)
5. [Runs](#5-runs)
6. [report.json v2](#6-reportjson-v2)
7. [Commands](#7-commands)
8. [Migration from 1.x](#8-migration-from-1x)
9. [The online-store example](#9-the-online-store-example)
10. [Decisions to confirm](#10-decisions-to-confirm)

## 1. Layout

An agent system has one folder, and each eval of it ([estimators §1](estimators.md#1-where-evals-go))
has a folder inside it:

```
evals/agents/<agent>/            the agent system
  agent.yaml                     inventory of the system and how to invoke it end to end
  discovery.md                   the Assess report (unchanged)
  env/                           sandbox fakes, shared by the system's evals
  data/                          imported traces: the frames evals draw from
  labels/standard.md             the labeling standard, shared
  journal/                       activity log (unchanged)
  <eval>/                        one eval: one estimand
    eval.yaml                    the eval spec: the four parts
    coverage.yaml                the external coverage list (1.x taxonomy.yaml)
    plan.yaml                    generated: case targets per use case (1.x allocation.yaml)
    cases/<use_case>/<id>.json
    checks/code/<id>.py
    checks/judge/<id>.md         plus <id>.labels.jsonl, .calibration.json, .reliability.json
    labels/                      whole-run labels, rulings, triage for this eval
    runs/<run-id>/
    report/
```

- **Every agent has an end-to-end eval**, by convention in `<agent>/end-to-end/`. Its unit is the
  whole system and it invokes the agent through `agent.yaml`'s `invoke`.
- **A component eval** (a subagent behind a context boundary) has its own folder, named for the
  component, and its own `invoke` in `eval.yaml` that calls the component directly with a handoff.
- **What is shared** across a system's evals: `env/` (the sandbox), `data/` (the frames), the
  labeling standard and the journal. **What is not:** cases, checks, judges and their calibration,
  labels, runs and reports. A judge's error rates belong to the population it was calibrated on.
- `--eval <id>` selects an eval, as `--agent` selects an agent. With one eval it is optional.

## 2. The eval spec: eval.yaml

`eval.yaml` is the four parts written down. An eval is **complete** when every required field is
filled. An incomplete eval still runs; its report lists the missing fields under `spec.missing`,
and the numbers that depend on them are null with the reason. That replaces most of 1.x's
command gates: the question is "what is missing from the spec", not "which numbered step is unmet".

The loader (`spec.py`) sorts what it finds into four lists, each entry `{field, why, blocks[]}`,
where `blocks` names the report keys and commands the field is needed for (`run`, `draw`, `plan`,
`estimate`, `use_cases`, `measurement`, `decision`, `comparison`):

- **missing**: a required field left out or empty, or a reference to something not there yet (a
  frame with no import in `data/export.manifest.json`, a check with no file, an eval named in
  `also_requires` that doesn't exist).
- **invalid**: a field that is there but cannot mean anything (shares that don't sum to 1, an
  unknown test, two counted checks on one mode, a decision rule on another quantity).
- **notes**: block nothing (an unknown key, with the field it probably meant; a `bar` a
  non-inferiority test ignores; a correction where every gate must pass).
- **defaults**: each stated default the loader filled, so the report can say "α 0.05 by default".

An eval is complete when `missing` and `invalid` are both empty.

The values below are the store's refund eval ([§9](#9-the-online-store-example)).

```yaml
eval: refunds
version: 1.0                       # major.minor; see estimators §9 for which changes are major

estimand:
  unit:
    kind: component                # system | component
    component: refund-subagent     # for a component: what it is, named in agent.yaml
    boundary: handoff from the orchestrator's refund route
  quantity: failure_rate:breaks-policy   # pass_rate | failure_rate:<failure mode id>
  population:
    frame: refund-handoffs-2026-10 # an import id in data/export.manifest.json
    window: 2026-10-01/2026-10-31
    environment: env/              # the sandbox; its hash goes in every manifest
  use_cases:
    - id: full-refund
      definition: Refund of a whole order inside the policy window.
      example: tr_8812             # a trace id from the frame
      share: 0.80
      cost: 50                     # what one failure costs, in any unit, relative to the others
    - id: partial-refund
      definition: Refund of some items, or a partial amount.
      example: tr_9017
      share: 0.15
      cost: 50
    - id: gift-card
      definition: Refund to a gift card instead of the original payment.
      example: tr_9230
      share: 0.05
      cost: 20
  share_source: refund-handoffs-2026-10   # where the shares were measured
  weights: cost                    # traffic (w = share) | cost (w ∝ share × cost) | {use_case: w}
  decision:
    action: ship a change to the refund subagent
    owner: refunds team
    cadence: weekly

design:
  quality_set:
    selection: stratified_random   # the only selection allowed for the quality set
    seed: 1234
    oversample: {gift-card: 4}     # draw a use case at k times its share; π records it
  bug_finding_set:
    coverage: coverage.yaml        # the external list it is checked against
  cluster_key: order_template      # case field that marks related cases (estimators rule 9)

measurement:
  failure_modes:
    - id: breaks-policy
      description: Refunds an order the policy does not allow, or refuses one it does.
      use_cases: "*"
      check: policy-judge          # the one check that counts (rule 12)
      diagnostics: []              # other checks on this mode, reported, never counted
    - id: wrong-amount
      use_cases: "*"
      check: amount-matches
    - id: unrequested-change
      use_cases: "*"
      check: no-side-effects
      side_effect: true            # at least one counted side-effect check is required
  trials: 3                        # or: auto (from the measured variance split, rule 16)
  correction: ppi                  # none | rogan_gladen | ppi
  max_inflation: 2.0               # how many times more cases a judge may cost (statistics §3.3)
  people:
    floors: {catch: null, clean: null}   # the eval against people; null: from max_inflation, as for a judge
    margin: 0.10                   # floors are shown with this non-inferiority margin (statistics §4.2)
    labels_per_kind: auto          # or a number; auto sizes from the margin

decision_rule:
  test: threshold                  # superiority | non_inferiority | threshold
  quantity: failure_rate:breaks-policy   # defaults to estimand.quantity; must match it
  bar: 0.05                        # threshold only
  margin: null                     # non_inferiority and superiority: the smallest change that matters
  alpha: 0.05
  power: 0.80
  looks: fixed                     # fixed | sequential | optimizer_holdout
  combine: all                     # all: every gate must pass | any: one gate alone triggers the action
  multiplicity: none               # none | holm | benjamini_hochberg; needed only with combine: any (statistics §4.6)
  use_case_gates: []                # use cases with their own rule (rule 20); each: {use_case, test, ...}
  also_requires:                   # other evals that must pass for this decision (estimators rule 27)
    - eval: end-to-end
      test: non_inferiority
      margin: 0.02
  constraints:                     # budgets; limits, not part of θ (rule 24)
    default: {cost_per_success_usd: 0.05, latency_p90_ms: 8000}
    use_cases: {}

invoke:                            # component evals only; the system eval uses agent.yaml
  command: ["python", "agent/refunds.py", "--handoff"]
  cwd: .
  timeout: 60
```

**Field rules.**

| Field | Part | Required | Rule |
|---|---|---|---|
| `estimand.unit` | Estimand | yes | `system` once per agent; `component` needs `component` and `boundary` |
| `estimand.quantity` | Estimand | yes | |
| `estimand.population.frame` | Estimand | yes | an import id; a component's frame holds handoffs (rule 4) |
| `estimand.use_cases[]` | Estimand | yes | `id`, `definition`, `example`, `share`; shares sum to 1 ± 0.02 |
| `use_cases[].cost` | Estimand | when `weights: cost` | a positive number; null means not stated |
| `estimand.weights` | Estimand | yes | an unstated weight is unknown, never 1 |
| `estimand.decision` | Estimand | yes | `action` and `owner` |
| `design.quality_set` | Design | yes | `seed`; `oversample` optional |
| `design.cluster_key` | Design | yes | a case field; `id` means every case is its own cluster |
| `measurement.failure_modes[]` | Measurement | yes | exactly one counted `check` per mode |
| `measurement.trials` | Measurement | yes | ≥ 3, or `auto` |
| `measurement.correction` | Measurement | when any check is a judge | |
| `measurement.max_inflation` | Measurement | when any check is a judge | sets the floor on each judge (statistics §3.3); default 2.0 |
| `measurement.failure_modes[].side_effect` | Measurement | on at least one mode | that mode's counted check catches changes nobody asked for |
| `decision_rule.test` | Decision rule | yes | |
| `decision_rule.margin` or `bar` | Decision rule | yes | whichever the test needs |
| `decision_rule.quantity` | Decision rule | no | defaults to `estimand.quantity`; any other value is invalid |
| `decision_rule.alpha` | Decision rule | yes | one-sided, above 0 and below 0.5; default 0.05; 0.025 where a bad change is costly or hard to reverse (statistics §4.5) |
| `decision_rule.power` | Decision rule | yes | default 0.80 |
| `decision_rule.looks` | Decision rule | yes | default `fixed` |
| `decision_rule.combine` | Decision rule | yes | `all` (default): the action needs every gate (the headline and each use case gate) to pass; `any`: one gate alone triggers it. `also_requires` always must pass (rule 27) |
| `decision_rule.multiplicity` | Decision rule | when one gate alone can trigger the action | required with `combine: any` and more than one gate, and `none` is then invalid; otherwise defaults to `none`, the intersection–union case (statistics §4.6) |
| `decision_rule.also_requires` | Decision rule | for a component eval | must name the agent's end-to-end eval (rule 27) |
| `measurement.people.floors` | Measurement | no | `{catch, clean}`, each a rate or null; null (the default) means from `max_inflation`, as for a judge |
| `measurement.people.margin`, `labels_per_kind` | Measurement | no | defaults 0.10 and `auto` |
| `invoke` | Agent contract | for a component eval | `command` as argv; a system eval has none (it uses `agent.yaml`) |
| `decision_rule.constraints` | Decision rule | no | budget keys as in 1.x `budgets.yaml` |

**What the generated plan holds.** `plan.yaml` (1.x `allocation.yaml`) is written by
`aot-evals plan --write`: per use case and pool, the target from the decision rule's power (with each
judge's inflation factor), the minimum, the optimum allocation of the rest, what exists, and how
many are screened. Humans edit only `status` and `reason`, as in 1.x.

- **The headline need** is the independent cases the rule's test needs at its α and power:
  `stats.threshold_n` for a threshold test, with the judge's catch and clean rates written into the
  test, or `stats.paired_n` for a superiority or non-inferiority test, from the flip rate, times each
  counted judge's inflation factor. A judge without a current calibration is planned at
  `max_inflation`, the most the spec lets it cost.
- **Minimums**: each use case gate's own need, and each oversampled use case's factor × share × N.
- **N** is raised until the optimum allocation (proportional to the weights until a baseline
  measures spreads and per-trial costs) still holds the headline need once its unequal weighting
  (`stats.allocation_design_effect`) and the clusters' measured design effect are counted.
  `--total N` fixes the budget instead.
- **What it can't know it says.** Before a baseline, a threshold test needs the rate expected under
  the alternative (`--assumed-rate`, the value of the quantity) and a paired test the flip rate
  (`--flip-rate`, from an A/A rerun or the last comparison); without them the targets are null and
  the reason names the flag. Every assumption is written under `assumptions` with its source.
- Bug-finding rows have no target: that pool is sized by its coverage list, not by power.

## 3. Cases

A case keeps the 1.x shape. Changes:

| Field | 2.0 | 1.x |
|---|---|---|
| `use_case` | required; equals the folder name | `category` |
| `pool` | `quality` or `bug_finding`, required | `set`: `quality_estimate` or `error_finding` |
| `draw` | quality pool only: `{frame, seed, index, inclusion_prob}`, written by `aot-evals draw` | none; cases were picked by hand |
| `cluster` | the value of the eval's `cluster_key`; defaults to the case id | optional `cluster` |
| `failure_modes` | as 1.x | |
| `coverage_entries` | as 1.x `taxonomy_entries` | `taxonomy_entries` |
| `trigger`, `inputs`, `start_state`, `followups`, `expected_end_state` | unchanged: these are what the agent receives | |
| `requirements`, `rules_not_applicable`, `provenance`, `screen` | unchanged | |

For a component eval, `trigger` and `inputs` hold the handoff as the component receives it.

**Quality cases come from `aot-evals draw`, never by hand.** It draws from the frame with the
eval's seed, stratified by use case and oversampled as declared, records `inclusion_prob` on each
case, and logs every skip with its reason. A quality case without `draw`, or with a `draw` from
another frame or seed than the spec's, is refused from the estimate (rule 6). Bug-finding cases
carry no `draw` and never enter θ̂ (rule 5); a `draw` on one is ignored, with a note.

- **The frame's rows.** Each row of the frame's import is a JSON object with an `id` (or
  `trace_id`), a `use_case`, and the fields the case needs (`trigger`, `inputs`, `start_state`,
  `followups`, `expected_end_state`, `requirements`, `rules_not_applicable`, `failure_modes`,
  `coverage_entries`, and the `cluster_key` field). Only those are copied into the case, with
  `provenance` pointing at the trace. Rows with no use case, or one the spec doesn't name, are
  counted in the draw log and never drawn.
- **The order.** Each use case is drawn as the first n of a seeded random order of its rows
  (`stats.draw_order`, one stream per use case). So drawing more later extends the same draw and
  rewrites the earlier cases' π (an expansion), and resizing one use case never changes another's.
  n comes from `--n USE_CASE=N`, else `plan.yaml`'s target, else the last draw.
- **Skips.** `draw --skip TRACE_ID --reason R` takes a row out of the frame; the next row of the same
  order replaces it, and π counts the rows that remain. Skips, frame sizes and the frame's hash are
  in `<eval>/draw.json`; a new frame or seed starts a new log.
- **Removing cases.** A quality case the draw no longer holds (a smaller n, a skip, a new seed) is
  removed only with `--prune`; without it `draw` refuses, so no one trims the quality set by hand.
- **Clusters.** A case's cluster is its `cluster`, else the value of its `cluster_key` field, else its
  id. Clusters shared by the two pools are listed in the report (`design.clusters`), since the pools
  must be disjoint by cluster key (rule 10).

## 4. Checks and judges

Code checks are unchanged (`check(start, end, case) -> (bool, detail)`; `USES_AGENT_REPORT` is
refused). Judge files keep their front matter, with these changes:

- `min_tpr` and `min_tnr` go (a 2.0 judge that still sets them gets a note). A judge's floor comes
  from `measurement.max_inflation` and the eval's failure rate: the judge passes when its inflation
  factor at the current rate, computed from its lower confidence bounds on catch and clean, is at or
  under the limit (`measurement.judge_floor`).
  - **The bounds** are one-sided Wilson lower bounds at the decision rule's α.
  - **The current rate** is the mode's failure rate in the report's runs (the weighted Hájek mean
    over the counted quality cases of the use cases the mode applies to), corrected with the
    judge's point rates and kept half a failure away from 0 and 1 over the trials it rests on.
  - **A judge with no current calibration** (none, stale, or labels of one kind only) has unknown
    error rates and does not count either (rule 13). With no scored run yet the floor is `unknown`,
    and `plan` counts the judge at `max_inflation`.
  - A counted judge that feeds the quantity (its mode's check, for `failure_rate:<mode>`; every
    counted judge, for `pass_rate`) and does not count leaves θ̂ null with the reason.
- Calibration reports **catch rate** and **clean pass rate** (1.x TNR and TPR), each with its
  interval, its one-sided lower bound and its count of labels per kind (`labels_per_kind:
  {fail, pass}`), plus J and the inflation factor its lower bounds imply at 50%, 20%, 10% and 3%
  (`inflation_at_lower_bounds`). The 1.x `tpr`/`tnr` keys stay beside them. A 2.0 calibration's
  `status` is `calibrated` when it has labels of both kinds and a verdict on each. Whether the
  judge may count is the floor above, read by `report`, since it depends on the eval's rate.
- A judge belongs to one eval. Copying a judge into another eval copies its definition, not its
  calibration.

## 5. Runs

The manifest becomes `aot-evals/run-manifest@2`:

- adds `eval` (id and version), `spec_sha`, one hash per part (below), and `spec_complete`;
- `case_set` adds each quality case's `inclusion_prob` (null for one without a valid draw);
- `spec_issues` (the fields missing or invalid when the run started) replaces 1.x `unmet_gates`;
- `fakes_sha256` hashes the agent system's shared `env/`, and `standard_sha` its shared standard;
- removes `simulator`;
- everything else as 1.x, including the resume rules.

`outcomes.jsonl` attempt lines rename `category` to `use_case` and `set` to `pool`. Check lines add
`counted`: true for a failure mode's counted check, false for a diagnostic (rule 12). An attempt's
`passed` is its counted code checks' verdict. The agent contract's per-result fields keep their
names. `run` takes k from `measurement.trials`, `--use-case` in place of `--category`, and for a
component eval invokes the component through `eval.yaml`'s `invoke`.

**`trials: auto`** (rule 16) runs k = 3 until a baseline under the current spec measures the split
of variance between cases and within them (`stats.variance_components`). From then on k is the
two-stage optimum k* = √(case_cost × within ÷ between) (Cochran 1977 §10.6), with `case_cost` = 1
(a new case is taken to cost one trial more than its own trials), clamped to [3, 10]
(`stats.trials_for_split`). The manifest records `trials: {spec, recommended, source, k}`, and an
explicit `--k` still wins.

**Which runs can be compared.** The spec says what a run's number means, so two runs compare only
when they measured the same thing. `spec_sha` holds one hash per part, `{estimand, design,
measurement, decision_rule}`, taken over that part of `eval.yaml`. The `measurement` hash also
covers the eval's check files and judge prompts, but not their calibration files. `compare`, and
any report that sets a candidate against a baseline:

- **refuses** when the `estimand`, `design` or `measurement` hash differs. That is a revision
  ([estimators §9](estimators.md#9-changing-an-eval)): the two scores are different quantities. The
  message names the part that changed and says to re-run the baseline under the current spec.
- **refuses** when only the `decision_rule` hash differs, unless the change was on record before
  the first run decided on (the candidate's, or the reported runs' for a threshold rule with no
  candidate). Moving the bar or the margin after seeing results is problem 12 (rule 21). Either
  record counts:
  - **a commit of `eval.yaml`.** The record is the oldest commit in the newest unbroken stretch of
    eval.yaml's history whose `decision_rule` hash is the current one; an uncommitted edit is no
    record. When the evals live in the agent's repository, it counts when it is an ancestor of
    each decided run's agent commit or of the evals commit the run recorded (both are stamped
    when the run starts; the agent commit ignores evals/, so a rule committed after the agent
    change is an ancestor only of the evals commit). When the evals live in a repository of their
    own, the agent's commits can't order it, so it counts when its commit date is no later than
    the first decided run's start.
  - **a journal entry**, `aot-evals --eval <id> log --kind decision "why"`, which records the eval
    and its current `spec_sha`; it counts when its `decision_rule` hash is the current one and its
    time is no later than the first run decided on. The journal is not committed, so the entry
    lives where the decision was made, which is why a commit counts too.
- **refuses**, as 1.x G7, when the two sides are not one build apart: they may differ only on the
  manifest fields the candidate's declared variable covers.
- **compares** when nothing but the cases or the calibrations changed. Adding cases drawn from the
  same frame and seed, or bug-finding cases, is an expansion. Recalibrating a judge refines its
  measured error rates without changing what it measures. A new judge, or a changed judge prompt,
  is a new instrument (rule 13) and changes the `measurement` hash.

## 6. report.json v2

`"schema": "aot-evals/report@2"`. Keys may be added within v2, never removed or renamed. Unknown
values are null with a reason, never 0, and nothing is pre-rounded.

| Key | Holds | Part |
|---|---|---|
| `schema`, `generated`, `runs`, `refused` | as 1.x | |
| `eval` | `{id, version, unit, quantity, decision}` | Estimand |
| `spec` | `{complete, missing[{field, why, blocks[]}], invalid[…], notes[…], defaults[{field, value}]}` (§2) | all |
| `estimate` | the headline: `{theta, ci, ci_method, se, quantity, weights{use_case: w}, weights_source, estimator: "hajek", corrected, n_cases, n_clusters, n_effective, k, null_reason}` | Estimand, design |
| `use_cases` | one row per use case and pool: 1.x category rows, with `share`, `cost`, `weight`, `inclusion_prob_range`, and `estimate` (the use case's Hájek μ̂ of the quantity, quality pool only) | Estimand, design |
| `design` | `{quality{n, drawn, frame, seed, oversample, strata, skips[], refused[]}, bug_finding{n, coverage}, clusters{n, n_bug_finding, cluster_key, design_effect, icc, largest, mean_size, shared_with_bug_finding}, cases_without_pool[]}` | Design |
| `measurement` | `{failure_modes[{id, check, type, use_cases, observed_rate, catch, clean, j, labels{fail, pass}, inflation, inflation_at_lower_bounds, floor{status, reason, rate, max_inflation}, corrected_rate, feeds_estimate}], eval_vs_people{catch, clean, all, labels{fail, pass}, labels_needed, floor, failure_rate, stale}, person_anchored{ppi}, variance{icc, between, within, k_recommended}, people{pairs[{ac1, kappa, pass_agreement, fail_agreement}]}, trials, max_inflation, correction, gates[{id, detail}]}` | Measurement |
| `decision` | `{test, quantity, bar, margin, alpha, power, looks, combine, multiplicity, subject, result: "pass" \| "fail" \| "insufficient" \| "unknown" \| "trade", reasons[], null_reason, interval, detectable_effect, cases_needed, headline{…}, gates[{gate, use_case, result, p, p_adjusted, …}], also_requires[{eval, result, reason, runs, gate}], constraints{status, breaches[]}, look{n, prior[], recorded}, refused}` | Decision rule |
| `comparison` | as 1.x, with Δθ̂ design-weighted, the verdict read from the paired sign-flip test per cluster, `per_use_case` adjusted p-values, `bug_finding` flips apart, and `variance_band` removed; null without `--candidate` | Decision rule |
| `coverage`, `redundancy`, `cases`, `conditions`, `next_actions` | as 1.x (`conditions.simulator` removed) | |
| `checks` | as 1.x, with `catch` and `clean` in place of `tnr` and `tpr` | Measurement |

**How the estimate is computed** (estimators §7). A trial scores 1 for `pass_rate` when every
counted check of the modes that apply to its case passed, and for `failure_rate:<mode>` when that
mode's check failed; a trial missing a counted verdict is unscored. ŷ is a case's mean over its
scored trials. θ̂ = Σ w_s μ̂_s over the use cases with weight, μ̂_s the Hájek mean of ŷ over the
quality cases that count (a valid draw, screened, committed). Its interval is normal, with each use
case's linearized variance summed over clusters and floored at an Agresti–Caffo-adjusted binomial
variance (`stats.stratified_hajek`, statistics §2.3). `theta` is null, with `null_reason`, when the
spec blocks the estimate, a weight is unstated, there is no run, a use case with weight has no
scored case, the runs are refused, a counted judge that feeds the quantity does not count (§4), or
the correction lacks its measurement. `refused` is set when a run's manifest is not v2 or its
`estimand`, `design` or `measurement` hash differs from the current spec's: those numbers are a
different quantity. `corrected` says whether the correction was applied, and `corrected_reason`
says why not (`correction: none`, or a code check that has nothing to correct).

**The correction** (`measurement.correction`) applies after the uncorrected θ̂, which stays in
`estimate.uncorrected`. `rogan_gladen` is linear, so it corrects the weighted θ̂ as a whole and each
use case's μ̂ on its own (`use_cases[].estimate_corrected`), with a delta-method interval that adds
the calibration's uncertainty (`stats.rogan_gladen_rate`). Its grader is the quantity's judge for
`failure_rate:<mode>` (the judge's calibration), and the eval against people for `pass_rate` (every
whole-run label, `eval_vs_people.all`). `ppi` combines the trials a person labeled with every graded
trial, each weighted by its case's share of θ̂ (`stats.ppi_weighted`, PPI++ with power tuning);
its labels are the whole-run labels for `pass_rate` and the quantity judge's labels that name a
trial of the report's runs for `failure_rate`, and it assumes they were drawn at random. A
`failure_rate` whose check is code has nothing to correct. A correction whose measurement is missing
leaves θ̂ null with the reason, never silently uncorrected.

**The measurement gates** (`measurement.gates`) each have an id, so a fixture can trigger exactly
one: `judge_floor` (refused, or no rate to read it at yet), `judge_calibration` (no current
calibration), `people_unmeasured`, `people_stale`, and agreement.json's own: `people_labels` (a kind
short of its count), `people_disputes`, `people_floor`, `people_triage`.

**How the decision is computed** (estimators §6, statistics §4; `decision.py`). The decision is
about the candidate's runs when `report --candidate` or `compare` gives them, else about the
reported runs, so a paired rule with no candidate is `unknown`.

- **Each gate** (the headline, each `use_case_gates` entry) is one one-sided test at α. A
  **threshold** test reads θ̂ (or the use case's μ̂) as the report computed it, corrected where the
  spec corrects. A rate as graded is tested by its one-sided Clopper–Pearson bound at Kish's
  effective size over the design weights, with the count θ̂·n_eff (Korn & Graubard 1998;
  `stats.rate_bound_test`; statistics §4.1), so with equal weights it is the exact binomial test
  and 0 failures in 32 cases do not clear a 5% bar. A corrected estimate keeps a one-sided normal
  bound (`stats.bound_test`), since it is not a count and its se carries the calibration. When a
  counted judge feeds an uncorrected estimate, the bar is read on the grader's scale,
  (1 − clean) + J·bar, at the judge's point rates (for a pass rate, the eval's against people). A
  **superiority** test (H0 Δ ≤ 0) and a **non-inferiority** test (H0 Δ ≤ −margin) are one-sided
  sign-flip tests on the paired deltas, the candidate's ŷ minus the baseline's per counted
  quality case, negated for a failure rate, each case carrying its design weight in θ̂ so the mean
  delta is Δθ̂, with signs flipped per cluster (`stats.superiority_test`,
  `stats.non_inferiority_test`). A grader with J < 1 shrinks a true change to J·Δ, so a
  non-inferiority margin is tested on the grader's scale at J's one-sided lower bound; with J
  unknown (a pass rate graded by judges, the eval not yet held to people) the gate is unknown.
- **A gate's result** is `pass` when its test rejects at α; `fail` when the two-sided 1 − 2α
  interval sits at or beyond the null on the wrong side (shown worse than the margin, shown no
  better, shown on the wrong side of the bar); `insufficient` otherwise, with `cases_needed`, the
  cases like these that power 1 − β at the measured spread would take (`stats.cases_for_spread`;
  for an exactly tested rate, the larger of the cases its bound needs to clear at the measured
  rate and `stats.threshold_n`, both at the measured n/n_eff). When the point estimate is already
  past the null (a drop past the margin, no gain, θ̂ on the wrong side of the bar), the reason
  says so first: "the refund pass rate dropped 33 points, past the margin of 5; too few cases to
  show it at α 0.05";
  and `unknown` with its reason when there is nothing to test (rule 13 included: a judge that feeds
  the quantity and does not count leaves every gate unknown, never a pass). `detectable_effect` is
  (z₁₋α + z_power)·se on the true scale.
- **Gates combine** by `combine`: `all` is the worst of fail, unknown, insufficient, pass, with no
  correction (intersection–union); `any` adjusts the p-values by `multiplicity` and passes when one
  gate passes at its adjusted p. `also_requires` must pass either way: each entry is tested on the
  other eval's candidate runs that declare the same variable at the same agent commit, against that
  eval's baseline, and is unknown (naming the command) until they exist.
- **Constraints** are read per use case on the decided runs, each breach marked `new` when the
  baseline did not have it. Gates that pass with a breach are a `trade`.
- **Looks.** Under `looks: fixed` `report` and `compare` append each decision with a result to
  `<eval>/report/looks.jsonl`, keyed by the decision rule's hash and the change (variable and commit).
  Deciding the same change again on other runs is a second look and leaves the result unknown.
  `sequential` and `optimizer_holdout` need intervals not built yet, so their decisions are unknown.
- **The comparison's verdict** is the two-sided sign-flip test at 2α (so `better` is exactly the
  superiority test passing at α), with its 1 − 2α interval; a new budget breach makes `better` a
  `trade` and `indistinguishable` a `worse`, as in 1.x. Per-use-case rows are diagnostics, with
  p-values adjusted by `multiplicity`, or Benjamini–Hochberg when it is `none`.

**Removed from v1:** `validity` (compounded validity), `online` (always null), `regime`,
`sets` (now `estimate`, `design` and `use_cases`), `categories` (now `use_cases`), the `simple`
flag, `conditions.simulator`, and gates G9 and C16/C17. `gates` becomes `spec.missing` plus the
evidence checks that remain (manifest integrity, screening, trial completeness, isolation), keyed
by part.

`report/agreement.json` keeps its file and its role (gates read it), renames `catch`/`clean`
consistently, and adds `labels_per_kind`, `labels_needed`, the margin-based evidence and `gates`.
For a 2.0 eval its floors come from `measurement.people`. A stated floor is met when the dev
point estimate reaches it and its 95% lower bound is within `margin` of it (statistics §4.2,
`stats.floor_evidence`). A null floor is the `max_inflation` reading, as for a judge, at the eval's
whole-run failure rate. `labels_per_kind: auto` fixes each kind's count before looking: the Wilson
±margin size at the stated floor, or at 50% (the widest) where the floor is null.

## 7. Commands

Unchanged in purpose: `start`, `doctor`, `init`, `status`, `validate`, `import`, `screen`, `run`,
`label`, `agreement`, `serve`, `replay`, `calibrate`, `reliability`, `judge apply`, `ops`,
`snapshot`, `compare`, `coverage`, `redundancy`, `log`, `activity`, `checkpoint`, `telemetry`,
`benchmarks`, `report`.

| 2.0 | Change |
|---|---|
| `--eval <id>` | new global option |
| `init [--eval <id> --component <name>]` | scaffolds an eval folder with `eval.yaml`, and the agent system's shared files if missing; `--component` alone names the eval for the component; refuses a second system eval and an id that names a shared folder |
| `validate`, `status` | on an agent folder with 2.0 evals, read the specs: each missing, invalid and (with `--warnings`) noted field, and the defaults filled |
| `draw [--n UC=N] [--skip ID --reason R] [--prune] [--dry-run]` | new: seeded stratified draw of the quality set from the frame, with π (§3) |
| `plan [--assumed-rate R] [--flip-rate D] [--total N] [--write]` | replaces `allocate`; targets from the decision rule (§2) |
| `screen`, `run`, `report` | read a 2.0 eval: `run --use-case`, k from `measurement.trials` (`auto`: §5); `screen --judges` with the eval's calibrated judges; `report` writes the §6 keys, with `comparison` and the decision on the candidate under `--candidate` (`--html` not yet) |
| `compare` | reads a 2.0 eval: the paired comparison and the decision on the candidate (§5, §6), saved under `report/comparisons/` |
| `log --kind decision` | on a 2.0 eval, records the eval and its `spec_sha`, so a decision-rule change journaled before the candidate runs lets the comparison stand (§5) |
| `label`, `calibrate`, `judge`, `agreement` | read a 2.0 eval: per-judge labels and calibration in catch and clean pass rates (§4); whole-run labels, rulings and triage in `<eval>/labels/` (§6) |
| `migrate --to 2` | new: 1.x suite to a 2.0 end-to-end eval ([§8](#8-migration-from-1x)) |
| `build`, `components`, `discovery-page` | rewritten around the four parts (stage 7) |
| `demo` | the online store ([§9](#9-the-online-store-example)) |

## 8. Migration from 1.x

`aot-evals migrate --to 2` turns a 1.x suite into a 2.0 agent folder with one eval,
`end-to-end`. It moves files with `git mv`, rewrites their contents, writes a `MIGRATION.md`
listing every decision it made, and leaves the spec incomplete wherever 1.x never recorded what 2.0
needs, so the report says so instead of inventing a value. A migrated suite reports the same pass
rates as before; what changes is that it says what it is missing.

**Scope.** Very few 1.x suites exist, so `migrate` covers the mechanical part (the moves, the
renames and the table below) and does not try to handle every variation of a 1.x suite. Anything
it can't map it lists in MIGRATION.md and leaves in place. Each migrated suite is then checked by
hand. Only the tests need the full path to work unattended.

| 1.x | 2.0 | Notes |
|---|---|---|
| `evals/agents/<a>/agent.yaml` | stays; `validity` and `simulator` dropped | logged in MIGRATION.md |
| `categories.yaml` | `eval.yaml` `estimand.use_cases` | `observed_share` → `share`; `share_source` → `estimand.share_source` |
| category `worth`, `cost` row | `use_cases[].cost: null`, `weights: traffic` | 1.x never put a number on cost; the owner states one (problem 1) |
| category `simple`, `heuristic`, `other`, `draft` | dropped | heuristic text kept as a note in MIGRATION.md |
| `failure_modes.yaml` | `measurement.failure_modes` | first code check → `check`, the rest → `diagnostics`; a mode with only judges keeps its first judge; every choice logged |
| `failure_modes[].cost_cell`, `feature`, `scenario` | dropped | |
| `check_type: monitor` | `check: null`, `monitor: true` | |
| `budgets.yaml` | `decision_rule.constraints` | same keys |
| `labels/floors.yaml` | `measurement.people` | `min_catch`/`min_clean` → `floors.catch`/`floors.clean`; `margin: 0.10` added |
| `allocation.yaml` | `plan.yaml` | regenerated by `plan`; `status`/`reason` marks carried over |
| `taxonomy.yaml` | `coverage.yaml` | contents unchanged |
| case `category` | `use_case` | folders unchanged |
| case `set` | `pool` | `error_finding` → `bug_finding`; `quality_estimate` → `quality` |
| quality cases (hand-picked) | `pool: quality`, no `draw` | counted with π assumed equal within a use case, and flagged; `draw` replaces them |
| case `cluster` | `cluster` | missing → the case id |
| judge `min_tpr`, `min_tnr` | dropped | `measurement.max_inflation: 2.0` default, logged |
| runs, labels, calibration, journal | moved unchanged | 1.x manifests stay readable; v1 runs are not comparable with v2 runs of a revised eval |
| — | `estimand.quantity: pass_rate`, `decision_rule.test: superiority`, `alpha 0.05`, `power 0.80`, `looks: fixed` | defaults, stated in MIGRATION.md |
| — | `estimand.decision`, `decision_rule.margin` | left missing: only the owner knows them |

## 9. The online-store example

`examples/store/` replaces `examples/calendar/` as the example, `aot-evals demo` and the test
fixture. It is the agent from the [problems](problems.md):

- **The agent.** An orchestrator that reads each request and answers order-status and return
  questions with an order-reading tool and an address-changing tool, and routes refunds to a
  **refund subagent** with its own prompt and model. Both are small Python programs speaking the
  agent contract, with fakes in `env/` for the order system and payments.
- **Two evals.** `end-to-end` (unit: the system; use cases order status 0.70, returns 0.20, address
  0.08, refunds 0.02; costs $1, $5, $20, $50; weights: cost; decision: non-inferiority, margin 2
  points) and `refunds` (unit: the subagent; frame: refund handoffs; the threshold test above).
- **Checks.** Code checks for end state, amount and side effects; one policy judge at catch 0.95
  and clean 0.99 on a labeled set shipped with the example, and a weaker one (0.80, 0.90) that the
  floor refuses. At those point rates the policy judge costs 1.43× at a 3% failure rate, but the
  floor reads the lower bounds (§4), so the set needs about 100 failure labels and 500 pass labels
  to clear `max_inflation: 2.0` (at 20 and 100 the bounds give 3.7×).
- **Cases.** A quality set drawn from a shipped trace export with `draw`, and a bug-finding set
  from templates with cluster keys, including the policy corners (a day outside the window, a
  partial refund, a gift card).
- **Variants.** `AGENT_VARIANT` switches the behaviors the self-tests need, as the calendar's
  does, plus the problems' scenarios: `refund-bug` (refunds fail 15% instead of 5%, problem 1),
  `declines-missing-order` (the subagent declines handoffs with no order number, problem 2), a
  flaky variant (problem 8), a cheaper model (problem 11).

The calendar stays until the last 1.x code path is gone (the tests in `tests/test_old_layout.py`
and nine others use it).

## 10. Decisions to confirm

Each is cheap to change now and expensive after the code lands.

1. **Layout** (decided): one folder per eval inside the agent folder, with the end-to-end eval in
   `end-to-end/`, and the sandbox, frames and standard shared. A component gets an eval only when
   someone decides about it separately (estimators §1, rule 3). Behind a router, each route is
   a use case of the end-to-end eval, and a route whose model ships on its own gets a gate (rule 20).
2. **Renames** (decided): `category` → `use_case`, `set` → `pool` (`bug_finding`, `quality`),
   `taxonomy` → `coverage`, `allocate` → `plan`, TPR/TNR → clean pass rate and catch rate, all
   defined in [the terms](estimators.md#terms). 1.x names are read by `migrate` only.
3. **Judge floors from `max_inflation`** (decided) instead of fixed catch and clean floors, default 2.0:
   a judge may cost at most twice the cases a code check would.
4. **Measured values stay out of eval.yaml** (decided). The spec states the requirement
   (`max_inflation`) and calibration files hold the measurements, so the spec doesn't change every
   time a judge is recalibrated.
5. **Migration defaults** (decided): traffic weights with costs left null, superiority at α 0.05 and 80%
   power, `decision` and `margin` left missing.
