"""`aot-evals`: the deterministic half of the plugin. The skills do the judgement half.

    aot-evals demo [DIR]                a toy agent with a finished suite, to try it in minutes
    aot-evals doctor                    check the environment (paste into bug reports)
    aot-evals init                      create the agent's suite, evals/agents/<agent>/, with templates
    aot-evals status [--json]           every command gate (C0-C18); the next unmet one
    aot-evals validate                  every problem and warning, across all gates
    aot-evals import FILE ...           C0: copy an export into evals/data/, record provenance
    aot-evals allocate [--write]        C5: size both case sets, print the arithmetic
    aot-evals screen [--read-by NAME]   C7: reference / do-nothing / claim screens per case
    aot-evals run --purpose P --k N     C1 smoke, C12 baseline, candidate runs
    aot-evals label queue|page|import|add|status   C9: human labels per judge (page: label in a browser)
    aot-evals calibrate --judge ID      C10 / E3 / E5: TPR/TNR per backend on the labels
    aot-evals reliability --judge ID    C11 / E4: self-consistency and cross-family agreement
    aot-evals judge apply --judge ID --run ID   judge a past run
    aot-evals compare --candidate ID    C13 / E2: paired comparison against the baseline
    aot-evals coverage                  C14 / E8: taxonomy entry x failure mode, empty cells first
    aot-evals redundancy                C15 / E9: discriminating fraction and a prune proposal
    aot-evals ops [--run ID|--export]   E14: plane-B sweep against budgets
    aot-evals snapshot [--exclude GLOB] a hash per file of the working tree, for an observe hook
    aot-evals report [--run ID ...]     C18: write report/report.json
    aot-evals log TEXT [--kind K]       add to the activity log (every command logs itself)
    aot-evals activity [--open]         render the live activity page, journal/activity.html
    aot-evals checkpoint [--gate CX]    write a branded checkpoint page for the owner to review
    aot-evals telemetry [status|show|off|on]   pseudonymous usage telemetry (SECURITY.md#telemetry)
"""

from __future__ import annotations

import argparse
import json
import sys
import time

from . import __version__, journal, telemetry
from . import allocate as allocate_mod
from . import gates as gates_mod
from . import ops as ops_mod
from . import report as report_mod
from . import runner as runner_mod
from . import screen as screen_mod
from .importer import import_export
from .repo import Evals
from .scaffold import init
from .util import ContractError

GLYPH = {"met": "met", "unmet": "UNMET", "not_applicable": "n/a", "not_implemented": "later"}


def _evals(args) -> Evals:
    try:
        ev = Evals.find(args.evals, args.agent)
    except ContractError as e:
        sys.exit(str(e))
    if args.cmd not in ("init",) and not ev.exists():
        sys.exit(f"no suite at {ev.root}; run `aot-evals --agent NAME init` in the repository "
                 "root, or pass --evals PATH")
    return ev


def _refuse_unless(ev: Evals, upto: str, force: bool) -> list[str]:
    blocked = gates_mod.require(ev, upto)
    if not blocked:
        return []
    names = ", ".join(f"{g.id} {g.command}" for g in blocked)
    if force:
        print(f"warning: running past unmet gate(s) {names}; recorded in the run manifest",
              file=sys.stderr)
        return [g.id for g in blocked]
    first = blocked[0]
    lines = [f"refused: {upto} {gates_mod.COMMAND_BY_ID[upto][1]} needs {first.id} "
             f"{first.command} to be met (skill: {first.skill}):"]
    lines += [f"  - {p}" for p in first.problems[:10]]
    if len(blocked) > 1:
        lines.append(f"  also unmet: {', '.join(g.id for g in blocked[1:])}")
    sys.exit("\n".join(lines))


def cmd_init(args) -> int:
    ev = _evals(args)
    created = init(ev)
    print(f"suite at {ev.root}")
    for c in created:
        print(f"  created {c}")
    if not created:
        print("  nothing to create; every file already exists")
    print("next: C0 import an export, then C1 fill agent.yaml (skill: scope)")
    return 0


def cmd_status(args) -> int:
    ev = _evals(args)
    gs = gates_mod.evaluate(ev)
    nxt = gates_mod.next_unmet(gs)
    if args.json:
        print(json.dumps({"evals": str(ev.root), "gates": [g.as_dict() for g in gs],
                          "next": nxt.as_dict() if nxt else None}, indent=2))
        return 0
    print(f"suite at {ev.root}")
    for g in gs:
        note = (g.problems[0] if g.problems else (g.info[0] if g.info else ""))
        more = f" (+{len(g.problems) - 1} more)" if len(g.problems) > 1 else ""
        print(f"  {g.id:<4} {g.command:<12} {g.skill:<12} {GLYPH[g.status]:<6} {note}{more}")
    if nxt:
        print(f"\nnext: {nxt.id} {nxt.command} (skill: {nxt.skill})")
        for p in nxt.problems[:15]:
            print(f"  - {p}")
    else:
        print("\nevery implemented gate is met")
    return 0


