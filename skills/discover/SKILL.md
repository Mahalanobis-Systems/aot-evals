---
name: discover
description: Phase 1 of aot-evals, usually reached through start. Runs when a team wants evals for an agent and no discovery report exists yet (evals/agents/<agent>/discovery.md), about 5 minutes. Shows the AOT EVALS banner and the two phases, scans the repository for every agent (each skill of a multi-skill system counts as its own agent), asks which agent to test, asks three questions about it, runs discovery in parallel, and writes a plain-English discovery report: an overview of the four things good evals rest on, the details, and next steps. Use for "set up evals", "build evals for my agent", "start aot-evals", or when status finds no discovery report.
---

# discover: Phase 1

You run Phase 1 of building evals for **one** agent: discovery and a first report, in about 5
minutes of work. Phase 2 (building the evals) comes later and takes an afternoon.

CLI: `"${CLAUDE_PLUGIN_ROOT}/bin/aot-evals"` (also `aot-evals` on PATH while the plugin is on).

## Rules for everything you write to the owner

- Plain English a ninth grader can follow. No step codes (no C0–C19, gate ids, "Part 3",
  "Build 2"), no jargon a new engineer wouldn't know.
- Say what a thing is, not its label: "three booking bugs found on Mar 3", not "BK-101 to
  BK-103"; "look up records", not "read-lookup"; "the reply stopped partway", not "stall";
  "put deleted records back", not "reseed"; "how much results move by chance", not "noise
  band". A label or file name may follow in brackets. Dates as "Sep 18", not "09-18".
- Lead with the point. Numbers with units. Mark anything inferred as a best guess.
- Never ask for something you can look up. Never print private content (names, addresses,
  message text, secrets): counts and kinds only.
- Read only. Never contact live services, run the agent, or copy raw traces into `evals/`.

## Step 1. Show the banner and the two phases, on their own, first

Before any other command, and before any question, run this command **by itself**, with no
other command in the same message:

```bash
aot-evals start
```

The plugin draws this command's output in full in the conversation, so don't paste it. Wait
for it to finish, say one short line ("Starting the scan now."), then start Step 2.

## Step 2. Quick scan: find the agents (under a minute, no subagents)

Look for every agent in the repository and anything it points to:

- Skill packs: `skills/*/SKILL.md`, `.claude/skills/`, plugin folders. **Each skill of a
  multi-skill system counts as its own agent.**
- Agent code: entry points using an agent framework or model SDK, system prompts, tool
  definitions.
- Triggers: cron or scheduler definitions, queue consumers, webhooks, chat channels.
- Records: trace or log exports in or next to the repository (read their README first).
- History: `git log --since="30 days ago"` per agent folder.

Sort each into **agent** (runs on its own, with its own trigger and state), **helper** (started
by a person), or **rule or mode** (used inside other agents; tested inside them, not listed for
choice). Where several agents share one channel or entry point, say the split isn't possible
yet; full discovery will split it.

