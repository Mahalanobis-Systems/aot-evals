"""Checkpoints and the activity log (docs/method.md §9)."""

from __future__ import annotations

import re
import subprocess

from aot_evals import journal
from aot_evals.repo import Evals


def kinds(ev: Evals) -> list[str]:
    return [e["kind"] for e in journal.entries(ev)]


def no_network(html: str) -> bool:
    """Self-contained: nothing is fetched. The wordmark's link is a link, not a request."""
    return not re.search(r'(src|href)="(https?:)?//(?!mahalsystems\.ai)', html) and "<link" not in html


def test_every_command_logs_itself_and_reads_do_not(make_repo):
    repo = make_repo()
    ev = Evals(repo.evals)
    logged = journal.entries(ev)
    assert [e["text"].split()[1] for e in logged] == ["import", "screen", "allocate"]
    assert all("--evals" not in e["text"] for e in logged)
    assert logged[0]["gate"] == "C0" and logged[-1]["gate"] == "C5" and logged[-1]["exit"] == 0

    n = len(logged)
    assert repo.cli("status") == 0 and repo.cli("validate") in (0, 1)
    assert len(journal.entries(ev)) == n  # reads leave no trace


def test_refusals_are_logged_with_their_reason(make_repo):
    repo = make_repo()
    ev = Evals(repo.evals)
    try:
        repo.cli("run", "--purpose", "baseline", "--k", "3")  # C1 is unmet: refused
    except SystemExit:
        pass
    last = journal.entries(ev)[-1]
    assert last["kind"] == "command" and last["exit"] == 1 and last["gate"] == "C12"
    assert last["detail"].startswith("refused: C12 baseline needs C1")


def test_a_run_streams_progress_and_collapses_it(make_repo):
    repo = make_repo()
    ev = Evals(repo.evals)
    assert repo.cli("run", "--purpose", "baseline", "--k", "3", "--force") == 0
    ks = kinds(ev)
    assert ks[-1] == "command" and "progress" in ks and "step" in ks  # started, progress, finished
    html = journal.html_path(ev).read_text()
    assert html.count('class="k-progress"') == 1 and "progress lines" in html


def test_checkpoint_renders_the_design_and_waits_for_the_owner(make_repo):
    repo = make_repo()
    ev = Evals(repo.evals)
    assert repo.cli("log", "Grouping traces by request", "--gate", "C3") == 0
    assert repo.cli("log", "book-meeting is 60% of traffic", "--kind", "decision", "--by", "owner",
                    "--gate", "C3") == 0
    assert repo.cli("checkpoint", "--gate", "C3", "--summary", "Sorted <b>traces</b>.\n\n- two categories",
                    "--ask", "Is `nothing-to-do` really simple?", "--ask", "Merge any categories?") == 0

    pages = sorted((repo.evals / "report" / "checkpoints").glob("*.html"))
    assert [p.name[:7] for p in pages] == ["001-C3-"]
    html = pages[0].read_text()
    assert "Sort real traffic into categories" in html            # the plain-language guide
    assert "&lt;b&gt;traces&lt;/b&gt;" in html and "<li>two categories</li>" in html  # escaped prose
    assert "<code>nothing-to-do</code>" in html and "Merge any categories?" in html
    for artifact in ("C0 · Imported traffic", "C1 · The agent", "C3 · Categories", "C4 · How it can fail",
                     "C5 · How many cases", "C6–C7 · Test cases", "C8 · Checks"):
        assert artifact in html, artifact
    assert "60.0%" in html and "0.004" in html  # shares as percentages, budgets as written
    assert "book-meeting is 60% of traffic" in html  # the log since the last checkpoint
    assert no_network(html)

    last = journal.entries(ev)[-1]
    assert last["kind"] == "milestone" and last["gate"] == "C3"
    assert last["path"] == f"report/checkpoints/{pages[0].name}"
    assert {g["id"] for g in last["gates"]} >= {"C0", "C18"}
    activity = journal.html_path(ev).read_text()
    assert "waiting for" in activity and f"../report/checkpoints/{pages[0].name}" in activity
    assert no_network(activity)

    # Once Claude picks the work back up, the banner goes, and the next page only shows new entries.
    assert repo.cli("log", "Applying the owner's answers") == 0
    assert "waiting for" not in journal.html_path(ev).read_text()
    assert repo.cli("checkpoint") == 0  # defaults to the next unmet gate
    second = sorted((repo.evals / "report" / "checkpoints").glob("*.html"))[-1]
    assert second.name.startswith("002-C1-")
    text = second.read_text()
    assert "Applying the owner" in text and "book-meeting is 60% of traffic" not in text


