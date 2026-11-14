"""The eval spec, `eval.yaml` (docs/v2-design.md §2): load it, fill its stated defaults, and say what
is missing.

An eval with a missing field still runs; the report lists the field under `spec.missing`, with why
it matters and which numbers it blocks, and those numbers are null. A field that is present but
cannot mean anything (a share above 1, an unknown test) is `spec.invalid`, and blocks the same
numbers. `spec.notes` are observations that block nothing (an unknown key, a bar a superiority test
ignores). `spec.defaults` lists every default the loader filled, so a report can say "α 0.05 by
default" instead of presenting it as a choice someone made.

Each issue names the blocks it affects, from BLOCKS: the report v2 keys (`estimate`, `use_cases`,
`measurement`, `decision`, `comparison`) and the commands that need the field (`run`, `draw`,
`plan`).
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .util import ContractError, load_yaml


def load_yaml_text(text: str):
    import yaml

    try:
        return yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise ContractError(f"front matter: {e}") from e

if TYPE_CHECKING:
    from .repo import Eval

PARTS = ("estimand", "design", "measurement", "decision_rule")
BLOCKS = ("run", "draw", "plan", "estimate", "use_cases", "measurement", "decision", "comparison")

UNIT_KINDS = ("system", "component")
WEIGHTS = ("traffic", "cost")
SELECTIONS = ("stratified_random",)
CORRECTIONS = ("none", "rogan_gladen", "ppi")
TESTS = ("superiority", "non_inferiority", "threshold")
LOOKS = ("fixed", "sequential", "optimizer_holdout")
COMBINE = ("all", "any")
MULTIPLICITY = ("none", "holm", "benjamini_hochberg")
ALL_USE_CASES = "*"
SHARE_TOLERANCE = 0.02

DEFAULT_ALPHA = 0.05            # one-sided (statistics §4.5)
DEFAULT_POWER = 0.80
DEFAULT_LOOKS = "fixed"
DEFAULT_COMBINE = "all"         # every gate must pass: an intersection-union test (statistics §4.6)
DEFAULT_MAX_INFLATION = 2.0     # a judge may cost at most twice the cases (v2-design §10.3)
DEFAULT_PEOPLE_MARGIN = 0.10    # floors shown with a 10-point non-inferiority margin (statistics §4.2)

KEYS = {
    "": ("eval", "version", *PARTS, "invoke"),
    "estimand": ("unit", "quantity", "population", "use_cases", "share_source", "weights", "decision"),
    "estimand.unit": ("kind", "component", "boundary"),
    "estimand.population": ("frame", "window", "environment"),
    "estimand.use_cases[]": ("id", "definition", "example", "share", "cost"),
    "estimand.decision": ("action", "owner", "cadence"),
    "design": ("quality_set", "bug_finding_set", "cluster_key"),
    "design.quality_set": ("selection", "seed", "oversample"),
    "design.bug_finding_set": ("coverage",),
    "measurement": ("failure_modes", "trials", "correction", "max_inflation", "people"),
    "measurement.failure_modes[]": ("id", "description", "use_cases", "check", "diagnostics",
                                    "side_effect", "monitor"),
    "measurement.people": ("floors", "margin", "labels_per_kind"),
    "measurement.people.floors": ("catch", "clean"),
    "decision_rule": ("test", "quantity", "bar", "margin", "alpha", "power", "looks", "combine",
                      "multiplicity", "use_case_gates", "also_requires", "constraints"),
    "decision_rule.use_case_gates[]": ("use_case", "test", "bar", "margin"),
    "decision_rule.also_requires[]": ("eval", "test", "bar", "margin"),
    "decision_rule.constraints": ("default", "use_cases"),
    # the agent contract's invoke block, as in agent.yaml (references/agent-contract.md)
    "invoke": ("command", "cwd", "isolate", "timeout", "max_attempts", "setup", "seed", "observe",
               "reset", "reset_scope", "env", "model"),
}

ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
VERSION_RE = re.compile(r"^\d+\.\d+$")


@dataclass
class Issue:
    field: str
    why: str
    blocks: list[str]

    def as_dict(self) -> dict:
        return {"field": self.field, "why": self.why, "blocks": list(self.blocks)}


@dataclass
class Spec:
    """A loaded eval.yaml. `data` is the file as written; `resolved` has the defaults filled."""

    eval_id: str
    path: Path
    data: dict
    resolved: dict
    missing: list[Issue] = field(default_factory=list)
    invalid: list[Issue] = field(default_factory=list)
    notes: list[Issue] = field(default_factory=list)
    defaults: list[dict] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        """Every required field is filled and means something (v2-design §2)."""
        return not self.missing and not self.invalid

    def blocked(self, block: str) -> list[Issue]:
        """The issues that make one number or command meaningless."""
        return [i for i in (*self.missing, *self.invalid) if block in i.blocks]

    def part(self, name: str) -> dict:
        v = self.resolved.get(name)
        return v if isinstance(v, dict) else {}

    def as_dict(self) -> dict:
        """The report's `spec` key (v2-design §6)."""
        return {"complete": self.complete,
                "missing": [i.as_dict() for i in self.missing],
                "invalid": [i.as_dict() for i in self.invalid],
                "notes": [i.as_dict() for i in self.notes],
                "defaults": list(self.defaults)}


# ---- small predicates ------------------------------------------------------------------------

def _num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _text(v: Any) -> bool:
    return isinstance(v, str) and bool(v.strip())


def _unit_interval(v: Any) -> bool:
    """Strictly between 0 and 1: a rate, a margin, an α."""
    return _num(v) and 0 < v < 1


def _version(v: Any) -> str | None:
    """major.minor. YAML reads an unquoted 1.0 as a float, so numbers are accepted and written
    back as text; an int is major.0."""
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return f"{v}.0"
    if isinstance(v, float):
        v = repr(v)
    if isinstance(v, str) and VERSION_RE.match(v.strip()):
        return v.strip()
    return None


def _window(v: Any) -> bool:
    """start/end, as ISO dates, start no later than end."""
    if not isinstance(v, str) or v.count("/") != 1:
        return False
    try:
        start, end = (date.fromisoformat(s.strip()) for s in v.split("/"))
    except ValueError:
        return False
    return start <= end


# ---- the checker -----------------------------------------------------------------------------