Show one numbered table: agent, what it does in one line, how often it ran recently (if records
exist), whether it starts on its own, changes in the last 30 days. Then suggest one, with the
reason (what it can do that can't be undone, and what test work already exists).

Ask: **"Which agent are we building evals for?"** Use the AskUserQuestion tool when you have it
(the four likeliest as options); otherwise ask in plain text. **Stop and wait for the answer.**
From here on, everything is about that one agent.

## Step 3. Start discovery, then ask the three required questions

First launch four discovery subagents in the background (Agent tool, `general-purpose`,
`run_in_background: true`), all in one message, so they run while the owner answers. Each is
read-only, has a hard limit of 6 minutes, and returns under 600 words with a source for every
fact and "(inferred)" on guesses. Give each the agent's name, its folders, its channel or entry
point, and where the records are.

1. **How it works.** Its jobs and what starts each; platform, model and limits; where each piece
   of its instructions lives (files, scheduler text, files outside git) and which one wins when
   they disagree; what it remembers between runs; each guard rail and whether instructions,
   code or permissions enforce it; dated history of changes; how stable it is; contradictions.
2. **Tools and test space.** Every outside service: what it reads and writes, side effects,
   whether they can be undone, its kind (fixed data, live internet, changing records, changes
   records, acts on the outside world, own state), login names only. Whether any model call
   site is itself an agent with its own tools (a coding harness such as `opencode run` or
   `claude -p`, web search): if so, it can read the repository, including evals/. What records of past runs
   exist and how far back; is cost real or estimated. Any existing test setup or earlier eval
   work, **including other git branches and nearby local folders**: what ran, what's missing,
   what to build next in order.
3. **Traffic and task types.** Match runs to this agent by channel, timer and the agent's files
   together, and say which signal matched. Runs in total and in the last 4 weeks, by trigger;
   outcome mix and failure reasons. Sort recent runs into task types (aim for 7, never 10 or
   more) by **what the person wanted done**: look something up, change a record, summarize.
   A task type is never a property of the request. "Safety", "refusals", "multi-turn",
   "ambiguous" and the like are **situations**, not task types: a lookup can arrive over four
   turns and need a question first, so these cut across every task type. Keep them out of the
   task type list and instead count, per task type, how many runs showed each situation
   (asked first or didn't, refused, was told "none", a tool call failed, the thread was lost).
   `aot-evals benchmarks` lists the situations. Share, cost and latency (median, 90th
   percentile) for each task type. Health of each timer: last success, recent failures. How
   often the owner corrected it.
4. **Test data and privacy.** Where examples can come from (real runs, cleaned examples,
   labels, earlier drafts and whether the owner confirmed them). Kinds of private data present,
   with counts: people, family, customers or prospects, locations, secrets. Where raw data sits
   and whether it's kept out of git. Any cleaning tool and what it misses. Whether any data may
   fall under an NDA or customer agreement. Public benchmarks that fit, **from the local catalog
   only, never a web search**: once the task types from subagent 3 are known, run
   `aot-evals benchmarks --workload TAG --task "<task type>" ...` (one `--task` per task type;
   `aot-evals benchmarks` alone lists the workload tags) and keep the top fits with the reason
   each might fit, what to borrow from it (grading design, case template, user simulator,
   sandbox design, baseline number) and its caveats. Say which of the agent's task types each
   one informs. The command also prints the **situations to cover**: the columns of the golden
   test case grid, each with which matched benchmark tests it. Keep that list. Then map every
   existing case file into the grid: for each task type, how many cases are plain requests and
   how many sit in each situation (a case with no situation is a plain request). Phase 2 may
   look for newer benchmarks on the web; Phase 1 does not.

Then ask these three questions about the chosen agent, in these words. Offer a suggestion
for each, drawn from the quick scan, but nothing is built until the owner answers.

1. **Why are you building tests for <agent> now?** Options: it makes mistakes I want fixed;
   I'm about to change it and don't want to break it; I want it cheaper or faster; I want to
   trust it to do more on its own.
2. **What are the goals around the agent?** In the owner's words: time saved,
   mistakes avoided, more handled, and so on.
3. **What will you be using these tests for?** Regression testing (about 10 examples per task
   type), comparing options (about 20) or full optimization (30 to 40, tests run side by
   side). Give a range for the total, since task types aren't known until discovery finishes.
   Always list these options from small to big, in this order: catch regressions, compare
   options, full optimization. Don't move the suggested one to the top; mark it "(suggested)"
   instead.

Use AskUserQuestion when available, otherwise plain text. Keep each option's description to one
plain sentence: say what the goal is, with no labels or qualifiers tacked on (not "…, as a
proof of concept"). Keep the owner's answer in their own
words, separate from your suggestion; never merge the two. Don't wait for the answers before
writing the report.

## Step 4. Write the report

When all four subagents are back, write `evals/agents/<agent-slug>/discovery.md` (create the
folders; nothing else goes there). It has two parts: a YAML front matter block that fills the
page's overview and next steps, then the markdown details.

**The front matter.** The page puts the congrats line and the AOT Evals value statement above
it; you supply what discovery found. Every value is one or two short plain sentences (inline
markdown allowed: `**bold**`, `code`, links). Use real numbers from discovery, never filler.

```yaml
---
minutes: 8                       # how long Phase 1 took
bottom_line: >-                  # 2 or 3 sentences: is it understood, and what stands in the way
  ...
stats:                           # exactly 3 numbers that matter most for this agent
  - {value: "1,004", label: past runs studied}
  - {value: "7", label: task types found}
  - {value: "25%", label: replies stop partway}
needs_you: Approve the privacy plan   # the one thing waiting on the owner; leave out if none
overview:                        # one entry per pillar, all four, these keys
  business_context:              # why it exists, who relies on it, what a wrong answer costs
    found: "**Why now:** ... **Goal:** ..."   # from the owner's three answers
    state: done                  # done | partial | risk | todo
    label: Clear                 # 1-3 words for the state, e.g. Understood, Partly there, Not safe yet
    open: ...                    # what's still open, under 12 words; "Nothing open" if none
  agent_architecture: {...}      # code, prompts, models, tools, production setup, traces
  safe_testing_env: {...}        # can runs touch real people, data or money; cost and speed
  golden_use_cases: {...}        # task types found, cases that exist, how many are needed; name the empty grid cells
grid:                            # the golden test case grid: task types (rows) by situations (columns)
  note: ...                      # one sentence on how the targets were set (optional)
  columns:                       # from the situations `aot-evals benchmarks` printed; order as printed
    - {id: unanswerable, from: CRMArena}            # `from`: the benchmark(s) that test it, or "applies to nearly every agent"
    - {id: ambiguous, from: BIRD-Interact, catches: ...}   # `catches` and `check` override the vocabulary's words
    - {id: stub, name: Oversized result, short: over the 16 KB cap, from: its own traces, catches: ..., check: ...}
                                 # one column of the agent's own is allowed, when the traces show a failure no benchmark covers
  rows:                          # one per task type, in the task type table's order
    - task_type: Look up records and numbers
      share: 27%                 # of traffic
      passed: 22%                # in the runs studied (leave out if unknown)
      cells:                     # `plain` first, then one key per column id
        plain: {have: 14, want: 14}      # have: cases that exist; want: the target
        unanswerable: {have: 0, want: 6}
        ambiguous: null          # null when the situation can't arise for this task type
next:
  path: ...                      # the recommended path, as a short headline
  why: ...                       # what it gets them, then time and cost
  steps:                         # 3 to 6, in order; owner steps first
    - {who: you, title: ..., detail: ..., when: 5 minutes}
    - {who: us, title: ..., detail: ...}   # `when` only if there's a real cost or time
  other_paths:                   # the 1 or 2 paths not recommended
    - {name: ..., why: ...}      # what it gets, and its catch, in one sentence
---
```

Use `risk` only when something could touch real people, data or money today. Link to a
section from a step with its heading as an anchor, e.g. `[Read the plan](#safe-testing-environment)`.

**Setting the grid's targets.** Start flat: the cases per task type the owner's third answer
implies (about 10, 20 or 30 to 40), the same for every task type. Then weight it, and say in the
grid's `note` how. A flat target sends most new cases to the rarest task types, which is right
when those are also the ones that can send, delete or change what can't be undone (worth), and
wrong when they are harmless. So give a task type more than the flat number when its worth is
high or its share of traffic is large, and fewer when both are low; never below 10 for a task
type that can do something irreversible. About a third of each task type's cases carry a
situation; split that third by the risks the traffic showed (a situation seen in many failures
gets more), and give every column at least a few cases in the task types where it can arise.
Universal situations (marked `*` by `aot-evals benchmarks`) get a column always; the others
only when a matched benchmark or the traffic says they apply here. The empty cells are the
finding: say in the pillar's `found` how many columns have no cases at all, and in the
`open` line where the new cases go. Where that differs from where the agent fails most, say
so in the markdown: a cell can be empty because nobody wrote cases there, not because the
agent fails there.

**The markdown.** The first line is the title: what the agent is, in plain words, with its code
name in brackets, e.g. `# Meeting scheduler (cal-bot)`. Not "<name>: discovery report"; the page
header already says it's the discovery report. No opening paragraph: the page writes the
congrats. Then these sections, in this order, with these exact headings (the page numbers the
four pillars and puts the last two after the next steps):

1. **Business context.** The Goals table first: the three questions above, plus one row for its
   limits ("What it must never do without asking: found in its instructions; confirm or
   change"), with columns Question, Your answer, Evidence. "Your answer" is the owner's answer in
   their words. If one isn't answered yet, write "Waiting for you" and the suggestion after it
   ("Suggested: …"). Never ask about limits as a question; they come from discovery. Don't call
   these "required" or "no default", and don't use a "Suggested answer" column here. Then
   **What it does**, **Volume and cost**, **Biggest risk** and **Keep in mind**, each a short
   bold-led paragraph.
2. **Agent architecture.** How it's built; the model; where its instructions live; where they
   disagree; memory between runs; guard rails and what enforces each; dated history; stability.
   Then `### What's around the agent`: tools and side effects (what testing needs for each:
   exists or to build); records of past runs; gaps that affect testing.
3. **Safe testing environment.** The test space (what exists, what ran, gaps to close in order); private
   data found (counts only); the cleaning tool and what it misses; a proposed privacy plan that
   needs a yes.
4. **Golden test cases.** Each job as a table: what starts it, a good result, its limits, recent
   runs, in scope or not; then where the instructions and the traffic disagree. The task types
   (aim for 7; what people ask for, never a situation such as "safety" or "multi-turn") with
   share, risk and how each is checked (code first; an AI grader only for judgement calls); the
   checks that run on every test. Where examples come from per task type; size and the cost and
   time of a full pass. Then **Public benchmarks that fit**, a table from the catalog matches:
   Benchmark, Which of our task types it informs, What to borrow, Which situations it adds,
   Caveats. Public benchmarks are a source of grading designs, case templates and situations,
   never of cases. The page draws the grid from the front matter at the end of this section, so
   don't write it out as a table here; one sentence may point at it.
5. **Questions for you.** At most five, as a table: Question, Suggested answer, If no reply.
   Anything touching private data waits for a yes; mark questions waiting on the owner with ⏳.
6. **How this run went.** Time taken per step, and anything that should change. Then sources.

Then render and open it:

```bash
aot-evals discovery-page evals/agents/<agent-slug>/discovery.md --agent "<agent name>" --open
```

## Step 5. Hand off

Reply in a few lines: where the report is, which required questions are still open, and the
next step. Phase 2 starts only once the three required questions are answered and the privacy
plan has a yes. Then load `status`.
