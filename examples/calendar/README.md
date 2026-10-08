# Example: a toy calendar agent

A small agent with everything aot-evals needs, used by `aot-evals demo` and by the test suite:

- `agent/`: the agent (`agent.py`, which speaks the [agent contract](../../references/agent-contract.md)),
  a `seed.py` hook that sets up the calendar, and an `observe.py` hook that prints it.
- `docs/product-spec.md`: the document the coverage list (`taxonomy.yaml`) comes from.
- `traces.jsonl`: an exported trace file, as you would import from your observability stack.
- `evals/`: a reviewed suite: categories, failure modes, budgets, cases and code checks.

`AGENT_VARIANT` switches the agent between behaviours the self-tests need (a good agent, one
that claims success without acting, a flaky one, a slow one, ...); see the docstring in
`agent/agent.py`. To try it: `aot-evals demo` copies this folder into a new repository and runs
a baseline, a candidate and a comparison.
