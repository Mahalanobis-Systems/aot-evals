"""The activity log (docs/method.md §9): what Claude and the CLI did, in order, for the person to watch.

`evals/journal/activity.jsonl` is append-only. Every CLI command logs itself (cli.main); the
skills add the steps, findings, decisions and questions between commands with `aot-evals log`.
Every append re-renders `evals/journal/activity.html`, a branded page that reloads itself, so
the person can keep it open in a browser tab and watch the work instead of the terminal.

The directory carries its own `.gitignore` (`*`): the log is a working record for the people in
the session and may quote unreviewed trace text, so it never enters git (docs/method.md §1, principle 5). The
committed record of each decision is the file the decision changed.
"""

from __future__ import annotations

import time
from pathlib import Path

from .brand import _esc, human_date, page
from .repo import Evals
from .util import append_jsonl, now_iso, read_jsonl

KINDS = ("step", "finding", "decision", "question", "command", "progress", "milestone")
# Claude has stopped and the next move is the person's.
WAITING_KINDS = ("question", "milestone")
KIND_LABEL = {"step": "doing", "finding": "found", "decision": "decided", "question": "asked you",
              "command": "ran", "progress": "progress", "milestone": "checkpoint"}
# Which gate a CLI command works on, for commands that are about one gate.
COMMAND_GATE = {"import": "C0", "allocate": "C5", "screen": "C7", "label": "C9", "calibrate": "C10",
                "reliability": "C11", "judge": "C10", "compare": "C13", "coverage": "C14",
                "redundancy": "C15", "report": "C18", "init": "C0"}
RUN_GATE = {"smoke": "C1", "baseline": "C12", "candidate": "C13", "drift": "C16"}
RELOAD_MS = 4000
_PROGRESS_EVERY_S = 2.0
_last_render = 0.0


def directory(ev: Evals) -> Path:
    return ev.p("journal")


def log_path(ev: Evals) -> Path:
    return ev.p("journal", "activity.jsonl")


def html_path(ev: Evals) -> Path:
    return ev.p("journal", "activity.html")


def _ensure_dir(ev: Evals) -> None:
    d = directory(ev)
    d.mkdir(parents=True, exist_ok=True)
    ignore = d / ".gitignore"
    if not ignore.exists():
        ignore.write_text("# aot-evals activity log: a working record, never committed (docs/method.md §9)\n*\n")


def entries(ev: Evals) -> list[dict]:
    return read_jsonl(log_path(ev))


def append(ev: Evals, kind: str, text: str, gate: str | None = None, **extra) -> dict:
    """Append one entry and re-render the page. Progress entries re-render at most every two
    seconds, so a long run streams into the page without rewriting it once per attempt."""
    global _last_render
    if kind not in KINDS:
        raise ValueError(f"unknown log kind {kind!r}; one of {', '.join(KINDS)}")
    _ensure_dir(ev)
    entry = {"ts": now_iso(), "kind": kind, "gate": gate, "text": text}
    entry.update({k: v for k, v in extra.items() if v is not None})
    append_jsonl(log_path(ev), entry)
    now = time.monotonic()
    if kind != "progress" or now - _last_render >= _PROGRESS_EVERY_S:
        render(ev)
        _last_render = now
    return entry


def render(ev: Evals) -> Path:
    _ensure_dir(ev)
    path = html_path(ev)
    path.write_text(activity_page(ev, entries(ev)))
    return path


# ---- the page ------------------------------------------------------------------------------

def _clock(ts: str | None) -> str:
    """'2026-10-05T14:03:09Z' -> '14:03:09 UTC'; the page's script rewrites it to local time."""
    return f"{(ts or '')[11:19]} UTC" if ts and len(ts) >= 19 else (ts or "")


def _collapse_progress(items: list[dict]) -> list[dict]:
    """Consecutive progress lines become one row: the latest line and how many came before."""
    out: list[dict] = []
    for e in items:
        if e.get("kind") == "progress" and out and out[-1].get("kind") == "progress":
            out[-1] = {**e, "_count": out[-1].get("_count", 1) + 1}
        else:
            out.append(dict(e))
    return out


