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

Within each category, about a third of its cases carry a situation from the discovery report's
grid (`grid` in `discovery.md`'s front matter), split by the risks the traffic showed. The
grid's `want` numbers are that split; keep to them unless the owner changes the budget, and
update the grid when they do.

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
- `taxonomy_entries`, which feeds coverage; a case in a situation lists its `situation.<id>`
  entry here (a plain request lists none), and borrows that situation's case template from the
  benchmark the report names (τ-bench's init, solution and assertion shape for a write under
  policy; CRMArena's "none" answers; BIRD-Interact's ambiguous prompts);
- `provenance`: source, the export id, trace_ref, `synthetic`, the agent version that produced the
  trace;
- `requirements`: what a correct run of this case must do, in plain words, each citing a rule of
  the standard and naming the checks that decide it (below).

**Write the standard first.** `labels/standard.md` (`aot-evals init` writes a template) holds the
rules a person applies when failing a run, with the categories each applies to: every stated
fact true, lists complete or marked partial, writes right and complete, related records
connected, nothing left behind, wide changes confirmed, the turn delivers. Fit them to the agent
with the owner before writing cases; the same rules guide labelling (C9, C19).

**Then, for every case, walk the rules.** For each rule that applies to the case's category,
write the requirement it implies for this case, concretely ("lists all 28 deals over $100K, or
says it shows a part and why"; "the follow-up task is attached to the deal and to Ana"), or say
in `rules_not_applicable` why it doesn't apply. This is the step that catches what a check per
failure mode misses: E5's calibrated suite missed partial lists, unattached tasks and leftover
junk because no case said they mattered.

```json
"requirements": [
  {"id": "all-deals", "rule": "complete", "says": "lists all 28 open deals over $100K", "checks": ["lists-every-deal"]},
  {"id": "total-true", "rule": "facts-true", "says": "the stated total is $6.593M", "checks": ["answer-grounded"]}
],
"rules_not_applicable": {"connected": "read-only: nothing to connect"}
```

- **Cases come from reviewed real traces** (process steps 9–10). The confirmed review becomes the
  expected end state. Never ship an uncorrected model draft as ground truth.
- **Prefer self-verifying pairs** where the world allows: create → fetch → assert exactly one.
- **Scrub before writing:** names to placeholders, emails to `example.com`, no tokens or keys.
  `aot-evals validate` blocks on secrets and warns on likely PII; a person still reads every case.
- **Keep the two sets disjoint:** one trace never feeds both sets.

- **Derive expected values from the start state** wherever you can (a count, a total, a list of
  ids computed from the seeded records), rather than typing them in. A typed-in expected answer
  is where E5's suite was wrong (a count of 55 for a true 87; an expected title with a stray
  asterisk).

**Gate:** every case has a set, category, failure modes, provenance, requirements covering every
rule that applies to it, and no secrets; the standard exists.

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
the agent's report, and G10 refuses it.

When a case has a reference answer (`expected_end_state.output`), write two or three other correct
wordings of it in `expected_end_state.output_variants` (other number formats: "$1.413M",
"1,413,000"; other phrasings; another order), and confirm them with the owner like the reference.
The screen then also checks:
- **paraphrases pass**: every variant passes every check. A check bound to one wording fails
  correct answers in real runs (in E5, 6 of a suite's 13 false alarms);
- **the liar fails**: the reference answer with nothing changed fails, when a change is expected;
- **a wrong number fails**: the reference answer with every number changed fails. Reported, not
  blocking: when it passes, nothing checks the answer's numbers. Add a check for the case's
  `facts-true` requirement. Expect losses: SWE-bench kept 500 of 2,294 tasks. Report
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

**Every requirement is decided by a check that runs on the case** (its failure mode listed in the
case, the check listed under that failure mode), or says why it is `unchecked`. An unchecked
requirement is allowed and stays visible; C19's triage will show what it costs. `aot-evals
status` prints, per rule, how many cases it applies to, cite it, and check it: a rule cited
everywhere and checked in a few cases is the gap to close first.

**Check every fact an answer states.** A false number inside an otherwise right answer (micros
read as dollars, a wrong percentage, a wrong date) was the one failure no arm of E5 caught. For
answers in prose, give each case a `facts-true` requirement decided by a grounding check: code
that extracts each number, total or name from the answer and compares it with values computed
from the start state, or a judge given the answer and the full records it should rest on, asked
whether every stated fact is supported. One judge spec can serve every such case; its inputs
must include the records, not a summary of them.

**Gate:** every failure mode that isn't monitor-only has at least one check file; a side-effect
code check exists; no check declares or shows reliance on the agent's report; every requirement
names a check that runs on its case or says why it is unchecked. Then
`aot-evals status`. With judge checks, go to `calibrate` next (C9–C11 do not block a baseline,
and a baseline gives you items to label). Without them, C9–C11 show `n/a`; go to `run`.
