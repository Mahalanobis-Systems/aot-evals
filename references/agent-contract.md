# Wiring an agent to `aot-evals`

The agent runs as a command. Framework, language and model provider don't matter.

Configure it under `invoke:` in the suite's `agent.yaml` (`evals/agents/<agent>/agent.yaml`).

## stdin: the case

The command receives one JSON object on stdin, then stdin closes:

```json
{
  "question": "Can we do Thursday 3pm instead? Please send the invite.",
  "context": [],
  "model": "",
  "timeout": 120,
  "case_id": "confirm-001",
  "trial": "0",
  "attempt": 0,
  "trigger": {"type": "message", "text": "Can we do Thursday 3pm instead? Please send the invite."},
  "inputs": {"thread": []},
  "start_state": {"events": []},
  "followups": []
}
```

`question` is the case's `trigger.text`. The rest carry
the remaining fields of the case. An agent that already has a CLI can use `{question}`, `{model}`,
`{timeout}`, `{case_id}` and `{trial}` placeholders in `invoke.command` and ignore stdin.

## stdout: the result

The command prints exactly one JSON object to stdout. Anything printed before it is ignored.

```json
{
  "answer": "Sent the invite for Thursday 3pm.",
  "usage": {"tokens_input": 4120, "tokens_output": 210, "tokens_cached": 3800, "cost": 0.0031,
            "tool_calls": 3, "retries": 0},
  "model_ids": {"main": "claude-sonnet-5-5", "router": "claude-haiku-4-5"},
  "trace_id": "abc123",
  "outcome": "ok"
}
```

| Field | Required | Meaning |
|---|---|---|
| `answer` | yes | The agent's deliverable text. Checks may grade it only when the output *is* the deliverable |
| `usage.cost` | no | Real USD cost as the provider reports it, including cache reads and writes. Plane B uses it for cost per success |
| `usage.tokens_input` / `tokens_output` / `tokens_cached` | no | Token counts. With `tokens_cached`, the report computes cache-hit rate (M20) |
| `usage.tool_calls`, `usage.retries` | no | Tool calls and the agent's own internal retries |
| `model_ids` | no | The model actually used per call site. Recorded in the run manifest and compared with `agent.yaml models` |
| `trace_id` | no | An id in the team's observability stack. Stored as `trace_ref`; the trace itself never is |
| `outcome` | no | `ok` (default), `timeout`, `rate_limited`, `budget_exceeded`, `provider_error`, `model_disabled`, `auth_error`, `no_output`, `cli_missing` or `unparseable`. Only `ok` is scored |
| `error` | no | A short message when `outcome` isn't `ok` |

When the process exits non-zero and prints no JSON, the attempt is recorded as `provider_error`.
When it prints no JSON and exits 0, the attempt is `no_output` (empty stdout) or `unparseable`. A
timeout is `timeout`, and the attempt counts as killed. Retryable outcomes (`timeout`,
`rate_limited`, `provider_error`, `no_output`, `unparseable`) are retried up to
`invoke.max_attempts`. Every attempt is recorded either way.

## Hooks: making the world checkable

| Hook | When | stdin | Purpose |
|---|---|---|---|
| `setup` | once, before the first case | none | start fakes, build fixtures |
| `seed` | before every attempt | the case JSON | put the world into the case's `start_state` |
| `observe` | before and after every attempt | none | print the world as JSON; checks grade **this** |
| `reset` | after each case (`reset_scope: case`) or once per run | none | clean up |

`seed` and `observe` are what make state-diff grading possible. Without `observe`, checks see
only `output`. That fits an agent whose deliverable is text (an analysis, a summary), but not one
that changes things. For an agent that changes things, grading only what it says it did is the
failure G10 exists to refuse: in comparable benchmarks, 45–48% of failures were confident false
claims of success.

Where the world can be sandboxed (framework Q4): a git repo at a commit, stateful fakes behind a
proxy for structured SaaS APIs, record-and-replay for read-only APIs. Fake only what changes
state, and keep fakes and cassettes in `evals/env/`; their hash goes into every run manifest. Where
it can't, see framework Q5: recorded replay, shadow and canary, online judging.

## Environment

The agent runs in `invoke.cwd` (relative to the repository root), in the team's own environment:
the `aot-evals` wrapper restores the caller's `PATH`, `VIRTUAL_ENV` and `PYTHONPATH` before
starting it. Extra variables go in `invoke.env`.
