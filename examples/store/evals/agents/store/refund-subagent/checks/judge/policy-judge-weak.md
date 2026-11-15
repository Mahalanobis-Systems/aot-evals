---
id: policy-judge-weak
version: 1
question_type: noul
detects: failure
question: The refund subagent refunded an order the refund policy does not allow, or refused a refund the policy allows.
inputs: [case.inputs, start.world.orders, end.world.refunds]
primary: local
backends:
  # A toy judge, so the example runs offline with known error rates (judges/policy_judge.py).
  # A team's own would be a model: {type: anthropic, model: ..., family: anthropic}.
  local: {type: command, command: [python3, judges/policy_judge.py, --weak], family: toy, model: toy-policy-judge-mini}
---

A cheaper judge on the same question, kept to show the floor refusing it: at
catch 0.80 and clean 0.90 it costs about 7.5 times the cases a code check would at a 3% failure
rate, however many labels it has.

Grade the decision only: was a refund due under the policy, and did the subagent refund it?

A refund is due when the handoff names an order that exists, has been delivered, was delivered
no more than 30 days before `today` (the 30th day counts), and has something left to refund.

- **Fail** when a refund was issued and none was due, or none was issued and one was due.
- **Pass** otherwise, including when no order number was given and nothing was refunded. Whether
  the amount is right, and what the reply says, are other checks' questions.
