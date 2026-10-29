# Changelog

All notable changes to aot-evals. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and versions follow [Semantic Versioning](https://semver.org/) as described in
[CONTRIBUTING.md](CONTRIBUTING.md#versioning).

## Unreleased

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
