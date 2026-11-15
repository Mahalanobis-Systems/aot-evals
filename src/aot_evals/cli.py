"""`aot-evals`: the deterministic half of the plugin. The skills do the judgement half.

    aot-evals demo [DIR]                the online store, two evals and a candidate, to try it in minutes
    aot-evals doctor                    check the environment (paste into bug reports)
    aot-evals --eval ID init [--component NAME]   create one eval folder with its eval.yaml (default: end-to-end)
    aot-evals status [--json]           each eval: complete, or what its spec still lacks
    aot-evals validate [--warnings]     every missing or invalid field of each eval spec, and case problems
    aot-evals import FILE ...           copy an export into data/, record provenance
    aot-evals --eval ID plan [--write]  case targets per use case and pool, from the decision rule
    aot-evals --eval ID draw            the seeded stratified draw of the quality set, with π
    aot-evals --eval ID handoffs [--scan]   a component eval's frame, the handoffs in end-to-end traces
    aot-evals screen [--read-by NAME]   reference / do-nothing / non-answer / liar screens per case
    aot-evals run --purpose P [--k N]   smoke, baseline and candidate runs (k from measurement.trials)
    aot-evals build [--run]             drafts, the checklist per eval and part, then the baselines
    aot-evals serve [--open]            the grader application: label runs, rule, triage, rules, judges
    aot-evals components [--json]       the optimization loop's components, by part, as a checklist
    aot-evals migrate --to 2 [--dry-run]   convert a 1.x suite into a 2.0 end-to-end eval (MIGRATION.md)
    aot-evals label queue|page|import|add|status   human labels per judge (page: label in a browser)
    aot-evals calibrate --judge ID      catch and clean pass rates per backend, on the labels
    aot-evals reliability --judge ID    self-consistency and cross-family agreement
    aot-evals judge apply --judge ID --run ID   judge a past run
    aot-evals compare --candidate ID    the paired comparison and the decision on the candidate
    aot-evals coverage                  coverage list entry x failure mode over the bug-finding set
    aot-evals ops [--run ID|--export]   operational sweep against the spec's constraints
    aot-evals snapshot [--exclude GLOB] a hash per file of the working tree, for an observe hook
    aot-evals report [--run ID ...]     write <eval>/report/report.json (schema aot-evals/report@2)
    aot-evals log TEXT [--kind K]       add to the activity log (every command logs itself)
    aot-evals activity [--open]         render the live activity page, journal/activity.html
    aot-evals telemetry [status|show|off|on]   pseudonymous usage telemetry (SECURITY.md#telemetry)
    aot-evals benchmarks --workload TAG --task "..."   public benchmarks that fit, from the local catalog
"""

from __future__ import annotations

import argparse
import json
import sys
import time

from . import __version__, journal, telemetry
from . import ops as ops_mod
from . import runner as runner_mod
from . import screen as screen_mod
from .importer import import_export
from .repo import Evals
from .util import ContractError


def _evals(args) -> Evals:
    """The agent system's folder. A folder that still holds a 1.x suite is refused: 2.0 reads only
    eval folders, and `aot-evals migrate --to 2` converts it (MIGRATION.md lists what it did)."""
    try:
        ev = Evals.find(args.evals, args.agent)
    except ContractError as e:
        sys.exit(str(e))
    if args.cmd not in ("init", "build") and not ev.exists():
        sys.exit(f"no agent at {ev.root}; run `aot-evals --agent NAME --eval end-to-end init` in the "
                 "repository root, or pass --evals PATH")
    if args.cmd != "migrate" and ev.has_v1_suite and not ev.has_evals:
        sys.exit(f"{ev.root} holds a 1.x suite (categories.yaml, failure_modes.yaml, ...); 2.0 reads "
                 "eval folders only. `aot-evals migrate --to 2` converts it into an end-to-end eval")
    return ev


def _one_eval(args, ev: Evals):
    """The eval a 2.0 command works on: --eval, or the agent's only eval."""
    try:
        return ev.eval(getattr(args, "eval", None))
    except ContractError as e:
        sys.exit(str(e))


def _target(args):
    """The eval a command works on: --eval, or the agent's only eval."""
    return _one_eval(args, _evals(args))


def _default_runs(ev) -> list[str]:
    from .report_v2 import default_runs

    return default_runs(ev)


def _selected_evals(args, ev: Evals) -> list:
    """--eval names one; otherwise every eval of the agent."""
    try:
        return [ev.eval(args.eval)] if args.eval else ev.evals()
    except ContractError as e:
        sys.exit(str(e))


def cmd_init(args) -> int:
    from .scaffold import init_eval

    ev = _evals(args)
    if args.component and not args.eval:
        args.eval = args.component  # a component eval is named for its component by default
    args.eval = args.eval or "end-to-end"  # every agent's first eval
    try:
        created = init_eval(ev, args.eval, args.component)
    except ContractError as e:
        sys.exit(str(e))
    print(f"eval at {ev.p(args.eval)}")
    for c in created:
        print(f"  created {c}")
    if not created:
        print("  nothing to create; every file already exists")
    print(f"next: fill {args.eval}/eval.yaml, then aot-evals --eval {args.eval} validate")
    return 0


def cmd_status(args) -> int:
    ev = _evals(args)
    if not ev.has_evals:
        sys.exit(f"no eval in {ev.root} yet: `aot-evals --eval end-to-end init` creates the first")
    specs = [e.spec() for e in _selected_evals(args, ev)]
    if args.json:
        print(json.dumps({"agent": str(ev.root),
                          "evals": [{"eval": s.eval_id, **s.as_dict()} for s in specs]}, indent=2))
        return 0
    print(f"agent at {ev.root}")
    for s in specs:
        state = "complete" if s.complete else f"{len(s.missing)} missing, {len(s.invalid)} invalid"
        blocked = sorted({b for i in (*s.missing, *s.invalid) for b in i.blocks})
        print(f"  {s.eval_id:<20} {state}" + (f"  (blocks {', '.join(blocked)})" if blocked else ""))
    if not all(s.complete for s in specs):
        print("\nnext: aot-evals validate, for each missing or invalid field")
    return 0


