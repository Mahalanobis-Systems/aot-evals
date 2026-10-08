"""What the plugin shows first, and the discovery report page.

The banner and the phase message are printed by the CLI, not written by the model: a model asked
to show ASCII art or a welcome screen often skips it, and a command prints it every time."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from . import brand, markdown

BANNER = r"""
    ___   ____  ______   _______    _____    __   _____
   /   | / __ \/_  __/  / ____/ |  / /   |  / /  / ___/
  / /| |/ / / / / /    / __/  | | / / /| | / /   \__ \
 / ___ / /_/ / / /    / /___  | |/ / ___ |/ /______/ /
/_/  |_\____/ /_/    /_____/  |___/_/  |_/_____/____/

by Mahal Systems
"""

PHASES = """\
I'll build tests for one of your agents in two phases.

Phase 1 (about 5 minutes): discovery and a first report.
  I'll scan this repository to find your agents and ask which one to test.
  Then I'll ask three questions about it, and read its code, tools, records
  and data. You'll get a report with what I found and the likely ways forward.

Phase 2 (an afternoon): building the evals.
  I'll build a safe place to run it, turn real runs into examples, write the
  checks, and run the first full test. I'll only stop for things that could
  touch real people, data or money.
"""


def start_text() -> str:
    return BANNER.lstrip("\n") + "\n" + PHASES


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "agent"


# The overview on the discovery page: what AOT Evals is for, then the four pillars good evals rest on.
VALUE = ("AOT Evals make agent evals simple. Create golden records, safe testing environments, and "
         "repeatable optimization loops to improve cost, quality, and speed of your agent.")

PILLARS = [  # (key in the report's front matter, headline, what it means, tag line)
    ("business_context", "Business context",
     "Why the agent exists, who relies on it, and what a wrong answer costs.", "Goals · stakes · intent"),
    ("agent_architecture", "Agent architecture",
     "Its code, prompts, models and tools, its production setup, and the traces of real runs.",
     "Code · setup · traces"),
    ("safe_testing_env", "Safe testing environment",
     "Runs that can't touch real people, data or money, and are fast and cheap to repeat.",
     "Safe · secure · efficient"),
    ("golden_use_cases", "Golden test cases",
     "Examples drawn from real runs, grouped into the task types the agent actually handles.",
     "Test cases · task types"),
]

# Pillar headings in reports written before 0.1.1, still placed and numbered as their pillar.
OLD_HEADS = {"Safe testing env": "Safe testing environment", "Golden use cases": "Golden test cases"}

STATES = {"done": "✓", "partial": "◐", "risk": "!", "todo": "○"}

# Sections that follow the next steps; every other section sits above them.
AFTER_NEXT = ("Questions for you", "How this run went")


def split_front_matter(text: str) -> tuple[dict, str]:
    """The report's YAML front matter (the overview and next steps) and the markdown after it."""
    m = re.match(r"\s*---\n(.*?)\n---\n", text, re.S)
    if not m:
        return {}, text
    import yaml

    data = yaml.safe_load(m.group(1)) or {}
    return (data if isinstance(data, dict) else {}), text[m.end():]


def _sections(text: str) -> tuple[str, list[tuple[str, str]]]:
    """Markdown cut at its `## ` headings: what comes before the first, then (heading, body)."""
    parts = re.split(r"^## +(.+?)\s*$", text, flags=re.M)
    return parts[0], [(parts[k].strip(), parts[k + 1]) for k in range(1, len(parts), 2)]


def _i(s) -> str:
    return markdown.inline(str(s or ""))


def _overview(fm: dict, agent: str) -> str:
    minutes = fm.get("minutes")
    kicker = "Phase 1 complete" + (f" · {minutes} minutes" if minutes else "")
    stats = "".join(f'<div class="stat"><span class="n">{_i(x.get("value"))}</span>'
                    f'<span class="l">{_i(x.get("label"))}</span></div>'
                    for x in (fm.get("stats") or [])[:3] if isinstance(x, dict))
    bottom = (f'<p class="bottom-line"><b>Bottom line:</b> {_i(fm["bottom_line"])}</p>'
              if fm.get("bottom_line") else "")
    needs = (f'<a class="needs" href="#next">⏳ Needs you: {_i(fm["needs_you"])} ↓</a>'
             if fm.get("needs_you") else "")
    rows = []
    found = fm.get("overview") or {}
    for key, name, meaning, tags in PILLARS:
        p = found.get(key) or {}
        state = p.get("state") if p.get("state") in STATES else "todo"
        rows.append(f"""<article class="pillar">
  <div><h3>{name}</h3><p class="def">{meaning}</p><span class="tags">{tags}</span></div>
  <p class="found">{_i(p.get("found")) or "Not looked at yet."}</p>
  <div class="state"><span class="chip {state}">{STATES[state]} {_i(p.get("label") or state)}</span>
    <p class="open">{_i(p.get("open"))}</p></div>
</article>""")
    return f"""<section class="hero">
  <div>
    <p class="kicker">{kicker}</p>
    <p class="hero-title">Congrats! You just finished Phase 1 of your evals assessment.</p>
    <p class="value">{VALUE}</p>
    {bottom}
  </div>
  <div class="stats">{stats}</div>
</section>
<section class="overview">
  <div class="overview-head"><p class="kicker">Overview</p>{needs}</div>
  {"".join(rows)}
</section>"""


