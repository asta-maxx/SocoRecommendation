"""The M1 check script. ENG-11 (Build List v1.3).

    .venv/bin/python scripts/check_m1.py            # run, print PASS/FAIL, save the output
    .venv/bin/python scripts/check_m1.py --keep     # keep the two throwaway databases afterwards

Loads the constructed test users (tests/m1_dataset.py) into a throwaway platform
database, then runs the engine for real on them, the way the servers will:

    python -m reco.jobs sync         the engine sync copies them (ENG-04)
    python -m reco.jobs interest     M1, both methods, from the copies (ENG-10)
    python -m reco.jobs popularity   the ladder's rung 3 (ENG-09)

and prints PASS or FAIL for each of the row's 11 checks. The full output is saved
to Tracing/checks/ENG-11_<date>.md (the Home sheet: "<item ID>_<date>").

Both databases are throwaway, on the ENGINE cluster (ML_MONGO_URI; the platform
login is read-only and is never used): reco_m1_check and reco_m1_check_platform.
SOCO's data and the engine's own databases are never touched. Exit 0 only if all
11 pass.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

ENGINE_DB = "reco_m1_check"
PLATFORM_DB = "reco_m1_check_platform"

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")
os.environ.update({  # before the engine's settings are read
    "APP_MONGO_URI": os.environ.get("ML_MONGO_URI", ""), "APP_MONGO_DB": PLATFORM_DB, "ML_MONGO_DB": ENGINE_DB,
    "DATA_PROFILE": "live",
})

from pymongo import AsyncMongoClient  # noqa: E402

from reco.config import get_settings, live, sync  # noqa: E402
from reco.fallback import read_path  # noqa: E402
from reco.platform import connection as platform_conn  # noqa: E402
from reco.slots.interest import copies, interest_decay  # noqa: E402
from reco.slots.interest.context import ScoringContext  # noqa: E402
from reco.store import connection as store_conn  # noqa: E402
from reco.store.scores import Method  # noqa: E402
from tests.m1_dataset import ELEC, HOME, PETS, build_m1_dataset  # noqa: E402

PY = sys.executable
lines: list[str] = []
results: list[bool] = []


def say(text: str = "") -> None:
    print(text)
    lines.append(text)


def check(number: int, label: str, ok: bool, detail: str = "") -> None:
    results.append(ok)
    say(f"  {'PASS' if ok else 'FAIL'}  {number:>2}. {label}")
    if detail:
        say(f"           {detail}")


def job(name: str) -> None:
    done = subprocess.run([PY, "-m", "reco.jobs", name], cwd=ROOT, env=os.environ, capture_output=True, text=True)
    outcome = "succeeded" if done.returncode == 0 else f"FAILED (exit {done.returncode})"
    say(f"  python -m reco.jobs {name:<11} {outcome}")
    if done.returncode:
        say("    " + (done.stdout + done.stderr).strip().splitlines()[-1][:300])


ASSIGN = """
import sys
from reco.config import live
from reco.slots.assignment import SLOT_NAMES, assign
ids = [f"check-user-{n}" for n in range(10000)]
t = live.current()
for slot in SLOT_NAMES:
    print(slot, "".join(str(int(assign(slot, u, t).method == getattr(t.slots, slot).method_two)) for u in ids))
