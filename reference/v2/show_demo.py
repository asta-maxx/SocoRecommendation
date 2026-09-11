#!/usr/bin/env python3
"""
The demonstration display.  DS-015 task 16.

Prints the nine steps of the DS-014 running order as terminal tables.  It reads
the score store and the manifest and computes nothing it can read, so what is on
the screen is what the engine produced rather than what this script thinks the
engine should have produced.

    python show_demo.py --dir ./demo
    python show_demo.py --mongo "mongodb+srv://..." --db soco
    python show_demo.py --dir ./demo --step 4

Written before the engine exists, on purpose.  Until Method A is writing, every
step that needs a score falls back to the generator's own arithmetic in
ml_demo_meta.expected_raw and says so in the header, so the narration can be
rehearsed on day 2 rather than first read aloud on day 3.  Anything marked
[rehearsal] is this script's arithmetic and must not be shown on the day.

Field names are read from ml_demo_meta.score_store_contract, never written as
literals here.  If DS-015 task 13 lands on different names, this script follows
without an edit.  That is the whole reason the contract is in the manifest.

Step 10, the conformance check, is withdrawn: task 19 and task 4 are out of the
four days per DS-018 C-66.  Nine steps, numbered as in DS-014 so the narration
and the script agree.
"""

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

RULE = "-" * 78
LEGEND_SHOWN = False


# --------------------------------------------------------------------------
# Loading.  Deliberately the same shape as run_data_checks.py: same flags, same
# failure messages, same refusal to infer the reference date.
# --------------------------------------------------------------------------
def plain(v):
    """Unwrap MongoDB Extended JSON.

    mongoexport writes {"$date": "..."} and {"$oid": "..."} rather than plain
    values, so a store handed over as a file looks different from the same store
    read through pymongo.  Unwrap on load and the rest of this script never has
    to know which way the rows arrived.
    """
    if isinstance(v, dict):
        for k in ("$date", "$oid", "$numberDecimal", "$numberInt",
                  "$numberLong", "$numberDouble"):
            if k in v and len(v) == 1:
                x = v[k]
                if k in ("$numberDecimal", "$numberDouble"):
                    return float(x)
                if k in ("$numberInt", "$numberLong"):
                    return int(x)
                return x
        return {k: plain(x) for k, x in v.items()}
    if isinstance(v, list):
        return [plain(x) for x in v]
    return v