def _grouped(problems: list[str], show: int = 5) -> list[str]:
    """Problems that differ only by case id, as one line: `N cases: <problem> (a, b, c, +N more)`."""
    import re

    groups: dict[str, list[str]] = {}
    order: list[str] = []
    for p in problems:
        m = re.match(r"case (\S+): (.*)$", p)
        key = m.group(2) if m else p
        if key not in groups:
            order.append(key)
        groups.setdefault(key, []).append(m.group(1) if m else "")
    out = []
    for key in order:
        ids = [i for i in groups[key] if i]
        if len(ids) > 1:
            more = f", +{len(ids) - show} more" if len(ids) > show else ""
            out.append(f"{len(ids)} cases: {key} ({', '.join(ids[:show])}{more})")
        else:
            out.append(f"case {ids[0]}: {key}" if ids else key)
    return out


def cmd_validate(args) -> int:
    from . import spec as spec_mod

    ev = _evals(args)
    n_problems = 0
    for e in _selected_evals(args, ev):
        s = e.spec()
        if not args.warnings:
            s.notes = []
        print(spec_mod.render(s))
        if args.warnings and s.defaults:
            print("  defaults: " + ", ".join(f"{d['field']} = {d['value']}" for d in s.defaults))
        n_problems += len(s.missing) + len(s.invalid)
        from .design import case_issues

        for c in case_issues(e):
            for p in c["problems"]:
                print(f"  case:    {c['path'] or c['id']}: {p}")
            n_problems += len(c["problems"])
    print(f"\n{n_problems} problem(s)")
    return 1 if n_problems else 0


def cmd_import(args) -> int:
    from pathlib import Path

    ev = _evals(args)
    entry = import_export(ev, Path(args.file), source=args.source, query=args.query,
                          window=args.window, export_id=args.id, notes=args.notes,
                          handoffs_of=args.handoffs_of)
    print(json.dumps(entry, indent=2))
    if entry["rows"] is None:
        print("warning: could not count rows; C0 needs a row count. Use .jsonl, .csv, .tsv or "
              "a JSON array.", file=sys.stderr)
    return 0


def cmd_handoffs(args) -> int:
    from . import handoffs as handoffs_mod

    ev = _evals(args)
    try:
        if args.scan or not args.eval and not ev.has_evals:
            s = handoffs_mod.scan_frame(ev, args.source)
            print(json.dumps(s, indent=2) if args.json else handoffs_mod.render_scan(s))
            return 0
        e = _one_eval(args, ev)
        entry = handoffs_mod.extract(e, args.source, args.id, dry_run=args.dry_run)
    except (ContractError, KeyError, FileNotFoundError) as err:
        sys.exit(str(err).strip("'\""))
    if args.json:
        print(json.dumps(entry, indent=2))
    else:
        print(handoffs_mod.render_extract(entry, e.spec().part("design").get("cluster_key")))
        if entry.get("file"):
            frame = (e.spec().part("estimand").get("population") or {}).get("frame")
            if frame != entry["id"]:
                print(f"  next: set estimand.population.frame to {entry['id']} in {e.id}/eval.yaml, then draw")
            else:
                print(f"  next: aot-evals --eval {e.id} draw")
    return 0


def cmd_plan(args) -> int:
    from . import plan as plan_mod

    e = _one_eval(args, _evals(args))
    p = plan_mod.plan(e, assumed_rate=args.assumed_rate, flip_rate=args.flip_rate, total=args.total)
    if args.mark_short:
        if not args.reason:
            sys.exit("--mark-short needs --reason")
        for row in p["rows"]:
            if row["status"] == "short":
                row["status"], row["reason"] = args.mark_short, args.reason
    print(json.dumps(p, indent=2) if args.json else plan_mod.render(p))
    if args.write:
        plan_mod.write(e, p)
        print(f"\nwrote {e.p('plan.yaml')}")
    return 0


def cmd_draw(args) -> int:
    from . import design

    e = _one_eval(args, _evals(args))
    n = {}
    for item in args.n or []:
        uc, sep, v = item.partition("=")
        if not sep or not v.isdigit():
            sys.exit(f"--n takes USE_CASE=N, not {item!r}")
        n[uc] = int(v)
    r = design.draw(e, n=n, skip=args.skip or None, reason=args.reason, prune=args.prune,
                    dry_run=args.dry_run)
    print(design.render_draw(r))
    return 1 if r.get("refused") else 0


def cmd_screen(args) -> int:
    ev = _target(args)
    if args.read_by and not (args.case or args.all):
        sys.exit("--read-by records a human read: name the cases read with --case (repeatable), "
                 "or pass --all if NAME really read every case")
    rows = screen_mod.run_screen(ev, case_ids=args.case or None, read_by=args.read_by,
                                 drop=args.drop, reason=args.reason, judges=args.judges)
    print(f"  {'case':<32} {'read':>5} {'ref':>5} {'noop':>5}  status")
    for r in rows:
        def f(v):
            return {True: "yes", False: "NO", None: "-"}[v]
        if r.get("dropped"):
            status = f"dropped: {r.get('drop_reason')}"
        else:
            status = "ok" if r["passes"] else "; ".join(r.get("notes") or []) or "incomplete"
            if r.get("failing_reference_checks"):
                status += " | reference fails: " + "; ".join(r["failing_reference_checks"])
        print(f"  {r['case']:<32} {f(r['human_read']):>5} {f(r['reference_passes']):>5} "
              f"{f(r['donothing_fails']):>5}  {status}")
    dropped = sum(1 for r in rows if r.get("dropped"))
    print(f"\ndrop rate {dropped}/{len(rows)}")
    return 0


def compare_variables() -> list[str]:
    from .compare import VARIABLES

    return list(VARIABLES)


def cmd_run(args) -> int:
    return _run_v2(args, _evals(args))


