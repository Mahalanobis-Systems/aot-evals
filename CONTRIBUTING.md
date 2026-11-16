# Contributing to aot-evals

Thanks for helping. Bug reports, feedback from running aot-evals on a real agent, and pull
requests are all welcome. By contributing, you agree that your contribution is licensed under
the [Apache License 2.0](LICENSE), the same as the project.

## Reporting a problem or giving feedback

[Open an issue](https://github.com/Mahalanobis-Systems/aot-evals/issues/new/choose). The most
useful reports include:

- the output of `aot-evals doctor` (versions and environment; it prints no secrets);
- the command you ran and what it printed, or what the skill did;
- what you expected instead.

Leave out traces, case contents and anything from your agent's users. If the problem is a
security issue, follow [SECURITY.md](SECURITY.md) instead.

## Making a change

1. Fork the repository and create a branch from `main`.
2. Make the change. Keep to the conventions below.
3. Run the checks:

   ```bash
   uv run --no-project --python 3.11 --with pyyaml --with pytest env PYTHONPATH=src python -m pytest -q
   uvx ruff check src tests scripts
   ```

4. Try it in Claude Code against a real or toy agent: `claude --plugin-dir /path/to/your/checkout`
   loads your working copy instead of the released plugin (`aot-evals demo` sets up a toy one).
5. Add a line under `## Unreleased` in [CHANGELOG.md](CHANGELOG.md) for anything a user would
   notice.
6. Open a pull request. CI runs the tests on Python 3.11 and 3.13, lint, and the plugin manifest
   validator.

### Conventions

- **The method is the contract.** [docs/method.md](docs/method.md) describes what every command,
  gate and file does. A change in behavior updates it in the same pull request; why a rule holds
  lives in [docs/statistics.md](docs/statistics.md), linked rather than repeated.
- **Runtime code stays light.** `src/aot_evals/` runs in users' environments through
  `bin/aot-evals`: standard library and PyYAML only. The `anthropic` SDK is imported lazily by the
  Anthropic judge backend. Python 3.11 is the floor.
- **Every gate change needs a fixture test** (`tests/test_fixtures.py`, `tests/test_judges.py`),
  and each self-test fixture must trigger exactly the gate it targets.
- **Docs credit their sources.** Cite the literature directly, credit the field each piece comes
  from, and don't claim a first.
- **Unknown is `null`, never `0`**, and nothing in `report.json` is pre-rounded.
- **Skills** (`skills/*/SKILL.md`) are instructions to Claude. Keep them short and concrete, and
  test a changed skill by running it.
- Working on this repository with Claude Code picks up `.claude/CLAUDE.md`, which repeats these
  rules.

Good first contributions: a vertical coverage-list template with a real source
([templates/taxonomies/](templates/taxonomies/README.md)), a judge backend, a clearer error
message for something that confused you.

## Versioning

aot-evals follows [Semantic Versioning](https://semver.org/):

- **Major** (`2.0.0`): any breaking change. Breaking means a user must change something: the agent
  contract ([references/agent-contract.md](references/agent-contract.md)), the files of an eval,
  `report.json` keys or its schema version, CLI commands or flags. The changelog entry leads with
  what to change.
- **Minor** (`2.1.0`): new features that need nothing from users, such as a key added to
  `report.json` within its schema version.
- **Patch** (`2.0.1`): fixes and improvements that need nothing from users.

## Releasing

Maintainers release from `main`. Claude Code offers users an update only when the plugin's
`version` changes, and the marketplace entry installs the plugin from its release tag, so
unreleased work on `main` never reaches users.

1. Make sure `## Unreleased` in CHANGELOG.md describes the release.
2. On a clean branch from `main`, run:

   ```bash
   python3 scripts/release.py 2.1.0
   ```

   It writes the version to `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`
   (the version and the `ref` the plugin installs from, `aot-evals--v2.1.0`), `pyproject.toml`
   and `src/aot_evals/__init__.py`, and moves the `Unreleased` notes under `## 2.1.0 — <date>`.
3. Open a pull request titled `Release 2.1.0`, and merge it when CI passes.
4. On merge, the [release workflow](.github/workflows/release.yml) tags the merge commit
   `aot-evals--v2.1.0` and publishes a GitHub release with the changelog section. Users get it
   with `claude plugin marketplace update aot-evals` and `claude plugin update
   aot-evals@aot-evals` (then a restart), or automatically if they turned on auto-update for
   the marketplace.

The release also attaches the method as published files, built by `scripts/build_site.py`:
`evals.json` (schema `aot-evals/site@2`: the method, the three guiding documents with their terms
and rules, the online-store example, practice findings, benchmark catalog, situations and
templates as data, which mahalsystems.ai imports) and `aot-evals-method-<version>.zip` (the same
as plain files, to download and read without the plugin). The four parts, the three roles, the
commands, the spec's fields, report.json's keys and the gates are parsed from the tables in
docs/method.md, so keep their columns as they are; `tests/test_build_site.py` fails if a table doesn't
parse or the commands table misses a CLI command, and `tests/test_docs_links.py` fails on
any relative link or `#anchor` that doesn't resolve. To see what a release
will publish:

```bash
uv run --no-project --with pyyaml python3 scripts/build_site.py   # writes dist/
```

If the workflow fails, fix the cause and re-run it from the Actions tab (it skips a tag that
already exists). Never move or delete a published tag: release a new patch version instead.
