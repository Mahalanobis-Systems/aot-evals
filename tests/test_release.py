"""The release metadata agrees with itself (CONTRIBUTING.md, "Releasing").

Claude Code offers users an update only when the plugin's `version` changes, and the
marketplace entry installs the plugin from its release tag, so a version written in one place
and not another ships the wrong code or none.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("release", ROOT / "scripts" / "release.py")
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


def test_every_version_agrees():
    versions = release.current_versions()
    assert len(set(versions.values())) == 1, versions
    assert release.SEMVER.match(next(iter(versions.values())))


def test_the_marketplace_installs_the_release_tag():
    entry = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text())["plugins"][0]
    version = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())["version"]
    assert entry["source"] == {"source": "github", "repo": "Mahalanobis-Systems/aot-evals",
                               "ref": release.tag_for(version)}


def test_the_changelog_has_the_current_release_and_an_unreleased_section():
    text = (ROOT / "CHANGELOG.md").read_text()
    version = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())["version"]
    assert "## Unreleased" in text
    assert release.changelog_section(version, text), f"CHANGELOG.md has no `## {version}` section"


def test_rolling_the_changelog_moves_unreleased_under_the_version(tmp_path, monkeypatch):
    log = tmp_path / "CHANGELOG.md"
    log.write_text("# Changelog\n\n## Unreleased\n\n- Fixed a thing.\n\n## 0.1.0\n\nFirst.\n")
    monkeypatch.setattr(release, "CHANGELOG", log)
    release._roll_changelog("0.1.1", "2026-11-02")
    text = log.read_text()
    assert text.startswith("# Changelog\n\n## Unreleased\n\n## 0.1.1 — 2026-11-02\n\n- Fixed a thing.\n\n## 0.1.0")
    assert release.changelog_section("0.1.1", text) == "- Fixed a thing."
