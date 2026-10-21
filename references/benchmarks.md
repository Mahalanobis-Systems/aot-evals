# The public benchmark catalog

`references/benchmarks.yaml` is a local catalog of public agent benchmarks. Phase 1 (the
`discover` skill) matches an agent against it with `aot-evals benchmarks`, from this copy alone:
no web search, no model call, so it costs no time or tokens. The point is not to run these
benchmarks. In this method, public benchmarks are a source of grading designs, case templates,
user simulators, sandbox designs and baseline numbers; the cases themselves come from the
agent's own traffic (docs/method.md §1, principle 1).

## Matching

```bash
aot-evals benchmarks                                        # the workload vocabulary, and the catalog size
aot-evals benchmarks --workload crm --workload customer-support \
    --task "look up and summarize a record" --task "create or edit a record" --task "refuse an unsafe request"
aot-evals benchmarks ... --json                             # the same, as JSON, with `score` and `why`
aot-evals benchmarks --validate                             # check the catalog against the schema
```

Each entry scores 3 points per workload tag it shares with the agent and 1 point per word its
task types share with the agent's task types (common words ignored). Saturated benchmarks are
hidden unless `--include-saturated`; deprecated ones never show. Ties go to the newer benchmark.
The result says why each fits, so the reader can judge the match rather than trust a number.

## Fields

| Field | Meaning | Values |
|---|---|---|
| `id` | unique slug | lowercase letters, digits, hyphens |
| `name`, `year`, `by` | what it's called, first release, who made it | |
| `workloads` | the kinds of agent it concerns, 1 to 5 | the vocabulary in `src/aot_evals/benchmarks.py` (`WORKLOADS`) |
| `task_types` | what the agent is asked to do, 2 to 6 items in plain words | matched word by word against the agent's task types |
| `interaction` | how the agent is driven | `single-turn`, `multi-turn-scripted`, `multi-turn-simulated-user`, `autonomous-long-horizon` |
| `environment` | where it acts | `static`, `api-sandbox`, `database`, `browser`, `desktop`, `mobile`, `filesystem`, `terminal`, `containers`, `mixed` |
| `state_checked` | does grading compare the end state of a system | `true`, `false` |
| `tools` | what it can call, in plain words | |
| `grading` | how results are checked | `exact-match`, `state-diff`, `unit-tests`, `programmatic-check`, `llm-judge`, `human`, `pass^k`, `trajectory-check` |
| `size` | number of tasks | an integer, or `null` when unpublished |
| `data`, `pii` | where the data came from, and whether it holds personal data | `synthetic`, `real-public`, `real-scraped`, `mixed`; `none`, `possible`, `yes` |
| `license` | SPDX id, or `unknown` | |
| `harness` | runnable implementations | `inspect_evals`, `hal`, `agentbeats`, `own-repo`, `none` |
| `status` | | `active`, `frozen` (no new results accepted), `saturated` (top scores above about 90%), `deprecated` |
| `links` | `paper`, `github`, `website`, `leaderboard`; at least one of the first three | |
| `good_for` | what a team can borrow | `grading-design`, `case-template`, `baseline`, `user-simulator`, `sandbox-design`, `privacy-pattern`, `taxonomy` |
| `fit` | which production agents it helps and why, 1 or 2 sentences | |
| `caveats` | what's wrong with it, 1 sentence | |

## Keeping it current

- **Phase 1 never searches.** It reads this file.
- **Phase 2 may search.** When the `scope` skill builds the taxonomy (C2) it can look for
  benchmarks newer than the catalog for the agent's workload. Anything found goes into the report
  marked "not in the catalog", and into a pull request that adds it here with every field filled.
- **`python3 scripts/benchmarks_refresh.py`** prints the names in Berkeley RDI's list that the
  catalog lacks, with their links, ready to research and add by hand. Run it monthly.
- **Upstream lists to check for new names** (none has the fields above, so entries are still
  written by hand): Berkeley RDI's
  [awesome-agent-benchmarks](https://github.com/RDI-Foundation/awesome-agent-benchmarks)
  (`benchmarks.yaml`, auto-updated weekly),
  [Inspect Evals](https://ukgovernmentbeis.github.io/inspect_evals/) (runnable implementations),
  and the [Awesome-LLM-Agent-Evaluation](https://github.com/vnageshwaran-de/Awesome-LLM-Agent-Evaluation)
  living review (`data/benchmarks.csv`).
- `aot-evals benchmarks --validate` and `tests/test_benchmarks.py` reject an entry with a missing
  field or a value outside the vocabularies.
