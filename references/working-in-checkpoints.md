# Working in checkpoints

`aot-evals` below means the plugin's own CLI, `"${CLAUDE_PLUGIN_ROOT}/bin/aot-evals"`. Call it by
that full path: a bare `aot-evals` on PATH can be an older install.

Every aot-evals skill paces its work the same way. The person follows it in a browser, not the
terminal: `evals/agents/<agent>/journal/activity.html` shows everything done so far and reloads
itself. A **checkpoint** is a point where a piece of work is done, or needs the owner. Work so the
activity page tells the story, and stop wherever the person should steer.

1. **Open the activity page once per session**: `aot-evals activity --open`. Tell the person
   the path, and that the page updates itself.
2. **Log as you go.** CLI commands log themselves. Log everything else in one line before you
   do it (`aot-evals log "Reading agent/ to find every model call site"`). Log what you learn
   with `--kind finding --detail "<evidence>"`. Log each decision with `--kind decision --by
   <name|claude>`, saying whether it is confirmed or inferred. A decision about an eval's decision
   rule goes on that eval (`aot-evals --eval <id> log --kind decision "why"`): it records the spec's
   hash, so a comparison can show the rule came before the results.
3. **Save questions for the checkpoint.** Ask in the terminal only when you can't go on without
   the answer.
4. **Checkpoint, then stop.** When a piece of work is done, or needs the owner (a draft to
   confirm, a number to choose, a cost to approve):

   - write the summary in the conversation: what you did and found, in two or three short
     paragraphs or "- " bullets, in plain words, naming the numbers and where they came from;
   - log it as a question, so the activity page shows the "waiting for you" banner:

     ```bash
     aot-evals log "<what this checkpoint is about>: <the question>" --kind question --detail "<the headline>"
     ```

   End your turn with three lines: where to look (a file, a page, the activity log), the headline,
   and what you need from the person. **Don't start the next step until they reply**, even when
   you asked nothing.

## Words for the person

- Say who the step is for (the owner, engineering, or the people who know what good looks like)
  and what it does in plain words. The four parts (estimand, sampling design, measurement model,
  decision rule) can be named once explained; rule numbers, gate ids and field paths live in
  `docs/method.md` for whoever wants them.
- **Speak in consequences.** Do the statistics yourself and say what they mean for the next step:
  "about 40 more cases would show it", "this judge needs about 80 more labeled failures before its
  scores count". Point to `docs/estimators.md` or `docs/statistics.md` only when someone asks how.
- Use the terms as `docs/estimators.md#terms` defines them: a **use case** is a kind of request, a
  **pool** is the quality set or the bug-finding set, **coverage** is the list the bug-finding set
  must reach, the **plan** is how many cases each use case needs, and a grader's errors are its
  **catch rate** and **clean pass rate**.
- Say what a thing is, not its label: "three booking bugs found on Mar 3", not "BK-101 to BK-103".
- Lead with the point. Numbers with units and their interval. Mark anything inferred as a best guess.
- Never print private content (names, addresses, message text, secrets): counts and kinds only.

## Rules every skill holds the team to

1. **Cases come from real traffic and real failures**, not public benchmarks. The quality set is
   drawn at random from a frame of real requests (`aot-evals draw`), never picked by hand.
2. **Two pools.** The bug-finding set is hard and rare cases picked to find failures; the quality
   set is the random draw. Only the quality set's rate is called quality.
3. **Grade the end state with code first.** Use a judge only where code can't decide, and count it
   only once its catch and clean pass rates are measured. Never grade the agent's own report of
   success.
4. **The headline is θ̂ under the owner's stated weights**, with the per-use-case table beside it.
   Correctness and cost are reported side by side, never folded into one score.
5. **Every number carries n, k and an interval**, or says why it can't. Unknown is null with the
   reason, never 0.
6. **Decide by the rule written down first.** The test, margin or bar, α and power are in the spec
   before a candidate runs; "no significant difference" is never "no worse".
7. **Raw traces and PII never enter git.** Exports live in the agent folder's `data/`, which is
   ignored. Only scrubbed, reviewed cases are committed.
8. **Record each claim as confirmed or inferred, with its source.** When config and traces
   disagree, trust the traces.
