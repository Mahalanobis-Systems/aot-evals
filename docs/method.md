# The aot-evals method

This is the reference for what aot-evals 2.0 does: the principles, the four parts of an eval and
the three phases that settle them, where evals go, the files kept in your repository, the eval
spec, cases, checks and runs, every command, `report.json`, the gates, and what `status` reports.
Terms mean what [estimators.md](estimators.md#terms) says. Why each rule holds is derived in
[statistics.md](statistics.md) and shown by worked example in [problems.md](problems.md); this page
links to those sections instead of repeating them.

## Contents

1. [Principles](#1-principles)
2. [The four parts and the three phases](#2-the-four-parts-and-the-three-phases)
3. [Where evals go](#3-where-evals-go)
4. [Files](#4-files)
5. [The eval spec](#5-the-eval-spec)
6. [Cases, frames and draws](#6-cases-frames-and-draws)
7. [Checks, judges and labels](#7-checks-judges-and-labels)
8. [Runs and comparability](#8-runs-and-comparability)
9. [Commands](#9-commands)
10. [report.json](#10-reportjson)
11. [Gates](#11-gates)
12. [Status: phase and trust](#12-status-phase-and-trust)
13. [Not in 2.0](#13-not-in-20)
14. [Lineage](#14-lineage)
15. [References](#15-references)

**Who it is for.** Production, user-facing agents on any stack: their work is specific to the
product, so no public benchmark measures it; their volume makes a point of correctness, cost or
latency worth measuring; and their output reaches users without an expert checking it first. The
agent is invoked as a command ([the agent contract](../references/agent-contract.md)), so
framework, language and model provider do not matter.

**What it is not.** Not trace collection (it reads exports of what your observability already
records), not a model gateway, not a hosted dashboard and not a leaderboard. There is no service
and no account. Everything it writes is text, diffable and safe to commit; raw traces and PII
never enter git.

**The example.** Every section below uses the online store in
[examples/store/](../examples/store/README.md): a support agent whose orchestrator answers order,
return and address requests and hands refunds to a refund subagent owned by another team. It has
two evals, `end-to-end` and `refund-subagent`. `aot-evals demo` copies it into a new repository and
runs it.

---

## 1. Principles

1. **An eval is an estimator, and its four parts are written down.** The estimand (what number,
   for which decision), the sampling design (which cases, drawn how), the measurement model (how
   wrong the grader is) and the decision rule (when to act) live in the eval's `eval.yaml`. The
   rules for building a suite follow from them, not from rules of thumb
   ([estimators §10](estimators.md#10-the-rules-in-one-table)).
2. **Cases come from the agent's real traffic.** The quality set is a seeded random draw from a
   frame of real requests, with each case's inclusion probability recorded, and it is the only set
   whose rate is called quality. The bug-finding set is picked by hand to find failures, checked
   against a coverage list written outside the cases, and never enters a rate. Public benchmarks
   are a source of grading designs and situations, never of cases.
3. **Grade the world with code first.** A check reads what the agent changed, never its claim of
   success. A judge goes where code cannot decide, and counts only once its catch rate and clean
   pass rate are measured and its errors cost no more cases than the spec allows.
4. **Hold the whole eval to people.** People label whole runs without seeing the checks; the
   eval's own catch rate and clean pass rate come from comparing the two.
5. **Decide by a rule fixed before the results.** The test, margin or bar, α, power and the number
   of looks are in the spec before a run is decided on. The number of cases comes from that rule's
   power, with the grader's error counted.
6. **Unknown is `null`, never `0`.** Every number carries its n, its k and an interval, or says why
   it has none. A missing spec field does not stop anything from running: it nulls the numbers
   that depend on it, with the reason.
7. **Correctness and cost are kept apart.** θ̂ is about correctness. Cost and latency are
   constraints in the decision rule, reported beside θ̂, never folded into it.
8. **Keep sensitive data out of version control.** Raw traces stay in the agent folder's `data/`,
   which is ignored; only scrubbed, reviewed cases are committed.
9. **Record every claim as confirmed or inferred, with its source.** When configuration and traces
   disagree, trust the traces.

---

## 2. The four parts and the three phases

An eval's number means something only when its four parts are written down
([estimators.md](estimators.md)). Each part has its own problems, rules and derivations:

| Part | Question | Written down in | Problems | Derived in |
|---|---|---|---|---|
| Estimand | What number, about what, drives which decision? | `estimand:` (unit, quantity, population, use cases, weights, decision); agent.yaml's `components` | [1](problems.md#1-decide-which-mistakes-matter), [2](problems.md#2-a-better-part-isnt-a-better-agent), [3](problems.md#3-keep-the-test-current) | [statistics §1](statistics.md#1-the-estimand) |
| Sampling design | Which cases, drawn how? | `design:` (the quality set's seed and oversampling, the coverage list, the cluster key) | [4](problems.md#4-test-what-your-users-actually-ask), [5](problems.md#5-count-the-evidence-not-the-cases) | [statistics §2](statistics.md#2-the-sampling-design) |
| Measurement model | How wrong is the grader? | `measurement:` (one counted check per failure mode, trials, the correction, `max_inflation`, the floors against people) | [6](problems.md#6-your-grader-is-wrong-sometimes), [7](problems.md#7-hold-the-whole-eval-to-a-person), [8](problems.md#8-run-it-more-than-once) | [statistics §3](statistics.md#3-the-measurement-model) |
| Decision rule | When do we act? | `decision_rule:` (the test, bar or margin, α, power, looks, gates, `also_requires`, constraints) | [9](problems.md#9-a-clean-run-isnt-a-clean-bill-of-health), [10](problems.md#10-compare-case-by-case), [11](problems.md#11-no-difference-isnt-no-worse), [12](problems.md#12-stop-peeking) | [statistics §4](statistics.md#4-the-decision-rule) |

People meet the method as **three phases**, Assess, Build and Judge. Each settles some of the
parts, and the skills and `status` speak in phases:

| Phase | Who | Settles | Skill | Commands |
|---|---|---|---|---|
| Assess | Claude with the agent's owner, about 5 minutes | the estimand: what the agent is for, its context boundaries (where its evals go), its use cases with their shares and the cost of a failure in each, the decision each eval drives | `start` | `start`, `benchmarks`, `discovery-page` |
| Build | engineering, about half a day for a first pass | the agent contract and sandbox; the sampling design (frames, the drawn quality set, the bug-finding set and its coverage list, cluster keys); the measurement model's checks and trials; the decision rule; a baseline under the current spec | `build` | `build`, `init`, `import`, `handoffs`, `plan`, `draw`, `screen`, `run`, `compare`, `coverage`, `ops`, `replay`, `snapshot` |
| Judge | the people who know what good looks like, and whoever facilitates them | the measurement model's error rates: whole-run labels, the eval held to people, each judge's catch and clean pass rates | `judge` | `serve`, `agreement`, `label`, `calibrate`, `reliability`, `judge apply` |

The `report` skill writes an HTML diagnostic from report.json in any phase. The phases overlap in
practice: the owner states costs and the margin during Build, and a change to the agent sends an
eval back to Build for a candidate run. `status` says which phase each eval is in (§12).

---

## 3. Where evals go

One eval answers one question: one unit, one population, one decision (rule 1,
[statistics §1.3](statistics.md#13-units-where-an-eval-goes)). Every agent has an **end-to-end
eval**, by convention `<agent>/end-to-end/`, whose unit is the whole system as a user meets it. A
component gets an eval of its own only at a **context boundary** (it starts from a handoff the
orchestrator writes) and only when someone decides about it separately (rule 3).

agent.yaml's `components` lists each part the orchestrator calls, so the specs can say why a part
has an eval of its own or doesn't (`boundaries.py`). The store's refund subagent:

```yaml
components:
  - id: refund-subagent
    kind: subagent          # subagent: called with a handoff the orchestrator writes
                            # route: handed the user's request as sent, picked by a router
                            # step: runs inside the orchestrator's context
    context: own            # own: starts from its handoff (a context boundary) | shared
    called_by: the orchestrator's refund route
    model: toy-refunds-1
    owner: refunds team
    ships_separately: true  # its own prompt, model or owner, changed on its own schedule
    use_case: refund        # the end-to-end use case whose requests reach it
```

| Component | Where it is graded |
|---|---|
| subagent, own context, ships separately | an eval of its own, drawn from the handoffs it receives (rules 3, 4), gated on the end-to-end eval (rule 27) |
| subagent, own context, ships only with the system | checks in the end-to-end eval: an eval of it would drive no decision |
| route whose model ships on its own | a use case gate in the end-to-end eval (rule 20), not an eval of its own |
| route that ships with the system | a use case of the end-to-end eval |
| step, or a shared context | checks on its steps in the end-to-end eval |

A route's input is the user's request, so its population is the routed share of requests: a use
case of the end-to-end eval. A subagent's input is a handoff the orchestrator writes, a population
of its own. The discovery report names the boundaries first (`boundaries:` in its front matter,
the same fields); `build` drafts agent.yaml's list from it and creates the evals it calls for;
`validate` refuses a component eval for a shared context, a step, a route or a part that only
ships with the system, and one whose decision copies the end-to-end eval's (rule 1). A component
change ships only when the end-to-end eval shows no regression too (rule 27,
[problem 2](problems.md#2-a-better-part-isnt-a-better-agent)). When every gate must pass, testing
each at α needs no multiplicity correction ([statistics §4.6](statistics.md#46-many-gates)).

---

## 4. Files

An agent system has one folder, and each eval of it has a folder inside it:

```
evals/agents/<agent>/            the agent system
  agent.yaml                     the system's inventory (its components) and how to invoke it end to end
  discovery.md, discovery.html   the Assess report and its page
  env/                           sandbox fakes and the seed and observe hooks, shared, hashed into every run
  data/                          imported traces (the frames), ignored by git; export.manifest.json records each
  labels/standard.md             the labeling standard, shared
  journal/                       the activity log (activity.jsonl, activity.html)
  <eval>/                        one eval: one estimand
    eval.yaml                    the eval spec: the four parts
    coverage.yaml                the coverage list the bug-finding set is checked against
    plan.yaml                    written by `plan --write`: case targets per use case and pool
    draw.json                    the draw log: frame, seed, frame sizes, skips
    cases/<use_case>/<id>.json
    checks/code/<id>.py
    checks/judge/<id>.md         plus <id>.labels.jsonl, .calibration.json, .reliability.json, .judgements.jsonl
    labels/                      runs.jsonl, rulings.jsonl, triage.yaml, proposals.yaml, drafts/
    runs/<run-id>/               manifest.json, outcomes.jsonl, raw/
    report/                      report.json, agreement.json, looks.jsonl, comparisons/
```

| File | Part | Written by | Holds |
|---|---|---|---|
| `agent.yaml` | agent contract, estimand | `build`, then people | `invoke` (command, cwd, timeout, hooks, env, `isolate`), models per call site, tools, `components` |
| `discovery.md` | estimand | the `start` skill (Assess) | front matter (overview, `boundaries`, `components`, the case grid, next steps) and the report |
| `env/` | agent contract | engineering | the sandbox; its hash is every manifest's `fakes_sha256`, and a resume refuses changed fakes |
| `data/export.manifest.json` | sampling design | `import`, `handoffs` | each import's source, query, window, hash and, for a handoff frame, where its handoffs came from |
| `labels/standard.md` | measurement | people, through `serve` | the rules a person applies when failing a run; accepted rules carry their `use_cases` |
| `<eval>/eval.yaml` | all four | `init`, `build`, then people | §5 |
| `<eval>/coverage.yaml` | sampling design | people | a source written for another purpose, `read_on`, and entries; committed before the first case |
| `<eval>/plan.yaml` | sampling design, decision rule | `plan --write` | targets per use case and pool; people edit only `status` and `reason` |
| `<eval>/draw.json` | sampling design | `draw` | the frame, its hash, the seed, rows per use case and every skip with its reason |
| `<eval>/cases/` | sampling design | `draw` (quality), people (bug-finding) | §6 |
| `<eval>/checks/` | measurement | people | §7 |
| `<eval>/labels/` | measurement | `serve`, `agreement` | whole-run labels, rulings, causes of disagreements, proposed rules, drafted cases |
| `<eval>/runs/` | all four | `run` | §8 |
| `<eval>/report/` | all four | `report`, `agreement`, `compare` | §10 |
| `journal/` | process | every command, and the skills' `log` lines | the activity page |

What the evals of one system share: `env/`, `data/`, the labeling standard and the journal. What
they don't: cases, checks, judges and their calibration, labels, runs and reports. A judge's error
rates belong to the population it was calibrated on, so copying a judge into another eval copies
its definition, not its calibration.

---

## 5. The eval spec

`eval.yaml` is the four parts written down, plus `invoke` for a component eval. The store's refund
eval, abridged ([the full file](../examples/store/evals/agents/store/refund-subagent/eval.yaml)):

```yaml
eval: refund-subagent
version: 1.0                       # major: estimand, weights, use cases, design or checks changed
estimand:
  unit: {kind: component, component: refund-subagent, boundary: handoff from the orchestrator's refund route}
  quantity: failure_rate:breaks-policy   # pass_rate | failure_rate:<failure mode id>
  population: {frame: refund-handoffs-2026-10, window: 2026-10-01/2026-10-31, environment: env/}
  use_cases:
    - {id: full-refund, definition: ..., example: tr_8812, share: 0.80, cost: 50}
    - {id: partial-refund, definition: ..., example: tr_9017, share: 0.15, cost: 50}
    - {id: gift-card, definition: ..., example: tr_9230, share: 0.05, cost: 20}
  share_source: refund-handoffs-2026-10
  weights: cost                    # traffic (w = share) | cost (w ∝ share × cost) | {use_case: w}
  decision: {action: ship a change to the refund subagent, owner: refunds team, cadence: weekly}
design:
  quality_set: {selection: stratified_random, seed: 1234, oversample: {gift-card: 4}}
  bug_finding_set: {coverage: coverage.yaml}
  cluster_key: order_template
measurement:
  failure_modes:
    - {id: breaks-policy, use_cases: "*", check: policy-judge, diagnostics: [policy-judge-weak]}
    - {id: wrong-amount, use_cases: "*", check: amount-matches}
    - {id: unrequested-change, use_cases: "*", check: no-side-effects, side_effect: true}
    - {id: wrong-reply, use_cases: "*", check: reply-matches-refund}
  trials: 3                        # or auto
  correction: rogan_gladen         # none | rogan_gladen | ppi
  max_inflation: 2.0
  people: {floors: {catch: null, clean: null}, margin: 0.10, labels_per_kind: auto}
decision_rule:
  test: threshold                  # superiority | non_inferiority | threshold
  bar: 0.05
  alpha: 0.05
  power: 0.80
  looks: fixed                     # fixed | sequential | optimizer_holdout
  combine: all                     # all: every gate must pass | any: one gate alone acts
  multiplicity: none               # none | holm | benjamini_hochberg
  also_requires: [{eval: end-to-end, test: non_inferiority, margin: 0.02}]
  constraints: {default: {cost_per_success_usd: 0.05, latency_p90_ms: 8000}}
invoke:                            # component evals only; the end-to-end eval uses agent.yaml's
  command: [python3, agent/refunds.py, --handoff]
```

**Complete, missing, invalid.** The loader (`spec.py`) sorts what it finds into four lists, each
entry `{field, why, blocks[]}`, where `blocks` names the commands and report keys the field is
needed for (`run`, `draw`, `plan`, `estimate`, `use_cases`, `measurement`, `decision`,
`comparison`):

- **missing**: a required field left out or empty, or a reference to something not there yet (a
  frame with no import, a check with no file, an `also_requires` eval that doesn't exist);
- **invalid**: a field that is there but cannot mean anything (shares that don't sum to 1, two
  counted checks on one mode, a decision rule on another quantity);
- **notes**: block nothing (an unknown key with the field it probably meant, a `bar` a
  non-inferiority test ignores);
- **defaults**: each stated default the loader filled.

An eval is **complete** when `missing` and `invalid` are both empty. An incomplete eval still
runs; its report lists the fields under `spec.missing` and nulls the numbers that depend on them.
`validate` prints every field; `status` summarizes.

| Field | Part | Required | Rule |
|---|---|---|---|
| `estimand.unit` | Estimand | yes | `system` once per agent; `component` needs `component` and `boundary`, and the component in agent.yaml's `components`, placed at an eval of its own (§3) |
| `estimand.quantity` | Estimand | yes | `pass_rate`, or `failure_rate:<mode>` |
| `estimand.population.frame` | Estimand | yes | an import id; a component's frame must be an import of handoffs into it (rule 4); one from an older end-to-end frame is a note (rule 26) |
| `estimand.use_cases[]` | Estimand | yes | `id`, `definition`, `example`, `share`; shares sum to 1 ± 0.02 |
| `use_cases[].cost` | Estimand | with `weights: cost` | a positive number in any unit; null means not stated |
| `estimand.weights` | Estimand | yes | an unstated weight is unknown, never 1 ([statistics §1.1](statistics.md#11-weights-what-a-failure-costs)) |
| `estimand.decision` | Estimand | yes | `action` and `owner`; a component eval with the end-to-end eval's action and owner is invalid (rule 1) |
| `design.quality_set` | Design | yes | `seed`; `oversample` optional (a use case drawn at k times its share) |
| `design.bug_finding_set.coverage` | Design | no | the coverage list's file |
| `design.cluster_key` | Design | yes | a case field; `id` means every case is its own cluster |
| `measurement.failure_modes[]` | Measurement | yes | exactly one counted `check` per mode (rules 11, 12); other checks on it are `diagnostics` |
| `failure_modes[].side_effect` | Measurement | on at least one mode | that mode's counted check catches changes nobody asked for |
| `measurement.trials` | Measurement | yes | ≥ 3, or `auto` (§8) |
| `measurement.correction` | Measurement | when any counted check is a judge | `rogan_gladen` or `ppi` (§10) |
| `measurement.max_inflation` | Measurement | when any counted check is a judge | default 2.0: a judge may cost at most twice the cases a code check would ([statistics §3.3](statistics.md#33-what-a-graders-error-costs-you)) |
| `measurement.people` | Measurement | no | `floors: {catch, clean}` (null: from `max_inflation`), `margin` (default 0.10), `labels_per_kind` (default `auto`) |
| `decision_rule.test` | Decision rule | yes | `superiority`, `non_inferiority` or `threshold` |
| `decision_rule.margin` or `bar` | Decision rule | yes | whichever the test needs |
| `decision_rule.quantity` | Decision rule | no | defaults to `estimand.quantity`; any other value is invalid |
| `decision_rule.alpha` | Decision rule | yes | one-sided, above 0 and below 0.5; default 0.05; 0.025 where a bad change is costly or hard to reverse ([statistics §4.5](statistics.md#45-no-difference-isnt-no-worse)) |
| `decision_rule.power` | Decision rule | yes | default 0.80 |
| `decision_rule.looks` | Decision rule | yes | default `fixed` |
| `decision_rule.combine` | Decision rule | yes | `all` (default) or `any`; `also_requires` always must pass |
| `decision_rule.multiplicity` | Decision rule | with `combine: any` and several gates | `holm` or `benjamini_hochberg`, and `none` is then invalid; otherwise `none` ([statistics §4.6](statistics.md#46-many-gates)) |
| `decision_rule.use_case_gates` | Decision rule | per separately shipped route | each `{use_case, test, margin or bar, ...}` (rule 20, [statistics §1.2](statistics.md#12-the-blind-spot-a-use-case-the-headline-cant-see)) |
| `decision_rule.also_requires` | Decision rule | for a component eval | must name the end-to-end eval with a paired test; a threshold there is invalid (rules 19, 27) |
| `decision_rule.constraints` | Decision rule | no | `default` and `use_cases`, with `cost_per_success_usd`, `latency_p90_ms` and the other budget keys (rule 24) |
| `invoke` | Agent contract | for a component eval | `command` as argv, and the hooks; the end-to-end eval has none |

**Defaults stated as defaults.** α 0.05 one-sided, power 0.80, `looks: fixed`, `combine: all`,
`max_inflation` 2.0 when a judge counts, the eval-vs-people margin 0.10 and `labels_per_kind:
auto`. The report lists each default it filled.

**Versions.** `version` is major.minor. Any change to the estimand, the weights, the use cases,
the design or the checks (a new judge included) is a revision and a major version: re-run the
baseline, and don't compare old and new numbers. New cases from the same frame and seed are an
expansion and keep the version ([estimators §9](estimators.md#9-changing-an-eval)).

**The plan** (`plan`, `plan.yaml`). Per use case and pool: the target from the decision rule's
power, the minimum, the optimum allocation of the rest, what exists, what is drawn and screened
([statistics §2.3](statistics.md#23-allocation-how-many-cases-per-use-case),
[§4.1](statistics.md#41-case-counts-come-from-power)).

- **The headline need** is the independent cases the rule's test needs at its α and power:
  `stats.threshold_n` for a threshold test, with the judge's catch and clean pass rates written
  into the test, or `stats.paired_n` from the flip rate for a paired test, times each counted
  judge's inflation factor. A judge without a current calibration is planned at `max_inflation`.
- **Minimums**: each use case gate's own need, and each oversampled use case's factor × share × N.
- **N** is raised until the optimum allocation (proportional to the weights until a baseline
  measures spreads and costs) still holds the headline need once its unequal weighting and the
  clusters' design effect are counted. `--total N` fixes the budget instead.
- **What it can't know, it asks for**: before a baseline, a threshold test needs the rate expected
  under the alternative (`--assumed-rate`) and a paired test the flip rate (`--flip-rate`, from an
  A/A rerun or the last comparison). Without them the targets are null and the reason names the
  flag. Every assumption is written under `assumptions` with its source.
- Bug-finding rows have no target. People edit only each row's `status` (`scheduled`,
  `out_of_scope`) and `reason`; `plan --mark-short` sets them for every short row.

---

## 6. Cases, frames and draws

A case is one request with what is needed to run it and grade the result. Its fields:

| Field | Holds |
|---|---|
| `id`, `use_case` | the use case equals the folder name |
| `pool` | `quality` or `bug_finding` |
| `draw` | quality pool only: `{frame, seed, index, inclusion_prob}`, written by `draw` |
| `cluster` | the value of the eval's `cluster_key`; defaults to the case id |
| `trigger`, `inputs`, `start_state`, `followups`, `expected_end_state` | what the agent receives, and the state a correct run ends in (`{world, output}`, with optional `output_variants`) |
| `failure_modes`, `coverage_entries`, `requirements`, `rules_not_applicable` | what the case tests and which rules of the standard apply |
| `provenance` | the source trace (`source_trace` for a handoff), `synthetic`, and who confirmed the expected state |
| `screen` | the screens' verdicts and who read the case |

**Quality cases come from `draw`, never by hand** (rules 5, 6;
[statistics §2.1](statistics.md#21-two-pools-because-there-are-two-questions),
[§2.2](statistics.md#22-drawing-the-quality-set)). `draw` takes each use case's rows from the
frame in a seeded random order (one stream per use case), takes the first n (from `--n`, else
plan.yaml's target, else the last draw), records each case's inclusion probability, and copies
only the case fields from each row, with `provenance` pointing at the trace. Drawing more later
extends the same draw and rewrites the earlier cases' π (an expansion); resizing one use case never
changes another. `draw --skip ID --reason R` takes a row out of the frame and the next row of the
same order replaces it. A quality case the draw no longer holds is removed only with `--prune`. A
quality case without a `draw`, or with one from another frame or seed than the spec's, is refused
from the estimate. Bug-finding cases carry no `draw` and never enter θ̂.

**Frames.** A frame is an import in `data/export.manifest.json`: one JSON row per trace, with an
`id`, a `use_case` and the case fields. Rows with no use case, or one the spec doesn't name, are
counted in the draw log and never drawn.

**Frames of handoffs** (rule 4). A component eval's frame is the handoffs its component receives
in production, never written by hand. Each row of an end-to-end frame records its handoffs as
`handoffs: [{to, use_case, <cluster key>, trigger, inputs, start_state, expected_end_state, ...}]`,
with `to` naming the component as agent.yaml does. `aot-evals --eval <component eval> handoffs`
imports one row per handoff, with id `<trace>.h<k>`, `source_trace` and `source_use_case`, as a new
frame, and records `handoffs: {component, from, from_sha256, traces, traces_with_handoff, multi,
source_use_cases}`. Handoffs from one trace are related, so `cluster_key: source_trace` counts them
once (rule 9). `import FILE --handoffs-of COMPONENT` records handoffs a team's tracing captured as
they happened. `handoffs --scan` counts the handoffs into each component in a frame, beside
agent.yaml's `components`. A routing change makes a new end-to-end frame, so the handoffs are
extracted again: a revision of the component eval (rule 26).

**Clusters** ([statistics §2.4](statistics.md#24-clusters-count-the-evidence-not-the-cases)). A
case's cluster is its `cluster`, else the value of its `cluster_key` field, else its id. Intervals,
bounds and the sign-flip test count clusters. Clusters shared by the two pools are listed in
`design.clusters.shared_with_bug_finding`: the pools must be disjoint by cluster key (rule 10).

**The bug-finding set** ([statistics §2.5](statistics.md#25-the-bug-finding-set-coverage-adequacy-and-construction))
is written by people, from templates and real failures, and sized by the coverage list it must
reach, not by power. `coverage` lays coverage entries against failure modes over it. Pruning may
remove bug-finding cases freely while coverage holds; quality cases are pruned only by redrawing
(rule 25, [statistics §2.6](statistics.md#26-pruning)).

**Screens** (`screen`). Per case: the reference end state passes, doing nothing fails, a
non-answer fails, and doing nothing while claiming success fails (the liar screen); each
`output_variants` wording passes. A person reads each case (`screen --read-by NAME`). Cases that
are unscreened, or whose file is untracked or has uncommitted edits, stay out of θ̂ (rule 17).
`screen --judges` counts the eval's calibrated judges in every screen as its code checks, so a
use case only a judge grades can pass (the judge must fail the do-nothing run).

---

## 7. Checks, judges and labels

**Code checks** live in `checks/code/<id>.py`: `check(start, end, case) -> (bool, detail)`, where
`start` and `end` are `{world, output}` as the `observe` hook printed them. A check grades the
world against the goal, never the agent's own report: `USES_AGENT_REPORT = True` is refused
(evidence gate `independent_reference`). Template: [templates/check_code.py](../templates/check_code.py).

**Judges** live in `checks/judge/<id>.md`, front matter plus the question in prose
([templates/check_judge.md](../templates/check_judge.md),
[references/judge-backends.md](../references/judge-backends.md)). A judge asks one typed question
about one failure mode: a `noul` (a true/false claim, `detects` saying whether yes means the
failure is present), a `choice` over declared options, or a `score` on a rubric level. Backends:
`systemone` (a probability per answer), `anthropic` (generative, from a different model family
than the agent), and `command` (any judge you run yourself); `primary` names the backend whose
verdicts count. Judgements are cached per backend; a refusal or an error is an instrument error,
never a verdict from another model.

**A judge's error rates** ([statistics §3.2](statistics.md#32-a-judge-is-a-diagnostic-test)).
`calibrate` measures, per backend, on the judge's labels: the **catch rate** and the **clean pass
rate**, each with its Wilson interval, its one-sided lower bound at the decision rule's α and its
count of labels per kind (`labels_per_kind: {fail, pass}`), plus J and the inflation factor its
lower bounds imply at 50%, 20%, 10% and 3% (`inflation_at_lower_bounds`). The 1.x `tpr`/`tnr` keys
stay beside them. A probabilistic backend's threshold is chosen on the dev labels by maximizing
catch + clean, and the reported rates come from 5-fold out-of-fold predictions; a hash-assigned 20%
of labels is a holdout, reported apart. A calibration's `status` is `calibrated` when it has
labels of both kinds and a verdict on each. A changed prompt, model or inputs (a new `version`) is
a new instrument with unknown error rates (rule 13).

**The judge floor** (`measurement.judge_floor`; [statistics §3.3](statistics.md#33-what-a-graders-error-costs-you)).
A judge counts when its inflation factor q(1 − q)/(J²·p(1 − p)), at its lower bounds on catch and
clean and at the eval's current failure rate on its mode, is at or under `max_inflation`. The
current rate is the mode's design-weighted rate in the report's runs, corrected with the judge's
point rates and kept half a failure away from 0 and 1. A judge with no current calibration (none,
stale, or labels of one kind only) does not count. A counted judge that feeds the quantity and does
not count leaves θ̂ null and every gate `unknown`, never a pass. With no scored run yet the floor is
`unknown`, and `plan` counts the judge at `max_inflation`. A 2.0 judge that still sets `min_tpr` or
`min_tnr` gets a note; the floor ignores them.

**How many labels** ([statistics §3.4](statistics.md#34-how-many-labels-and-which-ones)). Labels
count per kind: the catch rate rests only on runs a person failed, the clean pass rate only on runs
a person passed. `label status` and `calibrate` say how many of each kind ±10 points needs.

**Reliability is not validity** ([statistics §3.5](statistics.md#35-reliability-is-not-validity)).
`reliability` measures a judge's self-consistency over repeated sessions and its agreement with a
backend from another family. Both are reported beside catch and clean pass rates, never in their
place.

**Whole-run labels and the eval against people** (rule 15,
[statistics §3.6](statistics.md#36-the-whole-eval-against-people)). People label whole runs, pass
or fail with a note, blind to the checks, the expected state and each other (`labels/runs.jsonl`,
one line per run and labeler). Where labelers differ the run has no verdict until someone rules
(`labels/rulings.jsonl`). Each run is assigned to dev or holdout by a hash of its id. `agreement`
compares the eval's verdicts with people's on the same runs and writes `report/agreement.json`:
the eval's catch and clean pass rates (dev, holdout, all), labels per kind against the count fixed
before looking, agreement between labelers (share agreed, Cohen's κ, Gwet's AC1, agreement on
fails and on passes), the person-anchored pass rate (PPI++), and its gates (§11). Every dev
disagreement needs a cause in `labels/triage.yaml`: `wrong-expectation`, `missing-requirement`,
`check-bug`, `judge-error`, `out-of-scope` or `accepted`.

- **Floors.** A stated floor (`measurement.people.floors`) is met when the dev point estimate
  reaches it and its 95% lower bound is within `margin` of it
  ([statistics §4.2](statistics.md#42-floors-showing-that-you-cleared-the-bar), `stats.floor_evidence`).
  A null floor is the `max_inflation` reading, as for a judge, at the eval's whole-run failure rate.
- **Labels per kind.** `labels_per_kind: auto` fixes each kind's count before looking: the Wilson
  ±margin size at the stated floor, or at 50% where the floor is null
  ([statistics §4.7](statistics.md#47-looks-stop-peeking)).
- **Re-grading is offline.** `agreement regrade --run ID` re-grades labeled runs from their raw
  records with the checks as they are now: no agent runs, and no judge calls unless
  `--call-judges`.
- **The label queue draws**, it doesn't pick: labels stand for the runs they were drawn from. After
  a change, `agreement label queue --changed` limits the queue to the cases whose verdict moved.

**The grader application** (`serve`) is the Judge phase's local web page for one eval, bound to
127.0.0.1 with a session token in its link; `&labeller=NAME` gives each grader their own.
Everything it does writes the eval's files above:

| What a grader does | Where it is written |
|---|---|
| Labels whole runs pass or fail, with a note, blind | `labels/runs.jsonl` |
| Settles a run two labelers disagree on | `labels/rulings.jsonl` |
| Gives a cause to a disagreement between the eval and a person | `labels/triage.yaml` |
| Accepts an answer the eval failed as another correct wording | the case's `expected_end_state.output_variants`; the case is screened again |
| Proposes a rule from a pattern of rulings; the owner accepts or declines it | `labels/proposals.yaml`; an accepted rule joins the shared `labels/standard.md` with its `use_cases` |
| Labels items for a judge, and recalibrates it after confirming the cost of new calls | `checks/judge/<id>.labels.jsonl`, `<id>.calibration.json` |
| Drafts a new case in the shape of an existing one | `labels/drafts/<id>.json`, until an engineer finishes it |

A new labeler starts with up to five runs whose answer is settled and sees it after each label;
after that, one run in four is one someone else labeled, so agreement between people can be
measured. Its overview shows the eval's spec, its baseline and latest candidate, the eval against
people, and per use case its cases, labeled runs and catch and clean pass rates. The engineering
inbox lists what only engineering can do.

---

## 8. Runs and comparability

`run --purpose smoke|baseline|candidate|drift` runs the agent over an eval's cases, k trials each.
A component eval invokes its component through `eval.yaml`'s `invoke`; the end-to-end eval
through agent.yaml's. Each run writes `runs/<run-id>/manifest.json` (`aot-evals/run-manifest@2`),
`outcomes.jsonl` and `raw/`.

**The manifest** records the eval (id and version), `spec_sha` (one hash per part), `spec_complete`
and `spec_issues` (the fields missing or invalid when it started), the agent and evals commits and
whether each was dirty, the harness, k and its source (`trials`), the model ids declared and
observed per call site, the judge backends, `fakes_sha256` over the shared `env/`, `standard_sha`
over the shared standard, and `case_set` with each quality case's `inclusion_prob`. `--resume`
continues a stopped run and refuses when the cases, checks, fakes or agent changed.

**Outcomes.** One attempt line per attempt (with `use_case` and `pool`, and the agent contract's
per-result fields: `case_id`, `trial`, `attempt`, `outcome`, `cost_usd`, `tokens_input`,
`tokens_output`, `latency_ms`, `model`), and one check line per check (`counted`: true for a
failure mode's counted check, false for a diagnostic). An attempt's `passed` is its counted code
checks' verdict; outcome codes are in `outcomes.py`, and operational failures (timeouts, rate
limits) are counted on their own, never as wrong answers.

**Trials** (rule 16, [statistics §3.7](statistics.md#37-trials-noise-and-k)). `measurement.trials`
sets k (≥ 3). `trials: auto` runs k = 3 until a baseline under the current spec measures the split
of variance between and within cases, then k* = √(case_cost × within ÷ between) (Cochran 1977
§10.6), with case_cost = 1, clamped to [3, 10]. The manifest records `trials: {spec, recommended,
source, k}`; an explicit `--k` wins.

**Isolation.** A model call site that has tools of its own (a coding harness, a model with web
search) can read the repository, cases included. `invoke.isolate: true` runs the agent outside the
eval files; the `manifest` gate fails a run whose eval files changed during it or whose output
names them.

**Which runs can be compared** (`spec_sha`). The `estimand`, `design`, `measurement` and
`decision_rule` hashes are taken over each part of `eval.yaml`; the `measurement` hash also covers
the check files and judge prompts, not their calibration. `report` and `compare`:

- **refuse** when the estimand, design or measurement hash differs from the current spec's: a
  revision, so the two scores are different quantities. The message names the part and says to
  re-run the baseline;
- **refuse** when only the decision rule's hash differs, unless the change was on record before the
  first run decided on (rule 21, [problem 12](problems.md#12-stop-peeking)). A record is a commit of
  eval.yaml holding the current rule that is an ancestor of the decided runs' agent or evals commit
  (or, when the evals live in a repository of their own, dated no later than the first decided
  run), or a journal entry `aot-evals --eval <id> log --kind decision "why"`, which records the
  eval's `spec_sha`;
- **refuse** when the two sides are not one build apart: they may differ only on the manifest fields
  the candidate's declared variable covers (`--variable KIND=VALUE`, or `--model ID`);
- **compare** when only the cases or the calibrations changed.

---

## 9. Commands

`aot-evals` is the plugin's CLI (`bin/aot-evals`); it needs Python ≥ 3.11 with PyYAML, or `uv`.
Global options: `--agent NAME` (needed when the repository has several agents), `--eval ID` (needed
when the agent has several evals), and `--evals PATH`. Every command logs itself to the journal.

| Command | Part | Phase | What it does |
|---|---|---|---|
| `start` | | Assess | prints the banner and the three phases |
| `doctor` | agent contract | any | checks the environment, each eval's cases and `invoke.cwd`; paste it into bug reports |
| `demo [DIR]` | | any | copies the online store into a new repository and runs both baselines and a refund-subagent change |
| `benchmarks --workload TAG --task TEXT` | sampling design | Assess | matches the agent to the local catalog of public benchmarks and prints the situations to cover; `--validate` checks the catalog |
| `discovery-page FILE --agent NAME` | estimand | Assess | renders discovery.md as a page, with "Where the evals go" and the components |
| `init [--component NAME]` | all | Build | creates an eval folder with its `eval.yaml` (default: `end-to-end`) and the system's shared files if missing; refuses a second system eval |
| `build [--run]` | all | Build | creates the end-to-end eval and one per component that earns one, drafts agent.yaml's `components`, the use cases (costs null), the coverage list and one generic code check, and prints each eval's checklist by part; `--run` runs each eval that can run (smoke, baseline, report) |
| `status [--json]` | all | any | the phase, each eval's spec, trust and changes since its baseline, and the next step (§12) |
| `validate [--warnings] [--all]` | all | any | every missing and invalid field of each spec, the cases' problems, and with `--warnings` the notes and defaults |
| `import FILE --source S --query Q --window W` | sampling design | Build | copies an export into `data/` with its provenance; `--handoffs-of COMPONENT` imports handoffs captured as they happened |
| `handoffs [--from ID] [--id ID] [--scan]` | sampling design | Build | extracts a component eval's frame from the end-to-end traces; `--scan` counts the handoffs into each component |
| `plan [--assumed-rate R] [--flip-rate D] [--total N] [--write]` | sampling design, decision rule | Build | case targets per use case and pool from the decision rule's power, by optimum allocation |
| `draw [--n UC=N] [--skip ID --reason R] [--prune] [--dry-run]` | sampling design | Build | the seeded stratified draw of the quality set from the frame, with π |
| `screen [--judges] [--read-by NAME] [--drop ID --reason R]` | sampling design, measurement | Build | the reference, do-nothing, non-answer and liar screens per case, and who read it |
| `run --purpose P [--k N] [--variable V] [--model ID]` | all | Build | runs the agent over the cases; `--use-case`, `--case`, `--resume`, `--no-judges`, `--pause-every` |
| `replay run\|seed\|observe RECORDS` | agent contract | Build | acts as the agent and its hooks from recorded runs, for agents that can't run safely |
| `snapshot [--exclude GLOB]` | agent contract | Build | a hash per file of the working tree, for an `observe` hook |
| `compare [--baseline ID] [--candidate ID]` | decision rule | Build | the paired comparison and the decision on the candidate, saved under `report/comparisons/` |
| `coverage [--json]` | sampling design | Build | coverage entries × failure modes over the bug-finding set, against `coverage.yaml` |
| `ops [--run ID \| --export ID --field K=V]` | decision rule | Build | the operational sweep (cost per success, latency p50/p90, errors) against the spec's constraints per use case |
| `components [--json]` | all | any | the optimization loop's components grouped by part, each with its phase and state |
| `serve [--open] [--host H] [--port P]` | measurement | Judge | the grader application for one eval |
| `agreement [label queue\|page\|import\|add\|status] [rule] [regrade]` | measurement | Judge | whole-run labels, rulings, re-grading, and the eval held to people (`report/agreement.json`) |
| `label queue\|page\|import\|add\|status --judge ID` | measurement | Judge | labels per judge |
| `calibrate --judge ID [--dry-run] [--cached-only]` | measurement | Judge | catch and clean pass rates per backend, on the judge's labels |
| `reliability --judge ID --backend A --backend B` | measurement | Judge | self-consistency and cross-family agreement |
| `judge apply --judge ID --run ID` | measurement | Judge | judges a past run with a judge |
| `report [--run ID ...] [--candidate ID ...]` | all | any | writes `report/report.json` (§10) |
| `migrate --to 2 [--dry-run]` | all | | converts a 1.x suite into a 2.0 agent folder with one eval, `end-to-end`, and writes MIGRATION.md |
| `log TEXT [--kind K] [--detail D] [--by NAME]` | | any | adds to the activity log; `--kind decision` on an eval records its `spec_sha` |
| `activity [--open]` | | any | renders the activity page, `journal/activity.html` |
| `telemetry [status\|show\|off\|on]` | | any | pseudonymous usage telemetry ([SECURITY.md](../SECURITY.md#telemetry)) |

**`migrate --to 2`** reads a 1.x suite in `evals/`, `evals/<agent>/` or `evals/agents/<agent>/`
and writes `evals/agents/<agent>/` with one eval, `end-to-end`. It moves files with `git mv` where
git tracks them, renames case fields (`category` → `use_case`, `set` → `pool`, `taxonomy_entries`
→ `coverage_entries`), writes `eval.yaml` from categories, failure modes, budgets and floors
(traffic weights, costs null, superiority at α 0.05 and 80% power, `max_inflation` 2.0, correction
none, seed 1, cluster key `id`), keeps the 1.x files it read in `migrated-from-1x/`, and writes
`MIGRATION.md` in the agent folder with every decision it made and every line to check by hand.
The decision and the margin are left missing for the owner. A migrated eval reports nothing until
its quality set is drawn and run again: hand-picked cases carry no `draw`, and 1.x runs are not
2.0 runs.

---

## 10. report.json

`report` writes `<eval>/report/report.json`, schema `aot-evals/report@2`. Keys may be added within
v2, never removed or renamed. Unknown values are `null` with a reason, never 0, and nothing is
pre-rounded. The `report` skill writes its HTML from this file and nothing else.

| Key | Holds | Part |
|---|---|---|
| `schema`, `generated`, `runs`, `refused` | the runs reported; `refused` says why they can't stand for the current spec | |
| `eval` | `{id, version, unit, quantity, decision}` | Estimand |
| `spec` | `{complete, missing[], invalid[], notes[], defaults[], sha{estimand, design, measurement, decision_rule}}` | all |
| `estimate` | the headline: `{theta, ci, ci_method, se, quantity, weights, weights_source, estimator, corrected, correction, corrected_reason, uncorrected, n_cases, n_clusters, n_effective, k, null_reason}` | Estimand, design |
| `use_cases[]` | one row per use case and pool: `share`, `cost`, `weight`, `inclusion_prob_range`, `n_cases`, `estimate` (quality pool only), `estimate_corrected`, `pass_rate`, `pass_pow_k`, `flaky`, `variance_band`, `zero_failure_bound`, `clusters`, `variance_components`, `operational`, `excluded` | Estimand, design |
| `design` | `{quality{n, drawn, frame, seed, oversample, strata, skips, refused}, bug_finding{n, coverage}, clusters{n, cluster_key, design_effect, icc, largest, mean_size, shared_with_bug_finding}, cases_without_pool}` | Design |
| `measurement` | `{failure_modes[{id, check, type, use_cases, observed_rate, catch, clean, j, labels, inflation, inflation_at_lower_bounds, floor, corrected_rate, feeds_estimate}], eval_vs_people, person_anchored, variance, people, trials, max_inflation, correction, gates[]}` | Measurement |
| `decision` | `{test, quantity, bar, margin, alpha, power, looks, combine, multiplicity, subject, result, reasons, null_reason, interval, detectable_effect, cases_needed, headline, gates[], also_requires[], constraints, look, refused}` | Decision rule |
| `comparison` | with `--candidate`: Δθ̂ design-weighted, gains and losses, flips, the verdict from the paired sign-flip test per cluster, per-use-case rows with adjusted p-values, bug-finding flips apart, new budget breaches; else null | Decision rule |
| `checks` | per check, with `catch` and `clean` | Measurement |
| `gates` | the evidence gates, keyed by part: `{agent_contract[], design[], measurement[]}` (§11) | Agent contract, design, measurement |

**The estimate** ([estimators §7](estimators.md#7-the-estimate),
[statistics §2.1](statistics.md#21-two-pools-because-there-are-two-questions)). A trial scores 1
for `pass_rate` when every counted check of the modes that apply to its case passed, and for
`failure_rate:<mode>` when that mode's check failed; a trial missing a counted verdict is unscored.
ŷ is a case's mean over its scored trials. θ̂ = Σ w_s μ̂_s over the use cases with weight, μ̂_s the
Hájek mean of ŷ over the quality cases that count (a valid draw, screened, committed). Its interval
is normal, with each use case's linearized variance summed over clusters and floored at an
Agresti–Caffo-adjusted binomial variance ([statistics §2.3](statistics.md#23-allocation-how-many-cases-per-use-case)).
`theta` is null with `null_reason` when the spec blocks the estimate, a weight is unstated, there
is no run, a use case with weight has no scored case, the runs are refused, a counted judge that
feeds the quantity does not count, or the correction lacks its measurement.

**The correction** applies after the uncorrected θ̂, which stays in `estimate.uncorrected`.
`rogan_gladen` corrects θ̂ and each use case's μ̂ for the grader's catch and clean pass rates, with
a delta-method interval that adds the calibration's uncertainty (Rogan & Gladen 1978;
[statistics §3.2](statistics.md#32-a-judge-is-a-diagnostic-test)). Its grader is the quantity's
judge for `failure_rate:<mode>`, and the eval against people for `pass_rate`. `ppi` combines the
trials a person labeled with every graded trial, each weighted by its case's share of θ̂ (PPI++;
Angelopoulos, Duchi & Zrnic 2026; [statistics §3.6](statistics.md#36-the-whole-eval-against-people)),
and assumes the labels were drawn at random. A `failure_rate` whose check is code has nothing to
correct. A correction whose measurement is missing leaves θ̂ null with the reason, never silently
uncorrected. The store's refund eval uses Rogan–Gladen because its judge's labels are on past runs,
not drawn from the report's.

**The decision** ([statistics §4](statistics.md#4-the-decision-rule); `decision.py`). It is about
the candidate's runs under `report --candidate` or `compare`, else about the reported runs, so a
paired rule with no candidate is `unknown`.

- **Each gate** (the headline and each use case gate) is one one-sided test at α. A **threshold**
  test on a rate as graded uses the one-sided Clopper–Pearson bound at Kish's effective size over
  the design weights (Korn & Graubard 1998; [statistics §4.1](statistics.md#41-case-counts-come-from-power)),
  so with equal weights it is the exact binomial test and 0 failures in 32 cases do not clear a 5%
  bar; a corrected estimate keeps a one-sided normal bound. When a counted judge feeds an
  uncorrected estimate, the bar is read on the grader's scale, (1 − clean) + J·bar. A
  **superiority** test (H0 Δ ≤ 0) and a **non-inferiority** test (H0 Δ ≤ −margin) are one-sided
  sign-flip tests on the paired, design-weighted per-case deltas, with signs flipped per cluster
  ([statistics §4.4](statistics.md#44-which-test), [§4.5](statistics.md#45-no-difference-isnt-no-worse));
  a non-inferiority margin is read on the grader's scale at J's lower bound, and with J unknown the
  gate is unknown.
- **A gate's result** is `pass` when its test rejects at α; `fail` when the two-sided 1 − 2α
  interval sits at or beyond the null on the wrong side; `insufficient` otherwise, with
  `cases_needed` (the cases like these that power 1 − β at the measured spread would take), and a
  reason that says first when the point estimate is already past the null; and `unknown`, with its
  reason, when there is nothing to test.
- **Gates combine** by `combine`: `all` is the worst of fail, unknown, insufficient and pass, with
  no correction (an intersection–union test; Berger 1982); `any` adjusts the p-values by
  `multiplicity` and passes when one gate passes at its adjusted p. `also_requires` must pass
  either way: each entry is tested on the other eval's candidate runs that declare the same
  variable at the same agent commit, and is unknown until they exist, while either side has
  uncommitted changes, or when those runs hold no case of the use cases the component's handoffs
  came from.
- **Constraints** are read per use case on the decided runs, each breach marked `new` when the
  baseline did not have it. Gates that pass with a breach are a `trade`. Budgets are compared as
  point values (§13).
- **Looks.** Under `looks: fixed`, `report` and `compare` append each decision with a result to
  `report/looks.jsonl`, keyed by the decision rule's hash and the change; deciding the same change
  again on other runs is a second look and leaves the result unknown.
- **The comparison's verdict** is the two-sided sign-flip test at 2α (so `better` is exactly the
  superiority test passing at α), with its 1 − 2α interval; a new budget breach makes `better` a
  `trade` and `indistinguishable` a `worse`. Per-use-case rows are diagnostics, with p-values
  adjusted by `multiplicity`, or Benjamini–Hochberg when it is `none`.

---

## 11. Gates

A 2.0 eval has no numbered command gates. What 1.x checked as gates is now one of three things,
each with a stable id so a fixture can trigger exactly one (`tests/test_fixtures.py`,
`tests/test_judges.py`):

1. **Spec fields** (`spec.missing`, `spec.invalid`, §5): what the spec lacks, with what each blocks.
2. **Evidence gates** (`gates` in report.json, `evidence.py`): whether the runs can carry the
   number. They are computed on every run the report reads. `status` is `pass`, `fail`, or null
   when there is nothing to judge. None nulls θ̂ by itself: the cases `screened` and `committed`
   name are already left out of it, and the others are read beside the number.
3. **Measurement gates** (`measurement.gates` in report.json, and `gates` in agreement.json):
   whether the graders' error rates are measured and within the spec.

| Part | id | Fails when |
|---|---|---|
| agent_contract | `manifest` | a run's manifest lacks `agent_commit`, `evals_commit`, `harness`, `k` or a model id per call site; or eval files changed during the run, or the agent's output names them (re-run with `invoke.isolate: true`) |
| agent_contract | `trials_complete` | a (case, trial) the run planned has no final attempt, or a trial's attempt numbers skip one |
| design | `screened` | a case of the runs has not passed its screen; such cases stay out of θ̂ |
| design | `committed` | a case file of the runs is untracked or has uncommitted edits (kept out of θ̂, rule 17), or the runs hold attempts for a case the eval doesn't have |
| design | `coverage_list` | the coverage list names no source, is made from the cases, lacks `read_on` or entries, or was not committed before the first case |
| measurement | `independent_reference` | a counted code check declares `USES_AGENT_REPORT = True`, or a case's screen found it passing on a bare claim of success |
| measurement | `k` | a run other than a smoke run has k < 3 |
| measurement | `judge_floor` | a counted judge's inflation at its lower bounds is over `max_inflation`, or there is no rate to read it at yet |
| measurement | `judge_calibration` | a counted judge has no current calibration |
| measurement | `people_unmeasured` | the eval has not been held to people's labels |
| measurement | `people_stale` | the eval against people was measured before the checks or labels changed |
| measurement | `people_labels` | a kind of whole-run label is short of its count (agreement.json) |
| measurement | `people_disputes` | labelers disagree on a run nobody has ruled on (agreement.json) |
| measurement | `people_floor` | the eval's catch or clean pass rate does not meet its floor with the margin (agreement.json) |
| measurement | `people_triage` | a dev disagreement has no cause (agreement.json) |

The comparison's refusals (§8) and its `trade` and `worse` verdicts (§10) are the decision rule's
counterpart.

---

## 12. Status: phase and trust

`status` reads each eval's report the way a team does (`trust.py`). For the agent, it prints the
phase of its earliest eval; for each eval, its phase, its trust, what changed since its baseline,
and the next step. `status --json` carries the same, with each eval's spec lists.

**Phase.** No eval and no discovery report: **Assess**. A discovery report and no eval yet, or an
eval with no number under its current spec (no baseline, a refused run, θ̂ null): **Build**, with
its next step in order (the first field blocking a run, draw or estimate; the draw; the screens;
the baseline). A baseline with θ̂ under the current spec: **Judge**.

**Trust**, per eval:

| Level | When |
|---|---|
| untested | no number yet: no baseline under the current spec, or θ̂ null with its reason |
| provisional | θ̂ exists, but at least one of the conditions below is open; each open one is listed with its command |
| trusted | every spec field filled; every counted judge within `max_inflation` (no `judge_floor` or `judge_calibration` gate); the eval against people meets its floors and is not stale; and the quality set holds what the decision rule's power calls for (every quality row of the plan drawn to its target) |

A paired rule's plan needs a flip rate; `status` takes it from the newest saved comparison, and
until one exists says the plan can't size the rule yet.

**Changes since the baseline**, each with the way back:

| Change | Read from | Next |
|---|---|---|
| a revision: the estimand, design or measurement changed | the newest baseline's `spec_sha` against the current spec | run the baseline again under the current spec |
| the decision rule changed | the same, `decision_rule` | commit eval.yaml or `log --kind decision` before the candidate runs |
| the agent has uncommitted changes | `git status` outside evals/ | commit before running |
| the agent changed | the baseline's `agent_commit` against the working tree's | a candidate run with one declared variable, then `compare` |
| a candidate has run and not been compared | runs and `report/comparisons/` | `compare`, then label what moved |

`components` gives each component of the loop a phase as well: the estimand's components belong to
Assess, the judges and the labeling components (the grader application, the calibration set, two
blind labels per run, the grader pool, the eval held to people) to Judge, and the rest to Build.

---

## 13. Not in 2.0

**Removed without a 2.0 replacement:**

- `checkpoint` (the checkpoint pages): the skills write their summary in the conversation and log a
  question to the activity page instead.
- `redundancy` (the prune proposal): pruning is by hand, under rule 25.
- `report --html` (the branded HTML shell): the `report` skill writes the HTML itself from
  report.json v2.
- `status --gates` (the C0–C19 gate table): `status` and `validate` list spec fields, and report.json
  the evidence and measurement gates.
- G4, the refusal of a same-family generative judge for pairwise grading. A pairwise judge should
  still come from a different family than both sides and judge both orders
  ([statistics §3.5](statistics.md#35-reliability-is-not-validity)); nothing checks it yet.

**Not computed yet:**

- `looks: sequential` and `looks: optimizer_holdout` leave the decision `unknown`, with a validate
  note: no always-valid interval or reusable holdout is built yet
  ([statistics §4.7](statistics.md#47-looks-stop-peeking)).
- Budgets are compared as point values. Medians and p90 with bootstrap intervals
  ([statistics §4.8](statistics.md#48-cost-and-latency-are-constraints)) are not computed yet.
- A probabilistic judge's threshold maximizes catch + clean pass rate, not the cost-based threshold
  of [statistics §3.2](statistics.md#32-a-judge-is-a-diagnostic-test).
- Shares are measured again by hand on a schedule; nothing detects a population shift (rule 26),
  and drift has no control chart yet ([statistics §1.4](statistics.md#14-when-the-population-moves)).
- report.json v2 has no `coverage`, `redundancy`, `cases`, `conditions` or `next_actions` keys yet;
  `aot-evals coverage` prints the coverage grid.

**Out of scope:** simulated users, and whether a pass in the sandbox means a pass in production
([estimators §11](estimators.md#11-out-of-scope-and-open-problems)).

---

## 14. Lineage

None of the four parts is new. aot-evals writes them down for each eval of an agent and lets the
rules follow from them ([estimators §12](estimators.md#12-prior-work) has the closest prior work):

- **The estimand** comes from validity theory in psychometrics: a score's meaning is the
  interpretation it supports for a use (Cronbach & Meehl 1955; Messick 1989; AERA, APA & NCME 2014),
  and from the estimands framework of clinical trials, brought to ML evaluation by Binette & Reiter
  (2024). Weights from share × cost are decision theory's expected loss.
- **The sampling design** is survey statistics: stratified sampling and optimum allocation (Neyman
  1934; Cochran 1977), inclusion probabilities and the Horvitz–Thompson estimator (Horvitz &
  Thompson 1952), its Hájek form (Hájek 1971), and clusters and the design effect (Kish 1965).
  Software testing drew the same line between testing to find faults and testing to measure
  reliability (Musa 1993; Frankl et al. 1998), and the coverage grid is category-partition testing
  (Ostrand & Balcer 1988).
- **The measurement model** is diagnostic testing: sensitivity and specificity (here catch rate and
  clean pass rate), Youden's J (Youden 1950), the Rogan–Gladen correction (Rogan & Gladen 1978),
  misclassification's cost in power (Bross 1954); inter-rater agreement (Cohen 1960; Gwet 2008);
  generalizability theory for trials (Cronbach et al. 1972); and prediction-powered inference for
  combining labels with a grader's verdicts (Angelopoulos et al. 2023; Angelopoulos, Duchi & Zrnic
  2026).
- **The decision rule** is hypothesis testing (Neyman & Pearson 1933), with paired permutation
  tests (Fisher 1935), non-inferiority margins from clinical trials (U.S. FDA 2016), exact binomial
  bounds (Clopper & Pearson 1934) adapted to survey weights (Korn & Graubard 1998), the
  intersection–union test (Berger 1982), multiplicity corrections (Holm 1979; Benjamini & Hochberg
  1995), sequential analysis (Wald 1947), and the reusable holdout (Dwork et al. 2015).

Applied to language-model evaluation, Miller (2024) treats eval questions as a sample with clustered
errors and paired tests, and Chouldechova et al. (2024) define the population an eval measures.

---

## 15. References

Full entries for every source the three guiding documents cite are in
[estimators §13](estimators.md#13-references) and [statistics §5](statistics.md#5-references). The
ones cited on this page:

- AERA, APA & NCME (2014). *Standards for Educational and Psychological Testing.* Washington, DC: American Educational Research Association.
- Angelopoulos, A. N., Bates, S., Fannjiang, C., Jordan, M. I. & Zrnic, T. (2023). Prediction-powered inference. *Science* 382(6671):669–674. doi:10.1126/science.adi6000
- Angelopoulos, A. N., Duchi, J. C. & Zrnic, T. (2026). PPI++: Efficient prediction-powered inference. *The Annals of Applied Statistics* 20(3):2235–2252. doi:10.1214/26-AOAS2215. arXiv:2311.01453
- Benjamini, Y. & Hochberg, Y. (1995). Controlling the false discovery rate: A practical and powerful approach to multiple testing. *JRSS B* 57(1):289–300. doi:10.1111/j.2517-6161.1995.tb02031.x
- Berger, R. L. (1982). Multiparameter hypothesis testing and acceptance sampling. *Technometrics* 24(4):295–300. doi:10.2307/1267823
- Binette, O. & Reiter, J. P. (2024). Improving the validity and practical usefulness of AI/ML evaluations using an estimands framework. arXiv:2406.10366
- Bross, I. (1954). Misclassification in 2 × 2 tables. *Biometrics* 10(4):478–486. doi:10.2307/3001619
- Chouldechova, A. et al. (2024). A shared standard for valid measurement of generative AI systems' capabilities, risks, and impacts. NeurIPS 2024 Workshop on Statistical Foundations of LLMs and Foundation Models. arXiv:2412.01934
- Clopper, C. J. & Pearson, E. S. (1934). The use of confidence or fiducial limits illustrated in the case of the binomial. *Biometrika* 26(4):404–413. doi:10.1093/biomet/26.4.404
- Cochran, W. G. (1977). *Sampling Techniques* (3rd ed.). New York: Wiley.
- Cohen, J. (1960). A coefficient of agreement for nominal scales. *Educational and Psychological Measurement* 20(1):37–46. doi:10.1177/001316446002000104
- Cronbach, L. J., Gleser, G. C., Nanda, H. & Rajaratnam, N. (1972). *The Dependability of Behavioral Measurements: Theory of Generalizability for Scores and Profiles.* New York: Wiley.
- Cronbach, L. J. & Meehl, P. E. (1955). Construct validity in psychological tests. *Psychological Bulletin* 52(4):281–302. doi:10.1037/h0040957
- Dwork, C., Feldman, V., Hardt, M., Pitassi, T., Reingold, O. & Roth, A. (2015). The reusable holdout: Preserving validity in adaptive data analysis. *Science* 349(6248):636–638. doi:10.1126/science.aaa9375
- Fisher, R. A. (1935). *The Design of Experiments.* Edinburgh: Oliver & Boyd.
- Frankl, P. G., Hamlet, R. G., Littlewood, B. & Strigini, L. (1998). Evaluating testing methods by delivered reliability. *IEEE Transactions on Software Engineering* 24(8):586–601. doi:10.1109/32.707695
- Gwet, K. L. (2008). Computing inter-rater reliability and its variance in the presence of high agreement. *British Journal of Mathematical and Statistical Psychology* 61(1):29–48. doi:10.1348/000711006X126600
- Hájek, J. (1971). Comment on "An essay on the logical foundations of survey sampling, part one" by D. Basu. In V. P. Godambe & D. A. Sprott (Eds.), *Foundations of Statistical Inference* (p. 236). Toronto: Holt, Rinehart and Winston.
- Holm, S. (1979). A simple sequentially rejective multiple test procedure. *Scandinavian Journal of Statistics* 6(2):65–70.
- Horvitz, D. G. & Thompson, D. J. (1952). A generalization of sampling without replacement from a finite universe. *JASA* 47(260):663–685. doi:10.1080/01621459.1952.10483446
- Kish, L. (1965). *Survey Sampling.* New York: Wiley.
- Korn, E. L. & Graubard, B. I. (1998). Confidence intervals for proportions with small expected number of positive counts estimated from survey data. *Survey Methodology* 24(2):193–201.
- Messick, S. (1989). Validity. In R. L. Linn (Ed.), *Educational Measurement* (3rd ed., pp. 13–103). New York: American Council on Education / Macmillan.
- Miller, E. (2024). Adding error bars to evals: A statistical approach to language model evaluations. arXiv:2411.00640
- Musa, J. D. (1993). Operational profiles in software-reliability engineering. *IEEE Software* 10(2):14–32. doi:10.1109/52.199724
- Neyman, J. (1934). On the two different aspects of the representative method: The method of stratified sampling and the method of purposive selection. *JRSS* 97(4):558–625. doi:10.2307/2342192
- Neyman, J. & Pearson, E. S. (1933). On the problem of the most efficient tests of statistical hypotheses. *Phil. Trans. R. Soc. A* 231:289–337. doi:10.1098/rsta.1933.0009
- Ostrand, T. J. & Balcer, M. J. (1988). The category-partition method for specifying and generating functional tests. *Communications of the ACM* 31(6):676–686. doi:10.1145/62959.62964
- Rogan, W. J. & Gladen, B. (1978). Estimating prevalence from the results of a screening test. *American Journal of Epidemiology* 107(1):71–76. doi:10.1093/oxfordjournals.aje.a112510
- U.S. Food and Drug Administration (2016). *Non-Inferiority Clinical Trials to Establish Effectiveness: Guidance for Industry.* https://www.fda.gov/media/78504/download
- Wald, A. (1947). *Sequential Analysis.* New York: Wiley.
- Youden, W. J. (1950). Index for rating diagnostic tests. *Cancer* 3(1):32–35. doi:10.1002/1097-0142(1950)3:1<32::aid-cncr2820030106>3.0.co;2-3
