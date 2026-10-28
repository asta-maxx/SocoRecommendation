"""ENG-14: M2 retrieval method two, similar posts computed nightly.

Unit tests (no database):
    the vector             test_vector_*
    the post type          test_post_type_*
    the pool's rules       test_pool_*
    the profile            test_profile_*, test_engaged_*
    cosine and the top N   test_top_*

MongoDB (pytest -m mongo; throwaway databases from tests/conftest.py):
    the job end to end, the batch, and the 20 ms read
                           test_the_job_writes_a_current_batch_and_one_list_reads_in_20_ms
"""

from __future__ import annotations

import math
import time
from datetime import date, datetime, timedelta, timezone

import pytest

from reco.config.tunables import InterestWeights
from reco.platform.records import PostRecord, UserRecord
from reco.ranking import similar

NOW = datetime(2026, 10, 16, 2, 0, tzinfo=timezone.utc)
CATS = [f"c{i}" for i in range(23)]
TYPES = ["photo", "video", "normal", "other"]
WEIGHTS = InterestWeights().model_dump()


def vec(categories=("c0",), post_type="photo", days=0.0):
    return similar.post_vector(categories, post_type, days, CATS, TYPES)


def length(v):
    return math.sqrt(sum(x * x for x in v))


# --- the vector -----------------------------------------------------------------------


def test_vector_has_23_categories_then_the_types_then_age() -> None:
    assert len(vec()) == 23 + len(TYPES) + 1


def test_vector_carries_one_over_k_in_each_own_category_before_scaling() -> None:
    v = vec(("c1", "c4", "c9"), "video", 0.0)
    raw = [0.0] * 23 + [0, 1, 0, 0] + [0.2]
    for c in (1, 4, 9):
        raw[c] = 1 / 3
    scale = length(raw)
    assert v == pytest.approx([x / scale for x in raw])
    assert v[1] == v[4] == v[9] and v[2] == 0 and v[0] == 0


def test_vector_type_is_one_hot() -> None:
    v = vec(("c0",), "normal")
    types = v[23:27]
    assert types[2] > 0 and types[0] == types[1] == types[3] == 0


def test_vector_age_is_point_two_times_exp_minus_days_over_30() -> None:
    for days in (0, 15, 30, 90):
        raw = [0.0] * 23 + [1, 0, 0, 0] + [0.2 * math.exp(-days / 30)]
        raw[0] = 1.0
        assert vec(("c0",), "photo", days)[-1] == pytest.approx(raw[-1] / length(raw))
    assert similar.age_value(0) == pytest.approx(0.2)
    assert similar.age_value(30) == pytest.approx(0.2 / math.e)
    # The age dimension can never dominate: at most 0.2 against a type's 1.
    assert all(vec((), "photo", d)[-1] < vec((), "photo", d)[23] for d in (0, 1, 10))


def test_vector_has_length_one() -> None:
    for cats, kind, days in ((("c0",), "photo", 0), (("c1", "c2"), "other", 29.5), ((), "video", 3)):
        assert length(vec(cats, kind, days)) == pytest.approx(1.0)


def test_vector_ignores_categories_outside_the_23() -> None:
    assert vec(("c0", "not one of the 23")) == vec(("c0",))


# --- the post type (Kala, 16 Oct 2026) ------------------------------------------------------


def test_post_type_is_detailed_where_filled_else_post_type() -> None:
    assert similar.post_type_of("Video", "normal", TYPES) == ("video", True)
    assert similar.post_type_of("", "photo", TYPES) == ("photo", True)
    assert similar.post_type_of(None, "photo", TYPES) == ("photo", True)


def test_post_type_empty_gives_normal() -> None:
    assert similar.post_type_of("", "normal", TYPES) == ("normal", True)
    assert similar.post_type_of(None, None, TYPES) == ("normal", True)
    assert similar.post_type_of("  ", "", TYPES) == ("normal", True)


def test_post_type_unlisted_goes_to_other_and_is_reported() -> None:
    assert similar.post_type_of("carousel", "normal", TYPES) == ("other", False)
    assert similar.raw_type_of("carousel", "normal") == "carousel"
    assert similar.post_type_of("other", None, TYPES) == ("other", True)


