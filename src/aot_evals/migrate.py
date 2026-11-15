"""`aot-evals migrate --to 2`: a 1.x suite becomes a 2.0 agent folder with one eval, `end-to-end`
(docs/v2-design.md §8).

It reads the three places a 1.x suite can be: `evals/` itself (a one-agent repository whose
evals/ holds agent.yaml), the old layout `evals/<agent>/`, and `evals/agents/<agent>/` with 1.x
files beside it. The result is always `evals/agents/<agent>/`:

    agent.yaml, discovery.md, env/, data/, labels/standard.md, journal/   shared by the agent's evals
    end-to-end/eval.yaml          written from categories, failure modes, budgets and floors
    end-to-end/coverage.yaml      the 1.x taxonomy.yaml, unchanged
    end-to-end/plan.yaml          only the scheduled / out_of_scope marks of allocation.yaml
    end-to-end/cases, checks, labels, runs, report, data/agreement
    migrated-from-1x/             the 1.x files eval.yaml was written from, for checking by hand
    MIGRATION.md                  every decision made, and what was not mapped

The migration is mechanical: moves (`git mv` for tracked files, so history follows them), renames
and the mapping table. Where 1.x never recorded what 2.0 needs, the field is left missing so
`validate` and the report say so. Nothing is invented and nothing outside the suite is touched.
This module reads the 1.x files directly; it does not use the 1.x readers.
"""

from __future__ import annotations

import json
import shutil
from collections import Counter
from datetime import date
from pathlib import Path

from .util import ContractError, dump_yaml, git, load_json, load_yaml

EVAL_ID = "end-to-end"
V1_FILES = ("categories.yaml", "failure_modes.yaml", "taxonomy.yaml", "allocation.yaml", "budgets.yaml")
CONSUMED_DIR = "migrated-from-1x"

# Where each top-level entry of a 1.x suite goes, relative to the agent folder.
SHARED = {"agent.yaml": "agent.yaml", "discovery.md": "discovery.md", "discovery.html": "discovery.html",
          "env": "env", "journal": "journal", "data": "data", ".gitignore": ".gitignore"}
TO_EVAL = {"cases": f"{EVAL_ID}/cases", "checks": f"{EVAL_ID}/checks", "runs": f"{EVAL_ID}/runs",
           "report": f"{EVAL_ID}/report", "pulled": f"{EVAL_ID}/pulled",
           "taxonomy.yaml": f"{EVAL_ID}/coverage.yaml"}
CONSUMED = ("categories.yaml", "failure_modes.yaml", "budgets.yaml", "allocation.yaml")
# labels/ is split: the standard is shared, floors.yaml is read into eval.yaml, the rest is the eval's.
# data/agreement/ (queues, the judgement cache) is the eval's; the rest of data/ is shared.

SETS = {"error_finding": "bug_finding", "quality_estimate": "quality"}
CASE_RENAMES = {"category": "use_case", "set": "pool", "taxonomy_entries": "coverage_entries"}
FM_KEEP = ("id", "description", "use_cases", "check", "diagnostics", "side_effect", "monitor")
DEFAULT_SEED = 1

# files the CLI writes again from their data; append-only logs are merged by time
REGENERATED = {"journal/activity.html", "journal/.gitignore", "discovery.html"}
MERGED = {"journal/activity.jsonl"}

DEFAULTS = [
    ("estimand.unit.kind", "system", "the end-to-end eval: the whole agent through agent.yaml's invoke"),
    ("estimand.quantity", "pass_rate", "1.x reported pass rates"),
    ("estimand.weights", "traffic",
     "1.x never put a number on what a failure costs; `cost` needs the owner's costs (problem 1)"),
    ("design.quality_set.selection", "stratified_random", "the only selection 2.0 allows"),
    ("design.quality_set.seed", DEFAULT_SEED, "any integer; the draw repeats from it"),
    ("design.cluster_key", "id", "every case its own cluster, unless a case sets `cluster`"),
    ("measurement.trials", 3, "the 2.0 floor; `auto` sizes k from a baseline (rule 16)"),
    ("measurement.correction", "none", "1.x reported judge rates uncorrected; `ppi` or `rogan_gladen` corrects them"),
    ("measurement.max_inflation", 2.0, "replaces the judges' min_tpr / min_tnr (v2-design §4)"),
    ("measurement.people.margin", 0.10, "floors are shown with a 10-point margin (statistics §4.2)"),
    ("measurement.people.labels_per_kind", "auto", ""),
    ("decision_rule.test", "superiority", "a candidate ships when it is shown better"),
    ("decision_rule.alpha", 0.05, "one-sided"),
    ("decision_rule.power", 0.80, ""),
    ("decision_rule.looks", "fixed", ""),
    ("decision_rule.combine", "all", ""),
    ("decision_rule.multiplicity", "none", ""),
]
LEFT_MISSING = [
    ("estimand.decision.action, estimand.decision.owner",
     "only the owner knows what this number decides and who decides"),
    ("decision_rule.margin", "the smallest change that matters is the owner's call"),
]


