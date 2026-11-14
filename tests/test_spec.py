"""The 2.0 eval spec (docs/v2-design.md §2) and the eval layout (§1): spec.py, repo.Eval, init --eval.

The store's two specs (examples/store) are the fixture. With their frames imported and their check
files in place both are complete, so each mutation below must produce exactly the issue it targets.
"""

from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path

import pytest
import yaml

from aot_evals import cli, spec
from aot_evals.repo import Evals

STORE = Path(__file__).parents[1] / "examples" / "store" / "evals" / "agents" / "store"
CODE_CHECKS = {"end-to-end": ["reply-matches-order", "end-state-matches", "no-side-effects", "routed-correctly"],
               "refunds": ["amount-matches", "no-side-effects"]}
JUDGES = {"refunds": ["policy-judge"]}


@pytest.fixture
def store(tmp_path: Path, monkeypatch) -> Evals:
    """evals/agents/store/ with both evals, both frames imported and every counted check present."""
    root = tmp_path / "evals" / "agents" / "store"
    shutil.copytree(STORE, root)
    (root / "data").mkdir()
    (root / "data" / "export.manifest.json").write_text(json.dumps({"exports": [
        {"id": "support-requests-2026-10"}, {"id": "refund-handoffs-2026-10"}]}))
    for ev, ids in CODE_CHECKS.items():
        (root / ev / "checks" / "code").mkdir(parents=True)
        for i in ids:
            (root / ev / "checks" / "code" / f"{i}.py").write_text("def check(start, end, case):\n"
                                                                   "    return True, ''\n")
    for ev, ids in JUDGES.items():
        (root / ev / "checks" / "judge").mkdir(parents=True)
        for i in ids:
            (root / ev / "checks" / "judge" / f"{i}.md").write_text("---\nid: policy-judge\n---\n")
    monkeypatch.chdir(tmp_path)
    return Evals(root)


def _spec(ev: Evals, eval_id: str) -> dict:
    return yaml.safe_load((ev.p(eval_id, "eval.yaml")).read_text())


def _write(ev: Evals, eval_id: str, data: dict) -> None:
    ev.p(eval_id, "eval.yaml").write_text(yaml.safe_dump(data, sort_keys=False))


def _issues(s: spec.Spec) -> list[tuple[str, str]]:
    return ([("missing", i.field) for i in s.missing] + [("invalid", i.field) for i in s.invalid])


# ---- the store's specs ---------------------------------------------------------------------------

def test_store_specs_are_complete(store):
    for e in store.evals():
        s = e.spec()
        assert _issues(s) == [], spec.render(s)
        assert s.notes == [], spec.render(s)
        assert s.complete


def test_store_specs_without_their_files_say_what_is_missing(tmp_path, monkeypatch):
    """The example ships specs only: no frames imported, no check files yet."""
    root = tmp_path / "evals" / "agents" / "store"
    shutil.copytree(STORE, root)
    monkeypatch.chdir(tmp_path)
    s = Evals(root).eval("refunds").spec()
    fields = {f for _, f in _issues(s)}
    assert "estimand.population.frame" in fields
    assert "measurement.failure_modes[breaks-policy].check" in fields
    assert all(k == "missing" for k, _ in _issues(s))


def test_defaults_are_filled_and_listed(store):
    data = _spec(store, "end-to-end")
    for k in ("alpha", "power", "looks", "multiplicity"):
        del data["decision_rule"][k]
    del data["measurement"]["people"]
    _write(store, "end-to-end", data)
    s = store.eval("end-to-end").spec()
    assert s.complete
    r = s.part("decision_rule")
    assert (r["alpha"], r["power"], r["looks"], r["combine"], r["multiplicity"]) == (0.05, 0.80, "fixed", "all", "none")
    assert r["quantity"] == "pass_rate"
    assert s.part("measurement")["people"] == {"floors": {"catch": None, "clean": None}, "margin": 0.10,
                                               "labels_per_kind": "auto"}
    filled = {d["field"] for d in s.defaults}
    assert filled >= {"decision_rule.alpha", "decision_rule.power", "decision_rule.quantity",
                      "measurement.people.margin"}
    assert s.data["decision_rule"].get("alpha") is None  # the file as written is kept apart