def roadmap_html(snapshot: list[dict] | None, focus: str | None = None) -> str:
    """The C0-C18 strip: one cell per gate, grouped by stage, the focus gate outlined."""
    from .checkpoint import STAGES

    if not snapshot:
        return ""
    status = {g["id"]: g["status"] for g in snapshot}
    groups = []
    for stage in STAGES:
        cells = []
        for gid in stage["gates"]:
            st = status.get(gid, "unmet")
            cls = {"met": "met", "unmet": "unmet", "not_applicable": "na",
                   "not_implemented": "later"}.get(st, "unmet")
            mark = " focus" if gid == focus else ""
            cells.append(f'<span class="gate {cls}{mark}" title="{gid} {_esc(st)}">{gid}</span>')
        groups.append(f'<div class="stage"><span class="stage-name">{_esc(stage["name"])}</span>'
                      f'<span class="gates">{"".join(cells)}</span></div>')
    return ('<div class="roadmap" aria-label="Gates C0 to C18">' + "".join(groups) +
            '</div><p class="caption legend"><span class="gate met">C0</span> met '
            '<span class="gate unmet">C0</span> open <span class="gate na">C0</span> does not apply '
            '<span class="gate later">C0</span> not yet automated</p>')


def activity_page(ev: Evals, items: list[dict]) -> str:
    agent = ev.agent_name
    last = items[-1] if items else None
    milestones = [e for e in items if e.get("kind") == "milestone"]
    snapshot = milestones[-1].get("gates") if milestones else None
    focus = milestones[-1].get("gate") if milestones else None

    parts = []
    if last and last.get("kind") in WAITING_KINDS:
        what = "published a checkpoint for you to review" if last["kind"] == "milestone" \
            else "asked you a question"
        link = ""
        if last.get("path"):
            link = f' <a href="{_esc(_rel_from_journal(last["path"]))}">Open the checkpoint</a>.'
        parts.append(f'<div class="banner waiting"><strong>Claude has stopped and is waiting for '
                     f'you.</strong> It {what}: {_esc(last.get("text", ""))}.{link} Reply in '
                     f'Claude Code to continue.</div>')
    elif last:
        parts.append(f'<div class="banner working"><strong>Latest</strong>: '
                     f'{_esc(last.get("text", ""))} <span class="ago" data-ts="{_esc(last["ts"])}">'
                     f'</span></div>')
    else:
        parts.append('<div class="banner">Nothing logged yet. The log fills in as Claude works.</div>')

    if snapshot:
        parts.append('<h2>Where the evals stand</h2>')
        parts.append(roadmap_html(snapshot, focus))
        parts.append('<p class="caption">As of the latest checkpoint. Each gate is one step of '
                     'the method (C0 import … C18 report); the checkpoint pages explain each.</p>')

    if milestones:
        rows = []
        for m in reversed(milestones):
            href = _esc(_rel_from_journal(m.get("path") or ""))
            rows.append(f'<tr><td>{_esc(human_date(m["ts"]))} '
                        f'<span class="t" data-ts="{_esc(m["ts"])}">{_esc(_clock(m["ts"]))}</span></td>'
                        f'<td>{_esc(m.get("gate") or "")}</td>'
                        f'<td><a href="{href}">{_esc(m.get("text", ""))}</a></td></tr>')
        parts.append('<h2>Checkpoints</h2><table><thead><tr><th>When</th><th>Gate</th>'
                     '<th>Checkpoint</th></tr></thead><tbody>' + "".join(rows) + '</tbody></table>')

    rows = []
    for e in reversed(_collapse_progress(items)):
        kind = e.get("kind", "")
        text = _esc(e.get("text", ""))
        if kind == "command":
            text = f'<code>{text}</code>'
            if e.get("exit") not in (None, 0):
                text += f' <span class="status-fail">exit {_esc(e["exit"])}</span>'
            if e.get("duration_ms") is not None:
                text += f' <span class="muted">{_esc(_secs(e["duration_ms"]))}</span>'
        if e.get("_count"):
            text += f' <span class="muted">({e["_count"]} progress lines)</span>'
        if e.get("detail"):
            text += f'<div class="detail">{_esc(e["detail"])}</div>'
        if kind == "decision" and e.get("by"):
            text += f' <span class="muted">by {_esc(e["by"])}</span>'
        if e.get("path") and kind == "milestone":
            text = f'<a href="{_esc(_rel_from_journal(e["path"]))}">{text}</a>'
        rows.append(f'<tr class="k-{_esc(kind)}"><td class="num"><span class="t" data-ts="{_esc(e["ts"])}">'
                    f'{_esc(_clock(e["ts"]))}</span></td><td>{_esc(e.get("gate") or "")}</td>'
                    f'<td class="kind">{_esc(KIND_LABEL.get(kind, kind))}</td><td>{text}</td></tr>')
    parts.append('<h2>Activity, newest first</h2>')
    if rows:
        parts.append('<table class="full log"><colgroup><col style="width:7em"><col style="width:4em">'
                     '<col style="width:7em"><col></colgroup><thead><tr><th class="num">Time</th>'
                     '<th>Gate</th><th>What</th><th></th></tr></thead><tbody>' + "".join(rows) +
                     '</tbody></table>')
    else:
        parts.append('<p class="muted">No activity yet.</p>')

    sub = (f"{_esc(agent)} &middot; reloads every {RELOAD_MS // 1000} seconds &middot; "
           f'<a href="#" id="pause">pause</a>')
    return page(f"Activity for {agent}", "AOT evals activity", sub, "\n".join(parts),
                script=_SCRIPT, footer_note=f"\n  Source: {_esc(str(log_path(ev)))}.")