class _Check:
    def __init__(self, ev: Eval | None):
        self.ev = ev
        self.missing: list[Issue] = []
        self.invalid: list[Issue] = []
        self.notes: list[Issue] = []
        self.defaults: list[dict] = []

    def miss(self, f: str, why: str, blocks: list[str]) -> None:
        self.missing.append(Issue(f, why, blocks))

    def bad(self, f: str, why: str, blocks: list[str]) -> None:
        self.invalid.append(Issue(f, why, blocks))

    def note(self, f: str, why: str) -> None:
        self.notes.append(Issue(f, why, []))

    def default(self, d: dict, key: str, f: str, value: Any) -> Any:
        d[key] = value
        self.defaults.append({"field": f, "value": value})
        return value

    def mapping(self, parent: dict, key: str, f: str, blocks: list[str], required: bool = True) -> dict | None:
        """parent[key] as a mapping: None (and an issue when required) when absent or not one."""
        v = parent.get(key)
        if v is None:
            if required:
                self.miss(f, "required", blocks)
            return None
        if not isinstance(v, dict):
            self.bad(f, "must be a mapping", blocks)
            return None
        return v

    def unknown_keys(self, d: dict, schema_key: str, f: str) -> None:
        known = KEYS[schema_key]
        for k in d:
            if k in known:
                continue
            close = difflib.get_close_matches(str(k), known, n=1)
            hint = f"; did you mean `{close[0]}`?" if close else ""
            self.note(f"{f}.{k}" if f else str(k), f"not a field of the eval spec, ignored{hint}")


def _gate_rule(c: _Check, f: str, d: dict, blocks: list[str]) -> str | None:
    """test plus the bar or margin it needs; shared by the headline rule and every gate."""
    test = d.get("test")
    if test is None:
        c.miss(f"{f}.test", f"required: one of {', '.join(TESTS)}", blocks)
        return None
    if test not in TESTS:
        c.bad(f"{f}.test", f"must be one of {', '.join(TESTS)}", blocks)
        return None
    need, other = ("bar", "margin") if test == "threshold" else ("margin", "bar")
    v = d.get(need)
    if v is None:
        why = ("a threshold test needs the bar it compares with" if need == "bar" else
               f"a {test.replace('_', '-')} test needs the smallest change that matters")
        c.miss(f"{f}.{need}", why, blocks)
    elif not _unit_interval(v):
        c.bad(f"{f}.{need}", "must be a rate strictly between 0 and 1", blocks)
    if d.get(other) is not None:
        c.note(f"{f}.{other}", f"a {test.replace('_', '-')} test uses `{need}`; `{other}` is ignored")
    return test


# ---- the four parts --------------------------------------------------------------------------

def _estimand(c: _Check, spec: dict) -> tuple[str | None, list[str]]:
    """Returns the unit kind and the use case ids."""
    e = c.mapping(spec, "estimand", "estimand", ["estimate", "decision", "plan", "draw"])
    if e is None:
        return None, []
    c.unknown_keys(e, "estimand", "estimand")

    kind = None
    unit = c.mapping(e, "unit", "estimand.unit", ["run", "estimate", "decision"])
    if unit is not None:
        c.unknown_keys(unit, "estimand.unit", "estimand.unit")
        kind = unit.get("kind")
        if kind is None:
            c.miss("estimand.unit.kind", "required: system or component", ["run", "estimate", "decision"])
        elif kind not in UNIT_KINDS:
            c.bad("estimand.unit.kind", "must be system or component", ["run", "estimate", "decision"])
            kind = None
        elif kind == "component":
            for k, why in (("component", "what the unit is, as agent.yaml names it"),
                           ("boundary", "the context boundary the handoff crosses (rule 3)")):
                if not _text(unit.get(k)):
                    c.miss(f"estimand.unit.{k}", f"a component eval needs {why}", ["estimate", "decision"])
        else:
            for k in ("component", "boundary"):
                if unit.get(k) is not None:
                    c.note(f"estimand.unit.{k}", "only a component eval has one; ignored")

    pop = c.mapping(e, "population", "estimand.population", ["draw", "estimate"])
    if pop is not None:
        c.unknown_keys(pop, "estimand.population", "estimand.population")
        frame = pop.get("frame")
        if frame is None:
            c.miss("estimand.population.frame", "required: the import id the quality set is drawn "
                   "from (rule 4)", ["draw", "estimate"])
        elif not _text(frame):
            c.bad("estimand.population.frame", "must be an import id", ["draw", "estimate"])
        elif c.ev is not None:
            ids = {x.get("id") for x in c.ev.exports() if isinstance(x, dict)}
            if frame not in ids:
                c.miss("estimand.population.frame",
                       f"no import '{frame}' in data/export.manifest.json; "
                       f"`aot-evals import FILE --id {frame}` records it", ["draw", "estimate"])
        if pop.get("window") is not None and not _window(pop["window"]):
            c.bad("estimand.population.window", "must be start/end as ISO dates, start first, "
                  "e.g. 2026-10-01/2026-10-31", ["draw"])

    ids: list[str] = []
    shares: dict[str, float] = {}
    costs: dict[str, Any] = {}
    ucs = e.get("use_cases")
    uc_blocks = ["draw", "plan", "estimate", "use_cases"]
    if ucs is None or ucs == []:
        c.miss("estimand.use_cases", "required: the kinds of request that partition the population, "
               "each with its share", uc_blocks)
    elif not isinstance(ucs, list):
        c.bad("estimand.use_cases", "must be a list", uc_blocks)
    else:
        dup = False
        for i, uc in enumerate(ucs):
            if not isinstance(uc, dict):
                c.bad(f"estimand.use_cases[{i}]", "must be a mapping", uc_blocks)
                continue
            uid = uc.get("id")
            if uid is None:
                c.miss(f"estimand.use_cases[{i}].id", "required: an id that names its cases' folder",
                       uc_blocks)
                continue
            if not _text(uid) or not ID_RE.match(uid):
                c.bad(f"estimand.use_cases[{i}].id", "must be an id that can name a folder "
                      "(letters, digits, - _ .)", uc_blocks)
                continue
            f = f"estimand.use_cases[{uid}]"
            if uid in ids:
                c.bad(f"{f}.id", "used twice: use cases partition the population", uc_blocks)
                dup = True
                continue
            ids.append(uid)
            c.unknown_keys(uc, "estimand.use_cases[]", f)
            for k, why in (("definition", "what belongs in this use case"),
                           ("example", "a trace id from the frame that belongs in it")):
                if not _text(uc.get(k)):
                    c.miss(f"{f}.{k}", f"required: {why}", ["use_cases"])
            share = uc.get("share")
            if share is None:
                c.miss(f"{f}.share", "required: its measured fraction of the population",
                       ["draw", "plan", "estimate"])
            elif not _num(share) or not 0 < share <= 1:
                c.bad(f"{f}.share", "must be a fraction above 0 and at most 1", ["draw", "plan", "estimate"])
            else:
                shares[uid] = float(share)
            costs[uid] = uc.get("cost")
        if ids and len(shares) == len(ids) and not dup:
            total = sum(shares.values())
            if abs(total - 1) > SHARE_TOLERANCE:
                c.bad("estimand.use_cases", f"shares sum to {total:g}; they partition the population, "
                      f"so they sum to 1 ± {SHARE_TOLERANCE:g}", ["draw", "plan", "estimate"])

    w = e.get("weights")
    w_blocks = ["estimate", "plan"]
    if w is None:
        c.miss("estimand.weights", "required: traffic, cost or {use_case: weight}; an unstated weight "
               "is unknown, never 1 (rule 2)", w_blocks)
    elif w == "cost":
        for uid in ids:
            cost = costs.get(uid)
            if cost is None:
                c.miss(f"estimand.use_cases[{uid}].cost", "weights: cost needs what one failure costs; "
                       "only its owner can say (problem 1)", w_blocks)
            elif not _num(cost) or cost <= 0:
                c.bad(f"estimand.use_cases[{uid}].cost", "must be a positive number", w_blocks)
    elif w == "traffic":
        pass
    elif isinstance(w, dict):
        for k, v in w.items():
            if k not in ids:
                c.bad(f"estimand.weights[{k}]", "not a use case of this eval", w_blocks)
            elif not _num(v) or v < 0:
                c.bad(f"estimand.weights[{k}]", "must be a number at or above 0", w_blocks)
        for uid in ids:
            if uid not in w or w[uid] is None:
                c.miss(f"estimand.weights[{uid}]", "an unstated weight is unknown, never 1 (rule 2)",
                       w_blocks)
        stated = [v for k, v in w.items() if k in ids and _num(v) and v >= 0]
        if ids and len(stated) == len(ids) and abs(sum(stated) - 1) > SHARE_TOLERANCE:
            c.bad("estimand.weights", f"weights sum to {sum(stated):g}; they sum to "
                  f"1 ± {SHARE_TOLERANCE:g}", w_blocks)
    else:
        c.bad("estimand.weights", "must be traffic, cost or {use_case: weight}", w_blocks)

    dec = c.mapping(e, "decision", "estimand.decision", ["decision"])
    if dec is not None:
        c.unknown_keys(dec, "estimand.decision", "estimand.decision")
        for k, why in (("action", "the action this number drives"), ("owner", "who makes the decision")):
            if not _text(dec.get(k)):
                c.miss(f"estimand.decision.{k}", f"required: {why}", ["decision"])
    return kind, ids


