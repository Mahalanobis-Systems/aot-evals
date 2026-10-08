# Brand

aot-evals is part of **AOT, the Agent Optimization Toolkit**, a Mahal Systems offering. Every
HTML report the plugin writes carries this branding, so whoever opens a report can see where the
tool comes from. The rules below are the subset of the Mahal Systems brand that applies to
reports.

## Names

| What | Write it |
|---|---|
| The company | **Mahal Systems**. "Mahalanobis-Systems" is only the GitHub org name |
| The product family | **AOT**, spelled out once per document as **"AOT, the Agent Optimization Toolkit"** |
| Attribution lockup | *"a Mahal Systems offering"* |

## Color

| Role | Name | Hex | In reports |
|---|---|---|---|
| Primary | Enterprise Forest | `#225734` | headings, structure, links, interval marks, failing gates |
| Accent | Velocity Green | `#95C13E` | **sparingly, one per region**: the thing that improved (gains) |
| Text | Production Charcoal | `#1A201C` | body text, error bars, losses |
| Background | Cloud White | `#F9FAF9` | page background |
| Tint | Light Forest | `#E2EAE4` | panels, table header rules |
| Tint | Pale Green | `#EFF6DF` | variance bands, highlight bands |

Charts may add a neutral grey ramp. No other colors. Light backgrounds only: there is no
dark-background version of the logo.

## Type

- **Montserrat** SemiBold/Bold for headings, in Enterprise Forest; Regular for the wordmark.
- **Roboto** Regular for body copy.
- Both are vendored in [`fonts/`](fonts/) and embedded in each report, because reports make no
  network requests. Both are licensed under the SIL Open Font License 1.1: see
  [`fonts/Montserrat-OFL.txt`](fonts/Montserrat-OFL.txt) and [`fonts/Roboto-LICENSE.txt`](fonts/Roboto-LICENSE.txt).

## Logo

| File | Use |
|---|---|
| [`agent-optimization-logo.png`](agent-optimization-logo.png) | The AOT logo, full size (1312×1199, transparent, for light backgrounds) |
| [`aot-logo-128.png`](aot-logo-128.png) | The same logo at 128 px, embedded in report headers |

Rules: at the top right; never smaller than about 48 px tall; clear space of about half its
width; never recolored; light backgrounds only.

The "Mahal Systems" wordmark is text, not an image: Montserrat Regular, Production Charcoal, set
smaller than any product name near it, bottom right of the report.

## In a report

`aot-evals report --html` writes `evals/report/report-<date>.html`, a branded shell. It contains:
- the embedded fonts and logo;
- the brand styles from [`../skills/report/references/style.css`](../skills/report/references/style.css);
- a header and footer;
- `report.json` inlined.

Claude then writes the panels into its `<main>`. Leave the header and footer as generated.

Dates shown to readers are written "Month Day, Year" (`October 2, 2026`). `report.json` keeps ISO
timestamps.
