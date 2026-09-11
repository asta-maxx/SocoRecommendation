"""Render a project Markdown document to a print-ready PDF.

    python scripts/render_pdf.py EVENT_CONTRACT.md

Uses Microsoft Edge (or Chrome) in headless mode, so there is nothing to install
beyond `markdown`. Regenerate whenever the source document changes -- the PDF is
a rendering, not a second copy to keep in step by hand.

    pip install markdown
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import markdown

BROWSERS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]

CSS = """
@page { size: A4; margin: 18mm 16mm 20mm 16mm; }

html { -webkit-print-color-adjust: exact; print-color-adjust: exact; }

body {
  font-family: "Segoe UI", "Helvetica Neue", Arial, sans-serif;
  font-size: 10.2pt;
  line-height: 1.55;
  color: #16191d;
  margin: 0;
}

/* --- headings ---------------------------------------------------------- */
h1 {
  font-size: 21pt;
  line-height: 1.2;
  margin: 0 0 2mm 0;
  letter-spacing: -0.3pt;
}
h2 {
  font-size: 13.5pt;
  margin: 9mm 0 3mm 0;
  padding-bottom: 1.6mm;
  border-bottom: 1.5px solid #d7dbe0;
  page-break-after: avoid;
}
h3 {
  font-size: 11pt;
  margin: 6mm 0 2mm 0;
  color: #0f3d63;
  page-break-after: avoid;
}
h2 + h3 { margin-top: 4mm; }

p { margin: 0 0 2.6mm 0; }
h1 + p { color: #5a6470; font-size: 10pt; }

/* --- rules ------------------------------------------------------------- */
hr {
  border: 0;
  border-top: 1px solid #e3e7ec;
  margin: 7mm 0;
}

/* --- tables ------------------------------------------------------------ */
table {
  border-collapse: collapse;
  width: 100%;
  margin: 3mm 0 4mm 0;
  font-size: 9.3pt;
  page-break-inside: avoid;
}
th {
  background: #eef2f6;
  text-align: left;
  font-weight: 600;
  padding: 2mm 2.6mm;
  border: 1px solid #d0d7de;
  color: #16191d;
}
td {
  padding: 2mm 2.6mm;
  border: 1px solid #dde2e8;
  vertical-align: top;
}
tbody tr:nth-child(even) td { background: #fafbfc; }

/* --- code -------------------------------------------------------------- */
code {
  font-family: "Cascadia Mono", Consolas, "Courier New", monospace;
  font-size: 8.9pt;
  background: #f2f4f7;
  border: 1px solid #e2e6eb;
  border-radius: 2.5px;
  padding: 0.4mm 1.1mm;
  white-space: nowrap;
}
pre {
  background: #f7f9fb;
  border: 1px solid #dde3ea;
  border-left: 3px solid #2f6f9f;
  border-radius: 3px;
  padding: 3mm 3.5mm;
  margin: 3mm 0 4mm 0;
  overflow: hidden;
  page-break-inside: avoid;
}
pre code {
  background: none;
  border: 0;
  padding: 0;
  font-size: 8.7pt;
  line-height: 1.45;
  white-space: pre-wrap;
  word-break: break-word;
}

/* --- lists ------------------------------------------------------------- */
ul, ol { margin: 0 0 3mm 0; padding-left: 5.5mm; }
li { margin-bottom: 1.2mm; }

strong { font-weight: 600; }

/* --- status banner ----------------------------------------------------- */
.status {
  background: #fff8e6;
  border: 1px solid #f0d795;
  border-left: 3px solid #c9971d;
  border-radius: 3px;
  padding: 2.8mm 3.5mm;
  margin: 0 0 5mm 0;
  font-size: 9.6pt;
}

/* --- footer ------------------------------------------------------------ */
.footer {
  margin-top: 9mm;
  padding-top: 2.5mm;
  border-top: 1px solid #e3e7ec;
  font-size: 8.2pt;
  color: #7b858f;
}
"""

PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>{title}</title>
<style>{css}</style></head>
<body>{body}
<div class="footer">{footer}</div>
</body></html>
"""


def find_browser() -> str:
    for path in BROWSERS:
        if Path(path).exists():
            return path
    for name in ("msedge", "chrome"):
        found = shutil.which(name)
        if found:
            return found
    raise SystemExit("No Edge or Chrome found to render the PDF.")


def render(source: Path, output: Path) -> None:
    text = source.read_text(encoding="utf-8")

    body = markdown.markdown(
        text,
        extensions=["tables", "fenced_code", "sane_lists", "attr_list"],
    )

    # The status line reads as a banner rather than a paragraph.
    body = body.replace(
        "<p><strong>Status:",
        '<p class="status"><strong>Status:',
        1,
    )
    title = source.stem.replace("_", " ").title()
    footer = (
        f"SOCO M1 interest model &nbsp;·&nbsp; {source.name} &nbsp;·&nbsp; "
        f"enforced in code at reco/domain/event_contract.py"
    )

    output.parent.mkdir(parents=True, exist_ok=True)

    # The HTML is kept alongside the PDF rather than thrown away: it is what
    # actually gets rendered, so it is the thing to look at when the PDF comes
    # out wrong.
    html_path = output.with_suffix(".html")
    html_path.write_text(
        PAGE.format(title=title, css=CSS, body=body, footer=footer),
        encoding="utf-8",
    )

    subprocess.run(
        [
            find_browser(),
            "--headless",
            "--disable-gpu",
            "--no-pdf-header-footer",
            f"--print-to-pdf={output}",
            html_path.as_uri(),
        ],
        check=True,
        capture_output=True,
        timeout=120,
    )

    if not output.exists():
        raise SystemExit(f"Rendering produced no file at {output}")
    print(f"{output}  ({output.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    name = sys.argv[1] if len(sys.argv) > 1 else "EVENT_CONTRACT.md"
    root = Path(__file__).resolve().parents[1]
    source = (root / name).resolve()
    if not source.exists():
        raise SystemExit(f"No such document: {source}")
    render(source, root / "docs" / f"{source.stem}.pdf")
