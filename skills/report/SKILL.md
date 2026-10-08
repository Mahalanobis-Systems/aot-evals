---
name: report
description: Command C18 of aot-evals - regenerate <suite>/report/report.json (fixed schema) and write one self-contained local HTML diagnostic from it, shaped around the user's question (why did the candidate regress? is this suite any good? what does it cost?). Use when someone asks for an eval report, dashboard, scorecard or diagnostic for an agent that has an evals/ directory.
user-invocable: false
---

# report: the report

Paths below start at `<suite>/`, this agent's suite: `evals/agents/<agent>/`, beside its discovery report
(a one-agent repository may keep it in `evals/` itself). When the repository has several agents, pass
`--agent <agent>` to every `aot-evals` command.

## 1. Regenerate the data

```bash
aot-evals report                       # latest baseline
aot-evals report --run A --run B       # specific runs
```

This writes `<suite>/report/report.json` (schema `aot-evals/report@1`, docs/method.md §8). Read it in full
before writing anything. It is the only data source: never re-derive a number differently from
it, and never fill a `null` in. When `refused` is set, the report leads with that.

## 2. Ask what the report is for

The schema is fixed and the HTML is not. Each file is written for one question, and the question
decides what leads:

| Question | Leads with |
|---|---|
| "How is the agent doing?" | P1 gates, P3 + P4 side by side, P9 flakiness |
| "Is this suite any good?" | P1 gates, P5 coverage, P6 discrimination, P13 next actions |
| "Why did the candidate regress?" | P7 comparison, the losing cases in P12 |
| "What does it cost?" | P4 operational, budget breaches, cost per success |

If the question isn't clear, ask it in one line.

## 3. Write one self-contained HTML file → `<suite>/report/report-<YYYY-MM-DD>.html`

```bash
aot-evals report --html --title "<a title that states what this report answers>"
```

This writes the **branded shell**: Montserrat and Roboto embedded, the AOT logo top right, the
"Mahal Systems" wordmark bottom right, the brand style sheet, and report.json inlined as
`<script type="application/json" id="data">`.
- **Write the panels into `<main id="panels">`**, replacing the `PANELS` comment. Use inline JS
  that reads the `#data` script, or static HTML.
- **Leave the header and footer as generated.** Don't add other logos, icon sets, colors or
  fonts: the style sheet (`references/style.css`, already inlined) has every class you need.
  That includes `.ci`, `.bar.gains` / `.bar.losses`, `.marks`, `tr.fail`, `.greyed`, `.over`,
  `.empty-cell` and `colgroup.group-reliability`.
- **Colors.** Velocity Green appears once per region at most, for the thing that improved.
  Failures are Forest bold on a Pale Green band (`tr.fail`), never red.
- **Dates.** Write dates for readers as "Month Day, Year" (`October 2, 2026`).
- **Self-contained.** No network requests, no CDN, no build step. The file must open from the
  filesystem and be attachable to a PR or an email. The shell never overwrites a report whose
  panels are already written; it picks the next free name.
- **Don't publish it.** It's a local file; tell the user the path.

### Panels

Include the panels that serve the question, in the order the question needs. A panel with no
data shows one line saying so.

