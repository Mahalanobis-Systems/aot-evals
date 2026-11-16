"""What the paired comparison of an eval (decision.py) needs to know about the runs on each
side: the candidate's declared independent variable and the manifest fields it may change, whether
the two sides are one build apart (otherwise the comparison is refused), and where comparisons are
saved (`report/comparisons/`).
"""

from __future__ import annotations

import hashlib
import json
import re

from .repo import Evals
from .results import BUILD_FIELDS, Context, manifest_view
from .util import write_json

# Declared variable (the part before "=" in `run --variable`) -> manifest fields it may change.
VARIABLES = {
    "prompt": {"agent_commit", "invoke"},
    "skills": {"agent_commit", "invoke"},
    "instructions": {"agent_commit", "invoke"},
    "tools": {"agent_commit", "invoke", "fakes_sha256"},
    "code": {"agent_commit", "invoke"},
    "config": {"agent_commit", "invoke"},
    "model": {"agent_commit", "invoke", "model_ids", "model_ids_observed"},
    "harness": {"agent_commit", "invoke", "harness"},
    "environment": {"fakes_sha256"},
    "fakes": {"fakes_sha256"},
}

view = manifest_view


def variable_of(manifests: list[dict]) -> str | None:
    for m in manifests:
        if m.get("declared_variable"):
            return str(m["declared_variable"])
    return None


def allowed_fields(variable: str | None) -> set[str]:
    if not variable:
        return set()
    return VARIABLES.get(variable.split("=", 1)[0].strip().lower(), set())


# Per-item fields: a side's runs may each cover some of the items (runs split by use case), so
# they are merged by key and differ only where the same key has a different value.
MERGED = ("case_set", "checks", "judges", "model_ids_observed")


def _keyed(field: str, v) -> dict:
    if field == "judges":
        return {j[0]: list(j[1:]) for j in v or []}
    if field == "model_ids_observed":
        return {site: sorted(models) for site, models in (v or {}).items()}
    return dict(v) if isinstance(v, dict) else {"*": v}


def side_view(side: str, manifests: list[dict]) -> tuple[dict, list[str]]:
    """One view of a side's runs, and what stops them being one measurement of one build. Runs
    of one build over different cases (split by use case, to pace a rate-limited runtime) are
    one side; runs of different builds, or that measured a case or check differently, are not."""
    views = [view(m) for m in manifests]
    problems = []
    merged = {f: views[0][f] for f in (*BUILD_FIELDS, "agent_dirty")}
    for m, v in zip(manifests[1:], views[1:], strict=True):
        d = [f for f in BUILD_FIELDS if json.dumps(v[f], sort_keys=True, default=str)
             != json.dumps(merged[f], sort_keys=True, default=str)]
        if d:
            problems.append(f"{side} runs are not one build: {manifests[0]['run_id']} and "
                            f"{m['run_id']} differ on {d}")
    for f in MERGED:
        acc: dict = {}
        for m, v in zip(manifests, views, strict=True):
            for key, val in _keyed(f, v[f]).items():
                if f == "model_ids_observed":
                    acc[key] = sorted(set(acc.get(key, [])) | set(val))
                elif key in acc and acc[key] != val:
                    problems.append(f"{side} runs measured {key!r} differently ({f}): see {m['run_id']}")
                else:
                    acc[key] = val
        merged[f] = acc
    if any(v["agent_dirty"] for v in views):
        problems.append(f"{side} ran with uncommitted agent changes: what ran cannot be named")
    return merged, problems


def side_differences(a: dict, b: dict) -> list[str]:
    """Build fields that differ, and per-item fields that differ on an item both sides have."""
    def norm(v):
        return json.dumps(v, sort_keys=True, default=str)
    out = [f for f in BUILD_FIELDS if norm(a[f]) != norm(b[f])]
    out += [f for f in MERGED if any(norm(a[f][k]) != norm(b[f][k]) for k in set(a[f]) & set(b[f]))]
    return out


def comparability(base: Context, cand: Context) -> list[str]:
    problems = []
    sides = {}
    for side, ctx in (("baseline", base), ("candidate", cand)):
        if not ctx.manifests:
            problems.append(f"no {side} run")
            continue
        sides[side], p = side_view(side, ctx.manifests)
        problems += p
    if problems:
        return problems
    variable = variable_of(cand.manifests)
    diffs = side_differences(sides["baseline"], sides["candidate"])
    undeclared = [d for d in diffs if d not in allowed_fields(variable)]
    if undeclared:
        hint = (f"declared variable {variable!r} covers {sorted(allowed_fields(variable))}" if variable
                else "the candidate declared no variable (run --variable KIND=VALUE)")
        problems.append(f"manifests differ on {undeclared}; {hint}")
    return problems


# ---- paired statistics ---------------------------------------------------------------------------

def comparison_path(ev: Evals, comp: dict):
    """A short, stable name: the declared variable and a hash of both sides' run ids. Joining
    the run ids themselves overflowed the file-name limit with six candidate runs."""
    sides = f"{comp['candidate']}|{comp['baseline']}"
    digest = hashlib.sha256(sides.encode()).hexdigest()[:12]
    label = re.sub(r"[^A-Za-z0-9._-]+", "-", comp.get("declared_variable") or "candidate")[:40].strip("-")
    return ev.p("report", "comparisons", f"{label or 'candidate'}-{digest}.json")


def save(ev: Evals, comp: dict) -> str:
    path = comparison_path(ev, comp)
    write_json(path, comp)
    return str(path)


def latest_for(ev: Evals, baseline_runs: list[str]) -> dict | None:
    d = ev.p("report", "comparisons")
    if not d.exists():
        return None
    key = "+".join(baseline_runs)
    found = []
    for f in d.glob("*.json"):
        c = json.loads(f.read_text())
        if c.get("baseline") == key:
            found.append(c)
    return max(found, key=lambda c: c.get("generated", "")) if found else None


