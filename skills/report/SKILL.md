---
name: report
description: The report for any phase of aot-evals - regenerate an eval's <eval>/report/report.json (schema aot-evals/report@2) and write one self-contained local HTML diagnostic from it, organized by the four parts (estimand, sampling design, measurement model, decision rule) and shaped around the user's question (should we ship this change? why did the candidate regress? is this eval any good? what does it cost?). Use when someone asks for an eval report, dashboard, scorecard or diagnostic for an agent that has an evals/ directory.
user-invocable: false
---

# report: the report

`aot-evals` is `"${CLAUDE_PLUGIN_ROOT}/bin/aot-evals"`. An agent's evals live in
`evals/agents/<agent>/<eval>/`; pass `--agent <agent>` with several agents and `--eval <id>` with
several evals. Each eval has its own report: a report about a component change covers the component
eval and the end-to-end eval it also requires.

## 1. Regenerate the data

```bash
aot-evals --eval <id> report                          # the baseline
aot-evals --eval <id> report --candidate <run-id>     # adds the comparison and decides on the candidate
aot-evals --eval <id> report --run A --run B          # specific runs
```

This writes `<eval>/report/report.json`, schema `aot-evals/report@2` (`${CLAUDE_PLUGIN_ROOT}/docs/method.md`
§10). Read it in full before writing anything. It is the only data source: never re-derive a number
differently from it, never round it before display, and never fill in a `null`; show the reason
beside it (`null_reason`, `reason`, `corrected_reason`, `floor.reason`). When `refused` is set, the
report leads with it: those runs measured a different quantity, and the next step is a baseline
under the current spec. Terms mean what `${CLAUDE_PLUGIN_ROOT}/docs/estimators.md#terms` says.

## 2. Ask what the report is for

The schema is fixed and the HTML is not. Each file answers one question, and the question decides
what leads:

| Question | Leads with |
|---|---|
| "Should we ship this change?" | Decision, Comparison, Operational, then Measurement |
| "How is the agent doing?" | Headline, Use cases, Operational |
| "Is this eval any good?" | Spec, Evidence gates, Measurement, Design, Next steps |
| "Why did the candidate regress?" | Comparison (the losses), Use cases, Cases |
| "What does it cost?" | Operational, the constraints in Decision |

If the question isn't clear, ask it in one line.

## 3. Write one self-contained HTML file → `<eval>/report/report-<YYYY-MM-DD>.html`

Write the file yourself (there is no HTML command); never overwrite an existing report, take the
next free name (`report-<date>-2.html`). The shell:

- `<style>`: the brand style sheet `${CLAUDE_PLUGIN_ROOT}/skills/report/references/style.css`,
  inlined in full, after `@font-face` rules for the fonts in `${CLAUDE_PLUGIN_ROOT}/brand/fonts/`
  (Montserrat 400/600/700, Roboto 400/700) as base64 `data:font/woff2` URLs. It has every class
  you need: `.ci`, `.bar.gains` / `.bar.losses`, `.marks`, `tr.fail`, `.greyed`, `.over`,
  `.empty-cell`, `colgroup.group-reliability`.
- A header with a title that states what the report answers, the eval id, its version and the
  report's date, and the AOT logo (`${CLAUDE_PLUGIN_ROOT}/brand/aot-logo-128.png`, base64) top right;
  a footer with the "Mahal Systems" wordmark bottom right and the schema.
- report.json inlined as `<script type="application/json" id="data">`, and the panels in
  `<main id="panels">`, as static HTML or inline JS that reads `#data`.

A short script does the embedding: read the CSS, base64 the fonts and logo, and `json.dumps` the
report into the page. Rules for the file:

- **Self-contained.** No network requests, no CDN, no build step. It must open from the filesystem
  and be attachable to a pull request or an email.
- **Brand** (`${CLAUDE_PLUGIN_ROOT}/brand/README.md`): Enterprise Forest for structure, Velocity
  Green at most once per region for the thing that improved, Charcoal on Cloud White, the neutral
  grey ramp, no other colors. Failures are Forest bold on a Pale Green band (`tr.fail`), never red.
  No gradients, shadows, emoji, icon sets or other logos. Tabular numerals, right-aligned; small
  dense tables rather than large charts; error bars wherever an interval exists; prose in one
  column of about 70 characters; a print stylesheet.
- **Dates** for readers as "Month Day, Year" (`November 14, 2026`).
- **Don't publish it.** It's a local file; tell the user the path.

