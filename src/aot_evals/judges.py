"""Judge checks (docs/method.md §5): one failure mode, one binary typed question, any backend.

A judge is `evals/checks/judge/<check-id>.md`: YAML frontmatter plus a human-readable body.

    ---
    id: summary-invents-figure
    failure_mode: invented-figure
    version: 3
    question_type: noul            # noul | choice | score
    question: The summary states a figure that does not appear in the source.
    detects: failure               # noul: does "yes" mean the failure is present (failure) or the
                                   #   requirement is met (pass)?
    options: {...}                 # choice: option -> definition; score: list of levels
    pass_options: [...]            # choice: options that mean pass
    pass_min_level: 1              # score: lowest level index that means pass
    inputs: [end.output, case.inputs.source]   # what the judge sees; dotted paths
    mode: binary                   # binary | pairwise (G4)
    min_tpr: 0.75                  # below either floor the judge stays uncalibrated (greyed)
    min_tnr: 0.75
    primary: jev
    backends:
      jev:    {type: systemone, model: jev-1.13, family: typesafe,
               base_url: https://api.typesafe.ai, api_key_env: TYPESAFE_API_KEY}
      claude: {type: anthropic, model: claude-opus-5-5, family: anthropic, effort: medium}
      local:  {type: command, command: [python, judges/my_judge.py], family: other, model: x}
    ---

Every backend returns a score s = P(pass) in [0, 1] for an item. Backends that return a
probability (System One) are thresholded on the labels (C10); backends that return a bare
verdict (a generative LLM, a command without a probability) give s in {0, 1}.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from . import __version__
from .executor import agent_env
from .util import ContractError, get_path

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

QUESTION_TYPES = ("noul", "choice", "score")
BACKEND_TYPES = ("systemone", "anthropic", "command")
DEFAULT_MIN_RATE = 0.75

# USD per million tokens (input, output) for cost per judgement. The Messages API reports tokens,
# not dollars, so generative judge costs are estimates; override with price_input_per_mtok /
# price_output_per_mtok in the backend config. Source: Anthropic's published pricing; check it is current.
ANTHROPIC_PRICES = {
    "claude-fable-5-1": (10.0, 50.0),
    "claude-opus-5-5": (4.0, 20.0),
    "claude-opus-5": (5.0, 25.0),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-haiku-4-5": (1.0, 5.0),
}
SYSTEMONE_PRICE_INPUT_PER_MTOK = 0.042  # Jev list price; output tokens are free


class JudgeError(Exception):
    """The judge could not produce a verdict (an instrument failure, never an agent failure)."""


# ---- spec ------------------------------------------------------------------------------------

@dataclass
class JudgeSpec:
    id: str
    path: Path
    meta: dict
    body: str

    @property
    def version(self):
        return self.meta.get("version")

    @property
    def failure_mode(self) -> str | None:
        return self.meta.get("failure_mode")

    @property
    def question_type(self) -> str:
        return self.meta.get("question_type", "noul")

    @property
    def backends(self) -> dict[str, dict]:
        return dict(self.meta.get("backends") or {})

    @property
    def primary(self) -> str | None:
        p = self.meta.get("primary")
        if p:
            return p
        names = list(self.backends)
        return names[0] if len(names) == 1 else None

    @property
    def min_tpr(self) -> float:
        return float(self.meta.get("min_tpr", DEFAULT_MIN_RATE))

    @property
    def min_tnr(self) -> float:
        return float(self.meta.get("min_tnr", DEFAULT_MIN_RATE))

    @property
    def mode(self) -> str:
        return self.meta.get("mode", "binary")

    def sha(self) -> str:
        """Hash of everything that changes what the judge decides (not the prose body)."""
        relevant = {k: v for k, v in self.meta.items() if k not in ("primary", "min_tpr", "min_tnr")}
        return hashlib.sha256(json.dumps(relevant, sort_keys=True, default=str).encode()).hexdigest()[:16]

    def backend_sha(self, backend: str) -> str:
        """sha() for one backend: the question and inputs plus that backend's own config only, so
        adding or changing another backend leaves this backend's cached judgements valid."""
        relevant = {k: v for k, v in self.meta.items()
                    if k not in ("primary", "min_tpr", "min_tnr", "backends")}
        relevant["backend"] = self.backends.get(backend)
        return hashlib.sha256(json.dumps(relevant, sort_keys=True, default=str).encode()).hexdigest()[:16]

    def problems(self) -> list[str]:
        p = []
        m = self.meta
        if m.get("id") and m["id"] != self.id:
            p.append(f"judge {self.id}: frontmatter id {m['id']!r} does not match the file name")
        if self.question_type not in QUESTION_TYPES:
            p.append(f"judge {self.id}: question_type must be one of {QUESTION_TYPES}")
        if not m.get("question"):
            p.append(f"judge {self.id}: question missing")
        if self.question_type == "noul" and m.get("detects") not in ("failure", "pass"):
            p.append(f"judge {self.id}: detects must be 'failure' or 'pass' (what a yes means)")
        if self.question_type == "choice" and not (isinstance(m.get("options"), dict) and m.get("pass_options")):
            p.append(f"judge {self.id}: choice needs options (name -> definition) and pass_options")
        if self.question_type == "score" and not (isinstance(m.get("options"), list) and "pass_min_level" in m):
            p.append(f"judge {self.id}: score needs options (list of levels) and pass_min_level")
        if not m.get("inputs"):
            p.append(f"judge {self.id}: inputs missing (which fields the judge sees)")
        if m.get("version") is None:
            p.append(f"judge {self.id}: version missing")
        if not self.backends:
            p.append(f"judge {self.id}: no backends")
        for name, b in self.backends.items():
            if b.get("type") not in BACKEND_TYPES:
                p.append(f"judge {self.id}: backend {name} type must be one of {BACKEND_TYPES}")
            if not b.get("family"):
                p.append(f"judge {self.id}: backend {name} has no model family (G4)")
            if not b.get("model"):
                p.append(f"judge {self.id}: backend {name} has no model id")
            if b.get("type") == "command" and not (_repo_root(self) / str(b.get("cwd", "."))).is_dir():
                p.append(f"judge {self.id}: backend {name} cwd {b.get('cwd', '.')!r} is not a "
                         "directory under the repository root")
        if self.backends and not self.primary:
            p.append(f"judge {self.id}: several backends and no primary")
        elif self.primary and self.primary not in self.backends:
            p.append(f"judge {self.id}: primary {self.primary!r} is not a backend")
        return p