def _design(c: _Check, spec: dict, ids: list[str]) -> None:
    d = c.mapping(spec, "design", "design", ["draw", "estimate", "plan"])
    if d is None:
        return
    c.unknown_keys(d, "design", "design")
    qs = c.mapping(d, "quality_set", "design.quality_set", ["draw", "estimate"])
    if qs is not None:
        c.unknown_keys(qs, "design.quality_set", "design.quality_set")
        sel = qs.get("selection")
        if sel is None:
            c.default(qs, "selection", "design.quality_set.selection", SELECTIONS[0])
        elif sel not in SELECTIONS:
            c.bad("design.quality_set.selection", "the quality set is drawn stratified at random, never "
                  "picked (rule 6)", ["draw", "estimate"])
        seed = qs.get("seed")
        if seed is None:
            c.miss("design.quality_set.seed", "required: the draw is seeded so it can be repeated (rule 6)",
                   ["draw"])
        elif not isinstance(seed, int) or isinstance(seed, bool):
            c.bad("design.quality_set.seed", "must be an integer", ["draw"])
        over = qs.get("oversample")
        if over is not None:
            if not isinstance(over, dict):
                c.bad("design.quality_set.oversample", "must be {use_case: factor}", ["draw"])
            else:
                for k, v in over.items():
                    if k not in ids:
                        c.bad(f"design.quality_set.oversample[{k}]", "not a use case of this eval", ["draw"])
                    elif not _num(v) or v <= 0:
                        c.bad(f"design.quality_set.oversample[{k}]", "must be a positive factor", ["draw"])
    bf = c.mapping(d, "bug_finding_set", "design.bug_finding_set", [], required=False)
    if bf is not None:
        c.unknown_keys(bf, "design.bug_finding_set", "design.bug_finding_set")
    ck = d.get("cluster_key")
    if ck is None:
        c.miss("design.cluster_key", "required: the case field that marks related cases; `id` makes "
               "every case its own cluster (rule 9)", ["estimate", "decision", "plan"])
    elif not _text(ck):
        c.bad("design.cluster_key", "must be a case field name", ["estimate", "decision", "plan"])


