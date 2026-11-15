"""`aot-evals serve`: the grader application (docs/method.md §7), for one eval.

A local web application for the Judge phase, on one eval of an agent system (`--eval`, or the
agent's only eval; docs/v2-design.md §1): people label whole runs (several people, blind to
each other, with a warm-up and overlaps), settle disagreements between labellers with rulings,
see where the suite and people disagree and give each a cause, accept another correct answer,
propose rules from rulings for the owner to accept, label and recalibrate judges, draft new cases,
and see what is waiting on engineering. Every action writes the eval's own files, or the agent
system's shared labelling standard (bench.py), so the result is reviewed and committed like any
other change. The overview reads the eval's spec (complete, or the fields it lacks), its baseline,
how far the eval agrees with people per use case, and the agent system's components.

It is the standard library's `http.server` and one page of plain JavaScript (serve_app.js): no
service, no account, no build step. It binds to 127.0.0.1 by default. Every API call must carry
the session token the page was served with, so another site open in the same browser can't
write to the eval. `--host 0.0.0.0` lets graders on the same network use it: anyone who can reach
the port and holds the link can label, so only do that on a network you trust.
"""

from __future__ import annotations

import json
import secrets
import threading
import webbrowser
from collections import Counter
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import agreement, bench, components, journal
from .brand import page
from .repo import Eval
from .util import ContractError

APP_JS = Path(__file__).with_name("serve_app.js")
LOCK = threading.Lock()  # one writer at a time: every action appends to or rewrites the eval's files


def _judges(ev: Eval) -> list[dict]:
    from .calibrate import is_current, load_calibration, pending_calls
    from .judges import load_spec
    from .labels import queue_path
    from .labels import status as label_status
    from .spec import check_ids

    out = []
    for cid in sorted(c for c in check_ids(ev.spec()) if ev.check_type(c) == "judge"):
        try:
            spec = load_spec(ev.judge_check_path(cid))
        except ContractError as e:
            out.append({"id": cid, "error": str(e)})
            continue
        st = label_status(ev, spec)
        cal = load_calibration(ev, spec)
        prim = ((cal or {}).get("backends") or {}).get(spec.primary) or {}
        labelled = st["labels"] > 0
        out.append({"id": spec.id, "version": spec.version, "question": spec.meta.get("question"),
                    "guidance": spec.body, "primary": spec.primary, "labels": st["labels"],
                    "pass": st["pass"], "fail": st["fail"], "labellers": st["labellers"],
                    "missing_use_cases": st.get("missing_use_cases", st.get("missing_categories")) or [],
                    "calibration": (cal or {}).get("status") if is_current(ev, spec, cal) else
                    ("stale" if cal else None),
                    "tpr": prim.get("tpr"), "tnr": prim.get("tnr"),
                    "pending_calls": pending_calls(ev, spec, [spec.primary]) if labelled else {},
                    "queue": queue_path(ev, spec).exists()})
    return out


def _judge_queue(ev: Eval, jid: str, labeller: str) -> list[dict]:
    import csv

    from .judges import load_spec
    from .labels import load_labels, make_queue, queue_path

    spec = load_spec(ev.judge_check_path(jid))
    q = queue_path(ev, spec)
    if not q.exists():
        runs = bench.label_runs(ev)
        if not runs:
            return []
        make_queue(ev, spec, runs, n=120)
    done = {r["item_id"] for r in load_labels(ev, spec)}
    with q.open(newline="") as f:
        rows = [r for r in csv.DictReader(f) if r["item_id"] not in done]
    return [{**r, "input": json.loads(r["input"] or "{}")} for r in rows[:20]]