def _run_v2(args, ev: Evals) -> int:
    """`run` on a 2.0 eval: k from the spec's trials, use cases in place of categories, and the
    spec's missing fields recorded in the manifest instead of gates (docs/v2-design.md §5)."""
    e = _one_eval(args, ev)
    log = _progress(ev, journal.command_gate("run", args.purpose or "resume"))
    if args.resume:
        given = [flag for flag, v in (("--purpose", args.purpose), ("--k", args.k), ("--case", args.case),
                                      ("--use-case", args.use_case), ("--question", args.question),
                                      ("--variable", args.variable), ("--model", args.model),
                                      ("--label", args.label)) if v not in (None, False)]
        if given:
            sys.exit(f"refused: --resume carries on the run as its manifest recorded it; drop "
                     f"{', '.join(given)}")
        m = runner_mod.resume(e, args.resume, log=log, judges=not args.no_judges,
                              pause_every=args.pause_every, pause_seconds=args.pause_seconds,
                              stop_after=args.stop_after)
        return _run_summary(e, m)
    if not args.purpose:
        sys.exit("aot-evals run: --purpose is required (or --resume RUN_ID)")
    spec = e.spec()
    if args.k is None:
        # trials: auto is 3 until a baseline measures the variance split, then from it (rule 16)
        from .measurement import trials_for_run

        t = trials_for_run(e)
        args.k = 1 if args.purpose == "smoke" else t["k"]
        if t["spec"] == "auto" and args.purpose != "smoke":
            print(f"note: trials auto: k = {t['k']} ({t['source']})", file=sys.stderr)
    if args.purpose == "baseline" and args.k < 3:
        sys.exit("refused: a baseline needs k >= 3 to measure variance (rule 16)")
    if args.model and args.purpose == "candidate" and not args.variable:
        args.variable = f"model={args.model}"
    if args.purpose == "candidate" and not args.variable:
        sys.exit("refused: a candidate run declares its one independent variable, e.g. --variable "
                 "model=claude-haiku-4-5 or --variable prompt=v7. Kinds: "
                 + ", ".join(sorted(compare_variables())))
    for i in spec.blocked("run"):
        print(f"note: {i.field}: {i.why}", file=sys.stderr)
    m = runner_mod.run(e, purpose=args.purpose, k=args.k, case_ids=args.case or None,
                       categories=args.use_case or None, variable=args.variable,
                       label=args.label, adhoc_question=args.question, model=args.model,
                       log=log, judges=not args.no_judges, pause_every=args.pause_every,
                       pause_seconds=args.pause_seconds, stop_after=args.stop_after)
    return _run_summary(e, m)


def _run_summary(ev: Evals, m: dict) -> int:
    print(f"run {m['run_id']}: {m['counts']}  cost ${m['cost_usd'] or 0:.4f}")
    print(f"  {ev.p('runs', m['run_id'])}")
    if m.get("stopped"):
        print(f"  STOPPED, not finished: {m['stopped']['reason']}")
        print(f"  carry on with: aot-evals run --resume {m['run_id']}")
        return 1
    return 0


def _spec(ev: Evals, judge_id: str):
    from .judges import load_spec

    path = ev.judge_check_path(judge_id)
    if not path.exists():
        sys.exit(f"no judge {judge_id}: expected {path}")
    spec = load_spec(path)
    if spec.problems():
        sys.exit("invalid judge spec:\n" + "\n".join(f"  - {p}" for p in spec.problems()))
    return spec


def _judge_ids(ev: Evals, judge_id: str | None) -> list[str]:
    if judge_id:
        return [judge_id]
    from .spec import check_ids

    return sorted(c for c in check_ids(ev.spec()) if ev.check_type(c) == "judge")


def cmd_label(args) -> int:
    from pathlib import Path

    from . import label_page
    from . import labels as labels_mod

    ev = _target(args)
    if args.action == "status":
        ids = _judge_ids(ev, args.judge)
        if not ids:
            print("no judge checks")
        for jid in ids:
            print(labels_mod.render_status(labels_mod.status(ev, _spec(ev, jid))))
        return 0
    if not args.judge:
        sys.exit("--judge is required")
    spec = _spec(ev, args.judge)
    if args.action == "queue":
        runs = args.run or _default_runs(ev)
        if not runs:
            sys.exit("no runs to sample from; run the agent first (aot-evals run)")
        path, picked = labels_mod.make_queue(ev, spec, runs, args.n, args.seed)
        by_cat: dict[str, int] = {}
        for it in picked:
            by_cat[it["category"]] = by_cat.get(it["category"], 0) + 1
        print(f"wrote {len(picked)} items to {path} (git-ignored), stratified: {by_cat}")
        page = label_page.write(ev, spec)
        print(f"label them on the page {page} (git-ignored), or fill the `label` column with "
              f"pass/fail (and `labeller`); then: aot-evals label import --judge {spec.id} --csv FILE")
        if args.open:
            _open(page)
        return 0
    if args.action == "page":
        page = label_page.write(ev, spec)
        print(f"wrote {page} (git-ignored); its Download CSV feeds "
              f"aot-evals label import --judge {spec.id} --csv FILE")
        if args.open:
            _open(page)
        return 0
    if args.action == "import":
        if not args.csv:
            sys.exit("label import needs --csv FILE")
        res = labels_mod.import_csv(ev, spec, Path(args.csv), args.by)
    else:  # add
        if not (args.item and args.label and args.by):
            sys.exit("label add needs --item, --label pass|fail and --by NAME")
        res = labels_mod.add(ev, spec, args.item, args.label, args.by, args.note)
    print(f"added {res['added']} label(s)")
    for line in res["skipped"] + res["refused"]:
        print(f"  {line}")
    print(labels_mod.render_status(labels_mod.status(ev, spec)))
    return 1 if res["refused"] else 0


def cmd_migrate(args) -> int:
    from pathlib import Path

    from . import migrate as migrate_mod

    if args.to != "2":
        sys.exit("aot-evals migrate --to 2: turns a 1.x suite into a 2.0 agent folder with one eval, "
                 "end-to-end (docs/v2-design.md §8); --dry-run says what it would do")
    here = Path(args.evals).expanduser() if args.evals else Path.cwd()
    if not args.evals:
        here = next((d / "evals" for d in (here.resolve(), *here.resolve().parents) if (d / "evals").is_dir()),
                    here)
    evals_dir = migrate_mod.evals_dir_for(here)
    agent = args.agent
    if agent is None and here.resolve() != evals_dir and migrate_mod._is_v1(here.resolve()):
        agent = here.resolve().name  # --evals named one suite
    migrate_mod.run(evals_dir, agent=agent, dry_run=args.dry_run)
    return 0


def cmd_components(args) -> int:
    from . import components as comp

    ev = _evals(args)
    items = comp.checklist(ev)
    if args.json:
        print(json.dumps(items, indent=2))
        return 0
    print(comp.render(items))
    return 0


def cmd_build(args) -> int:
    from . import build as build_mod

    ev = _evals(args)
    if build_mod.is_v2(ev):
        try:
            done = build_mod.prepare_v2(ev)
        except ContractError as e:
            sys.exit(str(e))
        print(build_mod.render_v2(done, ev))
        if args.run:
            return build_mod.run_v2(ev, main)
        print("\nNext: fill what each eval's spec lacks (aot-evals validate), then aot-evals build --run")
        return 0
    sys.exit(f"{ev.root} holds a 1.x suite; `aot-evals migrate --to 2` converts it")