| id | Panel | From report.json |
|---|---|---|
| P0 | Conditions: agent and commits (flag dirty), every model id declared and observed, harness, k, N per set, regime, exports, dates, total cost | `agent`, `conditions`, `sets`, `runs` |
| P1 | Gates: every G1–G13, pass/fail/n.a., what each failure blocks. **Above the results** | `gates` |
| P2 | Validity: task × simulator × judge and the product (M25), plus the MDE per set (M7) | `validity`, `sets.*.mde_at_80_power` |
| P3 | Correctness by category: pass rate with CI error bars and `pass^k`, ordered by worth, variance band shaded, n, k and set on every row; where `pass^k` is null, show `pass_pow_k_reason` instead of a bare dash; excluded (unscreened) cases greyed beside it | `categories[].pass_rate`, `.pass_pow_k`, `.pass_pow_k_reason`, `.variance_band`, `.excluded` |
| P4 | Operational by category against budgets: cost per success, p50/p90, cache-hit, errors by outcome code with CI, retries, kills; breaches flagged. **Next to P3, never merged with it** | `categories[].operational` |
| P5 | Coverage: taxonomy entry × failure mode counts. Outline empty cells, mark `not_applicable` cells n/a, and show the source in the caption with the empty-cell count. Add the authoring queue. Show `MISSING` when G5 fails | `coverage` (`cells`, `empty_cells`, `authoring_queue`) |
| P6 | Discrimination: one stacked bar of always-pass / always-fail / discriminating, with counts, the fraction against its threshold, and the per-case index. Show the prune proposal with its before and after pairwise tests. With `redundancy: null`: "needs at least two candidates" | `redundancy` |
| P7 | Comparison: gains and losses as separate bars, each case linked to P12. Put the McNemar p, bootstrap CI, MDE and variance band in the caption; the verdict and its reasons; per-set rows (label error-finding as not a quality estimate); plane-B deltas and new budget breaches beside it. No net-only view. If `refused`, show the G7 problems instead | `comparison` |
| P8 | Judges: backend and model family next to the agent's, version, labels, TPR/TNR with CIs, κ, confusion matrix, threshold, ECE/Brier, cost per judgement, holdout rates; E5's backend comparison (`backends_compared`, `recommendation`). Self-consistency, cross-family agreement and three-level agreement go in a separate column group labelled "reliability (not validity)". Uncalibrated judges are greyed, with `status_reasons` shown | `checks[].judge`, `conditions.judge_backends`, `conditions.judge_cost_usd` |
| P9 | Flakiness: per case, k marks in run order (pass, fail, operational failure) | `cases[].trials` |
| P10 | Drift (not yet automated) | — |
| P11 | Online (not yet automated) | `online` |
| P12 | Case detail: inputs, start and expected state, actual state diff, each check's verdict and detail (for judges: score, reasoning, and whether it `counted`), plane-B counters, trace ref, provenance, screen status | `cases[]` |
| P13 | Next actions, each with the command that clears it | `next_actions` |

### Rules (docs/method.md §9)

1. **Every number shows n, k and an interval**, or says why there is none.
2. **"Quality"** labels only `sets.quality_estimate.estimate`, with its weights published. Label
   error-finding numbers "error-finding set — not a quality estimate".
3. **Never combine correctness and operational numbers.** Show an operational regression even
   when correctness hasn't changed.
4. **Anything below its gate is greyed and kept out of the headline, but never hidden.**
5. **Reliability and validity never share a column group.**
6. **The headline is the per-category table**, not one aggregate pass rate.
7. **Every claim in prose links (`#p3`, …) to the panel it comes from.**

Visual style (the Mahal Systems brand: `${CLAUDE_PLUGIN_ROOT}/brand/README.md`):
- Enterprise Forest for structure, Velocity Green sparingly, Charcoal on Cloud White, a neutral
  grey ramp, and no other colors;
- tabular numerals, right-aligned, decimals aligned;
- small dense tables rather than large charts;
- error bars wherever an interval exists;
- no gradients, shadows, emoji or icon sets, and no logos other than the shell's;
- prose in a single column of about 70 characters; matrices full width;
- a print stylesheet.

## 4. Before handing it over

Open the file in a browser if one is available. Check that every panel renders, nothing makes a
network request, and every greyed item says which gate greyed it.

The report is this skill's checkpoint. Log it, so it shows on the activity page with the "waiting
for you" banner, and stop:

```bash
aot-evals log "Report ready: <suite>/report/report-<date>.html" --kind question --gate C18
```

Give the user the path, the headline in two sentences, and the first item from P13. Log your
steps as you write the panels, as in `status` ("Work in checkpoints").