# --- the pool's rules ---------------------------------------------------------------------------


def post(post_id="p", **fields) -> PostRecord:
    values = dict(post_id=post_id, author_id="a", created_at=NOW, categories=["c0"], categories_dropped=[],
                  post_type="normal", post_type_detailed=None, is_hidden=False, visibility="public",
                  compliance_status=None, product_status=None, age_group=None, is_repost=False, product_ids=[])
    values.update(fields)
    return PostRecord(**values)


def author(active=True) -> UserRecord:
    return UserRecord(user_id="a", status=None, is_active=active, moderation_state=None if active else "banned",
                      city=None, date_of_birth=None, account_is_public=True, restriction_level=None,
                      declared_interests=[], created_at=None)


def test_pool_keeps_an_ordinary_public_post() -> None:
    assert similar.post_is_eligible(post(), author()) is None


@pytest.mark.parametrize("fields, reason", [
    ({"is_seed": True}, "seed_post"),
    ({"is_repost": True}, "repost"),
    ({"is_hidden": True}, "E-04"),
    ({"visibility": "private"}, "E-04"),
    ({"compliance_status": "deranked"}, "E-12"),
    ({"compliance_status": "Removed"}, "E-12"),
    ({"product_ids": ["x"], "product_status": "Deactivated"}, "E-06"),
])
def test_pool_leaves_out(fields, reason) -> None:
    assert similar.post_is_eligible(post(**fields), author()) == reason


def test_pool_leaves_out_inactive_or_missing_authors() -> None:
    assert similar.post_is_eligible(post(), author(active=False)) == "E-08"
    assert similar.post_is_eligible(post(), None) == "E-08"


def test_pool_keeps_under_review_and_viewer_specific_cases() -> None:
    # Viewer rules (private author, adult-only) are applied at serving (ENG-08).
    assert similar.post_is_eligible(post(compliance_status="under review", age_group="18+"), author()) is None


# --- the profile ---------------------------------------------------------------------------


def row(user, post_id, event_type="like", days=1.0, **fields) -> dict:
    return {"user_id": user, "post_id": post_id, "event_type": event_type,
            "created_at": NOW - timedelta(days=days), **fields}


def engaged(rows, **kwargs):
    defaults = dict(anchor=NOW, weights=WEIGHTS, half_life_days=30, qualified_view_ms=3000)
    return similar.engaged_by_user(rows, **{**defaults, **kwargs})


def test_engaged_weight_is_action_weight_times_decay_summed_per_post() -> None:
    read = engaged([
        row("u", "p1", "like", days=0),  # 3 x 1
        row("u", "p1", "save", days=30),  # 4 x 0.5
        row("u", "p2", "add_to_cart", days=60),  # 10 x 0.25
        row("u", "p3", "product_click", days=0),  # a click: 5
        row("u", "p4", "view", days=0, dwell_ms=3000),  # qualified: 2
        row("u", "p4", "view", days=10, dwell_ms=9000),  # one view per post: the most recent
    ])
    posts = read.by_user["u"]
    assert posts["p1"].weight == pytest.approx(3 + 2)
    assert posts["p2"].weight == pytest.approx(2.5)
    assert posts["p3"].weight == pytest.approx(5)
    assert posts["p4"].weight == pytest.approx(2) and posts["p4"].actions == 1
    assert posts["p1"].last_at == NOW


def test_engaged_leaves_out_what_is_not_a_positive_action() -> None:
    read = engaged([
        row("u", "own", is_self=True),  # own post (Kala, 16 Oct)
        row("u", "seed"),  # a seed post (ENG-30 point 9)
        row("u", "undone", undone_at=NOW),  # undone later
        row("u", "undo", "unlike", undo_of="x"),  # the undo row
        row("u", "undo2", "like", undo_of="x"),
        row("u", "fb", "feedback", feedback_type="not_interested"),
        row("u", "imp", "impression"),
        row("u", "short", "view", dwell_ms=2999),  # not a qualified view
        row("tester", "p1"),  # a test account
        row("biz", "p1", actor="business"),
        row("u", "later", days=-1),  # after the anchor
        row("u", "kept"),
    ], seed_posts={"seed"}, test_accounts={"tester"})
    assert set(read.by_user) == {"u"} and set(read.by_user["u"]) == {"kept"}
    assert read.skipped["own_post"] == 1 and read.skipped["seed_post"] == 1 and read.skipped["undone"] == 2
    assert read.skipped["not_an_engagement"] == 3 and read.skipped["view_not_qualified"] == 1