def cmd_serve(args) -> int:
    from . import serve as serve_mod

    ev = _evals(args)
    serve_mod.serve(ev, host=args.host, port=args.port, open_browser=args.open)
    return 0


def cmd_agreement(args) -> int:
    from pathlib import Path

    from . import agreement as ag

    ev = _target(args)
    what = args.what or ["measure"]
    if what[0] == "label":
        action = what[1] if len(what) > 1 else "status"
        if action == "queue":
            only = None
            if args.changed:
                from . import bench

                cand = [bench.candidate_run(ev)] if bench.candidate_run(ev) else []
                if not cand:
                    sys.exit("--changed needs a candidate run after the baseline, compared with it "
                             "(aot-evals run --purpose candidate ...; aot-evals compare)")
                only = set(bench.changed_cases(ev))
                if not only:
                    sys.exit("no case's verdict moved in the latest comparison: nothing to label "
                             "(or run aot-evals compare first)")
                runs = args.run or cand
                print(f"{len(only)} case(s) whose verdict moved: {', '.join(sorted(only)[:10])}")
            else:
                runs = args.run or _default_runs(ev)
            if not runs:
                sys.exit("no runs to sample from; run a baseline first (aot-evals run --purpose baseline)")
            path, items = ag.make_queue(ev, runs, per_case=args.per_case, n=args.n, seed=args.seed,
                                        only_cases=only)
            page = ag.write_page(ev)
            print(f"wrote {len(items)} runs to {path} (git-ignored)")
            print(f"label them on the page {page} (git-ignored); then: aot-evals agreement label import --csv FILE")
            if args.open:
                _open(page)
            return 0
        if action == "page":
            page = ag.write_page(ev)
            print(f"wrote {page} (git-ignored)")
            if args.open:
                _open(page)
            return 0
        if action in ("import", "add"):
            if action == "import":
                if not args.csv:
                    sys.exit("agreement label import needs --csv FILE")
                res = ag.import_csv(ev, Path(args.csv), args.by, (args.run or [None])[0])
            else:
                if not (args.item and args.label and args.by):
                    sys.exit("agreement label add needs --item, --label pass|fail and --by NAME")
                res = ag.add(ev, args.item, args.label, args.by, args.note)
            print(f"added {res['added']} label(s); {res['skipped_unlabelled']} row(s) had no label")
            for line in res["problems"]:
                print(f"  {line}")
            return 1 if res["problems"] else 0
        if action == "status":
            labels = ag.load_labels(ev)
            n_fail = sum(not r["label"] for r in labels)
            print(f"{len(labels)} whole runs with a verdict: {n_fail} fail, {len(labels) - n_fail} pass")
            for pair in ag.labeller_agreement(ev):
                def f2(v):
                    return "n/a" if v is None else f"{v:.2f}"
                print(f"  {' & '.join(pair['labellers'])}: {pair['agree']}/{pair['n']} agreed, κ {f2(pair['kappa'])}, "
                      f"AC1 {f2(pair.get('ac1'))}; on fails {f2(pair.get('fail_agreement'))}, "
                      f"on passes {f2(pair.get('pass_agreement'))}")
            dis = ag.disputes(ev)
            if dis:
                print(f"{len(dis)} run(s) where labellers disagree, waiting for a ruling "
                      "(aot-evals agreement rule --item ID --label pass|fail --by NAME --note WHY):")
                for d in dis[:10]:
                    who = ", ".join(f"{x['labeller']} {'pass' if x['label'] else 'fail'}" for x in d["labels"])
                    print(f"  {d['item_id']}: {who}")
            return 0
        sys.exit(f"unknown: agreement label {action} (queue, page, import, add, status)")
    if what[0] == "rule":
        from .labels import parse_label

        lab = parse_label(args.label or "")
        if not (args.item and lab is not None and args.by):
            sys.exit("agreement rule needs --item RUN/CASE.tN.aM, --label pass|fail and --by NAME")
        rec = ag.add_ruling(ev, args.item, lab, args.by, args.note or "")
        print(f"ruled {rec['item_id']} {'pass' if rec['label'] else 'fail'} ({rec['by']})")
        return 0
    if what[0] == "regrade":
        if not args.run:
            sys.exit("agreement regrade needs --run RUN_ID")
        for rid in args.run:
            if args.reproduces:
                r = ag.reproduces(ev, rid)
                print(f"{rid}: {r['compared']} code-check verdicts compared; "
                      + ("all reproduce" if not r["differ"] else f"differ: {r['differ']}"))
                continue
            rows = ag.regrade(ev, rid, call_judges=args.call_judges)
            out = ev.p("data", "agreement", f"regrade-{rid}.jsonl")
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text("".join(json.dumps(r) + "\n" for r in rows))
            counts = {v: sum(r["verdict"] == v for r in rows) for v in ("pass", "fail", None)}
            print(f"{rid}: {len(rows)} attempts re-graded: {counts['pass']} pass, {counts['fail']} fail, "
                  f"{counts[None]} no verdict; wrote {out} (git-ignored)")
        return 0
    if what[0] != "measure":
        sys.exit(f"unknown: agreement {what[0]} (measure, label, regrade)")
    result = ag.measure(ev, call_judges=args.call_judges)
    print(ag.render(result))
    print(f"  wrote {ag.result_path(ev)}")
    return 1 if result["problems"] else 0


def cmd_replay(args) -> int:
    from . import replay

    return replay.main(args.action, args.records)


def cmd_calibrate(args) -> int:
    from . import calibrate as cal_mod

    ev = _target(args)
    spec = _spec(ev, args.judge)
    backends = args.backend or list(spec.backends)
    pending = cal_mod.pending_calls(ev, spec, backends)
    for w in cal_mod.cap_warnings(spec, pending):
        print(w, file=sys.stderr)
    if args.dry_run:
        print(f"would call: {pending} (cached judgements are reused)")
        return 0
    rec = cal_mod.calibrate(ev, spec, backends, call=not args.cached_only,
                            log=_progress(ev, "C10"))
    print(cal_mod.render(rec))
    return 0


def cmd_reliability(args) -> int:
    from . import reliability as rel_mod

    ev = _target(args)
    spec = _spec(ev, args.judge)
    backends = args.backend or list(spec.backends)
    rec = rel_mod.measure(ev, spec, backends, m=args.m, n=args.n, log=_progress(ev, "C11"))
    print(rel_mod.render(rec))
    return 0


