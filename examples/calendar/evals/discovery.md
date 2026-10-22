---
minutes: 2
bottom_line: >-
  The agent is understood: one command, one file it writes, 20 past runs and 10 reviewed cases. Nothing stands in the way of a fair test. The cases cover the two everyday jobs and none of the situations that trip agents up, so the grid below is mostly empty.
stats:
  - {value: "20", label: past runs studied}
  - {value: "2", label: task types found}
  - {value: "10", label: cases, all plain requests}
overview:
  business_context:
    found: "**Why now:** a toy to try aot-evals on. **Goal:** book exactly the meeting asked for, and touch nothing else."
    state: done
    label: Clear
    open: Nothing open
  agent_architecture:
    found: One Python script (`agent/agent.py`) with one model call site, run from one command. It reads the request and writes the calendar file (`world.json`).
    state: done
    label: Understood
    open: Nothing open
  safe_testing_env:
    found: The calendar is a file. The `seed` hook writes it before each case and the `observe` hook reads it back after, so nothing outside the test folder is touched.
    state: done
    label: Safe
    open: Nothing open
  golden_use_cases:
    found: "2 task types. 10 cases exist, all plain requests. None of the 5 situations has a case yet: no past dates, no vague requests, no requests to move a meeting, no multi-turn, no failed write."
    state: partial
    label: Halfway there
    open: 7 more cases, one per empty cell
