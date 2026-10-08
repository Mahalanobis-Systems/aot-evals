# Judge backends

A judge's spec (`evals/checks/judge/<check-id>.md`) declares one or more backends. Each backend
returns a score s = P(pass) for an item. The `primary` backend's verdicts count once the judge is
calibrated. The other backends exist for comparison (E5) and for reliability (C11).

| `type` | Calls | Score | Cost per judgement |
|---|---|---|---|
| `systemone` | `POST {base_url}/v1/systemone` with `state` and one typed question | a probability: `noul` → P(yes); `choice`/`score` → summed probability of the passing options or levels | the response's `cost` if it has one, else input tokens × `price_input_per_mtok` (default $0.042/MTok) |
| `anthropic` | the Claude Messages API via the official SDK, with a JSON-schema structured output `{reasoning, answer}` | 0 or 1 | estimated from tokens at list price; override with `price_input_per_mtok` / `price_output_per_mtok` |
| `command` | any command, run from the repository root, with the item on stdin | whatever the command returns | whatever it reports as `cost` |

## `systemone`

This is the typed-decision interface of a System One model such as TypeSafe's Jev (docs/method.md §5). It is
the same wire contract whether you call TypeSafe directly, a reseller, or a local open-weight
server (LAYA), so only `base_url`, `api_key_env` and the auth header change.

```yaml
jev:
  type: systemone
  model: <model id>
  family: typesafe
  base_url: https://api.typesafe.ai      # or a reseller / local server
  path: /v1/systemone                    # default
  api_key_env: TYPESAFE_API_KEY          # omit for an unauthenticated local server
  auth_header: Authorization             # default; auth_prefix defaults to "Bearer "
  headers: {}                            # extra request headers; User-Agent is aot-evals/<version>
```

**Jev through OpenCode Zen.** OpenCode Zen serves the same contract, and its free model needs no
key. Verified live on 2026-10-02 for `noul`, `choice` and `score`: about 350–500 ms per call,
`cost: "0"`. The gateway limits anonymous calls per IP per day: after about 250 calls it answers
HTTP 429 `FreeUsageLimitError`, which one calibration pass over a few judges can reach. It suits
small pilots and the opt-in live test, not a full calibration round or judging production
traffic. Set `daily_limit` and `aot-evals calibrate`
warns (also with `--dry-run`) when the calls it needs come near it. A rate-limit error stops that
backend's calls at once, and calibrate prints the errors grouped by message.

```yaml
jev:
  type: systemone
  model: jev-1.13-free                   # paid: jev-1.13 with api_key_env: OPENCODE_API_KEY
  family: typesafe
  base_url: https://opencode.ai/zen
  daily_limit: 250                       # calls a day; calibrate warns near it
```

What we know about these models' probabilities, and how calibration handles it:
- **Don't trust the confidence until it is measured.** The first independent measurement put
  Jev's calibration last of twelve models (ECE 0.246). Probabilities often saturate at exactly
  0 or 1. C10 therefore picks the threshold on your labels and reports ECE and the Brier score.
- **`noul` returns a probability but no confidence field.** That probability is the score.
- **An empty state comes back as a number (≈ 0.46), not an error.** The backend refuses to send
  an empty state and records an instrument error instead.

## `anthropic`

```yaml
claude:
  type: anthropic
  model: claude-opus-5-5
  family: anthropic
  effort: medium          # output_config.effort
  api_key_env: ANTHROPIC_API_KEY   # optional; the SDK also finds ANTHROPIC_API_KEY or an `ant auth login` profile
```

- The prompt is the question, the options and the judge file's body, followed by the judge's inputs.
  The answer is constrained by a JSON schema to `{reasoning, answer}`, with reasoning first.
- **No refusal fallback.** If the model refuses, the item gets an instrument error rather than a
  verdict from another model, because a judge is calibrated per model.
- **Model family matters.** Use a different family from the agent's (`agent.yaml`
  `model_family`). G4 refuses a same-family generative judge for pairwise grading.

## `command`

Use this for any other judge: your own LLM gateway, another provider, an evaluation service, or a
rules engine.

```yaml
mine:
  type: command
  command: [python, evals/env/my_judge.py]
  model: <model id>
  family: <family>
  timeout: 60
  env: {}
```

stdin:

```json
{"question": {"type": "noul", "instructions": "..."}, "state": "<end.output>\n...\n</end.output>",
 "input": {"end.output": "..."}, "judge_id": "...", "version": 3, "model": "...",
 "spec": {"question_type": "noul", "question": "...", "detects": "failure",
          "yes_means": "the failure is present: yes is a FAIL", "guidance": "Pass when ... Fail when ..."},
 "prompt": "Question: ...\nAnswer yes if ...\n\nGuidance:\n...\n\nMaterial:\n..."}
```

`prompt` is the text the `anthropic` backend sends, ready to pass to any chat model. `spec`
says which way a yes points: a `noul` question with `detects: failure` states a failure, so yes
means fail. A model that sees only the question can reason "the answer matches the reference"
and still answer yes to a failure statement, inverting every verdict. The safest output is `{"verdict": "pass"}` or `{"verdict": "fail"}`: ask the model for pass or
fail directly and there is no direction to get wrong.

stdout must contain one of `{"verdict": "pass"}`, `{"p_pass": 0.83}`, `{"noul": 0.2}` or
`{"probabilities": {...}}`. It may also include `reasoning`, `confidence`, `cost`, and
`usage.tokens_input` / `usage.tokens_output`. If the judge could not decide, print
`{"error": "..."}`.