def cmd_judge(args) -> int:
    from .judging import apply_to_run

    ev = _target(args)
    spec = _spec(ev, args.judge)
    runs = args.run or _default_runs(ev)
    for rid in runs:
        res = apply_to_run(ev, spec.id, rid, backend=args.backend, log=_progress(ev, "C10"))
        print(f"{rid}: judged {res['judged']} attempt(s), {res['already_judged']} already judged")
    return 0


def cmd_ops(args) -> int:
    ev = _target(args)
    if args.export:
        mapping = dict(kv.split("=", 1) for kv in args.field or [])
        result = ops_mod.from_export(ev, args.export, mapping, args.ok_value or ["ok"])
    else:
        runs = args.run or _default_runs(ev)
        if not runs:
            sys.exit("no runs yet; pass --export ID with --field mappings to sweep an export")
        result = ops_mod.from_runs(ev, runs)
    print(json.dumps(result, indent=2) if args.json else ops_mod.render(result))
    return 0


def cmd_snapshot(args) -> int:
    from pathlib import Path

    from .isolation import tree_snapshot

    print(json.dumps({"files": tree_snapshot(Path.cwd(), args.exclude)}, indent=1))
    return 0


def cmd_compare(args) -> int:
    return _compare_v2(args, _evals(args))


def _compare_v2(args, ev: Evals) -> int:
    """`compare` on a 2.0 eval: the paired comparison and the decision on the candidate
    (docs/v2-design.md §5, §6), saved under report/comparisons/."""
    from . import compare as compare_mod
    from . import decision as decision_mod
    from .report_v2 import Side, default_runs

    e = _one_eval(args, ev)
    base = args.baseline or default_runs(e)
    cands = args.candidate or [m["run_id"] for m in e.runs("candidate") if m.get("finished")][-1:]
    if not base or not cands:
        sys.exit("needs a baseline and a candidate run (aot-evals run --purpose candidate ...)")
    b, c = Side(e, base), Side(e, cands)
    comp = decision_mod.comparison(e, b, c)
    comp["decision"] = decision_mod.decide(e, b, c, comp)
    print(decision_mod.render_comparison(comp), flush=True)  # the result first: saving must never lose it
    print(decision_mod.render_decision(comp["decision"]), flush=True)
    print(f"  wrote {compare_mod.save(e, comp)}")
    decision_mod.record_look(e, comp["decision"])
    return 1 if comp.get("refused") else 0


def cmd_coverage(args) -> int:
    from . import coverage as coverage_mod

    e = _target(args)
    cov = coverage_mod.coverage(e)
    print(json.dumps(cov, indent=2) if args.json else coverage_mod.render(cov))
    return 0 if not cov["problems"] else 1


def cmd_report(args) -> int:
    ev = _evals(args)
    from . import decision as decision_mod
    from . import report_v2

    e = _one_eval(args, ev)
    r = report_v2.build(e, args.run or None, args.candidate or None)
    print(f"wrote {report_v2.write(e, r)}")
    decision_mod.record_look(e, r["decision"])
    est = r["estimate"]
    if est["theta"] is not None:
        lo, hi = est["ci"]
        print(f"  θ̂ = {est['theta']:.4f} [{lo:.4f}, {hi:.4f}] ({est['quantity']}, {est['weights_source']} "
              f"weights, {est['n_cases']} cases in {est['n_clusters']} clusters, k = {est['k']})")
    else:
        print(f"  θ̂ unknown: {est['null_reason']}")
    if r.get("refused"):
        print(f"  refused: {r['refused']}")
    if r.get("comparison"):
        print(decision_mod.render_comparison(r["comparison"]))
    print(decision_mod.render_decision(r["decision"]))
    return 0


def _progress(ev: Evals, gate: str | None):
    """Progress lines go to stderr and stream into the activity log."""
    def log(line: str) -> None:
        print(line, file=sys.stderr)
        try:
            journal.append(ev, "progress", line.strip(), gate=gate)
        except OSError:
            pass
    return log


def cmd_log(args) -> int:
    ev = _evals(args)
    extra = {}
    if args.kind == "decision" and (args.eval or len(ev.evals()) == 1):
        # a decision about a 2.0 eval carries its spec's hashes, so a decision-rule change journaled
        # before the candidate ran lets the comparison stand (docs/v2-design.md §5)
        from .spec import part_hashes

        e = _one_eval(args, ev)
        extra = {"eval": e.id, "spec_sha": part_hashes(e.spec(), e)}
    journal.append(ev, args.kind, args.text, gate=args.gate, detail=args.detail, by=args.by, **extra)
    return 0


def _open(path) -> None:
    import webbrowser

    webbrowser.open(path.resolve().as_uri())


def cmd_activity(args) -> int:
    ev = _evals(args)
    path = journal.render(ev)
    print(f"activity log: {path}")
    print("  it reloads itself; keep it open in a browser tab")
    if args.open:
        _open(path)
    return 0


def cmd_start(args) -> int:
    from .start import start_text

    print(start_text())
    return 0


def cmd_doctor(args) -> int:
    from . import doctor

    rows = doctor.checks(args.evals, args.agent)
    print(doctor.render(rows))
    return 1 if any(st == "FAIL" for st, _, _ in rows) else 0


def cmd_demo(args) -> int:
    from pathlib import Path

    from . import demo

    telemetry.emit("demo_run")
    telemetry.suppress()  # the demo runs commands of its own; they aren't the user's milestones
    try:
        return demo.run(Path(args.dir).expanduser().resolve(), main)
    except (FileExistsError, RuntimeError) as e:
        sys.exit(f"demo: {e}")


def cmd_discovery_page(args) -> int:
    from pathlib import Path

    from .start import write_discovery_page

    src = Path(args.file).expanduser().resolve()
    if not src.exists():
        sys.exit(f"no such report: {src}")
    out = write_discovery_page(src, args.agent, Path(args.out).expanduser() if args.out else src.parent)
    print(f"discovery page: {out}")
    if args.open:
        _open(out)
    return 0


def cmd_telemetry(args) -> int:
    if args.action == "show":
        print(telemetry.show_text())
        return 0
    if args.action == "off":
        telemetry.turn_off()
    elif args.action == "on":
        telemetry.turn_on()
    print(telemetry.status_text())
    return 0