def cmd_validate(args) -> int:
    ev = _evals(args)
    n_problems = 0
    for g in gates_mod.evaluate(ev):
        if not g.problems and not (args.warnings and g.info):
            continue
        print(f"{g.id} {g.command} [{GLYPH[g.status]}]")
        for p in g.problems:
            print(f"  error: {p}")
        n_problems += len(g.problems)
        for i in g.info:
            if args.warnings:
                print(f"  info:  {i}")
    print(f"\n{n_problems} problem(s)")
    return 1 if n_problems else 0


def cmd_import(args) -> int:
    from pathlib import Path

    ev = _evals(args)
    entry = import_export(ev, Path(args.file), source=args.source, query=args.query,
                          window=args.window, export_id=args.id, notes=args.notes)
    print(json.dumps(entry, indent=2))
    if entry["rows"] is None:
        print("warning: could not count rows; C0 needs a row count. Use .jsonl, .csv, .tsv or "
              "a JSON array.", file=sys.stderr)
    return 0


def cmd_allocate(args) -> int:
    ev = _evals(args)
    _refuse_unless(ev, "C5", args.force)
    p = allocate_mod.plan(ev, halfwidth=args.halfwidth, assumed_rate=args.assumed_rate, k=args.k)
    if args.mark_short:
        if not args.reason:
            sys.exit("--mark-short needs --reason")
        for cell in p["cells"]:
            if cell["status"] == "short":
                cell["status"], cell["reason"] = args.mark_short, args.reason
    print(allocate_mod.render(p))
    if args.write:
        allocate_mod.write(ev, p)
        print(f"\nwrote {ev.p('allocation.yaml')}")
    return 0


def cmd_screen(args) -> int:
    ev = _evals(args)
    _refuse_unless(ev, "C7", args.force)
    if args.read_by and not (args.case or args.all):
        sys.exit("--read-by records a human read: name the cases read with --case (repeatable), "
                 "or pass --all if NAME really read every case")
    rows = screen_mod.run_screen(ev, case_ids=args.case or None, read_by=args.read_by,
                                 drop=args.drop, reason=args.reason)
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
    ev = _evals(args)
    upto = "C1" if args.purpose == "smoke" else "C12"
    forced = _refuse_unless(ev, upto, args.force)
    if args.purpose == "candidate" and not args.variable and not args.force:
        sys.exit("refused: a candidate run declares its one independent variable, e.g. --variable "
                 "model=claude-haiku-4-5 or --variable prompt=v7 (C13, G7). Kinds: "
                 + ", ".join(sorted(compare_variables())))
    if args.purpose == "baseline" and args.k < 3 and not args.force:
        sys.exit("refused: a baseline needs k >= 3 to measure variance (C12, M5); pass --k 3..5")
    m = runner_mod.run(ev, purpose=args.purpose, k=args.k, case_ids=args.case or None,
                       categories=args.category or None, variable=args.variable,
                       label=args.label, adhoc_question=args.question,
                       log=_progress(ev, journal.command_gate("run", args.purpose)), forced=forced,
                       judges=not args.no_judges, pause_every=args.pause_every,
                       pause_seconds=args.pause_seconds, stop_after=args.stop_after)
    print(f"run {m['run_id']}: {m['counts']}  cost ${m['cost_usd'] or 0:.4f}")
    print(f"  {ev.p('runs', m['run_id'])}")
    if m.get("stopped"):
        print(f"  STOPPED, not finished: {m['stopped']['reason']}")
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
    return gates_mod._judge_checks(ev)


def cmd_label(args) -> int:
    from pathlib import Path

    from . import label_page
    from . import labels as labels_mod

    ev = _evals(args)
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
        runs = args.run or report_mod.default_runs(ev)
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


def cmd_calibrate(args) -> int:
    from . import calibrate as cal_mod

    ev = _evals(args)
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

    ev = _evals(args)
    spec = _spec(ev, args.judge)
    backends = args.backend or list(spec.backends)
    rec = rel_mod.measure(ev, spec, backends, m=args.m, n=args.n, log=_progress(ev, "C11"))
    print(rel_mod.render(rec))
    return 0


