"""`replay`: grade recorded runs as if they were the agent (offline evaluation from traces).

When the agent can't be run (no sandbox, a retired version, traces from production) or a suite is
built after the fact, its recorded runs can still be graded through the ordinary contract: point
`agent.yaml` at this command and every hook replays a record instead of calling the agent.

    invoke:
      command: [aot-evals, replay, run, records/]
      seed:    aot-evals replay seed records/
      observe: aot-evals replay observe records/

`records/<case-id>.t<trial>.json` holds one recorded run:

    {"answer": "<what the person saw>", "world": <the end state checks grade>,
     "usage": {...}, "model_ids": {...}}           # usage and model_ids optional

and `records/<case-id>.start.json`, if present, the world before it (otherwise the case's
`start_state`). Trials come from the run's `--k`: trial n replays `.t<n>`. A missing record is
`no_output`, an operational outcome, never a correctness failure (G13). The world between hooks
is kept in `records/.replay-state.json`, so runs over one records directory must not overlap.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def _state(d: Path) -> Path:
    return d / ".replay-state.json"


def seed(d: Path, case: dict) -> None:
    start = d / f"{case.get('id')}.start.json"
    world = json.loads(start.read_text()) if start.exists() else case.get("start_state")
    _state(d).write_text(json.dumps({"world": world}))


def observe(d: Path) -> str:
    st = _state(d)
    return json.dumps(json.loads(st.read_text())["world"] if st.exists() else None)


def run(d: Path, payload: dict) -> dict:
    rec_path = d / f"{payload.get('case_id')}.t{payload.get('trial')}.json"
    if not rec_path.exists():
        return {"outcome": "no_output", "error": f"no record {rec_path.name}"}
    rec = json.loads(rec_path.read_text())
    _state(d).write_text(json.dumps({"world": rec.get("world")}))
    out = {"answer": rec.get("answer"), "outcome": rec.get("outcome", "ok")}
    for k in ("usage", "model_ids", "trace_id"):
        if rec.get(k) is not None:
            out[k] = rec[k]
    out.setdefault("trace_id", f"replay:{rec_path.name}")
    return out


def main(action: str, records: str) -> int:
    d = Path(records)
    if not d.is_dir():
        print(f"replay: no records directory {d}", file=sys.stderr)
        return 2
    if action == "seed":
        seed(d, json.loads(sys.stdin.read() or "{}"))
    elif action == "observe":
        print(observe(d))
    elif action == "run":
        print(json.dumps(run(d, json.loads(sys.stdin.read() or "{}"))))
    else:
        print(f"replay: unknown action {action!r} (run, seed, observe)", file=sys.stderr)
        return 2
    return 0
