## What and why

<!-- What this changes, and the problem it solves. Link an issue if there is one. -->

## Checklist

- [ ] Tests pass (`uv run --no-project --python 3.11 --with pyyaml --with pytest env PYTHONPATH=src python -m pytest -q`)
- [ ] A gate change has a fixture test
- [ ] `docs/method.md` is updated if behaviour changed
- [ ] A line under `## Unreleased` in CHANGELOG.md, if a user would notice
- [ ] Tried in Claude Code with `claude --plugin-dir .` (for skill or CLI changes)
