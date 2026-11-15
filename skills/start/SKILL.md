---
name: start
description: The one command to remember for aot-evals. Says which of the three phases each of an agent's evals is in (Assess, Build, Judge), how far each eval's number can be trusted, what changed since its baseline, and carries on with the next step. With no discovery report yet (evals/agents/<agent>/discovery.md) it runs Assess itself, about 5 minutes - the AOT EVALS banner, a scan for every agent, three questions to the owner, discovery in parallel, and a plain-English report that settles the estimand (what the agent is for, where its evals go, its use cases and what a failure in each costs) - otherwise it hands over to build or judge. Use for "start aot-evals", "set up evals", "build evals for my agent", "assess my agent", "where are we with our evals", "what's next", "is this suite any good", or after any change to the agent, its prompt, tools or model.
---

# start

The single entry point. Work out where the evals stand, say so in plain words, and carry on with
the next step. An eval is an estimator with four parts: the **estimand** (what number, for which
decision), the **sampling design** (which cases, drawn how), the **measurement model** (how wrong
the grader is) and the **decision rule** (when to act). The person meets them as three phases:

| Phase | Settles | Skill |
|---|---|---|
| Assess | the estimand: what the agent is for, where its evals go, its use cases, what a failure in each costs, the decision each eval drives | this one (§2) |
| Build | the agent contract, the sampling design, the checks, the decision rule, a baseline | `build` |
| Judge | the measurement model's error rates: people label runs, judges are measured, the eval is held to people | `judge` |

Reference: `${CLAUDE_PLUGIN_ROOT}/docs/method.md` (§2 the parts and phases, §12 status). Words
mean what `${CLAUDE_PLUGIN_ROOT}/docs/estimators.md#terms` says: use case, pool, coverage, plan,
catch rate, clean pass rate. Pacing and wording: `${CLAUDE_PLUGIN_ROOT}/references/working-in-checkpoints.md`.