def _next(fm: dict) -> str:
    nx = fm.get("next") or {}
    if not nx:
        return ""
    steps = []
    for st in nx.get("steps") or []:
        you = st.get("who") == "you"
        steps.append(f'<li class="{"you" if you else "us"}"><div><span class="t">{_i(st.get("title"))}</span>'
                     f'<span class="who">{"You" if you else "Phase 2"}</span>'
                     f'<div class="d">{_i(st.get("detail"))}</div></div>'
                     f'<div class="when">{_i(st.get("when"))}</div></li>')
    alts = "".join(f'<p><b>{_i(a.get("name"))}.</b> {_i(a.get("why"))}</p>'
                   for a in nx.get("other_paths") or [])
    alts = f'<div class="alt"><p>Other paths we considered:</p>{alts}</div>' if alts else ""
    return f"""<section class="next" id="next">
  <p class="kicker">Next steps</p>
  <h2>{_i(nx.get("path"))}</h2>
  <p class="path">{_i(nx.get("why"))}</p>
  <ol class="steps">{"".join(steps)}</ol>
  <div class="cta"><code>/aot-evals:start</code>
    <span>Run it again to begin Phase 2. It takes about an afternoon.</span></div>
  {alts}
</section>"""


def discovery_body(fm: dict, text: str, agent: str) -> str:
    """The discovery page's body. With front matter (`fm`): the overview (congrats, value, the four
    pillars with what discovery found), the details grouped by pillar, then the next steps. Without
    it, the markdown as written."""
    if not fm:
        return markdown.render(text)
    lead, secs = _sections(text)
    names = [p[1] for p in PILLARS]
    before, after = [], []
    rank = {n: k for k, n in enumerate(names)}  # the four pillars in their order, then the rest as written
    secs = sorted(secs, key=lambda hb: rank.get(OLD_HEADS.get(hb[0], hb[0]), len(names)))
    for head, body in secs:
        pillar = OLD_HEADS.get(head, head)
        if pillar in names:
            num = f'<span class="num">{names.index(pillar) + 1:02d}</span> '
            before.append(f'<section class="detail-group" id="{slug(head)}"><h2>{num}{markdown.inline(head)}</h2>'
                          f"{markdown.render(body)}</section>")
        else:
            group = after if head in AFTER_NEXT else before
            group.append(f'<section class="detail-group" id="{slug(head)}"><h2>{markdown.inline(head)}</h2>'
                         f"{markdown.render(body)}</section>")
    details = ('<p class="kicker details-head">The details</p>' + "".join(before)) if before else ""
    return (_overview(fm, agent) + (markdown.render(lead) if lead.strip() else "") + details
            + _next(fm) + "".join(after))


def write_discovery_page(markdown_path: Path, agent: str, out_dir: Path) -> Path:
    """Render a discovery report (markdown) into the branded HTML page next to it."""
    fm, text = split_front_matter(markdown_path.read_text())
    title = agent
    m = re.match(r"\s*#\s+(.+)\n", text)
    if m:  # the page owns the title; drop the markdown's own h1
        title = m.group(1).strip()
        text = text[m.end():]
    body = discovery_body(fm, text, agent)
    # The subtitle says when and where, not the title again.
    parts = markdown_path.resolve().parts
    repo = parts[-5] if len(parts) >= 5 and parts[-4:-2] == ("evals", "agents") else ""
    sub = " · ".join(x for x in (brand.human_date(date.today().isoformat()), repo) if x)
    html = brand.page(title=title, eyebrow="AOT EVALS · PHASE 1 · DISCOVERY", sub=sub, body=body)
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "discovery.html"
    out.write_text(html)
    return out
