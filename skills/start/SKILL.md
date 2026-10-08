---
name: start
description: The one command to remember for aot-evals. Starts Phase 1 (discover) when this repository has no discovery report yet (evals/agents/<agent>/discovery.md); otherwise says where the evals stand and carries on with Phase 2 (status). Use for "start aot-evals", "set up evals", "build evals for my agent", "where are we with our evals", or "what's next".
---

# start

The single entry point. Decide which phase the team is in, then hand over.

1. Look for `evals/agents/*/discovery.md` in this repository.
2. **None found:** load the `discover` skill and follow it. That is Phase 1: the banner, which
   agent to test, three questions, and the discovery report.
3. **One or more found:** load the `status` skill and follow it. That is Phase 2: it reads
   where the evals stand, says so in plain words, and routes to the next step.

Do nothing else here. The other commands (`discover`, `status`, `scope`, `build`,
`calibrate`, `run`, `report`) stay available for anyone who wants a specific step.
