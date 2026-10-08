"""What a new user runs first: `aot-evals demo` and `aot-evals doctor`."""

from __future__ import annotations

import json

import pytest

from aot_evals import cli


def test_demo_runs_the_whole_loop_without_forcing_a_gate(tmp_path, capsys):
    dest = tmp_path / "demo"
    assert cli.main(["demo", str(dest)]) == 0
    suite = dest / "evals/agents/calendar"
    runs = [json.loads(p.read_text()) for p in (suite / "runs").glob("*/manifest.json")]
    assert sorted(m["purpose"] for m in runs) == ["baseline", "candidate", "smoke"]
    assert all(m["finished"] and not m["forced_past_gates"] for m in runs)
    comparison = json.loads(next((suite / "report/comparisons").glob("*.json")).read_text())
    assert comparison["losses"] == ["book-002", "book-003"] and comparison["refused"] is None
    assert (suite / "report/report.json").exists() and list((suite / "report/checkpoints").glob("*.html"))
    assert "Demo ready" in capsys.readouterr().out


def test_demo_refuses_a_folder_that_is_not_empty(tmp_path):
    (tmp_path / "keep.txt").write_text("mine\n")
    with pytest.raises(SystemExit, match="not empty"):
        cli.main(["demo", str(tmp_path)])
    assert (tmp_path / "keep.txt").read_text() == "mine\n"


def test_doctor_reports_the_environment_and_never_a_secret(make_repo, monkeypatch, capsys):
    repo = make_repo()
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-secret-value")
    (repo.evals / "checks/judge").mkdir(parents=True, exist_ok=True)
    (repo.evals / "checks/judge/j.md").write_text(
        "---\nid: j\nfailure_mode: x\nversion: 1\nquestion_type: noul\nquestion: q\ndetects: pass\n"
        "inputs: [end.output]\nbackends:\n  claude: {type: anthropic, model: m, family: anthropic}\n---\n")
    capsys.readouterr()
    assert cli.main(["--evals", str(repo.evals), "doctor"]) == 0
    out = capsys.readouterr().out
    assert "aot-evals" in out and "suite" in out and "invoke.cwd" in out
    assert "ANTHROPIC_API_KEY is set" in out and "sk-ant-secret-value" not in out


REPORT = """---
minutes: 6
bottom_line: It is <b>mostly</b> ready.
stats:
  - {value: "412", label: past runs}
needs_you: Approve the plan
overview:
  safe_testing_env: {found: Runs as admin., state: risk, label: Not safe yet, open: Block email}
next:
  path: Make it safe first
  why: A fair test.
  steps:
    - {who: you, title: Approve the plan, detail: "[Read it](#safe-testing-environment)", when: 5 minutes}
    - {who: us, title: Block outside tools, detail: Email and web.}
  other_paths:
    - {name: Baseline now, why: Quick but weak.}
---
# Pizza bot (pizza-bot)

## How this run went

Fast.

## Golden test cases

Orders.

## Business context

Goals table.
"""


def test_discovery_page_puts_the_overview_first_and_the_next_steps_last(tmp_path):
    from aot_evals.start import write_discovery_page

    src = tmp_path / "evals/agents/pizza-bot/discovery.md"
    src.parent.mkdir(parents=True)
    src.write_text(REPORT)
    html = write_discovery_page(src, "pizza-bot", src.parent).read_text()
    assert "<title>Pizza bot (pizza-bot)</title>" in html
    assert "minutes: 6" not in html  # the front matter is data, never shown as text
    assert "&lt;b&gt;mostly&lt;/b&gt;" in html  # values are escaped
    order = [html.index(s) for s in (
        "Congrats!", "AOT Evals make agent evals simple", ">Overview<", "Business context</h3>",
        "Golden test cases</h3>", 'id="business-context"', 'id="golden-test-cases"', 'id="next"',
        'id="how-this-run-went"')]
    assert order == sorted(order)
    assert 'chip risk' in html and "Not safe yet" in html
    assert "Not looked at yet." in html  # a pillar the report left out still shows
    assert 'class="you"' in html and "/aot-evals:start" in html and "Baseline now" in html


def test_discovery_page_still_places_pillar_headings_from_0_1_0(tmp_path):
    from aot_evals.start import write_discovery_page

    src = tmp_path / "evals/agents/pizza-bot/discovery.md"
    src.parent.mkdir(parents=True)
    src.write_text(REPORT.replace("## Golden test cases", "## Golden use cases")
                   + "\n## Safe testing env\n\nFakes.\n")
    html = write_discovery_page(src, "pizza-bot", src.parent).read_text()
    assert 'id="safe-testing-env"><h2><span class="num">03</span> Safe testing env</h2>' in html
    assert 'id="golden-use-cases"><h2><span class="num">04</span> Golden use cases</h2>' in html
    assert html.index('id="safe-testing-env"') < html.index('id="golden-use-cases"') < html.index('id="next"')


def test_discovery_page_without_front_matter_renders_the_markdown_as_written(tmp_path):
    from aot_evals.start import write_discovery_page

    src = tmp_path / "discovery.md"
    src.write_text("# Old bot (old)\n\n## Goals\n\nSome goals.\n")
    html = write_discovery_page(src, "old", tmp_path).read_text()
    assert "Some goals." in html and 'class="hero"' not in html
