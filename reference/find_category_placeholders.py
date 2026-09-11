#!/usr/bin/env python3
"""
Fills two of the placeholders in generate_demo_events.py from the actual
database.  Read only.  Nothing is written.

    python find_category_placeholders.py --mongo "mongodb+srv://..." --db nex-dev

Paste the twenty three canonical categories into CANONICAL below first, or
leave it empty and the script will just report what it found without
classifying anything.

Two things this settles that the earlier version could not.  It reports whether
a collection genuinely exists rather than assuming a query that returns nothing
means a collection that is readable, and it classifies category names by their
path as well as by their exact string, which is the open question in D-05: if
the mapping resolves through path[0] then 'Saree' is mappable through
'Fashion & Apparel' and U08 needs different values.
"""

import argparse
from collections import defaultdict
from pymongo import MongoClient

# Paste the twenty three post picker categories here if you have them.
CANONICAL = ['Fashion & Apparel',
  'Electronics',
  'Food & Beverages',
  'Home & Living',
  'Beauty & Personal Care',
  'Sports & Outdoors',
  'Automotive',
  'Travel & Lifestyle',
  'Health & Wellness',
  'Books & Education',
  'Pets',
  'Art & Collectibles',
  'Toys & Kids',
  'Music & Entertainment',
  'Office & Business',
  'Technology',
  'Jewellery',
  'Shoes & Footwear',
  'Organic & Eco',
  'Photography',
  'Finance',
  'Gaming',
  'Wedding & Events']

NAME_FIELDS = ["name", "categoryName", "title", "category", "label", "displayName"]
PATH_FIELDS = ["path", "ancestors", "breadcrumb", "parentPath", "categoryPath"]

PROBE = ("categories", "users", "businessregisters", "posts",
         "postevents", "trackings", "userevents", "orders")


def field_report(coll, label, limit=3):
    """Show what a collection actually looks like before assuming anything."""
    n = coll.estimated_document_count()
    print(f"\n--- {label}: {n} documents ---")
    keys = defaultdict(int)
    for doc in coll.find({}, limit=200):
        for k in doc:
            keys[k] += 1
    print("  fields seen:", ", ".join(sorted(keys)) or "(none)")
    for doc in coll.find({}, limit=limit):
        print("  sample:", {k: v for k, v in doc.items() if k != "_id"})
    return keys


def name_of(doc):
    for f in NAME_FIELDS:
        if isinstance(doc.get(f), str) and doc[f].strip():
            return doc[f].strip()
    return None


def path_of(doc):
    """The ancestor chain, outermost first, as a list of strings."""
    for f in PATH_FIELDS:
        v = doc.get(f)
        if isinstance(v, list) and v:
            out = []
            for item in v:
                s = item if isinstance(item, str) else (
                    name_of(item) if isinstance(item, dict) else None)
                if s:
                    out.append(s.strip())
            if out:
                return out
        if isinstance(v, str) and v.strip():
            parts = [p.strip() for p in v.replace(">", "/").split("/") if p.strip()]
            if parts:
                return parts
    return []