def _use_cases(ev: Eval, res: dict) -> list[dict]:
    """Per use case of the spec: its cases, how many a baseline covers, its labelled runs, and
    the eval's catch and clean pass rates against people on them (the latest measurement, dev)."""
    spec_ucs = [u.get("id") for u in ev.spec().part("estimand").get("use_cases") or []
                if isinstance(u, dict) and u.get("id")]
    cases = ev.cases(include_dropped=False)
    of = {c.get("id"): c.get("use_case") for c in cases}
    covered = {c for m in ev.baseline_runs() for c in (m.get("case_set") or {}).get("ids") or []}
    labelled = Counter(of.get(r.get("case_id")) for r in agreement.load_labels(ev))
    measured = res.get("use_cases") or {}
    ids = list(dict.fromkeys([*spec_ucs, *sorted({u for u in of.values() if u})]))
    out = []
    for uc in ids:
        dev = (measured.get(uc) or {}).get("dev") or {}
        out.append({"id": uc, "in_spec": uc in spec_ucs,
                    "cases": sum(u == uc for u in of.values()),
                    "in_baseline": sum(u == uc and c in covered for c, u in of.items()),
                    "labelled_runs": labelled.get(uc, 0),
                    "catch": (dev.get("catch") or {}).get("rate"), "clean": (dev.get("clean") or {}).get("rate")})
    return out


def _people(ev: Eval) -> dict:
    """The eval held to people (rule 15): its floors and labels per kind from the spec, and what
    still stands between it and them (agreement.gates)."""
    from .measurement import labels_needed, people_settings

    spec = ev.spec()
    result = agreement.load_result(ev)
    labels = agreement.load_labels(ev)
    n_fail = sum(not r["label"] for r in labels)
    ps = people_settings(spec)
    return {"floors": ps["floors"], "margin": ps["margin"],
            "labels": {"fail": n_fail, "pass": len(labels) - n_fail},
            "labels_needed": {k: (v or {}).get("n") for k, v in labels_needed(spec).items()},
            "status": ((result or {}).get("evidence") or {}).get("status") if result else None,
            "problems": agreement.gate_problems(ev, result, labels)}


def state(ev: Eval) -> dict:
    from .requirements import load_standard

    spec = ev.spec()
    std = load_standard(ev) or {"rules": [], "body": ""}
    res = bench.suite_disagreements(ev)
    cand = bench.candidate_run(ev)
    by = agreement.per_labeller(ev)
    return {"agent": ev.agent_name, "eval": ev.id, "evals": [e.id for e in ev.agent_system.evals()],
            "suite_dir": str(ev.root), "decision": spec.part("estimand").get("decision"),
            "spec": {"complete": spec.complete, "missing": [i.field for i in spec.missing],
                     "invalid": [i.field for i in spec.invalid]},
            "baseline": ev.baseline_ids(), "candidate": cand,
            "labellers": sorted({r.get("labeller") for people in by.values()
                                 for r in people.values()} - {None, ""}),
            "labelled": len(by),
            "between_people": agreement.labeller_agreement(ev),
            "disputes": agreement.disputes(ev),
            "suite": res, "causes": agreement.CAUSES, "use_cases": _use_cases(ev, res),
            "people": _people(ev),
            "standard": {"rules": std["rules"], "body": std["body"]},
            "proposals": bench.proposals(ev), "drafts": bench.drafts(ev), "inbox": bench.inbox(ev),
            "components": components.checklist(ev.agent_system),
            "judges": _judges(ev), "cases": [{"id": c["id"], "use_case": c.get("use_case")}
                                             for c in ev.cases(include_dropped=False)]}


# ---- actions ------------------------------------------------------------------------------------

def _need(body: dict, *keys: str) -> list:
    missing = [k for k in keys if body.get(k) in (None, "", [])]
    if missing:
        raise ValueError(f"missing {', '.join(missing)}")
    return [body[k] for k in keys]


