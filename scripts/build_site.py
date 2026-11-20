#!/usr/bin/env python3
"""Build the method's published data: `python3 scripts/build_site.py`.

    build_site.py [--out dist] [--today YYYY-MM-DD]

Writes two files, which the release workflow attaches to each GitHub release and the website
(mahalsystems.ai) imports:

- `evals.json`: the method as data. The four parts, the three roles, the commands, the spec's
  fields, report.json's keys and the gates are parsed from the tables in docs/method.md (they stay
  the record), alongside the method's sections, the three guiding documents (estimators, problems,
  statistics) with the terms and the rules, the online-store example, the practice findings, the
  benchmark catalog, the situations, the templates and the plugin's skills:

      {"schema": "aot-evals/site@2", "version": "2.0.0", "commit": "abc1234", "generated": "YYYY-MM-DD",
       "method": {...}, "principles": [...], "parts": [...], "roles": [...], "commands": [...],
       "spec_fields": [...], "report_keys": [...], "gates": [...], "judge_backends": [...],
       "docs": {"estimators": {...}, "problems": {...}, "statistics": {...}}, "terms": [...],
       "rules": [...], "example": {...}, "practices": {...}, "benchmarks": {...}, "situations": [...],
       "templates": [...], "plugin": {...}, "download": {...}, "interactive": {...}}

  `interactive` carries the interactive problems (docs/interactive/): the shared stylesheet, and for
  each problem its page's title, lead and address on the site, and its widget as an HTML fragment
  (markup, then one script) for the site to place on that page.

  Relative links in the Markdown become absolute links to the release tag on GitHub, so text read
  on the site still points somewhere real. Keys may be added within a schema version, never
  removed or renamed.
- `interactive/`: each interactive problem as a page of its own, with an index, to open in a
  browser and check before a release. The release doesn't attach them.
- `aot-evals-method-<version>.zip`: the method, the guiding documents, the store example,
  references and templates as plain files, to read or hand to any coding agent without installing
  the plugin. The same version always builds the same bytes.

A change to docs/method.md that breaks a table's shape fails here (and in tests/test_build_site.py)
rather than publishing a partial method. See CONTRIBUTING.md, "Releasing".
"""

from __future__ import annotations

import argparse
import datetime
import json
import re
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aot_evals import benchmarks  # noqa: E402

REPO = "Mahalanobis-Systems/aot-evals"
METHOD = ROOT / "docs" / "method.md"
GUIDES = {"estimators": ROOT / "docs" / "estimators.md", "problems": ROOT / "docs" / "problems.md",
          "statistics": ROOT / "docs" / "statistics.md"}
PRACTICES = ROOT / "references" / "eval-best-practices.md"
BACKENDS = ROOT / "references" / "judge-backends.md"
EXAMPLE = ROOT / "examples" / "store"
# The example's files the site shows as text: what an agent system's evals look like.
EXAMPLE_FILES = [
    "evals/agents/store/agent.yaml",
    "evals/agents/store/end-to-end/eval.yaml",
    "evals/agents/store/end-to-end/coverage.yaml",
    "evals/agents/store/refund-subagent/eval.yaml",
    "evals/agents/store/refund-subagent/coverage.yaml",
    "evals/agents/store/refund-subagent/checks/judge/policy-judge.md",
    "evals/agents/store/refund-subagent/checks/code/amount-matches.py",
    "evals/agents/store/labels/standard.md",
]
INTERACTIVE = ROOT / "docs" / "interactive"
TEMPLATES = ROOT / "templates"
SKILLS = ROOT / "skills"
SCHEMA = "aot-evals/site@2"

# What the zip holds, as repository paths (directories by their tracked files). A relative link in
# its Markdown to anything else becomes a link to GitHub at the release tag, so every link works
# (tests/test_build_site.py).
BUNDLE = [
    "LICENSE",
    "NOTICE",
    "SECURITY.md",
    "docs/method.md",
    "docs/estimators.md",
    "docs/problems.md",
    "docs/statistics.md",
    "examples/store",
    "references",
    "templates",
]

LINK = re.compile(r"(\]\()([^)\s]+)(\))")
PIPE = re.compile(r"(?<!\\)\|")


def tag_for(version: str) -> str:
    return f"aot-evals--v{version}"


def version() -> str:
    return json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())["version"]


def commit() -> str | None:
    r = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True)
    return r.stdout.strip() or None if r.returncode == 0 else None