def probe_collections(db):
    """Which of the collections we care about are present, and readable.

    find_one on a collection that does not exist returns None without raising, so
    the old probe reported every name in PROBE as readable whether or not it was
    there, and a missing 'categories' surfaced as 'nothing found' rather than as
    'that collection does not exist'.  Ask the server for the list, and fall back
    to the probe only when the role cannot run listCollections, saying so.
    """
    try:
        existing = set(db.list_collection_names())
        present = [n for n in PROBE if n in existing]
        for n in PROBE:
            if n not in existing:
                print(f"  {n}: not present in {db.name}")
        return present, True
    except Exception as exc:
        print(f"  listCollections unavailable ({type(exc).__name__}), falling back to "
              f"a read probe.\n  A collection that does not exist and one that is "
              f"empty look identical from here.")
        present = []
        for name in PROBE:
            try:
                db[name].find_one({}, {"_id": 1})
                present.append(name)
            except Exception as exc2:
                print(f"  {name}: not readable ({type(exc2).__name__})")
        return present, False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mongo", required=True)
    ap.add_argument("--db", default=None,
                    help="database name. Defaults to the one named in the URI. "
                         "Note that the cluster name and the database name differ: "
                         "a URI ending /soco on cluster nex-dev means --db soco.")
    a = ap.parse_args()
    client = MongoClient(a.mongo)
    db = client[a.db] if a.db else client.get_default_database()
    if db is None:
        raise SystemExit("No database given and the URI names none. Pass --db.")
    print(f"database: {db.name}")

    present, listed = probe_collections(db)
    print("collections present:", present, "" if listed else "(probed, not listed)")

    # ------------------------------------------------------------------
    # 1.  Seller created product categories with no canonical mapping.
    #     Fills UNMAPPABLE.  Three are needed for U08.
    # ------------------------------------------------------------------
    if "categories" in present:
        field_report(db.categories, "categories")
        docs = list(db.categories.find())
        by_name = {}
        for doc in docs:
            n = name_of(doc)
            if n:
                by_name.setdefault(n, path_of(doc))
        names = sorted(by_name)
        print(f"\n  {len(names)} distinct category names")
        n_paths = sum(1 for p in by_name.values() if p)
        print(f"  {n_paths} of them carry a path")

        if CANONICAL:
            lowered = {c.lower() for c in CANONICAL}

            # Exact string, which is what the generator's UNMAPPABLE means today.
            unmapped = [n for n in names if n.lower() not in lowered]

            # And the same names again under path based mapping, which is the
            # question D-05 leaves open.  A name whose path[0] is canonical is
            # mappable that way even though its own string is not, so it cannot
            # be used for U08 if the engine resolves through the path.
            via_path, truly = [], []
            for n in unmapped:
                root = next((p for p in by_name[n] if p.lower() in lowered), None)
                (via_path if root else truly).append((n, root))

            print(f"\n  {len(unmapped)} have no case insensitive match in CANONICAL:")
            for n in unmapped:
                print("     ", repr(n), "path", by_name[n] or "(none)")

            print(f"\n  of those, {len(via_path)} become mappable through path[0]:")
            for n, root in via_path:
                print(f"      {n!r} resolves to {root!r}")
            print(f"  and {len(truly)} are unmappable under either rule:")
            for n, _ in truly:
                print("     ", repr(n))

            safe = [n for n, _ in truly]
            if len(safe) >= 3:
                print("\n  UNMAPPABLE = " + repr(sorted(safe)[:3]))
                print("  These three are unmappable whichever way D-05 lands, so U08")
                print("  holds either way.")
            else:
                print(f"\n  Only {len(safe)} names are unmappable under both rules, and "
                      f"U08 needs three.")
                print("  Settle D-05 first. If the mapping is by exact string, any three")
                print("  of the list above will do:")
                print("  UNMAPPABLE = " + repr(sorted(unmapped)[:3]))
        else:
            for n in names:
                print("     ", repr(n), "path", by_name[n] or "(none)")
            print("\n  CANONICAL is empty, so nothing was classified. Paste the")
            print("  twenty three in and run again, or pick three from the list above")
            print("  that are plainly not post picker categories.")
    else:
        print(f"\n'categories' is not present in {db.name}. Check the list printed "
              f"above, and check that --db names the database and not the cluster.")

    # ------------------------------------------------------------------
    # 2.  Case variants among the interest keys actually stored.
    #     Fills LIST1_CASE_VARIANTS.  A pair is needed for U06.
    # ------------------------------------------------------------------
    groups = defaultdict(set)
    sources = set()

    for coll_name in ("users", "businessregisters"):
        if coll_name not in present:
            continue
        coll = db[coll_name]
        field_report(coll, coll_name, limit=1)
        for doc in coll.find():
            scores = doc.get("interestScores")
            if isinstance(scores, dict):
                for k in scores:
                    groups[k.strip().lower()].add(k)
                    sources.add(f"{coll_name}.interestScores")
            for f in ("interests", "interestCategories", "selectedInterests", "categories"):
                v = doc.get(f)
                if isinstance(v, list):
                    for item in v:
                        s = item if isinstance(item, str) else (
                            name_of(item) if isinstance(item, dict) else None)
                        if s:
                            groups[s.strip().lower()].add(s.strip())
                            sources.add(f"{coll_name}.{f}")

    print("\n--- interest keys ---")
    print("  read from:", ", ".join(sorted(sources)) or "nothing found")
    print(f"  {len(groups)} distinct keys ignoring case")

    variants = {k: sorted(v) for k, v in groups.items() if len(v) > 1}
    if variants:
        print("\n  keys stored with more than one spelling:")
        for k in sorted(variants):
            print("     ", variants[k])
        # Sorted, not "whichever the scan happened to reach first". Mongo makes no
        # promise about natural order, so the old code could suggest a different
        # pair on two runs against the same data.
        pick = variants[sorted(variants)[0]]
        print("\n  LIST1_CASE_VARIANTS = " + repr(pick[:2]))
        if CANONICAL and all(v in CANONICAL for v in pick[:2]):
            print("  WARNING  both spellings are already exact members of CANONICAL, so")
            print("           there is nothing for the engine to normalise. Choose a")
            print("           pair where at least one spelling is not in the vocabulary;")
            print("           the generator refuses the dataset otherwise.")
    else:
        print("\n  no case variants found in the data as it stands today.")
        print("  Two possibilities. The keys were cleaned up since profiling, in")
        print("  which case say so and U06 drops the case variant part. Or the")
        print("  variants live somewhere this script did not look, in which case")
        print("  the field list printed above will show where.")


if __name__ == "__main__":
    main()
