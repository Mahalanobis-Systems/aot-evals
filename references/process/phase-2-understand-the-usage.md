# Phase 2 — Understand the usage

Steps 5–7. Goal: know what each agent is asked to do, where it goes wrong, and have its raw traces in hand.

## 5. Characterize usage from cheap sources

Per agent: trigger mix, a task taxonomy with real examples, what it produces
or changes, observed failure modes with counts, what success means, and what
could be checked by code vs judgement. Also cross-agent patterns: shared
failure modes, how people phrase requests, hand-offs between agents.

- Sources: scheduled-prompt exports, telemetry snapshots, incident ledgers,
  the agents' own commits to their records.
- Caveat to record: these sources are usually failure-biased (they keep
  failed runs, not successful ones).
- Output: a usage-patterns doc, plus the list of questions only raw
  transcripts can answer.

## 6. Survey similar public benchmarks

For each agent's job, the closest 2–4 public benchmarks: what they measure,
task format, grader type (state check, LLM judge, human), size, license.
Decide what is reusable (datasets, graders, task formats) vs idea-only.

- Verify every citation against a live paper or repo.
- Output: a benchmarks doc with "what to borrow".

## 7. Pull raw traces

Export runs, transcript entries, tool calls, per-step model usage and
scheduled-job definitions. The window must cover each agent's stable window
(step 1), and reach back far enough to give at least 10 runs in each category. Read-only
transaction; output to an ignored data directory.

- **Whoever has production access may have to run it.** Have the script ready
  before asking.
- **Read-only transactions refuse temporary objects** (views, tables): put
  filters inline.
- **Set the per-entry size limit generously** (100,000 characters, not
  20,000). Tool outputs such as search results are large, and a cut-off entry
  loses exactly the data reviewers need.
- **Write down the export's real structure** (formats, join keys, counts) and
  check every assumption the category drafts made against it before using them.
- Output: a local, ignored dataset, the re-runnable pull script, and a notes
  file on its structure.
