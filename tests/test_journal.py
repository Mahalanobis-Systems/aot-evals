"""The activity log (docs/method.md §4), shared by an agent system's evals, and the markdown its
pages render."""

from __future__ import annotations

import re
import subprocess

from aot_evals import journal


def kinds(ev) -> list[str]:
    return [e["kind"] for e in journal.entries(ev)]


def no_network(html: str) -> bool:
    """Self-contained: nothing is fetched. The wordmark's link is a link, not a request."""
    return not re.search(r'(src|href)="(https?:)?//(?!mahalsystems\.ai)', html) and "<link" not in html


def test_every_command_logs_itself_and_reads_do_not(store_repo):
    s = store_repo
    logged = journal.entries(s.ev())
    assert [e["text"].split()[1:4] for e in logged] == [
        ["--eval", "end-to-end", "import"], ["--eval", "refund-subagent", "handoffs"],
        ["--eval", "end-to-end", "screen"], ["--eval", "refund-subagent", "screen"]]
    assert all("--evals" not in e["text"] for e in logged)
    assert logged[0]["gate"] == "C0" and logged[-1]["gate"] == "C7" and logged[-1]["exit"] == 0
    # one log for the agent system, whichever eval a command worked on
    assert journal.log_path(s.ev("refund-subagent")) == journal.log_path(s.ev()) == \
        s.agent / "journal" / "activity.jsonl"

    n = len(logged)
    assert s.cli("status") == 0 and s.cli("validate") in (0, 1)
    assert len(journal.entries(s.ev())) == n  # reads leave no trace


def test_an_incomplete_spec_is_noted_not_refused(store_repo, capsys):
    """Nothing blocks a run on a spec field it lacks (docs/v2-design.md §5): the run goes ahead,
    the note names the field, the manifest records it, and the command logs itself with exit 0."""
    s = store_repo
    spec = s.agent / "end-to-end" / "eval.yaml"
    spec.write_text(spec.read_text().replace("eval: end-to-end\n", "eval: e2e\n", 1))
    capsys.readouterr()
    assert s.cli("run", "--purpose", "baseline", "--use-case", "address") == 0
    assert "note: eval: says 'e2e'" in capsys.readouterr().err
    assert s.ev().latest_run("baseline")["spec_issues"] == ["eval"]
    last = journal.entries(s.ev())[-1]
    assert last["kind"] == "command" and last["exit"] == 0 and last["gate"] == "C12"


def test_a_run_streams_progress_and_collapses_it(store_repo):
    s = store_repo
    assert s.cli("run", "--purpose", "baseline", "--use-case", "address") == 0
    ks = kinds(s.ev())
    assert ks[-1] == "command" and "progress" in ks and "step" in ks  # started, progress, finished
    html = journal.html_path(s.ev()).read_text()
    assert html.count('class="k-progress"') == 1 and "progress lines" in html
    assert "Activity for store" in html and no_network(html)


def test_a_question_waits_for_the_person_until_the_work_resumes(store_repo):
    s = store_repo
    assert s.cli("log", "Is a refund on day 30 inside the window?", "--kind", "question") == 0
    html = journal.html_path(s.ev()).read_text()
    assert "waiting for" in html and "asked you a question" in html and no_network(html)
    assert s.cli("log", "The owner says yes; carrying on") == 0
    assert "waiting for" not in journal.html_path(s.ev()).read_text()


def test_a_decision_on_an_eval_records_its_spec(store_repo):
    s = store_repo
    assert s.cli("log", "refunds count 50 times an order-status failure", "--kind", "decision",
                 "--by", "owner") == 0
    last = journal.entries(s.ev())[-1]
    assert last["kind"] == "decision" and last["by"] == "owner" and last["eval"] == "end-to-end"
    assert last["spec_sha"]
    assert "by owner" in journal.html_path(s.ev()).read_text()


def test_the_log_never_enters_git(store_repo):
    s = store_repo
    out = subprocess.run(["git", "status", "--porcelain", "--untracked-files=all"], cwd=s.root,
                         capture_output=True, text=True, check=True).stdout
    assert (s.agent / "journal" / "activity.jsonl").exists()
    assert "journal/" not in out


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