def absolute_links(text: str, source: Path, tag: str, keep: set[str] | None = None) -> str:
    """Relative links in `source` become links to the same file at the release tag on GitHub,
    except links to the repository paths in `keep`."""

    def fix(m: re.Match) -> str:
        target = m.group(2)
        if target.startswith(("http://", "https://", "mailto:", "#")):
            return m.group(0)
        path, _, anchor = target.partition("#")
        resolved = (source.parent / path).resolve().relative_to(ROOT).as_posix()
        if keep is not None and resolved in keep:
            return m.group(0)
        url = f"https://github.com/{REPO}/blob/{tag}/{resolved}" + (f"#{anchor}" if anchor else "")
        return f"{m.group(1)}{url}{m.group(3)}"

    return LINK.sub(fix, text)


def anchor(title: str) -> str:
    """GitHub's heading anchor, so section ids match the links in the docs: inline links become
    their text, then everything but word characters, hyphens and spaces goes."""
    title = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", title)
    return re.sub(r"[^\w\- ]", "", title.lower()).replace(" ", "-")


def sections(text: str, level: str = "## ") -> tuple[str, list[dict]]:
    """Split Markdown at headings of `level`: the text before the first one, and each section."""
    parts = re.split(rf"^{re.escape(level)}", text, flags=re.M)
    out = []
    for part in parts[1:]:
        title, _, body = part.partition("\n")
        body = re.sub(r"\n-{3,}\s*$", "", body.strip()).strip()
        m = re.match(r"(\d+)\. ", title.strip())
        out.append({"id": anchor(title.strip()), "title": title.strip(), "markdown": body,
                    "number": int(m.group(1)) if m else None})
    return parts[0].strip(), out


def cells(line: str) -> list[str]:
    """A table row's cells; `\\|` is a literal pipe inside a cell."""
    return [c.strip().replace("\\|", "|") for c in PIPE.split(line.strip().strip("|"))]


def tables(md: str) -> list[list[str]]:
    """Every Markdown table in `md`, as its lines."""
    out: list[list[str]] = []
    cur: list[str] = []
    for ln in md.splitlines() + [""]:
        if ln.startswith("|"):
            cur.append(ln)
        elif cur:
            out.append(cur)
            cur = []
    return out


def table(md: str, where: str, nth: int = 0) -> list[dict]:
    """The `nth` Markdown table in `md`, one dict per row keyed by its snake_case header."""
    found = tables(md)
    if len(found) <= nth or len(found[nth]) < 3:
        raise ValueError(f"{where}: no table")
    lines = found[nth]
    header = [("id" if h in ("#", "") else h.strip("`").lower().replace(" ", "_")) for h in cells(lines[0])]
    rows = []
    for ln in lines[2:]:
        row = cells(ln)
        if len(row) != len(header):
            raise ValueError(f"{where}: a row has {len(row)} cells, the header {len(header)}: {ln}")
        rows.append(dict(zip(header, row, strict=True)))
    return rows


def principles(md: str) -> list[dict]:
    """The numbered list under Principles: each item's bold lead as its title, and its full text."""
    items = re.findall(r"^(\d+)\. (.*?)(?=^\d+\. |^\S|\Z)", md, flags=re.M | re.S)
    out = []
    for n, body in items:
        text = " ".join(body.split())
        lead = re.match(r"\*\*(.+?)\*\*", text)
        out.append({"number": int(n), "title": lead.group(1).rstrip(".:") if lead else None, "markdown": text})
    return out


# The sections of docs/method.md the site parses, by anchor without the section number; the
# build fails if one goes missing.
METHOD_SECTIONS = {
    "principles": "principles",
    "parts": "the-four-parts-and-the-three-roles",
    "spec": "the-eval-spec",
    "commands": "commands",
    "report": "reportjson",
    "gates": "gates",
}


