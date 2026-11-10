---
name: build
description: Build, the second of aot-evals' three phases, for engineering. Gets an agent's eval loop running with the fewest decisions - the agent wired to run as a command, 10 to 20 cases from real runs with a check on each, a baseline, and the grader application handed to the people who will label - then raises trust step by step (real-traffic provenance, the agent inventory, screens, the labelling standard and per-case requirements, categories and budgets, the coverage list, case allocation, comparisons of a changed agent, coverage and redundancy). Use when start says the phase is Build, when someone asks to wire an agent up for evals, write eval cases or checks, run a baseline, or compare a change to the agent.
---

# build: get the loop running

Build is engineering's phase. It ends with the loop running: the agent runs from a command, real
runs have become cases with a check on each, the baseline has run, and the grader application is
in the hands of the people who will label. Everything else is an **upgrade** that raises trust in
a number. Nothing refuses to run because an upgrade is missing; the report greys what it covers.

Method: `${CLAUDE_PLUGIN_ROOT}/docs/method.md` (§4.1 for the phases, §3 for the files). Pacing,
words and the rules you hold the team to: `${CLAUDE_PLUGIN_ROOT}/references/working-in-checkpoints.md`.
Paths start at `<suite>/`: `evals/agents/<agent>/`, beside the discovery report. Pass `--agent
<agent>` to every command when the repository has several agents.

## 1. The lightest Build

```bash
aot-evals build          # drafts what it can from the discovery report, prints the checklist
```

It creates the suite's files, drafts categories from the report's task types and the coverage
list from its situations, and adds one check that runs on every case: the world ends as the case
expects (`checks/code/end-state-matches.py`). **Commit `taxonomy.yaml` now, before any case**:
coverage is measured only against a list that came first. Then work down the checklist.

**1. Wire the agent.** Read `${CLAUDE_PLUGIN_ROOT}/references/agent-contract.md`. Most agents need
a small entry point that reads the case on stdin and prints the result JSON; set it as
`invoke.command` in `agent.yaml`. Add `seed` and `observe` hooks wherever the agent changes state:
checks grade what `observe` prints, never what the agent says it did. Where the agent can't run
safely, replay recorded runs instead (`aot-evals replay`). Two things to settle now:
- **Does a model call site have tools of its own?** A coding harness (`opencode run`, `claude -p`)
  or a model with web search can read the repository, including the cases. Set
  `invoke.isolate: true`.
- **Run it once:** `aot-evals run --purpose smoke --question "<a real request, scrubbed>"`. Read
  the raw output in `<suite>/runs/<id>/raw/` with the owner.

**2. Seed 10 to 20 cases from real runs**, in the two or three largest categories. Start from
`${CLAUDE_PLUGIN_ROOT}/templates/case.json`. Each case freezes the trigger, inputs, start state
(what `seed` writes), scripted follow-ups, and the expected end state, `{"world": …, "output": …}`.
- **A person confirms every expected end state.** Never ship an uncorrected model draft as ground
  truth. Checkpoint after the first two or three cases per category, before writing the rest.
- **Derive expected values from the start state** (a count, a total, a list of ids), rather than
  typing them in. A typed-in expected answer is where suites go wrong.
- **Scrub before writing:** names to placeholders, emails to `example.com`, no tokens or keys.
  `aot-evals validate` blocks on secrets and warns on likely PII.
- Give each seeded case `set: error_finding`, its `category`, and `provenance` (the source, the
  trace it came from, `synthetic: false`).

**3. A check on every case.** The generic end-state check covers agents that change state. Where
the world holds values a correct run can't reproduce (ids, timestamps, order), or the deliverable
is prose, write a code check per failure mode from `${CLAUDE_PLUGIN_ROOT}/templates/check_code.py`:
`check(start, end, case) -> (bool, detail)`, graded against the goal, never the agent's claim.

**4. The baseline**, on a committed agent:

```bash
aot-evals build --run      # the smoke run if needed, a k = 3 baseline, the report
```

**5. Hand over to Judge.** Start the grader application and give each grader their own link:

