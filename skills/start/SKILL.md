---
name: start
description: The one command to remember for aot-evals. On the first run (no discovery report at evals/agents/<agent>/discovery.md yet) it runs the first assessment with the owner, about 5 minutes - the AOT EVALS banner, a scan for every agent, three questions (what decision the tests drive, which mistakes cost most, what a change must show), discovery in parallel, and a plain-English discovery report. After that it says where each of an agent's evals stands - how far its number can be trusted, what changed since its baseline, and the next step for each role (the owner, engineering, the people who know what good looks like) - and carries on. Also offers to rebuild from an evals/ folder it doesn't recognize. Use for "start aot-evals", "set up evals", "build evals for my agent", "assess my agent", "where are we with our evals", "what's next", "is this suite any good", or after any change to the agent, its prompt, tools or model.
---

# start

The single entry point. Work out where the evals stand, say so in plain words, and carry on with
the next step. Three groups of people take part, usually at the same time:

| Role | Who | What they settle | Skill |
|---|---|---|---|
| The owner | a product owner or team lead | what the agent is for, which mistakes cost most, what a change must show before it ships | this one: three questions, about five minutes (§3) |
| Engineering | developers | the agent wired up to run safely, cases from real traffic, a check for each way it can fail, baselines and changes | `build` |
| Graders | the people who know what good looks like (experts, support staff, end users) | whole runs labeled pass or fail, disagreements settled, rules that AI judges learn | `judge` |

None waits for another to finish: graders can label the first runs while engineering is still
writing checks, and the owner states a cost or a margin whenever it comes up.

Reference: `${CLAUDE_PLUGIN_ROOT}/docs/method.md` (§2 the parts and roles, §12 status). Words
mean what `${CLAUDE_PLUGIN_ROOT}/docs/estimators.md#terms` says: use case, pool, coverage, plan,
catch rate, clean pass rate. Pacing and wording: `${CLAUDE_PLUGIN_ROOT}/references/working-in-checkpoints.md`.

