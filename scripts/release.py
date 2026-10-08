#!/usr/bin/env python3
"""Prepare a release: `python3 scripts/release.py 0.2.0`.

Also `--check` (every version agrees and the changelog has the section; prints the version) and
`--notes X.Y.Z` (prints that version's changelog section), which the release workflow uses.

Sets the version everywhere it lives, pins the marketplace entry to the release tag, and turns
CHANGELOG.md's `## Unreleased` section into the release's section. It does not commit, tag or
push: open a pull request with the result. When it merges, .github/workflows/release.yml tags
the merge commit `aot-evals--v<version>` and publishes a GitHub release from the changelog.
See CONTRIBUTING.md, "Releasing".
"""

from __future__ import annotations

import datetime
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / ".claude-plugin" / "plugin.json"
MARKETPLACE = ROOT / ".claude-plugin" / "marketplace.json"
PYPROJECT = ROOT / "pyproject.toml"
INIT = ROOT / "src" / "aot_evals" / "__init__.py"
CHANGELOG = ROOT / "CHANGELOG.md"
SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


def tag_for(version: str) -> str:
    return f"aot-evals--v{version}"


def current_versions() -> dict[str, str | None]:
    """Every place the version is written. They must agree (tests/test_release.py)."""
    plugin = json.loads(PLUGIN.read_text())
    entry = json.loads(MARKETPLACE.read_text())["plugins"][0]
    ref = (entry.get("source") or {}).get("ref", "") if isinstance(entry.get("source"), dict) else ""
    py = re.search(r'^version = "([^"]+)"', PYPROJECT.read_text(), re.M)
    init = re.search(r'^__version__ = "([^"]+)"', INIT.read_text(), re.M)
    return {
        ".claude-plugin/plugin.json": plugin.get("version"),
        ".claude-plugin/marketplace.json version": entry.get("version"),
        ".claude-plugin/marketplace.json source.ref": ref.removeprefix("aot-evals--v") or None,
        "pyproject.toml": py.group(1) if py else None,
        "src/aot_evals/__init__.py": init.group(1) if init else None,
    }


def changelog_section(version: str, text: str | None = None) -> str | None:
    """The body of `## <version>` in CHANGELOG.md, for the release notes."""
    text = text if text is not None else CHANGELOG.read_text()
    m = re.search(rf"^## {re.escape(version)}\b.*?$\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    return m.group(1).strip() if m else None


def _set_versions(version: str) -> None:
    plugin = json.loads(PLUGIN.read_text())
    plugin["version"] = version
    PLUGIN.write_text(json.dumps(plugin, indent=2, ensure_ascii=False) + "\n")
    market = json.loads(MARKETPLACE.read_text())
    entry = market["plugins"][0]
    entry["version"] = version
    entry["source"]["ref"] = tag_for(version)
    MARKETPLACE.write_text(json.dumps(market, indent=2, ensure_ascii=False) + "\n")
    PYPROJECT.write_text(re.sub(r'^version = "[^"]+"', f'version = "{version}"', PYPROJECT.read_text(),
                                count=1, flags=re.M))
    INIT.write_text(re.sub(r'^__version__ = "[^"]+"', f'__version__ = "{version}"', INIT.read_text(),
                           count=1, flags=re.M))


def _roll_changelog(version: str, today: str) -> None:
    text = CHANGELOG.read_text()
    m = re.search(r"^## Unreleased\s*$\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    if not m or not m.group(1).strip():
        sys.exit("CHANGELOG.md: add what changed under `## Unreleased` first")
    body = m.group(1).strip()
    new = f"## Unreleased\n\n## {version} — {today}\n\n{body}\n\n"
    CHANGELOG.write_text(text[:m.start()] + new + text[m.end():].lstrip("\n"))


def check() -> str:
    """Exit non-zero unless every version agrees and the changelog has the release's section;
    print the version. The release workflow runs this before tagging."""
    versions = current_versions()
    if len(set(versions.values())) != 1:
        sys.exit("versions disagree: " + ", ".join(f"{k}={v}" for k, v in versions.items()))
    version = next(iter(versions.values()))
    if not changelog_section(version):
        sys.exit(f"CHANGELOG.md has no `## {version}` section")
    return version


def main(argv: list[str]) -> int:
    if argv == ["--check"]:
        print(check())
        return 0
    if len(argv) == 2 and argv[0] == "--notes":
        print(changelog_section(argv[1]) or "")
        return 0
    if len(argv) != 1 or not SEMVER.match(argv[0]):
        sys.exit("usage: python3 scripts/release.py X.Y.Z | --check | --notes X.Y.Z")
    version = argv[0]
    old = current_versions()[".claude-plugin/plugin.json"]
    if old and tuple(map(int, version.split("."))) <= tuple(map(int, old.split("."))):
        sys.exit(f"{version} is not newer than the current version {old}")
    if subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True).stdout.strip():
        sys.exit("the working tree has uncommitted changes; commit or stash them first")
    _roll_changelog(version, datetime.date.today().isoformat())
    _set_versions(version)
    print(f"prepared {version} (tag {tag_for(version)} is created when this merges to main)")
    print("next: review the diff, then open a pull request titled "
          f"'Release {version}'")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
