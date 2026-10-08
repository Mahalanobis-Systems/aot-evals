"""Checkpoint pages (docs/method.md §9): a branded page at every point where the work needs the owner.

`aot-evals checkpoint` writes `evals/report/checkpoints/<nnn>-<gate>-<date>.html`. It is
deterministic: it renders what is on disk, so it costs no model calls and reads the same for
everyone. Each page shows:
- where the evals stand: the C0-C18 roadmap, in plain words;
- what happened since the last checkpoint: Claude's summary and the activity log;
- what the work has produced so far: every design file, rendered as tables;
- what Claude needs from the owner: the questions, and what still blocks the gate;
- what comes next.

The skills publish one and stop, so the owner reviews a page rather than a scroll of terminal
output, and steers between steps.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from . import gates as gates_mod
from . import journal, markdown
from .brand import _esc, human_date, page
from .repo import Evals
from .screen import passes as screen_passes
from .util import now_iso

STAGES = [
    {"name": "Scope", "skill": "scope", "gates": ["C0", "C1", "C2", "C3", "C4"],
     "about": "What the agent does, how people use it, and how it can fail."},
    {"name": "Build", "skill": "build", "gates": ["C5", "C6", "C7", "C8"],
     "about": "How many test cases are needed, the cases themselves, and the pass/fail checks."},
    {"name": "Judges", "skill": "calibrate", "gates": ["C9", "C10", "C11"],
     "about": "Whether the checks that need a model to grade them can be trusted."},
    {"name": "Run", "skill": "run", "gates": ["C12", "C13", "C14", "C15", "C16", "C17"],
     "about": "Running the suite, comparing versions, and finding out whether the suite is any good."},
    {"name": "Report", "skill": "report", "gates": ["C18"],
     "about": "A diagnostic report shaped around the question you are asking."},
]

# Per gate: a plain title, what the step does and why, and what it needs from the owner.
GUIDE = {
    "C0": ("Import real traffic",
           "Copy an export of the agent's real runs into evals/data/ (never committed) and record "
           "where it came from, so every later number can be traced to its source.",
           "An export file, the system it came from, the query or filter used, and the time window."),
    "C1": ("Describe the agent and run it once",
           "Write down what the agent is, which model each call actually uses, how long it has "
           "been unchanged, and how to run it. Then run it end to end once.",
           "How long the agent has been stable in production, and how it is invoked."),
    "C2": ("List what the agent should handle",
           "Take the list of jobs from a document written for another purpose (a product spec, "
           "the tool surface, help-centre topics). Coverage is measured against it, so it must not "
           "come from the test cases.",
           "Which document defines the agent's job, and edits to the drafted list."),
    "C3": ("Sort real traffic into categories",
           "Group the imported runs by what the agent was asked to do, measure each category's "
           "share of traffic, and record what a failure costs in each.",
           "Confirm, merge or rename categories; set each one's worth and failure costs."),
    "C4": ("List how each category can fail",
           "Break each category into the specific ways it can go wrong. Decide how each is "
           "checked: by code, by a model judge, or only watched in production. Set cost and "
           "latency budgets.",
           "Sign-off on the failure modes, how each is checked, and the budgets."),
    "C5": ("Decide how many cases",
           "Work out how many cases each category needs in two sets (one to find errors, one to "
           "estimate quality) and show the smallest change the suite could detect.",
           "How precise the quality estimate must be; what to do where traffic is too thin."),
    "C6": ("Write the test cases",
           "Turn reviewed real runs into frozen, scrubbed cases, each with the end state a correct "
           "agent would leave behind.",
           "Confirmation that each expected end state is right."),
    "C7": ("Sanity-check each case",
           "Every case is screened: the right answer passes, doing nothing fails, and a person has "
           "read it. Cases that fail are dropped with a reason.",
           "A person to read each case."),
    "C8": ("Write the pass/fail checks",
           "Code that inspects the end state comes first; a model judge is used only where code "
           "cannot decide. Nothing trusts the agent's own claim that it succeeded.",
           "Review of the checks."),
    "C9": ("Label examples for each judge",
           "A person marks a sample of what each judge sees as pass or fail, so the judge can be "
           "measured against people.",
           "100 to 200 labels per judge, from a person."),
    "C10": ("Measure each judge",
            "Compare each judge with the labels: how often it catches failures and how often it "
            "passes good work, separately. Pick the cheapest judge that is good enough.",
            "Approval of the judge chosen, and of the cost of measuring it."),
    "C11": ("Check judges agree",
            "Check that each judge gives the same answer twice, and agrees with a judge from a "
            "different model family. Agreement is reported beside accuracy, never instead of it.",
            "Approval of the cost."),
    "C12": ("Run the baseline",
            "Run the whole suite 3 to 5 times on the current agent: per-category results, how much "
            "they vary from run to run, and cost and latency against budget.",
            "Approval of the run's cost; a committed, unchanged agent."),
    "C13": ("Compare a change",
            "After a change to the agent, run it again and list exactly which cases got better and "
            "which got worse, with a paired test. Never just a net number.",
            "The one thing that was changed."),
    "C14": ("Find coverage gaps",
            "Count cases against the list from C2 and show the empty cells, most valuable first.",
            "For each gap: write a case, or say why it does not apply."),
    "C15": ("Find cases that never discriminate",
            "Across agent versions, find the cases that never tell versions apart and propose "
            "pruning them without losing sensitivity.",
            "Accept or reject each proposed prune."),
    "C16": ("Watch for drift", "Re-run the frozen suite on a schedule (guidance only for now).", ""),
    "C17": ("Evaluate online", "Judge a sample of live traffic (guidance only for now).", ""),
    "C18": ("Write the report",
            "A full diagnostic report, shaped around your question: how the agent is doing, whether "
            "the suite is any good, why a change regressed, or what it costs.",
            "The question the report should answer."),
}
STATUS_WORD = {"met": "met", "unmet": "open", "not_applicable": "does not apply",
               "not_implemented": "not yet automated"}


def checkpoint_dir(ev: Evals) -> Path:
    return ev.p("report", "checkpoints")


def next_path(ev: Evals, gate: str) -> Path:
    d = checkpoint_dir(ev)
    n = 1 + max((int(m.group(1)) for p in d.glob("*.html")
                 if (m := re.match(r"(\d+)-", p.name))), default=0) if d.exists() else 1
    return d / f"{n:03d}-{gate}-{now_iso()[:10]}.html"


def write(ev: Evals, gate: str | None = None, title: str | None = None, summary: str = "",
          asks: list[str] | None = None) -> Path:
    gs = gates_mod.evaluate(ev)
    nxt = gates_mod.next_unmet(gs)
    focus = gate or (nxt.id if nxt else "C18")
    if focus not in gates_mod.COMMAND_BY_ID:
        raise ValueError(f"unknown gate {focus!r}; one of C0..C18")
    items = journal.entries(ev)
    path = next_path(ev, focus)
    path.parent.mkdir(parents=True, exist_ok=True)
    title = title or f"{GUIDE[focus][0]} ({focus})"
    path.write_text(render(ev, gs, focus, title, summary, asks or [],
                           journal.since_last_milestone(items)))
    rel = str(path.relative_to(ev.root))
    journal.append(ev, "milestone", title, gate=focus, path=rel,
                   gates=[{"id": g.id, "status": g.status} for g in gs])
    return path


# ---- rendering -----------------------------------------------------------------------------

def _table(headers: list[str], rows: list[list], num: set[int] | None = None, cls: str = "") -> str:
    num = num or set()
    th = "".join(f'<th{" class=num" if i in num else ""}>{_esc(h)}</th>' for i, h in enumerate(headers))
    body = []
    for r in rows:
        tds = "".join(f'<td{" class=num" if i in num else ""}>{c if isinstance(c, _Raw) else _esc(_fmt(c))}</td>'
                      for i, c in enumerate(r))
        body.append(f"<tr>{tds}</tr>")
    return (f'<div class="wrap"><table class="{cls}"><thead><tr>{th}</tr></thead>'
            f'<tbody>{"".join(body)}</tbody></table></div>')


class _Raw(str):
    """Already-escaped HTML for a table cell."""


def _pct(v) -> str:
    return f"{v:.1%}" if isinstance(v, (int, float)) and not isinstance(v, bool) else "—"


def _fmt(v) -> str:
    if v is None:
        return "—"
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, float):
        return f"{v:g}"
    if isinstance(v, (list, tuple)):
        return ", ".join(_fmt(x) for x in v)
    if isinstance(v, dict):
        return ", ".join(f"{k}: {_fmt(x)}" for k, x in v.items())
    return str(v)


def _panel(pid: str, heading: str, body: str, caption: str = "") -> str:
    cap = f'<p class="caption">{caption}</p>' if caption else ""
    return f'<section id="{pid}"><h2>{_esc(heading)}</h2>{cap}{body}</section>'


def _roadmap_table(gs: list[gates_mod.Gate], focus: str) -> str:
    rows = []
    for stage in STAGES:
        for gid in stage["gates"]:
            g = next(x for x in gs if x.id == gid)
            name, does, _ = GUIDE[gid]
            cls = ' class="focus-row"' if gid == focus else ""
            first = f'<td rowspan="{len(stage["gates"])}" class="stage-cell"><strong>{_esc(stage["name"])}</strong>' \
                    f'<div class="muted">{_esc(stage["about"])}</div></td>' if gid == stage["gates"][0] else ""
            rows.append(f'<tr{cls}>{first}<td>{gid}</td><td><strong>{_esc(name)}</strong>'
                        f'<div class="muted">{_esc(does)}</div></td>'
                        f'<td class="st-{g.status}">{_esc(STATUS_WORD[g.status])}</td></tr>')
    return ('<details><summary>The whole method, gate by gate</summary>'
            '<div class="wrap"><table class="full roadmap-table">'
            '<thead><tr><th>Stage</th><th>Gate</th><th>What it does</th><th>Status</th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table></div></details>')


def _activity(items: list[dict]) -> str:
    items = journal._collapse_progress(items)
    if not items:
        return '<p class="muted">Nothing logged since the last checkpoint.</p>'
    rows = []
    for e in items:
        text = _esc(e.get("text", ""))
        if e.get("kind") == "command":
            text = f"<code>{text}</code>" + (f' <span class="status-fail">exit {_esc(e["exit"])}</span>'
                                             if e.get("exit") not in (None, 0) else "")
        if e.get("detail"):
            text += f'<div class="detail">{_esc(e["detail"])}</div>'
        if e.get("kind") == "decision" and e.get("by"):
            text += f' <span class="muted">by {_esc(e["by"])}</span>'
        rows.append(f'<tr class="k-{_esc(e.get("kind", ""))}"><td class="num">{_esc(journal._clock(e.get("ts")))}</td>'
                    f'<td>{_esc(e.get("gate") or "")}</td>'
                    f'<td class="kind">{_esc(journal.KIND_LABEL.get(e.get("kind"), e.get("kind")))}</td>'
                    f'<td>{text}</td></tr>')
    return ('<details><summary>Everything logged since the last checkpoint '
            f'({len(items)} entries)</summary><table class="full log"><tbody>{"".join(rows)}'
            '</tbody></table></details>')


def _artifacts(ev: Evals) -> list[str]:
    """Every design file that exists so far, as small tables, in method order."""
    out = []
    exports = ev.exports()
    if exports:
        out.append(_panel("exports", "C0 · Imported traffic", _table(
            ["Export", "Source", "Query", "Window", "Rows", "Imported"],
            [[e.get("id"), e.get("source"), e.get("query"), e.get("window"), e.get("rows"),
              human_date(e.get("date"))] for e in exports], num={4}),
            "Stored in evals/data/, which git ignores. Only this manifest is committed."))

    a = ev.agent()
    if a.get("id"):
        sw = a.get("stable_window") or {}
        inv = (a.get("invoke") or {}).get("command")
        rows = [["Agent", a.get("id")], ["What it does", a.get("description")],
                ["Where it runs", a.get("surface")], ["Triggers", a.get("triggers")],
                ["Model per call site", a.get("models")], ["How the models were observed", a.get("models_evidence")],
                ["Model family", a.get("model_family")], ["Stable since", sw.get("since")],
                ["Evidence for that", sw.get("evidence")], ["Invoked with", inv],
                ["Behaviour changes on record", len(a.get("version_history") or [])]]
        out.append(_panel("agent", "C1 · The agent", _table(["", ""], rows, cls="kv")))

    t = ev.taxonomy()
    if t.get("entries"):
        src = t.get("source") or {}
        src_txt = src.get("document") if isinstance(src, dict) else src
        out.append(_panel("taxonomy", f"C2 · What the agent should handle ({len(t['entries'])} entries)",
                          _table(["Entry", "Title"], [[e.get("id"), e.get("title")] for e in t["entries"]]),
                          f"From <em>{_esc(src_txt or 'no source named')}</em>, read "
                          f"{_esc(human_date(str(t['read_on'])) if t.get('read_on') else 'on an unrecorded date')}."))

    cats = ev.categories()
    if cats:
        out.append(_panel("categories", f"C3 · Categories of real traffic ({len(cats)})", _table(
            ["Category", "Definition", "Worth", "Simple", "Share", "Cost of each failure kind"],
            [[c.get("id"), c.get("definition"), c.get("worth"), c.get("simple"),
              _pct(c.get("observed_share")), c.get("cost")] for c in cats], num={4}, cls="full"),
            "Share is measured from the imported traffic. Worth and costs are the owner's call."))

    fms = ev.failure_modes()
    if fms:
        out.append(_panel("failure-modes", f"C4 · How it can fail ({len(fms)} failure modes)", _table(
            ["Failure mode", "Description", "Categories", "Checked by", "Checks", "Cost cell"],
            [[f.get("id"), f.get("description"), f.get("categories"), f.get("check_type"),
              f.get("checks"), f.get("cost_cell")] for f in fms], cls="full"),
            "Checked by: code inspects the end state; judge is a model check that must be "
            "calibrated before it counts; monitor is watched in production only."))
        b = ev.budgets()
        brows = []
        if b.get("default"):
            brows.append(["(default)", b["default"]])
        for cid, v in (b.get("categories") or {}).items():
            brows.append([cid, v])
        if brows:
            out.append(_panel("budgets", "C4 · Cost and latency budgets", _table(["Category", "Budget"], brows)))

    alloc = ev.allocation()
    if alloc.get("cells"):
        ef, qe = alloc.get("error_finding") or {}, alloc.get("quality_estimate") or {}
        cap = (f"Error-finding set: {_esc(_fmt(ef.get('n')))} cases ({_esc(ef.get('rule') or '')}). "
               f"Quality-estimate set: {_esc(_fmt(qe.get('n')))} cases ({_esc(qe.get('rule') or '')}). "
               f"Smallest detectable change, upper bound: error-finding "
               f"{_pct(ef.get('mde_unpaired_upper_bound'))}, quality-estimate "
               f"{_pct(qe.get('mde_unpaired_upper_bound'))}.")
        out.append(_panel("allocation", "C5 · How many cases", _table(
            ["Category", "Set", "Target", "Have", "Screened", "Status", "Reason"],
            [[c.get("category"), c.get("set"), c.get("target"), c.get("have"), c.get("screened"),
              c.get("status"), c.get("reason")] for c in alloc["cells"]], num={2, 3, 4}), cap))

    try:
        cases = ev.cases()
    except Exception:  # a malformed case is C6's problem; the checkpoint still renders
        cases = []
    if cases:
        by = Counter((c.get("category"), c.get("set")) for c in cases)
        screened = Counter((c.get("category"), c.get("set")) for c in cases if screen_passes(c.get("screen")))
        dropped = Counter((c.get("category"), c.get("set")) for c in cases if (c.get("screen") or {}).get("dropped"))
        out.append(_panel("cases", f"C6–C7 · Test cases ({len(cases)})", _table(
            ["Category", "Set", "Cases", "Passed the screen", "Dropped"],
            [[k[0], k[1], n, screened[k], dropped[k]] for k, n in sorted(by.items(), key=lambda x: str(x[0]))],
            num={2, 3, 4})))

    code = sorted(p.stem for p in ev.p("checks", "code").glob("*.py")) if ev.p("checks", "code").exists() else []
    judge = sorted(p.stem for p in ev.p("checks", "judge").glob("*.md")) if ev.p("checks", "judge").exists() else []
    if code or judge:
        rows = [[c, "code", ""] for c in code]
        for j in judge:
            rows.append([j, "judge", f"{len(ev.judge_labels(j))} labels"])
        out.append(_panel("checks", f"C8 · Checks ({len(code)} code, {len(judge)} judge)",
                          _table(["Check", "Kind", "Labels"], rows)))

    runs = ev.runs()
    if runs:
        out.append(_panel("runs", f"C12 · Runs ({len(runs)})", _table(
            ["Run", "Purpose", "k", "Finished", "Cost (USD)", "Variable"],
            [[r.get("run_id"), r.get("purpose"), r.get("k"), bool(r.get("finished")),
              r.get("cost_usd"), r.get("variable")] for r in runs[-10:]], num={2, 4}),
            "The latest ten. Results by category are in the full report (report, C18)."))
    return out


def render(ev: Evals, gs: list[gates_mod.Gate], focus: str, title: str, summary: str,
           asks: list[str], recent: list[dict]) -> str:
    g = next(x for x in gs if x.id == focus)
    nxt = gates_mod.next_unmet(gs)
    name, does, needs = GUIDE[focus]
    agent = ev.agent_name
    parts = [_panel("where", "Where the evals stand",
                    journal.roadmap_html([{"id": x.id, "status": x.status} for x in gs], focus)
                    + f'<p class="prose">This checkpoint is about <strong>{focus} · {_esc(name)}</strong> '
                    f'({_esc(STATUS_WORD[g.status])}). {_esc(does)}</p>' + _roadmap_table(gs, focus))]

    body = markdown.render(summary) if summary.strip() else '<p class="muted">No summary was written.</p>'
    parts.append(_panel("summary", "What happened", body + _activity(recent)))

    need = []
    if asks:
        need.append("<ol class=\"asks\">" + "".join(f"<li>{markdown.inline(a)}</li>" for a in asks) + "</ol>")
        need.append('<p class="caption">Answer in Claude Code, in any order; a short answer is '
                    'fine. Claude will not continue until you reply.</p>')
    else:
        need.append('<p>Nothing specific. Reply in Claude Code to continue, or steer the next step.</p>')
    if g.problems:
        need.append(f"<h3>Still open on {focus}</h3><ul>" +
                    "".join(f"<li>{_esc(p)}</li>" for p in g.problems[:20]) + "</ul>")
        if len(g.problems) > 20:
            need.append(f'<p class="caption">and {len(g.problems) - 20} more: run '
                        '<code>aot-evals validate</code>.</p>')
    if needs:
        need.append(f'<p class="caption">What this step usually needs from you: {_esc(needs)}</p>')
    parts.append(_panel("needs", "What Claude needs from you", "".join(need)))

    arts = _artifacts(ev)
    parts.append(_panel("produced", "What the work has produced so far",
                        "".join(arts) if arts else '<p class="muted">Nothing yet: evals/ holds only '
                        'its templates.</p>'))

    if nxt:
        n_name, n_does, n_needs = GUIDE[nxt.id]
        stage = next(s for s in STAGES if nxt.id in s["gates"])
        after = (f'<p class="prose"><strong>{nxt.id} · {_esc(n_name)}</strong> '
                 f'(skill <code>{_esc(stage["skill"])}</code>). {_esc(n_does)}</p>')
        if n_needs:
            after += f'<p class="caption">It will need: {_esc(n_needs)}</p>'
    else:
        after = '<p>Every implemented gate is met. Ask for a report (C18) or compare a change (C13).</p>'
    parts.append(_panel("next", "What comes next", after))

    sub = (f"{_esc(agent)} &middot; {_esc(human_date(now_iso()))} &middot; "
           f'<a href="../../journal/activity.html">activity log</a>')
    return page(title, f"AOT evals checkpoint · {focus}", sub, "\n".join(parts))