def method(tag: str) -> dict:
    text = absolute_links(METHOD.read_text(), METHOD, tag)
    title = text.splitlines()[0].removeprefix("# ").strip()
    intro, secs = sections(text.split("\n", 1)[1])
    secs = [s for s in secs if s["id"] != "contents"]
    lead = intro.split("\n\n")[0]
    # After the Contents list, up to the first rule, the preface.
    preface = re.split(r"^## Contents\s*$", text, flags=re.M)[1]
    preface = re.split(r"^-{3,}\s*$", preface, flags=re.M)[0]
    preface = "\n\n".join(p for p in preface.strip().split("\n\n") if not re.match(r"^\d+\. \[", p))
    numbers = [s["number"] for s in secs]
    if numbers != list(range(1, len(secs) + 1)):
        raise ValueError(f"docs/method.md: sections must be numbered 1..N in order, found {numbers}")
    by_id = {s["id"]: s for s in secs}
    by_name = {s["id"].split("-", 1)[-1]: s for s in secs}
    missing = [a for a in METHOD_SECTIONS.values() if a not in by_name]
    if missing:
        raise ValueError(f"docs/method.md: no section {', '.join(missing)}")
    return {"title": title, "lead": " ".join(lead.split()), "preface": preface.strip(), "sections": secs,
            "by_id": by_id, "by_name": by_name}


def guide(name: str, path: Path, tag: str) -> dict:
    """One guiding document: its title, the lead before its first section, and its sections."""
    text = absolute_links(path.read_text(), path, tag)
    title = text.splitlines()[0].removeprefix("# ").strip()
    intro, secs = sections(text.split("\n", 1)[1])
    return {"slug": name, "title": title, "intro": intro,
            "sections": [s for s in secs if s["id"] != "contents"]}


def terms(estimators: dict) -> list[dict]:
    """estimators.md's Terms: the Term table under each bold heading, one row per term. Other
    tables in a group, such as the worked 2×2 table, are examples, not terms."""
    sec = next((s for s in estimators["sections"] if s["id"] == "terms"), None)
    if sec is None:
        raise ValueError("docs/estimators.md: no Terms section")
    out = []
    groups = re.split(r"^\*\*(.+?)\*\*\s*$", sec["markdown"], flags=re.M)
    for k in range(1, len(groups), 2):
        group = groups[k].strip()
        where = f"estimators Terms, {group}"
        found = tables(groups[k + 1])
        nth = next((i for i, t in enumerate(found) if cells(t[0])[:1] == ["Term"]), None)
        if nth is None:
            raise ValueError(f"{where}: no Term table")
        for row in table(groups[k + 1], where, nth):
            out.append({"group": group, "term": row["term"].replace("**", ""), "meaning": row["meaning"],
                        "standard_term": row["standard_term"]})
    if not out:
        raise ValueError("docs/estimators.md: the Terms section has no tables")
    return out


def rules(estimators: dict) -> list[dict]:
    sec = next((s for s in estimators["sections"] if s["id"] == "10-the-rules-in-one-table"), None)
    if sec is None:
        raise ValueError("docs/estimators.md: no section 10, the rules")
    rows = table(sec["markdown"], "estimators §10 rules")
    for r in rows:
        r["number"] = int(r.pop("id"))
    return rows


def example(tag: str) -> dict:
    readme = EXAMPLE / "README.md"
    files = []
    for rel in EXAMPLE_FILES:
        p = EXAMPLE / rel
        if not p.is_file():
            raise ValueError(f"examples/store/{rel}: missing")
        files.append({"path": f"examples/store/{rel}", "content": p.read_text()})
    text = absolute_links(readme.read_text(), readme, tag)
    return {"title": text.splitlines()[0].removeprefix("# ").strip(),
            "markdown": text.split("\n", 1)[1].strip(), "files": files,
            "demo": "aot-evals demo"}


def plugin() -> dict:
    skills = []
    for f in sorted(SKILLS.glob("*/SKILL.md")):
        # Not strict YAML (descriptions hold ": "), so read the two fields as lines.
        lines = f.read_text().split("---")[1].strip().splitlines()
        front = dict(ln.split(": ", 1) for ln in lines if re.match(r"^(name|description): ", ln))
        skills.append({"name": front["name"], "command": f"/aot-evals:{front['name']}",
                       "description": " ".join(str(front["description"]).split())})
    return {
        "repo": f"https://github.com/{REPO}",
        "install": [f"claude plugin marketplace add {REPO}", "claude plugin install aot-evals@aot-evals"],
        "start": "/aot-evals:start",
        "skills": skills,
    }


def _tracked(p: Path) -> list[Path] | None:
    """The files git tracks under `p`, or None outside a git checkout."""
    r = subprocess.run(["git", "ls-files", "-z", "--", p.relative_to(ROOT).as_posix()], cwd=ROOT,
                       capture_output=True, text=True)
    if r.returncode != 0:
        return None
    return sorted(ROOT / f for f in r.stdout.split("\0") if f)