# ---- finding 1.x suites ------------------------------------------------------------------------

def _is_v1(d: Path) -> bool:
    return (d / "agent.yaml").exists() and any((d / f).exists() for f in V1_FILES)


def find(evals_dir: Path, agent: str | None = None) -> list[dict]:
    """The 1.x suites under an evals/ folder: [{name, src, dst, shape}]."""
    out = []
    if _is_v1(evals_dir):
        a = load_yaml(evals_dir / "agent.yaml") or {}
        name = a.get("id") or evals_dir.parent.name
        out.append({"name": name, "src": evals_dir, "dst": evals_dir / "agents" / name, "shape": "flat"})
    for d in sorted(p for p in evals_dir.iterdir() if p.is_dir() and p.name != "agents") if evals_dir.is_dir() else []:
        if _is_v1(d):
            out.append({"name": d.name, "src": d, "dst": evals_dir / "agents" / d.name, "shape": "old"})
    agents = evals_dir / "agents"
    for d in sorted(p for p in agents.iterdir() if p.is_dir()) if agents.is_dir() else []:
        if _is_v1(d):
            out.append({"name": d.name, "src": d, "dst": d, "shape": "agents"})
    if agent:
        out = [s for s in out if s["name"] == agent or s["src"].name == agent]
    return out


def evals_dir_for(path: Path) -> Path:
    """The evals/ folder a path names or sits in (the agent's folder, a 1.x suite, or evals/)."""
    path = path.resolve()
    for d in (path, *path.parents):
        if d.name == "evals":
            return d
    return path


# ---- moving files --------------------------------------------------------------------------------

class Mover:
    def __init__(self, repo: Path | None, dry_run: bool):
        self.repo, self.dry_run = repo, dry_run
        self.tracked: set[str] = set()
        if repo is not None:
            out = git(["ls-files", "-z"], repo)
            self.tracked = {str((repo / p).resolve()) for p in (out or "").split("\0") if p}
        self.moved: list[tuple[str, str]] = []
        self.kept: list[str] = []      # present in both; the destination's copy is kept
        self.settled: list[tuple[str, str]] = []

    def _has_tracked(self, p: Path) -> bool:
        s = str(p.resolve())
        return s in self.tracked if p.is_file() else any(t.startswith(s + "/") for t in self.tracked)

    def _git_mv(self, src: Path, dst: Path) -> bool:
        if self.repo is None or not self._has_tracked(src):
            return False
        return git(["mv", "-k", str(src), str(dst)], self.repo) is not None

    def move(self, src: Path, dst: Path, label: str) -> None:
        """Move a file or folder; into an existing folder, entry by entry."""
        if not src.exists() or src.resolve() == dst.resolve():
            return
        if dst.exists() and src.is_dir() and dst.is_dir():
            for child in sorted(src.iterdir()):
                self.move(child, dst / child.name, f"{label}/{child.name}")
            if not self.dry_run and src.is_dir() and not any(src.iterdir()):
                src.rmdir()
            return
        if dst.exists():
            self._settle(src, dst, label)
            return
        self.moved.append((label, str(dst)))
        if self.dry_run:
            return
        dst.parent.mkdir(parents=True, exist_ok=True)
        self._git_mv(src, dst)
        if src.exists() and not dst.exists():
            shutil.move(str(src), str(dst))
        elif src.exists():  # git moved only the tracked files of a folder: the rest follows
            self.moved.pop()
            self.move(src, dst, label)

    def _settle(self, src: Path, dst: Path, label: str) -> None:
        if src.is_file() and dst.is_file() and src.read_bytes() == dst.read_bytes():
            how = "identical"
        elif label in REGENERATED:
            how = "regenerated"
        elif label in MERGED:
            how = "merged"
        else:
            self.kept.append(label)
            return
        self.settled.append((label, how))
        if self.dry_run:
            return
        if how == "merged":
            _merge_jsonl(src, dst)
        if self.repo is not None and self._has_tracked(src):
            git(["rm", "-q", "--cached", str(src)], self.repo)
        src.unlink()

    def copy(self, src: Path, dst: Path, label: str) -> None:
        if not src.exists() or dst.exists():
            return
        self.moved.append((f"{label} (copied)", str(dst)))
        if not self.dry_run:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)


