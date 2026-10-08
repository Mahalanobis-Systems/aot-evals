---
name: discover
description: Phase 1 of aot-evals, usually reached through start. Runs when a team wants evals for an agent and no discovery report exists yet (evals/agents/<agent>/discovery.md), about 5 minutes. Shows the AOT EVALS banner and the two phases, scans the repository for every agent (each skill of a multi-skill system counts as its own agent), asks which agent to test, asks three questions about it, runs discovery in parallel, and writes a plain-English discovery report: an overview of the four things good evals rest on, the details, and next steps. Use for "set up evals", "build evals for my agent", "start aot-evals", or when status finds no discovery report.
---

# discover: Phase 1

You run Phase 1 of building evals for **one** agent: discovery and a first report, in about 5
minutes of work. Phase 2 (building the evals) comes later and takes an afternoon.

CLI: `"${CLAUDE_PLUGIN_ROOT}/bin/aot-evals"` (also `aot-evals` on PATH while the plugin is on).

## Rules for everything you write to the owner

- Plain English a ninth grader can follow. No step codes (no C0–C18, gate ids, "Part 3",
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
   more) by what the agent should do; share, cost and latency (median, 90th percentile) for
   each. Health of each timer: last success, recent failures. How often the owner corrected it.
4. **Test data and privacy.** Where examples can come from (real runs, cleaned examples,
   labels, earlier drafts and whether the owner confirmed them). Kinds of private data present,
   with counts: people, family, customers or prospects, locations, secrets. Where raw data sits
   and whether it's kept out of git. Any cleaning tool and what it misses. Whether any data may
   fall under an NDA or customer agreement. Public benchmarks that fit (names, marked unchecked)
   and whether they're worth running.

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
  golden_use_cases: {...}        # task types found, cases that exist, how many are needed
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
   (aim for 7) with share, risk and how each is checked (code first; an AI grader only for
   judgement calls); the checks that run on every test. Where examples come from per task type;
   size and the cost and time of a full pass; public benchmarks.
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
