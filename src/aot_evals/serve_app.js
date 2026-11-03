/* The grader application (serve.py). Plain JavaScript, no build step. Every write goes through
   POST /api/act/<action> with the session token; the server writes the suite's files. */
(function () {
  "use strict";
  const TOKEN = __TOKEN__;
  const app = document.getElementById("app");
  const TABS = [["overview", "Overview"], ["label", "Label runs"], ["agreement", "Agreement"],
                ["rules", "Rules"], ["judges", "Judges"], ["inbox", "Engineering inbox"]];
  const S = { tab: "overview", state: null, queue: [], qi: 0, mode: "auto", flash: "", judgeQ: null,
              judge: null, recheck: {}, confirm: null };

  function store(k, v) { try { if (v === undefined) return localStorage.getItem(k); localStorage.setItem(k, v); } catch (e) { return null; } }
  // A link may carry the labeller's name (&labeller=NAME), so each grader can be sent their own.
  const fromLink = new URLSearchParams(location.search).get("labeller");
  if (fromLink) store("aot-labeller", fromLink.trim());
  S.name = (fromLink || store("aot-labeller") || "").trim();
  S.tab = (location.hash || "#overview").slice(1);

  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const pct = (v) => (v == null ? "n/a" : Math.round(v * 100) + "%");
  const show = (v) => {
    if (typeof v === "string") return v;
    // a plain message request reads as its text
    if (v && typeof v.text === "string" && Object.keys(v).every((k) => k === "type" || k === "text")) return v.text;
    return JSON.stringify(v, null, 2);
  };

  async function api(path, body) {
    const opts = { headers: { "X-AOT-Token": TOKEN } };
    if (body !== undefined) { opts.method = "POST"; opts.headers["Content-Type"] = "application/json"; opts.body = JSON.stringify(body); }
    const r = await fetch(path, opts);
    const data = await r.json().catch(() => ({ error: "bad response" }));
    if (!r.ok) throw new Error(data.error || r.statusText);
    return data;
  }
  async function act(action, body) {
    try { const out = await api("/api/act/" + action, Object.assign({ by: S.name, labeller: S.name }, body)); S.err = false; return out; }
    catch (e) { S.flash = e.message; S.err = true; render(); throw e; }
  }
  async function reload() { S.state = await api("/api/state"); render(); }

  // ---- layout ---------------------------------------------------------------------------------
  const CSS = `
  .ga-bar{display:flex;flex-wrap:wrap;gap:8px 16px;align-items:center;margin:0 0 14px}
  .ga-tabs{display:flex;flex-wrap:wrap;gap:4px}
  .ga-tabs a{padding:7px 12px;border:1px solid var(--rule);text-decoration:none;color:var(--forest)}
  .ga-tabs a.on{background:var(--forest);color:#fff;border-color:var(--forest)}
  .ga-name input{font:inherit;padding:4px 6px}
  .ga-flash{background:var(--pale-green);border-left:4px solid var(--forest);padding:8px 12px;margin:0 0 12px}
  .ga-flash.err{background:#fbeee6;border-color:#8a3b12}
  .ga-fields{display:grid;gap:12px}
  .ga-field h3{font-size:13px;margin:0 0 4px;color:var(--forest)}
  .ga-field pre{white-space:pre-wrap;word-break:break-word;margin:0;max-height:55vh;overflow:auto}
  .ga-actions{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:12px 0}
  .ga-actions button,.ga-btn{font:inherit;padding:7px 14px;border:2px solid var(--forest);background:transparent;color:var(--forest);cursor:pointer}
  .ga-btn.solid,.ga-actions button.solid{background:var(--forest);color:#fff}
  .ga-actions textarea,.ga-text{font:inherit;flex:1;min-width:220px;min-height:2.6em;width:100%;box-sizing:border-box}
  .ga-tag{display:inline-block;font-size:12px;padding:2px 8px;border:1px solid var(--rule);margin-right:6px}
  .ga-tag.validated{background:var(--pale-green)} .ga-tag.provisional{background:#fdf3e0} .ga-tag.untested{background:#f1f1f1}
  .ga-item{border-top:1px solid var(--rule);padding:12px 0}
  .ga-item:first-child{border-top:0}
  .ga-row{display:flex;flex-wrap:wrap;gap:8px;align-items:center}
  .ga-wrap{overflow-x:auto}
  .ga-keys{font-size:12px;color:var(--grey-muted)}
  @media (max-width:600px){.ga-actions button{flex:1}}`;

  function render() {
    const st = S.state;
    let html = `<style>${CSS}</style><div class="ga-bar"><nav class="ga-tabs">` +
      TABS.map(([id, name]) => `<a href="#${id}" data-tab="${id}" class="${S.tab === id ? "on" : ""}">${name}${badge(id)}</a>`).join("") +
      `</nav><label class="ga-name">Your name <input id="ga-name" value="${esc(S.name)}" placeholder="who is labelling"></label></div>`;
    if (S.flash) html += `<div class="ga-flash ${S.err ? "err" : ""}" role="status">${esc(S.flash)}</div>`;
    if (!st) { app.innerHTML = html + "<p>Loading…</p>"; return; }
    html += ({ overview, label, agreement, rules, judges, inbox }[S.tab] || overview)(st);
    app.innerHTML = html;
    bind();
  }
  function badge(id) {
    const st = S.state; if (!st) return "";
    const n = { agreement: st.disputes.length + st.suite.items.filter((d) => d.split === "dev" && !(d.triage && d.triage.cause)).length,
                rules: st.proposals.filter((p) => p.status === "proposed").length, inbox: st.inbox.length }[id];
    return n ? ` (${n})` : "";
  }

  // ---- overview -------------------------------------------------------------------------------
  function overview(st) {
    const ph = st.phase;
    let h = `<section class="panel"><h2>${esc(ph.name)}</h2><p>${esc(ph.about)}</p>
      <p><strong>Next:</strong> ${esc(st.next.what)}</p></section>`;
    h += `<section class="panel"><h2>Trust per category</h2><p class="muted">Untested: no baseline covers it. Provisional: its numbers print, but the suite hasn't been held to people's verdicts yet. Validated: the suite agrees with people on its runs (floors: catch ${pct(st.floors.min_catch)}, clean pass ${pct(st.floors.min_clean)}).</p>
      <div class="ga-wrap"><table><thead><tr><th>Category</th><th>Trust</th><th>Cases</th><th>Labelled runs</th><th>Catch</th><th>Clean pass</th><th>Why</th></tr></thead><tbody>` +
      st.trust.map((r) => `<tr><td>${esc(r.category)}</td><td><span class="ga-tag ${r.level}">${r.level}</span></td><td>${r.n_cases}</td><td>${r.labelled_runs}</td><td>${pct(r.catch)}</td><td>${pct(r.clean)}</td><td>${esc(r.why)}</td></tr>`).join("") +
      `</tbody></table></div></section>`;
    if (st.changes.length) {
      h += `<section class="panel"><h2>Since the baseline</h2>` + st.changes.map((c) => `<div class="ga-item"><strong>${esc(c.what)}</strong><ul>${c.path.map((p) => `<li>${esc(p)}</li>`).join("")}</ul></div>`).join("") + `</section>`;
    }
    h += `<section class="panel"><h2>The bench</h2><p>${st.labelled} runs labelled by ${st.labellers.length} ${st.labellers.length === 1 ? "person" : "people"}${st.labellers.length ? ": " + esc(st.labellers.join(", ")) : ""}. ${st.disputes.length} disagreement(s) between people waiting for a ruling.</p></section>`;
    return h;
  }

  // ---- label runs -----------------------------------------------------------------------------
  function label() {
    if (!S.name) return `<section class="panel"><h2>Enter your name</h2><p>Every label records who made it, so agreement between people can be measured. Type your name in the box above.</p></section>`;
    const modes = [["auto", "Next for me"], ["changed", "Only what the last change moved"], ["new", "Unlabelled runs"], ["overlap", "Runs someone else labelled"], ["warmup", "Warm-up"]];
    let h = `<section class="panel"><div class="ga-row"><strong>Queue</strong> ` + modes.map(([m, n]) => `<button class="ga-btn ${S.mode === m ? "solid" : ""}" data-mode="${m}">${n}</button>`).join(" ") + `</div></section>`;
    const it = S.queue[S.qi];
    if (!it) return h + `<section class="panel"><p>Nothing left in this queue. Try another, or ask an engineer to run a new baseline or candidate.</p></section>`;
    const v = it.view || {};
    h += `<section class="panel"><p class="muted"><span class="ga-tag">${esc(it.mode)}</span>${esc(it.category)} · run ${S.qi + 1} of ${S.queue.length} · ${esc(it.item_id)}</p>
      <h2>Did the agent do what was asked, correctly?</h2>
      <p class="muted">Judge it from scratch: no check's verdict and no expected answer is shown. For a fail, say what went wrong.</p>
      <div class="ga-fields">` + Object.keys(v).map((k) => `<div class="ga-field"><h3>${esc(k)}</h3><pre>${esc(show(v[k]))}</pre></div>`).join("") + `</div>
      <div class="ga-actions"><button data-label="pass">Pass (p)</button><button data-label="fail">Fail (f)</button><button data-skip>Skip (s)</button>
      <textarea id="ga-note" placeholder="Note (n): what went wrong, or what is unclear"></textarea></div>
      <p class="ga-keys">p pass · f fail · s skip · n note. Labels are saved as you go.</p></section>`;
    return h;
  }
  async function loadQueue() {
    if (!S.name) return;
    const r = await api(`/api/queue?labeller=${encodeURIComponent(S.name)}&mode=${S.mode}`);
    S.queue = r.items; S.qi = 0; render();
  }
  async function doLabel(lab) {
    const it = S.queue[S.qi]; if (!it) return;
    const note = (document.getElementById("ga-note") || {}).value || "";
    const out = await act("label", { item: it, label: lab, note });
    S.flash = out.settled ? `Settled answer for that run: ${out.settled.label ? "pass" : "fail"} (${out.settled.why}).` +
      ((out.settled.label ? "pass" : "fail") === lab ? " You agreed." : " You differed: read the ruling before the next one.") : `Labelled ${lab}.`;
    S.qi += 1;
    if (S.qi >= S.queue.length) await loadQueue();
    await reload();
  }

  // ---- agreement ------------------------------------------------------------------------------
  function agreement(st) {
    let h = `<section class="panel"><h2>Between people</h2>`;
    h += st.between_people.length ? `<div class="ga-wrap"><table><thead><tr><th>Labellers</th><th>Runs both labelled</th><th>Agreed</th><th>κ</th></tr></thead><tbody>` +
      st.between_people.map((p) => `<tr><td>${esc(p.labellers.join(" & "))}</td><td>${p.n}</td><td>${pct(p.rate)}</td><td>${p.kappa == null ? "n/a" : p.kappa.toFixed(2)}</td></tr>`).join("") + `</tbody></table></div>`
      : `<p class="muted">No run has two labellers yet. The queue puts one overlap in every four runs.</p>`;
    h += `<h3>Waiting for a ruling (${st.disputes.length})</h3>` + (st.disputes.length ? st.disputes.map((d) => `<div class="ga-item" data-item="${esc(d.item_id)}"><p><strong>${esc(d.case_id)}</strong> <span class="muted">${esc(d.item_id)}</span></p><ul>` +
      d.labels.map((l) => `<li>${esc(l.labeller)}: <strong>${l.label ? "pass" : "fail"}</strong>${l.note ? " · " + esc(l.note) : ""}</li>`).join("") +
      `</ul><div class="ga-actions"><textarea class="ga-text" data-ruling-note placeholder="Why: this becomes the reason others see in their warm-up"></textarea><button data-rule="pass">Rule pass</button><button data-rule="fail">Rule fail</button></div></div>`).join("") : `<p class="muted">None.</p>`);
    h += `</section>`;
    const s = st.suite;
    h += `<section class="panel"><h2>The suite against people</h2><div class="ga-row"><button class="ga-btn solid" data-measure>Re-grade the labelled runs</button><span class="muted">${s.measured_at ? "Last measured " + esc(s.measured_at) + (s.stale ? " (stale: something changed since)" : "") : "Not measured yet."} Re-grading reads the recorded runs: no agent runs and no judge calls.</span></div>`;
    if (s.dev) h += `<p>Dev: catch <strong>${pct(s.dev.catch.rate)}</strong> of the runs people failed, clean pass <strong>${pct(s.dev.clean.rate)}</strong> of the runs they passed, on ${s.dev.runs} runs. Holdout: ${s.holdout.runs ? `catch ${pct(s.holdout.catch.rate)}, clean pass ${pct(s.holdout.clean.rate)}` : "no runs yet"}.</p>`;
    const dev = s.items.filter((d) => d.split === "dev");
    h += `<h3>Disagreements to explain (${dev.length})</h3>` + (dev.length ? dev.map((d) => `<div class="ga-item" data-item="${esc(d.item)}"><p><strong>${esc(d.case_id)}</strong>: person <strong>${d.human}</strong>, suite <strong>${d.suite == null ? "no verdict" : d.suite}</strong> <span class="muted">${esc(d.item)}</span></p>` +
      (d.note ? `<p>Their note: ${esc(d.note)}</p>` : "") + (d.failing.length ? `<p class="muted">Failing: ${d.failing.map(esc).join("; ")}</p>` : "") +
      `<div class="ga-actions"><select data-cause>${Object.keys(st.causes).map((c) => `<option value="${c}" ${d.triage && d.triage.cause === c ? "selected" : ""}>${c}</option>`).join("")}</select>
      <textarea class="ga-text" data-triage-note placeholder="Why">${esc((d.triage && d.triage.note) || "")}</textarea><button data-triage>Save the cause</button>` +
      (d.human === "pass" && d.suite === "fail" ? `<button data-accept>This answer is also correct</button>` : "") + `</div>` +
      `<p class="ga-keys">${esc(Object.entries(st.causes).map(([k, v]) => k + ": " + v).join(" · "))}</p></div>`).join("") : `<p class="muted">None in the latest measurement.</p>`);
    return h + `</section>`;
  }

  // ---- rules ----------------------------------------------------------------------------------
  function rules(st) {
    let h = `<section class="panel"><h2>The labelling standard</h2>` + (st.standard.rules.length ? `<ul>` + st.standard.rules.map((r) => `<li><strong>${esc(r.id)}</strong>: ${esc(r.says)} <span class="muted">${esc((r.categories || ["*"]).join(", "))}${r.from ? " · " + esc(r.from) : ""}</span></li>`).join("") + `</ul>` : `<p class="muted">No rules yet.</p>`) + `</section>`;
    const open = st.proposals.filter((p) => p.status === "proposed");
    h += `<section class="panel"><h2>Proposed rules (${open.length})</h2><p class="muted">When rulings keep going the same way, propose the pattern as a rule. The owner accepts it into the standard, and the runs it could flip are listed for a recheck.</p>` +
      st.proposals.map((p) => `<div class="ga-item" data-rule-id="${esc(p.id)}"><p><strong>${esc(p.says)}</strong></p><p class="muted">${esc(p.categories.join(", "))} · proposed by ${esc(p.by)} on ${esc(p.at)} · ${esc(p.status)}${p.decided_by ? " by " + esc(p.decided_by) : ""}</p>` +
        (p.status === "proposed" ? `<div class="ga-actions"><button data-decide="yes" class="solid">Accept into the standard</button><button data-decide="no">Decline</button></div>` : "") +
        (p.status === "accepted" ? `<button class="ga-btn" data-recheck>Runs to recheck</button> ${S.recheck[p.id] ? `<span>${S.recheck[p.id].length} run(s): ${esc(S.recheck[p.id].slice(0, 8).join(", "))}${S.recheck[p.id].length > 8 ? "…" : ""}</span>` : ""}` : "") + `</div>`).join("") +
      `<h3>Propose a rule</h3><textarea class="ga-text" id="ga-says" placeholder="e.g. A rounded amount passes when its scale and unit are right ($1.41M for $1,413,000)."></textarea>
      <div class="ga-actions"><input id="ga-cats" class="ga-text" placeholder="categories it applies to, comma separated (blank: all)"><button class="solid" data-propose>Propose</button></div></section>`;
    return h;
  }

  // ---- judges ---------------------------------------------------------------------------------
  function judges(st) {
    if (!st.judges.length) return `<section class="panel"><h2>Judges</h2><p>This suite has no AI judges: every check is code. Nothing to calibrate.</p></section>`;
    let h = st.judges.map((j) => `<section class="panel" data-judge="${esc(j.id)}"><h2>${esc(j.id)} <span class="muted">v${esc(j.version)}</span></h2><p><strong>${esc(j.question || "")}</strong></p>
      <p>${j.labels} labels (${j.pass} pass, ${j.fail} fail)${j.labellers.length ? " by " + esc(j.labellers.join(", ")) : ""}. Calibration: <strong>${esc(j.calibration || "none")}</strong>${j.tpr != null ? ` · passes good work ${pct(j.tpr)}, catches failures ${pct(j.tnr)}` : ""}.</p>
      ${j.missing_categories.length ? `<p class="muted">No labels yet in: ${esc(j.missing_categories.join(", "))}</p>` : ""}
      <div class="ga-actions"><button data-jlabel>Label items for this judge</button><button data-calibrate>Recalibrate</button></div>
      ${S.confirm && S.confirm.judge === j.id ? `<div class="ga-flash">${esc(S.confirm.message)} <button class="ga-btn solid" data-confirm>Confirm: ${S.confirm.calls} call(s)</button></div>` : ""}</section>`).join("");
    const q = S.judgeQ, it = q && q.items[q.i];
    if (q) {
      const j = st.judges.find((x) => x.id === q.judge);
      h += `<section class="panel"><h2>Labelling for ${esc(q.judge)}</h2>` + (it ? `<p class="muted">Item ${q.i + 1} of ${q.items.length} · ${esc(it.category)} · ${esc(it.case_id)}</p><p><strong>${esc(j.question)}</strong></p>
        <p class="muted">Pass means this item does not show the failure this judge is for; fail means it does.</p>
        <div class="ga-fields">` + Object.keys(it.input).map((k) => `<div class="ga-field"><h3>${esc(k)}</h3><pre>${esc(show(it.input[k]))}</pre></div>`).join("") +
        `</div><div class="ga-actions"><button data-jl="pass">Pass</button><button data-jl="fail">Fail</button><textarea id="ga-jnote" placeholder="Note"></textarea></div>` : `<p>Nothing left to label for this judge.</p>`) + `</section>`;
    }
    return h;
  }

  // ---- inbox ----------------------------------------------------------------------------------
  function inbox(st) {
    let h = `<section class="panel"><h2>Waiting on engineering (${st.inbox.length})</h2><p class="muted">What only an engineer can do: fix a check or a case, finish a drafted case, run the agent after it changed. Everything else happens here.</p>` +
      (st.inbox.length ? st.inbox.map((x) => `<div class="ga-item"><p><span class="ga-tag">${esc(x.kind)}</span><strong>${esc(x.what)}</strong></p><p>${esc(x.note)}</p><p class="muted">${esc([x.case, x.item, x.by].filter(Boolean).join(" · "))}</p></div>`).join("") : `<p class="muted">Nothing.</p>`) + `</section>`;
    h += `<section class="panel"><h2>Draft a new case</h2><p class="muted">Write a new request in the shape of an existing case. An engineer sets its start and expected end state before it is graded.</p>
      <div class="ga-fields"><label>Like case <select id="ga-like">${st.cases.map((c) => `<option value="${esc(c.id)}">${esc(c.id)} (${esc(c.category)})</option>`).join("")}</select></label>
      <textarea class="ga-text" id="ga-req" placeholder="The request, as a user would send it"></textarea>
      <textarea class="ga-text" id="ga-ans" placeholder="A correct answer, if it has one (optional)"></textarea>
      <label><input type="checkbox" id="ga-nochange"> Nothing should change</label>
      <textarea class="ga-text" id="ga-dnote" placeholder="What this case tests"></textarea></div>
      <div class="ga-actions"><button class="solid" data-draft>Save the draft</button></div>
      ${st.drafts.length ? `<h3>Drafts</h3><ul>${st.drafts.map((d) => `<li>${esc(d.id)}: ${esc(d.trigger.text)} <span class="muted">by ${esc(d.by)}</span></li>`).join("")}</ul>` : ""}</section>`;
    return h;
  }

  // ---- events ---------------------------------------------------------------------------------
  function bind() {
    const name = document.getElementById("ga-name");
    if (name) name.onchange = () => { S.name = name.value.trim(); store("aot-labeller", S.name); S.queue = []; if (S.tab === "label") loadQueue(); render(); };
    app.querySelectorAll("[data-tab]").forEach((a) => (a.onclick = (e) => { e.preventDefault(); S.tab = a.dataset.tab; S.flash = ""; location.hash = S.tab; if (S.tab === "label" && !S.queue.length) loadQueue(); render(); }));
    app.querySelectorAll("[data-mode]").forEach((b) => (b.onclick = () => { S.mode = b.dataset.mode; loadQueue(); }));
    app.querySelectorAll("[data-label]").forEach((b) => (b.onclick = () => doLabel(b.dataset.label)));
    app.querySelectorAll("[data-skip]").forEach((b) => (b.onclick = () => { S.qi += 1; render(); }));
    app.querySelectorAll("[data-rule]").forEach((b) => (b.onclick = async () => {
      const box = b.closest("[data-item]");
      await act("rule-dispute", { item_id: box.dataset.item, label: b.dataset.rule, note: box.querySelector("[data-ruling-note]").value });
      S.flash = "Ruling saved."; reload();
    }));
    app.querySelectorAll("[data-measure]").forEach((b) => (b.onclick = async () => { b.disabled = true; await act("measure", {}); S.flash = "Re-graded."; reload(); }));
    app.querySelectorAll("[data-triage]").forEach((b) => (b.onclick = async () => {
      const box = b.closest("[data-item]");
      await act("triage", { item: box.dataset.item, cause: box.querySelector("[data-cause]").value, note: box.querySelector("[data-triage-note]").value });
      S.flash = "Cause saved."; reload();
    }));
    app.querySelectorAll("[data-accept]").forEach((b) => (b.onclick = async () => {
      const out = await act("accept-answer", { item: b.closest("[data-item]").dataset.item });
      S.flash = out.check_rejects && out.check_rejects.length ? "Added as another correct answer, but a check still rejects it; it is in the engineering inbox as a check bug." : "Added as another correct answer. Re-grade to see the effect.";
      reload();
    }));
    app.querySelectorAll("[data-decide]").forEach((b) => (b.onclick = async () => {
      await act("decide", { id: b.closest("[data-rule-id]").dataset.ruleId, accept: b.dataset.decide === "yes" });
      S.flash = b.dataset.decide === "yes" ? "Accepted into the standard. Recheck the runs it could flip." : "Declined."; reload();
    }));
    app.querySelectorAll("[data-recheck]").forEach((b) => (b.onclick = async () => {
      const id = b.closest("[data-rule-id]").dataset.ruleId;
      S.recheck[id] = (await api("/api/recheck?rule=" + encodeURIComponent(id))).items; render();
    }));
    app.querySelectorAll("[data-propose]").forEach((b) => (b.onclick = async () => {
      const says = document.getElementById("ga-says").value, cats = document.getElementById("ga-cats").value.split(",").map((x) => x.trim()).filter(Boolean);
      await act("propose", { says, categories: cats.length ? cats : ["*"] }); S.flash = "Proposed. The owner accepts or declines it here."; reload();
    }));
    app.querySelectorAll("[data-jlabel]").forEach((b) => (b.onclick = async () => {
      const id = b.closest("[data-judge]").dataset.judge;
      S.judgeQ = { judge: id, i: 0, items: (await api(`/api/judge-queue?judge=${encodeURIComponent(id)}&labeller=${encodeURIComponent(S.name)}`)).items }; render();
    }));
    app.querySelectorAll("[data-jl]").forEach((b) => (b.onclick = async () => {
      const q = S.judgeQ, it = q.items[q.i];
      await act("judge-label", { judge: q.judge, row: it, label: b.dataset.jl, note: (document.getElementById("ga-jnote") || {}).value || "" });
      q.i += 1; S.flash = "Labelled."; reload();
    }));
    app.querySelectorAll("[data-calibrate]").forEach((b) => (b.onclick = async () => calibrate(b.closest("[data-judge]").dataset.judge, false)));
    app.querySelectorAll("[data-confirm]").forEach((b) => (b.onclick = async () => calibrate(S.confirm.judge, true)));
    app.querySelectorAll("[data-draft]").forEach((b) => (b.onclick = async () => {
      await act("draft", { like: document.getElementById("ga-like").value, request: document.getElementById("ga-req").value,
        answer: document.getElementById("ga-ans").value, nothing_changes: document.getElementById("ga-nochange").checked, note: document.getElementById("ga-dnote").value });
      S.flash = "Draft saved; it is in the engineering inbox."; reload();
    }));
  }
  async function calibrate(judge, confirm) {
    const out = await act("calibrate", { judge, confirm });
    if (out.needs_confirm) { S.confirm = Object.assign({ judge }, out); render(); return; }
    S.confirm = null; S.flash = `Recalibrated: ${out.status}${out.reasons && out.reasons.length ? " (" + out.reasons.join("; ") + ")" : ""}.`; reload();
  }
  document.addEventListener("keydown", (e) => {
    if (S.tab !== "label" || /TEXTAREA|INPUT|SELECT/.test(document.activeElement.tagName)) return;
    if (e.key === "p") doLabel("pass"); else if (e.key === "f") doLabel("fail");
    else if (e.key === "s") { S.qi += 1; render(); }
    else if (e.key === "n") { const n = document.getElementById("ga-note"); if (n) { e.preventDefault(); n.focus(); } }
  });
  window.addEventListener("hashchange", () => { S.tab = (location.hash || "#overview").slice(1); render(); });
  reload().then(() => { if (S.tab === "label") loadQueue(); }).catch((e) => { S.flash = e.message; S.err = true; render(); });
})();
