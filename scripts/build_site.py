#!/usr/bin/env python3
"""Build the method's published data: `python3 scripts/build_site.py`.

    build_site.py [--out dist] [--today YYYY-MM-DD]

Writes two files, which the release workflow attaches to each GitHub release and the website
(mahalsystems.ai) imports:

- `evals.json`: the method as data. The commands, gates, measurements, experiments and report
  panels are parsed from the tables in docs/method.md (they stay the record), alongside the
  method's sections, the process, the practice findings, the benchmark catalog, the situations,
  the templates and the plugin's skills:

      {"schema": "aot-evals/site@1", "version": "0.4.1", "commit": "abc1234", "generated": "YYYY-MM-DD",
       "method": {...}, "principles": [...], "planes": [...], "commands": [...], "judge_backends": [...],
       "measurements": [...], "experiments": [...], "panels": [...], "gates": [...], "process": [...],
       "practices": {...}, "benchmarks": {...}, "situations": [...], "templates": [...], "plugin": {...},
       "download": {...}}

  Relative links in the Markdown become absolute links to the release tag on GitHub, so text read
  on the site still points somewhere real. Keys may be added within a schema version, never
  removed or renamed.
- `aot-evals-method-<version>.zip`: the method, references and templates as plain files, to
  read or hand to any coding agent without installing the plugin. The same version always
  builds the same bytes.

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
PRACTICES = ROOT / "references" / "eval-best-practices.md"
PROCESS = ROOT / "references" / "process"
TEMPLATES = ROOT / "templates"
SKILLS = ROOT / "skills"
SCHEMA = "aot-evals/site@1"

# What the zip holds, as repository paths. A relative link in its Markdown to anything else
# becomes a link to GitHub at the release tag, so every link works (tests/test_build_site.py).
BUNDLE = [
    "LICENSE",
    "NOTICE",
    "SECURITY.md",
    "docs/method.md",
    "references",
    "templates",
]

GUIDANCE = "†"
LINK = re.compile(r"(\]\()([^)\s]+)(\))")


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
    """GitHub's heading anchor, so section ids match the links in the docs."""
    return re.sub(r"[^\w\- ]", "", title.lower()).replace(" ", "-")


def sections(text: str, level: str = "## ") -> tuple[str, list[dict]]:
    """Split Markdown at headings of `level`: the text before the first one, and each section."""
    parts = re.split(rf"^{re.escape(level)}", text, flags=re.M)
    out = []
    for part in parts[1:]:
        title, _, body = part.partition("\n")
        body = re.sub(r"\n-{3,}\s*$", "", body.strip()).strip()
        out.append({"id": anchor(title.strip()), "title": title.strip(), "markdown": body})
    return parts[0].strip(), out


def cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def table(md: str, where: str) -> list[dict]:
    """The first Markdown table in `md`, one dict per row keyed by its snake_case header."""
    lines = [ln for ln in md.splitlines() if ln.startswith("|")]
    if len(lines) < 3:
        raise ValueError(f"{where}: no table")
    header = [("id" if h in ("#", "") else h.lower().replace(" ", "_")) for h in cells(lines[0])]
    rows = []
    for ln in lines[2:]:
        row = cells(ln)
        if len(row) != len(header):
            raise ValueError(f"{where}: a row has {len(row)} cells, the header {len(header)}: {ln}")
        rows.append(dict(zip(header, row, strict=True)))
    return rows


def ids(rows: list[dict], name_key: str | None = None) -> list[dict]:
    """Plain ids, a `guidance_only` flag from the † mark, and the name column as `name`."""
    for row in rows:
        raw = row["id"]
        row["id"] = raw.replace(GUIDANCE, "").strip()
        row["guidance_only"] = GUIDANCE in raw
        if name_key:
            row["name"] = row.pop(name_key)
    return rows


def principles(md: str) -> list[dict]:
    """The numbered list in §1: each item's bold lead as its title, and its full text."""
    items = re.findall(r"^(\d+)\. (.*?)(?=^\d+\. |^\S|\Z)", md, flags=re.M | re.S)
    out = []
    for n, body in items:
        text = " ".join(body.split())
        lead = re.match(r"\*\*(.+?)\*\*", text)
        out.append({"number": int(n), "title": lead.group(1).rstrip(".:") if lead else None, "markdown": text})
    return out


def method(tag: str) -> dict:
    text = absolute_links(METHOD.read_text(), METHOD, tag)
    title = text.splitlines()[0].removeprefix("# ").strip()
    intro, secs = sections(text.split("\n", 1)[1])
    secs = [s for s in secs if s["id"] != "contents"]
    # The text before the Contents list is the lead; after it, up to the first rule, the preface.
    lead = intro.split("\n\n")[0]
    preface = re.split(r"^## Contents\s*$", text, flags=re.M)[1]
    preface = re.split(r"^-{3,}\s*$", preface, flags=re.M)[0]
    preface = "\n\n".join(p for p in preface.strip().split("\n\n") if not re.match(r"^\d+\. \[", p))
    for s in secs:
        m = re.match(r"(\d+)\. ", s["title"])
        s["number"] = int(m.group(1)) if m else None
    by_number = {s["number"]: s for s in secs}
    if set(by_number) != set(range(1, 11)):
        raise ValueError(f"docs/method.md: expected sections 1-10, found {sorted(k for k in by_number if k)}")
    return {"title": title, "lead": " ".join(lead.split()), "preface": preface.strip(), "sections": secs,
            "by_number": by_number}


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