class Store:
    def __init__(self, args):
        if args.mongo:
            from pymongo import MongoClient
            client = MongoClient(args.mongo)
            if args.db:
                db = client[args.db]
            else:
                try:
                    db = client.get_default_database()
                except Exception:
                    db = None
                if db is None:
                    sys.exit("The connection string names no database and --db was "
                             "not given.\nPass the database name, not the cluster "
                             "name: a URI ending /soco on\ncluster nex-dev means "
                             "--db soco.")
            self.events = list(db.ml_demo_events.find({}, {"_id": 0}))
            self.users = list(db.ml_demo_users.find({}, {"_id": 0}))
            self.orders = list(db.ml_demo_orders.find({}, {"_id": 0}))
            meta = db.ml_demo_meta.find_one({}, {"_id": 0})
            try:
                self.scores = list(db[args.scores].find({}, {"_id": 0}))
            except Exception as exc:
                print(f"WARNING  could not read {args.scores}: {type(exc).__name__}")
                self.scores = []
            self.source = f"{db.name} on the cluster"
        else:
            p = Path(args.dir)
            self.events = self._load(p / "ml_demo_events.json", required=True)
            self.users = self._load(p / "ml_demo_users.json", required=True)
            self.orders = self._load(p / "ml_demo_orders.json") or []
            meta = self._load(p / "ml_demo_meta.json")
            self.scores = self._load(p / f"{args.scores}.json") or []
            self.scores = [plain(r) for r in self.scores]
            for r in self.scores:
                r.pop("_id", None)
            self.source = str(p.resolve())

        if not meta:
            sys.exit("No manifest found. Rerun the generator; it writes ml_demo_meta.\n"
                     "The reference date must be read, not inferred.")
        self.meta = meta
        self.as_of = datetime.fromisoformat(meta["reference_date"])
        self.floor = meta["declared_floor"]
        self.threshold = meta["qualified_view_seconds"]
        self.half_life = meta["half_life_days"]
        self.handles = meta["handles"]
        self.canonical = set(meta["canonical_categories"])
        self.expected_raw = meta.get("expected_raw", {})
        self.unmappable = set(meta.get("unmappable", []))

        c = meta.get("score_store_contract", {})
        self.raw_f = c.get("raw_field", "raw")
        self.share_f = c.get("share_field", "share")
        self.count_f = c.get("event_count_field", "event_count")
        self.version_f = c.get("model_version_field", "model_version")
        self.decay_method = c.get("decay_method_name", "recency_decay")

        self.generations = self._pick_generation(args.version)

    @staticmethod
    def _load(path, required=False):
        if path.exists():
            return json.loads(path.read_text())
        if required:
            sys.exit(f"{path} is missing. Run the generator first.")
        return None

    # ---- the score store ---------------------------------------------
    def _pick_generation(self, wanted):
        """Keep one generation per method.

        The store may carry more than one model_version, because a parameter
        change writes a new generation rather than overwriting the last.  That
        is the right thing for the store and the wrong thing for a screen: a
        display that does not filter shows every generation at once and the same
        category appears twice.  Newest wins unless --version names one.
        """
        seen = defaultdict(set)
        for r in self.scores:
            seen[r.get("method", "unstated")].add(r.get(self.version_f))
        if wanted:
            self.scores = [r for r in self.scores if r.get(self.version_f) == wanted]
            if not self.scores:
                sys.exit(f"No rows carry {self.version_f} == {wanted!r}. The store holds "
                         f"{sorted({v for s in seen.values() for v in s if v})}.")
            return {m: {wanted} for m in seen}
        for method, versions in seen.items():
            real = sorted(v for v in versions if v)
            if len(real) > 1:
                newest = real[-1]
                self.scores = [r for r in self.scores
                               if r.get("method") != method
                               or r.get(self.version_f) == newest]
                print(f"NOTE     {method} carries {len(real)} generations "
                      f"{real}; showing {newest!r}. Use --version to pick another.")
        return seen

    def methods(self):
        return sorted({r.get("method", "unstated") for r in self.scores})

    def other_method(self, exclude=None):
        """Method B: whichever method is neither decay nor the decay-off run.

        Decay-off is written under its own method value so the checks can skip
        it, which means a naive "first method that is not decay" picks it up and
        step 7 compares decay against decay-with-decay-turned-off rather than
        against Method B.  Both tables then say the same thing and the step
        proves nothing.
        """
        skip = {self.decay_method, exclude} | {
            m for m in self.methods()
            if m.startswith(self.decay_method) and m != self.decay_method}
        return next((m for m in self.methods() if m not in skip), None)

    def rows_for(self, uid, method=None):
        rows = [r for r in self.scores if r.get("user_id") == uid]
        if method:
            rows = [r for r in rows if r.get("method") == method]
        return rows

    def raw(self, r):
        return r.get(self.raw_f)

    def share(self, r, siblings):
        """The stored share, or derived from raw within this method if absent."""
        if r.get(self.share_f) is not None:
            return r[self.share_f], True
        total = sum(self.raw(x) or 0 for x in siblings)
        return ((self.raw(r) or 0) / total if total else 0.0), False

    # ---- the events, for the rehearsal fallback and the counters ------
    def events_for(self, uid):
        return [e for e in self.events if e["user_id"] == uid]

    def declared(self, uid):
        return next((u["declared_interests"] for u in self.users
                     if u["user_id"] == uid), [])

    def age(self, e):
        return (self.as_of - datetime.fromisoformat(e["timestamp"])).total_seconds() / 86400

    def usable(self, e):
        """The rows the engine should be counting, by DS-008 section 8."""
        if not e.get("timestamp"):
            return False
        if self.age(e) < 0:
            return False
        if e["event_type"] == "product_view" and \
                (e.get("view_duration_seconds") or 0) < self.threshold:
            return False
        if not e.get("categories"):
            return False
        # A name outside the canonical 23 is not automatically a drop: U06's
        # List 1 names resolve through LEGACY_LABEL_MAP.  This script cannot
        # read that map, so it trusts the manifest, which records the names the
        # generator put in deliberately as unmappable.
        if all(c in self.unmappable for c in e["categories"]):
            return False
        return True

    def rehearsal(self, uid, decay=True):
        """What the generator says the raw scores are. Never shown on the day."""
        if decay and uid in self.expected_raw:
            # expected_raw is behavioural only.  DS-008 4.1 defines the stored
            # raw as floor + weighted sum, so the floor has to be added back or
            # a declared category with no activity does not appear at all --
            # which silently emptied U07, the rung 2 user, and left U05 showing
            # one category when the whole point of the step is that three
            # declared ones outrank it.
            out = dict(self.expected_raw[uid])
            for cat in self.declared(uid):
                out[cat] = out.get(cat, 0.0) + self.floor
            return out
        out = defaultdict(float)
        for e in self.events_for(uid):
            if not self.usable(e):
                continue
            f = 2 ** (-self.age(e) / self.half_life) if decay else 1.0
            for cat in e["categories"]:
                out[cat] += e["weight"] * f
        for cat in self.declared(uid):
            out[cat] += self.floor
        return dict(out)