def _rel_from_journal(path_in_evals: str) -> str:
    return f"../{path_in_evals}" if path_in_evals else "#"


def _secs(ms) -> str:
    try:
        s = float(ms) / 1000
    except (TypeError, ValueError):
        return ""
    return f"{s:.1f} s" if s < 90 else f"{s / 60:.1f} min"


# Reload while open, keeping the scroll position; show times in the reader's local time zone.
_SCRIPT = """
(function () {
  var KEY = "aot-evals-activity";
  var state = {};
  try { state = JSON.parse(sessionStorage.getItem(KEY) || "{}"); } catch (e) {}
  if (state.y) window.scrollTo(0, state.y);
  var paused = !!state.paused;
  var btn = document.getElementById("pause");
  function save() {
    try { sessionStorage.setItem(KEY, JSON.stringify({y: window.scrollY, paused: paused})); } catch (e) {}
  }
  function label() { if (btn) btn.textContent = paused ? "resume" : "pause"; }
  label();
  if (btn) btn.addEventListener("click", function (ev) { ev.preventDefault(); paused = !paused; save(); label(); });
  setInterval(function () { if (!paused) { save(); location.reload(); } }, RELOAD_MS);
  document.querySelectorAll(".t[data-ts]").forEach(function (el) {
    var d = new Date(el.getAttribute("data-ts"));
    if (!isNaN(d)) el.textContent = d.toLocaleTimeString();
  });
  document.querySelectorAll(".ago[data-ts]").forEach(function (el) {
    var s = Math.round((Date.now() - new Date(el.getAttribute("data-ts"))) / 1000);
    if (!isNaN(s)) el.textContent = "(" + (s < 90 ? s + " s" : Math.round(s / 60) + " min") + " ago)";
  });
})();
""".replace("RELOAD_MS", str(RELOAD_MS))


def command_gate(cmd: str, purpose: str | None = None) -> str | None:
    if cmd == "run":
        return RUN_GATE.get(purpose or "")
    return COMMAND_GATE.get(cmd)


def since_last_milestone(items: list[dict]) -> list[dict]:
    idx = max((i for i, e in enumerate(items) if e.get("kind") == "milestone"), default=-1)
    return items[idx + 1:]