def test_profile_needs_three_engaged_posts() -> None:
    vectors = {p: vec((c,)) for p, c in (("p1", "c1"), ("p2", "c2"), ("p3", "c3"))}
    two = engaged([row("u", "p1"), row("u", "p2"), row("u", "p2", "save")]).by_user["u"]
    assert similar.user_profile(two, vectors, last_posts=50, min_engaged=3) is None
    three = engaged([row("u", "p1"), row("u", "p2"), row("u", "p3")]).by_user["u"]
    assert similar.user_profile(three, vectors, last_posts=50, min_engaged=3) is not None


def test_profile_counts_only_posts_with_a_vector() -> None:
    vectors = {"p1": vec(("c1",)), "p2": vec(("c2",))}  # p3 is gone from the platform
    three = engaged([row("u", "p1"), row("u", "p2"), row("u", "p3")]).by_user["u"]
    assert similar.user_profile(three, vectors, last_posts=50, min_engaged=3) is None


def test_profile_is_the_weighted_average_scaled_to_one() -> None:
    vectors = {"a": vec(("c1",)), "b": vec(("c2",)), "c": vec(("c3",))}
    read = engaged([row("u", "a", "add_to_cart", days=0), row("u", "b", "like", days=0),
                    row("u", "c", "like", days=30)]).by_user["u"]
    profile = similar.user_profile(read, vectors, last_posts=50, min_engaged=3)
    weights = {"a": 10, "b": 3, "c": 1.5}
    total = sum(weights.values())
    expected = similar.normalise([sum(weights[p] / total * vectors[p][i] for p in weights) for i in range(28)])
    assert profile == pytest.approx(expected)
    assert length(profile) == pytest.approx(1)
    assert profile[1] > profile[2] > profile[3]


def test_profile_uses_the_last_50_engaged_posts() -> None:
    rows = [row("u", f"p{i:03}", days=i) for i in range(60)]  # p000 most recent
    vectors = {f"p{i:03}": vec((CATS[0] if i < 50 else CATS[5],)) for i in range(60)}
    read = engaged(rows).by_user["u"]
    chosen = similar.last_engaged(read, vectors, 50)
    assert chosen == [f"p{i:03}" for i in range(50)]
    profile = similar.user_profile(read, vectors, last_posts=50, min_engaged=3)
    assert profile[5] == 0  # the ten oldest (category c5) are outside the last 50


def test_profile_last_is_by_the_most_recent_action_on_the_post() -> None:
    read = engaged([row("u", "old", days=40), row("u", "old", "share", days=0), row("u", "new", days=1)]).by_user["u"]
    assert similar.last_engaged(read, {"old": [1.0], "new": [1.0]}, 1) == ["old"]


# --- cosine and the top N ---------------------------------------------------------------------


def test_cosine_of_unit_vectors_is_their_dot_product_in_0_to_1() -> None:
    a, b = vec(("c1",), "photo"), vec(("c1",), "photo")
    assert similar.cosine(a, b) == pytest.approx(1)
    c = vec(("c2",), "video")
    assert 0 < similar.cosine(a, c) < 0.1  # only the age dimension is shared
    assert similar.cosine(a, c) == pytest.approx(sum(x * y for x, y in zip(a, c)))


def pool_post(post_id, cats, kind="photo", days=0.0):
    return similar.PoolPost.of(post_id, NOW - timedelta(days=days), vec(cats, kind, days))


def test_top_is_ordered_by_cosine_and_capped() -> None:
    profile = vec(("c1",), "photo")
    pool = [pool_post("far", ("c9",), "video"), pool_post("same", ("c1",)), pool_post("half", ("c1", "c2"))]
    top = similar.top_similar(profile, pool, 200)
    assert [p for p, _ in top] == ["same", "half", "far"]
    assert top[0][1] == pytest.approx(1) and all(0 <= s <= 1 for _, s in top)
    assert [p for p, _ in similar.top_similar(profile, pool, 2)] == ["same", "half"]