CLI: `"${CLAUDE_PLUGIN_ROOT}/bin/aot-evals"`. Call it by that full path: a bare `aot-evals` on
PATH can be an older install. It needs `uv`, or Python ≥ 3.11 with PyYAML, and installs nothing
into the team's project. With several agents, pass `--agent <agent>`; with several evals, `--eval
<id>`. Below, `aot-evals` means that full path.

## 1. Which phase

1. Look for agents with evals: `evals/agents/*/agent.yaml`. A folder that still holds a 1.x suite
   (`categories.yaml`, `failure_modes.yaml`, or a suite directly in `evals/` or `evals/<agent>/`)
   must be converted first: show `aot-evals migrate --to 2 --dry-run`, then run `aot-evals migrate
   --to 2` and walk the owner through the MIGRATION.md it writes in the agent folder (the decision
   and the margin are theirs to fill). **No agent folder and no `evals/agents/*/discovery.md`:**
   run Assess (§2). Stop there.
2. Otherwise run `aot-evals status`. It prints the agent's phase, then per eval its phase, its trust
   (untested, provisional or trusted, with each open reason and its command), what changed since its
   baseline with the way back, and the next step.

## 2. Assess: settle the estimand (about 5 minutes)

Assess runs for **one** agent and is read only: never contact live services, run the agent, or
copy raw traces into `evals/`.

**Rules for everything you write to the owner.** Plain English a ninth grader can follow; the
phases are Assess, Build and Judge, and nothing else is named by a code. Say what a thing is, not
its label ("three booking bugs found on Mar 3", not "BK-101 to BK-103"). Lead with the point;
numbers with units; mark anything inferred as a best guess. Never ask for something you can look
up. Never print private content (names, addresses, message text, secrets): counts and kinds only.

### 2.1 The banner, on its own, first

Before any other command or question, run `aot-evals start` **by itself**, with no other command
in the same message. The plugin draws its output in full; don't paste it. Say one short line
("Starting the scan now."), then go on.

### 2.2 Quick scan: find the agents (under a minute, no subagents)

Look for every agent in the repository and anything it points to: skill packs
(`skills/*/SKILL.md`, `.claude/skills/`, plugin folders; **each skill of a multi-skill system is
its own agent**), agent code (entry points using an agent framework or model SDK, system prompts,
tool definitions), triggers (cron, queues, webhooks, chat channels), records (trace or log exports;
read their README first), and history (`git log --since="30 days ago"` per agent folder).

Sort each into **agent** (its own trigger and state), **helper** (started by a person) or **rule
or mode** (used inside other agents; tested inside them). Show one numbered table: agent, what it
does in one line, how often it ran recently, whether it starts on its own, changes in the last 30
days. Suggest one, with the reason (what it can do that can't be undone, what test work exists).

Ask **"Which agent are we building evals for?"** (AskUserQuestion when you have it, the four
likeliest as options). **Stop and wait.** From here on, everything is about that one agent.

### 2.3 Discovery in parallel, then three questions

Launch four read-only discovery subagents in the background (Agent tool, `general-purpose`,
`run_in_background: true`), all in one message. Each has a hard limit of 6 minutes and returns
under 600 words, a source for every fact, "(inferred)" on guesses. Give each the agent's name,
folders, entry point and where its records are.

1. **How it works, and where its evals go** (the unit). Its jobs and what starts each; platform,
   model and limits; where its instructions live and which wins when they disagree; memory between
   runs; each guard rail and what enforces it; dated history; how stable it is. **Its context
   boundaries:** every subagent, route and step the orchestrator calls, and for each whether it
   starts from a handoff the orchestrator writes (a **subagent**, its own context), gets the
   user's request as sent because a router picked it (a **route**), or runs inside the
   orchestrator's context (a **step**); its own prompt, model and owner; whether it changes on its
   own schedule (git history per folder, separate owners or deploys); whether traces record each
   handoff and its input.
2. **Tools and the sandbox** (the agent contract). Every outside service: what it reads and writes,
   side effects and whether they can be undone, login names only. Whether a model call site has
   tools of its own (a coding harness such as `claude -p`, web search): it could read the
   repository, cases included. What records of past runs exist, and how far back. Existing test
   setup or earlier eval work, including other git branches and nearby folders.
3. **Traffic and use cases** (the population). Match runs to this agent by channel, timer and its
   files, and say which signal matched. Runs in total and in the last 4 weeks. Sort recent runs into
   **use cases** by what the person wanted done (look something up, change a record, summarize),
   so that each request belongs to exactly one; aim for 7 or fewer. Use cases are not
   **situations** ("ambiguous", "refused", "multi-turn", "a tool failed"): those cut across every
   use case, so count per use case how many runs showed each. `aot-evals benchmarks` lists the
   situations. For each use case: its **share** of traffic, measured from the records, its
   outcome mix, cost and latency (median, 90th percentile), and the worst thing a failure in it did
   (did it write, delete, send or move money; could it be undone; would anyone notice).
4. **Test data and privacy** (the frame). Where cases can come from (real runs, cleaned examples,
   labels). Kinds of private data present, with counts. Where raw data sits and whether git
   ignores it; any cleaning tool and what it misses; anything under an NDA. Public benchmarks that
   fit, **from the local catalog only**: `aot-evals benchmarks --workload TAG --task "<use case>"
   ...`, with what to borrow from each (a grading design, a case template, a sandbox design) and
   which situations it adds. Benchmarks are a source of grading designs and situations, never of
   cases. Then map every existing case file into the grid of use cases × situations.

While they run, ask the owner three questions, each with a suggestion drawn from the scan. Keep
the owner's answer in their own words, separate from your suggestion; never merge the two. Don't
wait for the answers before writing the report.

1. **What decision will these tests drive, and who makes it?** (the estimand's decision) For
   example: ship a prompt or model change, swap to a cheaper model, keep or replace a subagent.
   Ask who owns that decision and how often it is made.
2. **Are some of its mistakes much worse than others?** (the weights) Offer: about the same; some
   are much worse (which, and roughly how much: a wrong status costs a follow-up, a wrong refund
   costs money); not sure yet. Equal is a fine answer if it is true; an unstated cost stays
   unknown, it is never assumed equal.
3. **What should a change have to show before it ships?** (the decision rule) List in this order
   and mark one "(suggested)": no worse than today by more than a small margin (a non-inferiority
   test); better than today (a superiority test); a failure rate under a fixed bar (a threshold
   test). Say that the number of cases follows from this answer, and that Build works it out
   (`aot-evals plan`).

### 2.4 Write the report

When the four subagents are back, write `evals/agents/<agent-slug>/discovery.md` (nothing else goes
in that folder yet): YAML front matter that fills the page's overview and next steps, then the
markdown details. Every value is one or two plain sentences (inline markdown allowed), with real
numbers from discovery.

```yaml
---
minutes: 8                       # how long Assess took
bottom_line: >-                  # 2 or 3 sentences: is it understood, and what stands in the way
  ...
stats:                           # exactly 3 numbers that matter most for this agent
  - {value: "1,004", label: past runs studied}
  - {value: "4", label: use cases found}
  - {value: "2%", label: of requests are refunds}
needs_you: Say what a wrong refund costs   # the one thing waiting on the owner; leave out if none
overview:                        # the page's four pillars, these keys
  business_context: {found: ..., state: done, label: Clear, open: ...}   # the decision, its owner, the costs
  agent_architecture: {...}      # code, prompts, models, tools, traces, context boundaries
  safe_testing_env: {...}        # can runs touch real people, data or money; cost and speed
  golden_use_cases: {...}        # use cases with shares, cases that exist, the empty grid cells
                                 # state: done | partial | risk | todo; label: 1-3 words; open: under 12 words
boundaries:                      # from read 1; leave out for one context
  - id: refund-subagent
    kind: subagent               # subagent | route | step
    context: own                 # own | shared
    called_by: the orchestrator's refund route
    model: claude-haiku-5-5
    owner: refunds team
    ships_separately: true       # null when discovery can't tell; then ask the owner
    use_case: refund             # the use case whose requests reach it
    evidence: "`agent/refunds.py`, its own prompt; 14 commits in 30 days, none touching the orchestrator"
components:                      # what the optimization loop already has, keyed by id (aot-evals components)
  sandbox: {state: partial, note: "runs from `make agent`; no isolation from the repository"}
grid:                            # use cases (rows) by situations (columns): the bug-finding set's coverage
  note: ...                      # one sentence on how the targets were set
  columns:                       # from the situations `aot-evals benchmarks` printed, in its order
    - {id: unanswerable, from: CRMArena}
  rows:
    - task_type: Refund an order  # the use case, in plain words
      share: 2%
      cells:                     # `plain` first, then one key per column id; null where it can't arise
        plain: {have: 3, want: 4}
        unanswerable: {have: 0, want: 2}
next:
  path: ...                      # the recommended path, as a short headline
  why: ...
  steps:                         # 3 to 6, owner steps first
    - {who: you, title: ..., detail: ..., when: 5 minutes}
    - {who: us, title: ..., detail: ...}
  other_paths:
    - {name: ..., why: ...}
---
```

- **Boundaries decide how many evals there are**: one end to end always, plus one for each subagent
  with its own context that ships on its own (rule 3). A route is a use case of the end-to-end eval,
  with a gate of its own when its model ships on its own; a step is graded by checks end to end. The
  page shows them under "Where the evals go", and `aot-evals build` creates the evals they call for.
- **The grid is the bug-finding set's coverage**, not the quality set: the quality set is drawn at
  random in Build and sized by the decision rule. Set each cell's `want` to the few hard cases that
  reach it, more where the traffic showed failures, and leave cells that can't arise null. The
  empty cells are the finding: say in `golden_use_cases.found` how many columns have no cases, and
  where a cell is empty because nobody wrote cases there rather than because the agent fails there.
- Use `risk` only when something could touch real people, data or money today.

**The markdown.** The first line is the title: what the agent is, in plain words, with its code
name in brackets (`# Support agent (store)`). No opening paragraph. Then these sections, with these
exact headings:

1. **Business context.** A Goals table first (Question, Your answer, Evidence): the three questions,
   plus "What it must never do without asking" from discovery. An unanswered one says "Waiting for
   you" with the suggestion after it. Then **What it does**, **Volume and cost**, **Biggest risk**,
   **Keep in mind**, each a short bold-led paragraph.
2. **Agent architecture.** How it's built, the model, where its instructions live and where they
   disagree, memory, guard rails, dated history, stability, its context boundaries. Then `### What's
   around the agent`: tools and side effects (what testing needs for each), records of past runs.
3. **Safe testing environment.** What exists, what ran, the gaps in order; private data (counts
   only); the cleaning tool and what it misses; a privacy plan that needs a yes.
4. **Golden test cases.** The jobs; the use cases with share, the cost of a failure (the owner's, or
   "not stated") and how each is checked (code first; a judge only where code can't decide); where
   cases come from; **Public benchmarks that fit** (Benchmark, Which use cases it informs, What to
   borrow, Which situations it adds, Caveats). The page draws the grid here from the front matter.
5. **Questions for you.** At most five (Question, Suggested answer, If no reply); anything touching
   private data waits for a yes (⏳).
6. **How this run went.** Time per step, what should change, then sources.

Render and open it: `aot-evals discovery-page evals/agents/<agent-slug>/discovery.md --agent "<agent
name>" --open`. Then reply in a few lines: where the report is, which questions are open, and the
next step. Build starts once the three questions are answered and the privacy plan has a yes; then
load `build`.

## 3. Say where things stand

Outside Assess, tell the person in three or four plain sentences, from `status`: the phase of each
eval, how far its number can be trusted and why (the first open reason, in plain words), anything
that changed since its baseline, and the next step. Then open the activity page and log that you
are waiting (`references/working-in-checkpoints.md`):

```bash
aot-evals activity --open
aot-evals log "Where <agent>'s evals stand: <one line>" --kind question
```

Stop and wait for the person, unless they already asked you to carry on.

## 4. Hand over

| `status` says | Load |
|---|---|
| Phase: Build (no eval yet, or no number under the current spec) | `build` |
| An eval in Judge and provisional because it isn't held to people, or a judge doesn't count | `judge` |
| An eval in Judge and provisional because the quality set is short | `build` (plan, draw, rerun) |
| A change since the baseline | the change's path below |
| Someone asks for a report, dashboard or scorecard | `report` |

**After a change** (status names each, with its command):

- **The agent changed** (prompt, skill, tool, model, harness): the baseline no longer describes
  it. Commit it, run a candidate with one declared variable and compare (`build`, "Decide on a
  change"), then have people label only what moved (`aot-evals agreement label queue --changed`).
- **A candidate has run and not been compared**: compare it, read the decision with the owner,
  then either run it as the new baseline or put the agent back.
- **A revision** (the estimand, the design or the checks changed, a new judge or a new use case
  included): old and new numbers are different quantities. Bump the spec's major version and run
  the baseline again; nothing is compared across it.
- **Only the decision rule changed**: commit `eval.yaml` (or `aot-evals --eval <id> log --kind
  decision "why"`) before the candidate runs, or the comparison refuses it.
- **The traffic mix or routing changed**: re-measure the shares; a routing change also means
  extracting the component evals' handoffs again (`aot-evals --eval <id> handoffs`).

Nothing refuses to run because something is missing: a missing spec field or an unmeasured grader
nulls the numbers that depend on it, with the reason. Say so plainly when it happens.
