# Phase 1 — Understand the system

Steps 1–4. Goal: know what agents exist, where they run, how much they run, and what already measures them.

## 1. Inventory the agents

For each agent: where it lives (surface/channel), what triggers it (human,
schedule, other agents), its instructions (prompts, skills, stored scheduled
prompts), its tools and credentials, the harness that runs it, and the model
it actually uses.

- Sources: deployment config, prompt/skill files, the harness's source,
  runtime config stored in its database, traces.
- Watch for: agents with no prompt file (instructions stored only at
  runtime), per-agent model or provider overrides, side calls on different
  models (routing, "should I respond", titles, compaction), permission mode.
- **Version history and stable window.** For each agent, list every change
  that could alter its behavior: prompt or skill edits, stored scheduled-prompt
  edits, model or provider changes, harness upgrades (which hit every agent at
  once). The **stable window** is the time since the last significant change.
  Ask the owner: "How long has this agent been stable in production?" and
  check the answer against the history. Version control is a good first
  source; changes made at runtime (stored prompts, model overrides) need the
  runtime's own records.
- Output: an agent catalog, with a version history and stable window for each
  agent.

## 2. Map the infrastructure and trace pipeline

Where each agent runs (provider, region, services, sandbox vs host), the
hardware, the model providers it reaches, network egress controls. Then the
traces: how they are collected, which provider stores them, exact locations,
what they contain (prompts, completions, tool I/O, tokens, cost), retention,
and whether records in different sinks can be joined.

- Fix labeling gaps before collecting data for evals: every trace must be
  attributable to an agent.
- Output: an infrastructure doc with a data-flow diagram.

## 3. Measure volume per agent

Runs, model calls, tokens and cost per agent per day, split by trigger
(scheduled vs human). Make it a script that regenerates the report.

- Tells you how to sample (a 50-runs/day scheduled agent and a 2-runs/day
  human-driven agent need different case sets) and where cost concentrates.
- Output: a volume report plus the script.

## 4. Catalog existing evals and monitors

Tests, eval suites, judges, benchmarks, production monitors, user-feedback
capture — across the agent repos and neighboring projects. Note which are
live, which run automatically, which cover agent *quality* vs platform
correctness.

- Output: an evals inventory and the gap list (agents with no quality
  signal).
