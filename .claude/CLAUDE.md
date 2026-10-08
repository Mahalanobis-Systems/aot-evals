# aot-evals: working on this repo

- `docs/method.md` is the reference for behaviour: when you change what a command, gate or
  file does, update it in the same change. CONTRIBUTING.md has the workflow and the release
  process.
- `src/aot_evals/` is runtime code that users execute through `bin/aot-evals`. It may use only
  the standard library and PyYAML; the `anthropic` SDK is imported lazily by the anthropic judge
  backend only. pytest and ruff are dev-only.
- Python floor is 3.11: run the tests with `--python 3.11`.
- Keep the agent contract stable (references/agent-contract.md): the stdin/stdout fields, the
  outcome codes in `outcomes.py`, and the per-result field names (`case_id`, `trial`,
  `attempt`, `outcome`, `cost_usd`, `tokens_input`, `tokens_output`, `latency_ms`, `model`,
  `judge_model`). Users' agents depend on them.
- `report.json` keys may be added within a schema version, never removed or renamed.
- Unknown values are `None`/`null`, never `0`. Never pre-round anything in `report.json`.
- Every gate change needs a fixture test (`tests/test_fixtures.py`, `tests/test_judges.py`).
  Each self-test fixture must trigger exactly the gate it targets.
- Every user-visible change gets a line under `## Unreleased` in CHANGELOG.md.
- Tests: `uv run --no-project --python 3.11 --with pyyaml --with pytest env PYTHONPATH=src python -m pytest -q`