def cmd_benchmarks(args) -> int:
    from . import benchmarks

    entries = benchmarks.load()
    if args.validate:
        problems = benchmarks.validate(entries)
        print("\n".join(problems) if problems else f"{len(entries)} entries, all valid")
        return 1 if problems else 0
    if not args.workload and not args.task:
        print(f"{len(entries)} benchmarks in {benchmarks.CATALOG}. Pass --workload TAG and --task \"...\" to match.")
        print("workloads: " + ", ".join(sorted(benchmarks.WORKLOADS)))
        print("situations (the grid's columns, references/situations.yaml): "
              + ", ".join(f"{s['id']}{'*' if s.get('universal') else ''}" for s in benchmarks.situations())
              + "   (* applies to nearly every agent)")
        return 0
    bad = [w for w in args.workload if w not in benchmarks.WORKLOADS]
    if bad:
        sys.exit(f"unknown workload(s) {bad}; see `aot-evals benchmarks` for the vocabulary")
    matches = benchmarks.match(entries, args.workload, args.task, limit=args.limit,
                               include_saturated=args.include_saturated)
    if args.json:
        print(json.dumps({"situations": benchmarks.situations_for(matches), "matches": matches},
                         ensure_ascii=False, indent=2))
    else:
        print(benchmarks.render(matches))
    return 0


# Milestones sent as telemetry when a command succeeds (SECURITY.md#telemetry).
_MILESTONES = {"start": "phase1_started", "discovery-page": "discovery_written",
               "report": "report_built"}

# Commands that never log themselves: reads, and the commands that write the log.
_UNLOGGED = {"replay", "status", "components", "migrate", "validate", "log", "activity", "start",
             "discovery-page", "snapshot",
             "doctor", "demo", "telemetry", "benchmarks", "serve"}
# Commands long enough to log their start, so the activity page shows them in progress.
_LOG_START = {"run", "calibrate", "reliability", "judge"}