def _merge_jsonl(src: Path, dst: Path) -> None:
    lines = []
    for f in (src, dst):
        for ln in f.read_text().splitlines():
            if ln.strip():
                try:
                    lines.append((json.loads(ln).get("ts") or "", ln))
                except json.JSONDecodeError:
                    continue
    seen, out = set(), []
    for _, ln in sorted(lines, key=lambda x: x[0]):
        if ln not in seen:
            seen.add(ln)
            out.append(ln)
    dst.write_text("\n".join(out) + "\n")


# ---- the mapping table ---------------------------------------------------------------------------

def _check_type(src: Path, cid: str) -> str | None:
    if (src / "checks" / "code" / f"{cid}.py").exists():
        return "code"
    if (src / "checks" / "judge" / f"{cid}.md").exists():
        return "judge"
    return None


def _window(w):
    """1.x windows are `start..end`; 2.0 writes `start/end`."""
    if isinstance(w, str) and ".." in w:
        a, _, b = w.partition("..")
        try:
            date.fromisoformat(a.strip()[:10])
            date.fromisoformat(b.strip()[:10])
            return f"{a.strip()[:10]}/{b.strip()[:10]}"
        except ValueError:
            return None
    return w if isinstance(w, str) and "/" in w else None


def build_spec(src: Path, log: dict) -> dict:
    """eval.yaml from a 1.x suite's files, with every choice recorded in `log`."""
    cats = list((load_yaml(src / "categories.yaml") or {}).get("categories") or [])
    fms = list((load_yaml(src / "failure_modes.yaml") or {}).get("failure_modes") or [])
    budgets = load_yaml(src / "budgets.yaml") or {}
    floors = load_yaml(src / "labels" / "floors.yaml") or {}
    exports = load_json(src / "data" / "export.manifest.json")
    exports = list((exports.get("exports") if isinstance(exports, dict) else exports) or [])

    # the estimand
    ucs, sources = [], Counter()
    for c in cats:
        if not isinstance(c, dict) or not c.get("id"):
            continue
        ucs.append({"id": c["id"], "definition": c.get("definition"), "example": c.get("example"),
                    "share": c.get("observed_share"), "cost": None})
        if c.get("share_source"):
            sources[c["share_source"]] += 1
        dropped = {k: c[k] for k in ("worth", "cost", "simple", "other", "draft") if k in c}
        if dropped:
            log["dropped"].append((f"category {c['id']}", dropped))
        if c.get("heuristic"):
            log["heuristics"].append((c["id"], c["heuristic"]))
        other = sorted(set(c) - {"id", "definition", "example", "observed_share", "share_source", "heuristic",
                                 "worth", "cost", "simple", "other", "draft"})
        if other:
            log["unmapped"].append((f"categories.yaml {c['id']}", {k: c[k] for k in other}))
    share_source = sources.most_common(1)[0][0] if sources else None
    if len(sources) > 1:
        log["notes"].append(f"categories name {len(sources)} share sources ({', '.join(sources)}); "
                            f"estimand.share_source is the most common, {share_source}")
    frame = exports[-1] if exports else None
    population = {"frame": frame.get("id") if frame else None,
                  "window": _window(frame.get("window")) if frame else None,
                  "environment": "env/"}
    if frame:
        log["choices"].append(("estimand.population.frame", frame.get("id"),
                               "the newest import in data/export.manifest.json; check it is the traffic the "
                               "quality set should be drawn from"))
        if frame.get("window") and population["window"] is None:
            log["notes"].append(f"the import's window {frame.get('window')!r} is not start..end dates; "
                                "estimand.population.window left empty")
    else:
        log["missing"].append(("estimand.population.frame", "no import in data/export.manifest.json: "
                               "`aot-evals import FILE --id ID` records one"))

    # the measurement model
    modes, counted = [], set()
    for fm in fms:
        if not isinstance(fm, dict) or not fm.get("id"):
            continue
        out = {"id": fm["id"], "description": fm.get("description")}
        cats_ = fm.get("categories", fm.get("use_cases"))
        out["use_cases"] = "*" if cats_ == "*" or cats_ == ["*"] else list(cats_ or [])
        ids = [c for c in (fm.get("checks") or []) if isinstance(c, str)]
        if isinstance(fm.get("check"), str):
            ids = [fm["check"], *[c for c in ids if c != fm["check"]]]
        kinds = {c: _check_type(src, c) for c in ids}
        if fm.get("check_type") == "monitor":
            out["check"], out["monitor"] = None, True
            out["diagnostics"] = ids
            why = "check_type monitor: watched, never counted"
        else:
            free = [c for c in ids if c not in counted]
            code = [c for c in free if kinds[c] == "code"]
            judge = [c for c in free if kinds[c] == "judge"]
            pick = (code or judge or [None])[0]
            if pick is None and ids:
                why = (f"every check of this mode already counts for another mode or has no file "
                       f"({', '.join(ids)}): choose one that counts here")
            elif pick is None:
                why = "no check listed"
            elif kinds[pick] == "code":
                why = "the first code check"
            else:
                why = "no code check: the first judge"
            out["check"] = pick
            out["diagnostics"] = [c for c in ids if c != pick]
            if pick:
                counted.add(pick)
        if fm.get("side_effect") is not None:
            out["side_effect"] = fm["side_effect"]
        log["modes"].append((fm["id"], out.get("check"), out.get("diagnostics") or [], why))
        missing_files = [c for c in ids if kinds[c] is None]
        if missing_files:
            log["notes"].append(f"failure mode {fm['id']}: no check file for {', '.join(missing_files)}")
        dropped = {k: fm[k] for k in fm if k not in (*FM_KEEP, "categories", "checks", "check_type")}
        if dropped:
            log["dropped"].append((f"failure mode {fm['id']}", dropped))
        modes.append(out)

    # people floors
    people = {"floors": {"catch": floors.get("min_catch"), "clean": floors.get("min_clean")},
              "margin": 0.10, "labels_per_kind": "auto"}
    if floors:
        log["choices"].append(("measurement.people.floors", people["floors"],
                               "labels/floors.yaml min_catch / min_clean"))
        rest = {k: v for k, v in floors.items() if k not in ("min_catch", "min_clean")}
        if rest:
            log["dropped"].append(("labels/floors.yaml", rest))
    else:
        log["choices"].append(("measurement.people.floors", {"catch": None, "clean": None},
                               "no labels/floors.yaml; null floors come from max_inflation. 1.x's built-in "
                               "85% / 85% floors are not carried over"))

    # constraints
    constraints = {"default": budgets.get("default") or {}, "use_cases": budgets.get("categories") or {}}
    if budgets:
        log["choices"].append(("decision_rule.constraints", "budgets.yaml",
                               "default -> default, categories -> use_cases"))
        rest = {k: v for k, v in budgets.items() if k not in ("default", "categories")}
        if rest:
            log["unmapped"].append(("budgets.yaml", rest))

    spec = {
        "eval": EVAL_ID,
        "version": "1.0",
        "estimand": {
            "unit": {"kind": "system"},
            "quantity": "pass_rate",
            "population": population,
            "use_cases": ucs,
            "share_source": share_source,
            "weights": "traffic",
            "decision": {"action": None, "owner": None, "cadence": None},
        },
        "design": {
            "quality_set": {"selection": "stratified_random", "seed": DEFAULT_SEED, "oversample": {}},
            "bug_finding_set": {"coverage": "coverage.yaml"},
            "cluster_key": "id",
        },
        "measurement": {
            "failure_modes": modes,
            "trials": 3,
            "correction": "none",
            "max_inflation": 2.0,
            "people": people,
        },
        "decision_rule": {
            "test": "superiority", "margin": None, "alpha": 0.05, "power": 0.80, "looks": "fixed",
            "combine": "all", "multiplicity": "none", "use_case_gates": [], "also_requires": [],
            "constraints": constraints,
        },
    }
    alloc = load_yaml(src / "allocation.yaml") or {}
    k = (alloc.get("assumptions") or {}).get("k")
    if k and k != 3:
        log["notes"].append(f"allocation.yaml assumed k = {k}; measurement.trials is 3 (set it to {k} to keep "
                            "running as many trials)")
    return spec