def test_top_keeps_200_of_more() -> None:
    profile = vec(("c1",))
    pool = [pool_post(f"p{i}", (CATS[i % 23],), days=i % 30) for i in range(500)]
    top = similar.top_similar(profile, pool, 200)
    assert len(top) == 200
    scores = [s for _, s in top]
    assert scores == sorted(scores, reverse=True)
    brute = sorted(((similar.cosine(profile, vec((CATS[i % 23],), "photo", i % 30)), f"p{i}") for i in range(500)),
                   key=lambda t: -t[0])
    assert scores == pytest.approx([s for s, _ in brute[:200]])


def test_top_ties_newer_post_first_then_post_id() -> None:
    profile = vec(("c1",))
    same = vec(("c4",), "video", 0)  # identical vectors: identical scores
    pool = [similar.PoolPost("b", NOW.timestamp(), tuple(enumerate(same))),
            similar.PoolPost("a", NOW.timestamp(), tuple(enumerate(same))),
            similar.PoolPost("c", (NOW + timedelta(hours=1)).timestamp(), tuple(enumerate(same)))]
    assert [p for p, _ in similar.top_similar(profile, pool, 3)] == ["c", "a", "b"]


# --- MongoDB: the job end to end ---------------------------------------------------------------


@pytest.fixture
async def dbs(store):
    from pymongo import AsyncMongoClient

    from tests.conftest import TEST_DB, TEST_PLATFORM_DB, _test_uri

    client = AsyncMongoClient(_test_uri())
    engine, platform = client[TEST_DB], client[TEST_PLATFORM_DB]
    engine_names = ("ml_events", "ml_job_runs", "ml_user_candidates")
    platform_names = ("users", "businessregisters", "posts")
    for name in engine_names:
        await engine[name].delete_many({})
    for name in platform_names:
        await platform[name].delete_many({})
    try:
        yield store, engine, platform
    finally:
        for name in engine_names:
            await engine[name].delete_many({})
        for name in platform_names:
            await platform[name].delete_many({})
        await client.close()


