"""Telemetry: off whenever Claude Code's is, only allowlisted fields, never breaks a command."""

from __future__ import annotations

import json

import pytest

from aot_evals import cli, telemetry

OFF_SWITCHES = [
    ("AOT_EVALS_TELEMETRY", "0"),
    ("DO_NOT_TRACK", "0"),  # presence is enough, whatever the value
    ("DISABLE_TELEMETRY", "1"),
    ("CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC", "1"),
    ("CLAUDE_CODE_USE_BEDROCK", "1"),
    ("CLAUDE_CODE_USE_VERTEX", "1"),
    ("CLAUDE_CODE_USE_FOUNDRY", "1"),
    ("CI", "true"),
    ("GITHUB_ACTIONS", "true"),
]
ALL_SWITCHES = [name for name, _ in OFF_SWITCHES] + ["CLAUDE_CODE_USE_ANTHROPIC_AWS", "GITLAB_CI", "BUILDKITE",
                                                    "CIRCLECI", "JENKINS_URL", "TF_BUILD", "TEAMCITY_VERSION",
                                                    "TRAVIS", "APPVEYOR"]


@pytest.fixture
def sent(monkeypatch):
    """Telemetry switched on, with a fake sender that records each event instead of sending it."""
    for name in ALL_SWITCHES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(telemetry, "_suppressed", False)
    events: list[dict] = []

    class Fake:
        def submit(self, body: bytes) -> None:
            events.append(json.loads(body))

    monkeypatch.setattr(telemetry, "_get_sender", lambda: Fake())
    return events


@pytest.mark.parametrize("name,value", OFF_SWITCHES)
def test_every_off_switch_sends_nothing(sent, monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    assert not telemetry.enabled()
    telemetry.emit("phase1_started")
    assert sent == []


def test_off_command_sends_nothing_and_on_restores_it(sent, capsys):
    assert telemetry.enabled()
    cli.main(["telemetry", "off"])
    assert "off (turned off" in capsys.readouterr().out
    telemetry.emit("phase1_started")
    assert sent == []
    cli.main(["telemetry", "on"])
    telemetry.emit("phase1_started")
    assert len(sent) == 1


def test_an_event_carries_only_the_allowlist(sent):
    telemetry.emit("checkpoint", gate="C3")
    telemetry.emit("checkpoint", gate="../../etc/passwd")  # anything but a gate id is dropped
    first, second = sent
    assert set(first) == {"api_key", "event", "distinct_id", "properties", "timestamp"}
    assert first["event"] == "aot_evals_checkpoint"
    assert set(first["properties"]) == {"version", "os", "gate", "$ip", "$geoip_disable",
                                        "$process_person_profile"}
    assert first["properties"]["gate"] == "C3" and first["properties"]["$ip"] is None
    assert "gate" not in second["properties"]
    assert first["distinct_id"] == second["distinct_id"]  # one install id, kept


def test_unknown_events_are_never_sent(sent):
    telemetry.emit("prompt_text")
    assert sent == []


def test_the_notice_shows_once_before_the_first_event(sent, capsys):
    telemetry.emit("phase1_started")
    telemetry.emit("discovery_written")
    err = capsys.readouterr().err
    assert err.count("pseudonymous usage telemetry") == 1


def test_a_successful_command_sends_its_milestone(sent, capsys):
    assert cli.main(["start"]) == 0
    assert [e["event"] for e in sent] == ["aot_evals_phase1_started"]


def test_a_broken_sender_never_breaks_a_command(sent, monkeypatch, capsys):
    def boom():
        raise RuntimeError("network down")

    monkeypatch.setattr(telemetry, "_get_sender", boom)
    assert cli.main(["start"]) == 0


def test_show_prints_the_event_and_sends_nothing(sent, capsys):
    assert cli.main(["telemetry", "show"]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["event"] == "aot_evals_checkpoint" and sent == []
    assert not telemetry._id_path().exists()  # showing creates no id