def bundle_files() -> list[Path]:
    files = []
    for entry in BUNDLE:
        p = ROOT / entry
        if p.is_dir():
            tracked = _tracked(p)
            files += tracked if tracked else sorted(f for f in p.rglob("*") if f.is_file())
        else:
            files.append(p)
    return [f for f in files if f.is_file() and "__pycache__" not in f.parts and f.name != ".DS_Store"]


def bundle_readme(v: str) -> str:
    tag = tag_for(v)
    return f"""# The aot-evals method, {v}

How to design, build, calibrate and run evals for a production agent, as plain files: an eval as
an estimator with four parts (estimand, sampling design, measurement model, decision rule), the
twelve problems they solve, the statistics behind every number, the reference for every command
and file, a worked example, findings from the literature, a catalog of public agent benchmarks,
and the templates. Read them, or point any coding agent at them. Apache License 2.0 (LICENSE, NOTICE).

| Start with | What it holds |
|---|---|
| docs/estimators.md | The structure: what an eval is, where evals go, the eval spec, the terms, the rules |
| docs/problems.md | Twelve problems every agent eval has to solve, each with a worked example |
| docs/statistics.md | The derivations: how many cases, trials and labels; when to trust a judge or a difference |
| docs/method.md | The reference: the roles, the files, the eval spec, every command, report.json and the gates |
| examples/store/ | The online store's support agent and refund subagent, with both evals |
| references/eval-best-practices.md | What the 2025-2026 literature says about evaluating agents, with sources |
| references/benchmarks.md, benchmarks.yaml | The public benchmark catalog, and how an agent is matched against it |
| references/situations.yaml | The conditions a request can put an agent in, which a bug-finding set should reach |
| references/agent-contract.md | How an agent is run as a command: what goes in on stdin and comes back on stdout |
| templates/ | A case, a code check and a judge spec to start from |

The Claude Code plugin runs this method on your own agent: https://github.com/{REPO}
(this is release {tag}).
"""


def write_zip(path: Path, v: str) -> None:
    """Sorted entries with a fixed timestamp and mode, so one version always builds the same bytes."""
    top = f"aot-evals-method-{v}"
    entries = [(f"{top}/README.md", bundle_readme(v).encode())]
    files = bundle_files()
    keep = {f.relative_to(ROOT).as_posix() for f in files}
    for f in files:
        data = f.read_bytes()
        if f.suffix == ".md":
            data = absolute_links(data.decode(), f, tag_for(v), keep).encode()
        entries.append((f"{top}/{f.relative_to(ROOT).as_posix()}", data))
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in sorted(entries):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.external_attr = 0o644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, data)


def build(today: str) -> dict:
    v = version()
    tag = tag_for(v)
    m = method(tag)
    sec = {k: m["by_name"][a]["markdown"] for k, a in METHOD_SECTIONS.items()}
    m.pop("by_id")
    m.pop("by_name")

    practices_text = absolute_links(PRACTICES.read_text(), PRACTICES, tag)
    p_intro, p_secs = sections(practices_text.split("\n", 1)[1])
    docs = {name: guide(name, path, tag) for name, path in GUIDES.items()}

    entries = benchmarks.load()
    problems = benchmarks.validate(entries)
    if problems:
        raise ValueError("references/benchmarks.yaml: " + "; ".join(problems[:5]))

    commands = table(sec["commands"], "method, Commands")
    for c in commands:
        c["name"] = c["command"].strip("`").split(" ")[0]
        c["command"] = c["command"].strip("`")

    zip_name = f"aot-evals-method-{v}.zip"
    return {
        "schema": SCHEMA,
        "version": v,
        "commit": commit(),
        "generated": today,
        "method": m,
        "principles": principles(sec["principles"]),
        "parts": table(sec["parts"], "method, the four parts"),
        "roles": table(sec["parts"], "method, the three roles", nth=1),
        "commands": commands,
        "spec_fields": table(sec["spec"], "method, the spec's fields"),
        "report_keys": table(sec["report"], "method, report.json"),
        "gates": [{**g, "id": g["id"].strip("`")} for g in table(sec["gates"], "method, Gates")],
        "judge_backends": table(BACKENDS.read_text(), "references/judge-backends.md"),
        "docs": docs,
        "terms": terms(docs["estimators"]),
        "rules": rules(docs["estimators"]),
        "example": example(tag),
        "practices": {"title": practices_text.splitlines()[0].removeprefix("# ").strip(), "intro": p_intro,
                      "sections": p_secs},
        "benchmarks": {
            "vocabulary": {
                "workloads": sorted(benchmarks.WORKLOADS), "interaction": sorted(benchmarks.INTERACTIONS),
                "environment": sorted(benchmarks.ENVIRONMENTS), "grading": sorted(benchmarks.GRADING),
                "harness": sorted(benchmarks.HARNESS), "good_for": sorted(benchmarks.GOOD_FOR),
                "status": sorted(benchmarks.STATUS), "data": sorted(benchmarks.DATA),
                "pii": sorted(benchmarks.PII),
            },
            "entries": entries,
        },
        "situations": benchmarks.situations(),
        "templates": [{"path": f.relative_to(ROOT).as_posix(), "content": f.read_text()}
                      for f in sorted(TEMPLATES.rglob("*")) if f.is_file()],
        "plugin": plugin(),
        "download": {"zip": zip_name, "url": f"https://github.com/{REPO}/releases/download/{tag}/{zip_name}"},
        "interactive": interactive(),
    }


