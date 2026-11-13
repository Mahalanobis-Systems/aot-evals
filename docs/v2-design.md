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
  multiplicity: none               # none | holm | benjamini_hochberg; needed only when one gate alone can act (statistics §4.6)
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
| `measurement.max_inflation` | Measurement | when any check is a judge | sets the floor on each judge (statistics §3.3) |
| `decision_rule.test` | Decision rule | yes | |
| `decision_rule.margin` or `bar` | Decision rule | yes | whichever the test needs |
| `decision_rule.alpha` | Decision rule | yes | one-sided (the regulatory convention for non-inferiority is 0.025) |
| `decision_rule.multiplicity` | Decision rule | when one gate alone can trigger the action | `none` when every gate must pass (statistics §4.6) |
| `decision_rule.constraints` | Decision rule | no | budget keys as in 1.x `budgets.yaml` |

**What the generated plan holds.** `plan.yaml` (1.x `allocation.yaml`) is written by
`aot-evals plan`: per use case and pool, the target from the decision rule's power (with each
judge's inflation factor), the minimum, the optimum allocation of the rest, what exists, and how
many are screened. Humans edit only `status` and `reason`, as in 1.x.

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
case, and logs every skip with its reason. A quality case without `draw` is refused from the
estimate (rule 6). Bug-finding cases carry no `draw` and never enter θ̂ (rule 5).

## 4. Checks and judges

Code checks are unchanged (`check(start, end, case) -> (bool, detail)`; `USES_AGENT_REPORT` is
refused). Judge files keep their front matter, with these changes:

- `min_tpr` and `min_tnr` go. A judge's floor comes from `measurement.max_inflation` and the
  eval's failure rate: the judge passes when its inflation factor at the current rate, computed
  from its lower confidence bounds on catch and clean, is at or under the limit.
- Calibration reports **catch rate** and **clean pass rate** (1.x TNR and TPR), each with its
  interval and its count of labels per kind, plus the inflation factor and the J it implies.
- A judge belongs to one eval. Copying a judge into another eval copies its definition, not its
  calibration.

## 5. Runs

The manifest becomes `aot-evals/run-manifest@2`:

- adds `eval` (id and version) and `spec_sha`, one hash per part (below);
- `case_set` adds each quality case's `inclusion_prob`;
- removes `simulator`;
- everything else as 1.x, including `fakes_sha256` and the resume rules.

`outcomes.jsonl` attempt lines rename `category` to `use_case` and `set` to `pool`. The agent
contract's per-result fields keep their names.

**Which runs can be compared.** The spec says what a run's number means, so two runs compare only
when they measured the same thing. `spec_sha` holds one hash per part, `{estimand, design,
measurement, decision_rule}`, taken over that part of `eval.yaml`. The `measurement` hash also
covers the eval's check files and judge prompts, but not their calibration files. `compare`, and
any report that sets a candidate against a baseline:

- **refuses** when the `estimand`, `design` or `measurement` hash differs. That is a revision
  ([estimators §9](estimators.md#9-changing-an-eval)): the two scores are different quantities. The
  message names the part that changed and says to re-run the baseline under the current spec.
- **refuses** when only the `decision_rule` hash differs, unless the change has a journal entry
  dated before the first candidate run. Moving the bar or the margin after seeing results is
  problem 12 (rule 21).
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
| `spec` | `{complete, missing[{field, why, blocks[]}]}` | all |
| `estimate` | the headline: `{theta, ci, ci_method, weights{use_case: w}, weights_source, estimator: "hajek", corrected, n_cases, n_clusters, k}` | Estimand, design |
| `use_cases` | one row per use case and pool: 1.x category rows, with `share`, `cost`, `weight`, `inclusion_prob_range` | Estimand, design |
| `design` | `{quality{n, drawn, seed, skips[]}, bug_finding{n, coverage}, clusters{n, design_effect, largest}}` | Design |
| `measurement` | `{failure_modes[{id, check, catch, clean, j, inflation, corrected_rate}], eval_vs_people{catch, clean, labels{fail, pass}}, person_anchored{ppi}, variance{icc, between, within}, people{ac1, specific_agreement}}` | Measurement |
| `decision` | `{test, quantity, bar, margin, alpha, power, looks, result: "pass" \| "fail" \| "insufficient", interval, detectable_effect, cases_needed, gates[{use_case, result, p, p_adjusted}], also_requires[{eval, result}], constraints{status, breaches[]}}` | Decision rule |
| `comparison` | as 1.x, with the verdict read from the paired sign-flip test and `variance_band` removed | Decision rule |
| `coverage`, `redundancy`, `cases`, `conditions`, `next_actions` | as 1.x (`conditions.simulator` removed) | |
| `checks` | as 1.x, with `catch` and `clean` in place of `tnr` and `tpr` | Measurement |

**Removed from v1:** `validity` (compounded validity), `online` (always null), `regime`,
`sets` (now `estimate`, `design` and `use_cases`), `categories` (now `use_cases`), the `simple`
flag, `conditions.simulator`, and gates G9 and C16/C17. `gates` becomes `spec.missing` plus the
evidence checks that remain (manifest integrity, screening, trial completeness, isolation), keyed
by part.

`report/agreement.json` keeps its file and its role (gates read it), renames `catch`/`clean`
consistently, and adds `labels_per_kind` and the margin-based evidence.

## 7. Commands

Unchanged in purpose: `start`, `doctor`, `init`, `status`, `validate`, `import`, `screen`, `run`,
`label`, `agreement`, `serve`, `replay`, `calibrate`, `reliability`, `judge apply`, `ops`,
`snapshot`, `compare`, `coverage`, `redundancy`, `log`, `activity`, `checkpoint`, `telemetry`,
`benchmarks`, `report`.

| 2.0 | Change |
|---|---|
| `--eval <id>` | new global option |
| `init [--eval <id> --component <name>]` | scaffolds an eval folder with `eval.yaml` |
| `draw` | new: seeded stratified draw of the quality set from the frame, with π |
| `plan` | replaces `allocate`; targets from the decision rule |
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
  and clean 0.99 on a labeled set shipped with the example, which meets `max_inflation: 2.0` at a
  3% failure rate, and a weaker one (0.80, 0.90) that the floor refuses.
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