# --------------------------------------------------------------------------
# Presentation
# --------------------------------------------------------------------------
def banner(step, title):
    """Title only.  The narration lives in the script Bernard is holding; on
    screen it is clutter, and a client reading the presenter's lines off the
    projector is worse than clutter."""
    print(f"\n{RULE}\nSTEP {step}   {title}\n{RULE}\n")


def table(headers, rows, aligns=None):
    if not rows:
        print("    (nothing to show)")
        return
    cols = len(headers)
    aligns = aligns or ["<"] * cols
    w = [len(h) for h in headers]
    for r in rows:
        for i, cell in enumerate(r):
            w[i] = max(w[i], len(str(cell)))
    line = "  " + "  ".join(f"{h:{aligns[i]}{w[i]}}" for i, h in enumerate(headers))
    print(line)
    print("  " + "  ".join("-" * w[i] for i in range(cols)))
    for r in rows:
        print("  " + "  ".join(f"{str(c):{aligns[i]}{w[i]}}" for i, c in enumerate(r)))


def rehearsal_note(s):
    global LEGEND_SHOWN
    if not LEGEND_SHOWN:
        print("  [rehearsal]  the store holds no rows for this, so the figures below are")
        print("               this script's arithmetic, not the engine's. Do not show")
        print("               these on the day; rerun once the engine has written.")
        print()
        LEGEND_SHOWN = True
    else:
        print("  [rehearsal]  figures below are this script's, not the engine's.")
        print()


def profile(s, uid, method=None, label=""):
    """One user's category table: raw, share, event count. The core view."""
    method = method or s.decay_method
    rows = s.rows_for(uid, method)
    if rows:
        out = []
        for r in sorted(rows, key=lambda x: -(s.raw(x) or 0)):
            sh, stored = s.share(r, rows)
            out.append([r.get("category"), f"{s.raw(r):.2f}", f"{sh:.3f}" + ("" if stored else " *"),
                        r.get(s.count_f, "--"), r.get(s.version_f, "--")])
        table([f"{uid} category" + (f"  {label}" if label else ""), "raw", "share",
               "events", "version"], out, ["<", ">", ">", ">", "<"])
        if any(r.get(s.share_f) is None for r in rows):
            print(f"    * share derived by this script; the engine did not store "
                  f"a {s.share_f!r} field")
        print(f"    method {method}   computed_at "
              f"{rows[0].get('computed_at', 'not stored')}")
        return True
    rehearsal_note(s)
    want = s.rehearsal(uid)
    total = sum(want.values()) or 1
    out = [[c, f"{v:.2f}", f"{v / total:.3f}", "--", "--"]
           for c, v in sorted(want.items(), key=lambda kv: -kv[1])]
    table([f"{uid} category" + (f"  {label}" if label else ""), "raw", "share",
           "events", "version"], out, ["<", ">", ">", ">", "<"])
    return False


