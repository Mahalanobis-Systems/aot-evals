"""Names in Berkeley RDI's awesome-agent-benchmarks that our catalog doesn't have yet.

    python3 scripts/benchmarks_refresh.py

Prints the new names with their description and links, ready to research and add to
references/benchmarks.yaml by hand (every field, see references/benchmarks.md). Nothing is
written. Needs PyYAML and network access."""

from __future__ import annotations

import re
import sys
import urllib.request
from pathlib import Path

import yaml

UPSTREAM = "https://raw.githubusercontent.com/RDI-Foundation/awesome-agent-benchmarks/main/benchmarks.yaml"
CATALOG = Path(__file__).resolve().parents[1] / "references" / "benchmarks.yaml"


def norm(name: str) -> str:
    s = str(name).lower()
    for a, b in (("τ", "tau"), ("²", "2"), ("³", "3"), ("++", "plusplus"), ("+", "plus")):
        s = s.replace(a, b)
    return re.sub(r"[^a-z0-9]", "", s)


def main() -> int:
    ours = yaml.safe_load(CATALOG.read_text())
    known = {norm(e["name"]) for e in ours} | {norm(e["id"]) for e in ours}
    with urllib.request.urlopen(UPSTREAM, timeout=30) as r:
        theirs = yaml.safe_load(r.read())
    if isinstance(theirs, dict):
        theirs = theirs.get("benchmarks") or next(iter(theirs.values()))
    new = [b for b in theirs if norm(b.get("name", "")) not in known]
    for b in new:
        links = " ".join(v for v in (b.get("links") or {}).values() if v)
        print(f"- {b['name']} [{b.get('category', '?')}]: {b.get('description', '').strip()}\n  {links}")
    print(f"\n{len(new)} of {len(theirs)} upstream names are not in the catalog ({len(ours)} entries)",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