def load_spec(path: Path) -> JudgeSpec:
    text = path.read_text()
    if not text.startswith("---"):
        raise ContractError(f"{path}: a judge needs YAML frontmatter between --- lines")
    try:
        _, front, body = text.split("---", 2)
    except ValueError as e:
        raise ContractError(f"{path}: unterminated frontmatter") from e
    from .util import _Loader

    meta = yaml.load(front, Loader=_Loader) or {}  # noqa: S506 - a SafeLoader
    if not isinstance(meta, dict):
        raise ContractError(f"{path}: frontmatter must be a mapping")
    return JudgeSpec(id=path.stem, path=path, meta=meta, body=body.strip())


# ---- items -----------------------------------------------------------------------------------

def build_input(spec: JudgeSpec, case: dict, start: dict, end: dict) -> dict:
    """The judge's whole view of an item: only the declared input paths."""
    ctx = {"case": {k: v for k, v in case.items() if not k.startswith("_")}, "start": start, "end": end}
    return {path: get_path(ctx, path) for path in spec.meta.get("inputs") or []}


def item_id(spec: JudgeSpec, case_id: str, judge_input: dict) -> str:
    h = hashlib.sha256(json.dumps(judge_input, sort_keys=True, default=str).encode()).hexdigest()[:10]
    return f"{case_id}:{h}"


def render_state(judge_input: dict) -> str:
    parts = []
    for path, value in judge_input.items():
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=1)
        parts.append(f"<{path}>\n{text}\n</{path}>")
    return "\n\n".join(parts)


# ---- verdicts --------------------------------------------------------------------------------

@dataclass
class Judgement:
    backend: str
    model: str
    family: str
    score: float | None  # P(pass)
    answer: object = None
    confidence: float | None = None
    reasoning: str | None = None
    cost_usd: float | None = None
    latency_ms: float | None = None
    tokens_input: int | None = None
    tokens_output: int | None = None
    error: str | None = None
    raw: dict = field(default_factory=dict)

    def passed(self, threshold: float | None) -> bool | None:
        if self.score is None:
            return None
        return self.score >= (0.5 if threshold is None else threshold)

    def as_dict(self) -> dict:
        d = {k: v for k, v in self.__dict__.items() if k != "raw"}
        return d


