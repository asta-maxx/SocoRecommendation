"""List Obsidian [[links]] in obsidian/ that point to no note.

    python3 .claude/skills/update-docs/check_links.py

Exit 0 when every link resolves, or when the only unresolved ones are "Next"
links to task notes not yet written (names starting with ENG-). Exit 1 otherwise.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

VAULT = Path(__file__).resolve().parents[3] / "obsidian"
LINK = re.compile(r"\[\[([^\]|#]+)")


def main() -> int:
    notes = {path.stem for path in VAULT.rglob("*.md")}
    unresolved: dict[str, list[str]] = {}
    for path in VAULT.rglob("*.md"):
        for target in LINK.findall(path.read_text(encoding="utf-8")):
            target = target.strip()
            if target not in notes:
                unresolved.setdefault(target, []).append(path.stem)

    print(f"{len(notes)} notes in {VAULT.name}/")
    pending = {t: s for t, s in unresolved.items() if t.startswith("ENG-")}
    broken = {t: s for t, s in unresolved.items() if not t.startswith("ENG-")}
    for target, sources in sorted(pending.items()):
        print(f"  next (not written yet): [[{target}]]  from {', '.join(sorted(set(sources)))}")
    for target, sources in sorted(broken.items()):
        print(f"  BROKEN: [[{target}]]  from {', '.join(sorted(set(sources)))}")
    if not unresolved:
        print("  all links resolve")
    return 1 if broken else 0


if __name__ == "__main__":
    sys.exit(main())