# --------------------------------------------------------------------------
# The nine steps
# --------------------------------------------------------------------------
def step_1(s):
    banner(1, "The opening statement")
    m = s.meta
    table(["", ""], [
        ["dataset", s.source],
        ["reference date", s.as_of.isoformat()],
        ["seed", m["seed"]],
        ["narrated users", m["narrated_users"]],
        ["filler users", m["filler_users"]],
        ["events", m["events_total"]],
        ["categories", f"{len(s.canonical)} from {m['canonical_source']}"],
        ["half life", f"P-04 = {s.half_life} days"],
        ["declared floor", f"P-25 = {s.floor}"],
        ["qualified view", f"P-02 = {s.threshold}s"],
        ["score store", f"{len(s.scores)} rows, methods {s.methods() or 'none yet'}"],
    ])


def step_2(s):
    banner(2, "What the model produces, and why the share exists")
    # U01 and the U12/U13 pair were separate steps until the narration put them
    # in one breath: the share is introduced on U01's table and then justified
    # by the pair, so splitting them made the presenter say "share" twice.
    # The remaining step numbers are unchanged, because DS-014, DS-015 and the
    # running order all refer to steps by number and renumbering buys tidiness
    # at the cost of a class of error.
    profile(s, "U01")
    print(f"\n    declared at signup: {s.declared('U01')}")
    print(f"    each contributes a floor of {s.floor}, which does not decay (P-26 = No)")

    print(f"\n{'- ' * 39}")
    for uid in ("U12", "U13"):
        print(f"\n  {uid}: {len(s.events_for(uid))} events, "
              f"{len(s.declared(uid))} declared interests")
        profile(s, uid)
    a, b = s.rows_for("U12", s.decay_method), s.rows_for("U13", s.decay_method)
    if a and b:
        ta, tb = sum(s.raw(r) for r in a), sum(s.raw(r) for r in b)
        print(f"\n    raw totals differ {ta / tb:.1f}x; the share columns agree")


def step_4(s, decay_off_method=None):
    banner(4, "U04 — with decay, and without")
    print("  decay ON")
    profile(s, "U04", s.decay_method, "decay on")
    off = decay_off_method or next(
        (m for m in s.methods() if "inf" in m or "off" in m or "no_decay" in m), None)
    print("\n  decay OFF")
    if off:
        profile(s, "U04", off, "decay off")
    else:
        rehearsal_note(s)
        want = s.rehearsal("U04", decay=False)
        total = sum(want.values()) or 1
        table(["U04 category  decay off", "raw", "share"],
              [[c, f"{v:.2f}", f"{v / total:.3f}"]
               for c, v in sorted(want.items(), key=lambda kv: -kv[1])],
              ["<", ">", ">"])
        print("    no decay-off method found in the store. Pass --decay-off-method")
        print("    once the engine writes it under its own method value.")
    old, new = s.handles["electronics"], s.handles["home"]
    print(f"\n    watch {old} against {new}: the order must reverse between the two tables")


def step_5(s):
    banner(5, "U07, then U05 — cold start and the floor")
    print(f"  U07: {len(s.declared('U07'))} declared interests, "
          f"{len(s.events_for('U07'))} events — rung 2")
    profile(s, "U07")
    print(f"\n  U05: {len(s.declared('U05'))} declared, "
          f"{len(s.events_for('U05'))} events aged 90-120 days in a fourth category")
    profile(s, "U05")
    print(f"\n    three categories with no activity outrank one with "
          f"{len(s.events_for('U05'))} events")


