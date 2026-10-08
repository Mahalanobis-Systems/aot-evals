---
name: build
description: Commands C5-C8 of aot-evals - size the error-finding and quality-estimate case sets with the arithmetic printed, author frozen and scrubbed cases from real traces, screen each case (human read, reference passes, do-nothing fails, no check trusts the agent's claim), and implement binary code checks and judge specs. Use when status reports C5-C8 unmet, or when writing eval cases or checks for an agent.
user-invocable: false
---

# build: how many cases, which ones, and how each is checked

CLI: `"${CLAUDE_PLUGIN_ROOT}/bin/aot-evals"` (on PATH as `aot-evals`). Templates:
`${CLAUDE_PLUGIN_ROOT}/templates/`.

Paths below start at `<suite>/`, this agent's suite: `evals/agents/<agent>/`, beside its discovery report
(a one-agent repository may keep it in `evals/` itself). When the repository has several agents, pass
`--agent <agent>` to every `aot-evals` command.

## Work in checkpoints

The person follows the work in a browser, not the terminal: `<suite>/journal/activity.html` shows
everything done so far and reloads itself, and each checkpoint page shows what the work has
produced. Work so those pages tell the story, and stop wherever the person should steer.

1. **Open the activity page once per session**: `aot-evals activity --open`. Tell the person
   the path, and that the page updates itself.
2. **Log as you go.** CLI commands log themselves. Log everything else in one line before you
   do it (`aot-evals log "Reading agent/ to find every model call site" --gate C1`). Log what
   you learn with `--kind finding --detail "<evidence>"`. Log each decision with `--kind
   decision --by <name|claude>`, saying whether it is confirmed or inferred.
3. **Save questions for the checkpoint.** Ask in the terminal only when you cannot go on without
   the answer. Log such a question first, with `--kind question`.
4. **Checkpoint, then stop.** Write a checkpoint when a gate clears, or when the work needs the
   owner: a draft to confirm, a number to choose, a cost to approve.

   ```bash
   aot-evals checkpoint --gate C3 --open --ask "<question>" --ask "<question>" --summary-file - <<'EOF'
   What you did and found, in two or three short paragraphs or "- " bullets. Plain words: the
   reader may not know the method. Name the numbers and where they came from.
   EOF
   ```

   End your turn with three lines: the page's path, the headline, and what you need from the
   person. **Don't start the next step until they reply**, even when you asked nothing.

Checkpoints in this skill:
- **C5**: the case budget and the minimum detectable effect, before any case is written.
- **C6**: after the first few cases of each category, so the owner confirms the expected end
  states before you write the rest. Then after the remaining cases.
- **C7**: the screen results, with the list of cases waiting for a human read.
- **C8**: the checks, and what comes next (judges or the baseline).

## C5 allocate

```bash
aot-evals allocate                    # print the arithmetic
aot-evals allocate --halfwidth 0.05 --write
aot-evals allocate --write --mark-short scheduled --reason "authoring from the Q3 export in C6"
```

The two sets are sized by different arithmetic (docs/method.md §2.3):
- **Error-finding set:** flat, ≥10 per category and 3 per simple category, whatever the category's
  share. Rare categories are where the worth usually is. Its pass rate is never called quality.
- **Quality-estimate set:** proportional to observed share, sized by the 95% interval the owner
  needs on the weighted pass rate (±5 points ≈ 385 cases at p = 0.5).

Show the user the minimum detectable effect (M7) before anything runs. If the MDE is wider than
any change they care about, say so now.

`allocation.yaml` records each (category × set) cell. When traffic cannot fill a cell, have the
owner mark it `scheduled` (synthetic variants, or cases chosen by a selector: uncertainty T1 or
committee disagreement T2, marked `synthetic: true`) or `out_of_scope`, with a reason either way.
Those marks survive re-allocation. **Gate:** every cell is filled, scheduled or out of scope with
a reason.

## C6 author → `<suite>/cases/<category>/<case-id>.json`

Start from `${CLAUDE_PLUGIN_ROOT}/templates/case.json`. Each case freezes:
- `trigger`;
- `inputs`;
- `start_state`: what `seed` writes;
- scripted `followups`;
- `expected_end_state`: `{"world": …, "output": …}`, confirmed by a person;
- `set` (no default);
- `category`, matching its directory;
- `failure_modes`;
- `taxonomy_entries`, which feeds coverage;
- `provenance`: source, the export id, trace_ref, `synthetic`, the agent version that produced the
  trace.

- **Cases come from reviewed real traces** (process steps 9–10). The confirmed review becomes the
  expected end state. Never ship an uncorrected model draft as ground truth.
- **Prefer self-verifying pairs** where the world allows: create → fetch → assert exactly one.
- **Scrub before writing:** names to placeholders, emails to `example.com`, no tokens or keys.
  `aot-evals validate` blocks on secrets and warns on likely PII; a person still reads every case.
- **Keep the two sets disjoint:** one trace never feeds both sets.

**Gate:** every case has a set, category, failure modes, provenance, and no secrets.

## C7 screen

```bash
aot-evals screen                                  # machine screens, written into each case
aot-evals screen --read-by "Ana" --case book-001  # after Ana has read the case (repeat --case)
aot-evals screen --drop book-007 --reason "expected state ambiguous: two valid invites"
```

Per case (M22):
- the **reference passes**: checks pass on start → expected end state;
- **doing nothing fails**: checks fail on start → start. This doesn't apply when the expected end
  state equals the start state;
- a **human read** it.

The screen also replays "do nothing, but claim success". A check that passes only then is grading
the agent's report, and G10 refuses it. Expect losses: SWE-bench kept 500 of 2,294 tasks. Report
the drop rate. Unscreened cases never count toward gated numbers (G8).

**Gate:** both machine screens and the human read are recorded for every case, and every drop has
a reason.

## C8 checks

**Code checks: `<suite>/checks/code/<check-id>.py`.** Start from
`${CLAUDE_PLUGIN_ROOT}/templates/check_code.py`.

```python
def check(start, end, case) -> tuple[bool, str]:
    ...  # start/end = {"world": <observe output>, "output": <deliverable text>}
```

- Code first: diff the end state (rows, events, files, messages sent).
- **Grade against the goal, not one path.** Any action sequence that reaches the right state
  passes.
- Binary, with a short `detail` saying why. Never read the agent's claim of success.
- A check that raises is recorded as an instrument error (plane C), never as an agent failure.

**Judge checks: `<suite>/checks/judge/<check-id>.md`.** Start from
`${CLAUDE_PLUGIN_ROOT}/templates/check_judge.md`. One failure mode per judge, one binary typed
question, and only the inputs it needs. The default backend is System One (docs/method.md §5); a generative
backend must come from a different family than the agent (G4). Judges run and are recorded from
the first run, but they count toward pass rates only once they're calibrated in `calibrate`
(G3).

**Gate:** every failure mode that isn't monitor-only has at least one check file; a side-effect
code check exists; no check declares or shows reliance on the agent's report. Then
`aot-evals status`. With judge checks, go to `calibrate` next (C9–C11 do not block a baseline,
and a baseline gives you items to label). Without them, C9–C11 show `n/a`; go to `run`.
