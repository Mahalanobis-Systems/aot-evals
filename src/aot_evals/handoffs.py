"""Frames of handoffs (estimators rule 4; statistics §1.3, §2.1): a component eval's population is the
inputs the orchestrator actually hands the component, so its frame is extracted from end-to-end
traces, never written by hand.

**The trace.** A row of an end-to-end frame (an import in `data/export.manifest.json`) records each
handoff across a context boundary in a `handoffs` list:

```json
{"id": "tr_1417", "use_case": "refund", "trigger": {...},
 "handoffs": [{"to": "refund-subagent", "use_case": "full-refund", "order_template": "t-07",
               "trigger": {"type": "handoff", "text": "Refund order 5521 ..."}, "inputs": {...},
               "start_state": {...}, "expected_end_state": {...}}]}
```

`to` names the component as agent.yaml's `components` does. The other fields are what the
component receives and how its case is graded, the fields a frame row carries (v2-design §3), plus
the component's `use_case` and whatever field its eval's `cluster_key` names. A handoff may nest
them under `input` instead.

**The extraction.** `aot-evals --eval <component eval> handoffs` reads the end-to-end eval's frame
(or `--from`), keeps every handoff into the eval's component, and imports them as a new frame:
one row per handoff, with id `<trace>.h<k>` (k counts the trace's handoffs into this component),
`source_trace`, and `source_use_case` (the end-to-end use case of the trace). The manifest entry
records `handoffs: {component, from, from_sha256, traces, traces_with_handoff,
source_use_cases, multi}`, so the component eval's spec can check that its frame is what the
component receives (rule 4) and that it comes from the end-to-end eval's current frame (rule 26).
Handoffs from one trace are related: when a trace hands off more than once, the summary says so,
and `cluster_key: source_trace` counts them as one piece of evidence (rule 9).

`--scan` reads a frame and counts the handoffs into each component: where the traces show context
boundaries, set against agent.yaml's inventory.
"""

from __future__ import annotations

import json

from .importer import export_file, iter_rows, manifest_path
from .util import ContractError, load_json, now_iso, sha256_file, write_json


def handoffs_of(row: dict) -> list[dict]:
    hs = row.get("handoffs") if isinstance(row, dict) else None
    return [h for h in hs if isinstance(h, dict) and h.get("to")] if isinstance(hs, list) else []


def _trace_id(row: dict) -> str | None:
    v = row.get("id", row.get("trace_id"))
    return str(v) if v not in (None, "") else None


def scan(rows) -> dict[str, dict]:
    """{component: {handoffs, traces, source_use_cases{uc: n}}} over a frame's rows."""
    out: dict[str, dict] = {}
    for row in rows:
        seen = set()
        for h in handoffs_of(row):
            to = str(h["to"])
            d = out.setdefault(to, {"handoffs": 0, "traces": 0, "source_use_cases": {}})
            d["handoffs"] += 1
            uc = row.get("use_case") or "(none)"
            d["source_use_cases"][uc] = d["source_use_cases"].get(uc, 0) + 1
            if to not in seen:
                d["traces"] += 1
                seen.add(to)
    return out


def rows_for(rows, component: str) -> tuple[list[dict], dict]:
    """The frame rows of the handoffs into `component`, and what the extraction saw."""
    out: list[dict] = []
    traces = with_handoff = multi = 0
    per_uc: dict[str, int] = {}
    for row in rows:
        traces += 1
        tid = _trace_id(row)
        hs = [h for h in handoffs_of(row) if str(h["to"]) == component]
        if not hs or tid is None:
            continue
        with_handoff += 1
        multi += len(hs) > 1
        for k, h in enumerate(hs):
            r = {kk: v for kk, v in h.items() if kk not in ("to", "input")}
            if isinstance(h.get("input"), dict):
                r = {**h["input"], **r}
            if "trigger" not in r and isinstance(r.get("text"), str):
                r["trigger"] = {"type": "handoff", "text": r.pop("text")}
            r["id"] = f"{tid}.h{k}"
            r["source_trace"] = tid
            r["source_use_case"] = row.get("use_case")
            out.append(r)
            uc = row.get("use_case") or "(none)"
            per_uc[uc] = per_uc.get(uc, 0) + 1
    return out, {"traces": traces, "traces_with_handoff": with_handoff, "multi": multi,
                 "source_use_cases": per_uc}


def _entry(ev, export_id: str) -> dict | None:
    return next((x for x in ev.exports() if isinstance(x, dict) and x.get("id") == export_id), None)


def system_frame(agent_dir) -> tuple[str | None, str | None]:
    """The end-to-end eval's id and its population frame."""
    for e in agent_dir.evals():
        try:
            unit = (e.spec().part("estimand").get("unit") or {})
        except ContractError:
            continue
        if isinstance(unit, dict) and unit.get("kind") == "system":
            pop = e.spec().part("estimand").get("population") or {}
            return e.id, (pop.get("frame") if isinstance(pop, dict) else None)
    return None, None


