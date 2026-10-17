"""M8 promoter score, the nightly job. ENG-16.

    python -m reco.jobs promoter

Reads the engine's copies (postevents, orders, return requests) and the platform's
accounts, posts, products, follows and blocks; works out each promoter's
components; scores both methods (reco.slots.promoter.score); writes each method as
one ENG-07 batch into ml_promoter_scores; on the 1st of a month copies both into
ml_promoter_scores_monthly.

Who is scored (Build List v1.4 ENG-16): active; not suspended or removed (the
platform's moderation state or store status, a restriction_level of suspended or
removed once DB-08 exists, a confirmed fraud case at level 4 or 5); not on the
exemption or test-account lists; account at least 14 days old; at least one
original post (isRepost false, not a seed post) in the last 90 days; and qualified
views on their original posts in the last 30 days (no views: not scored, never
scored as zero). Stores with original posts are scored like any promoter. A
promoter's main category is the category on most of their original posts in the
last 90 days (ties: by name).

Orders through their posts: the order's post led back to its original (ENG-30
point 3); the sale is credited to the original's author. A broken chain credits
nobody. A buyer who is the same person as that author (ENG-30 point 2) is left
out, as are test accounts' orders and orders on seed posts. Only orders created in
the last 90 days count. What became of each order: reco.slots.promoter.sales.

Return requests (ENG-30 point 7): if the copy is not current, the job does not run
(the previous batches stay current) and an error is logged for the service owner;
if returnrequests cannot be read at all, the commerce components stay off.
"""

from __future__ import annotations

import logging
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Any

from reco.config import Settings, live
from reco.config.accounts import is_exempt, test_account_ids
from reco.jobs.batches import recorded_run, run_batch
from reco.platform import fetch
from reco.platform.people import People, promoter_of
from reco.platform.reposts import resolve_originals
from reco.slots.promoter import sales
from reco.slots.promoter.score import PromoterInput, PromoterSettings, Scored, score_promoters
from reco.store import promoter as store
from reco.store import writers
from reco.store.scores import utc_now

logger = logging.getLogger("reco.job")

POSTS_DAYS = 90
VIEWS_DAYS = 30
SALES_DAYS = 90
WEEKS = 8
MIN_AGE_DAYS = 14
ENGAGEMENTS = ("like", "save", "share", "comment")
#: restriction_level values (DB-08, once it exists) and fraud levels that mean "not scored".
NOT_SCORED_RESTRICTIONS = ("suspended", "removed")
SUSPENDED_LEVEL = 4
_IDS_PER_READ = 500


def data_window(anchor: datetime) -> dict[str, datetime]:
    return {"from": anchor - timedelta(days=POSTS_DAYS), "to": anchor}


def methods() -> tuple[str, str]:
    slot = live.current().slots.promoter_score
    return slot.method_one, slot.method_two


async def _posts_by_id(settings: Settings, ids: set[str], known: dict[str, Any]) -> dict[str, Any]:
    missing = sorted(i for i in ids if i and i not in known)
    for start in range(0, len(missing), _IDS_PER_READ):
        known |= await fetch.read_posts(settings, missing[start:start + _IDS_PER_READ])
    return known


