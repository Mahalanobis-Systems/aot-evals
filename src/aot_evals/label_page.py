"""C9: a local page for labelling a judge's queue, instead of editing a CSV of JSON blobs.

`aot-evals label page --judge ID` reads `<check-id>.queue.csv` and writes one self-contained page
to `data/labelling/<check-id>.html`. data/ is git-ignored in every suite, and the page carries the
same judge inputs as the queue, so it never enters git either.

The page shows one item at a time: the judge's question and its Pass/Fail guidance, then each
input field (question, reference, answer, ...) in its own panel. Keys: p pass, f fail, j / k or
the arrow keys to move, n for a note. Labels are kept in the browser (localStorage) as they are
made, and "Download CSV" writes the queue back with `label`, `labeller` and `note` filled in, for
`aot-evals label import --csv`.
"""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

from .brand import _esc, page
from .judges import JudgeSpec, command_spec
from .labels import QUEUE_FIELDS, queue_path
from .markdown import render as md
from .repo import Evals


def page_path(ev: Evals, spec: JudgeSpec) -> Path:
    return ev.p("data", "labelling", f"{spec.id}.html")


def read_queue(ev: Evals, spec: JudgeSpec) -> list[dict]:
    path = queue_path(ev, spec)
    if not path.exists():
        raise FileNotFoundError(f"no queue at {path}; run `aot-evals label queue --judge {spec.id}` first")
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def write(ev: Evals, spec: JudgeSpec) -> Path:
    rows = read_queue(ev, spec)
    items = []
    for r in rows:
        try:
            inp = json.loads(r.get("input") or "{}")
        except json.JSONDecodeError:
            inp = {"input": r.get("input")}
        items.append({**{k: r.get(k, "") for k in QUEUE_FIELDS if k != "input"}, "input": inp})
    queue_sha = hashlib.sha256(json.dumps([i["item_id"] for i in items]).encode()).hexdigest()[:12]
    s = command_spec(spec)
    data = {"judge": spec.id, "version": spec.version, "queue_sha": queue_sha, "fields": QUEUE_FIELDS,
            "items": items}
    yes = f'<p class="muted">A yes to this question means {_esc(s["yes_means"])}.</p>' if s.get("yes_means") else ""
    body = f"""
<style>
.lp-q {{ border-left: 4px solid var(--forest); padding: 4px 14px; margin: 8px 0 16px; }}
.lp-bar {{ display: flex; flex-wrap: wrap; align-items: center; gap: 10px 16px; margin: 12px 0; }}
.lp-bar input {{ font: inherit; padding: 4px 6px; }}
.lp-progress {{ flex: 1; min-width: 160px; height: 8px; background: var(--rule); }}
.lp-progress span {{ display: block; height: 8px; background: var(--forest); width: 0; }}
.lp-meta {{ color: var(--grey-muted); font-size: 13px; margin: 6px 0 10px; }}
.lp-fields {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 16px; }}
.lp-field h3 {{ font-size: 13px; margin: 0 0 4px; color: var(--forest); }}
.lp-field pre {{ white-space: pre-wrap; word-break: break-word; margin: 0; max-height: 60vh; overflow: auto; }}
.lp-actions {{ display: flex; flex-wrap: wrap; gap: 10px; align-items: center; margin: 16px 0; }}
.lp-actions button {{ font: inherit; padding: 8px 16px; border: 2px solid var(--forest); background: transparent;
  color: var(--forest); cursor: pointer; }}
.lp-actions button.on {{ background: var(--forest); color: #fff; }}
.lp-actions textarea {{ font: inherit; flex: 1; min-width: 240px; min-height: 2.4em; }}
.lp-keys {{ font-size: 12px; color: var(--grey-muted); }}
</style>
<section class="panel">
  <h2>The question</h2>
  <div class="lp-q"><p><strong>{_esc(spec.meta.get("question", ""))}</strong></p>{yes}</div>
  {md(spec.body) if spec.body else ""}
  <p class="muted">Label from your own judgement: <strong>Pass</strong> means this item does not show
  the failure this judge is for; <strong>Fail</strong> means it does.</p>
</section>
<section class="panel">
  <div class="lp-bar">
    <label>Labeller <input id="labeller" placeholder="your name"></label>
    <span id="count"></span>
    <div class="lp-progress"><span id="progress"></span></div>
    <button id="download" type="button">Download CSV</button>
  </div>
  <div class="lp-meta" id="meta"></div>
  <div class="lp-fields" id="fields"></div>
  <div class="lp-actions">
    <button id="prev" type="button">&larr; Previous</button>
    <button id="pass" type="button">Pass (p)</button>
    <button id="fail" type="button">Fail (f)</button>
    <button id="next" type="button">Next &rarr;</button>
    <textarea id="note" placeholder="Note (n): why, or what is unclear"></textarea>
  </div>
  <p class="lp-keys">Labels are saved in this browser as you go. When done, Download CSV and run
  <code>aot-evals label import --judge {_esc(spec.id)} --csv &lt;the downloaded file&gt;</code>.</p>
</section>
"""
    path = page_path(ev, spec)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(page(f"Label {spec.id}", "AOT evals labelling",
                         f"{len(items)} items &middot; judge version {_esc(spec.version)}", body,
                         data=data, script=SCRIPT))
    return path