def _measurement(c: _Check, spec: dict, ids: list[str]) -> tuple[list[str], dict]:
    """Returns the failure mode ids, and the counted check of each mode (None for a monitor)."""
    m = c.mapping(spec, "measurement", "measurement", ["measurement", "estimate", "run"])
    modes: list[str] = []
    counted: dict[str, str | None] = {}
    if m is None:
        return modes, counted
    c.unknown_keys(m, "measurement", "measurement")
    fm_blocks = ["measurement", "estimate"]
    fms = m.get("failure_modes")
    by_check: dict[str, str] = {}
    side_effect = False
    if fms is None or fms == []:
        c.miss("measurement.failure_modes", "required: each way a run can go wrong, with the one check "
               "that counts for it (rules 11, 12)", fm_blocks)
    elif not isinstance(fms, list):
        c.bad("measurement.failure_modes", "must be a list", fm_blocks)
    else:
        for i, fm in enumerate(fms):
            if not isinstance(fm, dict):
                c.bad(f"measurement.failure_modes[{i}]", "must be a mapping", fm_blocks)
                continue
            fid = fm.get("id")
            if fid is None:
                c.miss(f"measurement.failure_modes[{i}].id", "required", fm_blocks)
                continue
            if not _text(fid):
                c.bad(f"measurement.failure_modes[{i}].id", "must be text", fm_blocks)
                continue
            f = f"measurement.failure_modes[{fid}]"
            if fid in modes:
                c.bad(f"{f}.id", "used twice", fm_blocks)
                continue
            modes.append(fid)
            c.unknown_keys(fm, "measurement.failure_modes[]", f)
            ucs = fm.get("use_cases")
            if ucs is None:
                c.miss(f"{f}.use_cases", "required: the use cases it can occur in, or \"*\"", fm_blocks)
            elif ucs != ALL_USE_CASES:
                if not isinstance(ucs, list) or not ucs:
                    c.bad(f"{f}.use_cases", "must be \"*\" or a list of use case ids", fm_blocks)
                else:
                    for u in ucs:
                        if u not in ids:
                            c.bad(f"{f}.use_cases", f"'{u}' is not a use case of this eval", fm_blocks)
            check = fm.get("check")
            if fm.get("side_effect") is True and check is not None:
                side_effect = True  # the check's own problems are reported on it
            if fm.get("monitor") is True and check is None:
                counted[fid] = None  # a monitor is watched, never counted
            elif check is None:
                c.miss(f"{f}.check", "required: the one check that counts for this mode (rule 12)", fm_blocks)
            elif isinstance(check, list):
                c.bad(f"{f}.check", "exactly one check counts per failure mode (rule 12); list the others "
                      "under `diagnostics`", fm_blocks)
            elif not _text(check) or not ID_RE.match(check):
                c.bad(f"{f}.check", "must be a check id (the file name, without .py or .md)", fm_blocks)
            elif check in by_check:
                c.bad(f"{f}.check", f"'{check}' already counts for {by_check[check]}: one failure mode "
                      "per check (rule 11)", fm_blocks)
            else:
                by_check[check] = fid
                counted[fid] = check
                if c.ev is not None and c.ev.check_type(check) is None:
                    c.miss(f"{f}.check", f"no checks/code/{check}.py or checks/judge/{check}.md in this "
                           "eval", fm_blocks)
            diags = fm.get("diagnostics")
            if diags is not None:
                if not isinstance(diags, list) or not all(_text(x) for x in diags):
                    c.bad(f"{f}.diagnostics", "must be a list of check ids", [])
                elif check in diags:
                    c.bad(f"{f}.diagnostics", f"'{check}' is the counted check; a diagnostic is "
                          "reported, never counted (rule 12)", fm_blocks)
            if fm.get("side_effect") not in (None, True, False):
                c.bad(f"{f}.side_effect", "must be true or false", fm_blocks)
        if modes and not side_effect:
            c.miss("measurement.failure_modes", "no counted side-effect check: at least one mode with "
                   "`side_effect: true` and a check, so a run that changes what it shouldn't fails",
                   fm_blocks)

    trials = m.get("trials")
    if trials is None:
        c.miss("measurement.trials", "required: runs per case, 3 or more, or auto (rule 16)", ["run", "plan"])
    elif trials != "auto" and (not isinstance(trials, int) or isinstance(trials, bool) or trials < 3):
        c.bad("measurement.trials", "must be a whole number of at least 3, or auto (rule 16)", ["run", "plan"])

    judges = [ck for ck in counted.values() if ck and c.ev is not None and c.ev.check_type(ck) == "judge"]
    for ck in judges:  # 2.0 judges have no fixed floors (docs/v2-design.md §4)
        try:
            front = c.ev.judge_check_path(ck).read_text().split("---")
            meta = load_yaml_text(front[1]) if len(front) > 2 else {}
        except (OSError, ContractError):
            meta = {}
        old = [k for k in ("min_tpr", "min_tnr") if isinstance(meta, dict) and k in meta]
        if old:
            c.note(f"checks/judge/{ck}.md", f"{' and '.join(old)} are 1.x floors and are ignored: a 2.0 judge "
                   "counts when its inflation at the eval's failure rate is within measurement.max_inflation")
    corr = m.get("correction")
    if corr is not None and corr not in CORRECTIONS:
        c.bad("measurement.correction", f"must be one of {', '.join(CORRECTIONS)}", ["estimate"])
    elif corr is None and judges:
        c.miss("measurement.correction", f"required when a judge counts ({', '.join(judges)}): none, "
               "rogan_gladen or ppi", ["estimate"])
    elif corr == "none" and judges:
        c.note("measurement.correction", f"a judge counts ({', '.join(judges)}) and correction is none: "
               "its rate is reported uncorrected for its errors")
    mi = m.get("max_inflation")
    if mi is not None:
        if not _num(mi) or mi < 1:
            c.bad("measurement.max_inflation", "must be a number of at least 1: how many times the cases "
                  "of a code check a judge may cost (statistics §3.3)", ["measurement", "plan"])
    elif judges:
        c.default(m, "max_inflation", "measurement.max_inflation", DEFAULT_MAX_INFLATION)

    people = m.get("people")
    if people is None:
        people = m["people"] = {}
    if not isinstance(people, dict):
        c.bad("measurement.people", "must be a mapping", ["measurement"])
        return modes, counted
    c.unknown_keys(people, "measurement.people", "measurement.people")
    floors = people.get("floors")
    if floors is None:
        c.default(people, "floors", "measurement.people.floors", {"catch": None, "clean": None})
    elif not isinstance(floors, dict):
        c.bad("measurement.people.floors", "must be {catch, clean}", ["measurement"])
    else:
        for k in floors:
            if k not in KEYS["measurement.people.floors"]:
                hint = (f"; 2.0 calls it `{k.removeprefix('min_')}`"
                        if k in ("min_catch", "min_clean") else "")
                c.bad(f"measurement.people.floors.{k}", f"not a floor of the eval against people{hint}",
                      ["measurement"])
        for k in ("catch", "clean"):
            v = floors.get(k)
            if k not in floors:
                floors[k] = None
                c.defaults.append({"field": f"measurement.people.floors.{k}", "value": None})
            elif v is not None and not (_num(v) and 0 < v <= 1):
                c.bad(f"measurement.people.floors.{k}", "must be a rate above 0 and at most 1, or null "
                      "(null: set from max_inflation, as for a judge)", ["measurement"])
    margin = people.get("margin")
    if margin is None:
        c.default(people, "margin", "measurement.people.margin", DEFAULT_PEOPLE_MARGIN)
    elif not _unit_interval(margin):
        c.bad("measurement.people.margin", "must be a rate strictly between 0 and 1 (statistics §4.2)",
              ["measurement"])
    lpk = people.get("labels_per_kind")
    if lpk is None:
        c.default(people, "labels_per_kind", "measurement.people.labels_per_kind", "auto")
    elif lpk != "auto" and (not isinstance(lpk, int) or isinstance(lpk, bool) or lpk < 1):
        c.bad("measurement.people.labels_per_kind", "must be auto or a positive whole number", ["measurement"])
    return modes, counted