def test_max_inflation_defaults_only_when_a_judge_counts(store):
    for eval_id, expect in (("refunds", 2.0), ("end-to-end", None)):
        data = _spec(store, eval_id)
        data["measurement"].pop("max_inflation", None)
        _write(store, eval_id, data)
        s = store.eval(eval_id).spec()
        assert s.complete
        assert s.part("measurement").get("max_inflation") == expect


def test_version_reads_unquoted_numbers(store):
    for written, read in ((1.0, "1.0"), (2, "2.0"), ("1.10", "1.10")):
        data = _spec(store, "refunds")
        data["version"] = written
        _write(store, "refunds", data)
        assert store.eval("refunds").spec().resolved["version"] == read


# ---- one issue per mutation ----------------------------------------------------------------------

def _set(path: str, value):
    def f(d):
        *head, last = path.split(".")
        for k in head:
            d = d[int(k)] if isinstance(d, list) else d[k]
        if isinstance(d, list):
            d.append(value)  # tests only ever extend a list
        elif value is _DEL:
            del d[last]
        else:
            d[last] = value
    return f


_DEL = object()

MUTATIONS = [
    # (eval, mutation, kind, field)
    # estimand
    ("refunds", _set("estimand.unit.kind", "subagent"), "invalid", "estimand.unit.kind"),
    ("refunds", _set("estimand.unit.boundary", _DEL), "missing", "estimand.unit.boundary"),
    ("refunds", _set("estimand.population.frame", _DEL), "missing", "estimand.population.frame"),
    ("refunds", _set("estimand.population.frame", "not-imported"), "missing", "estimand.population.frame"),
    ("refunds", _set("estimand.population.window", "2026-10-31/2026-10-01"), "invalid", "estimand.population.window"),
    ("refunds", _set("estimand.use_cases.0.share", 0.70), "invalid", "estimand.use_cases"),
    ("refunds", _set("estimand.use_cases.0.share", 1.5), "invalid", "estimand.use_cases[full-refund].share"),
    ("refunds", _set("estimand.use_cases.0.example", _DEL), "missing", "estimand.use_cases[full-refund].example"),
    ("refunds", _set("estimand.use_cases.2.cost", None), "missing", "estimand.use_cases[gift-card].cost"),
    ("refunds", _set("estimand.use_cases.2.cost", -1), "invalid", "estimand.use_cases[gift-card].cost"),
    ("refunds", _set("estimand.use_cases.1.id", "full-refund"), "invalid", "estimand.use_cases[full-refund].id"),
    ("refunds", _set("estimand.weights", _DEL), "missing", "estimand.weights"),
    ("refunds", _set("estimand.weights", "equal"), "invalid", "estimand.weights"),
    ("refunds", _set("estimand.weights", {"full-refund": 0.8, "partial-refund": 0.2}), "missing",
     "estimand.weights[gift-card]"),
    ("refunds", _set("estimand.weights", {"full-refund": 0.8, "partial-refund": 0.1, "gift-card": 0.5}),
     "invalid", "estimand.weights"),
    ("refunds", _set("estimand.decision.owner", _DEL), "missing", "estimand.decision.owner"),
    ("refunds", _set("estimand.quantity", "failure_rate:no-such-mode"), "invalid", "estimand.quantity"),
    ("refunds", _set("estimand.quantity", "accuracy"), "invalid", "estimand.quantity"),
    # design
    ("refunds", _set("design.quality_set.seed", _DEL), "missing", "design.quality_set.seed"),
    ("refunds", _set("design.quality_set.selection", "hand_picked"), "invalid", "design.quality_set.selection"),
    ("refunds", _set("design.quality_set.oversample", {"store-credit": 2}), "invalid",
     "design.quality_set.oversample[store-credit]"),
    ("refunds", _set("design.cluster_key", _DEL), "missing", "design.cluster_key"),
    # measurement
    ("refunds", _set("measurement.failure_modes.1.check", ["amount-matches", "policy-judge"]), "invalid",
     "measurement.failure_modes[wrong-amount].check"),
    ("refunds", _set("measurement.failure_modes.1.check", "no-side-effects"), "invalid",
     "measurement.failure_modes[unrequested-change].check"),
    ("refunds", _set("measurement.failure_modes.1.check", "no-such-check"), "missing",
     "measurement.failure_modes[wrong-amount].check"),
    ("refunds", _set("measurement.failure_modes.1.diagnostics", ["amount-matches"]), "invalid",
     "measurement.failure_modes[wrong-amount].diagnostics"),
    ("refunds", _set("measurement.failure_modes.2.side_effect", _DEL), "missing", "measurement.failure_modes"),
    ("refunds", _set("measurement.failure_modes.0.use_cases", ["store-credit"]), "invalid",
     "measurement.failure_modes[breaks-policy].use_cases"),
    ("refunds", _set("measurement.trials", 2), "invalid", "measurement.trials"),
    ("refunds", _set("measurement.trials", _DEL), "missing", "measurement.trials"),
    ("refunds", _set("measurement.correction", _DEL), "missing", "measurement.correction"),
    ("refunds", _set("measurement.correction", "bayes"), "invalid", "measurement.correction"),
    ("refunds", _set("measurement.max_inflation", 0.5), "invalid", "measurement.max_inflation"),
    ("refunds", _set("measurement.people.floors", {"min_catch": 0.85, "clean": None}), "invalid",
     "measurement.people.floors.min_catch"),
    ("refunds", _set("measurement.people.floors", {"catch": 1.2, "clean": None}), "invalid",
     "measurement.people.floors.catch"),
    ("refunds", _set("measurement.people.margin", 0), "invalid", "measurement.people.margin"),
    ("refunds", _set("measurement.people.labels_per_kind", 0), "invalid", "measurement.people.labels_per_kind"),
    # decision rule
    ("refunds", _set("decision_rule.test", _DEL), "missing", "decision_rule.test"),
    ("refunds", _set("decision_rule.test", "bayes_factor"), "invalid", "decision_rule.test"),
    ("refunds", _set("decision_rule.bar", None), "missing", "decision_rule.bar"),
    ("end-to-end", _set("decision_rule.margin", _DEL), "missing", "decision_rule.margin"),
    ("end-to-end", _set("decision_rule.margin", 2), "invalid", "decision_rule.margin"),
    ("refunds", _set("decision_rule.quantity", "pass_rate"), "invalid", "decision_rule.quantity"),
    ("refunds", _set("decision_rule.alpha", 0.5), "invalid", "decision_rule.alpha"),
    ("refunds", _set("decision_rule.alpha", 0), "invalid", "decision_rule.alpha"),
    ("refunds", _set("decision_rule.power", 1), "invalid", "decision_rule.power"),
    ("refunds", _set("decision_rule.looks", "whenever"), "invalid", "decision_rule.looks"),
    ("end-to-end", _set("decision_rule.combine", "some"), "invalid", "decision_rule.combine"),
    ("end-to-end", _set("decision_rule.multiplicity", "bonferroni"), "invalid", "decision_rule.multiplicity"),
    ("end-to-end", _set("decision_rule.use_case_gates.0.use_case", "store-credit"), "invalid",
     "decision_rule.use_case_gates[store-credit].use_case"),
    ("end-to-end", _set("decision_rule.use_case_gates.0.margin", _DEL), "missing",
     "decision_rule.use_case_gates[refund].margin"),
    ("refunds", _set("decision_rule.also_requires.1", {"eval": "checkout", "test": "non_inferiority",
                                                       "margin": 0.02}), "missing",
     "decision_rule.also_requires[checkout]"),
    ("refunds", _set("decision_rule.constraints.default", {"cost_per_turn_usd": 0.1}), "invalid",
     "decision_rule.constraints.default.cost_per_turn_usd"),
    # invoke
    ("refunds", _set("invoke", _DEL), "missing", "invoke"),
    ("refunds", _set("invoke.command", "python agent/refunds.py"), "invalid", "invoke.command"),
    ("end-to-end", _set("invoke", {"command": ["python", "agent.py"]}), "invalid", "invoke"),
    # top level
    ("refunds", _set("eval", "refund-subagent"), "invalid", "eval"),
    ("refunds", _set("version", "one"), "invalid", "version"),
    ("refunds", _set("version", _DEL), "missing", "version"),
]


