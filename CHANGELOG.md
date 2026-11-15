# Changelog

All notable changes to aot-evals. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and versions follow [Semantic Versioning](https://semver.org/) as described in
[CONTRIBUTING.md](CONTRIBUTING.md#versioning).

## Unreleased

## 2.0.0 — 2026-11-14

aot-evals 2.0 organizes everything around the four parts of an eval: the **estimand** (what
number, about what, drives which decision), the **sampling design** (which cases, drawn how), the
**measurement model** (how wrong the grader is) and the **decision rule** (when to act). Each eval
writes them down in one file, `eval.yaml`, and the rules for building a suite follow from them
([docs/estimators.md](docs/estimators.md)). Assess, Build and Judge stay as the three phases, each
settling some of the parts. [docs/method.md](docs/method.md) is rewritten as the reference for
2.0; [docs/problems.md](docs/problems.md) shows why each part matters and
[docs/statistics.md](docs/statistics.md) derives the numbers.

### Upgrading from 1.x

The agent contract is unchanged: the stdin and stdout fields, the hooks, the outcome codes and the
per-result field names are as in 1.x, so an agent that runs under 1.x runs under 2.0. The suite
around it changes, and 2.0 refuses a folder that still holds a 1.x suite.

1. **Convert the suite:** `aot-evals migrate --to 2 --dry-run`, then `aot-evals migrate --to 2`.
   It turns a 1.x suite (in `evals/`, `evals/<agent>/` or `evals/agents/<agent>/`) into
   `evals/agents/<agent>/` with one eval, `end-to-end/`, moving files with `git mv` where git tracks
   them, and writes **MIGRATION.md** in the agent folder: every default it chose, the check it
   chose per failure mode, each dropped field with its value, the files it left in place, and the
   lines to check by hand. The 1.x files it read are kept in `migrated-from-1x/` to check against.
2. **Fill what only the owner knows**, as MIGRATION.md lists: `estimand.decision` (the action and
   its owner), `decision_rule.margin`, and the cost of a failure per use case (1.x never put a
   number on it; the migrated eval uses traffic weights until the owner states costs).
   `aot-evals validate` lists every field still missing.
3. **Draw the quality set and run a new baseline.** Hand-picked 1.x quality cases carry no draw
   and do not count toward the estimate, and 1.x runs are not 2.0 runs, so a migrated eval reports
   nothing until `aot-evals plan --write`, `aot-evals draw`, the screens, a commit and a baseline.
4. **Check by hand** what MIGRATION.md names: code checks that find files from their own path
   (`Path(__file__).parents[k]`) sit one folder deeper, and scripts that name a moved folder.
5. **Readers of report.json** move to `aot-evals/report@2` (docs/method.md §10): `sets` and
   `categories` become `estimate`, `design` and `use_cases`; the G1–G14 list becomes `spec`
   (missing and invalid fields) and `gates` (evidence, keyed by part); judges report `catch` and
   `clean`, with `tpr` and `tnr` kept beside them. The run manifest is `aot-evals/run-manifest@2`.
6. **Judges** drop `min_tpr` and `min_tnr`: a judge counts when its errors cost no more cases than
   the eval's `measurement.max_inflation` allows (default 2.0).
7. **Renamed:** `category` → `use_case`, `set` → `pool` (`quality`, `bug_finding`), `taxonomy.yaml`
   → `coverage.yaml`, `allocate` → `plan`, `run --category` → `run --use-case`, TPR and TNR → clean
   pass rate and catch rate.

### Removed without a 2.0 replacement

- **Commands:** `checkpoint` (the skills summarize in the conversation and log a question to the
  activity page), `redundancy` (prune bug-finding cases by hand, never quality cases), `report
  --html` (the `report` skill writes the HTML from report.json v2), and `status --gates` (`status`
  and `validate` list the spec's fields; report.json carries the evidence and measurement gates).
- **Gates:** G4, the refusal of a same-family generative judge for pairwise grading (nothing checks
  the judge's family yet), and G9, the fidelity of simulators and fakes (simulated users are out of
  scope; the `env/` fakes stay, hashed into every run).
- **Flags and fields:** `run --force`; agent.yaml `simulator` and `validity` (compounded validity:
  the eval held to people measures it); the category `simple` flag and its 3-case target; the "Other
  under 10%" rule; report keys `online`, `regime`, `validity` and `conditions.simulator`; the
  variance band as part of the compare verdict (it is reported as data for drift).
- **The `assess` skill** is folded into `start`, which runs Assess when there is no discovery
  report. **references/process/**, the 1.x step-by-step process organized by category, is removed:
  its sizing rules (10 cases per category, 3 for a simple one) are replaced by counts from each
  eval's decision rule.

Everything else in 1.x has a 2.0 counterpart: the C0–C19 command gates and the G1–G14 report gates
become the spec's missing and invalid fields plus the evidence and measurement gates
(docs/method.md §11).

### Not computed yet

- `looks: sequential` and `looks: optimizer_holdout` leave the decision `unknown`, with a validate
  note: no always-valid interval or reusable holdout is built yet.
- Budgets are compared as point values, not as medians and p90 with intervals.
- A probabilistic judge's threshold maximizes catch + clean pass rate, not the cost-based threshold
  of docs/statistics.md §3.2.
- Nothing detects a population shift or drift yet; shares are measured again by hand.
- report.json v2 has no `coverage`, `redundancy`, `cases`, `conditions` or `next_actions` keys
  yet; `aot-evals coverage` prints the coverage grid.

### New

- **The eval spec** (`eval.yaml`, `spec.py`). `aot-evals --eval ID init [--component NAME]`
  creates an eval in `evals/agents/<agent>/<eval>/` beside the agent system's shared `env/`,
  `data/`, labeling standard and journal. The loader lists every missing and invalid field with the
  numbers it blocks, plus notes and the defaults it filled (one-sided α 0.05, power 0.80, fixed
  looks, `max_inflation` 2.0, the eval-vs-people margin 0.10 and labels per kind). An incomplete
  eval still runs; its report nulls what depends on the missing fields. The global `--eval` option
  selects an eval.
- **Estimand.** Use cases with shares and the cost of a failure, and weights (`traffic`, `cost` or
  stated). report.json v2's headline is the weighted θ̂ (a Hájek estimate with a cluster-aware
  interval), with the per-use-case table beside it.
- **Sampling design.** `aot-evals --eval ID plan [--write]` sizes each use case's quality set from
  the decision rule's power (with each judge's error counted), around use case gates and
  oversampling, by optimum allocation; what it can't know before a baseline it asks for
  (`--assumed-rate`, `--flip-rate`, `--total`). `aot-evals --eval ID draw` draws the quality set
  from the frame, seeded and stratified, with each case's inclusion probability; skips are logged
  with their reason, and drawn cases are removed only with `--prune`. Cases carry `use_case`,
  `pool`, `draw` and `cluster`.
- **Measurement model.** Catch rate and clean pass rate everywhere, each with its interval, lower
  bound and labels per kind. A judge counts when its inflation factor at its lower bounds is within
  `max_inflation`, read at the baseline's failure rate for a candidate (so a candidate that fails
  less never loses its judge); a judge that doesn't count and feeds the quantity leaves θ̂ null. Corrections feed
  the estimate (`rogan_gladen`, `ppi`). The eval is held to people with floors read through a
  non-inferiority margin and a label count fixed before looking. `trials: auto` takes k from the
  baseline's variance split.
- **Decision rules.** Superiority, non-inferiority and threshold tests per gate (the headline and
  each use case gate): the threshold on an exact Clopper–Pearson bound at Kish's effective size,
  the paired tests by sign flips per cluster on design-weighted deltas. Each gate is `pass`, `fail`,
  `insufficient` (with the cases that would decide it) or `unknown` with its reason. Gates combine
  with no correction when all must pass, or by Holm or Benjamini–Hochberg when any one acts;
  constraints make a passing change a `trade`; under fixed looks a change is decided once.
  `compare` and `report --candidate` refuse runs made under another estimand, design or
  measurement, and a decision-rule change not on record (a commit of eval.yaml, or `log --kind
  decision`) before the first run decided on.
- **Several evals per agent.** agent.yaml's `components` lists each subagent, route and step with
  its context and whether it ships on its own; a component gets an eval of its own only at a context
  boundary and when decided on separately. `aot-evals --eval ID handoffs` extracts a component
  eval's frame from the end-to-end traces, and `import --handoffs-of COMPONENT` imports handoffs
  captured as they happened. A component eval must also require the end-to-end eval
  (`also_requires`, non-inferiority), tested on the end-to-end runs of the same change.
- **The online store** (`examples/store/`) is the example, `aot-evals demo` and the test fixture: a
  support agent and its refund subagent, fakes for the order system and payments, a trace export
  whose refund traces record their handoffs, both evals with drawn quality sets and bug-finding sets,
  a policy judge calibrated on 100 failure and 500 pass labels beside a weaker one the floor refuses,
  and variants for the problems' scenarios. The demo runs both baselines, then a refund-subagent
  change that improves its own eval and breaks refunds end to end.
- **Phases and trust in `status`.** `status` names the agent's phase (Assess, Build or Judge, its
  earliest eval's), then for each eval its phase, its trust (untested, provisional or trusted: every
  spec field filled, every counted judge counting, the eval held to people at its floors, and the
  quality set its decision rule needs), what changed since its baseline (a revision, a decision-rule
  change, the agent, an uncompared candidate) with the way back, and the next step. `status --json`
  carries the same beside each spec's lists. `components` rows carry `phase` again.
- **The skills** (`start`, `build`, `judge`, `report`) are rewritten around the four parts and the
  terms of docs/estimators.md. `start` runs Assess itself, with questions that settle the estimand
  (the decision and its owner, the cost of a failure, what a change must show). The `report` skill
  writes its HTML from report.json v2, organized by part.
- **The grader application** serves one eval (`serve --eval`): its spec, its baseline and latest
  candidate, the eval against people, and per use case its cases, labeled runs and catch and clean
  pass rates. Labels, rulings, triage, proposals and drafts are the eval's own; accepted rules join
  the agent system's shared standard with their `use_cases`.
- **Evidence gates** in report.json v2, keyed by part: `manifest`, `trials_complete`, `screened`,
  `committed`, `coverage_list`, `independent_reference` and `k`.
- **The statistics library** (`aot_evals.stats`) adds, among others, `hajek_mean`,
  `stratified_hajek`, `optimum_allocation`, `judge_inflation`, `cases_needed`, `threshold_test`,
  `threshold_n`, `rate_bound_test`, `kish_n`, `superiority_test`, `non_inferiority_test`, `holm`,
  `rogan_gladen_rate`, `ppi_weighted`, `trials_for_split` and `draw_order`.
- **The published method** (`evals.json`, schema `aot-evals/site@2`, and the method zip) is built
  from docs/method.md, the three guiding documents and the store example; see CONTRIBUTING.md.

### Fixed

- `stats.floor_evidence` rounded the count at each candidate size, so 13 of 15 was sized as 42 of 48
  and reported 48 labels where 53 are needed. The "about N labels" hint in `calibrate` and
  `agreement` changes with it.
- A threshold rule on a rate passed a 5% failure-rate bar at 0 failures in 32 cases, and at 3 of 150
  and 5 of 200, on a normal bound; it now uses the exact bound.
- The committed-cases check missed an edited case file whose status line came first, and git
  status's first path lost a character; Python's bytecode caches no longer count as eval files
  changed during a run.
- Command judges in an eval run from the repository root, as agent.yaml's paths do.

## 1.1.0 — 2026-11-11

- **The statistics behind the method** ([docs/statistics.md](docs/statistics.md)): for each decision
  (how many cases, trials and labels, when a judge or a category can be trusted, when a difference
  is real, what to prune) the rule aot-evals applies, its basis in the sampling, diagnostic-test,
  psychometric and experiment-design literature, and when to deviate. It audits every rule of
  thumb in the method and lists fifteen proposed changes (P1–P15) that this release does not make.
  No gate or verdict changes.
- New numbers, each informational (docs/method.md M30–M35, E16):
  - `allocate` prints the rarest failure each error-finding target surfaces with 95% probability,
    and the report gives a category with no failure its `zero_failure_bound` (M30).
  - Each category and set carries `variance_components`: between-case and within-case variance,
    ICC, effective n, and the standard error after doubling cases or trials (M31, E16).
  - Each judge check carries `corrected_trigger_rate`: how often its failure mode really occurs,
    given the judge's measured TPR and TNR, with an interval (M32).
  - `agreement` reports a `human_anchored` pass rate that combines the labels with the suite's
    verdict on every other run (prediction-powered inference, M33), and `evidence`: whether each
    dev rate clears its floor with enough runs behind it (M35). Calibration reports the same
    `evidence` for TPR and TNR, and `label status` says how many labels of each kind ±10 points needs.
  - Agreement between labelers adds Gwet's AC1 and agreement on fails and on passes separately,
    in the CLI and the grader application (M34).
  - `compare` adds a paired sign-flip test on every change in a case's pass rate, the detectable
    effect implied by the observed per-case deltas (`mde_from_deltas`), and Benjamini–Hochberg
    adjusted p-values per category (`p_adjusted_bh`).
  - `compare` prints the flips next to the net: b (pass→fail), c (fail→pass) and the flip rate d,
    with the interval they imply, plus McNemar's mid-p and the inverted sign-flip interval (M36).
- **Correlated cases.** A case may carry an optional `cluster` key (its template, source trace or
  seed). Pass-rate intervals and the zero-failure bound then count clusters, and `compare` flips
  signs per cluster, with Webb weights at 6–9 clusters, a cluster jackknife cross-check, and a note
  that nothing can reach 5% at five clusters or fewer. Without keys, both say "cases assumed
  independent". Each set gains a `dependence` block: Cochran's Q across repeats, and an
  over-dispersion test across clusters (M37).
- Pass-rate intervals use a t(G − 1) critical value instead of z, and the logit scale when a
  symmetric interval would cross 0% or 100% (`ci_method` `cluster_robust_t`, `cluster_robust_t_logit`).
  Intervals on suites with few cases are slightly wider; no gate reads them.
- `docs/statistics.md` adds what the score is for (a numeric weight per category, and a
  blind-spot check), a check for uneven failure costs, per-category sizing by improvement,
  regression guard and detection, and correlated cases; three proposals (P13 costs, P14 weights
  and allocation, P15 clusters) with a build order that puts costs and weights ahead of
  cost-weighted thresholds and weighted allocation. The library (`aot_evals.stats`) gains the
  functions they need: Student t, cluster summaries and jackknife, effective n, mid-p McNemar,
  flip-rate sizing, objective weights, the blind-spot check, per-category allocation targets,
  weighted Neyman allocation, seeded stratified draws and the cost check.

## 1.0.1 — 2026-11-04

- The process documents head their sections by steps (Steps 1–4, 5–7, 8–12) instead of "Phase 1-3", so
  "phase" only ever means Assess, Build or Judge. File names are unchanged.

## 1.0.0 — 2026-11-03

The first major release: three phases (Assess, Build, Judge), trust per category, a grader
application, and iteration as the organizing idea. The method's commands, gates and ids are unchanged; what changes is how they are
reached and read.

- **No command refuses to run because an earlier gate is unmet.** A gate is a trust upgrade: the
  run goes ahead, the note names the unmet gates, the manifest records them (`unmet_gates`; the
  old `forced_past_gates` is kept with the same value), and the report greys what they cover, as
  it already did. `--force` is accepted and does nothing. The lightest Build (an agent that runs,
  a few cases with a check each, a baseline) now reaches a number in one pass (docs/method.md §4.1).
- **`aot-evals status` reads like a team would:** the phase (Assess, Build or Judge), trust per
  category (untested, provisional, validated, with the reason), what changed since the baseline
  with the short path back for each kind of change (agent, new use case, cases, checks, judge,
  standard, labels, an uncompared candidate), and the one next step. `--gates` prints the gate
  table it used to print; `--json` carries both.
- `report/agreement.json` gains `categories`: catch and clean pass rates per category, dev and
  holdout, which is what makes a category `validated`.
- The run manifest records `standard_sha`, so a change to the labelling standard is detected.
- Checkpoint pages group the roadmap by phase (Build, Judge, Report) instead of five stages.
- **`aot-evals serve`, the grader application.** A local web page for the Judge phase, so
  graders can work without an engineer: label whole runs (blind, with a warm-up on settled runs
  and an overlap in every four for agreement between people), rule on runs labellers disagree on,
  re-grade the labelled runs offline, give each disagreement with the suite a cause, accept an
  answer as another correct wording (the case is screened again), propose rules for the owner to
  accept into the standard, label and recalibrate judges, draft new cases, and see what is
  waiting on engineering. Localhost by default, with a session token in the link; `&labeller=NAME`
  gives each grader their own link. Everything it writes is a suite file (docs/method.md §4.2).
- **Several labellers per run.** `labels/runs.jsonl` keeps each person's latest label beside the
  others' instead of replacing them. A run whose labellers disagree has no verdict until a ruling
  (`labels/rulings.jsonl`, or `aot-evals agreement rule`), and C19 stays open while one is unruled.
  `agreement label status` reports agreement between each pair of labellers, with κ.
- `aot-evals agreement label queue --changed` queues only the cases whose verdict moved between
  the baseline and the latest compared candidate.
- `status` names an agent change already run as a candidate and compared as a decision to make
  (label what moved, then adopt it as the baseline or put it back), not a run to repeat.
- **`aot-evals build`, the lightest Build.** It drafts categories from the discovery report's task
  types and the coverage list from its situations, adds one failure mode on every case checked by
  a generic end-state check (`checks/code/end-state-matches.py`), and prints the Build checklist.
  `aot-evals build --run` then does the smoke run, a k = 3 baseline and the report, and points at
  the grader application. A first pass no longer needs check code of its own.
- **`aot-evals components`**: the optimization loop's components as a checklist (sandbox, fakes,
  replay, golden cases, deterministic checks, holdouts, the grader application, the bench, judges,
  synthetic cases, the evaluation engine, monitoring, significance, the noise floor), each with the
  phase that builds it and its state read from the suite. The discovery report may record their
  state (`components:` in its front matter) and the page lists them. `status --json` carries it.
- **Five skills instead of eight.** `start` (where things stand, and the next step), `assess`
  (was `discover`), `build` (was `scope`, `build`, and the baseline and comparison half of `run`),
  `judge` (was `calibrate` and the agreement half of `run`) and `report`. `status`, `scope`,
  `calibrate` and `run` are gone: use `/aot-evals:start`. The shared pacing rules live once, in
  `references/working-in-checkpoints.md`. The gate table's skill column names the new skills.
- The banner, the discovery page and the docs speak of Assess, Build and Judge instead of Phase 1
  and Phase 2.

- **Suites made by earlier versions are found and read right.** A suite in the old layout,
  `evals/<agent>/`, is found from the repository, from inside it, and with `--evals evals
  --agent NAME` (which no longer treats `evals/` itself as a suite), with its repository root and
  discovery report resolved; a note offers `aot-evals migrate`, which moves it to
  `evals/agents/<agent>/` with `git mv`, beside a discovery report a later assessment put there.
- **The baseline is every category's newest baseline run**, not the single newest run: a re-run of
  one category no longer marks the others untested. `status`, the gates, `compare`, `report`,
  `judge apply` and the labelling queues all use it, and `status` says when its runs used
  different builds of the agent.
- **"The agent changed" means its files changed.** Two commits with the same files outside
  `evals/` are one agent, however many commits to the suite (or to an earlier layout) lie between.
- `status` groups judges whose fingerprint differs from the baseline's, says when one was edited
  without a version bump, and gives the step that fits its calibration (re-judge, recalibrate,
  iterate, or label first). Lists of changed checks and cases show every name or `+N more`, and a
  baseline recorded without check fingerprints no longer reports every check as new.
- C10 fails a judge whose calibration is below its floors (it passed before). The coverage list
  committed in the same commit as the first cases, as a squash merge leaves it, passes C2. C15
  says whether the discriminating fraction is above or below the point where a prune proposal is
  made, and why it can't be computed when it can't. C19 says when per-judge labels exist and
  whole-run labels don't yet. `components` takes each state from the same facts as the gates.
- Two runs started in the same second (category by category, on a fast agent) no longer share a
  run folder; the second gets `-2`.
- `validate` groups problems that differ only by case (`62 cases: no requirements (…, +57 more)`);
  `--all` prints one line each.

### Upgrading from 0.4

Existing suites keep working: no suite file needs to change, and every report, run and label
written by 0.4 reads as before. What does change:

- **Skills.** `/aot-evals:discover` is now `/aot-evals:assess`; `/aot-evals:status` is gone, use
  `/aot-evals:start`. The step skills `scope`, `calibrate` and `run` are folded into `build` and
  `judge`.
- **Nothing refuses on an unmet gate.** A script that relied on `aot-evals run` exiting non-zero
  until earlier gates were met should read `aot-evals status --json` instead.
- **`status` output.** The plain output is the phase summary; `--gates` prints the old table. In
  `--json`, `next` is now the next step (`what`, `how`, `phase`); the first unmet gate moved to
  `next_gate`. `gates` is unchanged.
- **A suite in `evals/<agent>/`** (made before 0.2) works as it is. `aot-evals migrate --dry-run`
  says what would move to `evals/agents/<agent>/`, and `aot-evals migrate` moves it.
- **Pages and helper scripts from earlier versions.** `report/case-review.html`, the
  `*.label.html` labelling pages and old `report/report-*.html` files can go: `aot-evals serve`
  replaces the labelling pages and `aot-evals report` writes reports fresh. `journal/activity.html`
  is rewritten on the next command. Helper scripts a team wrote beside its suite for labelling
  pages, paired comparisons or a judge of its own are now covered by `serve`, `compare` and the
  `command` judge backend; check them against those before deleting.
- **A second labeller no longer replaces the first.** In `labels/runs.jsonl`, a later label by
  another person sits beside the earlier one. Where two people disagree, the run counts toward
  nothing until a ruling: run `aot-evals agreement label status` to find any such runs in an
  existing suite, and rule on them in `aot-evals serve` or with `aot-evals agreement rule`.

## 0.4.2 — 2026-11-03

- **`aot-evals run --model <id>`** pins the agent's model for one run: it overrides
  `agent.yaml`'s `invoke.model`, reaches the agent as stdin `model` and the `{model}` placeholder,
  and is recorded in the manifest as `invoke.model`. A candidate run with no `--variable` declares
  `model=<id>`, and `--resume` keeps the run's model. Comparing a cheaper, local or fine-tuned
  model on the same suite no longer means editing `agent.yaml` between runs.

## 0.4.1 — 2026-10-30

- **The method as a download.** Each release now attaches `aot-evals-method-<version>.zip`, the
  method, process, practice findings, benchmark catalog and templates as plain files to read or
  hand to any coding agent without installing the plugin, and `evals.json`, the same as data
  (commands, gates, measurements, experiments, panels and every catalog entry) for the website.
  Nothing changes in the plugin.

## 0.4.0 — 2026-10-29

What our experiments comparing aot-evals with plain Claude Code taught us. Graded against a
person's pass or fail on the same recorded runs, a suite built and calibrated with aot-evals 0.1.1
caught 69% of the runs the person failed and passed 81% of the runs they passed; plain Claude
Code, given the same 79 requests, wrote suites that did better in all four sessions. Every miss
traced to a part nobody had checked against a whole run: requirements no check looked at,
expected answers bound to one wording, code-check bugs, and numbers inside answers that nothing
read. This release checks the whole. On runs no suite had seen, a suite built with it caught 93%
of the failures and passed 92% of the good runs, level with the best plain Claude Code suite.

- **C19 agreement**, right after the baseline: a person labels whole runs pass or fail
  (`aot-evals agreement label queue|import`), every labelled run is re-graded from its raw record
  with the suite as it is now (`aot-evals agreement`), and the catch rate and clean pass rate are
  reported, dev and holdout (M29). Every dev disagreement gets a cause in `labels/triage.yaml`.
  The gate needs 60 runs with 15 of each kind, current measurements, both rates at or above 85%
  on dev, and every dev disagreement triaged. `aot-evals agreement regrade --run R` re-grades a
  whole run offline; `--reproduces` finds code checks that read something besides the record.
- **G14**: until C19 is met the report refuses the word "validated" and comparisons are marked
  provisional. `report.json` gains an `agreement` block.
- **The labelling standard and per-case requirements** (C6, C8). `labels/standard.md` (written by
  `init`) holds the rules a person applies when failing a run, with the categories each applies
  to. Every case carries `requirements`, each citing a rule and naming the checks that decide it;
  every rule that applies to a case is cited or excused. `status` prints per rule how many cases
  it applies to, cite it, and check it. Existing suites need a standard and requirements before
  C6 and C8 are met again.
- **Screens on the reference answer** (C7): other correct wordings (`output_variants`) must pass,
  the reference answer with nothing changed must fail, and an answer with every number wrong is
  reported when it passes.
- The `build` skill now asks for expected values derived from the start state, and a grounding
  check for every fact a prose answer states.
- **A non-answer fails** (C7): "Done!", or the request echoed back, with nothing changed must fail
  every case that has a reference answer, including cases where nothing should change ("that
  isn't on record"), which the do-nothing screen skips. `aot-evals screen --judges` lets calibrated
  judges count in this screen and the liar's.
- `aot-evals replay run|seed|observe RECORDS`: recorded runs stand in for the agent and its
  hooks, so a suite can be built, screened, run and checked against people offline, from traces
  (references/agent-contract.md, "Recorded runs"). Under replay, C1 is not applicable rather than
  met, replays of the same records are one agent version, and plane B is not measured. A suite's
  own replay script can declare `invoke.recorded: DIR`.

## 0.3.0 — 2026-10-26

- A local catalog of public agent benchmarks (`references/benchmarks.yaml`, over 100 entries with
  workload, task types, environment, grading, data, license and what to borrow) and
  `aot-evals benchmarks --workload TAG --task "..."`, which Phase 1 uses to list the benchmarks
  that fit an agent without searching the web. Phase 2 may search for newer ones.
- The discovery report's golden test cases now end in a grid: the agent's task types (rows,
  from its traffic) against the situations public benchmarks test (columns, from
  `references/situations.yaml`: unanswerable, ambiguous, forbidden, confidential, multi-turn,
  tool error, …), each cell the cases that exist against the target. `aot-evals benchmarks`
  prints the situations its matches test; catalog entries may list theirs under `situations`.
  Task types are what the person asked for, never a situation; Phase 2 carries each situation
  as a taxonomy entry so coverage reports the empty cells. Grid targets start flat per task
  type and are weighted by worth and share, with the weighting stated in the report.
- `aot-evals demo` now starts by rendering the toy calendar agent's Phase 1 report
  (`examples/calendar/evals/discovery.md`, rewritten in the current format with a grid) as
  `discovery.html`, so the demo shows both phases.

## 0.2.0 — 2026-10-16

- `aot-evals run --resume RUN_ID` carries on a run that stopped or died partway, in place, instead
  of starting over. Every (case, trial) with a final attempt is skipped, and the rest are appended
  to the same `outcomes.jsonl`. Resume is refused if the run is finished, or if the agent commit,
  the suite's commit, the env, the judges or the case set changed since the run started. A
  truncated last line is dropped, and a case interrupted mid-retry is run again. The manifest
  gets a `resumed` list (`at`, `pairs_done_before`) and a `judges_enabled` field. Counts, cost and
  observed models are now always recomputed from `outcomes.jsonl`. A stopped run prints the
  resume command.
- In `outcomes.jsonl`, an attempt's check lines now come before its attempt line, so a crash
  between them can't leave a final attempt without its checks.

## 0.1.1 — 2026-10-08

- The discovery report's pillars read "Safe testing environment" and "Golden test cases"
  (were "Safe testing env" and "Golden use cases"). Reports written with 0.1.0 still render
  as before.

## 0.1.0 — 2026-10-08

The first public release.

- Skills that take a team from no evals to a measured, comparable suite for their own agent:
  `/aot-evals:start` is the one command to remember: it runs `discover` (Phase 1) when there
  is no discovery report yet, and otherwise `status`, which routes to `scope`, `build`,
  `calibrate`, `run` and `report` (Phase 2, commands C0–C18). Only `start`, `discover` and `status`
  appear in the `/` menu; Claude loads the step skills as it reaches them.
- A discovery page that opens with an overview: what AOT Evals does, a bottom line, three key
  numbers, and the four things good evals rest on (business context, agent architecture, safe
  testing env, golden use cases), each with what discovery found and what's still open. The
  details follow, grouped by those four, then the next steps.
- The `aot-evals` CLI: gates, import, allocation, screening, runs with per-trial outcomes and
  operational counters, judge labelling (with a browser labelling page), calibration and
  reliability, paired comparisons, coverage, redundancy, `report.json`, checkpoints and an
  activity log. `aot-evals demo` sets up a toy agent with a finished suite; `aot-evals doctor`
  checks the environment.
- Judge backends: System One (`POST /v1/systemone`), Anthropic, and any command of your own.
- Several agents per repository (`evals/agents/<agent>/`), isolated runs that keep the agent
  away from the cases, run pacing, and a stop when the agent's provider goes silent.
- Pseudonymous milestone telemetry (Phase 1 started, discovery written, checkpoints, report built,
  demo run), off whenever Claude Code's own telemetry is off, on cloud providers and in CI.
  `aot-evals telemetry status|show|off|on`. What's sent and the opt-outs: SECURITY.md#telemetry.
- The method reference, `docs/method.md`.