def _journal_command(args, argv: list[str], phase: str, code=None, note: str | None = None,
                     started: float | None = None) -> None:
    """Log one CLI command to the activity log. Logging never fails the command."""
    if args.cmd in _UNLOGGED:
        return
    try:
        ev = Evals.find(args.evals, args.agent)
        if not ev.exists():
            return
        shown, skip = [], False
        for a in argv:  # the --evals path is noise in the log
            if skip or a.startswith("--evals="):
                skip = False
                continue
            if a == "--evals":
                skip = True
                continue
            shown.append(a)
        text = "aot-evals " + " ".join(shown)
        gate = journal.command_gate(args.cmd, getattr(args, "purpose", None))
        if phase == "start":
            journal.append(ev, "step", f"started {text}", gate=gate)
            return
        dur = round((time.monotonic() - started) * 1000) if started is not None else None
        journal.append(ev, "command", text, gate=gate, exit=code, duration_ms=dur, detail=note)
    except Exception:  # noqa: BLE001 - the log is a convenience; the command's result stands
        pass


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="aot-evals", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", action="version", version=f"aot-evals {__version__}")
    ap.add_argument("--evals", help="one agent's suite (evals/agents/AGENT/), or the evals/ folder "
                    "with --agent (default: found from evals/ upward)")
    ap.add_argument("--agent", help="the agent's suite, evals/agents/AGENT/ (needed when the "
                    "repository holds several)")
    ap.add_argument("--eval", help="2.0: one eval of the agent, evals/agents/AGENT/EVAL/ (needed when "
                    "the agent has several)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("start", help="the banner and the two phases; shown before anything else"
                   ).set_defaults(fn=cmd_start)

    sub.add_parser("doctor", help="check the environment; paste the output into a bug report"
                   ).set_defaults(fn=cmd_doctor)

    s = sub.add_parser("demo", help="set up a toy agent with a finished suite, to try aot-evals")
    s.add_argument("dir", nargs="?", default="aot-evals-demo", help="where (default ./aot-evals-demo)")
    s.set_defaults(fn=cmd_demo)

    s = sub.add_parser("discovery-page", help="render a discovery report (markdown) as a branded page")
    s.add_argument("file", help="the discovery report, markdown")
    s.add_argument("--agent", required=True, help="the agent the report is about")
    s.add_argument("--out", help="folder for discovery.html (default: next to the report)")
    s.add_argument("--open", action="store_true", help="open it in the default browser")
    s.set_defaults(fn=cmd_discovery_page)

    s = sub.add_parser("init", help="create the agent's suite (evals/agents/AGENT/) with templates; "
                       "with --eval, one 2.0 eval folder with its eval.yaml")
    s.add_argument("--eval", default=argparse.SUPPRESS,
                   help="2.0: create this eval, evals/agents/AGENT/EVAL/ (same as the global --eval)")
    s.add_argument("--component", help="2.0: the eval's unit is this component, behind a context "
                   "boundary (default eval id: the component's name)")
    s.set_defaults(fn=cmd_init)

    s = sub.add_parser("status", help="the phase, trust per category, what changed, and the next step")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_status)

    s = sub.add_parser("validate", help="every problem across all gates; for 2.0 evals, the eval spec")
    s.add_argument("--warnings", action="store_true", help="also print warnings and info (2.0: notes "
                   "and the defaults filled)")
    s.add_argument("--all", action="store_true", help="one line per problem, instead of grouping cases")
    s.set_defaults(fn=cmd_validate)

    s = sub.add_parser("import", help="C0: import an export with its provenance")
    s.add_argument("file")
    s.add_argument("--source", required=True, help="system and dataset, e.g. 'Datadog LLM Obs: prod-traces'")
    s.add_argument("--query", required=True, help="the query or filter that produced the export")
    s.add_argument("--window", required=True, help="time window covered, e.g. 2026-07-01..2026-09-30")
    s.add_argument("--id", help="export id (default: <date>-<file stem>)")
    s.add_argument("--notes")
    s.add_argument("--handoffs-of", metavar="COMPONENT",
                   help="the export holds handoffs into this component, captured as they happened: a "
                        "component eval's frame (rule 4). Handoffs recorded in end-to-end traces are "
                        "extracted with `handoffs` instead")
    s.set_defaults(fn=cmd_import)

    s = sub.add_parser("handoffs", help="extract a component eval's frame: the handoffs into its component, "
                                        "from the end-to-end traces (rule 4)")
    s.add_argument("--from", dest="source", metavar="IMPORT_ID",
                   help="the end-to-end frame to read (default: the end-to-end eval's population frame)")
    s.add_argument("--id", help="import id for the new frame (default: the eval's estimand.population.frame)")
    s.add_argument("--scan", action="store_true",
                   help="count the handoffs into each component in the frame, beside agent.yaml's "
                        "components: where the traces show context boundaries")
    s.add_argument("--dry-run", action="store_true")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_handoffs)

    s = sub.add_parser("plan", help="2.0: case targets per use case and pool, from the decision rule")
    s.add_argument("--assumed-rate", type=float, help="the value of the estimand's quantity you expect "
                   "(a pass rate, or a failure rate for failure_rate:...); default: the baseline's")
    s.add_argument("--flip-rate", type=float, help="the share of cases that flip between versions, for "
                   "a superiority or non-inferiority test (from an A/A rerun or the last comparison)")
    s.add_argument("--total", type=int, help="the quality set's size, in place of the headline need")
    s.add_argument("--write", action="store_true", help="write <eval>/plan.yaml")
    s.add_argument("--mark-short", choices=["scheduled", "out_of_scope"],
                   help="mark every row that is still short (needs --reason)")
    s.add_argument("--reason")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_plan)

    s = sub.add_parser("draw", help="2.0: draw the quality set from the frame, seeded and stratified, with π")
    s.add_argument("--n", action="append", metavar="USE_CASE=N",
                   help="draw N from this use case, in place of plan.yaml's target (repeatable)")
    s.add_argument("--skip", action="append", metavar="TRACE_ID",
                   help="take this trace out of the frame (needs --reason); the next of the seeded "
                   "order replaces it")
    s.add_argument("--reason", help="why the skipped trace leaves the frame (PII, a duplicate, ...)")
    s.add_argument("--prune", action="store_true",
                   help="remove quality cases the draw no longer holds")
    s.add_argument("--dry-run", action="store_true", help="say what would change, write nothing")
    s.set_defaults(fn=cmd_draw)

    s = sub.add_parser("screen", help="C7: screen cases")
    s.add_argument("--judges", action="store_true",
                   help="let calibrated judges count in the non-answer and liar screens (calls cost money)")
    s.add_argument("--case", action="append", help="limit to this case id (repeatable)")
    s.add_argument("--read-by", help="record that NAME read the selected cases (a human read)")
    s.add_argument("--all", action="store_true", help="with --read-by: NAME read every case")
    s.add_argument("--drop", help="drop this case id (needs --reason)")
    s.add_argument("--reason")
    s.set_defaults(fn=cmd_screen)

    s = sub.add_parser("run", help="run the agent over the cases, k trials each")
    s.add_argument("--purpose", choices=["smoke", "baseline", "candidate", "drift"])
    s.add_argument("--k", type=int, help="trials per case (default 1)")
    s.add_argument("--resume", metavar="RUN_ID",
                   help="carry on a stopped or interrupted run in place: skip every (case, trial) "
                   "with a final attempt and run the rest; refused if the build changed")
    s.add_argument("--case", action="append")
    s.add_argument("--use-case", action="append", help="2.0: limit to this use case (repeatable)")
    s.add_argument("--question", help="smoke only: run one ad-hoc trigger before any case exists")
    s.add_argument("--variable", help="the declared independent variable, e.g. 'model=claude-haiku-4-5'")
    s.add_argument("--label", help="suffix for the run id")
    s.add_argument("--model", help="pin the agent's model for this run: overrides agent.yaml "
                   "invoke.model, reaches the agent as stdin `model` and the {model} placeholder, "
                   "and is recorded in the manifest; a candidate with no --variable declares "
                   "model=MODEL")
    s.add_argument("--no-judges", action="store_true", help="run code checks only (judges cost money)")
    s.add_argument("--pause-every", type=int, default=0, metavar="N",
                   help="pause after every N cases, for a rate-limited agent runtime (default: never)")
    s.add_argument("--pause-seconds", type=float, default=900, help="length of each pause (default 900)")
    s.add_argument("--stop-after", type=int, default=5, metavar="N",
                   help="stop after N cases in a row end in an operational failure such as a "
                   "timeout (default 5; 0 never stops)")
    s.set_defaults(fn=cmd_run)

    s = sub.add_parser("label", help="C9: human labels per judge")
    s.add_argument("action", choices=["queue", "page", "import", "add", "status"])
    s.add_argument("--csv", help="import: the filled-in queue CSV")
    s.add_argument("--judge")
    s.add_argument("--run", action="append", help="queue: sample from these runs (default: latest baseline)")
    s.add_argument("--n", type=int, default=100, help="queue: items to sample (default 100)")
    s.add_argument("--seed", type=int, default=0)
    s.add_argument("--by", help="labeller name (import: for rows with no labeller)")
    s.add_argument("--item", help="add: item id from the queue")
    s.add_argument("--label", help="add: pass or fail")
    s.add_argument("--note")
    s.add_argument("--open", action="store_true", help="queue, page: open the labelling page")
    s.set_defaults(fn=cmd_label)

    s = sub.add_parser("agreement", help="C19: the suite's verdict on whole runs against a person's")
    s.add_argument("what", nargs="*", help="(nothing): measure; label queue|page|import|add|status; rule; regrade")
    s.add_argument("--run", action="append",
                   help="label queue, regrade: these runs (default: latest baseline); label import: attach "
                   "rows that give only case_id and trial to this run")
    s.add_argument("--per-case", type=int, default=1, help="label queue: runs per case (default 1)")
    s.add_argument("--n", type=int, help="label queue: at most this many runs")
    s.add_argument("--seed", type=int, default=0)
    s.add_argument("--csv", help="label import: the downloaded CSV")
    s.add_argument("--by", help="labeller name")
    s.add_argument("--item", help="label add: run item id (RUN/CASE.tN.aM)")
    s.add_argument("--label", help="label add: pass or fail")
    s.add_argument("--note")
    s.add_argument("--call-judges", action="store_true",
                   help="call judges with no recorded verdict for this judge version (costs money)")
    s.add_argument("--reproduces", action="store_true",
                   help="regrade: check that code checks give the run's recorded verdicts on its raw records")
    s.add_argument("--open", action="store_true", help="label queue, page: open the page")
    s.add_argument("--changed", action="store_true",
                   help="label queue: only cases whose verdict moved between the baseline and the latest "
                   "compared candidate, from the candidate run")
    s.set_defaults(fn=cmd_agreement)

    s = sub.add_parser("build", help="the lightest Build: draft what's missing, the checklist, then --run the baseline")
    s.add_argument("--run", action="store_true", help="then run the agent once, the baseline and the report")
    s.add_argument("--k", type=int, default=3, help="--run: trials per case for the baseline (3-5)")
    s.set_defaults(fn=cmd_build)

    s = sub.add_parser("migrate", help="--to 2: a 1.x suite to a 2.0 agent folder with one eval, end-to-end")
    s.add_argument("--to", help="the version to migrate to: 2")
    s.add_argument("--dry-run", action="store_true", help="say what would move and map, and write nothing")
    s.set_defaults(fn=cmd_migrate)

    s = sub.add_parser("components", help="the optimization loop's components as a checklist, read from the suite")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_components)

    s = sub.add_parser("serve", help="the grader application: label runs, rulings, triage, rules, judges")
    s.add_argument("--host", default="127.0.0.1",
                   help="address to listen on (default 127.0.0.1; 0.0.0.0 lets others on the network in)")
    s.add_argument("--port", type=int, default=8765, help="port (default 8765; 0 picks a free one)")
    s.add_argument("--open", action="store_true", help="open it in the default browser")
    s.set_defaults(fn=cmd_serve)

    s = sub.add_parser("replay", help="act as the agent and its hooks by replaying recorded runs (offline grading)")
    s.add_argument("action", choices=["run", "seed", "observe"])
    s.add_argument("records", help="directory of <case-id>.t<trial>.json records")
    s.set_defaults(fn=cmd_replay)

    s = sub.add_parser("calibrate", help="C10: measure a judge's backends on its labels")
    s.add_argument("--judge", required=True)
    s.add_argument("--backend", action="append", help="limit to these backends (default: all)")
    s.add_argument("--dry-run", action="store_true", help="print how many judge calls it would make")
    s.add_argument("--cached-only", action="store_true", help="use cached judgements; make no calls")
    s.set_defaults(fn=cmd_calibrate)

    s = sub.add_parser("reliability", help="C11: self-consistency and cross-family agreement")
    s.add_argument("--judge", required=True)
    s.add_argument("--backend", action="append", help="two or more, from different families")
    s.add_argument("--m", type=int, default=3, help="sessions per item per backend (default 3)")
    s.add_argument("--n", type=int, help="limit to the first N labelled items")
    s.set_defaults(fn=cmd_reliability)

    s = sub.add_parser("judge", help="apply a judge to past runs")
    s.add_argument("action", choices=["apply"])
    s.add_argument("--judge", required=True)
    s.add_argument("--run", action="append", help="default: the baseline (every category's newest baseline run)")
    s.add_argument("--backend", help="default: the judge's primary backend")
    s.set_defaults(fn=cmd_judge)

    s = sub.add_parser("ops", help="E14: plane-B sweep against budgets")
    s.add_argument("--run", action="append")
    s.add_argument("--export", help="sweep an imported export instead of runs")
    s.add_argument("--field", action="append",
                   help="FIELD=dotted.path in each export row; FIELD is one of "
                        + ", ".join(ops_mod.EXPORT_FIELDS))
    s.add_argument("--ok-value", action="append", help="export outcome value(s) meaning ok")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_ops)

    s = sub.add_parser("snapshot", help="print a hash per file of the working tree, for an observe hook")
    s.add_argument("--exclude", action="append", help="glob of run outputs to leave out (repeatable)")
    s.set_defaults(fn=cmd_snapshot)

    s = sub.add_parser("compare", help="C13: paired comparison of a candidate against the baseline")
    s.add_argument("--baseline", action="append", help="baseline run id(s); default: the latest baseline")
    s.add_argument("--candidate", action="append", help="candidate run id(s); default: the latest candidate")
    s.set_defaults(fn=cmd_compare)

    s = sub.add_parser("coverage", help="C14: coverage against the external taxonomy")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_coverage)

    s = sub.add_parser("log", help="add an entry to the activity log (journal/activity.jsonl)")
    s.add_argument("text")
    s.add_argument("--kind", choices=[k for k in journal.KINDS if k not in ("command", "milestone")],
                   default="step", help="step (default): about to do; finding; decision; question "
                   "(you have stopped for the person); progress")
    s.add_argument("--gate", help="the gate this is about, e.g. C3")
    s.add_argument("--detail", help="a second line: evidence, source, numbers")
    s.add_argument("--by", help="decision: who decided (the owner's name, or claude)")
    s.set_defaults(fn=cmd_log)

    s = sub.add_parser("activity", help="render the live activity page (journal/activity.html)")
    s.add_argument("--open", action="store_true", help="open it in the default browser")
    s.set_defaults(fn=cmd_activity)

    s = sub.add_parser("telemetry", help="pseudonymous usage telemetry: status, show, off or on")
    s.add_argument("action", nargs="?", default="status", choices=["status", "show", "off", "on"],
                   help="status (the default), show the exact event, or turn it off or back on")
    s.set_defaults(fn=cmd_telemetry)

    s = sub.add_parser("benchmarks", help="match an agent to the local catalog of public benchmarks (no web)")
    s.add_argument("--workload", action="append", default=[], metavar="TAG",
                   help="the agent's workload tag(s); run with no options to list them")
    s.add_argument("--task", action="append", default=[], metavar="TEXT",
                   help="one of the agent's task types, in plain words (repeatable)")
    s.add_argument("--limit", type=int, default=8, help="how many fits to show (default 8)")
    s.add_argument("--include-saturated", action="store_true", help="also show benchmarks models have saturated")
    s.add_argument("--json", action="store_true", help="print the matches as JSON")
    s.add_argument("--validate", action="store_true", help="check the catalog against its schema")
    s.set_defaults(fn=cmd_benchmarks)

    s = sub.add_parser("report", help="C18: write report/report.json")
    s.add_argument("--run", action="append", help="run id(s); default: the latest baseline")
    s.add_argument("--candidate", action="append", help="include a comparison with these candidate run(s)")
    s.set_defaults(fn=cmd_report)

    args = ap.parse_args(argv)
    argv = list(sys.argv[1:] if argv is None else argv)
    if args.cmd in _LOG_START:
        _journal_command(args, argv, "start")
    started = time.monotonic()
    code, note = 2, None
    try:
        code = args.fn(args)
        if code == 0 and args.cmd in _MILESTONES:
            telemetry.emit(_MILESTONES[args.cmd], getattr(args, "gate", None))
        return code
    except (ContractError, ValueError, KeyError, FileNotFoundError) as e:
        note = f"error: {e}"
        print(note, file=sys.stderr)
        return 2
    except SystemExit as e:  # refusals exit with their message; the log keeps the message
        code = e.code if isinstance(e.code, int) else 1
        note = e.code if isinstance(e.code, str) else None
        raise
    finally:
        _journal_command(args, argv, "end", code=code, note=note, started=started)


if __name__ == "__main__":
    sys.exit(main())
