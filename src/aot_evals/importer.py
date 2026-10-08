"""C0 `import`: bring a data export into `evals/data/` and record where it came from.

The export itself is git-ignored; the manifest entry is committed. Every downstream number has
to trace back to an entry here or to a committed case (G12). Nothing in this plugin calls a live
vendor API: the team exports from its observability stack and imports the file.
"""

from __future__ import annotations

import csv
import json
import re
import shutil
from pathlib import Path

from .repo import Evals
from .util import load_json, now_iso, sha256_file, write_json


def count_rows(path: Path) -> int | None:
    suffix = path.suffix.lower()
    try:
        if suffix in (".jsonl", ".ndjson"):
            with path.open() as f:
                return sum(1 for line in f if line.strip())
        if suffix in (".csv", ".tsv"):
            with path.open(newline="") as f:
                reader = csv.reader(f, delimiter="\t" if suffix == ".tsv" else ",")
                return max(0, sum(1 for _ in reader) - 1)
        if suffix == ".json":
            data = json.loads(path.read_text())
            if isinstance(data, list):
                return len(data)
            for key in ("data", "rows", "records", "traces", "spans", "items"):
                if isinstance(data, dict) and isinstance(data.get(key), list):
                    return len(data[key])
    except (OSError, json.JSONDecodeError, csv.Error):
        return None
    return None


def iter_rows(path: Path):
    suffix = path.suffix.lower()
    if suffix in (".jsonl", ".ndjson"):
        with path.open() as f:
            for line in f:
                if line.strip():
                    yield json.loads(line)
    elif suffix in (".csv", ".tsv"):
        with path.open(newline="") as f:
            yield from csv.DictReader(f, delimiter="\t" if suffix == ".tsv" else ",")
    elif suffix == ".json":
        data = json.loads(path.read_text())
        if isinstance(data, dict):
            data = next((data[k] for k in ("data", "rows", "records", "traces", "spans", "items")
                         if isinstance(data.get(k), list)), [])
        yield from data
    else:
        raise ValueError(f"unsupported export format: {path.suffix} (use .jsonl, .csv, .tsv, .json)")


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:60] or "export"


def manifest_path(ev: Evals) -> Path:
    return ev.p("data", "export.manifest.json")


def import_export(ev: Evals, src: Path, *, source: str, query: str, window: str,
                  export_id: str | None = None, notes: str | None = None) -> dict:
    if not src.is_file():
        raise FileNotFoundError(src)
    data = load_json(manifest_path(ev)) or {"exports": []}
    if isinstance(data, list):
        data = {"exports": data}
    existing = {e.get("id") for e in data["exports"]}
    export_id = export_id or f"{now_iso()[:10]}-{_slug(src.stem)}"
    if export_id in existing:
        raise ValueError(f"export id {export_id!r} already in the manifest; pass --id")

    dest_dir = ev.p("data", "exports", export_id)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / src.name
    shutil.copy2(src, dest)
    entry = {
        "id": export_id,
        "source": source,
        "query": query,
        "window": window,
        "rows": count_rows(dest),
        "date": now_iso(),
        "file": str(dest.relative_to(ev.root)),
        "sha256": sha256_file(dest),
        "notes": notes,
    }
    data["exports"].append(entry)
    write_json(manifest_path(ev), data)
    return entry


def export_file(ev: Evals, export_id: str) -> Path:
    for e in ev.exports():
        if e.get("id") == export_id:
            p = ev.p(e["file"])
            if not p.exists():
                raise FileNotFoundError(f"{p}: the export is listed in the manifest but not on "
                                        "this machine (exports are git-ignored; re-import it)")
            return p
    raise KeyError(f"no export {export_id!r} in data/export.manifest.json")