### Panels

Include the panels that serve the question, in the order it needs. A panel with no data shows one
line saying so.

| id | Panel | From report.json |
|---|---|---|
| `conditions` | The runs, their dates, the agent and evals commits (flag dirty), each model id declared and observed, harness, k, the spec's version and its hash per part | `runs`, `eval`, `spec.sha`, `estimate.k`, `decision.subject` |
| `spec` | Complete, or each missing and invalid field with what it blocks; the defaults filled. **Above the numbers** when anything is missing | `spec` |
| `headline` | θ̂ with its interval and `ci_method`, the quantity, the weights per use case and where they came from, n cases, n clusters, n effective, k; corrected and uncorrected side by side when a correction applies. When `theta` is null, the `null_reason` in its place | `estimate` |
| `use-cases` | One row per use case and pool: share, cost, weight, μ̂ with its interval (corrected beside it), n, k, `pass_pow_k` (or its reason), flaky cases, the zero-failure bound when nothing failed, and the variance band shaded. Bug-finding rows apart, labeled "bug-finding set: picked to find failures, not a rate of traffic". Excluded (unscreened or uncommitted) cases greyed with the reason | `use_cases[]` |
| `design` | The quality set: drawn of n, frame, seed, oversampling and π range per use case, skips with reasons, refused cases; the bug-finding set and its coverage list; clusters: count, largest, design effect, any shared between the pools | `design`, `use_cases[].inclusion_prob_range` |
| `measurement` | Per failure mode: its counted check and type, observed rate, catch rate and clean pass rate with intervals, J, labels per kind, inflation at the lower bounds against `max_inflation`, the floor's status, the corrected rate. Uncounted judges greyed with the reason. The eval against people beside it: catch and clean pass rates (dev, holdout), labels per kind against the count needed, the floor; the person-anchored rate; agreement between people (AC1, agreement on fails and on passes) in a column group labeled "reliability (not validity)" | `measurement`, `checks` |
| `decision` | The result in words (`pass`, `fail`, `insufficient`, `unknown`, `trade`) with its reasons; each gate's test, estimate, interval, bound, p (and adjusted p), detectable effect and `cases_needed`; `also_requires` per eval; constraints with each breach (`new` flagged); the look count | `decision` |
| `comparison` | Gains and losses as separate bars, each case listed; flips (b, c, flip rate) next to the net; Δθ̂ with its interval and the sign-flip p; the verdict and its reasons; per-use-case rows with adjusted p-values; bug-finding flips apart; new budget breaches. No net-only view. When `refused`, the refusal instead | `comparison` |
| `operational` | Per use case: cost per success, latency p50 and p90, tokens, cache hits, errors by outcome code, against the constraints. **Next to the correctness panels, never merged with them** | `use_cases[].operational`, `decision.constraints` |
| `gates` | The evidence gates by part (agent contract, design, measurement), pass, fail or n/a, with each failure's detail and what it means for the number | `gates`, `measurement.gates` |
| `next` | Next steps, each with the command that clears it, built from `spec.missing`, failed gates, `measurement.gates`, and the decision's reasons and `cases_needed` | those keys |

### Rules

1. **Every number shows its n, its k and an interval**, or says why there is none.
2. **The headline is θ̂ under the stated weights**, with the per-use-case table beside it as the
   diagnostic. Name the weights; never show an unweighted average over use cases.
3. **Only the quality set is a rate.** Bug-finding numbers are labeled as such and never sit in a
   column with quality rates.
4. **Correctness and cost are never combined.** Show an operational regression even when correctness
   hasn't changed; a gain that breaks a budget is a trade.
5. **Unknown stays unknown.** A null is shown with its reason, never as 0, a dash or a blank.
6. **"No significant difference" is never written as "no worse"**: say what the decision rule says,
   and the smallest change the comparison could have seen.
7. **Reliability and validity never share a column group.**
8. **Every claim in prose links (`#decision`, …) to the panel it comes from.**

## 4. Before handing it over

Open the file in a browser if one is available. Check that every panel renders, nothing makes a
network request, and every greyed item says why. Then log it, so it shows on the activity page with
the "waiting for you" banner, and stop:

```bash
aot-evals log "Report ready: <eval>/report/report-<date>.html" --kind question
```

Give the user the path, the headline in two sentences (θ̂ with its interval, and the decision), and
the first next step.