@pytest.mark.parametrize("eval_id,mutate,kind,field", MUTATIONS,
                         ids=[f"{m[0]}:{m[2]}:{m[3]}" for m in MUTATIONS])
def test_each_mutation_triggers_exactly_its_issue(store, eval_id, mutate, kind, field):
    data = _spec(store, eval_id)
    mutate(data)
    _write(store, eval_id, data)
    s = store.eval(eval_id).spec()
    assert _issues(s) == [(kind, field)], spec.render(s)
    assert not s.complete
    assert all(b in spec.BLOCKS for i in (*s.missing, *s.invalid) for b in i.blocks)


# ---- the four fields from #21 --------------------------------------------------------------------

def test_decision_quantity_must_match_the_estimand(store):
    data = _spec(store, "refunds")
    data["decision_rule"]["quantity"] = "failure_rate:wrong-amount"
    _write(store, "refunds", data)
    s = store.eval("refunds").spec()
    assert _issues(s) == [("invalid", "decision_rule.quantity")]
    assert "failure_rate:breaks-policy" in s.invalid[0].why
    # left out, it is the estimand's
    del data["decision_rule"]["quantity"]
    _write(store, "refunds", data)
    s = store.eval("refunds").spec()
    assert s.complete and s.part("decision_rule")["quantity"] == "failure_rate:breaks-policy"


