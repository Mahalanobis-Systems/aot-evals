# Interactive problems

One interactive widget for each of the twelve problems in [problems.md](../problems.md). Each one
works through that problem's example on the same online store, with sliders. They run on
mahalsystems.ai, one page each, and each problem in problems.md links to its page.

| File | What it is |
|---|---|
| `widgets.json` | The manifest: for each problem, its page's address (`slug`), title, lead, description, and the label the site's map gives it |
| `<slug>.html` | The widget: an HTML comment saying what it shows and how it computes it, the markup, then one `<script>` |
| `widgets.css` | The styles every widget shares |

## Conventions

- **A fragment, not a page.** A widget file has no `<html>` or `<head>`. The site places it on a
  page, so its script is wrapped in `(() => { ... })();` and finds its own root by a `data-` attribute,
  which lets several widgets share a page.
- **Plain JavaScript, no dependencies.** No build step and no libraries: what is in the file is what
  runs.
- **The store's numbers come from problems.md.** A widget that uses the store keeps them in its root's
  `data-config` JSON, and `tests/test_interactive.py` checks them against problems.md: the four kinds
  of request, their requests a day and what one mistake costs. A widget's defaults reproduce the
  numbers its problem quotes where it can.
- **Words from the terms.** Pass rate, catch rate, clean pass rate and a failure as the positive, as
  the [terms](../estimators.md#terms) define them.
- **Tokens with fallbacks.** `widgets.css` uses the host page's color and font tokens when it has
  them (`--forest`, `--green`, `--head`, ...) and falls back to its own.

## Checking a change

```bash
uv run --no-project --with pyyaml python3 scripts/build_site.py   # writes dist/interactive/
open dist/interactive/index.html
```

Each widget gets a page of its own there, with its title and lead. The release attaches
`evals.json`, which carries the manifest, the stylesheet and every fragment under `interactive`; the
site builds its pages from that.
