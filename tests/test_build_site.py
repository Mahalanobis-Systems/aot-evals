"""The method's published data (scripts/build_site.py) is complete, links out, and rebuilds the same.

The release attaches evals.json and the zip, and the website imports them, so a change to
docs/method.md that breaks a table's shape, or a bundled file that links outside the bundle,
fails here rather than on the site.
"""

from __future__ import annotations

import importlib.util
import io
import json
import re
import zipfile
from pathlib import Path

import pytest

from aot_evals import benchmarks

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("build_site", ROOT / "scripts" / "build_site.py")
build_site = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build_site)

LINK = re.compile(r"\]\(([^)\s]+)\)")


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    out = tmp_path_factory.mktemp("site")
    build_site.main(["--out", str(out), "--today", "2026-11-02"])
    doc = json.loads((out / "evals.json").read_text())
    return out, doc


def test_every_command_gate_measurement_experiment_and_panel_is_parsed(built):
    _, doc = built
    assert [c["id"] for c in doc["commands"]] == [f"C{i}" for i in [*range(13), 19, *range(13, 19)]]
    assert [g["id"] for g in doc["gates"]] == [f"G{i}" for i in range(1, 15)]
    assert {m["id"] for m in doc["measurements"]} == {f"M{i}" for i in range(1, 30)}
    assert {e["id"] for e in doc["experiments"]} == {f"E{i}" for i in range(1, 16)}
    assert [p["id"] for p in doc["panels"]] == [f"P{i}" for i in range(14)]
    assert [p["id"] for p in doc["planes"]] == ["A", "B", "C"]
    for rows, fields in [(doc["commands"], ("command", "does", "exit_gate")), (doc["gates"], ("condition", "refuses")),
                         (doc["measurements"], ("name", "plane", "definition", "use")),
                         (doc["experiments"], ("name", "design", "produces")), (doc["panels"], ("name", "shows"))]:
        for row in rows:
            assert all(row[f] for f in fields), row
    assert len(doc["principles"]) == 9 and all(p["title"] for p in doc["principles"])
    assert [s["number"] for s in doc["method"]["sections"]] == list(range(1, 11))


def test_guidance_only_items_are_flagged_and_their_mark_dropped(built):
    _, doc = built
    flagged = {r["id"] for key in ("commands", "measurements", "experiments", "panels") for r in doc[key]
               if r["guidance_only"]}
    assert {"C16", "C17", "M17", "M23", "M27", "M28", "E7", "E11", "E12", "E13", "P10", "P11"} == flagged
    assert not any("†" in r["id"] for key in ("measurements", "experiments", "panels") for r in doc[key])


def test_the_catalogs_and_the_release_are_whole(built):
    _, doc = built
    assert doc["schema"] == "aot-evals/site@1"
    assert doc["version"] == build_site.version()
    assert doc["benchmarks"]["entries"] == benchmarks.load()
    assert doc["situations"] == benchmarks.situations()
    assert {s["name"] for s in doc["plugin"]["skills"]} == {p.name for p in (ROOT / "skills").iterdir() if p.is_dir()}
    tag = build_site.tag_for(doc["version"])
    assert doc["download"]["url"].endswith(f"/releases/download/{tag}/aot-evals-method-{doc['version']}.zip")


def test_markdown_links_are_absolute_or_anchors(built):
    _, doc = built
    text = json.dumps(doc, ensure_ascii=False)
    for target in LINK.findall(text):
        assert target.startswith(("https://", "#")), target
    tag = build_site.tag_for(doc["version"])
    assert f"https://github.com/Mahalanobis-Systems/aot-evals/blob/{tag}/references/benchmarks.md" in text


def test_the_zip_rebuilds_byte_for_byte_and_its_links_resolve(built, tmp_path):
    out, doc = built
    name = doc["download"]["zip"]
    build_site.main(["--out", str(tmp_path), "--today", "2027-01-01"])
    assert (out / name).read_bytes() == (tmp_path / name).read_bytes()

    z = zipfile.ZipFile(io.BytesIO((out / name).read_bytes()))
    top = f"aot-evals-method-{doc['version']}/"
    names = set(z.namelist())
    for must in ("README.md", "LICENSE", "docs/method.md", "references/benchmarks.yaml", "templates/case.json"):
        assert top + must in names
    assert not any("__pycache__" in n or n.endswith(".pyc") for n in names)
    for n in names:
        if not n.endswith(".md"):
            continue
        for target in LINK.findall(z.read(n).decode()):
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            resolved = _normalize(f"{Path(n).parent.as_posix()}/{target.partition('#')[0]}")
            assert resolved in names, f"{n} links to {target}, which is not in the zip"


def _normalize(path: str) -> str:
    parts: list[str] = []
    for p in path.split("/"):
        if p == "..":
            parts.pop()
        elif p not in ("", "."):
            parts.append(p)
    return "/".join(parts)


def test_a_broken_table_fails_the_build():
    with pytest.raises(ValueError, match="cells"):
        build_site.table("| id | Condition | Refuses |\n|---|---|---|\n| G1 | only two |\n", "test")
    with pytest.raises(ValueError, match="no table"):
        build_site.table("no table here", "test")