def plan_marks(src: Path) -> list[dict]:
    """allocation.yaml's scheduled and out_of_scope marks, as plan.yaml rows `plan` carries over."""
    alloc = load_yaml(src / "allocation.yaml") or {}
    rows = []
    for c in alloc.get("cells") or []:
        if isinstance(c, dict) and c.get("status") in ("scheduled", "out_of_scope"):
            rows.append({"use_case": c.get("category"), "pool": SETS.get(c.get("set"), c.get("set")),
                         "status": c["status"], "reason": c.get("reason")})
    return rows


def rewrite_case(case: dict) -> tuple[dict, list[str]]:
    """The 1.x field names in a case, renamed in place (key order kept)."""
    out, changed = {}, []
    for k, v in case.items():
        if k in CASE_RENAMES:
            new = CASE_RENAMES[k]
            if k == "set":
                v = SETS.get(v, v)
            out[new] = v
            changed.append(k)
        else:
            out[k] = v
    return out, changed


def drop_top_keys(text: str, keys: tuple[str, ...]) -> tuple[str, list[str]]:
    """Remove top-level YAML keys and their indented bodies, keeping every other line and comment."""
    lines, out, dropped, skipping = text.splitlines(keepends=True), [], [], False
    for ln in lines:
        top = ln[:1] not in (" ", "\t", "\n", "\r", "#", "")
        if top:
            key = ln.split(":", 1)[0].strip()
            skipping = key in keys
            if skipping:
                dropped.append(key)
                continue
        elif skipping and (ln.startswith((" ", "\t")) or not ln.strip()):
            continue
        else:
            skipping = False
        out.append(ln)
    return "".join(out), dropped