def act(ev: Eval, action: str, body: dict) -> dict:
    """One action from the application. Each is logged to the activity log by name."""
    who = (body.get("by") or body.get("labeller") or "").strip()
    if action == "label":
        item, label = _need(body, "item", "label")
        if not who:
            raise ValueError("enter your name first: every label records who made it")
        out = bench.record_label(ev, item, label, who, body.get("note") or "")
        text = f"{who} labelled {item['item_id']} {label}"
    elif action == "rule-dispute":
        item, label = _need(body, "item_id", "label")
        if not who:
            raise ValueError("enter your name first: a ruling records who made it")
        out = agreement.add_ruling(ev, item, label in (True, "pass"), who, body.get("note") or "",
                                   body.get("rule"))
        text = f"{who} ruled {item} {'pass' if out['label'] else 'fail'}"
    elif action == "measure":
        res = agreement.measure(ev, call_judges=False, log=lambda *_: None)
        out = {"dev": res["dev"], "holdout": res["holdout"], "problems": res["problems"]}
        text = "agreement re-measured from the recorded runs (no agent runs, no judge calls)"
    elif action == "triage":
        item, cause = _need(body, "item", "cause")
        out = bench.set_triage(ev, item, cause, body.get("note") or "", who or "grader")
        text = f"{who or 'a grader'} triaged {item}: {cause}"
    elif action == "accept-answer":
        (item,) = _need(body, "item")
        if not who:
            raise ValueError("enter your name first")
        out = bench.accept_answer(ev, item, who)
        text = f"{who} accepted the answer in {item} as another correct wording of case {out['case']}"
    elif action == "propose":
        (says,) = _need(body, "says")
        if not who:
            raise ValueError("enter your name first")
        out = bench.propose_rule(ev, says, body.get("use_cases") or ["*"], who, body.get("items") or [])
        text = f"{who} proposed a rule: {says}"
    elif action == "decide":
        (rid,) = _need(body, "id")
        accept = body.get("accept")
        if accept is None:
            raise ValueError("missing accept: true to accept the rule, false to decline it")
        if not who:
            raise ValueError("enter your name first: the owner's decision records who made it")
        out = bench.decide_rule(ev, rid, accept in (True, "true", "yes"), who)
        text = f"{who} {out['status']} the rule {rid}"
    elif action == "draft":
        like, request = _need(body, "like", "request")
        if not who:
            raise ValueError("enter your name first")
        out = bench.draft_case(ev, like, request, who, body.get("answer"), bool(body.get("nothing_changes")),
                               body.get("note") or "")
        text = f"{who} drafted a case like {like}"
    elif action == "judge-label":
        from .judges import load_spec
        from .labels import import_rows

        jid, row, label = _need(body, "judge", "row", "label")
        if not who:
            raise ValueError("enter your name first")
        spec = load_spec(ev.judge_check_path(jid))
        out = import_rows(ev, spec, [{**row, "label": label, "note": body.get("note") or "",
                                      "input": json.dumps(row["input"])}], who)
        text = f"{who} labelled an item for judge {jid} {label}"
    elif action == "calibrate":
        from .calibrate import calibrate, pending_calls
        from .judges import load_spec

        (jid,) = _need(body, "judge")
        spec = load_spec(ev.judge_check_path(jid))
        pending = sum(pending_calls(ev, spec, [spec.primary]).values())
        if pending and not body.get("confirm"):
            return {"needs_confirm": True, "calls": pending,
                    "message": f"Calibrating {jid} calls its judge {pending} time(s) for labels it hasn't "
                               "judged yet. That can cost money. Confirm to go ahead."}
        rec = calibrate(ev, spec, [spec.primary], call=True, log=lambda *_: None)
        out = {"status": rec["status"], "reasons": rec["status_reasons"]}
        text = f"judge {jid} recalibrated: {rec['status']}"
    else:
        raise ValueError(f"unknown action {action!r}")
    journal.append(ev, "decision" if action in ("rule-dispute", "decide", "triage") else "step", text,
                   gate="C19", by=who or None)
    return out


# ---- the server ---------------------------------------------------------------------------------

def app_page(ev: Eval, token: str) -> str:
    script = APP_JS.read_text().replace("__TOKEN__", json.dumps(token))
    body = '<div id="app"><p class="muted">Loading…</p></div>'
    return page(f"Grade {ev.agent_name} · {ev.id}", "AOT evals · grader application",
                "Label runs, settle disagreements, and hold the suite to what people decide.",
                body, script=script)


