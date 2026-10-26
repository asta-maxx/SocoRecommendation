"""The category mapping list for the reviewer (ENG-03, ENG-29 item 1). Read-only.

    .venv/bin/python scripts/category_mapping_report.py
    .venv/bin/python scripts/category_mapping_report.py --counts Tracing/checks/category_counts_2026-10-26.json

Every category label in use on the platform (post categories, users' interests,
business categories, products' category ids), with how many items use it and
how the tree rule resolved it: through its top-level parent in the category
tree, through the settings' category map, by being one of the 23 -- or why it is
unmapped (not_in_tree, no_parent, top_not_mapped, map_not_to_23, ambiguous).
Also every top-level node of the tree and what it counts as.

Prints the list and writes it as Markdown (default
Tracing/checks/category_mapping_<IST date>.md). Reads the platform through
reco.platform only; opens no engine connection and writes nothing to any
database. The settings are read from the file (settings/engine.toml), not from
the engine's change log. Labels and counts only: no user, business or post ids.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from reco.config import get_settings, live  # noqa: E402
from reco.platform import connection as platform_conn  # noqa: E402
from reco.platform import fetch  # noqa: E402
from reco.platform.categories import (  # noqa: E402
    UNMAPPED_REASONS,
    VIA_TREE,
    VIA_TREE_AND_MAP,
    canonical_name,
    top_outcome,
)
from reco.platform.readers import vocabulary  # noqa: E402
from reco.sync.reconcile import IST  # noqa: E402

REASONS = {
    "not_in_tree": "no node of this name (or id) in the tree, and no category-map entry",
    "no_parent": "its node's top-level parent cannot be reached (a missing parent, or a loop)",
    "top_not_mapped": "its top is not one of the 23 and the category map has no entry for the top",
    "map_not_to_23": "a category-map entry (the label's or its top's) points to something that is not one of the 23",
    "ambiguous": "it would end up in two different categories (or cannot be told apart)",
    "empty": "no category at all",
}

DECISIONS = [
    "A label that is itself one of the 23 (case and spacing ignored) is that category: ENG-03 matches a "
    "post's categories to the 23 by name, and the Build List comes first. Where the tree puts a node of "
    "that name under another top, it is noted below and not applied.",
    "Names are found in the tree ignoring case and spacing, the same key as matching the 23. Ids "
    "(products) are found by id.",
    "The top is found by following parent links (the actual parent), not the node's path. A node with no "
    "parent is a top only at level 0 (or no level); a missing parent or a loop is no_parent.",
    "The top counts only by its own name: one of the 23, or a category-map entry for the top that points to "
    "one of the 23. A top with no map entry is top_not_mapped (the rule's 'otherwise unmapped').",
    "Two or more nodes with one name: mapped only if every one resolves, and all to the same category; "
    "otherwise ambiguous (the label cannot say which node it means).",
    "The direct rule stays for a label's own category-map entry. Tree and map both give a category and they "
    "differ: ambiguous, neither picked. Only one gives a category: it is used (noted where the tree's top "
    "was not mapped). A label's own map entry that does not point to one of the 23: map_not_to_23, "
    "whatever the tree says.",
    "A product's category id (categoryPathIds[0], else basicInfo.categoryId) is followed up its parents to "
    "its top; an id is never ambiguous and takes no direct rule.",
    "The app's interestLabel on category nodes is shown for information only; the rule does not use it.",
    "The tree is read at most once a minute per process (the settings' reload interval).",
]


def _uses(used_by: dict[str, int]) -> str:
    return ", ".join(f"{where} {n}" for where, n in sorted(used_by.items()))


def _cell(text: object) -> str:
    return str(text if text not in (None, "") else "").replace("|", "\\|")


async def gather() -> dict:
    settings = get_settings()
    read = live.read_file(settings.settings_file)
    if read.tunables is None:
        raise SystemExit(f"settings file not usable: {read.fault}")
    live.put_in_force(read.tunables, settings.settings_file)
    platform_conn.init_client(settings)
    try:
        rows = await fetch.category_mapping(settings)
        tree = await fetch.category_tree(settings)
        labels = await fetch.category_interest_labels(settings)
    finally:
        await platform_conn.close_client()
    vocab = vocabulary(settings)
    category_map = live.current().lists.category_map
    tops = []
    for node in sorted((n for n in tree.nodes.values() if n.parent_id is None), key=lambda n: n.name or ""):
        outcome = top_outcome(vocab, tree, node.category_id, category_map)
        tops.append({"top": node.name, "level": node.level, "category": outcome.category, "reason": outcome.reason,
                     "app_label": labels.get(node.category_id)})
    # Nodes below the top whose app interestLabel names another of the 23 than the rule
    # gives, with the labels in use beneath them: where the top-only rule and the app part.
    below = []
    for category_id, app_label in sorted(labels.items(), key=lambda kv: " > ".join(tree.path_of(kv[0]))):
        node = tree.nodes.get(category_id)
        if node is None or node.parent_id is None:
            continue
        rule = top_outcome(vocab, tree, category_id, category_map).category
        app = canonical_name(vocab, app_label)
        if app == rule:
            continue
        under = [r for r in rows if r["via"] in (VIA_TREE, VIA_TREE_AND_MAP) and not r["used_by"].get("products")
                 and any(_descends(tree, n.category_id, category_id) for n in tree.named(r["label"]))]
        below.append({"path": " > ".join(tree.path_of(category_id)), "app_label": app_label, "rule": rule,
                      "labels": [(r["label"], r["items"]) for r in under]})
    return {
        "db": settings.app_mongo_db, "config_version": live.current().config_version,
        "map_entries": len(category_map), "nodes": len(tree.nodes), "rows": rows, "tops": tops, "below": below,
    }


def _descends(tree, category_id: str, ancestor_id: str) -> bool:
    seen: set[str] = set()
    node = tree.nodes.get(category_id)
    while node is not None and node.category_id not in seen:
        if node.category_id == ancestor_id:
            return True
        seen.add(node.category_id)
        node = tree.nodes.get(node.parent_id) if node.parent_id else None
    return False


def render(data: dict, counts: dict | None, day: str) -> str:
    rows = data["rows"]
    mapped = [r for r in rows if r["category"]]
    unmapped = [r for r in rows if not r["category"]]
    by_via = Counter(r["via"] for r in mapped)
    by_reason = Counter(r["reason"] for r in unmapped)
    lines = [
        f"# Category mapping list ({day})",
        "",
        "ENG-03, ENG-29 item 1 (review points 4 and 5). Every category label in use on the platform, how many "
        "items use it, and how the tree rule resolved it: through its top-level parent in the platform's "
        "category tree (the top counts if it is one of the 23, or if the category map points it straight to "
        "one of the 23), or why it is unmapped. Nothing is guessed from a label, product or seller name.",
        "",
        f"Platform database `{data['db']}`, read only. Settings config_version {data['config_version']} "
        f"({data['map_entries']} category-map entries). Category tree: {data['nodes']} nodes, "
        f"{len(data['tops'])} top-level. Written by `scripts/category_mapping_report.py`.",
        "",
    ]
    if counts:
        lines += [f"## Before and after ({counts.get('when', day)})", "", counts.get("about", ""), "",
                  "| Measure | Before | After | Note |", "|---|---:|---:|---|"]
        lines += [f"| {_cell(r['measure'])} | {_cell(r['before'])} | {_cell(r['after'])} | {_cell(r.get('note'))} |"
                  for r in counts["rows"]]
        lines.append("")
    lines += [
        "## Summary", "",
        f"{len(rows)} labels in use: **{len(mapped)} mapped**, **{len(unmapped)} unmapped** "
        f"({sum(r['items'] for r in unmapped)} items).", "",
        "| How mapped | Labels |", "|---|---:|",
        *(f"| {via} | {n} |" for via, n in sorted(by_via.items())), "",
        "| Why unmapped | Labels | Items | Meaning |", "|---|---:|---:|---|",
        *(f"| {reason} | {by_reason[reason]} | {sum(r['items'] for r in unmapped if r['reason'] == reason)} "
          f"| {REASONS[reason]} |" for reason in UNMAPPED_REASONS if by_reason[reason]),
        "",
        "## Unmapped labels (for the reviewer)", "",
        "Left out of category scoring until mapped. Product rows are a category id, shown with its path.", "",
        "| Label | Used by | Items | Reason | Tree top | Note |", "|---|---|---:|---|---|---|",
        *(f"| {_cell(r['label'])} | {_uses(r['used_by'])} | {r['items']} | {r['reason']} | "
          f"{_cell(', '.join(r['tops']))} | {_cell(r['note'])} |" for r in unmapped),
        "",
        "## Mapped labels with a note", "",
        "Mapped, but the tree says something the reviewer should see.", "",
        "| Label | Used by | Items | Category | How | Note |", "|---|---|---:|---|---|---|",
        *(f"| {_cell(r['label'])} | {_uses(r['used_by'])} | {r['items']} | {r['category']} | {r['via']} | "
          f"{_cell(r['note'])} |" for r in mapped if r["note"]),
        "",
        "## The tree's top-level nodes", "",
        "What each top counts as. The app's interestLabel is shown for information only (the rule does not "
        "use it); where it differs from the result, the reviewer may want the category map changed.", "",
        "| Top | Counts as | Reason | App's interestLabel |", "|---|---|---|---|",
        *(f"| {_cell(t['top'])} | {_cell(t['category'])} | {_cell(t['reason'])} | {_cell(t['app_label'])} |"
          for t in data["tops"]),
        "",
        "## Below the top: where the app's interestLabel names another of the 23", "",
        "The rule uses the top only, so everything under these nodes counts in the top's category. The app "
        "labels the node itself as another of the 23. Shown for the reviewer; nothing here is applied.", "",
        "| Node | App's interestLabel | The rule gives | Labels in use beneath it (items) |", "|---|---|---|---|",
        *(f"| {_cell(b['path'])} | {_cell(b['app_label'])} | {_cell(b['rule'] or 'unmapped')} | "
          f"{_cell(', '.join(f'{label} ({n})' for label, n in b['labels']) or 'none')} |" for b in data["below"]),
        "",
        "## Every label in use", "",
        "| Label | Used by | Items | Category | How | Tree top |", "|---|---|---:|---|---|---|",
        *(f"| {_cell(r['label'])} | {_uses(r['used_by'])} | {r['items']} | {_cell(r['category'] or 'unmapped')} | "
          f"{_cell(r['via'] or r['reason'])} | {_cell(', '.join(r['tops']))} |" for r in rows),
        "",
        "## Decisions where the rule is silent (26 Oct 2026)", "",
        *(f"{i}. {text}" for i, text in enumerate(DECISIONS, 1)),
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--counts", type=Path, default=None, help="before/after counts (JSON) to show at the top")
    args = parser.parse_args()
    day = datetime.now(IST).date().isoformat()
    out = args.out or ROOT / "Tracing" / "checks" / f"category_mapping_{day}.md"
    counts = json.loads(args.counts.read_text(encoding="utf-8")) if args.counts else None
    data = asyncio.run(gather())
    text = render(data, counts, day)
    out.write_text(text, encoding="utf-8")
    print(text)
    print(f"\nwritten: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
