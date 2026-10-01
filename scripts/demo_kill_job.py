"""Act out the ENG-07 check with a real kill: "Kill a job halfway: requests keep
reading the previous batch. ml_job_runs shows the failure."

    ML_MONGO_DB=reco_demo .venv/bin/python scripts/demo_kill_job.py

Runs only against reco_demo (it refuses any other database). Uses four made-up
users, DEMO-U1..DEMO-U4, and the interest score collection:

  1. a complete batch: everyone "fashion"           -> current
  2. a slow batch ("beauty"), one user a second, killed with SIGKILL after ~2.5 s
  3. what a request reads now                        -> still "fashion"
  4. the next night's batch ("travel")               -> the killed run is recorded as failed
"""

from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from reco.config import get_settings  # noqa: E402
from reco.jobs.batches import run_batch  # noqa: E402
from reco.store import connection as store_conn  # noqa: E402
from reco.store import writers  # noqa: E402
from reco.store.scores import InterestScore, Method, Window, utc_now  # noqa: E402

METHOD = str(Method.RECENCY_DECAY)
USERS = [f"DEMO-U{n}" for n in range(1, 5)]


async def batch(settings, category: str, pause: float = 0.0) -> dict:
    async def work(job_run_id: str) -> int:
        written = 0
        for user in USERS:
            score = InterestScore(user_id=user, category=category, raw=1.0, share=1.0, event_count=1,
                                  method=Method.RECENCY_DECAY, model_version=settings.model_version,
                                  window=Window.ALL, computed_at=utc_now(), job_run_id=job_run_id)
            written += await writers.upsert_user_scores(settings, user, [score])
            if pause:
                print(f"    wrote {user}", flush=True)
                await asyncio.sleep(pause)
        return written

    return await run_batch(settings, job="interest", slot="interest", method=METHOD,
                           collection=settings.scores_collection, data_window={"from": None, "to": utc_now()}, work=work)


async def reads(settings) -> str:
    seen = []
    for user in USERS[:2]:
        held = await writers.read_user_scores(settings, user, METHOD)
        seen.append(f"{user}={'/'.join(s.category for s in held) or '-'}")
    return ", ".join(seen)


async def runs(settings) -> None:
    for r in (await writers.read_job_runs(settings, limit=3))[::-1]:
        print(f"    {r['_id'][:8]}  {r['outcome']:9} {'CURRENT' if r.get('is_current') else '       '}  {(r.get('error') or '')[:50]}")


async def main(slow: bool) -> int:
    sys.stdout.reconfigure(line_buffering=True)
    settings = get_settings()
    if settings.ml_mongo_db != "reco_demo":
        print("refusing: run with ML_MONGO_DB=reco_demo")
        return 2
    store_conn.init_client(settings)
    try:
        await writers.ensure_engine_collections(settings)
        await writers.ensure_indexes(settings)
        if slow:
            await batch(settings, "beauty", pause=1.0)
            return 0
        print("1. a complete batch (everyone 'fashion')")
        await batch(settings, "fashion")
        print(f"   a request reads: {await reads(settings)}")
        print("2. a slow batch ('beauty'), killed halfway")
        child = subprocess.Popen([sys.executable, __file__, "--slow-batch"], env=os.environ.copy())
        time.sleep(2.5)
        child.send_signal(signal.SIGKILL)
        child.wait()
        print("   killed (SIGKILL: nothing in the job could run after it)")
        print("3. straight after the kill")
        print(f"   a request reads: {await reads(settings)}")
        await runs(settings)
        print("4. the next night's batch ('travel')")
        await batch(settings, "travel")
        print(f"   a request reads: {await reads(settings)}")
        await runs(settings)
    finally:
        await store_conn.close_client()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main("--slow-batch" in sys.argv)))
