"""The sampling design of a 2.0 eval (docs/v2-design.md §3; estimators §4; statistics §2): the
case fields that say how a case was chosen, `aot-evals draw`, and the clusters.

**Cases.** Every case names its `use_case` (the folder it is in) and its `pool`: `quality`, drawn
at random from the frame, or `bug_finding`, written to find failures. A quality case carries
`draw: {frame, seed, index, inclusion_prob}`, written by `draw`; one without it, or drawn from
another frame or seed than the spec's, is refused from the estimate (rule 6). A bug-finding case
never enters θ̂ (rule 5). `cluster` is the value of the spec's `cluster_key` field, defaulting to
the case id (rule 9).

**The draw.** `draw` reads the frame (an import in `data/export.manifest.json`; each row a JSON
object with an `id` or `trace_id`, a `use_case`, and the fields a case needs) and takes, in each
use case, the first n of a seeded random order of its rows (`stats.stratified_draw`), n from
`--n`, else `plan.yaml`, else the last draw. π = n / N for the rows that remain in the frame. A skip (PII that can't be
scrubbed, a duplicate) is recorded with its reason in `draw.json` and the next row of the same
order replaces it, never one chosen by hand (statistics §2.2). Drawing more later extends the same
order, so the earlier cases stay and their π is rewritten: an expansion, not a revision.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from . import stats
from .repo import POOLS, Eval
from .util import ContractError, load_json, now_iso, sha256_file, write_json

DRAW_FILE = "draw.json"
DRAW_SCHEMA = "aot-evals/draw@1"
# Fields of a frame row that become the case, as the agent and the checks receive them
# (v2-design §3). Everything else in the row stays in the frame.
CASE_FIELDS = ("trigger", "inputs", "start_state", "followups", "expected_end_state", "requirements",
               "rules_not_applicable", "failure_modes", "coverage_entries")
V1_CASE_FIELDS = {"category": "use_case", "set": "pool", "taxonomy_entries": "coverage_entries"}


# ---- case fields -------------------------------------------------------------------------------

def cluster_of(case: dict, cluster_key: str | None) -> str:
    """The case's cluster: its `cluster`, else the value of the eval's cluster_key field, else its
    id (every case its own cluster)."""
    if case.get("cluster") not in (None, ""):
        return str(case["cluster"])
    if cluster_key and cluster_key != "id" and case.get(cluster_key) not in (None, ""):
        return str(case[cluster_key])
    return str(case.get("id"))


def case_status(ev: Eval, case: dict) -> dict:
    """What a case is and whether it may count toward θ̂: {id, use_case, pool, cluster,
    inclusion_prob, counts, problems[], notes[]}. `counts` is about the design only; screening,
    the run and the spec decide the rest."""
    spec = ev.spec()
    est, design = spec.part("estimand"), spec.part("design")
    ucs = [u.get("id") for u in est.get("use_cases") or [] if isinstance(u, dict)]
    frame = (est.get("population") or {}).get("frame") if isinstance(est.get("population"), dict) else None
    seed = (design.get("quality_set") or {}).get("seed") if isinstance(design.get("quality_set"), dict) else None
    problems, notes = [], []
    cid = case.get("id")
    folder = case.get("_dir_use_case")
    uc = case.get("use_case")
    for old, new in V1_CASE_FIELDS.items():
        if old in case:
            problems.append(f"`{old}` is a 1.x field; 2.0 calls it `{new}` (aot-evals migrate --to 2)")
    if uc is None:
        problems.append("no `use_case`: it is required and names the case's folder")
    elif folder is not None and uc != folder:
        problems.append(f"`use_case` is {uc} but the case is in cases/{folder}/")
    elif ucs and uc not in ucs:
        problems.append(f"use case {uc} is not in the spec's estimand.use_cases")
    pool = case.get("pool")
    draw = case.get("draw")
    pi = None
    if pool is None:
        problems.append("no `pool`: quality or bug_finding")
    elif pool not in POOLS:
        problems.append(f"`pool` is {pool}; it is quality or bug_finding")
    elif pool == "quality":
        if not isinstance(draw, dict):
            problems.append("a quality case without `draw`: quality cases come from `aot-evals draw`, "
                            "never by hand (rule 6)")
        else:
            p = draw.get("inclusion_prob")
            if not isinstance(p, (int, float)) or isinstance(p, bool) or not 0 < p <= 1:
                problems.append("`draw.inclusion_prob` must be above 0 and at most 1")
            else:
                pi = float(p)
            if frame is not None and draw.get("frame") != frame:
                problems.append(f"drawn from frame {draw.get('frame')}, but the spec's frame is {frame}: "
                                "draw again")
            if seed is not None and draw.get("seed") != seed:
                problems.append(f"drawn with seed {draw.get('seed')}, but the spec's seed is {seed}: "
                                "draw again")
    elif draw is not None:
        notes.append("a bug-finding case's `draw` is ignored: it never enters θ̂ (rule 5)")
    return {"id": cid, "use_case": uc, "pool": pool, "cluster": cluster_of(case, design.get("cluster_key")),
            "inclusion_prob": pi, "counts": pool == "quality" and not problems,
            "problems": problems, "notes": notes, "path": case.get("_path")}


def case_issues(ev: Eval) -> list[dict]:
    """The cases whose design fields are wrong, for `validate`."""
    out = []
    try:
        cases = ev.cases()
    except ContractError as e:
        return [{"id": None, "path": None, "problems": [str(e)]}]
    for c in cases:
        st = case_status(ev, c)
        if st["problems"]:
            out.append(st)
    return out


def clusters(ev: Eval, statuses: list[dict]) -> dict:
    """The clusters of an eval's cases: G per pool, the largest, and those shared by the two pools,
    which must be disjoint by cluster key (rule 10)."""
    by_pool: dict[str, list[str]] = defaultdict(list)
    for s in statuses:
        if s["pool"] in POOLS:
            by_pool[s["pool"]].append(s["cluster"])
    q = by_pool.get("quality", [])
    sizes: dict[str, int] = defaultdict(int)
    for g in q:
        sizes[g] += 1
    largest = max(sizes.items(), key=lambda kv: (kv[1], kv[0])) if sizes else None
    shared = sorted(set(q) & set(by_pool.get("bug_finding", [])))
    return {"n": len(sizes), "n_bug_finding": len(set(by_pool.get("bug_finding", []))),
            "largest": ({"cluster": largest[0], "n_cases": largest[1], "share": largest[1] / len(q)}
                        if largest else None),
            "mean_size": (len(q) / len(sizes)) if sizes else None,
            "shared_with_bug_finding": shared}


# ---- the draw ----------------------------------------------------------------------------------

def draw_path(ev: Eval) -> Path:
    return ev.p(DRAW_FILE)


def load_draw(ev: Eval) -> dict:
    return load_json(draw_path(ev)) or {}


def frame_rows(ev: Eval, frame: str) -> list[dict]:
    from .importer import export_file, iter_rows

    try:
        path = export_file(ev.agent_system, frame)
    except (KeyError, FileNotFoundError) as e:
        raise ContractError(str(e).strip("'\"")) from None
    return [r for r in iter_rows(path) if isinstance(r, dict)]


def _row_id(row: dict) -> str | None:
    v = row.get("id", row.get("trace_id"))
    return None if v in (None, "") else str(v)


def _case_id(trace_id: str) -> str:
    import re

    return re.sub(r"[^A-Za-z0-9_.-]+", "-", trace_id).strip("-") or "case"


def plan_targets(ev: Eval) -> dict[str, int]:
    """Quality targets per use case from plan.yaml (`aot-evals plan --write`)."""
    from .util import load_yaml

    data = load_yaml(ev.p("plan.yaml")) or {}
    out = {}
    for row in data.get("rows") or []:
        if row.get("pool") == "quality" and isinstance(row.get("target"), int):
            out[row["use_case"]] = row["target"]
    return out


def draw(ev: Eval, n: dict[str, int] | None = None, skip: list[str] | None = None,
         reason: str | None = None, prune: bool = False, dry_run: bool = False) -> dict:
    """Draw (or extend) the quality set. Returns what was drawn, written, replaced and refused.

    `n` overrides plan.yaml's quality targets per use case. `skip` are trace ids to take out of
    the frame, with `reason`; each is logged and replaced from the same seeded order. Quality cases
    that the draw no longer holds (a smaller n, a new seed or frame, a skip) are removed only with
    `prune`; without it the draw refuses, since removing them by hand would make the set a quota."""
    spec = ev.spec()
    blocked = spec.blocked("draw")
    if blocked:
        raise ContractError("the spec does not say enough to draw:\n" + "\n".join(
            f"  - {i.field}: {i.why}" for i in blocked))
    est, design = spec.part("estimand"), spec.part("design")
    frame = est["population"]["frame"]
    seed = design["quality_set"]["seed"]
    ucs = [u["id"] for u in est["use_cases"]]
    cluster_key = design.get("cluster_key")
    log = load_draw(ev)
    if log and (log.get("frame") != frame or log.get("seed") != seed):
        log = {"skips": []}  # a new design: earlier skips and sizes belonged to the old frame or seed
    # a use case keeps its last draw unless plan.yaml or --n sizes it again
    last = {u: v.get("n") for u, v in (log.get("strata") or {}).items() if isinstance(v, dict)}
    targets = {**{u: k for u, k in last.items() if isinstance(k, int)}, **plan_targets(ev), **(n or {})}
    unknown = sorted(set(targets) - set(ucs))
    if unknown:
        raise ContractError(f"not use cases of this eval: {', '.join(unknown)}")
    if not targets:
        raise ContractError("no quality targets: `aot-evals plan --write` sizes them, or pass "
                            "--n USE_CASE=N")

    rows = frame_rows(ev, frame)
    by_id: dict[str, dict] = {}
    pop: dict[str, list[str]] = {u: [] for u in ucs}
    unassigned, outside, dupes, no_id = 0, defaultdict(int), 0, 0
    for r in rows:
        rid = _row_id(r)
        if rid is None:
            no_id += 1
            continue
        if rid in by_id:
            dupes += 1
            continue
        by_id[rid] = r
        uc = r.get("use_case")
        if uc in (None, ""):
            unassigned += 1
        elif uc not in pop:
            outside[str(uc)] += 1
        else:
            pop[uc].append(rid)

    skips = list(log.get("skips") or [])
    for tid in skip or []:
        if tid not in by_id:
            raise ContractError(f"no row {tid} in frame {frame}")
        if not reason:
            raise ContractError("a skip needs --reason: every skip is logged with why (rule 6)")
        if tid not in {s["trace_id"] for s in skips}:
            skips.append({"trace_id": tid, "use_case": by_id[tid].get("use_case"), "reason": reason,
                          "at": now_iso()})
    skipped = [s["trace_id"] for s in skips]
    sizes = {u: targets.get(u, 0) for u in ucs}
    d = stats.stratified_draw(pop, sizes, seed, skip=skipped)

    # the draw's own cases; a quality case written by hand is refused from θ̂ but never removed here
    existing = {c.get("id"): c for c in ev.cases() if c.get("pool") == "quality" and isinstance(c.get("draw"), dict)}
    on_disk = {c.get("_path"): c for c in ev.cases()}
    keep: dict[str, tuple[str, str]] = {}  # case id -> (use case, trace id)
    for uc in ucs:
        for tid in d["drawn"][uc]:
            keep[_case_id(tid)] = (uc, tid)
    extra = sorted(cid for cid in existing if cid not in keep)
    short = {u: {"wanted": sizes[u], "frame_size": d["frame_size"][u]}
             for u in ucs if sizes[u] > d["frame_size"][u]}
    result = {"frame": frame, "seed": seed, "targets": sizes, "short": short,
              "drawn": {u: len(d["drawn"][u]) for u in ucs}, "written": [], "updated": [],
              "removed": [], "beyond_draw": extra, "skips": skips,
              "frame_rows": {"total": len(rows), "unassigned": unassigned, "outside_use_cases": dict(outside),
                             "duplicates": dupes, "no_id": no_id}}
    if extra and not prune:
        result["refused"] = (f"{len(extra)} quality case(s) are no longer in the draw (e.g. {extra[0]}); "
                             "pass --prune to remove them, since the draw, not a person, decides which "
                             "cases are in the quality set (rule 6)")
        return result
    if dry_run:
        return result

    for cid in extra:
        path = ev.p(existing[cid]["_path"])
        path.unlink()
        result["removed"].append(existing[cid]["_path"])
    for cid, (uc, tid) in sorted(keep.items()):
        record = {"frame": frame, "seed": seed, "index": d["index"][tid],
                  "inclusion_prob": d["inclusion_probability"][tid]}
        old = existing.get(cid)
        if old is not None and old.get("use_case") == uc:
            case = {k: v for k, v in old.items() if not k.startswith("_")}
            if case.get("draw") == record:
                continue
            case["draw"] = record
            path = ev.p(old["_path"])
            result["updated"].append(old["_path"])
        else:
            row = by_id[tid]
            case = {"id": cid, "use_case": uc, "pool": "quality", "draw": record}
            if cluster_key and cluster_key != "id" and row.get(cluster_key) not in (None, ""):
                case[cluster_key] = row[cluster_key]
            case["cluster"] = cluster_of({**row, "id": cid, "cluster": row.get("cluster")}, cluster_key)
            for k in CASE_FIELDS:
                if k in row:
                    case[k] = row[k]
            if "trigger" not in case and isinstance(row.get("text"), str):
                case["trigger"] = {"type": "message", "text": row["text"]}
            case["provenance"] = {"source": f"export:{frame}", "export": frame, "trace_ref": tid,
                                  "synthetic": False}
            if row.get("source_trace") not in (None, ""):  # a handoff: the end-to-end trace it came from
                case["provenance"]["source_trace"] = row["source_trace"]
            path = ev.p("cases", uc, f"{cid}.json")
            same = on_disk.get(str(path.relative_to(ev.root)))
            if same is not None and old is None:  # a file already there for this trace: keep its edits
                case = {**{k: v for k, v in same.items() if not k.startswith("_")},
                        "use_case": uc, "pool": "quality", "draw": record}
            if old is not None:  # the same id under another use case: the frame moved it
                ev.p(old["_path"]).unlink()
                result["removed"].append(old["_path"])
            result["written"].append(str(path.relative_to(ev.root)))
        write_json(path, case)

    from .importer import export_file

    write_json(draw_path(ev), {
        "schema": DRAW_SCHEMA, "frame": frame, "seed": seed,
        "frame_sha256": sha256_file(export_file(ev.agent_system, frame)),
        "drawn_at": now_iso(),
        "strata": {u: {"frame_size": d["frame_size"][u], "n": len(d["drawn"][u]),
                       "inclusion_prob": (len(d["drawn"][u]) / d["frame_size"][u]
                                          if d["frame_size"][u] else None),
                       "replaced": d["replaced"][u]} for u in ucs},
        "frame_rows": result["frame_rows"],
        "skips": skips})
    return result


def render_draw(r: dict) -> str:
    lines = [f"draw from {r['frame']} (seed {r['seed']})"]
    for uc, n in r["drawn"].items():
        want = r["targets"].get(uc, 0)
        lines.append(f"  {uc:<28} {n:>5} of {want:<5}" + ("  (the frame holds fewer)" if uc in r["short"] else ""))
    fr = r["frame_rows"]
    if fr["unassigned"] or fr["outside_use_cases"] or fr["duplicates"] or fr["no_id"]:
        lines.append(f"  frame rows not drawn from: {fr['unassigned']} without a use_case, "
                     f"{sum(fr['outside_use_cases'].values())} in no use case of the spec, "
                     f"{fr['duplicates']} duplicate ids, {fr['no_id']} without an id")
    for s in r["skips"]:
        lines.append(f"  skipped {s['trace_id']}: {s['reason']}")
    if r.get("refused"):
        lines.append(f"refused: {r['refused']}")
        return "\n".join(lines)
    lines.append(f"  {len(r['written'])} written, {len(r['updated'])} updated, {len(r['removed'])} removed")
    return "\n".join(lines)