CLI: `"${CLAUDE_PLUGIN_ROOT}/bin/aot-evals"`. Call it by that full path: a bare `aot-evals` on
PATH can be an older install. It needs `uv`, or Python ≥ 3.11 with PyYAML, and installs nothing
into the team's project. With several agents, pass `--agent <agent>`; with several evals, `--eval
<id>`. Below, `aot-evals` means that full path.

## Speak in consequences

You do the statistics; the person gets what they mean for the next step. Say "about 40 more refund
cases would show it", "this judge needs about 80 more labeled failures before its scores count",
"don't quote the 92% yet: nobody has checked the eval against your reviewers". Don't explain
estimators, intervals, power or inflation factors unless someone asks; then point them to
`docs/estimators.md` (the model) and `docs/statistics.md` (the derivations), and answer the
question they asked.

## 1. Where things stand

1. Look for agents with evals: `evals/agents/*/agent.yaml`. If `evals/` holds files that
   `aot-evals validate` doesn't recognize, or `status` can't read the folder, go to §2. **No agent
   folder and no `evals/agents/*/discovery.md`:** run the first assessment (§3). Stop there.
2. Otherwise run `aot-evals status`. Per eval it says how far its number can be trusted (untested,
   provisional or trusted, with each open reason and its command), what changed since its baseline
   with the way back, and the next step and who takes it.

## 2. An evals/ folder aot-evals doesn't recognize

When `evals/` holds files that `aot-evals validate` doesn't recognize (a suite from an earlier
version of aot-evals, or from another tool), say what you found in counts and kinds (cases, code
checks, judge prompts with labeled examples, a labeling standard, fakes) and offer to rebuild the
evals from it. It is raw material, not an eval: nothing in it is converted in place. Copy what
carries across into the layout `aot-evals build` creates, and leave the old files for the owner to
remove once the new evals run. With a yes, run the first assessment (§3) as
usual, letting discovery read the old suite, then `aot-evals build`, and carry across:

- **Code checks** that keep the signature `check(start, end, case) -> (bool, detail)` copy into
  `<eval>/checks/code/` as they are. Check any that find files from their own path
  (`Path(__file__)`): they sit in a different folder after the copy. A check that grades the
  agent's own report of success instead of the world is refused; say so and rewrite it against
  what `observe` prints.
- **Judge prompts** copy into `<eval>/checks/judge/<id>.md` with the front matter of
  `${CLAUDE_PLUGIN_ROOT}/templates/check_judge.md`, one failure mode each. Their **labeled
  examples become calibration labels** in `<id>.labels.jsonl`, in the shape `label import` writes;
  then `aot-evals calibrate --judge <id>`. Hand-picked examples tend to be the clear ones, so add
  labels from the queue too (`judge`).
- **The labeling standard** carries across as it is to `evals/agents/<agent>/labels/standard.md`;
  **agent.yaml** to `evals/agents/<agent>/agent.yaml`; **the fakes and hooks** to
  `evals/agents/<agent>/env/`.
- **The old cases become the bug-finding set** (`pool: bug_finding`, with a `use_case`, in
  `cases/<use_case>/`). They were not drawn at random with recorded inclusion probabilities, so
  they can find failures but can't stand for the traffic: they never become the quality set.
- **The quality set is drawn fresh from traces**: `aot-evals import FILE --source … --query …
  --window …`, then `aot-evals plan --write` and `aot-evals draw`.
- **Old results don't carry over**: a new baseline runs once the cases are screened and committed.

Then run `aot-evals validate`. It lists every field the specs still lack; fill them in with the
owner (what the eval decides and who owns it, the cost of a failure per use case, the margin or
bar), in plain words, one question at a time.

## 3. The first assessment: the owner's three questions (about 5 minutes)

The first assessment runs for **one** agent and is read only: never contact live services, run
the agent, or copy raw traces into `evals/`.

**Rules for everything you write to the owner.** Plain English a ninth grader can follow; nothing
is named by a code. Say what a thing is, not its label ("three booking bugs found on Mar 3", not
"BK-101 to BK-103"). Lead with the point; numbers with units; mark anything inferred as a best
guess. Never ask for something you can look up. Never print private content (names, addresses,
message text, secrets): counts and kinds only.

### 3.1 The banner, on its own, first

Before any other command or question, run `aot-evals start` **by itself**, with no other command
in the same message. The plugin draws its output in full; don't paste it. Say one short line
("Starting the scan now."), then go on.

### 3.2 Quick scan: find the agents (under a minute, no subagents)

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

### 3.3 Discovery in parallel, then three questions

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
   test). Say that the number of cases follows from this answer, and that engineering works it out
   (`aot-evals plan`).

### 3.4 Write the report

When the four subagents are back, write `evals/agents/<agent-slug>/discovery.md` (nothing else goes
in that folder yet): YAML front matter that fills the page's overview and next steps, then the
markdown details. Every value is one or two plain sentences (inline markdown allowed), with real
numbers from discovery.

```yaml
---
minutes: 8                       # how long the first run took
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
  random by engineering and sized by the decision rule. Set each cell's `want` to the few hard cases that
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
name>" --open`. Then reply in a few lines: where the report is, which questions are open, and who
does what next: engineering can start (`build`) once the three questions are answered and the
privacy plan has a yes, and the graders can start labeling as soon as the first runs exist.

## 4. Say where things stand

Outside the first assessment, tell the person in three or four plain sentences, from `status`: for
each eval, how far its number can be trusted and why (the first open reason, as a consequence:
"the refund numbers can't be quoted yet: about 40 more refund cases would settle them"), anything
that changed since its baseline, and the next step for each role that has one. Then open the
activity page and log that you are waiting (`references/working-in-checkpoints.md`):

```bash
aot-evals activity --open
aot-evals log "Where <agent>'s evals stand: <one line>" --kind question
```

Stop and wait for the person, unless they already asked you to carry on.

## 5. Hand over

Load the skill for the role the person in front of you holds, or the one the next step needs:

| The next step | Load |
|---|---|
| No eval yet, or no number under the current spec; wiring, cases, checks, a baseline; a short quality set (plan, draw, rerun) | `build` |
| Runs to label, a disagreement to settle, the eval not held to people yet, a judge that doesn't count | `judge` |
| A spec field only the owner can fill (the decision, a cost, the margin or bar) | ask the owner here, one question at a time |
| A change since the baseline | the change's path below |
| Someone asks for a report, dashboard or scorecard | `report` |

When engineering and the graders both have a step, say both: they can go at the same time.

**After a change** (status names each, with its command):

- **The agent changed** (prompt, skill, tool, model, harness): the baseline describes the agent as
  it was. Commit the change, run a candidate with one declared variable and compare (`build`,
  "Decide on a change"), then have people label only what moved (`aot-evals agreement label queue
  --changed`).
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
nulls the numbers that depend on it, with the reason. Say so plainly when it happens, and say what
would fill it.