def cmd_judge(args) -> int:
    from .judging import apply_to_run

    ev = _evals(args)
    spec = _spec(ev, args.judge)
    runs = args.run or report_mod.default_runs(ev)
    for rid in runs:
        res = apply_to_run(ev, spec.id, rid, backend=args.backend, log=_progress(ev, "C10"))
        print(f"{rid}: judged {res['judged']} attempt(s), {res['already_judged']} already judged")
    return 0


def cmd_ops(args) -> int:
    ev = _evals(args)
    if args.export:
        mapping = dict(kv.split("=", 1) for kv in args.field or [])
        result = ops_mod.from_export(ev, args.export, mapping, args.ok_value or ["ok"])
    else:
        runs = args.run or report_mod.default_runs(ev)
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
    from . import compare as compare_mod

    ev = _evals(args)
    base = args.baseline or report_mod.default_runs(ev)
    cands = args.candidate or [m["run_id"] for m in ev.runs("candidate") if m.get("finished")][-1:]
    if not base or not cands:
        sys.exit("needs a baseline and a candidate run (aot-evals run --purpose candidate ...)")
    c = compare_mod.compare(ev, base, cands)
    print(compare_mod.render(c), flush=True)  # the result first: saving must never lose it
    path = compare_mod.save(ev, c)
    print(f"  wrote {path}")
    return 1 if c.get("refused") else 0


def cmd_coverage(args) -> int:
    from . import suite

    ev = _evals(args)
    g5_ok = not gates_mod.taxonomy_problems(ev)
    cov = report_mod.coverage(ev, g5_ok)
    cov["authoring_queue"] = suite.authoring_queue(ev, cov["cells"])
    print(json.dumps(cov, indent=2) if args.json else suite.render_coverage(cov))
    return 0 if g5_ok else 1


def cmd_redundancy(args) -> int:
    from . import suite

    ev = _evals(args)
    r = suite.redundancy(ev, args.run or None, args.threshold)
    print(json.dumps(r, indent=2) if args.json else suite.render_redundancy(r))
    return 0


def cmd_report(args) -> int:
    ev = _evals(args)
    r = report_mod.build(ev, args.run or None, args.candidate or None)
    path = report_mod.write(ev, r)
    print(f"wrote {path}")
    if args.html:
        from .brand import write_shell

        html = write_shell(ev, r, title=args.title)
        print(f"wrote {html} (branded shell; write the panels into <main id=\"panels\">)")
    for g in r["gates"]:
        if g["status"] == "fail":
            print(f"  {g['id']} fail: {g['detail']}")
    if r.get("refused"):
        print(f"  refused: {r['refused']}")
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
    journal.append(ev, args.kind, args.text, gate=args.gate, detail=args.detail, by=args.by)
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


def cmd_checkpoint(args) -> int:
    from . import checkpoint as checkpoint_mod

    ev = _evals(args)
    summary = args.summary or ""
    if args.summary_file:
        summary = sys.stdin.read() if args.summary_file == "-" else open(args.summary_file).read()
    path = checkpoint_mod.write(ev, gate=args.gate, title=args.title, summary=summary, asks=args.ask)
    print(f"checkpoint: {path}")
    print(f"activity log: {journal.html_path(ev)}")
    if args.open:
        _open(path)
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


# Milestones sent as telemetry when a command succeeds (SECURITY.md#telemetry).
_MILESTONES = {"start": "phase1_started", "discovery-page": "discovery_written", "checkpoint": "checkpoint",
               "report": "report_built"}