def step_6(s):
    banner(6, "U11 — the bottom of the ladder")
    print(f"  U11: {len(s.declared('U11'))} declared interests, "
          f"{len(s.events_for('U11'))} events")
    rows = s.rows_for("U11")
    if rows:
        profile(s, "U11")
        if not any("rung" in str(k).lower() for r in rows for k in r):
            print("\n    WARNING  no rung recorded on these rows. Step 6's narration says")
            print("             which rung served the user; the read path must return it.")
    else:
        # The reasoning -- stored nothing because the denominator was zero, and
        # rung 3 is served by the read path rather than read from the store --
        # is in the narration document. On screen it is four lines the presenter
        # has to talk over.
        print("\n    no stored score. Rung 3 serves:")
        pop = defaultdict(float)
        for e in s.events:
            if s.usable(e) and s.age(e) <= 30:
                for c in e["categories"]:
                    pop[c] += e["weight"]
        print()
        top = sorted(pop.items(), key=lambda kv: -kv[1])[:8]
        tot = sum(pop.values()) or 1
        table(["popularity, last 30 days", "weight", "share"],
              [[c, f"{v:.0f}", f"{v / tot:.3f}"] for c, v in top], ["<", ">", ">"])


def step_7(s, decay_off_method=None):
    banner(7, "U14 under both methods")
    b = s.other_method(decay_off_method)
    if not b:
        print("  Method B has not written to the store yet, so there is nothing to")
        print("  compare against. This step needs both methods; rerun after task 15.")
        print(f"  The store holds: {s.methods() or 'no rows at all'}")
        return
    a_rows = s.rows_for("U14", s.decay_method)
    b_rows = s.rows_for("U14", b)
    cats = sorted({r["category"] for r in a_rows + b_rows})
    out = []
    for c in cats:
        ra = next((r for r in a_rows if r["category"] == c), None)
        rb = next((r for r in b_rows if r["category"] == c), None)
        sa = f"{s.share(ra, a_rows)[0]:.3f}" if ra else "--"
        sb = f"{s.share(rb, b_rows)[0]:.3f}" if rb else "--"
        out.append([c, f"{s.raw(ra):.2f}" if ra else "--", sa,
                    f"{s.raw(rb):.2f}" if rb else "--", sb])
    short = lambda m: m if len(m) <= 13 else m[:12] + "."
    table(["U14 category", f"{short(s.decay_method)} raw", "share",
           f"{short(b)} raw", "share"], out, ["<", ">", ">", ">", ">"])
    print("\n    two bursts of forty events, centred at day 28 and day 32, neither")
    print("    straddling the thirty day boundary. Under windows they fall either side")
    print("    and differ by half; under decay they are within ten percent.")


def step_8(s):
    banner(8, "U16 next to U17 — the purchase reversal")
    cat = s.handles["fashion"]
    a = s.rows_for("U16", s.decay_method)
    b = s.rows_for("U17", s.decay_method)
    if a and b:
        ra = next((r for r in a if r["category"] == cat), None)
        rb = next((r for r in b if r["category"] == cat), None)
        if ra and rb:
            diff = s.raw(ra) - s.raw(rb)
            print(f"  {cat}:  U16 {s.raw(ra):.2f}   U17 {s.raw(rb):.2f}   "
                  f"difference {diff:.2f}")
    else:
        rehearsal_note(s)
        wa, wb = s.rehearsal("U16"), s.rehearsal("U17")
        print(f"  {cat}:  U16 {wa.get(cat, 0):.2f}   U17 {wb.get(cat, 0):.2f}   "
              f"difference {wa.get(cat, 0) - wb.get(cat, 0):.2f}")
    o = next((x for x in s.orders if x.get("cancelled_at")), None)
    if o:
        placed = (s.as_of - datetime.fromisoformat(o["placed_at"])).days
        cancel = (s.as_of - datetime.fromisoformat(o["cancelled_at"])).days
        w = s.meta["event_weights"]["purchase"]
        print(f"\n    order placed {placed}d ago, cancelled {cancel}d ago")
        table(["term", "arithmetic", "value"], [
            ["purchase", f"{w} x 2^(-{placed}/{s.half_life})",
             f"+{w * 2 ** (-placed / s.half_life):.2f}"],
            ["reversal, aged from the order",
             f"{w} x 2^(-{placed}/{s.half_life})",
             f"-{w * 2 ** (-placed / s.half_life):.2f}"],
            ["reversal, aged from the cancellation  WRONG",
             f"{w} x 2^(-{cancel}/{s.half_life})",
             f"-{w * 2 ** (-cancel / s.half_life):.2f}"],
        ], ["<", "<", ">"])
        print("\n    the difference above must equal the purchase term, and no raw")
        print("    anywhere may be negative. That is check 7.")
    neg = [r for r in s.scores if (s.raw(r) or 0) < 0]
    if neg:
        print(f"\n    WARNING  {len(neg)} rows carry a negative raw: "
              f"{[(r['user_id'], r['category']) for r in neg[:3]]}")