def test_the_log_never_enters_git(make_repo):
    repo = make_repo()
    out = subprocess.run(["git", "status", "--porcelain", "--untracked-files=all"], cwd=repo.root,
                         capture_output=True, text=True, check=True).stdout
    assert (repo.evals / "journal" / "activity.jsonl").exists()
    assert "journal/" not in out


def test_unknown_gate_is_refused(make_repo):
    repo = make_repo()
    assert repo.cli("checkpoint", "--gate", "C99") == 2


def test_summary_markdown_renders():
    from aot_evals.markdown import render

    html = render("## What this work is\n\nAn eval suite for *this* agent, the **RAG** one.\n"
                  "Keep `nothing_to_do` and snake_case_names; 2 * 3 * 4 stays.\n\n"
                  "1. First\n   continued\n2. Second _step_\n- a bullet\n\n"
                  "[method](docs/method.md) [bad](javascript:alert(1)) <b>raw</b>")
    assert "<h3>What this work is</h3>" in html and "##" not in html
    assert "<em>this</em>" in html and "<strong>RAG</strong>" in html
    assert "<code>nothing_to_do</code>" in html and "snake_case_names" in html and "2 * 3 * 4" in html
    assert "<ol><li>First\ncontinued</li><li>Second <em>step</em></li></ol>\n<ul><li>a bullet</li></ul>" in html
    assert '<a href="docs/method.md">method</a>' in html and 'href="javascript' not in html
    assert "&lt;b&gt;raw&lt;/b&gt;" in html


def test_summary_markdown_spans_code_and_lines_and_renders_tables():
    """Bold around inline code, wrapped over two lines, and a pipe table must all render, not
    show as literal markdown."""
    from aot_evals.markdown import render

    html = render("**So the `.json` replies were not malformed: the parser dropped\nthem.** That matters.\n\n"
                  "| | support | billing |\n|---|---:|---:|\n| Reply parsed | 92.0% | 85.5% |\n"
                  "| Pipe in code `a|b` | 1.6% | 3.1% |\n")
    assert "**" not in html and "|---" not in html
    assert "<strong>So the <code>.json</code> replies were not malformed: the parser dropped\nthem.</strong>" in html
    assert '<th style="text-align:right">support</th>' in html
    assert '<td>Reply parsed</td><td style="text-align:right">92.0%</td>' in html
    assert "<td>Pipe in code <code>a|b</code></td>" in html


def test_summary_markdown_blocks():
    from aot_evals.markdown import inline, render

    html = render("Intro\n---\n- a\n  - nested ~~old~~\n- b\n\n> quoted **bold**\n\n"
                  "```python\nx = \"**no**\" < 3\n```\n\n3) three\n4) four\n\n"
                  "***both*** \\*lit\\* see https://x.io/a?b=1&c=2.\nhard  \nbreak")
    assert "<p>Intro</p>\n<hr>" in html
    assert "<ul><li>a\n<ul><li>nested <del>old</del></li></ul></li><li>b</li></ul>" in html
    assert "<blockquote><p>quoted <strong>bold</strong></p></blockquote>" in html
    assert '<pre><code class="language-python">x = &quot;**no**&quot; &lt; 3</code></pre>' in html
    assert '<ol start="3"><li>three</li><li>four</li></ol>' in html
    assert "<strong><em>both</em></strong> *lit*" in html
    assert '<a href="https://x.io/a?b=1&amp;c=2">https://x.io/a?b=1&amp;c=2</a>.' in html
    assert "hard<br>\nbreak" in html
    assert inline("**[ask](a.html)** with `` a ` tick ``") == \
        '<strong><a href="a.html">ask</a></strong> with <code>a ` tick</code>'