# Commands that never log themselves: reads, and the commands that write the log.
_UNLOGGED = {"status", "validate", "log", "activity", "checkpoint", "start", "discovery-page", "snapshot",
             "doctor", "demo", "telemetry"}
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
    ap.add_argument("--evals", help="path to the agent's suite directory (default: found from "
                    "evals/ upward; see --agent)")
    ap.add_argument("--agent", help="the agent's suite, evals/agents/AGENT/ (needed when the "
                    "repository holds several)")
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

    sub.add_parser("init", help="create the agent's suite (evals/agents/AGENT/) with templates"
                   ).set_defaults(fn=cmd_init)

    s = sub.add_parser("status", help="command gates C0-C18 and the next unmet one")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_status)

    s = sub.add_parser("validate", help="every problem across all gates")
    s.add_argument("--warnings", action="store_true", help="also print warnings and info")
    s.set_defaults(fn=cmd_validate)

    s = sub.add_parser("import", help="C0: import an export with its provenance")
    s.add_argument("file")
    s.add_argument("--source", required=True, help="system and dataset, e.g. 'Datadog LLM Obs: prod-traces'")
    s.add_argument("--query", required=True, help="the query or filter that produced the export")
    s.add_argument("--window", required=True, help="time window covered, e.g. 2026-07-01..2026-09-30")
    s.add_argument("--id", help="export id (default: <date>-<file stem>)")
    s.add_argument("--notes")
    s.set_defaults(fn=cmd_import)

    s = sub.add_parser("allocate", help="C5: size both case sets")
    s.add_argument("--halfwidth", type=float, default=0.05,
                   help="target 95%% CI half-width for the quality estimate (default 0.05)")
    s.add_argument("--assumed-rate", type=float, default=0.5,
                   help="assumed pass rate for sizing (default 0.5, the worst case)")
    s.add_argument("--k", type=int, default=3)
    s.add_argument("--write", action="store_true", help="write evals/allocation.yaml")
    s.add_argument("--mark-short", choices=["scheduled", "out_of_scope"],
                   help="mark every cell that is still short (needs --reason)")
    s.add_argument("--reason")
    s.add_argument("--force", action="store_true")
    s.set_defaults(fn=cmd_allocate)

    s = sub.add_parser("screen", help="C7: screen cases")
    s.add_argument("--case", action="append", help="limit to this case id (repeatable)")
    s.add_argument("--read-by", help="record that NAME read the selected cases (a human read)")
    s.add_argument("--all", action="store_true", help="with --read-by: NAME read every case")
    s.add_argument("--drop", help="drop this case id (needs --reason)")
    s.add_argument("--reason")
    s.add_argument("--force", action="store_true")
    s.set_defaults(fn=cmd_screen)

    s = sub.add_parser("run", help="run the agent over the cases, k trials each")
    s.add_argument("--purpose", choices=["smoke", "baseline", "candidate", "drift"], required=True)
    s.add_argument("--k", type=int, default=1)
    s.add_argument("--case", action="append")
    s.add_argument("--category", action="append")
    s.add_argument("--question", help="smoke only: run one ad-hoc trigger before any case exists")
    s.add_argument("--variable", help="the declared independent variable, e.g. 'model=claude-haiku-4-5'")
    s.add_argument("--label", help="suffix for the run id")
    s.add_argument("--no-judges", action="store_true", help="run code checks only (judges cost money)")
    s.add_argument("--pause-every", type=int, default=0, metavar="N",
                   help="pause after every N cases, for a rate-limited agent runtime (default: never)")
    s.add_argument("--pause-seconds", type=float, default=900, help="length of each pause (default 900)")
    s.add_argument("--stop-after", type=int, default=5, metavar="N",
                   help="stop after N cases in a row end in an operational failure such as a "
                   "timeout (default 5; 0 never stops)")
    s.add_argument("--force", action="store_true", help="run past unmet gates (recorded)")
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
    s.add_argument("--run", action="append", help="default: the latest baseline")
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

    s = sub.add_parser("redundancy", help="C15: discriminating fraction and a prune proposal")
    s.add_argument("--run", action="append", help="limit to these runs (default: every finished run)")
    s.add_argument("--threshold", type=float, help="minimum discriminating fraction (default 0.3, or "
                   "discriminating_threshold in allocation.yaml)")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_redundancy)

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

    s = sub.add_parser("checkpoint", help="write a branded checkpoint page for the owner to review")
    s.add_argument("--gate", help="the gate it is about (default: the next unmet gate)")
    s.add_argument("--title", help="default: the gate's plain-language name")
    s.add_argument("--summary", help="what happened, in a few short paragraphs or '- ' bullets")
    s.add_argument("--summary-file", help="read the summary from FILE, or '-' for stdin")
    s.add_argument("--ask", action="append", help="a question for the owner (repeatable)")
    s.add_argument("--open", action="store_true", help="open it in the default browser")
    s.set_defaults(fn=cmd_checkpoint)

    s = sub.add_parser("telemetry", help="pseudonymous usage telemetry: status, show, off or on")
    s.add_argument("action", nargs="?", default="status", choices=["status", "show", "off", "on"],
                   help="status (the default), show the exact event, or turn it off or back on")
    s.set_defaults(fn=cmd_telemetry)

    s = sub.add_parser("report", help="C18: write report/report.json")
    s.add_argument("--run", action="append", help="run id(s); default: the latest baseline")
    s.add_argument("--candidate", action="append", help="include a comparison with these candidate run(s)")
    s.add_argument("--html", action="store_true", help="also write the branded HTML shell (report-<date>.html)")
    s.add_argument("--title", help="the HTML report's title, shaped by its question")
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