def extract(e, source: str | None = None, out_id: str | None = None, dry_run: bool = False) -> dict:
    """Extract the handoffs into a component eval's component from an end-to-end frame, and import
    them as the eval's frame. Returns the manifest entry (with `dry_run`, the entry it would write)."""
    est = e.spec().part("estimand")
    unit = est.get("unit") if isinstance(est.get("unit"), dict) else {}
    if unit.get("kind") != "component" or not unit.get("component"):
        raise ContractError(f"{e.id} is not a component eval (estimand.unit.kind: component, with its "
                            "component): only a component's frame is its handoffs")
    component = unit["component"]
    agent_dir = e.agent_system
    if source is None:
        _, source = system_frame(agent_dir)
        if not source:
            raise ContractError("no end-to-end frame to read: pass --from IMPORT_ID, or set the end-to-end "
                                "eval's estimand.population.frame")
    parent = _entry(agent_dir, source)
    if parent is None:
        raise ContractError(f"no import '{source}' in data/export.manifest.json")
    if out_id is None:
        pop = est.get("population") if isinstance(est.get("population"), dict) else {}
        out_id = pop.get("frame")
        if not out_id:
            raise ContractError("pass --id: the eval's estimand.population.frame names no frame yet")
    if _entry(agent_dir, out_id) is not None:
        raise ContractError(f"import '{out_id}' is already in data/export.manifest.json; pass --id for a "
                            "new frame (and point estimand.population.frame at it)")
    src = export_file(agent_dir, source)
    rows, seen = rows_for(iter_rows(src), component)
    entry = {"id": out_id, "source": f"handoffs into {component}, extracted from {source}",
             "query": f"handoffs[].to == {component}", "window": parent.get("window"),
             "rows": len(rows), "date": now_iso(), "file": None, "sha256": None,
             "notes": None,
             "handoffs": {"component": component, "from": source, "from_sha256": parent.get("sha256"),
                          **seen}}
    if dry_run:
        return entry
    dest = agent_dir.p("data", "exports", out_id, "handoffs.jsonl")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows))
    entry.update(file=str(dest.relative_to(agent_dir.root)), sha256=sha256_file(dest))
    data = load_json(manifest_path(agent_dir)) or {"exports": []}
    if isinstance(data, list):
        data = {"exports": data}
    data.setdefault("exports", []).append(entry)
    write_json(manifest_path(agent_dir), data)
    return entry


def render_extract(entry: dict, cluster_key: str | None) -> str:
    h = entry["handoffs"]
    lines = [f"{entry['rows']} handoff(s) into {h['component']} from {h['traces_with_handoff']} of "
             f"{h['traces']} trace(s) in {h['from']}"
             + ("" if entry.get("file") else " (dry run: nothing written)")]
    if h["source_use_cases"]:
        lines.append("  from end-to-end use cases: " + ", ".join(
            f"{k} {v}" for k, v in sorted(h["source_use_cases"].items(), key=lambda kv: -kv[1])))
    if entry.get("file"):
        lines.append(f"  imported as {entry['id']} ({entry['file']})")
    if h["multi"]:
        lines.append(f"  {h['multi']} trace(s) hand off more than once: their handoffs are related"
                     + ("" if cluster_key == "source_trace" else
                        "; `cluster_key: source_trace` counts each trace once (rule 9)"))
    if not entry["rows"]:
        lines.append("  no handoffs: the traces record none into this component (a `handoffs` list "
                     "with `to` on each trace row)")
    return "\n".join(lines)


def scan_frame(agent_dir, source: str | None = None) -> dict:
    """The handoffs in a frame, by component, beside agent.yaml's inventory and each placement."""
    from . import boundaries

    if source is None:
        _, source = system_frame(agent_dir)
        if not source:
            raise ContractError("no end-to-end frame to read: pass --from IMPORT_ID")
    counts = scan(iter_rows(export_file(agent_dir, source)))
    known = {r["id"]: r for r in boundaries.plan(agent_dir.agent())}
    rows = []
    for to, d in sorted(counts.items(), key=lambda kv: -kv[1]["handoffs"]):
        k = known.get(to)
        rows.append({"component": to, **d, "in_agent_yaml": k is not None,
                     "placement": k["placement"] if k else None, "why": k["why"] if k else
                     f"{to} receives handoffs but is not in agent.yaml's components: add it, with its kind, "
                     "context and whether it ships separately"})
    return {"frame": source, "components": rows,
            "not_seen": sorted(set(known) - set(counts))}


def render_scan(s: dict) -> str:
    lines = [f"handoffs in {s['frame']}:"]
    if not s["components"]:
        lines.append("  none: the traces record no handoffs (a `handoffs` list with `to` on each row)")
    for r in s["components"]:
        lines.append(f"  {r['component']:<22} {r['handoffs']} handoff(s) in {r['traces']} trace(s)")
        lines.append(f"      {r['why']}")
    for n in s["not_seen"]:
        lines.append(f"  {n:<22} in agent.yaml, no handoffs in this frame")
    return "\n".join(lines)