async def compute(settings: Settings, anchor: datetime, commerce_readable: bool) -> tuple[dict[str, Scored], dict[str, Any]]:
    """Every scored promoter, both methods, and the counts to report."""
    tunables = live.current()
    report: dict[str, Any] = {}
    tests = test_account_ids(anchor.date())
    view_ms = tunables.events.qualified_view_seconds * 1000

    users = {u.user_id: u for u in await fetch.read_records(settings, "user")}
    businesses = {b.business_id: b for b in await fetch.read_records(settings, "business")}
    people = People.of(businesses.values())
    fraud = await store.read_confirmed_restrictions(settings, anchor)

    # --- original posts of the last 90 days, by author ------------------------------
    recent = await fetch.read_posts_since(settings, anchor - timedelta(days=POSTS_DAYS))
    known: dict[str, Any] = {p.post_id: p for p in recent}
    originals_by_author: dict[str, list[Any]] = defaultdict(list)
    for post in recent:
        if not post.is_repost and not post.is_seed and post.created_at is not None and post.created_at <= anchor:
            originals_by_author[post.author_id].append(post)

    # --- who is scored -----------------------------------------------------------------
    not_scored: Counter = Counter()
    candidates: dict[str, str] = {}  # promoter id -> kind
    reposters = {p.author_id for p in recent if p.is_repost} - set(originals_by_author)
    not_scored["only_reposts"] = len(reposters)
    for author in originals_by_author:
        account = users.get(author) or businesses.get(author)
        kind = "user" if author in users else "business"
        if account is None:
            not_scored["account_not_found"] += 1
        elif not account.is_active:
            not_scored["not_active"] += 1
        elif (getattr(account, "restriction_level", None) or "") in NOT_SCORED_RESTRICTIONS:
            not_scored["restricted"] += 1
        elif fraud.get(author, 0) >= SUSPENDED_LEVEL:
            not_scored["fraud_suspended_or_removed"] += 1
        elif author.lower() in tests:
            not_scored["test_account"] += 1
        elif is_exempt(author, anchor.date()):
            not_scored["exempt"] += 1
        elif account.created_at is None or anchor - account.created_at < timedelta(days=MIN_AGE_DAYS):
            not_scored["younger_than_14_days"] += 1
        else:
            candidates[author] = kind

    # --- main category and consistency -------------------------------------------------
    main_category: dict[str, str | None] = {}
    weeks_posted: dict[str, int] = {}
    for author in candidates:
        posts = originals_by_author[author]
        counts = Counter(c for p in posts for c in p.categories)
        main_category[author] = min(counts, key=lambda c: (-counts[c], c)) if counts else None
        weeks_posted[author] = sum(
            1 for k in range(WEEKS)
            if any(anchor - timedelta(days=7 * (k + 1)) <= p.created_at < anchor - timedelta(days=7 * k) for p in posts))

    # --- views and engagement on their original posts ------------------------------------
    rows = await store.read_promoter_event_rows(settings, anchor - timedelta(days=SALES_DAYS))
    await _posts_by_id(settings, {str(r["post_id"]) for r in rows}, known)
    views_30: dict[str, set[tuple[str, str]]] = defaultdict(set)
    views_90: dict[str, set[tuple[str, str]]] = defaultdict(set)
    engaged_30: Counter = Counter()
    skipped: Counter = Counter()
    for row in rows:
        post = known.get(str(row["post_id"]))
        viewer, at = str(row.get("user_id") or ""), row.get("created_at")
        if post is None or post.is_repost or post.is_seed or post.author_id not in candidates:
            continue
        author = post.author_id
        if not viewer or at is None or at > anchor:
            skipped["incomplete_or_future"] += 1
        elif row.get("is_self") or people.same_person(viewer, author):
            skipped["own_post"] += 1
        elif viewer.lower() in tests:
            skipped["test_account"] += 1
        elif row.get("actor") == "business":
            skipped["not_a_user"] += 1
        elif row["event_type"] == "view":
            if (row.get("dwell_ms") or 0) < view_ms:
                skipped["view_not_qualified"] += 1
                continue
            views_90[author].add((viewer, post.post_id))
            if at >= anchor - timedelta(days=VIEWS_DAYS):
                views_30[author].add((viewer, post.post_id))
        elif row["event_type"] in ENGAGEMENTS and at >= anchor - timedelta(days=VIEWS_DAYS):
            engaged_30[author] += 1

    # --- followers (Kala, 16 Oct) -------------------------------------------------------
    blocks = await fetch.read_all_blocks(settings)
    blocked = {frozenset((b.blocker_id, b.blocked_id)) for b in blocks}
    followers: Counter = Counter()
    for follow in await fetch.read_records(settings, "follow"):
        target, who = follow.followed_id, follow.follower_id
        if target not in candidates or people.same_person(who, target) or who.lower() in tests:
            continue
        if frozenset((who, target)) in blocked:
            continue
        followers[target] += 1

    # --- orders through their posts -----------------------------------------------------
    rules = sales.SaleRules.from_tunables(tunables)
    orders = [o for o in await store.read_order_rows(settings)
              if o.get("post_id") and o.get("created_at") is not None
              and anchor - timedelta(days=SALES_DAYS) <= o["created_at"] <= anchor]
    await _posts_by_id(settings, {str(o["post_id"]) for o in orders}, known)
    order_posts = [known[str(o["post_id"])] for o in orders if str(o["post_id"]) in known]
    originals, repost_report, chain = await resolve_originals(settings, order_posts)
    known |= {k: v for k, v in chain.items() if v is not None}
    product_ids = sorted({str(o["product_id"]) for o in orders if o.get("product_id")})
    products: dict[str, Any] = {}
    for start in range(0, len(product_ids), _IDS_PER_READ):
        for product in await fetch.read_where(settings, "product", "_id", product_ids[start:start + _IDS_PER_READ]):
            products[product.product_id] = product
    open_requests = await writers.read_open_return_orders(settings)
    order_skipped: Counter = Counter()
    outcomes: Counter = Counter()
    completed_value: Counter = Counter()
    completed_count: Counter = Counter()
    final_count: Counter = Counter()
    bad_count: Counter = Counter()
    fallback_windows = 0
    promoter_differs = 0
    for order in orders:
        post = known.get(str(order["post_id"]))
        original_id = originals.get(str(order["post_id"])) if post is not None else None
        original = known.get(original_id) if original_id else None
        buyer = str(order.get("buyer_id") or "")
        if post is None:
            order_skipped["post_not_found"] += 1
        elif original is None:
            order_skipped["no_original"] += 1  # a broken chain credits nobody (logged by reposts)
        elif post.is_seed or original.is_seed:
            order_skipped["seed_post"] += 1
        elif buyer.lower() in tests:
            order_skipped["test_account"] += 1
        elif people.same_person(buyer, original.author_id):
            order_skipped["self_purchase"] += 1  # the same person as the author (ENG-30 point 2)
        elif original.author_id not in candidates:
            order_skipped["author_not_scored"] += 1
        else:
            author = original.author_id
            if promoter_of(order, {post.post_id: post.author_id}) != author:
                promoter_differs += 1  # a repost: credited to the original's author, not the reposter
            window, fallback = sales.return_window_days(products.get(str(order.get("product_id"))),
                                                        tunables.commerce.return_window_fallback_days)
            fallback_windows += fallback
            outcome = sales.sale_outcome(order, now=anchor, window_days=window, rules=rules, open_requests=open_requests)
            outcomes[outcome] += 1
            if outcome == sales.COMPLETED:
                completed_value[author] += float(order.get("value") or 0)
                completed_count[author] += 1
            if outcome in sales.FINAL:
                final_count[author] += 1
            if outcome in sales.BAD:
                bad_count[author] += 1
    if fallback_windows:
        logger.info("return window fallback used", extra={"job": store.JOB, "orders": fallback_windows,
                                                          "days": tunables.commerce.return_window_fallback_days})

    inputs = [
        PromoterInput(
            promoter_id=pid, kind=kind, main_category=main_category[pid], followers=followers[pid],
            qualified_views_30d=len(views_30[pid]), reach_30d=len({v for v, _ in views_30[pid]}),
            engagements_30d=engaged_30[pid], weeks_posted=weeks_posted[pid], qualified_views_90d=len(views_90[pid]),
            completed_value=completed_value[pid], completed_count=completed_count[pid], final_count=final_count[pid],
            bad_count=bad_count[pid], trust_halved=fraud.get(pid, 0) >= store.RESTRICTED_LEVEL,
        )
        for pid, kind in sorted(candidates.items())
    ]
    no_views = sum(1 for p in inputs if p.qualified_views_30d == 0)
    commerce_on = commerce_readable and any(p.final_count > 0 for p in inputs if p.qualified_views_30d > 0)
    scored = score_promoters(inputs, settings=PromoterSettings.from_tunables(tunables), commerce_on=commerce_on)
    report.update(
        authors_with_original_posts=len(originals_by_author), candidates=len(candidates), not_scored=dict(not_scored),
        no_qualified_views=no_views, scored=len(scored), commerce_on=commerce_on, commerce_readable=commerce_readable,
        orders_in_window=len(orders), order_outcomes=dict(outcomes), orders_skipped=dict(order_skipped),
        reposts_on_orders=dict(repost_report), credited_to_original_not_promoter_id=promoter_differs,
        return_window_fallbacks=fallback_windows, events_skipped=dict(skipped),
        fraud_restricted=sum(1 for v in fraud.values() if v == store.RESTRICTED_LEVEL),
    )
    return scored, report


