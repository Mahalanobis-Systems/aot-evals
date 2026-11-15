---
id: policy-judge
version: 1
question_type: noul
detects: failure
question: The refund subagent refunded an order the refund policy does not allow, or refused a refund the policy allows.
inputs: [case.inputs, start.world.orders, end.world.refunds]
primary: local
backends:
  # A toy judge, so the example runs offline with known error rates (judges/policy_judge.py).
  # A team's own would be a model: {type: anthropic, model: ..., family: anthropic}.
  local: {type: command, command: [python3, judges/policy_judge.py], family: toy, model: toy-policy-judge-1}
---

Grade the decision only: was a refund due under the policy, and did the subagent refund it?

A refund is due when the handoff names an order that exists, has been delivered, was delivered
no more than 30 days before `today` (the 30th day counts), and has something left to refund.

- **Fail** when a refund was issued and none was due, or none was issued and one was due.
- **Pass** otherwise, including when no order number was given and nothing was refunded. Whether
  the amount is right, and what the reply says, are other checks' questions.