def drop_judge_floors(text: str) -> tuple[str, bool]:
    """min_tpr / min_tnr out of a judge's front matter."""
    if not text.startswith("---"):
        return text, False
    end = text.find("\n---", 3)
    if end < 0:
        return text, False
    head, body = text[:end], text[end:]
    kept = [ln for ln in head.splitlines(keepends=True) if ln.split(":", 1)[0].strip() not in ("min_tpr", "min_tnr")]
    new = "".join(kept)
    return new + body, new != head


# ---- one suite -----------------------------------------------------------------------------------

def _repo_of(path: Path) -> Path | None:
    top = git(["rev-parse", "--show-toplevel"], path)
    return Path(top) if top else None


def migrate_one(s: dict, dry_run: bool = False) -> dict:
    src, dst = s["src"], s["dst"]
    repo = _repo_of(src)
    mv = Mover(repo, dry_run)
    log = {"dropped": [], "heuristics": [], "unmapped": [], "notes": [], "choices": [], "modes": [],
           "missing": [], "not_moved": [], "by_hand": []}
    spec = build_spec(src, log)
    marks = plan_marks(src)
    n_cases = Counter()
    for p in sorted((src / "cases").glob("*/*.json")) if (src / "cases").is_dir() else []:
        try:
            c = json.loads(p.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        if isinstance(c, dict):
            n_cases[SETS.get(c.get("set"), c.get("pool") or c.get("set") or "none")] += 1
    runs_dir = src / "runs"
    n_runs = sum(1 for p in runs_dir.iterdir() if (p / "manifest.json").exists()) if runs_dir.is_dir() else 0

    # paths inside moved files that may point at the old places
    for p in sorted((src / "checks").rglob("*")) if (src / "checks").is_dir() else []:
        if p.is_file() and p.suffix == ".py":
            for n, ln in enumerate(p.read_text(errors="replace").splitlines(), 1):
                if "__file__" in ln:
                    log["by_hand"].append(f"checks/{p.relative_to(src / 'checks')} line {n} finds files from its own "
                                          f"place, which is now one folder deeper ({EVAL_ID}/checks/): "
                                          f"`{ln.strip()}`")
    agent_text = (src / "agent.yaml").read_text()
    for d in ("cases/", "checks/", "runs/", "report/", "labels/"):
        if d in agent_text:
            log["by_hand"].append(f"agent.yaml mentions {d}; that folder is now {EVAL_ID}/{d}")

    # the moves
    entries = sorted(p.name for p in src.iterdir())
    for name in entries:
        p = src / name
        if s["shape"] == "flat" and name == "agents":
            continue
        if name == ".gitignore" and s["shape"] == "flat":
            mv.copy(p, dst / ".gitignore", name)  # it also covers the team's own files in evals/
        elif name == "data" and p.is_dir():
            if (p / "agreement").exists():
                mv.move(p / "agreement", dst / EVAL_ID / "data" / "agreement", "data/agreement")
            mv.move(p, dst / "data", "data")
        elif name == "labels" and p.is_dir():
            if (p / "standard.md").exists():
                mv.move(p / "standard.md", dst / "labels" / "standard.md", "labels/standard.md")
            if (p / "floors.yaml").exists():
                mv.move(p / "floors.yaml", dst / CONSUMED_DIR / "floors.yaml", "labels/floors.yaml")
            for child in sorted(p.iterdir()) if p.exists() else []:
                if child.name not in ("standard.md", "floors.yaml"):
                    mv.move(child, dst / EVAL_ID / "labels" / child.name, f"labels/{child.name}")
            if not dry_run and p.exists() and not any(p.iterdir()):
                p.rmdir()
        elif name in SHARED:
            mv.move(p, dst / SHARED[name], name)
        elif name in TO_EVAL:
            mv.move(p, dst / TO_EVAL[name], name)
        elif name in CONSUMED:
            mv.move(p, dst / CONSUMED_DIR / name, name)
        elif s["shape"] == "flat":
            log["not_moved"].append(name + ("/" if p.is_dir() else ""))
        elif s["shape"] == "old":
            mv.move(p, dst / name, name)
            log["notes"].append(f"{name}: not a 1.x suite file; moved to the agent folder as it is")
        else:
            if name not in (EVAL_ID, CONSUMED_DIR, "MIGRATION.md", "labels"):
                log["not_moved"].append(name + ("/" if p.is_dir() else ""))

    # the team's own scripts left beside the suite, if they name a folder that moved
    if s["shape"] == "flat":
        import re

        pat = re.compile(r"""["'/](env|cases|runs|checks|labels|data|report|journal)["'/]""")
        for name in log["not_moved"]:
            p = src / name
            if p.is_file() and p.suffix in (".py", ".sh"):
                hits = sorted({m.group(1) for m in pat.finditer(p.read_text(errors="replace"))})
                if hits:
                    log["by_hand"].append(f"{name} (left in place) names {', '.join(f'{h}/' for h in hits)}, "
                                          "which moved into the agent folder or its end-to-end eval")

    ev_dir = dst / EVAL_ID
    rewritten, judges = 0, []
    if not dry_run and s["shape"] == "old" and src.exists():
        for d in sorted((p for p in src.rglob("*") if p.is_dir()), key=lambda p: -len(p.parts)):
            if not any(d.iterdir()):
                d.rmdir()
        if not any(src.iterdir()):
            src.rmdir()
    if not dry_run:
        # agent.yaml: validity and simulator go
        a = dst / "agent.yaml"
        if a.exists():
            text, dropped = drop_top_keys(a.read_text(), ("validity", "simulator"))
            if dropped:
                a.write_text(text)
                log["dropped"].append(("agent.yaml", {k: "(removed)" for k in dropped}))
        for p in sorted((ev_dir / "cases").glob("*/*.json")) if (ev_dir / "cases").is_dir() else []:
            try:
                c = json.loads(p.read_text())
            except (json.JSONDecodeError, OSError):
                continue
            if not isinstance(c, dict):
                continue
            new, changed = rewrite_case(c)
            if changed:
                p.write_text(json.dumps(new, indent=2, ensure_ascii=False) + "\n")
                rewritten += 1
        for p in sorted((ev_dir / "checks" / "judge").glob("*.md")) if (ev_dir / "checks" / "judge").is_dir() else []:
            new, changed = drop_judge_floors(p.read_text())
            if changed:
                p.write_text(new)
                judges.append(p.stem)
        gi = dst / ".gitignore"
        if gi.exists():
            lines = gi.read_text().splitlines()
            add = []
            for ln in lines:
                if ln.strip().startswith(("runs/", "checks/", "pulled/", "cases/", "report/")):
                    add.append("*/" + ln.strip())
            add += ["*/runs/*/raw/", "*/checks/judge/*.queue.csv", "*/data/"]
            new = [x for x in dict.fromkeys(add) if x not in lines]
            if new:
                gi.write_text(gi.read_text().rstrip("\n")
                              + "\n# 2.0: each eval's own folder (aot-evals migrate --to 2)\n"
                              + "\n".join(new) + "\n")
        ev_dir.mkdir(parents=True, exist_ok=True)
        (ev_dir / "eval.yaml").write_text(
            "# Written by `aot-evals migrate --to 2` from the 1.x suite; ../MIGRATION.md says what each\n"
            "# field came from and what is left for the owner. `aot-evals validate` lists what is missing.\n"
            + dump_yaml(spec))
        if marks:
            (ev_dir / "plan.yaml").write_text(
                "# The status / reason marks of the 1.x allocation.yaml; `aot-evals plan --write` fills in\n"
                "# the targets and keeps these marks.\n" + dump_yaml({"rows": marks}))
    log["judges_without_floors"] = judges

    evals_root = next((d for d in (src, *src.parents) if d.name == "evals"), src)
    result = {"agent": s["name"], "shape": s["shape"], "from": str(src), "to": str(dst),
              "from_rel": str(src.relative_to(evals_root.parent)),
              "use_cases": [(u["id"], u["share"]) for u in spec["estimand"]["use_cases"]],
              "modes": log["modes"], "constraints": spec["decision_rule"]["constraints"],
              "people_floors": spec["measurement"]["people"]["floors"], "cases": dict(n_cases),
              "cases_rewritten": rewritten, "runs": n_runs, "moved": mv.moved, "kept": mv.kept,
              "settled": mv.settled, "marks": marks, "log": log, "spec_missing": [], "spec_invalid": []}
    if not dry_run:
        try:
            from .repo import Evals

            sp = Evals(dst).eval(EVAL_ID).spec(reload=True)
            result["spec_missing"] = [(i.field, i.why) for i in sp.missing]
            result["spec_invalid"] = [(i.field, i.why) for i in sp.invalid]
        except ContractError as e:
            result["spec_invalid"] = [("eval.yaml", str(e))]
        (dst / "MIGRATION.md").write_text(render_md(result))
    return result


# ---- MIGRATION.md --------------------------------------------------------------------------------

def _v(v) -> str:
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False, default=str)
    return str(v)


