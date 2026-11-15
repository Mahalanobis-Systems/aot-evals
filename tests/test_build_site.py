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
    build_site.main(["--out", str(out), "--today", "2026-11-14"])
    doc = json.loads((out / "evals.json").read_text())
    return out, doc


def test_the_parts_roles_commands_fields_keys_and_gates_are_parsed(built):
    _, doc = built
    assert [p["part"] for p in doc["parts"]] == ["Estimand", "Sampling design", "Measurement model", "Decision rule"]
    assert [r["role"] for r in doc["roles"]] == ["The owner", "Engineering", "Graders"]
    assert "phases" not in doc
    assert len(doc["principles"]) == 9 and all(p["title"] for p in doc["principles"])
    for rows, fields in [(doc["commands"], ("command", "what_it_does")), (doc["gates"], ("part", "id", "fails_when")),
                         (doc["spec_fields"], ("field", "part", "required")), (doc["report_keys"], ("key", "holds"))]:
        assert rows
        for row in rows:
            assert all(row[f] for f in fields), row
    assert {g["id"] for g in doc["gates"]} >= {"manifest", "trials_complete", "screened", "committed",
                                               "coverage_list", "independent_reference", "k", "judge_floor",
                                               "people_floor"}
    numbers = [s["number"] for s in doc["method"]["sections"]]
    assert numbers == list(range(1, len(numbers) + 1))


def test_the_commands_table_names_every_command_the_cli_has(built):
    _, doc = built
    cli = (ROOT / "src" / "aot_evals" / "cli.py").read_text()
    subcommands = set(re.findall(r'sub\.add_parser\("([\w-]+)"', cli))
    assert {c["name"] for c in doc["commands"]} == subcommands
    gone = {"checkpoint", "redundancy", "allocate"}
    assert not gone & subcommands
    assert not any(re.search(r"\b(checkpoint|redundancy|allocate|status --gates|report --html)\b", c["command"])
                   for c in doc["commands"])


def test_the_guiding_documents_terms_rules_and_example_are_whole(built):
    _, doc = built
    assert set(doc["docs"]) == {"estimators", "problems", "statistics"}
    assert all(d["sections"] for d in doc["docs"].values())
    terms = {t["term"] for t in doc["terms"]}
    assert {"use case", "pool", "coverage", "plan", "catch rate", "clean pass rate"} <= terms
    assert [r["number"] for r in doc["rules"]] == list(range(1, 28))
    paths = {f["path"] for f in doc["example"]["files"]}
    assert "examples/store/evals/agents/store/refund-subagent/eval.yaml" in paths


def test_the_catalogs_and_the_release_are_whole(built):
    _, doc = built
    assert doc["schema"] == "aot-evals/site@2"
    assert doc["version"] == build_site.version()
    assert doc["benchmarks"]["entries"] == benchmarks.load()
    assert doc["situations"] == benchmarks.situations()
    assert {s["name"] for s in doc["plugin"]["skills"]} == {p.name for p in (ROOT / "skills").iterdir() if p.is_dir()}
    assert {s["name"] for s in doc["plugin"]["skills"]} == {"start", "build", "judge", "report"}
    tag = build_site.tag_for(doc["version"])
    assert doc["download"]["url"].endswith(f"/releases/download/{tag}/aot-evals-method-{doc['version']}.zip")


def test_markdown_links_are_absolute_or_anchors(built):
    _, doc = built
    text = json.dumps(doc, ensure_ascii=False)
    for target in LINK.findall(text):
        assert target.startswith(("https://", "#")), target
    tag = build_site.tag_for(doc["version"])
    assert f"https://github.com/Mahalanobis-Systems/aot-evals/blob/{tag}/references/agent-contract.md" in text


def test_the_zip_rebuilds_byte_for_byte_and_its_links_resolve(built, tmp_path):
    out, doc = built
    name = doc["download"]["zip"]
    build_site.main(["--out", str(tmp_path), "--today", "2027-01-01"])
    assert (out / name).read_bytes() == (tmp_path / name).read_bytes()

    z = zipfile.ZipFile(io.BytesIO((out / name).read_bytes()))
    top = f"aot-evals-method-{doc['version']}/"
    names = set(z.namelist())
    for must in ("README.md", "LICENSE", "docs/method.md", "docs/estimators.md", "docs/problems.md",
                 "docs/statistics.md", "examples/store/README.md", "references/benchmarks.yaml",
                 "templates/case.json"):
        assert top + must in names
    assert not any("__pycache__" in n or n.endswith(".pyc") for n in names)
    assert not any("/references/process/" in n for n in names)
    for n in names:
        if not n.endswith(".md"):
            continue
        for target in LINK.findall(z.read(n).decode()):
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            resolved = _normalize(f"{Path(n).parent.as_posix()}/{target.partition('#')[0]}")
            assert resolved in names or resolved + "/README.md" in names, \
                f"{n} links to {target}, which is not in the zip"


def _normalize(path: str) -> str:
    parts: list[str] = []
    for p in path.split("/"):
        if p == "..":
            parts.pop()
        elif p not in ("", "."):
            parts.append(p)
    return "/".join(parts).rstrip("/")


def test_a_broken_table_fails_the_build():
    with pytest.raises(ValueError, match="cells"):
        build_site.table("| id | Condition | Refuses |\n|---|---|---|\n| G1 | only two |\n", "test")
    with pytest.raises(ValueError, match="no table"):
        build_site.table("no table here", "test")


def test_an_escaped_pipe_stays_inside_its_cell():
    rows = build_site.table("| Command | Does |\n|---|---|\n| `replay run\\|seed` | acts |\n", "test")
    assert rows == [{"command": "`replay run|seed`", "does": "acts"}]