def make_handler(ev: Eval, token: str):
    class Handler(BaseHTTPRequestHandler):
        server_version = "aot-evals"

        def log_message(self, fmt, *args):  # keep the terminal quiet; actions go to the activity log
            pass

        def _send(self, code: int, payload, ctype: str = "application/json") -> None:
            data = payload if isinstance(payload, bytes) else (
                payload.encode() if isinstance(payload, str) else json.dumps(payload, default=str).encode())
            self.send_response(code)
            self.send_header("Content-Type", f"{ctype}; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(data)

        def _authorized(self) -> bool:
            return secrets.compare_digest(self.headers.get("X-AOT-Token", ""), token)

        def do_GET(self):  # noqa: N802
            url = urlparse(self.path)
            if url.path == "/":
                q = parse_qs(url.query)
                if not secrets.compare_digest((q.get("t") or [""])[0], token):
                    return self._send(HTTPStatus.FORBIDDEN, "Open the link `aot-evals serve` printed.",
                                      "text/plain")
                return self._send(HTTPStatus.OK, app_page(ev, token), "text/html")
            if not self._authorized():
                return self._send(HTTPStatus.FORBIDDEN, {"error": "missing or wrong session token"})
            q = {k: v[0] for k, v in parse_qs(url.query).items()}
            try:
                if url.path == "/api/state":
                    return self._send(HTTPStatus.OK, state(ev))
                if url.path == "/api/queue":
                    return self._send(HTTPStatus.OK, {"items": bench.queue(ev, q.get("labeller", ""),
                                                                           q.get("mode", "auto"))})
                if url.path == "/api/judge-queue":
                    return self._send(HTTPStatus.OK, {"items": _judge_queue(ev, q["judge"], q.get("labeller", ""))})
                if url.path == "/api/recheck":
                    return self._send(HTTPStatus.OK, {"items": bench.recheck(ev, q.get("rule", ""))})
            except (ValueError, KeyError, FileNotFoundError, ContractError) as e:
                return self._send(HTTPStatus.BAD_REQUEST, {"error": str(e)})
            return self._send(HTTPStatus.NOT_FOUND, {"error": "not found"})

        def do_POST(self):  # noqa: N802
            url = urlparse(self.path)
            if not self._authorized():
                return self._send(HTTPStatus.FORBIDDEN, {"error": "missing or wrong session token"})
            if not url.path.startswith("/api/act/"):
                return self._send(HTTPStatus.NOT_FOUND, {"error": "not found"})
            try:
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n) or b"{}")
                with LOCK:
                    out = act(ev, url.path.rsplit("/", 1)[1], body)
                return self._send(HTTPStatus.OK, out)
            except (ValueError, KeyError, FileNotFoundError, ContractError, json.JSONDecodeError) as e:
                return self._send(HTTPStatus.BAD_REQUEST, {"error": str(e)})

    return Handler


def serve(ev: Eval, host: str = "127.0.0.1", port: int = 8765, open_browser: bool = False,
          log=print) -> None:
    token = secrets.token_urlsafe(16)
    httpd = ThreadingHTTPServer((host, port), make_handler(ev, token))
    shown = "127.0.0.1" if host in ("127.0.0.1", "localhost") else host
    url = f"http://{shown}:{httpd.server_address[1]}/?t={token}"
    log(f"The grader application for {ev.agent_name}, eval {ev.id}, is at:\n\n  {url}\n")
    if host not in ("127.0.0.1", "localhost"):
        log("It is reachable from other machines: anyone with this link can label. Use it only on a "
            "network you trust.")
    log("Send each grader their own link by adding &labeller=NAME to it.")
    log("Everything it writes goes into the eval's files; review and commit them as usual. Ctrl-C stops it.")
    journal.append(ev, "step", f"the grader application started on {ev.id}", gate="C19")
    if open_browser:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