```bash
aot-evals serve --open     # then add &labeller=NAME to the link for each grader
```

Checkpoint "The loop is running": the per-category results with their intervals, how much they
move between trials, and the link. Then load `judge` for the people's side.

## 2. Upgrades, in the order they usually pay off

`aot-evals status --gates` lists the open ones. Do them when the numbers they cover matter.

**Real traffic, with provenance.** Import the team's trace export (`aot-evals import FILE
--source … --query … --window …`) so every number traces to it. Never call a vendor API. Then
offer the operational sweep, which needs no labels: `aot-evals ops --export <id> --field
cost_usd=… --field latency_ms=…`. Cost per successful task, not per run.

**The inventory** (`agent.yaml`): the model actually used per call site, taken from the traces
(`models_evidence` says how), including side calls such as routing or titles; the version history
and how long it has been stable; every tool, with credential names only.

**Screens** (`aot-evals screen`): per case, the reference end state passes, doing nothing fails,
and doing nothing while claiming success fails. With a reference answer, add two or three other
correct wordings (`expected_end_state.output_variants`): each must pass, a bare "Done!" must fail,
and an answer with every number wrong is reported if it passes. A person reads each case
(`aot-evals screen --read-by NAME --case ID`). Unscreened cases stay out of gated numbers.

**The labelling standard and requirements.** `labels/standard.md` holds the rules a person applies
when failing a run (every stated fact true, lists complete or marked partial, writes right and
complete, related records connected, nothing left behind, wide changes confirmed). Fit them with
the owner; graders propose more from their rulings in the grader application. Then walk the rules
for every case: each rule that applies becomes a concrete `requirement` naming the checks that
decide it, or goes in `rules_not_applicable` with why. **Check every fact a prose answer states**
with a grounding check: a false number inside a right-sounding answer is the failure suites miss
most.

**Categories, failure modes and budgets.** Confirm the drafted categories with the owner: worth
(low, medium, high), a cost per kind of failure, an example trace, and the share of traffic counted
from the export (`share_source`). Split the generic failure mode into the specific ways each
category fails, each `code`, `judge` (only where code can't decide; then `judge` calibrates it) or
`monitor`. Keep a side-effect mode on every case. Set cost and latency budgets in `budgets.yaml`
from the sweep, not from guesses.

**The coverage list.** Add the agent's jobs to `taxonomy.yaml` from a document written for
another purpose (the product spec, help-centre topics, the tool surface), never from the cases.
Here, and only here, search the web for public benchmarks newer than the catalog: sources of
grading designs and situations, never of cases.

**Allocation** (`aot-evals allocate`): two sets sized by different arithmetic. Error-finding:
about 10 per category, 3 for simple ones. Quality-estimate: in proportion to traffic, sized by the
interval the owner needs. Only the second may be called quality. Show the smallest detectable
change before anything runs, and say what the error-finding targets can find: `allocate` prints
the rarest failure each one surfaces (10 cases: a failure in about one run in four). Where a rare
failure would be costly, write cases aimed at it rather than adding cases everywhere. After the
baseline, the report's `variance_components` says whether more cases or more trials narrow the
interval faster; more cases usually win. Background: `${CLAUDE_PLUGIN_ROOT}/docs/statistics.md`.

**Compare a change.** After any change to the prompt, skills, tools, model or harness, commit it
and run a candidate with one declared variable:

```bash
aot-evals run --purpose candidate --k 5 --variable prompt=<what changed>   # or --model <id>
aot-evals compare
aot-evals agreement label queue --changed      # people label only what moved
```

Lead with gains and losses, never a net number alone. A change is better or worse only when the
paired test is significant and outside the baseline's spread; a gain bought with a budget breach
is a trade. If the change ships, run it as the new baseline.

**Coverage and redundancy.** `aot-evals coverage` lists the empty cells against the coverage list,
most valuable first: write a case or record why it doesn't apply. `aot-evals redundancy`, after
two or more versions, proposes cases to prune that never tell versions apart; the owner decides
each.

Drift and online evaluation are guidance only for now (method §4, C16 and C17).
