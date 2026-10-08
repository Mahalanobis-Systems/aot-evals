"""Pseudonymous milestone telemetry: how many teams use aot-evals, and how far they get.

One event per milestone (Phase 1 started, discovery report written, a checkpoint at a gate, a
report built, the demo run), keyed by a random install id stored locally. It follows Claude
Code's own telemetry choice: anything that turns Claude Code's telemetry off turns this off too.
Nothing about the agent, the repository, the cases or the answers is ever sent; the payload is
built only from the allowlist below. Standard library only: a urllib POST on a daemon thread with
a hard timeout. Telemetry never blocks, slows or breaks a command: every path is wrapped and
failures are swallowed. What's sent, the opt-outs and retention are in SECURITY.md#telemetry.
"""

from __future__ import annotations

import atexit
import json
import os
import platform
import queue
import re
import ssl
import sys
import threading
import urllib.request
import uuid
from datetime import UTC, datetime
from pathlib import Path

from . import __version__

# PostHog capture endpoint and project key. The key is write-only (it can send events, never read
# them), so it ships as a constant. Pinned literals with no override: an overridable URL would be
# a redirect primitive. An empty key means this build sends nothing.
ENDPOINT = "https://us.i.posthog.com/i/v0/e/"
PROJECT_KEY = "phc_rfgtrNeUyCA7GUwknQVKTEcDZfZKbRDKdr9AtHzU8hqL"

EVENTS = frozenset({"phase1_started", "discovery_written", "checkpoint", "report_built", "demo_run"})
_GATE = re.compile(r"^C(?:[0-9]|1[0-8])$")
_TIMEOUT = 1.0  # seconds per send
_FLUSH_BUDGET = 1.0  # seconds, total, at exit

_CI_VARS = ("GITHUB_ACTIONS", "GITLAB_CI", "BUILDKITE", "CIRCLECI", "JENKINS_URL", "TF_BUILD",
            "TEAMCITY_VERSION", "TRAVIS", "APPVEYOR")
# Claude Code turns its own metrics off by default on these providers: mostly enterprises.
_CLOUD_PROVIDER_VARS = ("CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY",
                        "CLAUDE_CODE_USE_ANTHROPIC_AWS")

DISCLOSURE = (
    "aot-evals sends pseudonymous usage telemetry: a random install id, the milestone reached "
    "(Phase 1 started, discovery written, a checkpoint at a gate, a report built), the gate id, "
    "the aot-evals version, your OS name and a timestamp. Never your code, agent, repository, "
    "cases, answers, file paths or IP address. It is off whenever Claude Code's telemetry is off. "
    "See it with `aot-evals telemetry show`; turn it off with `aot-evals telemetry off`, "
    "AOT_EVALS_TELEMETRY=0 or DO_NOT_TRACK=1."
)

_suppressed = False
_sender: _Sender | None = None
_lock = threading.Lock()


def _dir() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "aot-evals"


def _id_path() -> Path:
    return _dir() / "install-id"


def _optout_path() -> Path:
    return _dir() / "telemetry-off"


def _notice_path() -> Path:
    return _dir() / "telemetry-notice-shown"


def _truthy(name: str) -> bool:
    v = os.environ.get(name)
    return v is not None and v.strip().lower() not in {"", "0", "false", "no", "off"}


def why_off() -> str | None:
    """The first reason telemetry is off, or None when it's on."""
    v = os.environ.get("AOT_EVALS_TELEMETRY")
    if v is not None and v.strip().lower() in {"0", "false", "no", "off"}:
        return "AOT_EVALS_TELEMETRY is off"
    if "DO_NOT_TRACK" in os.environ:  # any value, as the convention says
        return "DO_NOT_TRACK is set"
    if _truthy("DISABLE_TELEMETRY"):
        return "Claude Code's telemetry is off (DISABLE_TELEMETRY)"
    if os.environ.get("CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"):
        return "Claude Code's nonessential traffic is off (CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC)"
    for name in _CLOUD_PROVIDER_VARS:
        if _truthy(name):
            return f"Claude Code runs on a cloud provider ({name}), where its telemetry is off"
    if _truthy("CI") or any(n in os.environ for n in _CI_VARS):
        return "running in CI"
    try:
        if _optout_path().exists():
            return "turned off with `aot-evals telemetry off`"
    except OSError:
        return "the settings folder can't be read"
    if not PROJECT_KEY:
        return "this build has no telemetry key"
    return None