@pytest.mark.mongo
async def test_the_job_writes_a_current_batch_and_one_list_reads_in_20_ms(dbs) -> None:
    from bson import ObjectId

    from reco.jobs.__main__ import JOBS
    from reco.jobs.scheduler import NIGHTLY
    from reco.store import candidates, writers
    from reco.store.scores import utc_now
    from tests.conftest import put_in_force

    settings, engine, platform = dbs
    now = utc_now()
    live_author, banned = ObjectId(), ObjectId()
    await platform["users"].insert_many([
        {"_id": live_author, "moderation": {"state": "active"}},
        {"_id": banned, "moderation": {"state": "banned"}},
    ])
    categories = ["Pets", "Electronics", "Fashion & Apparel", "Food & Beverages", "Travel & Tourism"]
    posts = []
    for i in range(300):  # more than 200, so the list is capped
        posts.append({"_id": ObjectId(), "userId": live_author, "timestamp": now - timedelta(hours=i),
                      "categories": [categories[i % 5]], "postType": "normal",
                      "postTypeDetailed": ["photo", "video", "", "carousel"][i % 4], "visibility": "public"})
    left_out = [
        {"_id": ObjectId(), "userId": live_author, "timestamp": now, "categories": ["Pets"], "visibility": "public",
         "isHidden": True},
        {"_id": ObjectId(), "userId": live_author, "timestamp": now, "categories": ["Pets"], "visibility": "public",
         "_seedTag": "seed"},
        {"_id": ObjectId(), "userId": live_author, "timestamp": now, "categories": ["Pets"], "visibility": "public",
         "isRepost": True},
        {"_id": ObjectId(), "userId": banned, "timestamp": now, "categories": ["Pets"], "visibility": "public"},
        {"_id": ObjectId(), "userId": live_author, "timestamp": now - timedelta(days=31), "categories": ["Pets"],
         "visibility": "public"},
    ]
    await platform["posts"].insert_many(posts + left_out)
    pets = [str(p["_id"]) for p in posts if p["categories"] == ["Pets"]]
    tester = str(ObjectId())
    put_in_force({"lists.test_accounts": [{"account_id": tester, "reason": "checks", "changed_by": "Allen",
                                           "expiry": date.today() + timedelta(days=7)}]})

    def event(user, post_id, event_type="like", **fields):
        return {"_id": ObjectId(), "kind": "postevent", "user_id": user, "event_type": event_type,
                "post_id": post_id, "created_at": now - timedelta(days=1), "undone_at": None, "undo_of": None,
                **fields}

    await engine["ml_events"].insert_many([
        *(event("fan", p) for p in pets[:4]),  # 4 engaged Pets posts: gets a list
        event("two", pets[0]), event("two", pets[1]),  # 2 engaged: none
        event("two", pets[2], is_self=True),  # own post: doesn't count
        event("two", str(left_out[1]["_id"])),  # seed post: doesn't count
        *(event(tester, p) for p in pets[:4]),  # a test account: none
    ])
    assert NIGHTLY[NIGHTLY.index("interest") + 1] == "similar_posts"

    await JOBS["similar_posts"](settings)

    run = await engine["ml_job_runs"].find_one({"job": "similar_posts"})
    assert run["outcome"] == "succeeded" and run["is_current"] and run["rows_written"] == 200
    assert await writers.current_job_run_id(settings, "similar_posts", "similar_posts") == run["_id"]
    stored = await engine["ml_user_candidates"].find({}).to_list(None)
    assert {r["user_id"] for r in stored} == {"fan"}
    assert all(r["job_run_id"] == run["_id"] and r["model_version"] == settings.model_version
               and r["method"] == "similar_posts" and r["slot"] == "retrieval" and r["config_version"]
               and r["data_window"]["from"] and r["data_window"]["to"] for r in stored)
    excluded = {str(p["_id"]) for p in left_out}
    assert not excluded & {r["post_id"] for r in stored}

    listed = await candidates.read_user_candidates(settings, "fan")
    assert [r["rank"] for r in listed] == list(range(1, 201))
    assert set(listed[0]) == {"post_id", "score", "rank"}
    # The 4 posts the profile was built from are left off (Nisha, 16 Oct); the other Pets posts come first.
    assert not set(pets[:4]) & {r["post_id"] for r in listed}
    assert {r["post_id"] for r in listed[:len(pets) - 4]} == set(pets[4:])
    assert all(a["score"] >= b["score"] for a, b in zip(listed, listed[1:]))
    assert await candidates.read_user_candidates(settings, "two") == []

    # The pack's check: reading one user's list takes 20 ms or less. The read is two
    # round trips (the current batch, then the list), so from a laptop to a remote
    # database the network alone can pass 20 ms. Measured three ways and printed:
    # the wall time, the network floor (a ping), and the database's own time.
    async def median_ms(call, n=20) -> float:
        timings = []
        for _ in range(n):
            started = time.perf_counter()
            await call()
            timings.append((time.perf_counter() - started) * 1000)
        return sorted(timings)[n // 2]

    from reco.store.connection import ml_db

    read = await median_ms(lambda: candidates.read_user_candidates(settings, "fan"))
    ping = await median_ms(lambda: ml_db(settings).command("ping"))
    plan = await ml_db(settings).command(
        "explain", {"find": "ml_user_candidates", "filter": {"job_run_id": run["_id"], "user_id": "fan"},
                    "sort": {"rank": 1}, "projection": {"_id": 0, "post_id": 1, "score": 1, "rank": 1}},
        verbosity="executionStats")
    stats = plan["executionStats"]
    beyond_network = read - 2 * ping
    print(f"\nread_user_candidates: median {read:.1f} ms wall; ping {ping:.1f} ms; "
          f"{read - 2 * ping:.1f} ms beyond two round trips; database {stats['executionTimeMillis']} ms, "
          f"{stats['totalKeysExamined']} keys and {stats['totalDocsExamined']} documents examined")
    assert "IXSCAN" in str(plan["queryPlanner"]["winningPlan"]) and "SORT" not in str(plan["queryPlanner"]["winningPlan"])
    assert stats["totalDocsExamined"] == 200 and stats["executionTimeMillis"] <= 20
    # With the test-only limits in force (a server far from the database, review of 26 Oct,
    # point 1), round trips swing by more than 20 ms (test server, 28 Oct: ping 266 ms, 26 ms
    # left beyond two), so the wall time is reported, not judged; the database's own time is.
    if not settings.request_budget_ms:
        assert read <= 20 or beyond_network <= 20

    # A second run replaces the batch whole; the reader switches to it.
    await JOBS["similar_posts"](settings)
    current = await writers.current_job_run_id(settings, "similar_posts", "similar_posts")
    assert current != run["_id"]
    assert len(await candidates.read_user_candidates(settings, "fan")) == 200
    assert await engine["ml_user_candidates"].count_documents({"job_run_id": current}) == 200


# --- Nisha's answers of 16 Oct 2026 -------------------------------------------------------------

REVERSED = ("Cancelled", "Rejected", "Returned")


def order(buyer="u", post_id="p1", status="Delivered", days=1.0, **fields) -> dict:
    return {"order_id": fields.pop("order_id", f"o-{post_id}-{status}"), "buyer_id": buyer, "post_id": post_id,
            "status": status, "created_at": NOW - timedelta(days=days), **fields}


def test_a_kept_purchase_from_a_post_adds_20_aged_from_the_order() -> None:
    bought, _ = similar.kept_purchases([order(days=30)], anchor=NOW, reversed_statuses=REVERSED)
    read = engaged([row("u", "p1", "like", days=0)], purchases=bought)
    assert read.by_user["u"]["p1"].weight == pytest.approx(3 + 20 * 0.5)  # like 3, purchase 20 x decay
    assert read.by_user["u"]["p1"].actions == 2


def test_purchases_follow_eng10_rules() -> None:
    """Cancelled, Rejected or Returned lose their weight; an open return request adds
    nothing while open; no post, a business buyer, a seed post, a test account or a
    future order add nothing."""
    orders = [
        order(post_id="kept"),
        order(post_id="c", status="cancelled"), order(post_id="r", status="Rejected"), order(post_id="ret", status="Returned"),
        order(post_id="open", order_id="o-open"),
        order(post_id=None), order(post_id="biz", buyer_actor="business"), order(post_id="seed"),
        order(buyer="tester", post_id="t"), order(post_id="later", days=-1),
    ]
    bought, skipped = similar.kept_purchases(orders, anchor=NOW, reversed_statuses=REVERSED, open_requests={"o-open"},
                                             seed_posts={"seed"}, test_accounts={"tester"})
    assert [p for _, p, _ in bought] == ["kept"]
    assert skipped["order_reversed"] == 3 and skipped["order_open_return_request"] == 1
    assert skipped["order_not_from_a_post"] == 1 and skipped["order_not_by_a_user"] == 1
    assert skipped["order_seed_post"] == 1 and skipped["order_test_account"] == 1 and skipped["order_future"] == 1


def test_the_postevents_purchase_row_is_never_counted() -> None:
    """ENG-10: purchases are read from the order, one place only."""
    read = engaged([row("u", "p1", "purchase"), row("u", "p2")])
    assert set(read.by_user["u"]) == {"p2"} and read.skipped["not_an_engagement"] == 1


def test_a_purchase_alone_makes_an_engaged_post() -> None:
    bought, _ = similar.kept_purchases([order(post_id=p) for p in ("p1", "p2", "p3")], anchor=NOW,
                                       reversed_statuses=REVERSED)
    vectors = {p: vec((c,)) for p, c in (("p1", "c1"), ("p2", "c2"), ("p3", "c3"))}
    read = engaged([], purchases=bought)
    assert similar.user_profile(read.by_user["u"], vectors, last_posts=50, min_engaged=3) is not None


def test_the_profile_posts_are_left_off_and_the_next_fill_their_places() -> None:
    profile = vec(("c1",), "photo")
    pool = [pool_post("seen", ("c1",)), pool_post("same", ("c1",), days=1), pool_post("half", ("c1", "c2")),
            pool_post("far", ("c9",), "video")]
    top = similar.top_similar(profile, pool, 2, exclude={"seen"})
    assert [p for p, _ in top] == ["same", "half"]  # 2 places, "seen" skipped, "half" moves up