def _decision_rule(c: _Check, spec: dict, ids: list[str], quantity: Any) -> None:
    blocks = ["decision", "plan"]
    r = c.mapping(spec, "decision_rule", "decision_rule", blocks)
    if r is None:
        return
    c.unknown_keys(r, "decision_rule", "decision_rule")
    _gate_rule(c, "decision_rule", r, blocks)

    q = r.get("quantity")
    if q is None:
        if quantity is not None:
            c.default(r, "quantity", "decision_rule.quantity", quantity)
    elif quantity is not None and q != quantity:
        c.bad("decision_rule.quantity", f"is {q} but the estimand is {quantity}: the rule must decide on "
              "the number the eval estimates (rule 1)", ["decision"])

    alpha = r.get("alpha")
    if alpha is None:
        c.default(r, "alpha", "decision_rule.alpha", DEFAULT_ALPHA)
    elif not _num(alpha) or not 0 < alpha < 0.5:
        c.bad("decision_rule.alpha", "must be a one-sided level above 0 and below 0.5: 0.05 by default, "
              "0.025 where a bad change is costly or hard to reverse (statistics §4.5)", blocks)
    power = r.get("power")
    if power is None:
        c.default(r, "power", "decision_rule.power", DEFAULT_POWER)
    elif not _unit_interval(power):
        c.bad("decision_rule.power", "must be strictly between 0 and 1", blocks)
    looks = r.get("looks")
    if looks is None:
        c.default(r, "looks", "decision_rule.looks", DEFAULT_LOOKS)
    elif looks not in LOOKS:
        c.bad("decision_rule.looks", f"must be one of {', '.join(LOOKS)} (rule 21)", ["decision"])
    elif looks != "fixed":
        c.note("decision_rule.looks", f"{looks} needs an always-valid interval this version does not compute: "
               "the decision stays unknown until it does (rule 21)")

    gates = r.get("use_case_gates")
    n_gates = 1  # the headline
    if gates is not None:
        if not isinstance(gates, list):
            c.bad("decision_rule.use_case_gates", "must be a list", blocks)
        else:
            seen = set()
            for i, g in enumerate(gates):
                if not isinstance(g, dict):
                    c.bad(f"decision_rule.use_case_gates[{i}]", "must be a mapping", blocks)
                    continue
                uc = g.get("use_case")
                f = f"decision_rule.use_case_gates[{uc if _text(uc) else i}]"
                c.unknown_keys(g, "decision_rule.use_case_gates[]", f)
                if uc not in ids:
                    c.bad(f"{f}.use_case", "must be a use case of this eval", blocks)
                elif uc in seen:
                    c.bad(f"{f}.use_case", "has two gates; a use case has one rule (rule 20)", blocks)
                seen.add(uc)
                _gate_rule(c, f, g, blocks)
                n_gates += 1

    combine = r.get("combine")
    if combine is None:
        combine = c.default(r, "combine", "decision_rule.combine", DEFAULT_COMBINE)
    elif combine not in COMBINE:
        c.bad("decision_rule.combine", "must be all (every gate must pass) or any (one gate alone "
              "triggers the action)", ["decision"])
        combine = None
    mult = r.get("multiplicity")
    if mult is not None and mult not in MULTIPLICITY:
        c.bad("decision_rule.multiplicity", f"must be one of {', '.join(MULTIPLICITY)}", ["decision"])
    elif combine == "any" and n_gates > 1:
        # one gate alone acts: several chances at a false alarm (rule 22, statistics §4.6)
        if mult is None:
            c.miss("decision_rule.multiplicity", f"one of {n_gates} gates alone can trigger the action, so "
                   "the gates need a correction: holm, or benjamini_hochberg for a list of findings "
                   "(rule 22)", ["decision"])
        elif mult == "none":
            a = r["alpha"] if _num(r.get("alpha")) and 0 < r["alpha"] < 0.5 else DEFAULT_ALPHA
            c.bad("decision_rule.multiplicity", f"one of {n_gates} gates alone can trigger the action; "
                  f"uncorrected, the chance of a false alarm is up to {1 - (1 - a) ** n_gates:.0%}, "
                  f"not {a:.1%} (rule 22)", ["decision"])
    elif mult is None:
        c.default(r, "multiplicity", "decision_rule.multiplicity", "none")
    elif mult != "none" and combine == "all" and n_gates > 1:
        c.note("decision_rule.multiplicity", f"every gate must pass (an intersection-union test), so {mult} "
               "is not needed and only costs power (statistics §4.6)")

    reqs = r.get("also_requires")
    if reqs is not None:
        if not isinstance(reqs, list):
            c.bad("decision_rule.also_requires", "must be a list", ["decision"])
        else:
            for i, a in enumerate(reqs):
                if not isinstance(a, dict):
                    c.bad(f"decision_rule.also_requires[{i}]", "must be a mapping", ["decision"])
                    continue
                f = f"decision_rule.also_requires[{a.get('eval') if _text(a.get('eval')) else i}]"
                c.unknown_keys(a, "decision_rule.also_requires[]", f)
                if not _text(a.get("eval")):
                    c.miss(f"{f}.eval", "required: the other eval's id", ["decision"])
                _gate_rule(c, f, a, ["decision"])

    con = c.mapping(r, "constraints", "decision_rule.constraints", ["decision"], required=False)
    if con is not None:
        from .report import BUDGET_KEYS

        c.unknown_keys(con, "decision_rule.constraints", "decision_rule.constraints")
        sets = [("decision_rule.constraints.default", con.get("default"))]
        per = con.get("use_cases")
        if per is not None and not isinstance(per, dict):
            c.bad("decision_rule.constraints.use_cases", "must be {use_case: budgets}", ["decision"])
        elif per:
            for k, v in per.items():
                if k not in ids:
                    c.bad(f"decision_rule.constraints.use_cases[{k}]", "not a use case of this eval",
                          ["decision"])
                sets.append((f"decision_rule.constraints.use_cases[{k}]", v))
        for f, b in sets:
            if b is None:
                continue
            if not isinstance(b, dict):
                c.bad(f, "must be a mapping of budgets", ["decision"])
                continue
            for k, v in b.items():
                if k not in BUDGET_KEYS:
                    c.bad(f"{f}.{k}", f"not a budget; one of {', '.join(BUDGET_KEYS)}", ["decision"])
                elif v is not None and (not _num(v) or v < 0):
                    c.bad(f"{f}.{k}", "must be a number at or above 0, or null", ["decision"])


