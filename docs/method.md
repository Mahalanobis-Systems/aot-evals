# The aot-evals method

This is the reference for what aot-evals does and why: the principles, the measurement frame,
the files it keeps in your repository, the commands C0–C18 and their exit gates, the
measurements (M), experiments (E), report panels (P) and refusal gates (G) that the skills and
the CLI name. The skills read the section they need; you can too.

## Contents

1. [Principles](#1-principles)
2. [Measurement frame](#2-measurement-frame)
3. [Repository contract](#3-repository-contract)
4. [Commands](#4-commands)
5. [Judges](#5-judges)
6. [Measurements](#6-measurements)
7. [Experiments](#7-experiments)
8. [report.json](#8-reportjson)
9. [The HTML report, checkpoints and the activity log](#9-the-html-report-checkpoints-and-the-activity-log)
10. [Gates](#10-gates)

**Who it is for.** The method is designed for production, user-facing agents on any stack: their
work is specific to the product, so no public benchmark measures it; their volume makes a point of
correctness, cost or latency worth measuring; and their output reaches users without an expert
checking it first. Any agent that can be run from a command can use it. The agent is invoked as a
command, so framework, language and model provider do not matter.

**What it is not.** Not trace collection (it reads exports of what your observability already
records), not a model gateway, not a hosted dashboard and not a leaderboard. There is no service
and no account. Everything it writes is text, diffable and safe to commit; raw traces and PII
never enter git. Every reported number carries `n`, `k` and an interval, or states why it cannot
have one. When a number cannot be defended, aot-evals refuses to print it and names the gate.

---

## 1. Principles

1. **Cases come from the agent's real traffic and real failures**, not from generic benchmarks.
   Public benchmarks are a source of grading designs, not of cases.
2. **Understand the agent before measuring it**: inventory, infrastructure, volume and usage first.
3. **Grade outcomes, with code first.** Check what changed in the world. Use a judge only where
   code cannot decide, and only after calibrating it.
4. **Cheap sources first, raw transcripts second.**
5. **Keep sensitive data out of version control.** Raw traces stay local and ignored; only
   reviewed, scrubbed cases are committed.
6. **Record every claim as confirmed or inferred, with its source.** When config and runtime
   disagree, trust the traces.
7. **Three planes, reported separately, never combined into one score** (§2.1): correctness,
   operational cost, and trust in the instruments.
8. **Two case sets and two regimes** (§2.2, §2.3). A set built to find errors and a set built to
   estimate quality are different sets. A test that can be re-run and a signal that can only be
   observed in production are different instruments. Every reported number states which set and
   regime it came from.
9. **Measure the suite itself** (§2.4): coverage against a list you did not derive from your own
   cases, and redundancy by whether cases distinguish versions of the agent.

The step-by-step process behind principles 1–6 is in
[references/process/](../references/process/README.md).

---

## 2. Measurement frame

### 2.1 Three planes

| Plane | Question | Instrument | Reported as |
|---|---|---|---|
| **A. Correctness** | Did the agent do the right thing? | code state-diff checks; a calibrated binary judge where code cannot decide | pass rate per category with CI; `pass^k` |
| **B. Operational** | What did it cost? | counters, not judgements: $ per run and per successful task, p50/p90 latency, input/output/cached tokens, cache-hit rate, tool calls, retries, errors and timeouts by outcome code, runs killed at a limit | values against per-category budgets, across runs |
| **C. Instrument trust** | Can plane A be believed? | judge TPR/TNR against human labels; judge self-consistency and cross-family agreement; case-validity screens | its own report panel, with reliability and validity in separate column groups |

Plane B is deterministic. It is recorded on every trial, pass or fail, and needs no ground truth,
judge or labels, so it is the first thing to instrument. Operational failures (timeouts, rate
limits, crashes) are plane-B data: never scored as correctness failures and never dropped.

- **An operational regression is a finding even when correctness is unchanged.** Cost per
  successful task doubling at the same pass rate is a failed comparison (verdict `worse`). A common
  cause is a prompt-prefix edit that invalidates the prompt cache.
- **A correctness gain that comes with a cost or latency regression beyond budget is a trade**,
  reported with both numbers, not as an improvement (G11).

### 2.2 Two regimes: offline and online

| | Offline (benchmark) | Online (operational) |
|---|---|---|
| Subject | frozen cases, in a sandbox or by replay | live traffic |
| Re-runnable | yes: same inputs, k times | no |
| Ground truth | the case's expected end state | none; needs a referent such as human labels or user behaviour |
| Grading | state diff, then a narrow judge | a judge on a sample; behavioural signals; fingerprints on a control chart |
| Answers | Did this change make the agent better? | Is it getting worse, and where? |
| Cannot answer | whether the frozen set still resembles production | which of two candidates is better |

Neither substitutes for the other. Offline cases may come from your observability stack, but are
always imported as a local export (C0); the suite runs with that stack switched off. aot-evals
automates the offline regime today; the online regime (C16, C17) is guidance only.

### 2.3 Two offline case sets

- The **error-finding set** is enriched with hard, ambiguous and rare-but-costly cases. It finds
  bugs and verifies fixes. Its pass rate says nothing about performance on real traffic.
- The **quality-estimate set** is sampled in proportion to each category's observed share of
  traffic. Its weighted pass rate is the only number the report may call "quality".

The two are disjoint, sized by different arithmetic (C5), and every reported number is labelled
with its set.

### 2.4 Coverage and redundancy

**Coverage.** Coverage measured against categories derived from the suite's own cases is always
100%, so it is measured against a list written for some other purpose: the product spec, the API
or tool surface, a help-centre topic list, a job-task taxonomy, a regulator's list of duties. The
report counts cases per entry on that list, crossed with failure modes, and lists the empty cells
first. A taxonomy entry may declare failure modes `not_applicable`, with a reason: those cells
leave the empty count but stay visible.

**Redundancy.** A case that every version of the agent passes, or every version fails, cannot tell
you which version is better. Over two or more versions, each case is always-pass, always-fail or
discriminating; the report gives the discriminating fraction. Always-pass cases still work as
regression guards; they just contribute nothing to a comparison. The hardest cases change after a
prompt rewrite, so the discriminating set is re-derived after every prompt change.

---

## 3. Repository contract

Each agent's suite lives in `evals/agents/<agent>/`, beside its discovery report. A repository
with one agent may keep the suite in `evals/` itself. Pass `--agent NAME` to the CLI when there
are several.

```
evals/agents/<agent>/
  discovery.md               # Phase 1: the discovery report
  agent.yaml                 # identity, triggers, tools, model per call site, stable window,
                             #   and how to invoke it (references/agent-contract.md)
  taxonomy.yaml              # the coverage list (§2.4): entries, the source document, the date read
  categories.yaml            # trace categories: definition, worth, simple flag, cost matrix, observed share
  failure_modes.yaml         # per failure mode: >=1 check, >=1 category, a cost-matrix cell
  budgets.yaml               # plane B: cost / latency / token / error-rate budgets per category
  allocation.yaml            # C5's plan: sizes, and each unfilled cell scheduled or out of scope
  cases/<category>/<case-id>.json   # frozen inputs, start state, trigger, expected end state, set, provenance
  checks/
    code/<check-id>.py              # binary state diff: check(start, end, case) -> (bool, detail)
    judge/<check-id>.md             # one failure mode, binary, typed; backend-agnostic (§5)
    judge/<check-id>.labels.jsonl   # human labels, each with the exact judge input labelled
    judge/<check-id>.judgements.jsonl   # cached judge calls, so re-measuring costs nothing
    judge/<check-id>.calibration.json   # C10's measurements
  env/                       # fakes, cassettes, seeds, frozen-clock config
  data/                      # ignored: exports, labelling pages; only export.manifest.json is committed
  runs/<run-id>/manifest.json       # the condition record
  runs/<run-id>/outcomes.jsonl      # one line per attempt and per check verdict
  report/report.json                # §8
  report/report-<date>.html         # §9
  report/checkpoints/               # §9: one page per owner checkpoint
  journal/                          # §9: the activity log; ignores itself
  .gitignore
```

Rules:

- **Paths start at the repository root**, the folder that holds `evals/`: `invoke.cwd` in
  `agent.yaml` and a command judge's `cwd`.
- **`outcomes.jsonl` is never aggregated at write time.** It has two kinds of line: `kind:
  attempt`, one per (case, trial, attempt), with the outcome code and plane-B counters; and `kind:
  check`, one per (case, check, trial, attempt), with the verdict. Every attempt is written,
  including retries and operational failures. `pass^k`, flakiness, discrimination and paired tests
  are computed from these lines.
- **`manifest.json` is the condition record**: the agent's commit (computed with `evals/`
  excluded, so committing a run or a label is never an agent change) and this suite's commit, every
  model id, harness, fakes, k, total cost, and whether the run was isolated or saw the eval files
  (§4, C12). Two runs whose manifests differ on any field other than the declared independent
  variable are not compared (G7).
- **Every case has a `set`**: `error_finding` or `quality_estimate`. There is no default.
- **`taxonomy.yaml` names the document it came from**, and is committed before the first case. A
  model may draft it (C2), but only from a source outside `cases/`.
- **Unknown values are `null`, never `0`.**

---

## 4. Commands

Each command has an exit gate. The CLI will not run a command whose predecessor's gate is unmet;
it names the gate and the command that clears it (`--force` runs past it, and the run manifest
records that it did). `aot-evals status` shows every gate and the next unmet one.

| # | Command | Does | Exit gate |
|---|---|---|---|
| C0 | `import` | Import your data as an export (trace dump, dataset download, CSV/JSONL from your observability stack) into `data/`, with an `export.manifest.json` entry: source, query, window, row count, date. | Every downstream number traces to an export manifest entry; no command calls a live vendor API. |
| C1 | `inventory` | Write `agent.yaml`: surface, triggers, instructions, tools (credential names only), harness, the model actually used per call site, version history, the stable window, and the invocation command. | Stable window stated with evidence; model per call site observable; `invoke.cwd` exists; the agent runs once end to end from its command. |
| C2 | `taxonomy` | Build the coverage list from a source outside the suite: the product spec, API/tool surface, help-centre topics or job description. The owner edits it; the source document is recorded. | `taxonomy.yaml` names a source outside `cases/` and a date, and its commit precedes the first case. |
| C3 | `categorize` | Sort traces into categories, one per trace. Give each a worth and a per-failure-kind cost matrix. Count observed share. | Every category has a definition, an example, worth, a simple flag, a cost row and a measured share. "Other" is under 10%. |
| C4 | `decompose` | Within each category: feature → scenario → failure mode. Mark each failure mode code-checkable, judge-needed or monitor-only, and set plane-B budgets. | Every failure mode names its category, check type and cost cell; `budgets.yaml` covers every category. |
| C5 | `allocate` | Size both case sets and print the arithmetic. Error-finding: ≥10 per category, 3 for simple ones. Quality-estimate: proportional to observed share, sized by the interval the owner needs (M14). | Both budgets printed with target intervals and the minimum detectable effect (M7); every cell filled, scheduled, or declared out of scope with a reason. |
| C6 | `author` | Write cases: frozen inputs, start state, trigger, scripted follow-ups, expected end state. Prefer self-verifying pairs where state allows. Scrub before writing. | Every case has a set, a category, failure modes, provenance, and no secrets. |
| C7 | `screen` | Per case: a human read; the checks must pass on start → expected end (reference) and fail on start → start (do nothing); a third pass, do-nothing plus a success claim, catches checks that trust the agent's report (G10). Drop cases that fail, and record the drop. | Screens recorded per case; drop rate reported. |
| C8 | `checks` | Implement plane-A checks: code state diffs first, graded against the goal rather than one path; binary judges only where code cannot decide; side-effect checks on every agent. A check never uses the agent's own report of success. | Every failure mode has at least one binary check; side-effect checks present. |
| C9 | `label` | Collect human labels per judge, stratified across categories: one item per case first, then other trials where the answers differ. Target 100–200; below 60 the interval is too wide to act on. | Label count and stratification printed per judge. |
| C10 | `calibrate` | Measure each judge against its labels: TPR and TNR separately (never raw agreement), κ, confusion matrix, cost per judgement. Choose a probabilistic backend's threshold on the labels. Version the criteria. | Every judge has TPR/TNR on ≥60 labels at or above its floors, a named backend and model family, and a version. Uncalibrated judges may run but never count toward headline numbers. |
| C11 | `reliability` | Run *m* fresh sessions per item on two backends from different model families; report agreement at three levels (all / majority / none) next to C10's TPR/TNR. | Self-consistency and cross-family agreement reported next to TPR/TNR, never in place of it. |
| C12 | `baseline` | Run the suite k = 3–5 times on an unchanged, committed build. Write per-trial outcomes and plane-B counters. Compute the variance band. | Run complete and finished, manifest complete, no eval-file exposure, variance band per category, plane B recorded against `budgets.yaml`. |
| C13 | `compare` | Run a candidate on the same cases with one declared independent variable. Report gains, losses and a paired test, never a net delta alone, with plane-B deltas alongside. | Paired test present; gains and losses listed; manifests differ only on the declared variable. |
| C14 | `coverage` | Count cases per (taxonomy entry × failure mode), zeros included, with the source document named. | Coverage reported against an external list, or refused (G5). |
| C15 | `redundancy` | Over ≥2 agent versions, classify each case; report the discriminating fraction and a per-case index; propose prunes and cells to extend. | Discriminating fraction published; below the threshold (default 0.3), a prune/extend proposal. |
| C16 | `drift` | Re-run the frozen set on a schedule and on every prompt, skill, tool, model or harness change, against the baseline's band. | Guidance only; not yet automated. |
| C17 | `online` | Set up the online regime: shadow → canary → online judging; behavioural signals; fingerprints. | Guidance only; not yet automated. |
| C18 | `report` | Write `report.json` (§8), then the HTML report (§9). | Every gate's status is in the report. |

C3–C18 repeat as a loop. A prompt rewrite re-derives the hard-case set, and a shift in category
mix re-opens C3 and C5.

**How runs work.**

- The agent is a command: the case goes in as JSON on stdin and one JSON result comes back on
  stdout, with optional `setup`, `seed`, `observe` and `reset` hooks
  ([references/agent-contract.md](../references/agent-contract.md)). Checks grade what `observe`
  returns, never what the agent says it did.
- Outcome codes (`ok`, `timeout`, `rate_limited`, `provider_error`, `no_output`, `unparseable`,
  `model_disabled`, `auth_error`, `budget_exceeded`, `cli_missing`) are recorded per attempt. Only
  `ok` is scored; retryable codes are retried up to `max_attempts`.
- A run stops after `--stop-after` (default 5) cases in a row end in an operational failure; a
  stopped run is never finished. `--pause-every N --pause-seconds S` paces a rate-limited runtime.
- **The agent must not see the cases.** `invoke.isolate: true` runs the agent and its hooks from a
  per-run copy of the repository without `evals/` (this suite's `env/` is kept). Every run, isolated
  or not, records eval files changed during the run and agent output that names a case file; either
  keeps the run from being a baseline.

**How comparisons work (C13).** Each side's verdict on a case is its majority over k trials. Gains
and losses are majority flips, tested with McNemar's exact test; a bootstrap CI covers the mean
per-case delta. A change is `better` or `worse` only when it is significant and outside the
baseline's variance band; otherwise `indistinguishable`. The declared variable is a kind
(`model`, `prompt`, `config`, `tools`, `harness`, ...) that maps to the manifest fields allowed to
differ. Runs of one build split across several runs (for example category by category, to pace a
rate-limited runtime) count as one side: their case sets, checks and judges are merged per item.

**How redundancy works (C15).** Versions are runs grouped by the fields that define the build, so
repeats of one build never look like two versions. The prune proposal never prunes
quality-estimate cases, sends always-fail cases to review, keeps regression guards for coverage
cells and categories, and re-runs the pairwise tests to show the detectable effect is unchanged.

---

## 5. Judges

A judge is a check for one failure mode that asks one binary, typed question: a `noul` (a
true/false claim, with `detects` saying whether yes means the failure is present or the
requirement is met), a `choice` over declared options, or a `score` on a rubric level. The judge
layer is backend-agnostic ([references/judge-backends.md](../references/judge-backends.md)):

| Backend | Use |
|---|---|
| Code | anything decidable from state; always first |
| System One (`systemone`), such as Jev | typed questions answered with a probability; cheap and fast enough to judge every attempt |
| Generative (`anthropic`), a different model family from the agent | reference-guided grading, pairwise comparison, anything needing a written critique |
| `command` | any judge you run yourself: another provider, a gateway, a rules engine |

Rules:

1. **Every backend is calibrated in C10.** A typed answer can still be wrong.
2. **A backend's confidence is not trusted until measured on your labels.** A probabilistic
   backend's threshold is chosen by maximising TPR + TNR on the dev labels; the reported rates come
   from 5-fold out-of-fold predictions, and a hash-assigned 20% holdout is reported separately. The
   floors are `min_tpr` / `min_tnr` (default 0.75).
3. **A judge counts toward a headline only when it is calibrated on its current version and
   backend.** Stored scores are re-thresholded with the calibrated threshold, so calibrating after a
   run changes the report without re-running anything.
4. **Labels carry the judge's input.** Each label includes the exact input that was labelled
   (after a secret scan), so calibration can be re-run on any backend without the raw run data.
5. **Judgements are cached** per backend (the question, the inputs and that backend's own config),
   so adding or changing a backend does not re-pay for the others.
6. **No silent fallback.** A refusal or an error is an instrument error, never a verdict from
   another model. A rate-limit error stops that backend's calls at once.
7. **Different family for pairwise grading** (G4).

E5 compares backends on the same labels, by TPR/TNR and cost per judgement, and is how each
judge's backend is chosen.

---

## 6. Measurements

`N` = cases, `k` = trials per case, `L` = human labels. Plane refers to §2.1. Measurements marked †
are guidance for the online regime and are not yet computed by the CLI.

| id | Plane | Measurement | Definition | Use |
|---|---|---|---|---|
| M1 | A | Per-check outcome | binary, per (case, check, trial) | the unit every other plane-A number is computed from |
| M2 | A | Pass rate | mean over trials and cases, per category, with a cluster-robust CI over cases (Wilson when that collapses) | never reported suite-wide without the per-category table |
| M3 | A | `pass^k` | fraction of cases passing all their trials | reliability across repeats; 75% per trial ≈ 42% at k = 3 |
| M4 | A | Flakiness | per case: 0 < passes < k | reported as a finding; sets the k budget |
| M5 | A | Variance band | same build, ≥3 repeats, spread per category | no change inside the band is called drift or improvement |
| M6 | A | Paired difference | per-case paired delta, McNemar and bootstrap CI, gains and losses listed separately | a net delta alone is not reported |
| M7 | A | Minimum detectable effect | from N, k and per-case variance at 80% power | printed before an experiment runs |
| M8 | C | Judge TPR / TNR | against that judge's labels, separately, with CIs | raw agreement is not reported: an always-pass judge agrees 95% of the time at a 95% base rate |
| M9 | C | Judge reliability | self-consistency across *m* sessions; agreement across two families; three-level agreement | reported next to M8, never in place of it |
| M10 | C | Label status | L per judge and the resulting interval width | under 60: uncalibrated; 100–200: usable |
| M11 | A | Check trigger rate | how often each check fires over the report's runs (the baseline by default), and how often it is the only failing check | a check that never fires across several versions, or always fires with another, is a prune candidate. On a baseline that passes everything, every rate is 0 and says nothing about the check |
| M12 | A | Coverage per cell | cases per (taxonomy entry × failure mode), zeros included, source named | G5 |
| M13 | A | Discriminating fraction | share of cases not always-pass or always-fail across ≥2 versions | §2.4 |
| M14 | A | Quality estimate | CI on the share-weighted pass rate of the quality-estimate set, weights published | the only number reported as "quality" |
| M15 | A | Error-finding yield | errors found per case reviewed, vs random selection | judges a case-selection method |
| M16 | A | Disagreement yield | size of the set where judges or models disagree, and its share of all errors | judges a case-selection method |
| M17 † | A | Hard-set churn | overlap of the hardest-*x*% set before and after a prompt change | re-derive the hard set when it churns |
| M18 | B | Cost per successful task | run cost ÷ successes | cost per run is the wrong denominator |
| M19 | B | Latency | p50/p90; runs killed at a limit | budgeted per category |
| M20 | B | Tokens and cache | input, output and cached tokens; cache-hit rate | a cost jump at an unchanged pass rate usually means a prompt-prefix edit broke the cache. Compare dollars, not tokens |
| M21 | B | Errors and retries | count and rate (Wilson interval) per outcome code, over every attempt including retries | needs no judge; the cheapest regression signal |
| M22 | C | Case validity | reference pass, do-nothing fail, human read; drop rate at C7 | unscreened cases do not count toward gated numbers (G8) |
| M23 † | C | Fake fidelity | contract test of each fake against the real API | a drifted fake looks the same as a regression |
| M24 | C | Simulated-user sensitivity | the same suite under ≥2 user simulators, reported per simulator | G9 |
| M25 | C | Compounded validity | product of stated stage validities (task × simulator × judge) | printed in the report header; 70% × 70% × 70% ≈ 34% |
| M26 | A | Leakage screen | overlap of case provenance with likely training or benchmark sources | required for cases built from a public source |
| M27 † | B | Online fingerprints | per agent: unanswered requests, time to first response, tokens and cost per turn, tool calls per turn, category mix, model id per call | drift in the part of the system that cannot be sandboxed |
| M28 † | A | Behavioural signals | post-output edits, acceptance, follow-up corrections, re-asks | free labels for C9 |

---

## 7. Experiments

No comparison runs before E1. Experiments marked † are guidance only.

| id | Experiment | Design | Produces |
|---|---|---|---|
| E1 | Noise floor | same build, same cases, k ≥ 3, ideally on two different days | M5, M4, the k budget |
| E2 | Candidate comparison | paired on identical cases; one declared independent variable | M6 with gains and losses, M3, plane B |
| E3 | Judge calibration | stratified labels per judge; iterate; hold out a slice | M8, M10, judge versions |
| E4 | Judge reliability | *m* sessions × two families, plus a human-labelled subsample | M9 next to M8 |
| E5 | Judge backend comparison | same judge and labels: System One vs generative vs your own | cost per judgement, TPR/TNR; the backend for each judge |
| E6 | Downgrade / routing probe | a cheaper model or routing policy against a near-100%-pass regression suite, with the prompt re-optimised first | M6, M18–M20 |
| E7 † | Selector comparison | random vs uncertainty vs disagreement selection at a fixed label budget | M15, M16 |
| E8 | Coverage audit | project the suite onto the taxonomy; triage every empty cell | M12, an ordered authoring queue |
| E9 | Redundancy / prune | classify every case over ≥2 versions; propose prunes | M13, M11, a smaller suite with the same detectable effect |
| E10 | Weight sensitivity | for composite scores only: vary the weights and check whether the ranking holds | whether the composite is stable |
| E11 † | Shadow / canary | the candidate states what it would do; compare with what happened; then a fraction of live traffic | the gate before write access, for agents with no sandbox |
| E12 † | Fake contract test | replay each fake against the live API on a schedule; diff | M23 |
| E13 † | Drift watch | the frozen set on a schedule, plus M27 on a control chart with M5's limits | the standing check for provider-side and self-inflicted changes |
| E14 | Operational sweep | plane B only, no labels or judges: budgets vs actuals per category | M18–M21; can run in week one, from an export |

---

## 8. report.json

Written by C18 (`aot-evals report`) to `report/report.json` and read by the HTML report. The
schema is versioned (`aot-evals/report@1`); keys may be added within a version, never removed or
renamed.

```jsonc
{
  "schema": "aot-evals/report@1",
  "generated": "2026-01-01T00:00:00Z",
  "agent":   { "id": "...", "stable_window_since": "...", "model_ids": {} },
  "conditions": { "agent_commit": "...", "evals_commit": "...", "harness": "...", "k": 5,
                  "judge_backends": [ { "check": "...", "backend": "...", "model": "...",
                                        "family": "...", "version": "..." } ],
                  "simulator": null, "cost_usd": 0.0,
                  "data_exports": [ { "source": "...", "window": "...", "rows": 0 } ] },
  "regime":  "offline",
  "taxonomy": { "name": "...", "source": "...|MISSING", "read_on": "...", "entries": [] },
  "sets":    { "error_finding": { "n": 0, "mde_at_80_power": 0.0 },
               "quality_estimate": { "n": 0, "weights_source": "...", "estimate": {} } },
  "categories": [ { "id": "...", "worth": "high", "simple": false,
                    "observed_share": 0.0, "n_cases": 0,
                    "pass_rate": { "point": 0.0, "ci": [0, 0], "n": 0, "n_cases": 0, "k": 5,
                                   "set": "...", "ci_method": "..." },
                    "pass_pow_k": 0.0, "pass_pow_k_reason": null, "flaky": 0, "variance_band": [0, 0],
                    "operational": { "cost_per_success": 0.0, "cost_per_run": 0.0,
                                     "latency_p50": 0, "latency_p90": 0,
                                     "tokens_input": 0, "tokens_output": 0, "cache_hit_rate": 0.0,
                                     "tool_calls": 0.0, "outcomes": { "ok": 0, "timeout": 0 },
                                     "retries": 0, "killed": 0,
                                     "budget": {}, "budget_status": "within|over" },
                    "excluded": null } ],
  "checks":  [ { "id": "...", "type": "code|judge", "failure_mode": "...",
                 "trigger_rate": 0.0, "sole_failure_rate": 0.0,
                 "judge": { "backend": "...", "model_family": "...", "agent_model_family": "...",
                            "tpr": 0.0, "tnr": 0.0, "labels": 0, "kappa": 0.0, "threshold": null,
                            "self_consistency": 0.0, "cross_family": 0.0,
                            "confidence_calibration": { "ece": null, "brier": null },
                            "cost_per_judgement": 0.0,
                            "status": "calibrated|uncalibrated", "status_reasons": [] } } ],
  "coverage": { "list": "external|MISSING", "cells": [ { "taxonomy_entry": "...", "failure_mode": "...", "n": 0 } ],
                "empty_cells": 0, "authoring_queue": [] },
  "redundancy": { "candidates": [], "always_pass": 0, "always_fail": 0, "discriminating": 0,
                  "discriminating_fraction": 0.0, "per_case": [], "proposal": {} },
  "comparison": { "baseline": "...", "candidate": "...", "paired": true, "refused": null,
                  "gains": [], "losses": [], "net": 0.0,
                  "test": { "name": "mcnemar_exact", "p": 0.0, "ci": [0, 0] },
                  "mde_at_80_power": 0.0, "per_set": {},
                  "operational_delta": { "cost_per_success": 0.0, "latency_p90": 0, "error_rate": 0.0 },
                  "verdict": "better|worse|indistinguishable|trade", "verdict_reasons": [] },
  "validity": { "stages": { "task": null, "simulator": null, "judge": null }, "compounded": null },
  "gates":   [ { "id": "G5", "status": "pass|fail|not_applicable", "detail": "...", "blocks": [] } ],
  "next_actions": [],
  "cases":   [ { "id": "...", "set": "...", "category": "...", "provenance": "...",
                 "screen": { "human_read": true, "reference_passes": true, "donothing_fails": true },
                 "trials": [ { "run": "...", "trial": 0, "attempt": 0, "outcome": "ok", "passed": false,
                               "checks": [ { "id": "...", "type": "code", "passed": false, "detail": "...",
                                             "counted": true } ],
                               "operational": { "cost_usd": 0.0, "latency_ms": 0,
                                                "tokens_input": 0, "tokens_output": 0,
                                                "tool_calls": 0, "retries": 0 },
                               "state_diff": "...", "trace_ref": "..." } ] } ]
}
```

Rules: unknown values are `null`, never `0`. A missing coverage list is the string `"MISSING"`,
not an omitted key. Nothing is pre-rounded. There is one category row per (category, set),
labelled by `pass_rate.set`. Per-trial outcomes and plane-B counters are kept so the renderer can
recompute anything. `trace_ref` is an id or a local path, never the trace.

---

## 9. The HTML report, checkpoints and the activity log

aot-evals ships the schema (§8), the panel list and the rules below, not a dashboard. On request,
Claude writes one self-contained local HTML file: data inlined as JSON, no network requests, no
CDN, no build step. It opens from the filesystem and can be attached to a pull request or an email.
Each file is written for a question: a report on "why did the candidate regress" leads with the
comparison and the losing cases; one on "is this suite any good" leads with gates, coverage and
discrimination. `aot-evals report --html` writes the branded shell, and Claude writes the panels
into it (the `report` skill).

| id | Panel | Shows |
|---|---|---|
| P0 | Conditions | agent and commits, every model id, harness, k, N per set, regime, data exports, date, total cost |
| P1 | Gates | every gate in §10, pass/fail, and what each failure blocks; above the results |
| P2 | Validity | task × simulator × judge and the compounded product (M25) |
| P3 | Correctness by category | pass rate with CI and `pass^k`, ordered by worth; variance band shaded; n, k and set on every row |
| P4 | Operational by category | plane B against `budgets.yaml`; over-budget cells flagged. Next to P3, never merged with it |
| P5 | Coverage | taxonomy entry × failure mode counts; empty cells outlined; source in the caption |
| P6 | Discrimination | always-pass / always-fail / discriminating, with counts and the discriminating fraction |
| P7 | Comparison | gains and losses as separate bars, each changed case linked; paired test and MDE in the caption; plane-B deltas beside it. No net-only view |
| P8 | Judges | per judge: backend and family vs the agent's, confusion matrix, TPR/TNR with CIs, labels, κ, threshold, cost; reliability in a separate column group. Uncalibrated judges greyed |
| P9 | Flakiness | per case, k marks in run order: pass, fail, operational failure |
| P10 † | Drift | the frozen set over time against M5's band |
| P11 † | Online | fingerprints on control charts, sampling rate, referent |
| P12 | Case detail | inputs, start state, expected end state, actual state diff, each check's verdict, plane-B counters, trace reference, provenance, screen status |
| P13 | Next actions | empty coverage cells, judges under 60 labels, categories under their k budget, prune candidates, over-budget categories; each with the command that clears it |

Rules:

1. Every number shows `n`, `k` and an interval, or says why no interval can be computed.
2. "Quality" labels only a quality-estimate-set number with published weights. Error-finding
   numbers are labelled "error-finding set — not a quality estimate".
3. Correctness and operational numbers are never combined, and an operational regression is shown
   even when correctness is unchanged.
4. Anything below its gate is shown greyed and not used as a headline; it is never hidden.
5. Reliability and validity never share a column group.
6. The headline is the per-category table, not a single aggregate pass rate.
7. Every claim in prose links to the panel it comes from.

**Checkpoints and the activity log.** The work is paced by pages, so the owner can follow it in a
browser and steer at every gate.

- **Activity log.** `journal/activity.jsonl` is append-only: every CLI command writes an entry
  (command, gate, exit code, duration, refusal message), and the skills add their steps, findings,
  decisions and questions with `aot-evals log`. Each append re-renders `activity.html`, which
  reloads itself and says when Claude is waiting. The journal ignores itself in git: it may quote
  unreviewed trace text, and the committed record of a decision is the file it changed.
- **Checkpoints.** `aot-evals checkpoint` writes a page for one gate: the C0–C18 roadmap in plain
  words, Claude's summary, the log since the last checkpoint, every design file rendered as tables,
  the owner's questions, what still blocks the gate, and the next step. It makes no model calls.
- **Pacing.** Every skill works until a gate clears or the work needs the owner, publishes a
  checkpoint, and stops until the person replies.
- **Telemetry.** `start`, `discovery-page`, `checkpoint`, `report` and `demo` each send one
  pseudonymous milestone event when they succeed (install id, event, gate id, version, OS, time;
  nothing about the agent or its data). It is off whenever Claude Code's own telemetry is off,
  on cloud providers and in CI; `aot-evals telemetry` shows, shows the payload of, and switches
  it. Details: [SECURITY.md](../SECURITY.md#telemetry).

Visual style follows [brand/README.md](../brand/README.md).

---

## 10. Gates

| id | Condition | Refuses |
|---|---|---|
| G1 | No condition record (model ids, commits, harness, k) | the whole report |
| G2 | `k = 1` | any claim of improvement, regression or drift |
| G3 | Judge uncalibrated (under 60 labels, below its floors), or reported as raw agreement | that judge's contribution to any headline; the judge is greyed |
| G4 | Generative judge from the same model family as the agent, for pairwise or preference grading | the pairwise result. A System One judge satisfies this |
| G5 | Coverage list with no external source, derived from the suite's own cases, or committed after them | the word "coverage"; prints `MISSING` and the reason |
| G6 | Headline pass rate from the error-finding set | the word "quality"; offers the weighted estimate instead |
| G7 | Comparison without a paired test, or with undeclared manifest differences | the comparison |
| G8 | Cases that have not passed the reference / do-nothing screen | their inclusion in any gated number |
| G9 | Simulated user present, results not reported per simulator | the aggregate score |
| G10 | A check that relies on the agent's own report of success | the check |
| G11 | A "better" verdict while plane B regressed beyond budget | the verdict; it becomes "trade", with both numbers |
| G12 | A number whose data does not trace to an export manifest entry or a committed case | that number |
| G13 | Retried attempts or operational failures missing from `outcomes.jsonl`, or scored as correctness | the run's plane-A and plane-B numbers |