def test_people_floors(store):
    data = _spec(store, "refunds")
    data["measurement"]["people"]["floors"] = {"catch": 0.85}
    _write(store, "refunds", data)
    s = store.eval("refunds").spec()
    assert s.complete
    assert s.part("measurement")["people"]["floors"] == {"catch": 0.85, "clean": None}
    assert {"field": "measurement.people.floors.clean", "value": None} in s.defaults


def test_alpha_is_one_sided_and_defaults_to_005(store):
    data = _spec(store, "refunds")
    data["decision_rule"]["alpha"] = 0.025  # the costly-to-reverse choice (statistics §4.5)
    _write(store, "refunds", data)
    assert store.eval("refunds").spec().complete
    del data["decision_rule"]["alpha"]
    _write(store, "refunds", data)
    s = store.eval("refunds").spec()
    assert s.part("decision_rule")["alpha"] == 0.05
    assert {"field": "decision_rule.alpha", "value": 0.05} in s.defaults
    data["decision_rule"]["alpha"] = 0.95  # a confidence level, not a one-sided α
    _write(store, "refunds", data)
    s = store.eval("refunds").spec()
    assert _issues(s) == [("invalid", "decision_rule.alpha")]
    assert "one-sided" in s.invalid[0].why


@pytest.mark.parametrize("combine,mult,expect", [
    ("all", None, []),                                       # intersection-union: none needed
    ("all", "none", []),
    ("any", None, [("missing", "decision_rule.multiplicity")]),
    ("any", "none", [("invalid", "decision_rule.multiplicity")]),
    ("any", "holm", []),
    ("any", "benjamini_hochberg", []),
])
def test_multiplicity_is_required_only_when_one_gate_alone_acts(store, combine, mult, expect):
    data = _spec(store, "end-to-end")  # the headline plus the refund gate: two gates
    data["decision_rule"]["combine"] = combine
    data["decision_rule"].pop("multiplicity")
    if mult is not None:
        data["decision_rule"]["multiplicity"] = mult
    _write(store, "end-to-end", data)
    s = store.eval("end-to-end").spec()
    assert _issues(s) == expect, spec.render(s)
    if not expect and mult is None:
        assert s.part("decision_rule")["multiplicity"] == "none"


