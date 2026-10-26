"""ENG-08: the eligibility rules E-01 to E-12.

The Build List's check: "A test case for each rule: one item excluded and one
kept." Each test_e_xx below builds the two from platform-shaped documents
(tests/platform_dataset.py where it has the case) and runs the rule. Then, on a
database: the viewer's context (follows, blocks, feedback) is read from the
platform and the engine's copy; each exclusion is logged with request_id,
item_id and rule; and an item that fails the final recheck is replaced.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

import pytest
import pytest_asyncio
from bson import ObjectId

from reco.config import PLATFORM_COLLECTIONS, Settings
from reco.eligibility import apply
from reco.eligibility.rules import RULES, Viewer, post_rule, product_rule
from reco.platform import connection as platform_conn
from reco.platform import records
from reco.platform.categories import ProductCategoryIndex
from reco.platform.readers import vocabulary
from reco.ranking import serving
from reco.ranking.serving import Candidate
from reco.store import connection as store_conn
from reco.store import writers
from reco.store.scores import utc_now
from tests.platform_dataset import build_dataset

DATA, C = build_dataset()
VOCAB = vocabulary(Settings())
INDEX = ProductCategoryIndex()


def doc(collection: str, key: str) -> dict:
    return next(d for d in DATA[collection] if d["_id"] == C[key])


def P(key: str, **changes) -> records.PostRecord:
    return records.parse_post({**doc("posts", key), **changes}, VOCAB)


def U(key: str, **changes) -> records.UserRecord:
    return records.parse_user({**doc("users", key), **changes}, VOCAB)


def B(key: str, **changes) -> records.BusinessRecord:
    return records.parse_business({**doc("businessregisters", key), **changes}, VOCAB)


def PR(key: str, **changes) -> records.ProductRecord:
    return records.parse_product({**doc("products", key), **changes}, INDEX)


def VARIANTS(product_key: str) -> list[records.VariantRecord]:
    return [records.parse_variant(v) for v in DATA["productvariants"] if v["productId"] == C[product_key]]


VIEWER = Viewer(user_id=str(C["viewer"]), own_ids=frozenset({str(C["viewer"])}), date_of_birth=date(1995, 4, 2))
AUTHOR = U("author")


def test_every_rule_is_named() -> None:
    assert list(RULES) == [f"E-{n:02}" for n in range(1, 13)]


def test_e01_blocked_either_way() -> None:
    blocked = Viewer(**{**VIEWER.__dict__, "blocked": frozenset({str(C["author"])})})
    assert post_rule(P("post"), AUTHOR, blocked) == "E-01"
    assert post_rule(P("post"), AUTHOR, VIEWER) is None
    seller_blocked = Viewer(**{**VIEWER.__dict__, "blocked": frozenset({str(C["seller"])})})
    assert product_rule(PR("product"), B("seller"), VARIANTS("product"), seller_blocked) == "E-01"


def test_e02_muted_author() -> None:
    muted = Viewer(**{**VIEWER.__dict__, "muted": frozenset({str(C["author"])})})
    assert post_rule(P("post"), AUTHOR, muted) == "E-02"
    assert post_rule(P("product_post"), AUTHOR, Viewer(**{**VIEWER.__dict__, "muted": frozenset({"someone else"})})) is None


def test_e03_not_interested_hide_or_report() -> None:
    dismissed = Viewer(**{**VIEWER.__dict__, "dismissed": frozenset({str(C["post"])})})
    assert post_rule(P("post"), AUTHOR, dismissed) == "E-03"
    assert post_rule(P("product_post"), AUTHOR, dismissed) is None


def test_e04_hidden_or_not_public() -> None:
    assert post_rule(P("hidden_post"), AUTHOR, VIEWER) == "E-04"
    assert post_rule(P("private_post"), AUTHOR, VIEWER) == "E-04"
    assert post_rule(P("post"), AUTHOR, VIEWER) is None


def test_e05_private_author_not_followed() -> None:
    private = U("private_author")
    assert post_rule(P("private_author_post"), private, VIEWER) == "E-05"
    follower = Viewer(**{**VIEWER.__dict__, "follows": frozenset({str(C["private_author"])})})
    assert post_rule(P("private_author_post"), private, follower) is None


def test_e06_product_post_not_activated() -> None:
    assert post_rule(P("product_post", Product_status="Deactivated"), AUTHOR, VIEWER) == "E-06"
    assert post_rule(P("product_post"), AUTHOR, VIEWER) is None  # Activated
    assert post_rule(P("post"), AUTHOR, VIEWER) is None  # N/A: no product


def test_e07_product_not_sellable() -> None:
    seller = B("seller")
    assert product_rule(PR("product_out_of_stock"), seller, VARIANTS("product_out_of_stock"), VIEWER) == "E-07"
    assert product_rule(PR("product_inactive"), seller, VARIANTS("product"), VIEWER) == "E-07"
    no_variant_stock = [records.parse_variant({**doc("productvariants", "variant"), "quantity": 2, "reservedStock": 2})]
    assert product_rule(PR("product"), seller, no_variant_stock, VIEWER) == "E-07"
    assert product_rule(PR("product"), seller, VARIANTS("product"), VIEWER) is None


def test_e08_author_or_seller_not_active() -> None:
    """Question 17, answered 16 Oct: a person is active unless moderation.state says
    otherwise (users.status is not used); a store only when its status is 'active'."""
    assert post_rule(P("inactive_author_post"), U("inactive_author"), VIEWER) == "E-08"  # moderation suspended
    assert post_rule(P("post"), U("author", moderation={"state": "Banned"}), VIEWER) == "E-08"
    assert post_rule(P("post"), U("author", status=None), VIEWER) is None  # no status: active, as in the app
    assert post_rule(P("post"), U("author", status="Inactive"), VIEWER) is None  # status alone decides nothing
    assert post_rule(P("post"), None, VIEWER) == "E-08"  # author not found
    assert product_rule(PR("product"), B("inactive_seller"), VARIANTS("product"), VIEWER) == "E-08"
    assert product_rule(PR("product"), B("seller", status=None), VARIANTS("product"), VIEWER) == "E-08"  # store: missing is not active
    assert post_rule(P("post"), U("author", moderation={"state": "active"}), VIEWER) is None


def test_e09_suspended_or_removed_once_db08_exists() -> None:
    assert post_rule(P("post"), U("author", restriction_level="Suspended"), VIEWER) == "E-09"
    assert post_rule(P("post"), U("author", restriction_level="warning"), VIEWER) is None
    assert post_rule(P("post"), AUTHOR, VIEWER) is None  # no field yet: nothing to apply


def test_e10_own_posts_and_products() -> None:
    me = Viewer(user_id=str(C["author"]), own_ids=frozenset({str(C["author"]), str(C["seller"])}), date_of_birth=date(1990, 1, 1))
    assert post_rule(P("post"), AUTHOR, me) == "E-10"
    assert product_rule(PR("product"), B("seller"), VARIANTS("product"), me) == "E-10"
    assert post_rule(P("post"), AUTHOR, VIEWER) is None


def test_e11_adult_only_content() -> None:
    minor = Viewer(user_id=str(C["minor"]), date_of_birth=date.today() - timedelta(days=365 * 15))
    no_dob = Viewer(user_id="x", date_of_birth=None)
    assert post_rule(P("adult_post"), AUTHOR, minor) == "E-11"
    assert post_rule(P("adult_post"), AUTHOR, no_dob) == "E-11"
    assert post_rule(P("adult_post"), AUTHOR, VIEWER) is None  # an adult
    assert post_rule(P("post"), AUTHOR, minor) is None  # 'All'


def test_e12_deranked_or_removed() -> None:
    assert post_rule(P("deranked_post"), AUTHOR, VIEWER) == "E-12"
    assert post_rule(P("post", compliance={"status": "Removed"}), AUTHOR, VIEWER) == "E-12"
    assert post_rule(P("under_review_post"), AUTHOR, VIEWER) is None  # served as normal


@pytest.mark.parametrize("compliance", [{"status": "ok"}, {"status": "review"}, {"status": "fix_requested"}, None],
                         ids=["ok", "review", "fix_requested", "none"])
def test_e12_serves_every_other_compliance_status(compliance) -> None:
    """ENG-30 point 11 (a check only): E-12 excludes only deranked and removed."""
    post = P("post", compliance=compliance) if compliance else P("post")
    assert post_rule(post, AUTHOR, VIEWER) is None


# --- on a database ----------------------------------------------------------------------


@pytest_asyncio.fixture
async def seeded(settings):
    store_conn.init_client(settings)
    platform_conn.init_client(settings)
    try:
        await store_conn.ml_db(settings).command("ping")
    except Exception as exc:  # pragma: no cover - environment dependent
        await platform_conn.close_client()
        await store_conn.close_client()
        pytest.skip(f"MongoDB unreachable: {type(exc).__name__}")
    platform = platform_conn.app_db(settings)
    engine = store_conn.ml_db(settings)
    for name, docs in DATA.items():
        await platform[name].drop()
        await platform[name].insert_many(docs)
    await engine["ml_events"].drop()
    await writers.ensure_engine_collections(settings)
    yield settings, platform, engine
    for name in DATA:
        await platform[name].drop()
    await engine["ml_events"].drop()
    await platform_conn.close_client()
    await store_conn.close_client()


@pytest.mark.mongo
async def test_the_viewer_context_comes_from_the_platform_and_the_engine_copy(seeded) -> None:
    settings, _, engine = seeded
    now = utc_now()
    await engine["ml_events"].insert_many([
        {"_id": ObjectId(), "user_id": str(C["viewer"]), "event_type": "feedback", "feedback_type": "not_interested",
         "post_id": str(C["product_post"]), "created_at": now, "undone_at": None},
        {"_id": ObjectId(), "user_id": str(C["viewer"]), "event_type": "feedback", "feedback_type": "mute_author",
         "post_id": str(C["post"]), "created_at": now, "undone_at": None},
        {"_id": ObjectId(), "user_id": str(C["viewer"]), "event_type": "feedback", "feedback_type": "hide",
         "post_id": str(C["adult_post"]), "created_at": now - timedelta(days=91), "undone_at": None},  # too old
        # E13 shape (F61, F62): target_id with target_type
        {"_id": ObjectId(), "user_id": str(C["viewer"]), "event_type": "feedback", "feedback_type": "report",
         "target_id": str(C["unmapped_category_post"]), "target_type": "post", "created_at": now, "undone_at": None},
        # E-02 has no time limit: a mute from a year ago still applies
        {"_id": ObjectId(), "user_id": str(C["viewer"]), "event_type": "feedback", "feedback_type": "mute_author",
         "target_id": str(C["private_author"]), "target_type": "author", "created_at": now - timedelta(days=365), "undone_at": None},
        # an undone mute does not apply
        {"_id": ObjectId(), "user_id": str(C["viewer"]), "event_type": "feedback", "feedback_type": "mute_author",
         "target_id": str(C["inactive_author"]), "target_type": "author", "created_at": now, "undone_at": now},
    ])
    viewer = await apply.viewer_context(settings, str(C["viewer"]))
    assert str(C["blocker"]) in viewer.blocked  # E-01, from followers, read now
    assert {str(C["author"]), str(C["seller"])} <= viewer.follows  # follows with ids as text and as ObjectId
    assert str(C["product_post"]) in viewer.dismissed and str(C["adult_post"]) not in viewer.dismissed
    assert str(C["author"]) in viewer.muted  # the mute was recorded against a post: its author
    assert str(C["unmapped_category_post"]) in viewer.dismissed  # target_id / target_type
    assert str(C["private_author"]) in viewer.muted and str(C["inactive_author"]) not in viewer.muted
    assert viewer.is_adult


@pytest.mark.mongo
async def test_each_exclusion_is_logged_with_request_id_item_and_rule(seeded, caplog) -> None:
    settings, _, _ = seeded
    viewer = await apply.viewer_context(settings, str(C["viewer"]))
    posts = [records.parse_post(d, VOCAB) for d in DATA["posts"]]
    with caplog.at_level(logging.INFO, logger="reco.eligibility"):
        kept = await apply.eligible_posts(settings, posts, viewer, request_id="req-test-1")
    logged = {(r.item_id, r.rule) for r in caplog.records if getattr(r, "request_id", None) == "req-test-1"}
    assert (str(C["hidden_post"]), "E-04") in logged and (str(C["deranked_post"]), "E-12") in logged
    assert (str(C["inactive_author_post"]), "E-08") in logged and (str(C["private_author_post"]), "E-05") in logged
    assert {p.post_id for p in kept} >= {str(C["post"]), str(C["product_post"]), str(C["under_review_post"])}
    assert len(logged) + len(kept) == len(posts)


@pytest.mark.mongo
async def test_an_item_failing_the_final_recheck_is_replaced(seeded) -> None:
    settings, platform, _ = seeded
    viewer = await apply.viewer_context(settings, str(C["viewer"]))
    cards = [Candidate(str(C[k]), "post", str(C[k]), None, rank=n) for n, k in
             enumerate(("post", "product_post", "under_review_post", "unmapped_category_post"), start=1)]
    # Hidden on the platform after the list was built, before it is returned.
    await platform[PLATFORM_COLLECTIONS["post"]].update_one({"_id": C["product_post"]}, {"$set": {"isHidden": True}})

    built = serving.Built(viewer, cards, {}, len(cards))
    page = await serving.page_after_recheck(settings, built, page=1, limit=2, request_id="req-test-2")

    assert [c.item_id for c in page] == [str(C["post"]), str(C["under_review_post"])]


@pytest.mark.mongo
async def test_e07_a_post_card_showing_an_unsellable_product_is_left_out(seeded) -> None:
    settings, platform, _ = seeded
    viewer = await apply.viewer_context(settings, str(C["viewer"]))
    card = records.parse_post(doc("posts", "product_post"), VOCAB)
    assert [p.post_id for p in await apply.eligible_posts(settings, [card], viewer)] == [card.post_id]
    await platform[PLATFORM_COLLECTIONS["variant"]].update_many({"productId": C["product"]}, {"$set": {"quantity": 0}})
    assert await apply.eligible_posts(settings, [card], viewer) == []
