"""Where an agent system's evals go (estimators §1, rule 3; v2-design §1, §10.1): the parts of the
system, their context boundaries, and which of them earn an eval of their own.

agent.yaml's `components:` lists each part of the system the orchestrator calls:

```yaml
components:
  - id: refund-subagent
    kind: subagent          # subagent | route | step
    context: own            # own: it starts from its handoff | shared: it reads the orchestrator's transcript
    called_by: the orchestrator's refund route
    instructions: [agent/refunds_prompt.md]
    model: claude-haiku-5-5
    owner: refunds team
    ships_separately: true  # its own prompt, model or owner, changed on its own schedule
    use_case: refund        # the end-to-end use case whose requests reach it
    evidence: handoffs in 212 of 10,412 traces (data/support-requests-2026-10)
```

- A **subagent** is called with a handoff the orchestrator writes: a defined input, captured in
  the end-to-end traces, that can be sampled and replayed.
- A **route** is a path a router sends the user's request down as the user sent it. Its population
  is the routed share of the requests, which is a use case of the end-to-end eval, not a population
  of its own.
- A **step** runs inside the orchestrator's context.

`placement` turns that into where the component is graded:

| Component | Where it is graded |
|---|---|
| subagent, own context, ships separately | its own eval (`init --component`), drawn from its handoffs (rule 4) |
| subagent, own context, ships with the system | checks end to end: its own eval would drive no decision |
| route whose model ships on its own | a use case gate in the end-to-end eval (rule 20) |
| route that ships with the system | a use case of the end-to-end eval |
| step, or shared context | checks on its steps in the end-to-end eval |

The discovery report (`discovery.md`) may name the boundaries before agent.yaml does
(`boundaries:` in its front matter, the same fields); `build` drafts agent.yaml's list from it.
"""

from __future__ import annotations

KINDS = ("subagent", "route", "step")
CONTEXTS = ("own", "shared")
FIELDS = ("id", "kind", "context", "called_by", "instructions", "model", "owner", "ships_separately",
          "use_case", "evidence")

# placement ids
OWN_EVAL = "own_eval"
USE_CASE_GATE = "use_case_gate"
USE_CASE = "use_case"
CHECKS = "checks"
UNKNOWN = "unknown"


def entries(raw) -> list[dict]:
    if isinstance(raw, dict):  # {id: {...}} is accepted as well as a list
        raw = [{"id": k, **(v if isinstance(v, dict) else {})} for k, v in raw.items()]
    if not isinstance(raw, list):
        return []
    return [{k: c.get(k) for k in FIELDS} for c in raw if isinstance(c, dict) and c.get("id")]


def inventory(agent: dict) -> list[dict]:
    """agent.yaml's `components`, each with every field (None where not stated)."""
    return entries((agent or {}).get("components"))


def by_id(agent: dict) -> dict[str, dict]:
    return {c["id"]: c for c in inventory(agent)}


def placement(c: dict) -> dict:
    """Where a component is graded: {placement, why}. `unknown` names what is not stated yet."""
    kind, ctx, ships = c.get("kind"), c.get("context"), c.get("ships_separately")
    name = c.get("id")
    if kind not in KINDS:
        return {"placement": UNKNOWN, "why": f"{name}: kind not stated (subagent, route or step)",
                "needs": "kind"}
    if kind == "step" or ctx == "shared":
        return {"placement": CHECKS,
                "why": f"{name} runs inside the orchestrator's context: it can't be sampled or replayed on "
                       "its own, so checks on its steps in the end-to-end eval grade it (rule 3)"}
    if kind == "route":
        if ships is True:
            return {"placement": USE_CASE_GATE,
                    "why": f"{name} gets the user's request as sent, so its population is a use case of the "
                           "end-to-end eval; its model ships on its own, so that use case gets a gate of its "
                           "own (rule 20), not an eval of its own"}
        if ships is False:
            return {"placement": USE_CASE,
                    "why": f"{name} gets the user's request as sent: a use case of the end-to-end eval"}
        return {"placement": UNKNOWN, "needs": "ships_separately",
                "why": f"{name}: whether its model ships on its own is not stated; if it does, its use case "
                       "gets a gate"}
    if ctx not in CONTEXTS:
        return {"placement": UNKNOWN, "needs": "context",
                "why": f"{name}: whether it starts from a handoff (own context) or reads the orchestrator's "
                       "transcript (shared) is not stated"}
    if ships is True:
        return {"placement": OWN_EVAL,
                "why": f"{name} has a context boundary and is decided on separately: an eval of its own, "
                       "drawn from the handoffs it receives (rules 3, 4), gated on the end-to-end eval "
                       "(rule 27)"}
    if ships is False:
        return {"placement": CHECKS,
                "why": f"{name} is only ever changed with the rest of the system: an eval of it would drive "
                       "no decision, so the end-to-end eval's checks cover it (rule 3)"}
    return {"placement": UNKNOWN, "needs": "ships_separately",
            "why": f"{name} has a context boundary; whether a team changes it on its own schedule (its own "
                   "prompt, model or owner) is not stated"}


def plan(agent: dict) -> list[dict]:
    """Each component with its placement."""
    return [{**c, **placement(c)} for c in inventory(agent)]


def from_discovery(path) -> list[dict]:
    """The context boundaries the discovery report found (`boundaries:` in its front matter)."""
    from .start import split_front_matter

    if not path.exists():
        return []
    fm, _ = split_front_matter(path.read_text())
    return entries((fm or {}).get("boundaries"))


def render(rows: list[dict]) -> str:
    word = {OWN_EVAL: "its own eval", USE_CASE_GATE: "a use case gate", USE_CASE: "a use case",
            CHECKS: "checks in the end-to-end eval", UNKNOWN: "not decided yet"}
    return "\n".join(f"  {r['id']:<22} {word[r['placement']]}: {r['why']}" for r in rows)