def step_9(s):
    banner(9, "U02, U08 and U10 — what the model refuses to count")
    out = []
    for uid, why in (("U02", "sub-threshold views"),
                     ("U08", "unresolved categories"),
                     ("U10", "timestamp failures")):
        ev = s.events_for(uid)
        short = sum(1 for e in ev if e["event_type"] == "product_view"
                    and (e.get("view_duration_seconds") or 0) < s.threshold)
        unres = sum(1 for e in ev if e.get("categories")
                    and all(c in s.unmappable for c in e["categories"]))
        nots = sum(1 for e in ev if not e.get("timestamp"))
        fut = sum(1 for e in ev if e.get("timestamp") and s.age(e) < 0)
        out.append([uid, why, len(ev), sum(1 for e in ev if s.usable(e)),
                    short, unres, nots + fut])
    table(["user", "demonstrates", "events", "counted", "short view",
           "no category", "bad time"], out, ["<", "<", ">", ">", ">", ">", ">"])
    print("\n    three counters, not one. The engine's own counters should match this")
    print("    table; if it reports a single 'dropped' figure, step 9 has nothing to show.")


STEPS = {1: step_1, 2: step_2, 4: step_4, 5: step_5,
         6: step_6, 7: step_7, 8: step_8, 9: step_9}

# --step 3 used to be the U12/U13 pair, now folded into step 2.  Kept as an
# alias rather than removed, so a command written down last week still works.
ALIASES = {3: 2}

# The order the narration uses, which is not numeric order.  The step numbers
# are DS-014's and are kept because DS-015, the running order and the change
# register all refer to steps by number.  But the presentation puts the
# cancelled order and the drop counters before the two-method comparison,
# because the comparison leads into "what it needs now is users" and is the
# closer.  Running numerically put U14 before U16 and U17 and left the script
# and the narration disagreeing on a dry run.
PRESENTATION_ORDER = [1, 2, 4, 5, 6, 8, 9, 7]


def main():
    ap = argparse.ArgumentParser(description="The DS-014 running order, on screen.")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--dir", help="folder holding the generator's JSON files")
    src.add_argument("--mongo", help="connection string")
    ap.add_argument("--db", help="database name, not the cluster name")
    ap.add_argument("--scores", default="ml_user_interest_scores_demo")
    ap.add_argument("--step", type=int, choices=sorted(set(STEPS) | set(ALIASES)),
                    help="show one step rather than all eight")
    ap.add_argument("--version", help="show this model_version rather than the newest")
    ap.add_argument("--decay-off-method",
                    help="the method value the engine writes decay-off scores under")
    ap.add_argument("--numeric", action="store_true",
                    help="run in step-number order rather than narration order")
    a = ap.parse_args()

    s = Store(a)
    print(f"\n{RULE}\nSOCO M1  ·  interest and profile model  ·  demonstration")
    print(f"{RULE}")
    print(f"source           {s.source}")
    print(f"reference date   {s.as_of.isoformat()}")
    print(f"score store      {len(s.scores)} rows"
          + (f", methods {s.methods()}" if s.scores else "  (engine has not run)"))
    if s.meta.get("canonical_is_placeholder"):
        print("WARNING          the vocabulary is still the placeholders; "
              "regenerate with --categories")

    order = sorted(STEPS) if a.numeric else PRESENTATION_ORDER
    for n in ([ALIASES.get(a.step, a.step)] if a.step else order):
        if n in (4, 7):
            STEPS[n](s, a.decay_off_method)
        else:
            STEPS[n](s)
    print(f"\n{RULE}")
    if not s.scores:
        print("Every figure above marked [rehearsal] is this script's arithmetic.")
        print("Rerun once the engine has written to the store.")
    print()


if __name__ == "__main__":
    main()
