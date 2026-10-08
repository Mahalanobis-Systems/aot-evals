# Principles

1. **Evals come from the agent's real traffic and real failures, not from
   generic benchmarks.** Public benchmarks supply grading designs; your
   traces supply the test cases.
2. **Understand before measuring.** Inventory, infrastructure, volume and
   usage come first. You can't pick what to check until you know what the
   agent is asked to do and where it goes wrong.
3. **Grade outcomes, with code first.** Check what the agent changed in the
   world (records, rows, events, posts). Use an LLM judge only for what code
   can't decide, and calibrate it against human labels.
4. **Cheap sources first, raw transcripts second.** Metadata, logs, commit
   history and incident ledgers characterize most of the picture without
   touching sensitive content. Pull full transcripts once you know what to
   look for.
5. **Keep sensitive data out of version control.** Raw traces stay local and
   ignored; only reviewed, scrubbed cases get committed.
6. **Record confirmed vs inferred** for every claim, with a source. Config
   often disagrees with runtime; trust what the traces show.