def _invoke(c: _Check, spec: dict, kind: str | None) -> None:
    inv = spec.get("invoke")
    if kind == "system":
        if inv is not None:
            c.bad("invoke", "the end-to-end eval invokes the agent through agent.yaml's invoke; "
                  "only a component eval has its own", ["run"])
        return
    if kind != "component":
        return
    if inv is None:
        c.miss("invoke", "a component eval calls the component directly with a handoff: "
               "{command, cwd, timeout}", ["run"])
        return
    if not isinstance(inv, dict):
        c.bad("invoke", "must be a mapping", ["run"])
        return
    c.unknown_keys(inv, "invoke", "invoke")
    cmd = inv.get("command")
    if not cmd:
        c.miss("invoke.command", "required: the argv that runs the component", ["run"])
    elif not isinstance(cmd, list) or not all(isinstance(x, str) for x in cmd):
        c.bad("invoke.command", "must be a list of strings (argv)", ["run"])
    t = inv.get("timeout")
    if t is not None and (not _num(t) or t <= 0):
        c.bad("invoke.timeout", "must be a positive number of seconds", ["run"])


# ---- across an agent's evals -----------------------------------------------------------------

def sibling_units(ev: Eval) -> dict[str, str | None]:
    """The unit kind of each other eval of the agent, read leniently."""
    out = {}
    for d in ev.agent_system.eval_dirs():
        if d.name == ev.id:
            continue
        try:
            data = load_yaml(d / "eval.yaml") or {}
        except ContractError:
            data = {}
        unit = (data.get("estimand") or {}).get("unit") if isinstance(data, dict) else None
        out[d.name] = unit.get("kind") if isinstance(unit, dict) else None
    return out


def _across(c: _Check, ev: Eval, spec: dict, kind: str | None) -> None:
    from .repo import RESERVED_EVAL_IDS

    if ev.id in RESERVED_EVAL_IDS or not ID_RE.match(ev.id):
        c.bad("eval", f"'{ev.id}' cannot name an eval folder: it is reserved or not an id", ["run"])
    sib = sibling_units(ev)
    systems = sorted(k for k, v in sib.items() if v == "system")
    if kind == "system" and systems:
        c.bad("estimand.unit.kind", f"{', '.join(systems)} is also a system eval; an agent has one "
              "end-to-end eval (rule 3)", ["run", "estimate", "decision"])
    reqs = (spec.get("decision_rule") or {}).get("also_requires") if isinstance(
        spec.get("decision_rule"), dict) else None
    named = [a.get("eval") for a in reqs if isinstance(a, dict)] if isinstance(reqs, list) else []
    for name in named:
        if name == ev.id:
            c.bad(f"decision_rule.also_requires[{name}]", "an eval cannot require itself", ["decision"])
        elif _text(name) and name not in sib:
            c.miss(f"decision_rule.also_requires[{name}]", f"no eval '{name}' in this agent", ["decision"])
    if kind == "component":
        if not systems:
            c.miss("decision_rule.also_requires", "this agent has no end-to-end eval yet; a component "
                   "change ships only when the end-to-end eval shows no regression (rule 27)", ["decision"])
        elif not set(systems) & set(named):
            c.miss("decision_rule.also_requires", f"a component change ships only when the end-to-end "
                   f"eval ({systems[0]}) shows no regression: add it with a non-inferiority test "
                   "(rule 27)", ["decision"])
        for a in reqs if isinstance(reqs, list) else []:
            if isinstance(a, dict) and a.get("eval") in systems and a.get("test") == "threshold":
                c.bad(f"decision_rule.also_requires[{a['eval']}].test", "the end-to-end eval must show no "
                      "regression on the same change, which takes a paired test against its baseline: "
                      "non_inferiority, or superiority (rules 19, 27)", ["decision"])
        _component(c, ev, spec, systems)
    elif kind == "system":
        _routes(c, ev, spec)


def _component(c: _Check, ev: Eval, spec: dict, systems: list[str]) -> None:
    """A component earns an eval only at a context boundary, when decided on separately (rule 3),
    and its population is the handoffs it receives (rule 4)."""
    from . import boundaries

    est = spec.get("estimand") if isinstance(spec.get("estimand"), dict) else {}
    unit = est.get("unit") if isinstance(est.get("unit"), dict) else {}
    name = unit.get("component")
    if not _text(name):
        return
    comps = boundaries.by_id(ev.agent_system.agent())
    comp = comps.get(name)
    blocks = ["estimate", "decision"]
    if comp is None:
        c.miss("estimand.unit.component", f"'{name}' is not in agent.yaml's components: name it there "
               "with its kind, context and whether it ships separately, so the eval can say why it has "
               "an eval of its own (rule 3)", blocks)
    else:
        p = boundaries.placement(comp)
        if p["placement"] == boundaries.UNKNOWN:
            c.miss(f"agent.yaml components[{name}].{p['needs']}", p["why"] + " (rule 3)", blocks)
        elif p["placement"] != boundaries.OWN_EVAL:
            c.bad("estimand.unit.component", p["why"], blocks)
    if systems:
        other = _peek(ev, systems[0])
        mine, theirs = (_decision_text(est), _decision_text((other or {}).get("estimand")))
        if mine and mine == theirs:
            c.bad("estimand.decision", f"the same decision as {systems[0]}: one decision, one eval "
                  "(rule 1); a component eval decides about the component", ["decision"])
    pop = est.get("population") if isinstance(est.get("population"), dict) else {}
    frame = pop.get("frame")
    entry = next((x for x in ev.exports() if isinstance(x, dict) and x.get("id") == frame), None)
    if entry is None:
        return  # a frame with no import is already missing
    h = entry.get("handoffs") if isinstance(entry.get("handoffs"), dict) else None
    if h is None or h.get("component") != name:
        into = f"handoffs into {h.get('component')}" if h else "no handoffs"
        src = f" --from {_peek_frame(ev, systems[0])}" if systems and _peek_frame(ev, systems[0]) else ""
        c.miss("estimand.population.frame", f"import '{frame}' holds {into}, not the handoffs {name} "
               f"receives (rule 4): `aot-evals --eval {ev.id} handoffs{src}` extracts them from the "
               f"end-to-end traces, or `import FILE --handoffs-of {name}` records handoffs captured as "
               "they happened", ["draw", "estimate"])
        return
    parent = h.get("from")
    current = _peek_frame(ev, systems[0]) if systems else None
    if parent and current and parent != current:
        c.note("estimand.population.frame", f"its handoffs were extracted from {parent}, but "
               f"{systems[0]} now draws from {current}: a new mix of traffic or a routing change upstream "
               "changes the handoffs too, so extract them again (rule 26)")


