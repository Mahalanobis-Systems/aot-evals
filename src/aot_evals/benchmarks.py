"""The public benchmark catalog (references/benchmarks.yaml) and how Phase 1 matches an agent to it.

Phase 1 runs from this local copy: no web search, no model call. `match()` scores every catalog
entry against the agent's workloads and task types and returns the best fits with the reason each
might fit. Phase 2 may search the web for newer benchmarks and propose additions to the catalog
(references/benchmarks.md says how). The catalog's fields and vocabularies are in
references/benchmarks.md; `validate()` enforces them, and tests/test_benchmarks.py runs it.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / "references" / "benchmarks.yaml"
SITUATIONS = ROOT / "references" / "situations.yaml"

WORKLOADS = {
    "customer-support", "crm", "sales", "retail", "travel", "finance", "legal", "healthcare", "science",
    "education", "hr", "it-ops", "devops", "coding", "code-review", "ml-engineering", "data-analysis", "sql",
    "spreadsheets", "documents", "email-calendar", "workflow-automation", "research", "web-browsing",
    "computer-use", "mobile", "shopping", "knowledge-qa", "memory", "multi-agent", "planning", "safety",
    "security", "tool-calling", "general-assistant", "games", "embodied", "telecom", "government",
    "manufacturing", "insurance", "logistics", "real-estate",
}
INTERACTIONS = {"single-turn", "multi-turn-scripted", "multi-turn-simulated-user", "autonomous-long-horizon"}
ENVIRONMENTS = {"static", "api-sandbox", "database", "browser", "desktop", "mobile", "filesystem", "terminal",
                "containers", "mixed"}
GRADING = {"exact-match", "state-diff", "unit-tests", "programmatic-check", "llm-judge", "human", "pass^k",
           "trajectory-check"}
HARNESS = {"inspect_evals", "hal", "agentbeats", "own-repo", "none"}
GOOD_FOR = {"grading-design", "case-template", "baseline", "user-simulator", "sandbox-design", "privacy-pattern",
            "taxonomy"}
STATUS = {"active", "frozen", "saturated", "deprecated"}
DATA = {"synthetic", "real-public", "real-scraped", "mixed"}
PII = {"none", "possible", "yes"}
REQUIRED = ("id", "name", "year", "by", "workloads", "task_types", "interaction", "environment", "state_checked",
            "tools", "grading", "size", "data", "pii", "license", "harness", "status", "links", "good_for",
            "fit", "caveats")

_STOP = {"a", "an", "the", "and", "or", "of", "to", "in", "on", "for", "with", "by", "from", "at", "into",
         "its", "it", "is", "are", "be", "as", "that", "this", "under", "over", "about", "up", "out", "one",
         "two", "new", "them", "their", "then", "than", "when", "which", "who", "what", "how", "any", "all",
         "each", "per", "via", "using", "use", "used", "user", "users", "agent", "agents", "task", "tasks"}


def load(path: Path = CATALOG) -> list[dict]:
    import yaml

    data = yaml.safe_load(path.read_text()) or []
    if not isinstance(data, list):
        raise ValueError(f"{path}: expected a list of entries")
    return data


def situations(path: Path = SITUATIONS) -> list[dict]:
    """The situations vocabulary (references/situations.yaml): the columns of the golden test case
    grid, each with what it catches, its default check, whether it applies to nearly every agent,
    and the catalog entries that established it."""
    import yaml

    data = yaml.safe_load(path.read_text()) or []
    if not isinstance(data, list):
        raise ValueError(f"{path}: expected a list of situations")
    return data


def validate(entries: list[dict], vocab: list[dict] | None = None) -> list[str]:
    """Every problem in the catalog, as 'id: what is wrong'. An empty list means it is valid."""
    problems: list[str] = []
    seen: set[str] = set()
    situation_ids = {s.get("id") for s in (vocab if vocab is not None else situations())}

    def bad(e: dict, msg: str) -> None:
        problems.append(f"{e.get('id', '?')}: {msg}")

    def check_set(e: dict, key: str, allowed: set[str], many: bool) -> None:
        v = e.get(key)
        vals = v if many else [v]
        if many and not isinstance(v, list):
            bad(e, f"{key} must be a list")
            return
        for x in vals:
            if x not in allowed:
                bad(e, f"{key} has {x!r}, not in the vocabulary")

    for e in entries:
        if not isinstance(e, dict):
            problems.append(f"entry is not a mapping: {e!r}")
            continue
        for k in REQUIRED:
            if k not in e:
                bad(e, f"missing {k}")
        eid = e.get("id")
        if not isinstance(eid, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]*", eid):
            bad(e, "id must be a lowercase slug")
        elif eid in seen:
            bad(e, "duplicate id")
        else:
            seen.add(eid)
        if not isinstance(e.get("year"), int) or not 2010 <= e["year"] <= 2030:
            bad(e, "year must be an int between 2010 and 2030")
        check_set(e, "workloads", WORKLOADS, True)
        if isinstance(e.get("workloads"), list) and not 1 <= len(e["workloads"]) <= 5:
            bad(e, "workloads needs 1 to 5 tags")
        if not isinstance(e.get("task_types"), list) or not 2 <= len(e["task_types"]) <= 6:
            bad(e, "task_types needs 2 to 6 items")
        for k in ("task_types", "tools"):
            if isinstance(e.get(k), list) and any(not isinstance(x, str) for x in e[k]):
                bad(e, f"{k} items must be plain strings")
        check_set(e, "interaction", INTERACTIONS, False)
        check_set(e, "environment", ENVIRONMENTS, False)
        if not isinstance(e.get("state_checked"), bool):
            bad(e, "state_checked must be true or false")
        check_set(e, "grading", GRADING, True)
        if e.get("size") is not None and not (isinstance(e["size"], int) and e["size"] > 0):
            bad(e, "size must be a positive int or null")
        check_set(e, "data", DATA, False)
        check_set(e, "pii", PII, False)
        check_set(e, "harness", HARNESS, True)
        check_set(e, "status", STATUS, False)
        check_set(e, "good_for", GOOD_FOR, True)
        if "situations" in e:
            check_set(e, "situations", situation_ids, True)
        links = e.get("links") or {}
        if not isinstance(links, dict) or not any(links.get(k) for k in ("paper", "github", "website")):
            bad(e, "links needs at least one of paper, github, website")
        for k in ("fit", "caveats"):
            if not isinstance(e.get(k), str) or len(e[k].split()) < 6:
                bad(e, f"{k} must be at least a sentence")
    return problems


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9][a-z0-9+#-]*", text.lower()) if w not in _STOP and len(w) > 2}


def match(entries: list[dict], workloads: list[str], tasks: list[str], limit: int = 8,
          include_saturated: bool = False) -> list[dict]:
    """The catalog entries that best fit an agent, scored by workload overlap and by the words its
    task types share with the entry's. Each result carries `score` and `why`, the matched tags and
    words, so the reader can see the reason and judge it."""
    want_tags = set(workloads)
    task_words = set()
    for t in tasks:
        task_words |= _words(t)
    results = []
    for e in entries:
        if e.get("status") == "deprecated" or (e.get("status") == "saturated" and not include_saturated):
            continue
        tags = want_tags & set(e.get("workloads") or [])
        entry_words = set()
        for t in e.get("task_types") or []:
            entry_words |= _words(t)
        words = task_words & entry_words
        score = 3 * len(tags) + len(words)
        if score == 0:
            continue
        results.append({**e, "score": score,
                        "why": {"workloads": sorted(tags), "words": sorted(words)}})
    results.sort(key=lambda r: (-r["score"], -(r.get("year") or 0), r["id"]))
    return results[:limit]


def situations_for(matches: list[dict], vocab: list[dict] | None = None) -> list[dict]:
    """The situations the grid should have columns for: every universal one, plus any that a
    matched benchmark tests. Each carries `from`, the matched benchmarks that test it (names), so
    the report can say where the column came from."""
    vocab = vocab if vocab is not None else situations()
    out = []
    for s in vocab:
        tested_by = [m["name"] for m in matches if s["id"] in (m.get("situations") or [])]
        if s.get("universal") or tested_by:
            out.append({**s, "tested_by": tested_by})
    return out


def render(matches: list[dict], vocab: list[dict] | None = None) -> str:
    """Matches as plain text for the terminal and the discovery report, with the situations the
    matches say the agent's cases should cover."""
    if not matches:
        return "No catalog entry fits these workloads or task types."
    out = []
    cols = situations_for(matches, vocab)
    if cols:
        lines = ["Situations to cover (columns of the golden test case grid):"]
        for s in cols:
            src = ("from " + ", ".join(s["tested_by"])) if s["tested_by"] else "applies to nearly every agent"
            lines.append(f"  {s['name']} ({s['short']}) · {src}\n"
                         f"    catches: {s['catches']} · check: {s['check']}")
        out.append("\n".join(lines))
    for m in matches:
        tags = ", ".join(m["why"]["workloads"]) or "none"
        words = ", ".join(m["why"]["words"]) or "none"
        size = f"{m['size']} tasks" if m.get("size") else "size unknown"
        sits = f"\n  situations it tests: {', '.join(m['situations'])}" if m.get("situations") else ""
        out.append(f"{m['name']} ({m['year']}, {m['by']}) · score {m['score']} · {size} · {m['status']}\n"
                   f"  matches: workloads {tags}; words {words}{sits}\n"
                   f"  fit: {m['fit'].strip()}\n"
                   f"  caveats: {m['caveats'].strip()}\n"
                   f"  good for: {', '.join(m['good_for'])} · grading: {', '.join(m['grading'])}"
                   f" · data: {m['data']}, pii {m['pii']} · license: {m['license']}\n"
                   f"  {m['links'].get('paper') or m['links'].get('github') or m['links'].get('website')}")
    return "\n\n".join(out)
