"""Every relative link in the repository's Markdown resolves, and so does every #anchor.

The docs link to each other by section (docs/method.md to docs/statistics.md#33-..., the skills
to docs/estimators.md#terms), so renaming a heading must not leave a dead link behind. Anchors
follow GitHub's rule (scripts/build_site.py `anchor`): inline links become their text, everything
but word characters, hyphens and spaces goes, spaces become hyphens, and a repeated heading gets
-1, -2, ... The skills' `${CLAUDE_PLUGIN_ROOT}/...` paths are checked the same way.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LINK = re.compile(r"\]\(([^)\s]+)\)")
PLUGIN_PATH = re.compile(r"\$\{CLAUDE_PLUGIN_ROOT\}/([^\s`'\")]+)")
FENCE = re.compile(r"^```.*?^```", re.M | re.S)
HEADING = re.compile(r"^#{1,6} +(.+?)\s*#*\s*$", re.M)


def _md_files() -> list[Path]:
    r = subprocess.run(["git", "ls-files", "-z", "*.md"], cwd=ROOT, capture_output=True, text=True)
    if r.returncode != 0:
        pytest.skip("not a git checkout")
    return [ROOT / f for f in r.stdout.split("\0") if f and (ROOT / f).is_file()]


def anchors(path: Path) -> set[str]:
    text = FENCE.sub("", path.read_text())
    seen: dict[str, int] = {}
    out = set()
    for title in HEADING.findall(text):
        title = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", title)
        slug = re.sub(r"[^\w\- ]", "", title.lower()).replace(" ", "-")
        n = seen.get(slug, 0)
        out.add(slug if n == 0 else f"{slug}-{n}")
        seen[slug] = n + 1
    out.update(re.findall(r'<a (?:id|name)="([^"]+)"', text))
    return out


def _check(source: Path, target: str, problems: list[str]) -> None:
    path, _, frag = target.partition("#")
    dest = source if not path else (source.parent / path).resolve()
    if not dest.exists():
        problems.append(f"{source.relative_to(ROOT)}: {target} does not exist")
        return
    if frag and dest.suffix == ".md" and frag not in anchors(dest):
        problems.append(f"{source.relative_to(ROOT)}: {target} has no heading #{frag}")


def test_every_relative_link_and_anchor_resolves():
    problems: list[str] = []
    for f in _md_files():
        text = FENCE.sub("", f.read_text())
        for target in LINK.findall(text):
            if target.startswith(("http://", "https://", "mailto:")):
                continue
            _check(f, target, problems)
    assert not problems, "\n".join(problems)


def test_every_plugin_path_the_skills_name_exists():
    problems: list[str] = []
    for f in sorted((ROOT / "skills").glob("*/SKILL.md")) + sorted((ROOT / "references").glob("*.md")):
        for target in PLUGIN_PATH.findall(f.read_text()):
            target = target.rstrip(".,:;")
            path, _, frag = target.partition("#")
            dest = ROOT / path
            if not dest.exists():
                problems.append(f"{f.relative_to(ROOT)}: ${{CLAUDE_PLUGIN_ROOT}}/{target} does not exist")
            elif frag and frag not in anchors(dest):
                problems.append(f"{f.relative_to(ROOT)}: ${{CLAUDE_PLUGIN_ROOT}}/{target} has no heading #{frag}")
    assert not problems, "\n".join(problems)


def test_the_anchor_rule_matches_githubs():
    p = ROOT / "docs" / "statistics.md"
    a = anchors(p)
    assert "33-what-a-graders-error-costs-you" in a
    assert "45-no-difference-isnt-no-worse" in a