def _p_pass_from_probs(spec: JudgeSpec, probs: dict) -> float | None:
    m = spec.meta
    if spec.question_type == "choice":
        return float(sum(float(probs.get(o, 0.0)) for o in m.get("pass_options") or []))
    if spec.question_type == "score":
        lo = int(m.get("pass_min_level", 0))
        return float(sum(float(v) for k, v in probs.items() if str(k).isdigit() and int(k) >= lo))
    return None


RATE_LIMIT = re.compile(r"\b429\b|rate.?limit|usage.?limit|quota|too many requests", re.I)


def is_rate_limit(error: str | None) -> bool:
    """A judge error that will repeat for every call until the limit resets."""
    return bool(error and RATE_LIMIT.search(error))


def _noul_to_pass(spec: JudgeSpec, p_yes: float) -> float:
    return 1.0 - p_yes if spec.meta.get("detects") == "failure" else p_yes


def judge(spec: JudgeSpec, backend_name: str, judge_input: dict) -> Judgement:
    cfg = spec.backends.get(backend_name)
    if cfg is None:
        raise JudgeError(f"judge {spec.id} has no backend {backend_name!r}")
    base = {"backend": backend_name, "model": str(cfg.get("model")), "family": str(cfg.get("family"))}
    start = time.monotonic()
    try:
        if cfg["type"] == "systemone":
            j = _systemone(spec, cfg, judge_input, base)
        elif cfg["type"] == "anthropic":
            j = _anthropic(spec, cfg, judge_input, base)
        elif cfg["type"] == "command":
            j = _command(spec, cfg, judge_input, base)
        else:
            raise JudgeError(f"unknown backend type {cfg.get('type')!r}")
    except JudgeError as e:
        j = Judgement(**base, score=None, error=str(e))
    j.latency_ms = round((time.monotonic() - start) * 1000, 1)
    return j


# ---- backend: System One (POST /v1/systemone) -------------------------------------------------

def systemone_question(spec: JudgeSpec) -> dict:
    m = spec.meta
    q = {"type": spec.question_type, "instructions": m["question"]}
    if spec.question_type == "choice":
        q["criteria"] = m["options"]
    elif spec.question_type == "score":
        q["criteria"] = list(m["options"])
    return q


def _systemone(spec: JudgeSpec, cfg: dict, judge_input: dict, base: dict) -> Judgement:
    url = cfg.get("base_url", "https://api.typesafe.ai").rstrip("/") + cfg.get("path", "/v1/systemone")
    state = render_state(judge_input)
    if not state.strip():
        # A System One model answers an empty state with a number (≈0.46), not an error.
        raise JudgeError("empty judge input: refusing to send an empty state")
    body = {"model": cfg["model"], "state": state, "questions": {"q": systemone_question(spec)}}
    # Identify the client honestly: some gateways (Cloudflare error 1010) reject urllib's default
    # "Python-urllib" User-Agent outright.
    headers = {"Content-Type": "application/json", "User-Agent": f"aot-evals/{__version__}",
               **{str(k): str(v) for k, v in (cfg.get("headers") or {}).items()}}
    key_env = cfg.get("api_key_env")
    if key_env:
        key = os.environ.get(key_env)
        if not key:
            raise JudgeError(f"{key_env} is not set")
        headers[cfg.get("auth_header", "Authorization")] = cfg.get("auth_prefix", "Bearer ") + key
    data = _post_json(url, body, headers, timeout=float(cfg.get("timeout", 30)))
    ans = (data.get("answers") or {}).get("q")
    if not isinstance(ans, dict):
        raise JudgeError(f"no answer in response: {str(data)[:200]}")
    usage = data.get("usage") or {}
    tin = usage.get("input_tokens")
    price = float(cfg.get("price_input_per_mtok", SYSTEMONE_PRICE_INPUT_PER_MTOK))
    cost = data.get("cost")
    try:
        cost = float(cost) if cost is not None else (tin * price / 1e6 if tin is not None else None)
    except (TypeError, ValueError):
        cost = tin * price / 1e6 if tin is not None else None
    if spec.question_type == "noul":
        p_yes = float(ans["noul"])
        score, answer = _noul_to_pass(spec, p_yes), p_yes
    else:
        # choice: keyed by option name; score: keyed by level index ("0", "1", ...)
        probs = {str(k): v for k, v in (ans.get("probabilities") or {}).items()}
        score = _p_pass_from_probs(spec, probs)
        answer = ans.get("choice", ans.get("score"))
    return Judgement(**base, score=score, answer=answer, confidence=ans.get("confidence"),
                     cost_usd=cost, tokens_input=tin, tokens_output=usage.get("output_tokens"), raw=data)