def render_md(r: dict) -> str:
    log = r["log"]
    L = [f"# Migration of {r['agent']} to aot-evals 2.0", "",
         f"`aot-evals migrate --to 2` turned the 1.x suite in `{r.get('from_rel', r['from'])}/` ({r['shape']} layout) into this agent "
         f"folder with one eval, `{EVAL_ID}/`, on {date.today().isoformat()}. It moved files, renamed fields and "
         "applied the mapping table in docs/v2-design.md §8; it invented nothing. Check each section below, then "
         "commit.", "",
         "## What to do next", "",
         "1. Fill what only the owner knows (below, *Left missing*), then `aot-evals validate`.",
         "2. The quality cases were picked by hand in 1.x, so they carry no `draw` and do not count toward θ̂ "
         "(rule 6). `aot-evals draw` draws the quality set from the frame; `--prune` removes the hand-picked ones.",
         "3. The 1.x runs moved unchanged, but their manifests are not 2.0 manifests, so `report` refuses them: "
         "screen, commit and run a new baseline (`aot-evals run --purpose baseline`).",
         "4. `aot-evals plan --write` sizes the eval from its decision rule.",
         "5. Delete `migrated-from-1x/` once you have checked eval.yaml against it.", "",
         "## Defaults filled", "", "| Field | Value | Why |", "|---|---|---|"]
    for f, v, why in DEFAULTS:
        L.append(f"| `{f}` | `{_v(v)}` | {why} |")
    for f, v, why in log["choices"]:
        L.append(f"| `{f}` | `{_v(v)}` | {why} |")
    L += ["", "## Left missing", ""]
    for f, why in LEFT_MISSING + log["missing"]:
        L.append(f"- `{f}`: {why}.")
    L.append("- every use case's `cost` is null: with `weights: traffic` it is not needed; `weights: cost` needs it.")
    L += ["", "## Use cases (from categories.yaml)", "", "| Use case | Share |", "|---|---|"]
    for uc, sh in r["use_cases"]:
        L.append(f"| {uc} | {_v(sh)} |")
    L += ["", "## Failure modes: the check that counts", "",
          "| Mode | Counted check | Diagnostics | Why |", "|---|---|---|---|"]
    for fid, ck, diags, why in r["modes"]:
        L.append(f"| {fid} | {ck or '—'} | {', '.join(diags) or '—'} | {why} |")
    L += ["", f"Constraints (budgets.yaml): `{_v(r['constraints'])}`. "
          f"People floors: `{_v(r['people_floors'])}`.", ""]
    if r["log"]["judges_without_floors"]:
        L.append("Judges whose `min_tpr` / `min_tnr` were removed (their calibrations stay current): "
                 + ", ".join(r["log"]["judges_without_floors"]) + ".")
        L.append("")
    if log["dropped"]:
        L += ["## Dropped fields", ""]
        for where, d in log["dropped"]:
            L.append(f"- {where}: " + "; ".join(f"`{k}` = `{_v(v)}`" for k, v in d.items()))
        L.append("")
    if log["heuristics"]:
        L += ["## Heuristics kept as notes", "",
              "1.x categories could say how to tell their requests apart by rule. 2.0 has no field for it:", ""]
        for uc, h in log["heuristics"]:
            L.append(f"- {uc}: {h}")
        L.append("")
    if log["unmapped"] or log["not_moved"] or r["kept"]:
        L += ["## Not mapped or not moved", ""]
        for where, d in log["unmapped"]:
            L.append(f"- {where}: " + "; ".join(f"`{k}` = `{_v(v)}`" for k, v in d.items()) + " (no 2.0 field)")
        for n in log["not_moved"]:
            L.append(f"- `{n}`: not a 1.x suite file; left where it was")
        for n in r["kept"]:
            L.append(f"- `{n}`: already in the agent folder and different; that copy was kept and the 1.x one left "
                     "in place for you to compare")
        L.append("")
    if log["by_hand"] or log["notes"]:
        L += ["## Check by hand", ""]
        for n in log["by_hand"] + log["notes"]:
            L.append(f"- {n}")
        L.append("")
    by_pool = ", ".join(f"{k}: {v}" for k, v in sorted(r["cases"].items()))
    L += ["## Files", "",
          f"- {sum(r['cases'].values())} cases moved ({by_pool or 'none'}); "
          f"{r['cases_rewritten']} rewritten for the 2.0 field names (`category` → `use_case`, `set` → `pool`, "
          "`taxonomy_entries` → `coverage_entries`).",
          f"- {r['runs']} runs moved to `{EVAL_ID}/runs/` unchanged.",
          f"- `plan.yaml` carries {len(r['marks'])} scheduled / out-of-scope marks from allocation.yaml." if r["marks"]
          else "- allocation.yaml had no scheduled or out-of-scope marks to carry over.",
          "- categories.yaml, failure_modes.yaml, budgets.yaml, allocation.yaml and labels/floors.yaml are in "
          "`migrated-from-1x/`; taxonomy.yaml is `end-to-end/coverage.yaml`.", ""]
    for label, d in r["moved"]:
        base = Path(r["to"]).parent
        L.append(f"  - `{label}` → `{Path(d).relative_to(base) if Path(d).is_relative_to(base) else d}`")
    for label, how in r["settled"]:
        L.append(f"  - `{label}`: in both places; {how}")
    L += ["", "## The spec after migration", ""]
    if r["spec_missing"] or r["spec_invalid"]:
        for f, why in r["spec_missing"]:
            L.append(f"- missing `{f}`: {why}")
        for f, why in r["spec_invalid"]:
            L.append(f"- invalid `{f}`: {why}")
    else:
        L.append("Complete.")
    return "\n".join(L) + "\n"


