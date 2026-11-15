# Example: the online store's support agent

The agent from [the twelve problems](../../docs/problems.md), small enough to run in a minute and
complete enough to show every part of an eval ([v2-design §9](../../docs/v2-design.md#9-the-online-store-example)).
`aot-evals demo` copies this folder into a new repository and runs it; the test suite builds its
fixtures from it.

- `agent/store.py`: the orchestrator. It answers order-status, return and address requests with
  the order tools and hands every refund to the refund subagent. `agent/refunds.py`: the refund
  subagent, a program of its own with its own prompt and model. Both speak the
  [agent contract](../../references/agent-contract.md); nothing calls a model or a network service.
- `evals/agents/store/env/`: the sandbox. Fakes for the order system and payments in one JSON
  file, and the `seed` and `observe` hooks that set it up and read it back.
- `traces.jsonl`: the October trace export. Each refund trace records its handoff to the subagent
  (`handoffs: [{to, use_case, order_template, trigger, inputs, ...}]`), which is what
  `aot-evals --eval refund-subagent handoffs` extracts the subagent's frame from.
- `evals/agents/store/end-to-end/`: the whole agent. Four use cases with costs ($1, $5, $20, $50),
  cost weights, a non-inferiority rule with a refund gate, code checks only.
- `evals/agents/store/refund-subagent/`: the subagent on its own, drawn from its handoffs. Its
  policy breaks are graded by `policy-judge` (catch 0.95, clean pass 0.99 on 100 failure and 500
  pass labels, enough to clear `max_inflation: 2.0` at a 3% failure rate); `policy-judge-weak`
  (0.80, 0.90) is kept as a diagnostic to show the floor refusing it. A threshold rule (under 5%),
  and the end-to-end eval must show no regression too (rule 27).
- Each eval's `cases/`: a quality set drawn from the export with `aot-evals draw` (`draw.json` is
  the log) and a bug-finding set (`bf-*`) written from templates, with the policy corners: the 30th
  and 31st day, partial refunds, gift cards, no order number.
- `docs/`: the help center topics and the refund policy the coverage lists come from.
- `judges/policy_judge.py`: a toy command judge that makes a judge's mistakes on purpose, at known
  rates, so the example runs offline.
- `generate.py`: rewrites the export, the bug-finding cases and the judges' labels (seeded).

`AGENT_VARIANT` switches the behaviors the problems and the self-tests need: `refund-bug` (problem
1), `declines-missing-order` (problem 2), `flaky` (problem 8) and `cheap` (problem 11), plus `liar`,
`costly`, `slow`, `silent` and `peek`; see the docstrings in `agent/store.py` and `agent/refunds.py`.

The quality sets are deliberately small, so the decisions come out `insufficient` with the number
of cases that would decide them: that is the honest answer at this size (problem 9).
