"""Turn a proof run into files to send: ENG-NN.md, .log and .pdf, and a README index.

    PROOF_DIR="Test Output" bash scripts/run_checklist.sh   # writes Test Output/ENG-NN.md
    pip install markdown                                      # once (not a service dependency)
    python scripts/make_proofs.py                             # adds .log, .pdf and README.md

Also blanks the per-run local test token, and adds the notes on ENG-01 (which
environments the run covers), ENG-06 (speed over a laptop link) and ENG-10 (its
check is ENG-11's). PDFs are printed with Edge or Chrome (scripts/render_pdf.py).
"""

import re
import time
import tempfile
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import markdown  # noqa: E402
from render_pdf import CSS, PAGE, find_browser  # noqa: E402

OUT = ROOT / "Test Output"
EXTRA_CSS = """
pre { white-space: pre-wrap; word-break: break-word; font-size: 7.6pt; page-break-inside: auto !important; break-inside: auto !important; }
h2 { font-size: 11pt; margin-top: 6mm; page-break-after: avoid; break-after: avoid; page-break-inside: avoid; }
"""

NOTES = {
    "ENG-01": "**Scope of this proof.** This run is the **dev** environment (the laptop). The pack's check names all "
              "three environments and production's read-only login: the test server is being set up (decided 14 Oct "
              "2026) and production follows later, so ENG-01 stays *Waiting* until those runs are added.",
    "ENG-06": "**About any FAIL on 6.3 or 6.4.** Those two lines time requests from a laptop over the internet to the "
              "database. The pack's speed check runs **on the test server**, next to the database (ENG-06: \"A request "
              "returns within 200 ms on test\"; ENG-20). Every list's record still matches the response exactly. The "
              "product rail is empty on dev because every seller there has no status (open question 17 to Aravinth), "
              "so each product request reads the whole 1,000-row window, which over a slow link can run past the time "
              "limit; the engine then answers 503 at once, as the pack requires (no retries, SD-26).",
    "ENG-10": "**ENG-10's own check** is \"All M1 checks in ENG-11 pass\": see ENG-11 (11 of 11). This file adds the "
              "reader's tests and M1 running on SOCO's real dev data.",
}

TITLES = {}
# The Home sheet: "Save the result as a file named <item ID>_<date>". The date is the run's.
for raw in sorted(OUT.glob("ENG-[0-9][0-9].md")):
    run = re.search(r"\*\*Run:\*\* (\d{4}-\d{2}-\d{2})", raw.read_text(encoding="utf-8"))
    raw.replace(raw.with_name(f"{raw.stem}_{run.group(1) if run else date.today().isoformat()}.md"))
for md in sorted(OUT.glob("ENG-*_*.md")):
    text = md.read_text(encoding="utf-8")
    text = re.sub(r"checklist-[0-9]+", "<throwaway-token>", text)  # a per-run local test token
    note = NOTES.get(md.stem.split("_")[0])
    if note and note not in text:
        i = text.index("- **Command:**")
        j = text.index("\n", i)
        text = text[:j] + "\n\n> " + note + text[j:]
    md.write_text(text, encoding="utf-8")
    m = re.search(r"\*\*Task:\*\* (.+?)\s*$", text, re.M)
    passed, failed = text.count("\n## PASS"), text.count("\n## FAIL")
    TITLES[md.stem] = (m.group(1) if m else "", passed, failed)

    plain = re.sub(r"^(?:```|~~~~)\s*$\n?", "", text, flags=re.M).replace("**", "")
    md.with_suffix(".log").write_text(plain, encoding="utf-8")

    body = markdown.markdown(text, extensions=["tables", "fenced_code", "sane_lists"])
    footer = f"SOCO recommendation engine · Wave 1A · {md.stem} · {passed} passed, {failed} failed"
    html = md.with_suffix(".html")
    html.write_text(PAGE.format(title=f"{md.stem} check output", css=CSS + EXTRA_CSS, body=body, footer=footer),
                    encoding="utf-8")
    pdf = md.with_suffix(".pdf")
    # Edge won't print into a folder whose name has a space ("Test Output"): print to a
    # temporary folder, then move the file.
    scratch = Path(tempfile.mkdtemp(prefix="proof-pdf-")) / pdf.name
    # Its own profile and no startup boost, so an Edge already running can't take the
    # job over and silently skip the print.
    subprocess.run([find_browser(), "--headless=new", "--disable-gpu", "--no-pdf-header-footer", "--no-first-run",
                    "--disable-features=msEdgeStartupBoost,msStartupBoost", "--disable-background-mode",
                    f"--user-data-dir={tempfile.mkdtemp(prefix='proof-edge-')}",
                    f"--print-to-pdf={scratch}", html.as_uri()], check=True, capture_output=True, timeout=120)
    for _ in range(60):  # Edge can return before the file is written
        if scratch.exists() and scratch.stat().st_size:
            break
        time.sleep(0.5)
    scratch.replace(pdf)
    html.unlink()
    print(f"{md.stem}: {passed} passed, {failed} failed -> .md .log .pdf ({pdf.stat().st_size // 1024} KB)")

rows = "\n".join(f"| {k} | {t} | {p} | {f} |" for k, (t, p, f) in TITLES.items())
(OUT / "README.md").write_text(f"""# Test Output: proof of ENG-01 to ENG-11

Produced {date.today().isoformat()} by `PROOF_DIR="Test Output" bash scripts/run_checklist.sh` on the dev laptop,
against the Atlas build cluster. Everything the checks write goes into throwaway databases, dropped at the end.
SOCO's own data is only read.

Each task has three copies of the same evidence, named `<item ID>_<date>` as the Build List's Home sheet asks:
**.md** (formatted), **.log** (plain text), **.pdf** (to attach).
Each file starts with the task's Build List v1.3 "How to check it is done", then every check: the command it ran,
its full output and its exit code. ENG-29 (adapters) is included because ENG-08 to ENG-11 build on it.

| Task | What | Passed | Failed |
|---|---|---|---|
{rows}

The official runs are on the **test** server (being set up); these are the dev runs. See the notes at the top of
ENG-01 (environments) and ENG-06 (speed over a laptop link).
""", encoding="utf-8")
print("README.md written")
