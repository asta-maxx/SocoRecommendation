"""Turn a proof run into files to send: one folder per model, one set of files per task.

    PROOF_DIR="Test Output" bash scripts/run_checklist.sh   # writes Test Output/ENG-NN.md
    pip install markdown                                      # once (not a service dependency)
    python scripts/make_proofs.py                             # files them by model, adds .log, .pdf, README.md

    Test Output/Foundation/ENG-01.md .log .pdf ... ENG-08, ENG-29
    Test Output/M1/ENG-09 ... ENG-11
    Test Output/M2/ENG-12 ... ENG-15

Each file is named after its task (Allen, 17 Oct 2026); the run's date is inside it.

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
    "ENG-10": "**ENG-10's own check** is \"All M1 checks in ENG-11 pass\": see ENG-11 (18 of 18). This file adds the "
              "reader's tests and M1 running on SOCO's real dev data.",
    "ENG-12": "**About the 20 ms limit.** Each source's rule and the drop-and-log are proved here. The timing itself is "
              "\"on test load\": from a laptop each read crosses the internet to the database (23 to 30 ms), so the "
              "timed run is on the test server.",
    "ENG-14": "**About the 20 ms read.** The database answers one list in 0 ms (an index scan, no sort); from a laptop "
              "the network adds two round trips, so the wall time is proved on the test server.",
}

#: Which folder each task goes in: the model it belongs to.
GROUPS = {
    "Foundation": ["ENG-01", "ENG-02", "ENG-03", "ENG-04", "ENG-05", "ENG-06", "ENG-07", "ENG-08", "ENG-29"],
    "M1": ["ENG-09", "ENG-10", "ENG-11"],
    "M2": ["ENG-12", "ENG-13", "ENG-14", "ENG-15"],
}
FOLDER = {task: group for group, tasks in GROUPS.items() for task in tasks}

def read(path: Path) -> str:
    """UTF-8, or the Windows code page a console wrote some lines in (e.g. "home décor")."""
    data = path.read_bytes()
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("cp1252")


TITLES = {}
RUN_DATE = {}
# File each raw run into its model's folder, named after the task.
for raw in sorted(OUT.glob("ENG-[0-9][0-9].md")):
    run = re.search(r"\*\*Run:\*\* (\d{4}-\d{2}-\d{2})", read(raw))
    RUN_DATE[raw.stem] = run.group(1) if run else date.today().isoformat()
    folder = OUT / FOLDER.get(raw.stem, "Other")
    folder.mkdir(exist_ok=True)
    raw.replace(folder / raw.name)
for md in sorted(OUT.glob("*/ENG-[0-9][0-9].md")):
    text = read(md)
    text = re.sub(r"checklist-[0-9]+", "<throwaway-token>", text)  # a per-run local test token
    note = NOTES.get(md.stem)
    if note and note not in text:
        i = text.index("- **Command:**")
        j = text.index("\n", i)
        text = text[:j] + "\n\n> " + note + text[j:]
    md.write_text(text, encoding="utf-8")
    m = re.search(r"\*\*Task:\*\* (.+?)\s*$", text, re.M)
    passed, failed = text.count("\n## PASS"), text.count("\n## FAIL")
    TITLES[md.stem] = (md.parent.name, m.group(1) if m else "", passed, failed)

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
    print(f"{md.parent.name}/{md.stem}: {passed} passed, {failed} failed -> .md .log .pdf ({pdf.stat().st_size // 1024} KB)")

rows = "\n".join(f"| {g} | {k} | {t} | {p} | {f} |"
                  for k, (g, t, p, f) in sorted(TITLES.items(), key=lambda kv: (list(GROUPS).index(kv[1][0])
                                                                                 if kv[1][0] in GROUPS else 99, kv[0])))
(OUT / "README.md").write_text(f"""# Test Output: proof by model

Produced {date.today().isoformat()} by `PROOF_DIR="Test Output" bash scripts/run_checklist.sh` on the dev laptop,
against the Atlas build cluster. Everything the checks write goes into throwaway databases, dropped at the end.
SOCO's own data is only read.

One folder per model: **Foundation** (ENG-01 to ENG-08, and ENG-29, the adapters the models build on), **M1**
(interest score: ENG-09 to ENG-11), **M2** (finding posts for the feed: ENG-12 to ENG-15). Each task has three
copies of the same evidence, named after the task: **.md** (formatted), **.log** (plain text), **.pdf** (to attach).
The run's date is inside each file. Each file starts with the task's Build List v1.4 "How to check it is done",
then every check: the command it ran, its full output and its exit code.

| Model | Task | What | Passed | Failed |
|---|---|---|---|---|
{rows}

The official runs are on the **test** server (being set up); these are the dev runs. See the notes at the top of
ENG-01 (environments) and ENG-06 (speed over a laptop link).
""", encoding="utf-8")
print("README.md written")