def test_multiplicity_with_one_gate_is_never_required(store):
    data = _spec(store, "end-to-end")
    data["decision_rule"]["combine"] = "any"
    data["decision_rule"]["use_case_gates"] = []
    data["decision_rule"].pop("multiplicity")
    _write(store, "end-to-end", data)
    assert store.eval("end-to-end").spec().complete


def test_a_correction_where_every_gate_must_pass_is_a_note(store):
    data = _spec(store, "end-to-end")
    data["decision_rule"]["multiplicity"] = "holm"
    _write(store, "end-to-end", data)
    s = store.eval("end-to-end").spec()
    assert s.complete
    assert [n.field for n in s.notes] == ["decision_rule.multiplicity"]


# ---- across an agent's evals ---------------------------------------------------------------------

def test_one_system_eval_per_agent(store):
    shutil.copytree(store.p("end-to-end"), store.p("end-to-end-2"))
    data = _spec(store, "end-to-end-2")
    data["eval"] = "end-to-end-2"
    _write(store, "end-to-end-2", data)
    s = store.eval("end-to-end-2").spec()
    assert ("invalid", "estimand.unit.kind") in _issues(s)


def test_a_component_eval_requires_the_end_to_end_eval(store):
    data = _spec(store, "refunds")
    data["decision_rule"]["also_requires"] = []
    _write(store, "refunds", data)
    s = store.eval("refunds").spec()
    assert _issues(s) == [("missing", "decision_rule.also_requires")]
    assert "rule 27" in s.missing[0].why
    shutil.rmtree(store.p("end-to-end"))
    s = store.eval("refunds").spec()
    assert _issues(s) == [("missing", "decision_rule.also_requires")]
    assert "no end-to-end eval" in s.missing[0].why


def test_unknown_keys_are_notes_with_a_suggestion(store):
    data = _spec(store, "refunds")
    data["decision_rule"]["aplha"] = 0.01
    _write(store, "refunds", data)
    s = store.eval("refunds").spec()
    assert s.complete
    assert [(n.field, "`alpha`" in n.why) for n in s.notes] == [("decision_rule.aplha", True)]


def test_invalid_yaml_is_an_issue_not_a_crash(store):
    store.p("refunds", "eval.yaml").write_text("estimand: [unclosed\n")
    s = store.eval("refunds").spec()
    assert [i.field for i in s.invalid] == ["eval.yaml"]
    assert set(s.invalid[0].blocks) == set(spec.BLOCKS)


# ---- layout and commands -------------------------------------------------------------------------

def test_eval_selection(store, monkeypatch):
    assert [e.id for e in store.evals()] == ["end-to-end", "refunds"]
    with pytest.raises(Exception, match="several evals"):
        store.eval()
    monkeypatch.chdir(store.p("refunds"))
    assert store.eval().id == "refunds"  # the folder you are in
    e = store.eval("refunds")
    assert e.shared("env") == store.p("env") and e.env_dir == store.p("env")
    assert e.standard_path == store.p("labels", "standard.md")
    assert e.check_type("policy-judge") == "judge" and e.check_type("amount-matches") == "code"
    with pytest.raises(Exception, match="no eval 'checkout'"):
        store.eval("checkout")


def test_shared_folders_are_never_evals(store):
    (store.p("data") / "eval.yaml").write_text("eval: data\n")
    assert [e.id for e in store.evals()] == ["end-to-end", "refunds"]


def test_validate_and_status(store, capsys):
    evals = str(store.root.parents[1])
    assert cli.main(["--evals", evals, "--agent", "store", "validate"]) == 0
    assert cli.main(["--evals", evals, "--agent", "store", "--eval", "refunds", "status", "--json"]) == 0
    out = json.loads(capsys.readouterr().out.split("\n0 problem(s)\n", 1)[1])
    assert [e["eval"] for e in out["evals"]] == ["refunds"] and out["evals"][0]["complete"]
    data = _spec(store, "refunds")
    del data["decision_rule"]["test"]
    _write(store, "refunds", data)
    assert cli.main(["--evals", evals, "--agent", "store", "validate"]) == 1
    assert "missing: decision_rule.test" in capsys.readouterr().out


