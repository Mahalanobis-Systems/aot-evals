"""The interactive problems (docs/interactive/) agree with problems.md.

Each problem has one widget, each widget's page is linked from its problem, and every widget that
uses the online store carries the store's numbers from problems.md, so the two can't drift.
"""

from __future__ import annotations

import html
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIR = ROOT / "docs" / "interactive"
PROBLEMS = (ROOT / "docs" / "problems.md").read_text()
MANIFEST = json.loads((DIR / "widgets.json").read_text())


def config(slug: str) -> dict | None:
    m = re.search(r"data-config='([^']*)'", (DIR / f"{slug}.html").read_text())
    return json.loads(html.unescape(m.group(1))) if m else None


def store() -> dict[str, dict]:
    """problems.md's store: requests a day from its table, what one mistake costs from problem 1."""
    rows = re.findall(r"^\| (Where's my order\?|Start a return|Change my address|Refund me) \| (\d[\d,]*) \|", PROBLEMS, re.M)
    prose = " ".join(PROBLEMS.split())
    costs = re.search(r"\(\$(\d+) for a wrong order status, \$(\d+) for a botched return, \$(\d+) for a wrong address, \$(\d+) for a bad refund\)", prose)
    assert len(rows) == 4 and costs, "problems.md: the store's table or problem 1's costs moved"
    return {label: {"n": int(n.replace(",", "")), "cost": int(c)} for (label, n), c in zip(rows, costs.groups())}


def test_every_problem_has_one_widget_and_its_files():
    numbers = sorted(w["problem"] for w in MANIFEST["widgets"])
    assert numbers == list(range(1, 13))
    for w in MANIFEST["widgets"]:
        assert (DIR / f"{w['slug']}.html").is_file(), w["slug"]
        assert {"title", "label", "description", "lead"} <= set(w), w["slug"]


def test_each_problem_links_to_its_widget_page():
    for w in MANIFEST["widgets"]:
        heading = re.search(rf"^### {w['problem']}\. .*$", PROBLEMS, re.M)
        rest = PROBLEMS[heading.end():]
        section = rest[: re.search(r"^(### |## )", rest, re.M).start()] if re.search(r"^(### |## )", rest, re.M) else rest
        assert f"]({MANIFEST['site']}{w['slug']}/)" in section, f"problem {w['problem']} doesn't link to {w['slug']}"


def test_widgets_on_the_store_carry_its_numbers():
    want = store()
    used = 0
    for w in MANIFEST["widgets"]:
        cfg = config(w["slug"])
        if not cfg or "kinds" not in cfg:
            continue
        used += 1
        got = {k["label"]: k for k in cfg["kinds"]}
        assert set(got) == set(want), w["slug"]
        for label, k in got.items():
            assert k["n"] == want[label]["n"], (w["slug"], label)
            if "cost" in k:
                assert k["cost"] == want[label]["cost"], (w["slug"], label)
    assert used >= 3   # problems 1, 3 and 4


def test_problem_1_defaults_reproduce_its_numbers():
    kinds = config("mistake-costs")["kinds"]
    n = sum(k["n"] for k in kinds)
    before = sum(k["pass"] for k in kinds)
    refund = next(k for k in kinds if k["id"] == "refund")
    after = before - (refund["pass"] - round(refund["n"] * (1 - 0.15)))   # the slider's default: 15% go wrong
    assert (round(before / n * 100, 1), round(after / n * 100, 1)) == (91.0, 90.8)
    weight = refund["n"] * refund["cost"] / sum(k["n"] * k["cost"] for k in kinds)
    assert round(weight * 100) == 23
    assert "91.0% to 90.8%" in PROBLEMS and "refunds carry 23% of the score" in PROBLEMS


def test_scripts_are_wrapped_and_use_no_typescript():
    for w in MANIFEST["widgets"]:
        text = (DIR / f"{w['slug']}.html").read_text()
        scripts = re.findall(r"<script>(.*?)</script>", text, re.S)
        assert len(scripts) == 1, w["slug"]
        body = scripts[0].strip()
        assert body.startswith("(() => {") and body.endswith("})();"), w["slug"]
        assert not re.search(r"\bas (HTML|SVG)\w*Element\b|: (number|string|boolean)\b\s*[,)=]", body), w["slug"]
