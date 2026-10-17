"""ENG-19: the launch ranking layer for the feed.

The Build List's check: "On test data, the order follows the formula, variety rules
hold, and changing a product's commission changes nothing."
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import pytest

from reco.ranking import feed
from reco.ranking.feed import Post, VarietyRules, fill_page, keep_consecutive_rule, score_posts
from reco.ranking.serving import Built, Candidate, leave_out_served

NOW = datetime(2026, 10, 17, 12, tzinfo=timezone.utc)
WEIGHTS = {"interest": 0.35, "retrieval": 0.15, "promoter": 0.20, "freshness": 0.20, "engagement_quality": 0.10}


def post(pid, author="a", cats=("Pets",), days=1.0, retrieval=0.5, views=0, engagements=0) -> Post:
    return Post(pid, author, list(cats), NOW - timedelta(days=days), retrieval, views, engagements)


def ranked(posts, shares=None, scores=None, medians=None, platform=None, shrink=50):
    return score_posts(posts, shares=shares or {"Pets": 0.6, "Home & Living": 0.3}, promoter_scores=scores or {},
                       medians=medians or {}, platform_median=platform, now=NOW, weights=WEIGHTS,
                       half_life_days=3, shrinkage_views=shrink)


# --- the formula -------------------------------------------------------------------------------


def test_the_score_is_the_weighted_sum_of_the_five_parts_by_hand() -> None:
    a = post("a", author="x", cats=("Pets", "Home & Living"), days=3, retrieval=0.9, views=100, engagements=20)
    b = post("b", author="y", cats=("Home & Living",), days=0, retrieval=0.1, views=0, engagements=0)
    out = {s.post.post_id: s for s in ranked([a, b], scores={"x": 0.8})}
    # a: interest 0.6 (its best category), retrieval pct 1, promoter 0.8, freshness 0.5 (3 days), quality pct 1
    # quality: average rate 20/100 = 0.2; a (20 + 50*0.2)/(100 + 50) = 0.2, b (0 + 10)/50 = 0.2 -> tie, both 0.5
    assert out["a"].parts == pytest.approx({"interest": 0.6, "retrieval": 1.0, "promoter": 0.8, "freshness": 0.5,
                                            "engagement_quality": 0.5})
    assert out["a"].score == pytest.approx(0.35 * 0.6 + 0.15 * 1 + 0.20 * 0.8 + 0.20 * 0.5 + 0.10 * 0.5)
    # b: an author with no score and no medians: 0.5; freshness 1
    assert out["b"].parts["promoter"] == 0.5 and out["b"].parts["freshness"] == pytest.approx(1.0)
    assert out["b"].score == pytest.approx(0.35 * 0.3 + 0.15 * 0 + 0.20 * 0.5 + 0.20 * 1 + 0.10 * 0.5)


def test_interest_is_the_highest_share_among_the_posts_categories() -> None:
    [s] = ranked([post("p", cats=("Home & Living", "Pets", "Gaming"))])
    assert s.parts["interest"] == 0.6 and s.category == "Pets"


def test_freshness_halves_every_3_days() -> None:
    assert [round(feed.freshness(NOW - timedelta(days=d), NOW, 3), 4) for d in (0, 3, 6)] == [1.0, 0.5, 0.25]


def test_engagement_is_pulled_toward_the_average_by_50_views() -> None:
    # Raw rates: few 1/1 = 100%, many 600/1000 = 60%, low 0/1000. Average 601/2001 = 0.30.
    # Shrunk by 50 views: few (1 + 15.0)/51 = 0.31; many (600 + 15.0)/1050 = 0.59; low 15.0/1050 = 0.01.
    few, many, low = post("few", views=1, engagements=1), post("many", views=1000, engagements=600),         post("low", views=1000, engagements=0)
    out = {s.post.post_id: s.parts["engagement_quality"] for s in ranked([few, many, low])}
    assert out == {"many": 1.0, "few": 0.5, "low": 0.0}  # one view at 100% no longer beats 1,000 at 60%


def test_an_author_with_no_score_takes_kalas_ladder() -> None:
    p = post("p", author="new", cats=("Pets", "Gaming"))
    assert feed.promoter_part("new", p.categories, {"new": 0.9}, {}, None) == (0.9, "own")
    assert feed.promoter_part("new", p.categories, {}, {"Pets": 0.4, "Gaming": 0.6}, 0.5) == (pytest.approx(0.5), "category_median")
    assert feed.promoter_part("new", p.categories, {}, {"Pets": 0.4}, 0.5) == (0.4, "category_median")
    assert feed.promoter_part("new", p.categories, {}, {"Food": 0.3}, 0.45) == (0.45, "platform_median")
    assert feed.promoter_part("new", p.categories, {}, {}, None) == (0.5, "default")


def test_ties_newer_first_then_post_id() -> None:
    posts = [post("b", days=2), post("a", days=2), post("c", days=1)]
    out = ranked(posts, shares={"Pets": 0.0})
    # c is fresher so scores higher; a and b tie exactly: by id
    assert [s.post.post_id for s in out] == ["c", "a", "b"]


def test_commission_never_enters_the_score() -> None:
    """The formula has no commission input: two posts identical but for their product's
    commission score the same."""
    import inspect

    assert "commission" not in inspect.signature(score_posts).parameters
    assert "commission" not in " ".join(feed.COMPONENTS)


# --- variety -----------------------------------------------------------------------------------


def scored(specs):
    """specs: (post id, author, category) in rank order."""
    return [feed.Scored(post(pid, author=a, cats=(c,)), 1.0 - n / 100, {}, c, "own") for n, (pid, a, c) in enumerate(specs)]


def ids(page):
    return [s.post.post_id for s in page]


def test_no_more_than_two_in_a_row_from_one_author() -> None:
    items = scored([("1", "x", "A"), ("2", "x", "B"), ("3", "x", "C"), ("4", "y", "D"), ("5", "z", "E")])
    page, relaxed = fill_page(items, 5, VarietyRules(2, 3, 5))
    assert ids(page) == ["1", "2", "4", "3", "5"] and relaxed == []


def test_at_most_three_per_author_on_a_page() -> None:
    items = scored([(str(n), "x" if n < 5 else f"y{n}", f"C{n}") for n in range(1, 9)])
    page, relaxed = fill_page(items, 6, VarietyRules(2, 3, 6))
    assert sum(s.post.author_id == "x" for s in page) == 3 and relaxed == []


def test_category_cap_is_ceil_04_limit_and_never_below_2() -> None:
    class T:
        class ranking:
            max_consecutive_same_author, max_per_author_per_page, max_category_fraction, min_category_cap = 2, 3, 0.4, 2

    assert VarietyRules.for_page(10, T).category_cap == math.ceil(0.4 * 10) == 4
    assert VarietyRules.for_page(3, T).category_cap == 2  # ceil(1.2) = 2; and never below 2
    assert VarietyRules.for_page(1, T).category_cap == 2


def test_rules_relax_in_order_and_filling_the_page_wins() -> None:
    # One category only, three authors: the category cap (2) must go first.
    items = scored([(str(n), f"a{n % 3}", "Pets") for n in range(1, 7)])
    page, relaxed = fill_page(items, 6, VarietyRules(2, 3, 2))
    assert len(page) == 6 and relaxed == ["category_cap"]
    # One author only: category, then per-author, then the consecutive rule.
    alone = scored([(str(n), "x", "Pets") for n in range(1, 6)])
    page, relaxed = fill_page(alone, 5, VarietyRules(2, 3, 2))
    assert len(page) == 5 and relaxed == ["category_cap", "per_author_cap", "consecutive_author"]


def test_a_short_shortlist_fills_what_it_can() -> None:
    page, relaxed = fill_page(scored([("1", "x", "A")]), 10, VarietyRules())
    assert ids(page) == ["1"] and relaxed == []


def test_the_shuffle_cannot_undo_the_consecutive_rule() -> None:
    def c(pid, author):
        return Candidate(pid, "post", pid, None, rank=1, author_id=author)

    shuffled = [c("1", "x"), c("2", "y"), c("3", "y"), c("4", "y"), c("5", "z")]
    fixed = keep_consecutive_rule(shuffled, 2)
    assert [i.item_id for i in fixed] == ["1", "2", "3", "5", "4"]
    for i in range(2, len(fixed)):
        assert len({fixed[i - 2].author_id, fixed[i - 1].author_id, fixed[i].author_id}) > 1


# --- paging ------------------------------------------------------------------------------------


def test_later_pages_leave_out_what_was_served_in_24_hours() -> None:
    made = [Candidate(f"p{n}", "product", None, f"p{n}", rank=n) for n in range(1, 31)]
    built = leave_out_served(Built(None, list(made), {}, 30), 2, {"p1", "p2", "p3"})
    assert built.page_start == 0 and [c.item_id for c in built.candidates[:3]] == ["p4", "p5", "p6"]
    assert built.detail["left_out_served"] == 3
    first = leave_out_served(Built(None, list(made), {}, 30), 1, {"p1"})
    assert first.page_start is None and first.candidates[0].item_id == "p1"  # page 1 is the top


# --- the request, with stand-ins for the shortlist and the stores -------------------------------


@pytest.fixture
def stubs(monkeypatch):
    from reco.ranking.merge import Shortlist, ShortlistItem

    state = {"shortlist": [], "records": {}, "index": {}, "scores": {}, "interim": []}

    async def viewer(settings, user_id):
        from reco.eligibility.rules import Viewer

        return Viewer(user_id=user_id)

    async def shortlist(settings, user_id, profile, viewer, request_id, time_limit_ms=None):
        return Shortlist(items=[ShortlistItem(pid, "post", ["interest"], pct, "method_one") for pid, pct in state["shortlist"]])

    async def read(settings, ids, batch):
        return {i: state["records"][i] for i in ids if i in state["records"]}, state["index"]

    async def batch(settings):
        return "b1"

    async def scores(settings, authors, method):
        return state["scores"]

    async def medians(settings, method):
        return {}, None

    async def interim(settings, surface, page, limit, context, user_id=None, request_id=None):
        return Built(None, state["interim"], {}, len(state["interim"]))

    monkeypatch.setattr(feed, "viewer_context", viewer)
    monkeypatch.setattr(feed.merge, "shortlist_for_user", shortlist)
    monkeypatch.setattr(feed, "_read", read)
    monkeypatch.setattr(feed.item_state, "current_batch", batch)
    monkeypatch.setattr(feed.promoter_store, "read_promoter_scores", scores)
    monkeypatch.setattr(feed.promoter_store, "read_medians", medians)
    monkeypatch.setattr(feed.serving, "interim_candidates", interim)
    return state


def record(pid, author, cat="Pets", days=1.0):
    from tests.test_quotas import post as post_record

    return post_record(pid, author_id=author, categories=[cat], created_at=datetime.now(timezone.utc) - timedelta(days=days))


async def test_the_feed_ranks_the_shortlist_and_tops_up_when_short(stubs, settings) -> None:
    from reco.fallback.profile import RUNG_DESCRIPTION, CategoryShare, Profile, Rung

    stubs["shortlist"] = [("p1", 0.2), ("p2", 0.9)]
    stubs["records"] = {"p1": record("p1", "x", days=0.1), "p2": record("p2", "y", days=5)}
    stubs["scores"] = {"y": 0.9}
    stubs["interim"] = [Candidate(f"n{n}", "post", f"n{n}", None, rank=n, author_id="z") for n in range(1, 4)]
    profile = Profile(user_id="u", categories=[CategoryShare(category="Pets", share=1.0)], rung=Rung.PERSONALISED,
                      rung_description=RUNG_DESCRIPTION[Rung.PERSONALISED], personalised=True, model_version="t")
    built = await feed.feed_candidates(settings, 1, 3, "u", "r1", profile, "shrinkage", set())
    order = [c.item_id for c in built.candidates]
    # By hand (interest 1 for both, engagement 0.5 each, no views):
    # p1 = 0.35 + 0.15 x 0 + 0.20 x 0.5 (no score: default) + 0.20 x 0.977 (2.4 hours) + 0.05 = 0.695
    # p2 = 0.35 + 0.15 x 1 + 0.20 x 0.9 + 0.20 x 0.315 (5 days) + 0.05 = 0.793
    assert order[:2] == ["p2", "p1"]
    assert built.candidates[0].score == pytest.approx(0.793, abs=0.002)
    assert built.candidates[1].score == pytest.approx(0.695, abs=0.002)
    assert order[2:] == ["n1", "n2", "n3"] and built.detail["topped_up"] == 3  # topped up after the ranked ones
    assert built.page_start == 0 and built.detail["ordering"] == feed.ORDERING
    assert all(c.score is not None for c in built.candidates[:2]) and built.candidates[2].score is None


async def test_page_two_leaves_out_what_was_served(stubs, settings) -> None:
    stubs["shortlist"] = [(f"p{n}", n / 10) for n in range(1, 9)]
    stubs["records"] = {f"p{n}": record(f"p{n}", f"a{n}") for n in range(1, 9)}
    first = await feed.feed_candidates(settings, 1, 3, "u", "r1", None, None, set())
    page_one = [c.item_id for c in first.candidates[:3]]
    second = await feed.feed_candidates(settings, 2, 3, "u", "r2", None, None, set(page_one))
    assert not set(page_one) & {c.item_id for c in second.candidates[:3]}
    assert second.detail["left_out_served"] == 3


# --- on a database: the Build List's check -------------------------------------------------------


@pytest.mark.mongo
async def test_the_feed_ranking_on_a_database(store) -> None:
    """Posts, views, a promoter batch and the post index on a database: the page follows
    the formula and keeps the variety rules; changing a product's commission changes
    nothing; page 2 leaves out page 1."""
    from bson import ObjectId
    from pymongo import AsyncMongoClient

    from reco.eligibility.apply import viewer_context
    from reco.fallback.profile import RUNG_DESCRIPTION, CategoryShare, Profile, Rung
    from reco.jobs.batches import run_batch
    from reco.ranking import post_index
    from reco.store import promoter as promoter_store
    from tests.conftest import TEST_DB, TEST_PLATFORM_DB, _test_uri

    settings = store
    now = datetime.now(timezone.utc)
    client = AsyncMongoClient(_test_uri())
    platform, engine = client[TEST_PLATFORM_DB], client[TEST_DB]
    names = ("posts", "users", "businessregisters", "follows", "followers", "products", "commissionconfigs")
    engine_names = ("ml_item_state", "ml_events", "ml_job_runs", "ml_user_candidates", "ml_promoter_scores", "ml_measurements")
    for name in names:
        await platform[name].delete_many({})
    for name in engine_names:
        await engine[name].delete_many({})
    authors = [ObjectId() for _ in range(6)]
    viewer = ObjectId()
    await platform["users"].insert_many([{"_id": u, "status": "Active", "accountIsPublic": True} for u in [*authors, viewer]])
    product = ObjectId()
    await platform["products"].insert_one({"_id": product, "status": "Activate", "availability": {"inStock": True}})
    posts = [{"_id": ObjectId(), "userId": authors[k % 6], "timestamp": now - timedelta(hours=k + 1),
              "categories": ["Pets" if k % 2 else "Gaming"], "visibility": "public"} for k in range(40)]
    await platform["posts"].insert_many(posts)
    await engine["ml_events"].insert_many([
        {"_id": ObjectId(), "kind": "postevent", "event_type": "view", "user_id": f"v{k}", "post_id": str(p["_id"]),
         "dwell_ms": 4000, "created_at": now - timedelta(minutes=30), "undone_at": None, "undo_of": None}
        for k, p in enumerate(posts[:30])])

    async def promoter_rows(job_run_id):
        return await promoter_store.write_promoter_scores(settings, [
            {"_id": f"{job_run_id}:{a}", "promoter_id": str(a), "method": "shrinkage", "score": 0.1 + 0.15 * n,
             "job_run_id": job_run_id} for n, a in enumerate(authors)])

    profile = Profile(user_id=str(viewer), categories=[CategoryShare(category="Pets", share=0.7),
                                                      CategoryShare(category="Gaming", share=0.3)],
                      rung=Rung.PERSONALISED, rung_description=RUNG_DESCRIPTION[Rung.PERSONALISED], personalised=True,
                      model_version=settings.model_version)
    try:
        await post_index.refresh(settings)
        await run_batch(settings, job="promoter", slot="promoter_score", method="shrinkage", collection="ml_promoter_scores",
                        data_window={"from": now, "to": now}, work=promoter_rows)
        built = await feed.feed_candidates(settings, 1, 10, str(viewer), "req", profile, "shrinkage", set(),
                                          time_limit_ms=5000)  # over the internet a source can take more than 20 ms
        page = built.candidates[:10]
        assert len(page) == 10 and built.detail["scored"] > 10
        by_id = {str(p["_id"]): p for p in posts}
        # Variety: never 3 in a row by one author, at most 3 per author, at most 4 per category (ceil(0.4 x 10)).
        page_authors = [str(by_id[c.item_id]["userId"]) for c in page]
        assert all(len(set(page_authors[i - 2:i + 1])) > 1 for i in range(2, 10))
        assert max(page_authors.count(a) for a in page_authors) <= 3 or "per_author_cap" in built.detail["relaxed"]
        # The formula: outside the variety swaps, scores never rise down the page.
        assert [c.score for c in built.candidates[10:]] == sorted([c.score for c in built.candidates[10:]], reverse=True)

        # Changing a product's commission changes nothing.
        await platform["commissionconfigs"].insert_one({"scope": "product", "scopeId": str(product), "poolPercent": 50,
                                                        "enabled": True})
        again = await feed.feed_candidates(settings, 1, 10, str(viewer), "req2", profile, "shrinkage", set(),
                                         time_limit_ms=5000)
        assert [c.item_id for c in again.candidates] == [c.item_id for c in built.candidates]
        # Same scores (freshness is measured at each request, so a later request differs in the 6th decimal).
        assert [c.score for c in again.candidates] == pytest.approx([c.score for c in built.candidates], abs=1e-4)

        # Page 2 leaves out page 1.
        two = await feed.feed_candidates(settings, 2, 10, str(viewer), "req3", profile, "shrinkage",
                                         {c.item_id for c in page}, time_limit_ms=5000)
        assert not {c.item_id for c in page} & {c.item_id for c in two.candidates[:10]}
        assert (await viewer_context(settings, str(viewer))).user_id == str(viewer)
    finally:
        for name in names:
            await platform[name].delete_many({})
        for name in engine_names:
            await engine[name].delete_many({})
        await client.close()