def bundle_files() -> list[Path]:
    files = []
    for entry in BUNDLE:
        p = ROOT / entry
        files += sorted(f for f in p.rglob("*") if f.is_file()) if p.is_dir() else [p]
    return [f for f in files if "__pycache__" not in f.parts and f.name != ".DS_Store"]


def bundle_readme(v: str) -> str:
    tag = tag_for(v)
    return f"""# The aot-evals method, {v}

How to design, build, calibrate and run evals for a production agent, as plain files: the method,
the step-by-step process, findings from the literature, a catalog of public agent benchmarks, and
the templates. Read them, or point any coding agent at them. Apache License 2.0 (LICENSE, NOTICE).

| Start with | What it holds |
|---|---|
| docs/method.md | The reference: principles, commands C0-C19 and their exit gates, judges, gates G1-G14 |
| references/process/README.md | The process in three phases and twelve steps, to a calibrated suite per agent |
| references/eval-best-practices.md | What the 2025-2026 literature says about evaluating agents, with sources |
| references/benchmarks.md, benchmarks.yaml | The public benchmark catalog, and how an agent is matched against it |
| references/situations.yaml | The conditions a request can put an agent in, which every suite should cover |
| references/agent-contract.md | How an agent is run as a command: what goes in on stdin and comes back on stdout |
| templates/ | A case, a code check and a judge spec to start from |

The Claude Code plugin runs this method on your own agent and enforces its gates:
https://github.com/{REPO} (this is release {tag}).
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
    sec = m.pop("by_number")

    practices_text = absolute_links(PRACTICES.read_text(), PRACTICES, tag)
    p_intro, p_secs = sections(practices_text.split("\n", 1)[1])

    process = []
    for f in [PROCESS / "README.md", *sorted(p for p in PROCESS.glob("*.md") if p.name != "README.md")]:
        text = absolute_links(f.read_text(), f, tag)
        process.append({"slug": "overview" if f.name == "README.md" else f.stem,
                        "title": text.splitlines()[0].removeprefix("# ").strip(),
                        "markdown": text.split("\n", 1)[1].strip()})

    entries = benchmarks.load()
    problems = benchmarks.validate(entries)
    if problems:
        raise ValueError("references/benchmarks.yaml: " + "; ".join(problems[:5]))

    planes = table(sections(sec[2]["markdown"], "### ")[1][0]["markdown"], "method §2.1 Three planes")
    for p in planes:
        p["id"], _, p["plane"] = p["plane"].strip("*").partition(". ")

    zip_name = f"aot-evals-method-{v}.zip"
    commands = ids(table(sec[4]["markdown"], "method §4 Commands"))
    for c in commands:
        c["command"] = c["command"].strip("`")
        c["guidance_only"] = c["exit_gate"].lower().startswith("guidance only")

    return {
        "schema": SCHEMA,
        "version": v,
        "commit": commit(),
        "generated": today,
        "method": m,
        "principles": principles(sec[1]["markdown"]),
        "planes": planes,
        "commands": commands,
        "judge_backends": table(sec[5]["markdown"], "method §5 Judges"),
        "measurements": ids(table(sec[6]["markdown"], "method §6 Measurements"), "measurement"),
        "experiments": ids(table(sec[7]["markdown"], "method §7 Experiments"), "experiment"),
        "panels": ids(table(sec[9]["markdown"], "method §9 panels"), "panel"),
        "gates": ids(table(sec[10]["markdown"], "method §10 Gates")),
        "process": process,
        "practices": {"title": practices_text.splitlines()[0].removeprefix("# ").strip(), "intro": p_intro,
                      "sections": p_secs},
        "benchmarks": {
            "vocabulary": {
                "workloads": sorted(benchmarks.WORKLOADS), "interaction": sorted(benchmarks.INTERACTIONS),
                "environment": sorted(benchmarks.ENVIRONMENTS), "grading": sorted(benchmarks.GRADING),
                "harness": sorted(benchmarks.HARNESS), "good_for": sorted(benchmarks.GOOD_FOR),
                "status": sorted(benchmarks.STATUS), "data": sorted(benchmarks.DATA), "pii": sorted(benchmarks.PII),
            },
            "entries": entries,
        },
        "situations": benchmarks.situations(),
        "templates": [{"path": f.relative_to(ROOT).as_posix(), "content": f.read_text()}
                      for f in sorted(TEMPLATES.rglob("*")) if f.is_file()],
        "plugin": plugin(),
        "download": {"zip": zip_name, "url": f"https://github.com/{REPO}/releases/download/{tag}/{zip_name}"},
    }


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
    print(f"wrote {out / 'evals.json'} and {out / doc['download']['zip']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