def _post_json(url: str, body: dict, headers: dict, timeout: float) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 - configured URL
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:300]
        raise JudgeError(f"HTTP {e.code} from {url}: {detail}") from e
    except (urllib.error.URLError, TimeoutError) as e:
        raise JudgeError(f"cannot reach {url}: {e}") from e
    except json.JSONDecodeError as e:
        raise JudgeError(f"non-JSON response from {url}") from e


# ---- backend: Anthropic Messages API (generative) ---------------------------------------------

JUDGE_SYSTEM = (
    "You are an evaluation judge. You answer exactly one question about the material you are "
    "given, using only that material. Write your reasoning first, then the answer."
)


def _anthropic_schema(spec: JudgeSpec) -> tuple[dict, list[str]]:
    if spec.question_type == "noul":
        options = ["yes", "no"]
    elif spec.question_type == "choice":
        options = list(spec.meta["options"])
    else:
        options = [str(i) for i in range(len(spec.meta["options"]))]
    schema = {
        "type": "object",
        "properties": {"reasoning": {"type": "string"}, "answer": {"type": "string", "enum": options}},
        "required": ["reasoning", "answer"],
        "additionalProperties": False,
    }
    return schema, options


def anthropic_prompt(spec: JudgeSpec, judge_input: dict) -> str:
    m = spec.meta
    lines = [f"Question: {m['question']}"]
    if spec.question_type == "noul":
        lines.append("Answer yes if the statement is true of the material, otherwise no.")
    elif spec.question_type == "choice":
        lines.append("Options:")
        lines += [f"- {k}: {v}" for k, v in m["options"].items()]
    else:
        lines.append("Levels:")
        lines += [f"- {i}: {v}" for i, v in enumerate(m["options"])]
    if spec.body:
        lines += ["", "Guidance:", spec.body]
    lines += ["", "Material:", render_state(judge_input)]
    return "\n".join(lines)


def _anthropic(spec: JudgeSpec, cfg: dict, judge_input: dict, base: dict) -> Judgement:
    try:
        import anthropic
    except ImportError as e:
        raise JudgeError("the anthropic package is not available; run through bin/aot-evals "
                         "(uv provides it)") from e
    schema, _ = _anthropic_schema(spec)
    kwargs = {}
    if cfg.get("api_key_env"):
        key = os.environ.get(cfg["api_key_env"])
        if not key:
            raise JudgeError(f"{cfg['api_key_env']} is not set")
        kwargs["api_key"] = key
    if cfg.get("base_url"):
        kwargs["base_url"] = cfg["base_url"]
    try:
        client = anthropic.Anthropic(**kwargs)
        # No refusal fallbacks: a judge is calibrated per model, so a verdict from a fallback model
        # would be an uncalibrated verdict. A refusal is recorded as an instrument error instead.
        response = client.messages.create(
            model=cfg["model"],
            max_tokens=int(cfg.get("max_tokens", 16000)),
            system=JUDGE_SYSTEM,
            messages=[{"role": "user", "content": anthropic_prompt(spec, judge_input)}],
            output_config={"effort": cfg.get("effort", "medium"),
                           "format": {"type": "json_schema", "schema": schema}},
        )
    except anthropic.RateLimitError as e:
        raise JudgeError(f"rate limited: {e}") from e
    except anthropic.APIStatusError as e:
        raise JudgeError(f"API error {e.status_code}: {e.message}") from e
    except anthropic.APIConnectionError as e:
        raise JudgeError(f"cannot reach the API: {e}") from e
    if response.stop_reason == "refusal":
        cat = getattr(response.stop_details, "category", None) if response.stop_details else None
        raise JudgeError(f"model refused (category {cat})")
    if response.stop_reason == "max_tokens":
        raise JudgeError("hit max_tokens before answering")
    text = next((b.text for b in response.content if b.type == "text"), None)
    try:
        out = json.loads(text or "")
    except json.JSONDecodeError as e:
        raise JudgeError("structured output was not JSON") from e
    ans = str(out.get("answer"))
    if spec.question_type == "noul":
        score = _noul_to_pass(spec, 1.0 if ans == "yes" else 0.0)
    elif spec.question_type == "choice":
        score = 1.0 if ans in (spec.meta.get("pass_options") or []) else 0.0
    else:
        score = 1.0 if int(ans) >= int(spec.meta.get("pass_min_level", 0)) else 0.0
    u = response.usage
    pin, pout = ANTHROPIC_PRICES.get(cfg["model"], (None, None))
    pin = cfg.get("price_input_per_mtok", pin)
    pout = cfg.get("price_output_per_mtok", pout)
    cost = (u.input_tokens * pin + u.output_tokens * pout) / 1e6 if pin is not None and pout is not None else None
    return Judgement(**base, score=score, answer=ans, reasoning=out.get("reasoning"), cost_usd=cost,
                     tokens_input=u.input_tokens, tokens_output=u.output_tokens)


