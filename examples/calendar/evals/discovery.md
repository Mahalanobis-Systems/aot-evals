# Meeting scheduler (toy-calendar)

This is the example's discovery report: what Phase 1 would have written for this toy agent. It
is short because the agent is.

## Where things stand

A toy agent that books meetings on a calendar when asked, and otherwise leaves it alone.

- Two jobs: book a requested meeting, and do nothing when there is nothing to book.
- It runs from one command and writes to one file (`world.json`), so a safe test space is easy.
- The export has 20 past runs; most are booking requests.

**Phase 1 · Understanding the agent: done**

| | Item | What we found | What's open |
|---|---|---|---|
| ✓ | The agent | `agent/agent.py`, one model call site | — |
| ✓ | Your goals | Book exactly the meeting asked for; touch nothing else | — |
| ✓ | What it does | Two jobs, from the product spec | — |
| ✓ | How it works | Reads the request, writes the calendar file | — |
| ✓ | What it touches | Only the calendar | — |
| ✓ | How to test it | Seed the calendar, run, read it back | — |
| ✓ | Test data | 20 exported runs | — |

**Phase 2 · Building the tests: done**

| | Item | Ready | Still to do |
|---|---|---|---|
| ✓ | Safe test space | `seed` and `observe` hooks | — |
| ✓ | Tests | 10 cases across both jobs | More cases for real use |
| ✓ | Checks | Meeting booked; nothing else changed | — |
| ✓ | Run and report | Baseline and a comparison | — |

✓ done · ◐ partly done · ○ not started · ⏳ waiting for you

**Next:** read the checkpoint page. **Then:** try aot-evals on your own agent.

## Goals

| Question | Your answer | Evidence |
|---|---|---|
| What must it get right? | The meeting it was asked for, at the right time | product spec |
| What does a failure cost? | A missed or wrong meeting | product spec |
| What must it never do without asking? | Change or delete an existing event | product spec |

## Summary

It books meetings from short requests. The biggest risk is booking at the wrong time, or
changing an event it wasn't asked about. Recommended path: state-diff checks on the calendar,
no judge needed.
