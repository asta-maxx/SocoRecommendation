"""Turn the pack in docs/updated into plain text, for reading and searching. Read-only.

    python3 scripts/extract_pack.py            # writes Tracing/pack_text/<file>.txt

The pack (.docx and .xlsx) stays exactly as it is; this only reads it. Word
files become one paragraph per line; spreadsheets become one row per line, cells
joined with " | ", each sheet under "=== SHEET: <name>". Standard library only,
so it runs on a fresh machine before the virtual environment exists.
"""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / "docs" / "updated"
OUT = ROOT / "Tracing" / "pack_text"

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
M = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
     "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}


def docx(path: Path) -> list[str]:
    root = ET.fromstring(zipfile.ZipFile(path).read("word/document.xml"))
    lines = []
    for paragraph in root.iter(W + "p"):
        text = "".join(t.text or "" for t in paragraph.iter(W + "t")).strip()
        if text:
            lines.append(text)
    return lines


def xlsx(path: Path) -> list[str]:
    z = zipfile.ZipFile(path)
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", M):
            shared.append("".join(t.text or "" for t in si.iter("{%s}t" % M["m"])))
    workbook = ET.fromstring(z.read("xl/workbook.xml"))
    rels = {r.get("Id"): r.get("Target") for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))}
    lines = []
    for sheet in workbook.find("m:sheets", M):
        target = rels[sheet.get("{%s}id" % M["r"])].lstrip("/")
        target = target if target.startswith("xl/") else "xl/" + target
        lines.append(f"=== SHEET: {sheet.get('name')}")
        for row in ET.fromstring(z.read(target)).iter("{%s}row" % M["m"]):
            cells = []
            for cell in row.findall("m:c", M):
                value, kind = cell.find("m:v", M), cell.get("t")
                if kind == "s" and value is not None:
                    cells.append(shared[int(value.text)])
                elif kind == "inlineStr":
                    cells.append("".join(t.text or "" for t in cell.iter("{%s}t" % M["m"])))
                elif value is not None:
                    cells.append(value.text)
            cells = [c.replace("\n", " / ") for c in cells if c]
            if cells:
                lines.append(" | ".join(cells))
    return lines


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for path in sorted(PACK.iterdir()):
        if path.suffix not in (".docx", ".xlsx"):
            continue
        lines = docx(path) if path.suffix == ".docx" else xlsx(path)
        (OUT / f"{path.name}.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"{path.name}: {len(lines)} lines")
    return 0


if __name__ == "__main__":
    sys.exit(main())