def _routes(c: _Check, ev: Eval, spec: dict) -> None:
    """Behind a router, each route is a use case of the end-to-end eval; one whose model ships on its
    own gets a use case gate (rule 20, v2-design §10.1). A subagent at a context boundary that ships
    on its own is told it can have an eval of its own (rule 3)."""
    from . import boundaries

    est = spec.get("estimand") if isinstance(spec.get("estimand"), dict) else {}
    ucs = {u.get("id") for u in est.get("use_cases") or [] if isinstance(u, dict)} if isinstance(
        est.get("use_cases"), list) else set()
    rule = spec.get("decision_rule") if isinstance(spec.get("decision_rule"), dict) else {}
    gates = rule.get("use_case_gates") if isinstance(rule.get("use_case_gates"), list) else []
    gated = {g.get("use_case") for g in gates if isinstance(g, dict)}
    units = _component_units(ev)
    for row in boundaries.plan(ev.agent_system.agent()):
        name, uc = row["id"], row.get("use_case")
        if row["placement"] in (boundaries.USE_CASE_GATE, boundaries.USE_CASE):
            if not _text(uc):
                c.miss("estimand.use_cases", f"route {name} gets the user's request as sent, so its "
                       f"requests are a use case of this eval: name it in agent.yaml (components[{name}]."
                       "use_case; rules 3, 20)", ["use_cases"] + (["decision"] if row["placement"] ==
                                                     boundaries.USE_CASE_GATE else []))
                continue
            if ucs and uc not in ucs:
                c.miss(f"estimand.use_cases[{uc}]", f"route {name} serves use case {uc}, which this eval "
                       "does not have: use cases partition the requests (rule 3)", ["draw", "estimate", "use_cases"])
            elif row["placement"] == boundaries.USE_CASE_GATE and uc not in gated:
                c.miss(f"decision_rule.use_case_gates[{uc}]", f"route {name}'s model ships on its own, so "
                       f"its use case needs a gate of its own (rule 20): {{use_case: {uc}, test: "
                       "non_inferiority, margin: ...}", ["decision"])
        elif row["placement"] == boundaries.OWN_EVAL and name not in units:
            c.note(f"agent.yaml components[{name}]", f"{name} has a context boundary and ships on its "
                   f"own: `aot-evals init --component {name}` gives it an eval of its own (rule 3)")


def _peek(ev: Eval, eval_id: str) -> dict | None:
    try:
        data = load_yaml(ev.agent_system.p(eval_id, "eval.yaml"))
    except ContractError:
        return None
    return data if isinstance(data, dict) else None


def _peek_frame(ev: Eval, eval_id: str) -> str | None:
    est = (_peek(ev, eval_id) or {}).get("estimand")
    pop = est.get("population") if isinstance(est, dict) else None
    f = pop.get("frame") if isinstance(pop, dict) else None
    return f if _text(f) else None


def _decision_text(est) -> str | None:
    d = est.get("decision") if isinstance(est, dict) else None
    if not isinstance(d, dict) or not _text(d.get("action")):
        return None
    return " ".join(str(d.get("action")).lower().split()) + "|" + " ".join(str(d.get("owner") or "").lower().split())


def _component_units(ev: Eval) -> set[str]:
    """The components that already have an eval in this agent."""
    out = set()
    for d in ev.agent_system.eval_dirs():
        if d.name == ev.id:
            continue
        est = (_peek(ev, d.name) or {}).get("estimand")
        unit = est.get("unit") if isinstance(est, dict) else None
        if isinstance(unit, dict) and unit.get("kind") == "component" and _text(unit.get("component")):
            out.add(unit["component"])
    return out


# ---- entry points ----------------------------------------------------------------------------

def check(data: Any, eval_id: str, ev: Eval | None = None, path: Path | None = None) -> Spec:
    """Validate an eval spec already read from YAML. With `ev`, also check it against the files
    around it: the frame's import, the check files, and the agent's other evals."""
    import copy

    path = path or Path("eval.yaml")
    c = _Check(ev)
    if data is None:
        c.miss("eval.yaml", "empty: no part of the eval is written down", list(BLOCKS))
        return Spec(eval_id, path, {}, {}, c.missing, c.invalid, c.notes, c.defaults)
    if not isinstance(data, dict):
        c.bad("eval.yaml", "must be a mapping of the four parts", list(BLOCKS))
        return Spec(eval_id, path, {}, {}, c.missing, c.invalid, c.notes, c.defaults)
    spec = copy.deepcopy(data)
    c.unknown_keys(spec, "", "")

    if spec.get("eval") is None:
        c.default(spec, "eval", "eval", eval_id)
    elif spec["eval"] != eval_id:
        c.bad("eval", f"says '{spec['eval']}' but the folder is '{eval_id}'; they name the same eval",
              ["run"])
    v = spec.get("version")
    if v is None:
        c.miss("version", "required: major.minor; a revision is a new major version (estimators §9)",
               ["comparison"])
    elif _version(v) is None:
        c.bad("version", "must be major.minor, e.g. 1.0", ["comparison"])
    else:
        spec["version"] = _version(v)

    kind, ids = _estimand(c, spec)
    _design(c, spec, ids)
    modes, counted = _measurement(c, spec, ids)

    est = spec.get("estimand") if isinstance(spec.get("estimand"), dict) else {}
    quantity = est.get("quantity")
    q_blocks = ["estimate", "decision", "plan"]
    if quantity is None:
        c.miss("estimand.quantity", "required: pass_rate, or failure_rate:<failure mode id>", q_blocks)
    elif quantity == "pass_rate":
        pass
    elif isinstance(quantity, str) and quantity.startswith("failure_rate:"):
        mode = quantity.split(":", 1)[1]
        if mode not in modes:
            c.bad("estimand.quantity", f"'{mode}' is not a failure mode of this eval", q_blocks)
            quantity = None
        elif counted.get(mode) is None and mode in counted:
            c.bad("estimand.quantity", f"'{mode}' is a monitor; an estimand needs a counted check", q_blocks)
            quantity = None
    else:
        c.bad("estimand.quantity", "must be pass_rate or failure_rate:<failure mode id>", q_blocks)
        quantity = None

    _decision_rule(c, spec, ids, quantity)
    _invoke(c, spec, kind)
    if ev is not None:
        _across(c, ev, spec, kind)
    return Spec(eval_id, path, data, spec, c.missing, c.invalid, c.notes, c.defaults)