# ---- backend: command (any judge the team runs itself) ---------------------------------------

def command_spec(spec: JudgeSpec) -> dict:
    """What a command judge needs to know which way its answer points. A model that sees only
    the question can answer yes to a failure statement it has just ruled out."""
    m = spec.meta
    out = {"question_type": spec.question_type, "question": m.get("question"),
           "guidance": spec.body or None}
    if spec.question_type == "noul":
        out["detects"] = m.get("detects")
        out["yes_means"] = ("the failure is present: yes is a FAIL" if m.get("detects") == "failure"
                            else "the requirement is met: yes is a PASS")
    elif spec.question_type == "choice":
        out.update(options=m.get("options"), pass_options=m.get("pass_options"))
    else:
        out.update(options=m.get("options"), pass_min_level=m.get("pass_min_level"))
    return out


def _command(spec: JudgeSpec, cfg: dict, judge_input: dict, base: dict) -> Judgement:
    """stdin: {"question": {...systemone-style...}, "state": "...", "input": {...}, "spec": {...},
    "prompt": "..."}; `spec` says what a yes means (detects) and carries the Pass/Fail guidance,
    and `prompt` is the same text a generative backend gets.
    stdout: {"verdict": "pass"|"fail"} (safest: no direction to get wrong) or {"p_pass": 0.83}
    or {"noul": 0.2} / {"probabilities": {...}}, optionally "reasoning", "confidence", "cost",
    "usage": {"tokens_input", "tokens_output"}."""
    cmd = cfg["command"]
    argv = shlex.split(cmd) if isinstance(cmd, str) else [str(x) for x in cmd]
    payload = {"question": systemone_question(spec), "state": render_state(judge_input),
               "input": judge_input, "judge_id": spec.id, "version": spec.version,
               "model": cfg.get("model"), "spec": command_spec(spec),
               "prompt": anthropic_prompt(spec, judge_input)}
    try:
        r = subprocess.run(argv, input=json.dumps(payload), capture_output=True, text=True,
                           timeout=float(cfg.get("timeout", 60)), cwd=str(_repo_root(spec) / cfg.get("cwd", ".")),
                           env=agent_env(cfg.get("env")))
    except subprocess.TimeoutExpired as e:
        raise JudgeError("judge command timed out") from e
    except FileNotFoundError as e:
        raise JudgeError(f"judge command not found: {e}") from e
    start = r.stdout.find("{")
    try:
        out = json.loads(r.stdout[start:]) if start >= 0 else None
    except json.JSONDecodeError:
        out = None
    if not isinstance(out, dict):
        raise JudgeError(f"judge command printed no JSON (exit {r.returncode}): {r.stderr.strip()[:200]}")
    if out.get("error"):
        raise JudgeError(str(out["error"]))
    if "p_pass" in out:
        score = float(out["p_pass"])
    elif "verdict" in out:
        score = 1.0 if str(out["verdict"]).lower() in ("pass", "true", "yes") else 0.0
    elif "noul" in out and spec.question_type == "noul":
        score = _noul_to_pass(spec, float(out["noul"]))
    elif "probabilities" in out:
        score = _p_pass_from_probs(spec, out["probabilities"])
    else:
        raise JudgeError("judge command output has no p_pass, verdict, noul or probabilities")
    usage = out.get("usage") or {}
    return Judgement(**base, score=score, answer=out.get("verdict", out.get("noul")),
                     confidence=out.get("confidence"), reasoning=out.get("reasoning"),
                     cost_usd=float(out["cost"]) if out.get("cost") is not None else None,
                     tokens_input=usage.get("tokens_input"), tokens_output=usage.get("tokens_output"))


def _repo_root(spec: JudgeSpec) -> Path:
    """<suite>/checks/judge/<id>.md -> the repository root; command judges run from there."""
    from .repo import Evals

    return Evals(spec.path.resolve().parents[2]).repo_root


def credentials_missing(cfg: dict) -> str | None:
    env = cfg.get("api_key_env")
    if env and not os.environ.get(env):
        return env
    return None