SCRIPT = r"""
(function () {
  const D = JSON.parse(document.getElementById("data").textContent);
  const KEY = "aot-label:" + D.judge + ":" + D.queue_sha;
  let st = { i: 0, labels: {}, notes: {}, labeller: "" };
  try { st = Object.assign(st, JSON.parse(localStorage.getItem(KEY) || "{}")); } catch (e) {}
  const save = () => { try { localStorage.setItem(KEY, JSON.stringify(st)); } catch (e) {} };
  const $ = (id) => document.getElementById(id);
  const show = (v) => typeof v === "string" ? v : JSON.stringify(v, null, 2);

  function render() {
    const n = D.items.length;
    if (!n) { $("fields").textContent = "The queue is empty."; return; }
    st.i = Math.max(0, Math.min(st.i, n - 1));
    const it = D.items[st.i];
    const done = Object.keys(st.labels).length;
    $("count").textContent = (st.i + 1) + " of " + n + " · " + done + " labelled";
    $("progress").style.width = (100 * done / n) + "%";
    $("meta").textContent = "case " + it.case_id + " · " + (it.category || "no category") +
      (it.trial !== "" ? " · trial " + it.trial : "") + (it.run ? " · run " + it.run : "");
    const f = $("fields");
    f.innerHTML = "";
    for (const [k, v] of Object.entries(it.input || {})) {
      const d = document.createElement("div"); d.className = "lp-field";
      const h = document.createElement("h3"); h.textContent = k;
      const p = document.createElement("pre"); p.textContent = show(v);
      d.append(h, p); f.append(d);
    }
    const lab = st.labels[it.item_id];
    $("pass").classList.toggle("on", lab === "pass");
    $("fail").classList.toggle("on", lab === "fail");
    $("note").value = st.notes[it.item_id] || "";
    $("labeller").value = st.labeller || "";
  }
  function label(v) {
    st.labels[D.items[st.i].item_id] = v; save();
    if (st.i < D.items.length - 1) st.i++;
    render();
  }
  function move(d) { st.i += d; save(); render(); }
  function csvCell(v) {
    const s = v == null ? "" : String(v);
    return /[",\n\r]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
  }
  function download() {
    const lines = [D.fields.join(",")];
    for (const it of D.items) {
      const row = Object.assign({}, it, {
        label: st.labels[it.item_id] || "", labeller: st.labels[it.item_id] ? st.labeller : "",
        note: st.notes[it.item_id] || "", input: JSON.stringify(it.input) });
      lines.push(D.fields.map((k) => csvCell(row[k])).join(","));
    }
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([lines.join("\r\n") + "\r\n"], { type: "text/csv" }));
    a.download = D.judge + ".labels.csv"; a.click();
  }
  $("pass").onclick = () => label("pass");
  $("fail").onclick = () => label("fail");
  $("prev").onclick = () => move(-1);
  $("next").onclick = () => move(1);
  $("download").onclick = download;
  $("note").oninput = (e) => { st.notes[D.items[st.i].item_id] = e.target.value; save(); };
  $("labeller").oninput = (e) => { st.labeller = e.target.value; save(); };
  document.addEventListener("keydown", (e) => {
    if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA") {
      if (e.key === "Escape") e.target.blur();
      return;
    }
    if (e.key === "p") label("pass");
    else if (e.key === "f") label("fail");
    else if (e.key === "j" || e.key === "ArrowRight") move(1);
    else if (e.key === "k" || e.key === "ArrowLeft") move(-1);
    else if (e.key === "n") { e.preventDefault(); $("note").focus(); }
  });
  render();
})();
"""