"""


def assignments() -> dict[str, str]:
    out = subprocess.run([PY, "-c", ASSIGN], cwd=ROOT, env=os.environ, capture_output=True, text=True, check=True).stdout
    return dict(line.split(" ", 1) for line in out.strip().splitlines())


async def main(keep: bool) -> int:
    now = datetime.now(timezone.utc)
    settings = get_settings()
    say(f"# ENG-11: M1 check script, {date.today().isoformat()}")
    say()
    say(f"Engine database {ENGINE_DB}, platform database {PLATFORM_DB} (both throwaway, engine cluster); "
        f"model_version {settings.model_version}.")
    say()
    say("```")
    dataset, users, expect = build_m1_dataset(now)
    name_of = {v: k for k, v in users.items()}
    client = AsyncMongoClient(settings.ml_mongo_uri, tz_aware=True)
    try:
        await client.drop_database(ENGINE_DB)
        await client.drop_database(PLATFORM_DB)
        for collection, documents in dataset.items():
            if documents:
                await client[PLATFORM_DB][collection].insert_many(documents)
        say(f"Loaded {sum(map(len, dataset.values()))} constructed documents; {len(users)} users.")
        for name in ("sync", "interest", "popularity"):
            job(name)
        say()

        store_conn.init_client(settings)
        platform_conn.init_client(settings)
        await sync.load_at_start(settings)
        engine = client[ENGINE_DB]
        rows = await engine["ml_user_interest_scores"].find({}).to_list(None)
        by = lambda method: {  # noqa: E731
            name_of.get(r["user_id"], r["user_id"]): {} for r in rows if r["method"] == method}
        scores = {m: by(m) for m in (Method.RECENCY_DECAY, Method.TIME_WINDOWS)}
        for r in rows:
            if r["method"] in scores:
                scores[r["method"]][name_of.get(r["user_id"], r["user_id"])][r["category"]] = r
        decay = scores[Method.RECENCY_DECAY]

        # 1
        missing = sorted(u for u in expect["scored"] for m in scores if u not in scores[m])
        extra = sorted(u for m in scores for u in scores[m] if u in expect["not_scored"])
        check(1, "Scores exist for every user with a mappable category", not missing and not extra,
              f"missing {missing}; scored though nothing mappable {extra}" if missing or extra else
              f"{len(expect['scored'])} users scored under both methods; {len(expect['not_scored'])} correctly not")
        # 2
        sums = {(m, u): sum(r["share"] for r in cats.values()) for m in scores for u, cats in scores[m].items()}
        bad = {k: round(v, 9) for k, v in sums.items() if abs(v - 1) > 1e-9}
        check(2, "Share sums to 1 per user", not bad and bool(sums), f"off: {bad}" if bad else f"{len(sums)} user-method maps")
        # 3
        low = [(name_of.get(r["user_id"]), r["category"], r["raw"]) for r in rows if r["raw"] < 0]
        neg = decay.get("negative", {})
        clipped = HOME in neg and neg[HOME]["raw"] == 0 and neg[PETS]["share"] == 1
        check(3, "Raw is never below 0", not low and clipped,
              f"below 0: {low}" if low else "the Hide user's Home & Living is clipped to 0 (3 - 5), Pets keeps share 1")
        # 4
        d = decay.get("decay", {})
        on = d.get(HOME, {}).get("raw", 0) > d.get(ELEC, {}).get("raw", 0)
        inputs = await copies.read_inputs(settings, now)
        ctx = ScoringContext(tunables=live.current().m1(), declared_interests=[], now=now, decay_enabled=False)
        plain, _ = interest_decay.score(inputs.events_by_user.get(users["decay"], []), ctx)
        off = plain.get(ELEC, 0) > plain.get(HOME, 0)
        check(4, "Decay on: Home & Living above Electronics; decay off: the order flips", on and off,
              f"on: Home & Living {d.get(HOME, {}).get('raw', 0):.2f} vs Electronics {d.get(ELEC, {}).get('raw', 0):.2f}; "
              f"off: Home & Living {plain.get(HOME, 0):.2f} vs Electronics {plain.get(ELEC, 0):.2f}")
        # 5
        floor = [scores[m].get("floor", {}).get(PETS, {}).get("raw") for m in scores]
        check(5, "The declared floor is present and not decayed", floor == [10.0, 10.0],
              f"Pets raw (decay, windows): {floor}; declared, no Pets action; one Electronics click 200 days ago")
        # 6
        c = decay.get("cancelled", {})
        check(6, "A bought-then-cancelled order nets to exactly zero",
              c.get(ELEC, {}).get("raw", 0) == 0 and PETS in c and inputs.skipped.get("order_reversed", 0) >= 2,
              f"Electronics raw {c.get(ELEC, {}).get('raw', 0)} (one Cancelled, one Returned order); "
              f"orders reversed {inputs.skipped.get('order_reversed', 0)}")
        # 7
        cats = {r["category"] for r in rows}
        allowed = set(live.current().lists.category_map.values()) | set(_vocabulary(settings))
        u7 = set(decay.get("unmappable", {}))
        check(7, "Unmappable and malformed categories are dropped", u7 == {HOME} and cats <= allowed,
              f"the user's categories: {sorted(u7)}; categories outside the 23 anywhere: {sorted(cats - allowed)}; "
              f"actions dropped for no category: {inputs.read_stats.unresolved_category}")
        # 8
        v = decay.get("views", {}).get(PETS, {})
        check(8, "event_count excludes views under 3 seconds", v.get("event_count") == 1,
              f"Pets event_count {v.get('event_count')} (views of 2.0 s, 2.999 s, then 4 s and 5 s on one post)")
        # 9
        both = all(u in scores[m] for u in expect["scored"] for m in scores)
        stamped = all(r.get("method") in (Method.RECENCY_DECAY, Method.TIME_WINDOWS)
                      and r.get("model_version") == settings.model_version for r in rows)
        check(9, "Both methods are written with method name and model_version", both and stamped and bool(rows),
              f"{len(rows)} rows: methods {sorted({r['method'] for r in rows})}, model_version {sorted({r['model_version'] for r in rows})}")
        # 10
        got = {}
        for name, step in expect["rungs"].items():
            when = now + timedelta(hours=49) if name == "rung4" else now  # rung 4: the score is 49 hours old
            if name == "rung5":
                real = read_path.read_user_scores

                async def down(*args, **kwargs):
                    raise ConnectionError("engine store down (simulated)")
                read_path.read_user_scores = down
                try:
                    got[name] = (await read_path.get_profile(settings, users[name], Method.RECENCY_DECAY, when)).fallback_step
                finally:
                    read_path.read_user_scores = real
            else:
                got[name] = (await read_path.get_profile(settings, users[name], Method.RECENCY_DECAY, when)).fallback_step
        check(10, "Each fallback rung is reported for its test user", got == expect["rungs"],
              ", ".join(f"{k}: {v or 'none (rung 1)'}" for k, v in got.items()))
        # 11
        first, second = assignments(), assignments()
        splits = {slot: abs(bits.count("1") / len(bits) * 100 - getattr(live.current().slots, slot).split) for slot, bits in first.items()}
        check(11, "Method assignment is stable across restarts; split within 2 points",
              first == second and all(gap <= 2 for gap in splits.values()),
              f"two separate processes, 10,000 ids: {'identical' if first == second else 'DIFFERENT'}; "
              + ", ".join(f"{s} {g:.2f} points from the split" for s, g in splits.items()))
        say()
        passed = sum(results)
        say(f"Result: {passed} of {len(results)} passed")
        say("```")
    finally:
        await platform_conn.close_client()
        await store_conn.close_client()
        if not keep:
            await client.drop_database(ENGINE_DB)
            await client.drop_database(PLATFORM_DB)
        await client.close()
    out = ROOT / "Tracing" / "checks" / f"ENG-11_{date.today().isoformat()}.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Saved {out.relative_to(ROOT)}")
    return 0 if all(results) and len(results) == 11 else 1


def _vocabulary(settings) -> list[str]:
    from reco.platform.readers import vocabulary

    return list(vocabulary(settings).canonical)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--keep", action="store_true", help="keep the two throwaway databases")
    raise SystemExit(asyncio.run(main(parser.parse_args().keep)))
