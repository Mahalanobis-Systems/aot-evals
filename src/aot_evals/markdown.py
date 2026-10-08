"""The markdown Claude writes on checkpoint pages: summaries (`--summary-file`) and asks.

A GitHub-flavoured subset, standard library only (runtime code may not depend on a markdown
package). Blocks: ATX and setext headings, paragraphs with hard breaks, `-`/`*`/`+` and `1.`/`1)`
lists nested by indentation, `>` quotes, fenced code, pipe tables and rules (`---` under a line
is a rule, not a heading, since that is what Claude means by it). Inline: code spans,
links and autolinks, bold, italics, bold-italics and strikethrough, which may span code and
links, and backslash escapes. Everything is escaped first, so raw HTML shows as text, and a
delimiter with no partner stays the character it is.
"""

from __future__ import annotations

import re

_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})\s*([^`\s]*)[^`]*$")
_HEADING = re.compile(r"^ {0,3}(#{1,6})(?:\s+(.*?))?(?:\s+#+)?\s*$")
_RULE = re.compile(r"^ {0,3}(?:(?:\*\s*){3,}|(?:-\s*){3,}|(?:_\s*){3,})$")
_ITEM = re.compile(r"^( *)([-*+]|\d{1,9}[.)])(?:[ \t]+(.*))?$")
_QUOTE = re.compile(r"^ {0,3}> ?(.*)$")
_DELIM_ROW = re.compile(r"^\s*\|?\s*:?-+:?\s*(?:\|\s*:?-+:?\s*)*\|?\s*$")
_SETEXT = re.compile(r"^ {0,3}=+\s*$")  # `---` under a line is a rule, not a heading


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def render(text: str) -> str:
    """Block-level markdown to HTML. Headings become h3 (h4 from `####`): the page owns h1-h2."""
    lines = text.replace("\x01", "").expandtabs(4).replace("\r\n", "\n").replace("\r", "\n").strip("\n").split("\n")
    return "\n".join(_blocks(lines))


# ---- blocks --------------------------------------------------------------------------------

def _starts_block(lines: list[str], i: int) -> bool:
    """Whether line i opens a block that interrupts a paragraph."""
    s = lines[i]
    if _FENCE.match(s) or _RULE.match(s) or _QUOTE.match(s) or _is_table(lines, i):
        return True
    if (m := _HEADING.match(s)) and (m.group(2) or s.strip() == m.group(1)):
        return True
    m = _ITEM.match(s)
    return bool(m and m.group(3) and (not m.group(2)[0].isdigit() or int(m.group(2)[:-1]) == 1))


def _blocks(lines: list[str]) -> list[str]:
    out: list[str] = []
    i, n = 0, len(lines)
    while i < n:
        s = lines[i]
        if not s.strip():
            i += 1
            continue
        if m := _FENCE.match(s):
            fence, lang = m.group(1), m.group(2)
            indent = len(s) - len(s.lstrip(" "))
            body, i = [], i + 1
            while i < n and not re.match(rf"^ {{0,3}}{re.escape(fence[0])}{{{len(fence)},}}\s*$", lines[i]):
                body.append(lines[i][min(indent, len(lines[i]) - len(lines[i].lstrip(" "))):])
                i += 1
            i += 1
            cls = f' class="language-{_esc(lang)}"' if lang else ""
            out.append(f"<pre><code{cls}>{_esc(chr(10).join(body))}</code></pre>")
            continue
        if (m := _HEADING.match(s)) and (m.group(2) is not None or s.strip() == m.group(1)):
            tag = "h3" if len(m.group(1)) <= 3 else "h4"
            out.append(f"<{tag}>{inline(m.group(2) or '')}</{tag}>")
            i += 1
            continue
        if _RULE.match(s):
            out.append("<hr>")
            i += 1
            continue
        if _QUOTE.match(s):
            body = []
            while i < n and lines[i].strip():
                q = _QUOTE.match(lines[i])
                body.append(q.group(1) if q else lines[i])  # lazy continuation
                i += 1
            out.append("<blockquote>" + "\n".join(_blocks(body)) + "</blockquote>")
            continue
        if _is_table(lines, i):
            i = _table(lines, i, out)
            continue
        if _ITEM.match(s):
            i = _list(lines, i, out)
            continue
        para = [s]
        i += 1
        while i < n and lines[i].strip() and not _starts_block(lines, i) and not _SETEXT.match(lines[i]):
            para.append(lines[i])
            i += 1
        if i < n and _SETEXT.match(lines[i]):
            out.append(f"<h3>{inline(' '.join(p.strip() for p in para))}</h3>")
            i += 1
            continue
        out.append(f"<p>{_para(para)}</p>")
    return out


def _para(lines: list[str]) -> str:
    """Lines of one paragraph, formatted together so emphasis can span them. Two trailing
    spaces or a trailing backslash is a hard break."""
    parts = []
    for k, line in enumerate(lines):
        brk = k < len(lines) - 1 and (line.endswith("  ") or line.rstrip(" ").endswith("\\"))
        line = line.strip()
        if brk and line.endswith("\\"):
            line = line[:-1].rstrip()
        parts.append(line + ("\x01" if brk else ""))
    return inline("\n".join(parts)).replace("\x01", "<br>")


def _list(lines: list[str], i: int, out: list[str]) -> int:
    """One list: items share the marker kind; an item owns the lines indented past its marker,
    blank lines between them, and unindented lines that continue its paragraph."""
    first = _ITEM.match(lines[i])
    ordered = first.group(2)[0].isdigit()
    sep = first.group(2)[-1] if ordered else first.group(2)
    base = len(first.group(1))
    items: list[list[str]] = []
    loose = False
    n = len(lines)
    while i < n:
        m = _ITEM.match(lines[i])
        if not m or len(m.group(1)) > base + 3 or len(m.group(1)) < base:
            break
        if m.group(2)[0].isdigit() != ordered or (m.group(2)[-1] if ordered else m.group(2)) != sep:
            break
        if _RULE.match(lines[i]):
            break
        content = len(m.group(1)) + len(m.group(2)) + 1
        body = [m.group(3) or ""]
        i += 1
        blank = False
        while i < n:
            line = lines[i]
            if not line.strip():
                blank = True
                body.append("")
                i += 1
                continue
            ind = len(line) - len(line.lstrip(" "))
            if ind > base:
                body.append(line[min(ind, content):])
                blank = False
                i += 1
                continue
            if blank or _ITEM.match(line) or _starts_block(lines, i):
                break
            body.append(line.strip())  # lazy continuation of the item's paragraph
            i += 1
        while body and not body[-1].strip():
            body.pop()
            if i < n and _ITEM.match(lines[i]):
                loose = True
        if any(not b.strip() for b in body):
            loose = True
        items.append(body)
    start = ""
    if ordered and (k := int(first.group(2)[:-1])) != 1:
        start = f' start="{k}"'
    tag = "ol" if ordered else "ul"
    lis = []
    for body in items:
        inner = _blocks(body)
        if not loose:
            inner = [b[3:-4] if b.startswith("<p>") and b.endswith("</p>") else b for b in inner]
        lis.append("<li>" + "\n".join(inner) + "</li>")
    out.append(f"<{tag}{start}>" + "".join(lis) + f"</{tag}>")
    return i


def _is_table(lines: list[str], i: int) -> bool:
    return (i + 1 < len(lines) and "|" in lines[i] and "-" in lines[i + 1]
            and bool(_DELIM_ROW.match(lines[i + 1]))
            and len(_cells(lines[i])) == len(_cells(lines[i + 1])))


def _cells(row: str) -> list[str]:
    """Split a table row on pipes that are neither escaped nor inside a code span."""
    row = row.strip()
    if row.startswith("|"):
        row = row[1:]
    if row.endswith("|") and not row.endswith("\\|"):
        row = row[:-1]
    cells, cur, tick, k = [], [], 0, 0
    while k < len(row):
        c = row[k]
        if c == "\\" and k + 1 < len(row) and row[k + 1] == "|":
            cur.append("|")
            k += 2
            continue
        if c == "`":
            run = len(row[k:]) - len(row[k:].lstrip("`"))
            tick = 0 if tick == run else (run if tick == 0 else tick)
            cur.append("`" * run)
            k += run
            continue
        if c == "|" and not tick:
            cells.append("".join(cur).strip())
            cur = []
        else:
            cur.append(c)
        k += 1
    cells.append("".join(cur).strip())
    return cells


def _table(lines: list[str], i: int, out: list[str]) -> int:
    head = _cells(lines[i])
    align = []
    for d in _cells(lines[i + 1]):
        left, right = d.startswith(":"), d.endswith(":")
        align.append("center" if left and right else "right" if right else "left" if left else "")
    i += 2
    rows = []
    while i < len(lines) and lines[i].strip() and "|" in lines[i] and not _starts_block_not_table(lines, i):
        cells = _cells(lines[i])
        rows.append((cells + [""] * len(head))[:len(head)])
        i += 1

    def cell(tag: str, text: str, a: str) -> str:
        style = f' style="text-align:{a}"' if a else ""
        return f"<{tag}{style}>{inline(text)}</{tag}>"

    th = "".join(cell("th", h, a) for h, a in zip(head, align, strict=True))
    body = "".join("<tr>" + "".join(cell("td", c, a) for c, a in zip(r, align, strict=True)) + "</tr>" for r in rows)
    out.append(f'<div class="wrap"><table class="md"><thead><tr>{th}</tr></thead>'
               f"<tbody>{body}</tbody></table></div>")
    return i


def _starts_block_not_table(lines: list[str], i: int) -> bool:
    s = lines[i]
    return bool(_FENCE.match(s) or _HEADING.match(s) or _QUOTE.match(s))


# ---- inline --------------------------------------------------------------------------------

_PH = "\x00{}\x00"
_PH_RE = re.compile("\x00(\\d+)\x00")


def inline(s: str) -> str:
    """Inline markdown to HTML. Code spans, escapes and links are set aside as placeholders
    first, so emphasis can wrap them but nothing inside them is read as emphasis."""
    held: list[str] = []

    def hold(html: str) -> str:
        held.append(html)
        return _PH.format(len(held) - 1)

    s = s.replace("\x00", "")
    # code spans: a run of n backticks closes only on a run of exactly n
    s = re.sub(r"(?<!`)(`+)(?!`)(.+?)(?<!`)\1(?!`)",
               lambda m: hold(f"<code>{_esc(_strip_code(m.group(2)))}</code>"), s, flags=re.S)
    s = re.sub(r"\\([\\`*_{}\[\]()#+\-.!|~<>])", lambda m: hold(_esc(m.group(1))), s)
    s = re.sub(r"<(https?://[^\s<>]+)>", lambda m: hold(_a(m.group(1), _esc(m.group(1)))), s)
    s = _esc(s)
    s = re.sub(r"\[((?:[^\[\]]|\[[^\[\]]*\])+)\]\(\s*(\S+?)(?:\s+&quot;[^&]*&quot;)?\s*\)", _link(hold), s)
    s = re.sub(r"(?<![\w/=])(https?://(?:[^\s<>&]|&amp;)*[^\s<>&.,;:!?)\]'\x00])",
               lambda m: hold(_a(m.group(1), m.group(1))), s)
    s = _emphasis(s)
    while _PH_RE.search(s):
        s = _PH_RE.sub(lambda m: held[int(m.group(1))], s)
    return s


def _strip_code(s: str) -> str:
    s = s.replace("\n", " ")
    return s[1:-1] if len(s) > 2 and s[0] == " " and s[-1] == " " and s.strip() else s


def _a(url: str, text: str) -> str:
    return f'<a href="{url}">{text}</a>'


def _link(hold):
    def sub(m: re.Match) -> str:
        """A relative or http(s) link; any other scheme (javascript:, data:) stays as text."""
        text, url = m.group(1), m.group(2)
        if url.startswith("&lt;") and url.endswith("&gt;"):
            url = url[4:-4]
        scheme = url.split("/", 1)[0]
        if ":" in scheme and not url.startswith(("http://", "https://", "mailto:")):
            return m.group(0)
        return hold(_a(url, _emphasis(text)))
    return sub


def _emphasis(s: str) -> str:
    """Strongest first; a delimiter must touch non-space on its inner side, and `_` and a lone
    `*` must not sit inside a word, so snake_case and 2 * 3 stay as written."""
    s = re.sub(r"\*\*\*(?![\s*])(.+?)(?<![\s*])\*\*\*", r"<strong><em>\1</em></strong>", s, flags=re.S)
    s = re.sub(r"(?<!\w)___(?![\s_])(.+?)(?<![\s_])___(?!\w)", r"<strong><em>\1</em></strong>", s,
               flags=re.S)
    s = re.sub(r"\*\*(?![\s*])(.+?)(?<![\s*])\*\*", r"<strong>\1</strong>", s, flags=re.S)
    s = re.sub(r"\*\*(?!\s)(\*.+?\*)\*\*", r"<strong>\1</strong>", s, flags=re.S)
    s = re.sub(r"(?<!\w)__(?![\s_])(.+?)(?<![\s_])__(?!\w)", r"<strong>\1</strong>", s, flags=re.S)
    s = re.sub(r"~~(?![\s~])(.+?)(?<![\s~])~~", r"<del>\1</del>", s, flags=re.S)
    s = re.sub(r"(?<![\w*])\*(?![\s*])(.+?)(?<![\s*])\*(?![\w*])", r"<em>\1</em>", s, flags=re.S)
    s = re.sub(r"(?<![\w_])_(?![\s_])(.+?)(?<![\s_])_(?![\w_])", r"<em>\1</em>", s, flags=re.S)
    return s
