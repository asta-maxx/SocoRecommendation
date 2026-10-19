"""Constructed platform-shaped data for the engine's test environment. ENG-29 item 8.

    build_dataset(now) -> {collection name: [documents]}

Every platform collection the engine reads, filled with made-up records in the
platform's own field names (platform schema reference v4, as ENG-03 reads it).
Each record exists to make one rule checkable; CASES names them, so a test or a
check can find "the hidden post" or "the order with a return request" by key
instead of by position.

Nothing here is real data. Ids are fixed (ObjectIds built from a counter), so a
seeded database is the same every time. Written by scripts/seed_test_platform.py;
read by the tests and, later, by the ENG-23 engine tests (T1 to T9).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from bson import ObjectId

_counter = iter(range(1, 10_000))


#: Every id is stamped 1 Sep 2026 00:00 UTC, then a0a0, then a counter: fixed, and a
#: time read from an id (ENG-03) is a plausible past time.
_STAMP = 0x6A961580


def _id() -> ObjectId:
    return ObjectId(f"{_STAMP:08x}a0a0{next(_counter):012x}")


def build_dataset(now: datetime | None = None) -> tuple[dict[str, list[dict[str, Any]]], dict[str, ObjectId]]:
    """(collections, CASES). Times are relative to `now` (UTC)."""
    global _counter
    _counter = iter(range(1, 10_000))
    now = now or datetime.now(timezone.utc)
    ago = lambda **kw: now - timedelta(**kw)  # noqa: E731
    c: dict[str, ObjectId] = {}

    # --- accounts -------------------------------------------------------------
    for key in ("viewer", "author", "private_author", "blocker", "inactive_author", "test_account",
                "exempt_account", "minor", "buyer", "promoter"):
        c[key] = _id()
    users = [
        {"_id": c["viewer"], "status": "Active", "interest": ["Fashion & Apparel", "Fashion"], "DOB": "1995-04-02",
         "accountIsPublic": True, "city": "Chennai"},
        {"_id": c["author"], "status": "active", "interest": ["Home & Living"], "accountIsPublic": True},
        {"_id": c["private_author"], "status": "Active", "accountIsPublic": False},
        {"_id": c["blocker"], "status": "Active", "accountIsPublic": True},
        # users.status is not what the app uses: moderation.state is (16 Oct). Kept "Inactive"
        # to show the status field alone no longer hides anyone.
        {"_id": c["inactive_author"], "status": "Inactive", "moderation": {"state": "suspended"}, "accountIsPublic": True},
        {"_id": c["test_account"], "status": "Active", "interest": ["Beauty & Personal Care"], "accountIsPublic": True},
        {"_id": c["exempt_account"], "status": "Active", "accountIsPublic": True},
        {"_id": c["minor"], "status": "Active", "DOB": (now - timedelta(days=365 * 15)).date().isoformat()},
        {"_id": c["buyer"], "status": "Active", "accountIsPublic": True},
        {"_id": c["promoter"], "status": "Active", "accountIsPublic": True},
    ]
    c["seller"] = _id()
    c["inactive_seller"] = _id()
    businesses = [
        {"_id": c["seller"], "user_id": c["author"], "category": "Fashion & Apparel", "status": "Active", "accountIsPublic": True},
        {"_id": c["inactive_seller"], "user_id": c["inactive_author"], "category": "Fashion", "status": "Inactive"},
    ]

    # --- graph: follows and blocks -----------------------------------------------
    follows = [
        {"_id": _id(), "userId": str(c["viewer"]), "followingId": str(c["author"]), "followingReference": "user"},  # ids as text
        {"_id": _id(), "userId": c["viewer"], "followingId": c["seller"], "followingReference": "businessRegister"},
        {"_id": _id(), "userId": c["buyer"], "followingId": c["promoter"], "followingReference": "user"},
    ]
    # The app's shape (question 16, answered 16 Oct): follower_id blocked user_id.
    followers = [
        {"_id": _id(), "follower_id": c["blocker"], "user_id": str(c["viewer"]), "status": "blocked", "isBlocked": True},
    ]

    # --- categories tree ----------------------------------------------------------
    c["cat_fashion_top"] = _id()  # "Fashion": not one of the 23 by name; needs the category map
    c["cat_home_top"] = _id()  # "Home & Living": one of the 23 by name
    c["cat_shirts"] = _id()
    categories = [
        {"_id": c["cat_fashion_top"], "name": "Fashion", "level": 0, "path": ["Fashion"]},
        {"_id": c["cat_shirts"], "name": "Shirts", "level": 1, "path": ["Fashion", "Shirts"], "parent": c["cat_fashion_top"]},
        {"_id": c["cat_home_top"], "name": "Home & Living", "level": 0, "path": ["Home & Living"]},
    ]

    # --- products and variants ----------------------------------------------------
    for key in ("product", "product_out_of_stock", "product_inactive", "product_no_category"):
        c[key] = _id()
    products = [
        {"_id": c["product"], "createdBy": c["seller"], "createdAt": ago(days=3), "status": "Activate",
         "availability": {"inStock": True}, "basicInfo": {"categoryId": c["cat_shirts"]}, "crossSellProducts": []},
        {"_id": c["product_out_of_stock"], "createdBy": c["seller"], "createdAt": ago(days=2), "status": "activate",
         "availability": {"inStock": False}, "categoryPathIds": [c["cat_home_top"]]},
        {"_id": c["product_inactive"], "createdBy": c["inactive_seller"], "createdAt": ago(days=1), "status": "Deactivate",
         "availability": {"inStock": True}, "basicInfo": {"categoryId": c["cat_shirts"]}},
        {"_id": c["product_no_category"], "createdBy": c["seller"], "createdAt": ago(hours=5), "status": "Activated",
         "availability": {"inStock": True}},  # 'Activated': a spelling the status_spellings map can cover
    ]
    c["variant"] = _id()
    variants = [
        {"_id": c["variant"], "productId": c["product"], "sellerId": c["seller"], "salePrice": 799, "originalPrice": 999,
         "quantity": 10, "reservedStock": 2, "status": "Active"},
        {"_id": _id(), "productId": c["product_out_of_stock"], "sellerId": c["seller"], "salePrice": 499, "quantity": 0,
         "reservedStock": 0, "status": "Active"},
    ]

    # --- posts --------------------------------------------------------------------
    for key in ("post", "product_post", "hidden_post", "private_post", "deranked_post", "under_review_post",
                "private_author_post", "inactive_author_post", "adult_post", "unmapped_category_post", "test_account_post"):
        c[key] = _id()

    def post(key: str, author: str, minutes: int, **fields: Any) -> dict[str, Any]:
        return {"_id": c[key], "userId": c[author], "userModel": "user", "timestamp": ago(minutes=minutes),
                "visibility": "public", "isHidden": False, "categories": ["Fashion & Apparel"], "postType": "normal",
                "ageGroup": "All", "Product_status": "N/A", **fields}

    posts = [
        post("post", "author", 10),
        post("product_post", "author", 20, products=[c["product"]], Product_status="Activated", isProductPost=True),
        post("hidden_post", "author", 30, isHidden=True),
        post("private_post", "author", 40, visibility="private"),
        post("deranked_post", "author", 50, compliance={"status": "deranked"}),
        post("under_review_post", "author", 60, compliance={"status": "under_review"}),
        post("private_author_post", "private_author", 70),
        post("inactive_author_post", "inactive_author", 80),
        post("adult_post", "author", 90, ageGroup="18+"),
        post("unmapped_category_post", "author", 100, categories=["Cricket"]),
        post("test_account_post", "test_account", 110, categories=["Beauty & Personal Care"]),
    ]

    # --- events -------------------------------------------------------------------
    c["like"] = _id()
    c["unlike"] = _id()
    c["feed_product_click"] = _id()
    c["post_detail_impression"] = _id()

    def event(key: str | None, event_type: str, user: str, minutes: int, **fields: Any) -> dict[str, Any]:
        _key = c[key] if key else _id()
        t = ago(minutes=minutes)
        return {"_id": _key, "event_id": f"ev_{_key}", "event_type": event_type, "user_id": c[user], "user_model": "user",
                "surface": "home_for_you", "created_at": t, "updated_at": t, **fields}

    like_time = ago(minutes=9)
    postevents = [
        event("like", "like", "viewer", 9, post_id=c["post"], item_type="post", undone_at=ago(minutes=5),
              updated_at=ago(minutes=5)),
        event("unlike", "unlike", "viewer", 5, post_id=c["post"], item_type="post", undo_of=f"ev_{c['like']}"),
        # The feed click shape seen on the platform: post_id plus item_type product, no item_id.
        event("feed_product_click", "click", "viewer", 8, post_id=c["product_post"], product_id=c["product"],
              item_type="product", request_id="req_fallback_1", position=2),
        event("post_detail_impression", "impression", "viewer", 7, post_id=c["post"], surface="post_detail"),
        event(None, "view", "viewer", 6, post_id=c["post"], item_type="post", dwell_ms=4200, request_id="req_fallback_1", position=1),
        event(None, "save", "test_account", 4, post_id=c["post"], item_type="post"),
        event(None, "follow", "viewer", 3, influencer_id=c["author"]),
        event(None, "add_to_cart", "buyer", 60 * 24, product_id=c["product"], variant_id=c["variant"], quantity=1, item_type="product"),
        event(None, "purchase", "buyer", 60 * 23, product_id=c["product"], order_id=None, value=799),
        event(None, "feedback", "viewer", 2, post_id=c["deranked_post"], feedback_type="not_interested"),
    ]
    del like_time

    # --- orders: tracking_info as the history (ENG-29 item 4) -----------------------
    for key in ("order_delivered", "order_returned", "order_cancelled_by_seller", "order_incognito", "order_pending"):
        c[key] = _id()

    def order(key: str, status: str, approval: str, steps: list[tuple[str, int]], **fields: Any) -> dict[str, Any]:
        return {"_id": c[key], "user_id": c["buyer"], "userModel": "user", "seller_id": c["seller"], "product_id": c["product"],
                "variant_id": c["variant"], "post_id": c["product_post"], "promoter_id": c["promoter"],
                "checkout_id": f"chk_{c[key]}", "total_price": 799, "quantity": 1, "order_status": status,
                "buyer_approval_status": approval, "isIncognitoMode": False,
                "tracking_info": [{"_id": _id(), "status": text, "timestamp": ago(hours=h)} for text, h in steps],
                "created_at": ago(hours=steps[0][1]), "updated_at": ago(hours=steps[-1][1]), **fields}

    orders = [
        order("order_delivered", "Delivered", "Accepted", [("Order created by Buyer One", 100), ("Order Accepted By Seller", 90),
              ("Shipped by seller", 80), ("Delivered (Test Seller Studio)", 70)]),
        # v1.4 (ENG-30 points 5, 6): no Return Requested status. The seller's return sets
        # Returned and return_info.returned_at; the request and refund are history events.
        order("order_returned", "Returned", "Accepted", [("Order created by Buyer One", 60),
              ("Delivered (Test Seller Studio)", 50), ("Return requested (RET-TEST0001)", 45),
              ("Refund of ₹799 initiated", 42), ("Returned to seller", 40)],
              return_info={"reason": "Arrived damaged or broken", "recorded_by": "seller", "returned_at": ago(hours=40)}),
        order("order_cancelled_by_seller", "Rejected", "Rejected By Seller", [("Order created by Buyer One", 30),
              ("Cancelled by seller", 29)], reject_reason_by_buyer="out of stock"),
        order("order_incognito", "Pending", "Pending", [("Order created by Buyer One", 20)], isIncognitoMode=True),
        order("order_pending", "Pending", "Pending", [("Order created by Buyer One", 10)], isIncognitoMode=None),
    ]

    # --- carts ----------------------------------------------------------------------
    carts = [
        {"_id": _id(), "user_id": c["buyer"], "userModel": "user", "product_id": c["product"], "variant_id": c["variant"],
         "post_id": c["product_post"], "quantity": 1, "ml": {"request_id": "req_fallback_1"}, "createdAt": ago(days=1)},
    ]

    # --- served lists and the serve log -----------------------------------------------
    c["fallback_list"] = _id()
    recommendationrequests = [
        {"_id": c["fallback_list"], "request_id": "req_fallback_1", "user_id": c["viewer"], "userModel": "user",
         "surface": "home_for_you", "policy_id": "wave1a_v1", "candidate_ids": [c["post"], c["product_post"]],
         "seen_ids": [c["post"]], "session_id": "ses_test_1", "page": 1, "server_ts": ago(minutes=11), "updated_at": ago(minutes=6)},
    ]
    rec_serve_log = [
        {"_id": _id(), "request_id": "req_fallback_1", "user_id": c["viewer"], "surface": "feed", "page": 1,
         "origin": "fallback", "outcome": "timeout", "elapsed_ms": 251, "time": ago(minutes=11)},
        {"_id": _id(), "request_id": "6f1d6c2e-0b7e-4d33-9e44-2b8c1c6b1a01", "user_id": c["viewer"], "surface": "feed",
         "page": 2, "origin": "engine", "outcome": "ok", "elapsed_ms": 74, "time": ago(minutes=10)},
        {"_id": _id(), "request_id": "6f1d6c2e-0b7e-4d33-9e44-2b8c1c6b1a01", "user_id": c["viewer"], "surface": "feed",
         "page": 2, "origin": "cache", "outcome": "ok", "elapsed_ms": 3, "time": ago(minutes=9)},
    ]

    # --- return requests (ENG-30 point 7): one closed, one open; personal fields included
    # here on purpose, so a test can show they never reach the engine.
    c["return_closed"], c["return_open"] = _id(), _id()
    personal = {"pickupAddress": {"line1": "12 Test Street", "phone": "+91 90000 00000"}, "comment": "box was torn",
                "photos": ["https://example.test/p.jpg"], "refund": {"destination": "UPI test@upi", "amount": 799}}
    returnrequests = [
        {"_id": c["return_closed"], "returnNumber": "RET-TEST0001", "orderId": c["order_returned"], "buyerId": c["buyer"],
         "status": "completed", "isActive": False, "createdAt": ago(hours=45), "completedAt": ago(hours=40),
         "updatedAt": ago(hours=40), "windowEndsAt": ago(hours=-200), "policySnapshot": {"windowDays": 7, "source": "product"},
         **personal},
        {"_id": c["return_open"], "returnNumber": "RET-TEST0002", "orderId": c["order_delivered"], "buyerId": c["buyer"],
         "status": "requested", "isActive": True, "createdAt": ago(hours=20), "completedAt": None,
         "updatedAt": ago(hours=20), "windowEndsAt": ago(hours=-100), "policySnapshot": {"windowDays": 7, "source": "product"},
         **personal},
    ]

    # ENG-30 point 4: commission settings, platform and store rows (read raw by
    # reco.platform.commission; the merge is tested in tests/test_commission.py).
    commissionconfigs = [
        {"_id": _id(), "scope": "platform", "scopeId": None, "enabled": True, "poolPercent": 10, "holdDays": 7,
         "updatedAt": ago(days=3)},
        {"_id": _id(), "scope": "seller", "scopeId": str(c["seller"]), "poolPercent": 5, "updatedAt": ago(days=2)},
    ]

    return {
        "users": users,
        "businessregisters": businesses,
        "follows": follows,
        "followers": followers,
        "categories": categories,
        "products": products,
        "productvariants": variants,
        "posts": posts,
        "postevents": postevents,
        "orders": orders,
        "carts": carts,
        "recommendationrequests": recommendationrequests,
        "rec_serve_log": rec_serve_log,
        "returnrequests": returnrequests,
        "commissionconfigs": commissionconfigs,
    }, c