def test_unready_commands_refuse_2_0_evals(store):
    evals = str(store.root.parents[1])
    with pytest.raises(SystemExit, match="does not read 2.0 evals"):
        cli.main(["--evals", evals, "--agent", "store", "redundancy"])


def test_init_eval(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert cli.main(["--agent", "shop", "--eval", "end-to-end", "init"]) == 0
    assert cli.main(["--agent", "shop", "init", "--component", "refund-subagent"]) == 0
    agent = tmp_path / "evals" / "agents" / "shop"
    for p in ("agent.yaml", "env", "data/export.manifest.json", "labels/standard.md", ".gitignore",
              "end-to-end/eval.yaml", "end-to-end/coverage.yaml", "end-to-end/cases", "end-to-end/runs",
              "refund-subagent/eval.yaml", "refund-subagent/checks/judge"):
        assert (agent / p).exists(), p
    for p in ("categories.yaml", "failure_modes.yaml", "taxonomy.yaml"):
        assert not (agent / p).exists()  # no 1.x suite files beside 2.0 evals
    assert "*/runs/*/raw/" in (agent / ".gitignore").read_text()

    ev = Evals(agent)
    sys_spec, comp_spec = ev.eval("end-to-end").spec(), ev.eval("refund-subagent").spec()
    assert sys_spec.resolved["estimand"]["unit"] == {"kind": "system"}
    assert comp_spec.resolved["estimand"]["unit"]["component"] == "refund-subagent"
    assert comp_spec.resolved["decision_rule"]["also_requires"][0]["eval"] == "end-to-end"
    # the template is incomplete, and says so field by field; it never fails to load
    assert not sys_spec.complete and not comp_spec.complete
    assert "invoke.command" in {i.field for i in comp_spec.missing}
    assert all(f != "invoke" for f in (i.field for i in sys_spec.invalid))

    capsys.readouterr()
    assert cli.main(["--agent", "shop", "--eval", "again", "init"]) == 2  # a second system eval
    assert "already this agent's end-to-end eval" in capsys.readouterr().err
    assert cli.main(["--agent", "shop", "--eval", "data", "init"]) == 2  # a shared folder
    with pytest.raises(SystemExit, match="holds 2.0 evals"):
        cli.main(["--agent", "shop", "init"])
    # re-running creates nothing and overwrites nothing
    before = (agent / "end-to-end" / "eval.yaml").read_text()
    assert cli.main(["--agent", "shop", "init", "--eval", "end-to-end"]) == 0
    assert (agent / "end-to-end" / "eval.yaml").read_text() == before


def test_filled_template_is_complete(tmp_path, monkeypatch):
    """The template's shape is the schema's: filling its blanks with the store's values completes it."""
    monkeypatch.chdir(tmp_path)
    assert cli.main(["--agent", "store", "--eval", "end-to-end", "init"]) == 0
    ev = Evals(tmp_path / "evals" / "agents" / "store")
    data = yaml.safe_load(ev.p("end-to-end", "eval.yaml").read_text())
    store_e2e = yaml.safe_load((STORE / "end-to-end" / "eval.yaml").read_text())
    for part in spec.PARTS:
        assert set(data[part]) <= set(spec.KEYS[part]), part
        data[part] = copy.deepcopy(store_e2e[part])
    ev.p("data", "export.manifest.json").write_text(json.dumps({"exports": [{"id": "support-requests-2026-10"}]}))
    for i in CODE_CHECKS["end-to-end"]:
        ev.p("end-to-end", "checks", "code", f"{i}.py").write_text("")
    _write(ev, "end-to-end", data)
    s = ev.eval("end-to-end").spec()
    assert s.complete, spec.render(s)


def test_v1_suites_are_untouched(tmp_path, monkeypatch):
    """A 1.x suite has no eval folders: --eval is the only way into the 2.0 path."""
    monkeypatch.chdir(tmp_path)
    assert cli.main(["--agent", "old", "init"]) == 0
    ev = Evals(tmp_path / "evals" / "agents" / "old")
    assert (ev.p("categories.yaml")).exists() and not ev.has_evals and ev.has_v1_suite