# ---- entry point ---------------------------------------------------------------------------------

def run(evals_dir: Path, agent: str | None = None, dry_run: bool = False, log=print) -> list[dict]:
    suites = find(evals_dir, agent)
    if not suites:
        log(f"no 1.x suite under {evals_dir}" + (f" named {agent}" if agent else "") + "; nothing to migrate")
        return []
    out = []
    for s in suites:
        r = migrate_one(s, dry_run=dry_run)
        out.append(r)
        log(f"{r['agent']}: {s['src']} -> {s['dst']}/{EVAL_ID}/ ({s['shape']} layout)"
            + (" [dry run: nothing written]" if dry_run else ""))
        log(f"  {len(r['use_cases'])} use cases, {len(r['modes'])} failure modes, "
            f"{sum(r['cases'].values())} cases {dict(r['cases'])}, {r['runs']} runs")
        for fid, ck, diags, why in r["modes"]:
            log(f"  mode {fid}: counts {ck or '-'}" + (f"; diagnostics {', '.join(diags)}" if diags else "")
                + f" ({why})")
        for n in r["log"]["not_moved"]:
            log(f"  not moved: {n}")
        for n in r["kept"]:
            log(f"  both have {n}: the agent folder's copy is kept")
        if not dry_run:
            log(f"  spec: {len(r['spec_missing'])} missing, {len(r['spec_invalid'])} invalid; "
                f"see {s['dst']}/MIGRATION.md")
    if not dry_run:
        log("done. Review with `git status`, fill what MIGRATION.md lists, then commit.")
    return out
