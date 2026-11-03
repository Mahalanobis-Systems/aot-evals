# Working in checkpoints

`aot-evals` below means the plugin's own CLI, `"${CLAUDE_PLUGIN_ROOT}/bin/aot-evals"`. Call it by
that full path: a bare `aot-evals` on PATH can be an older install.

Every aot-evals skill paces its work the same way. The person follows it in a browser, not the
terminal: `<suite>/journal/activity.html` shows everything done so far and reloads itself, and
each checkpoint page shows what the work has produced. Work so those pages tell the story, and
stop wherever the person should steer.

1. **Open the activity page once per session**: `aot-evals activity --open`. Tell the person
   the path, and that the page updates itself.
2. **Log as you go.** CLI commands log themselves. Log everything else in one line before you
   do it (`aot-evals log "Reading agent/ to find every model call site"`). Log what you learn
   with `--kind finding --detail "<evidence>"`. Log each decision with `--kind decision --by
   <name|claude>`, saying whether it is confirmed or inferred.
3. **Save questions for the checkpoint.** Ask in the terminal only when you can't go on without
   the answer. Log such a question first, with `--kind question`.
4. **Checkpoint, then stop.** Write a checkpoint when a piece of work is done, or when it needs
   the owner: a draft to confirm, a number to choose, a cost to approve.

   ```bash
   aot-evals checkpoint --open --title "<what this page is about>" --ask "<question>" --summary-file - <<'MD'
   What you did and found, in two or three short paragraphs or "- " bullets. Plain words: the
   reader may not know the method. Name the numbers and where they came from.
   MD
   ```

   End your turn with three lines: the page's path, the headline, and what you need from the
   person. **Don't start the next step until they reply**, even when you asked nothing.

## Words for the person

- Say the phase (Assess, Build, Judge) and what the step does, never a step code (C0–C19), gate
  id (G1–G14) or measurement id. Those live in `docs/method.md` for whoever wants them.
- Say what a thing is, not its label: "three booking bugs found on Mar 3", not "BK-101 to BK-103".
- Lead with the point. Numbers with units. Mark anything inferred as a best guess.
- Never print private content (names, addresses, message text, secrets): counts and kinds only.

## Rules every skill holds the team to

1. **Cases come from real traffic and real failures**, not public benchmarks.
2. **Three planes, never combined:** correctness, operational cost (cost, latency, errors), and
   trust in the instruments. Never fold them into a single score.
3. **Two case sets:** one to find errors (hard and rare cases), one to estimate quality (sampled by
   traffic share). Only the second may be called "quality".
4. **Grade the end state with code first.** Use a judge only where code can't decide, and only once
   it is calibrated. Never grade the agent's own report of success.
5. **Every number carries n, k and an interval**, or says why it can't. When a number can't be
   defended, it is greyed with the reason, never shown silently.
6. **Raw traces and PII never enter git.** Exports live in `<suite>/data/`, which is ignored. Only
   scrubbed, reviewed cases are committed.
7. **Record each claim as confirmed or inferred, with its source.** When config and traces
   disagree, trust the traces.