grid:
  note: Targets are for a toy. A real suite would want about 10 per task type for regression tests; here each situation gets one case where it can arise.
  columns:
    - {id: unanswerable, from: applies to nearly every agent, catches: Booking a meeting on a date that doesn't exist, or in the past}
    - {id: ambiguous, from: applies to nearly every agent, catches: "Picking a time when the request gave none (\"sometime next week\")"}
    - {id: forbidden, from: applies to nearly every agent, catches: Moving or deleting an existing event, which the spec forbids}
    - {id: multi-turn, from: applies to nearly every agent, catches: Booking the time first given after the person changed it}
    - {id: tool-error, from: applies to nearly every agent, catches: Claiming the meeting is booked when the calendar file couldn't be written}
  rows:
    - task_type: Schedule a meeting
      share: 60%
      passed: 100%
      cells:
        plain: {have: 7, want: 7}
        unanswerable: {have: 0, want: 1}
        ambiguous: {have: 0, want: 1}
        forbidden: {have: 0, want: 1}
        multi-turn: {have: 0, want: 1}
        tool-error: {have: 0, want: 1}
    - task_type: Leave the calendar alone
      share: 40%
      passed: 100%
      cells:
        plain: {have: 3, want: 3}
        unanswerable: null
        ambiguous: {have: 0, want: 1}
        forbidden: {have: 0, want: 1}
        multi-turn: null
        tool-error: null
next:
  path: Run the suite as it is, then fill the empty cells
  why: >-
    The demo runs a baseline and a candidate on the 10 cases in under a minute, with no model and no network. The seven missing cases would make it a suite that catches the failures a real scheduler has.
  steps:
    - {who: us, title: Run the baseline and the candidate, detail: "3 tries per case. The candidate books two meetings at the wrong time, and the comparison should say so.", when: under a minute}
    - {who: us, title: Write the seven missing cases, detail: "One per empty cell: a past date, a vague time, a request to move a meeting, a changed time over two turns, a calendar file that can't be written, and two for leaving the calendar alone."}
    - {who: you, title: Try it on your own agent, detail: "Run `/aot-evals:start` in your agent's repository.", when: 5 minutes}
  other_paths:
    - {name: Start from a public benchmark, why: "Gaia2's calendar tasks fit the shape, but they test a far bigger assistant than this toy."}
---
# Meeting scheduler (toy-calendar)

## Business context

| Question | Your answer | Evidence |
|---|---|---|
| Why are you building tests for it now? | To try aot-evals on a toy | `README.md` |
| What are the goals around the agent? | Book exactly the meeting asked for; touch nothing else | `docs/product-spec.md` |
| What will you be using these tests for? | Catch regressions (about 10 examples per task type) | `README.md` |
| What it must never do without asking | Found in its spec; confirm or change: change or delete an existing event | `docs/product-spec.md` |

**What it does.** It books meetings from short requests like "Book 'Sync with Ana' on 2026-10-05 at 14:00", and otherwise leaves the calendar alone.

**Volume and cost.** 20 past runs in the export (`traces.jsonl`), 12 of them booking requests. No model is called, so a run costs nothing and takes under a second.

**Biggest risk.** Booking at the wrong time, or changing an event it wasn't asked about.

**Keep in mind.** It is a toy. The point is to see the loop run end to end, not to learn anything about scheduling.

## Agent architecture

**How it's built.** One script, `agent/agent.py`, which speaks the agent contract: a request in, a reply and the calendar out. `AGENT_VARIANT` switches it between behaviours the self-tests need (good, claims success without acting, flaky, slow).

**The model.** None. The toy parses the request with code.

**Where its instructions live.** In the script. Nothing outside git.

**Memory between runs.** None.

**Guard rails and what enforces each.**
| Guard rail | Enforced by |
|---|---|
| Never change or delete an existing event | The spec only. The agent could, and a case should check it doesn't. |

### What's around the agent

| Tool or service | What it does | Undo? | Testing needs |
|---|---|---|---|
| The calendar file (`world.json`) | Holds the events | Yes, the `seed` hook rewrites it | Exists |

**Records of past runs.** `traces.jsonl`, 20 runs, with the request and what the agent wrote.

**Gaps that affect testing.** None.

## Safe testing environment

**The test space.** Each case starts by writing the calendar (`seed.py`) and ends by reading it back (`observe.py`). The checks compare the two. Nothing else is touched.

**Private data found.** None: made-up names and titles only.

**Proposed privacy plan.** Nothing needed.

## Golden test cases

**Jobs.**
| Job | What starts it | A good result | Limits | Recent runs | In scope |
|---|---|---|---|---|---|
| Schedule a meeting | A request with a title, date and time | Exactly one new event, as asked | Never touch other events | 12 | Yes |
| Leave the calendar alone | Any other message | Nothing changed | | 8 | Yes |

**Task types** (from the 20 past runs).
| Task type | Share | Passed | Risk | How it's checked |
|---|---|---|---|---|
| Schedule a meeting | 60% | 100% | Wrong time; a second event | Code: the calendar before and after |
| Leave the calendar alone | 40% | 100% | A booking from nothing | Code: the calendar unchanged |

**Checks on every test.**
- Nothing outside the case's scope changed.
- The reply finished.

**Where examples come from.** The 10 cases were written from the export and reviewed. 7 book a meeting (5 for finding errors, 2 for estimating quality) and 3 leave the calendar alone.

**Size.** 10 today. The grid below shows the seven cases a fuller toy would add.

**Public benchmarks that fit** (from the local catalog).

| Benchmark | Which of our task types it informs | What to borrow | Which situations it adds | Caveats |
|---|---|---|---|---|
| Gaia2 | Schedule a meeting | Checking write actions against the events that should exist; its ambiguity and time splits | none | Tests a far bigger assistant |
| AgentDojo | Both | Pairing a user task with an injected instruction in the content it reads | injected instruction | This toy reads no outside content, so the column isn't drawn |

Public benchmarks are a source of grading designs, case templates and situations, never of cases.

## Questions for you

| Question | Suggested answer | If no reply |
|---|---|---|
| Keep "never change an existing event" as the one hard limit? | Yes | Use it as written |

## How this run went

A toy, so the whole of Phase 1 took about 2 minutes: scan, three questions, report. Nothing should change.

**Sources:** `README.md`, `docs/product-spec.md`, `agent/agent.py`, `traces.jsonl`, `evals/cases/`.