def interactive() -> dict:
    """docs/interactive/: the manifest (widgets.json), one fragment per problem and the shared
    stylesheet. Every problem in problems.md has exactly one widget."""
    manifest = json.loads((INTERACTIVE / "widgets.json").read_text())
    site = manifest["site"]
    widgets = []
    for w in manifest["widgets"]:
        html = (INTERACTIVE / f"{w['slug']}.html").read_text()
        widgets.append({**w, "url": f"{site}{w['slug']}/", "html": html})
    numbers = sorted(w["problem"] for w in widgets)
    if numbers != list(range(1, len(widgets) + 1)):
        raise ValueError(f"docs/interactive/widgets.json: problems must be 1..N once each, found {numbers}")
    return {"site": site, "css": (INTERACTIVE / "widgets.css").read_text(), "widgets": widgets}


PREVIEW = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Montserrat:wght@500;600;700;800&family=Roboto:wght@400;500&display=swap">
<style>
body {{ margin: 0; background: #F9FAF9; color: #3F4541; font: 16px/1.5 "Roboto", system-ui, sans-serif; }}
main {{ max-width: 1200px; margin: 0 auto; padding: 32px 16px 64px; }}
h1 {{ margin: 4px 0 12px; font: 700 34px/1.15 "Montserrat", system-ui, sans-serif; color: #225734; }}
.eyebrow {{ margin: 0; font: 700 12px/1.3 "Montserrat", system-ui, sans-serif; letter-spacing: 0.08em; text-transform: uppercase; color: #6f9a2a; }}
.lead {{ max-width: 52em; font-size: 18px; }}
a {{ color: #225734; }}
{css}
</style></head>
<body><main>
{body}
</main></body></html>
"""


def write_previews(out: Path, doc: dict) -> None:
    """dist/interactive/: each widget on a page of its own, and an index of them."""
    d = out / "interactive"
    d.mkdir(parents=True, exist_ok=True)
    css = doc["interactive"]["css"]
    items = []
    for w in doc["interactive"]["widgets"]:
        body = (f'<p class="eyebrow">Problem {w["problem"]}</p>\n<h1>{w["title"]}</h1>\n'
                f'<p class="lead">{w["lead"]}</p>\n{w["html"]}\n'
                f'<p><a href="index.html">All problems</a></p>')
        (d / f"{w['slug']}.html").write_text(PREVIEW.format(title=w["title"], css=css, body=body))
        items.append(f'<li><a href="{w["slug"]}.html">{w["problem"]}. {w["title"]}</a></li>')
    (d / "index.html").write_text(PREVIEW.format(
        title="Interactive problems", css="",
        body='<h1>Interactive problems</h1>\n<ol style="list-style:none;padding:0">' + "".join(items) + "</ol>"))


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=str(ROOT / "dist"))
    ap.add_argument("--today", default=datetime.date.today().isoformat())
    args = ap.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    doc = build(args.today)
    (out / "evals.json").write_text(json.dumps(doc, indent=2, ensure_ascii=False, allow_nan=False) + "\n")
    write_zip(out / doc["download"]["zip"], doc["version"])
    write_previews(out, doc)
    print(f"wrote {out / 'evals.json'}, {out / doc['download']['zip']} and {out / 'interactive'}/")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