def load(ev: Eval) -> Spec:
    """Read and validate one eval's eval.yaml. Never raises for a bad spec: invalid YAML is an
    issue like any other, so `validate` and the report can say what is wrong."""
    try:
        data = load_yaml(ev.spec_path)
    except ContractError as e:
        c = _Check(ev)
        c.bad("eval.yaml", str(e).split(": ", 1)[-1], list(BLOCKS))
        return Spec(ev.id, ev.spec_path, {}, {}, c.missing, c.invalid, c.notes, c.defaults)
    if data is None and not ev.spec_path.exists():
        raise ContractError(f"{ev.spec_path} does not exist")
    return check(data, ev.id, ev, ev.spec_path)


def use_cases(spec: Spec) -> list[dict]:
    """The estimand's use cases that have an id."""
    ucs = spec.part("estimand").get("use_cases")
    return [u for u in ucs if isinstance(u, dict) and _text(u.get("id"))] if isinstance(ucs, list) else []


def use_case_weights(spec: Spec) -> tuple[dict[str, float] | None, str | None]:
    """Each use case's weight in θ, normalized to sum to 1, and where it came from: `traffic`
    (w = share), `cost` (w ∝ share × cost, statistics §1.1) or `stated` ({use_case: w}). None when
    any share, cost or stated weight is missing or invalid: an unstated weight is unknown, never 1
    (rule 2)."""
    from .stats import objective_weights

    w = spec.part("estimand").get("weights")
    ucs = use_cases(spec)
    if not ucs:
        return None, None
    shares = {u["id"]: u.get("share") if _num(u.get("share")) else None for u in ucs}
    if w == "traffic":
        return objective_weights(shares, {k: 1.0 for k in shares}), "traffic"
    if w == "cost":
        costs = {u["id"]: u.get("cost") if _num(u.get("cost")) and u["cost"] > 0 else None for u in ucs}
        return objective_weights(shares, costs), "cost"
    if isinstance(w, dict):
        stated = {k: w.get(k) for k in shares}
        if any(not _num(v) or v < 0 for v in stated.values()) or sum(stated.values()) <= 0:
            return None, "stated"
        t = sum(stated.values())
        return {k: v / t for k, v in stated.items()}, "stated"
    return None, None


def quantity(spec: Spec) -> tuple[str | None, str | None]:
    """("pass_rate", None) or ("failure_rate", mode id); (None, None) when not stated or invalid."""
    q = spec.part("estimand").get("quantity")
    if q == "pass_rate":
        return "pass_rate", None
    if isinstance(q, str) and q.startswith("failure_rate:") and not any(
            i.field == "estimand.quantity" for i in (*spec.missing, *spec.invalid)):
        return "failure_rate", q.split(":", 1)[1]
    return None, None


def check_ids(spec: Spec) -> list[str]:
    """Every check the measurement model names: each mode's counted check and its diagnostics."""
    out: list[str] = []
    fms = spec.part("measurement").get("failure_modes")
    for fm in fms if isinstance(fms, list) else []:
        if not isinstance(fm, dict):
            continue
        for cid in ([fm.get("check")] + list(fm.get("diagnostics") or [])):
            if isinstance(cid, str) and cid not in out:
                out.append(cid)
    return out


def part_hashes(spec: Spec, ev: Eval | None = None) -> dict[str, str | None]:
    """`spec_sha`: one hash per part of the eval (v2-design §5), over that part as resolved (so
    writing a default out changes nothing). The measurement hash also covers the files of the
    checks it names, code and judge prompts, but not their calibration: a changed check is a new
    instrument (rule 13), a recalibration is not. A part that is absent hashes to None."""
    import hashlib
    import json

    out: dict[str, str | None] = {}
    for part in PARTS:
        body = spec.resolved.get(part)
        if body is None:
            out[part] = None
            continue
        payload: dict[str, Any] = {"part": body}
        if part == "measurement" and ev is not None:
            files = {}
            for cid in check_ids(spec):
                for kind, path in (("code", ev.code_check_path(cid)), ("judge", ev.judge_check_path(cid))):
                    if path.exists():
                        files[f"{kind}/{cid}"] = hashlib.sha256(path.read_bytes()).hexdigest()
            payload["checks"] = files
        blob = json.dumps(payload, sort_keys=True, default=str, ensure_ascii=False)
        out[part] = hashlib.sha256(blob.encode()).hexdigest()[:16]
    return out


def render(spec: Spec) -> str:
    """Plain text for `validate` and `status`."""
    lines = [f"eval {spec.eval_id}: " + ("complete" if spec.complete else
             f"{len(spec.missing)} missing, {len(spec.invalid)} invalid")]
    for label, items in (("missing", spec.missing), ("invalid", spec.invalid), ("note", spec.notes)):
        for i in items:
            blocks = f"  [blocks {', '.join(i.blocks)}]" if i.blocks else ""
            lines.append(f"  {label + ':':<9}{i.field}: {i.why}{blocks}")
    return "\n".join(lines)