def enabled() -> bool:
    return why_off() is None


def suppress() -> None:
    """Send nothing more from this process (the demo runs commands of its own)."""
    global _suppressed
    _suppressed = True


def _read_id() -> str | None:
    try:
        return _id_path().read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def _install_id() -> str | None:
    """The install id, created once with an exclusive create so racing runs agree on one."""
    if (existing := _read_id()) is not None:
        return existing
    try:
        _dir().mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            fd = os.open(_id_path(), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            try:
                os.write(fd, str(uuid.uuid4()).encode())
            finally:
                os.close(fd)
        except FileExistsError:
            pass
        return _read_id()
    except OSError:
        return None


def _notice() -> None:
    """Print the disclosure once, to stderr, before the first event is sent."""
    try:
        if _notice_path().exists():
            return
        print(DISCLOSURE, file=sys.stderr)
        _dir().mkdir(parents=True, exist_ok=True, mode=0o700)
        _notice_path().write_text("")
    except OSError:
        pass


def payload(event: str, install: str, gate: str | None = None) -> dict:
    """The exact event, built only from allowlisted fields."""
    props: dict[str, object] = {"version": __version__, "os": platform.system()}
    if gate and _GATE.match(gate):
        props["gate"] = gate
    props["$ip"] = None  # PostHog: don't record the request IP or derive a location from it
    props["$geoip_disable"] = True
    props["$process_person_profile"] = False  # count events; build no person profile
    return {"api_key": PROJECT_KEY, "event": f"aot_evals_{event}", "distinct_id": install,
            "properties": props, "timestamp": datetime.now(UTC).isoformat()}


def emit(event: str, gate: str | None = None) -> None:
    """Queue one milestone event. Never raises."""
    try:
        if _suppressed or event not in EVENTS or not enabled():
            return
        _notice()
        install = _install_id()
        if install is None:
            return
        _get_sender().submit(json.dumps(payload(event, install, gate)).encode())
    except Exception:  # noqa: BLE001 - telemetry never breaks a command
        pass


class _Sender:
    def __init__(self) -> None:
        self._q: queue.Queue[bytes | None] = queue.Queue()
        self._opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            urllib.request.HTTPSHandler(context=ssl.create_default_context()))
        self._t = threading.Thread(target=self._run, daemon=True)
        self._t.start()

    def submit(self, body: bytes) -> None:
        self._q.put(body)

    def flush(self) -> None:
        self._q.put(None)
        self._t.join(timeout=_FLUSH_BUDGET)

    def _run(self) -> None:
        while (body := self._q.get()) is not None:
            try:
                req = urllib.request.Request(ENDPOINT, data=body, method="POST",
                                             headers={"Content-Type": "application/json"})
                with self._opener.open(req, timeout=_TIMEOUT) as r:
                    r.read()
            except Exception:  # noqa: BLE001 - a dead or blocked endpoint never raises
                pass


def _get_sender() -> _Sender:
    global _sender
    with _lock:
        if _sender is None:
            _sender = _Sender()
            atexit.register(_flush)
        return _sender


def _flush() -> None:
    try:
        if _sender is not None:
            _sender.flush()
    except Exception:  # noqa: BLE001
        pass


# ---- `aot-evals telemetry` ----

def status_text() -> str:
    reason = why_off()
    lines = [f"telemetry: {'on' if reason is None else 'off'}" + (f" ({reason})" if reason else "")]
    lines.append(f"install id: {_read_id() or 'none yet'}")
    lines.append(f"settings: {_dir()}")
    return "\n".join(lines)


def show_text() -> str:
    """The exact event a checkpoint would send. Sends nothing and creates no id."""
    return json.dumps(payload("checkpoint", _read_id() or "<created on the first event>", "C3"), indent=2)


def turn_off() -> None:
    _dir().mkdir(parents=True, exist_ok=True, mode=0o700)
    _optout_path().write_text("")


def turn_on() -> None:
    try:
        _optout_path().unlink()
    except FileNotFoundError:
        pass