def to_row(s: Scored, method: str, which: str, common: dict[str, Any]) -> dict[str, Any]:
    chosen = s.method_one if which == "one" else s.method_two
    return {
        "_id": f"{common['job_run_id']}:{s.promoter_id}", "promoter_id": s.promoter_id, "kind": s.kind,
        "method": method, "slot": store.SLOT, "score": chosen.score, "confidence": s.confidence,
        "flags": sorted(s.flags), "main_category": s.main_category, "follower_band": s.follower_band,
        "cohort_group": chosen.group, "components": s.raw, "percentiles": s.percentiles, "weights": s.weights,
        "own": s.own, "category_average": s.category_average, "qualified_views_30d": round(s.n * 100),
        **common,
    }


async def run(settings: Settings, anchor: datetime | None = None) -> dict[str, Any]:
    """Compute once, then write each method as its own batch (each becomes current
    only once complete). On the 1st of the month, copy both into the monthly table."""
    anchor = anchor or utc_now()
    tunables = live.current()
    await store.ensure_promoter_indexes(settings)
    readable = await fetch.can_read(settings, "return_request")
    if readable:
        current, why = await writers.return_requests_current(settings, anchor, tunables.commerce.return_request_current_hours)
        if not current:
            # ENG-30 point 7: the previous batches stay in use; the service owner is alerted.
            logger.error("M8 not run: the return-request copy is not current; the previous batches stay in use",
                         extra={"job": store.JOB, "why": why, "alert": "service_owner"})
            async with recorded_run(settings, store.JOB, data_window=data_window(anchor)) as record:
                record["detail"] = {"skipped": "return-request copy not current", "why": why}
            return {"skipped": "return-request copy not current", "why": why}
    else:
        logger.warning("returnrequests cannot be read: net commerce, conversion and sales quality stay off",
                       extra={"job": store.JOB})

    scored, report = await compute(settings, anchor, readable)
    window = data_window(anchor)
    one, two = methods()
    records = {}
    for method, which in ((one, "one"), (two, "two")):
        async def work(job_run_id: str, method: str = method, which: str = which) -> int:
            common = {"job_run_id": job_run_id, "model_version": settings.model_version,
                      "config_version": tunables.config_version, "computed_at": utc_now(), "data_window": window}
            return await store.write_promoter_scores(settings, [to_row(s, method, which, common) for s in scored.values()])

        records[method] = await run_batch(settings, job=store.JOB, slot=store.SLOT, method=method,
                                          collection=store.COLLECTION, data_window=window, work=work)
    if anchor.day == 1:
        month = anchor.strftime("%Y-%m")
        report["monthly_copy"] = {m: await store.copy_monthly(settings, month, m) for m in (one, two)}
    report["batches"] = {m: {"job_run_id": r["_id"], "rows": r["rows_written"]} for m, r in records.items()}
    return report
