# Changelog

All notable changes to aot-evals. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and versions follow [Semantic Versioning](https://semver.org/) as described in
[CONTRIBUTING.md](CONTRIBUTING.md#versioning).

## Unreleased

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
