"""Constructed platform-shaped data for the M1 checks. ENG-11 (and ENG-10, ENG-09).

    dataset, users, expect = build_m1_dataset(now)

`dataset` is collection -> documents, shaped as the platform stores them (the same
shapes as tests/platform_dataset.py). `users` names each constructed user; each
is built for one check of ENG-11:

    decay          Home & Living liked yesterday, Electronics liked 60 days ago (more of it):
                   decay on ranks Home & Living first; a plain sum ranks Electronics first (4)
    floor          declared Pets, and one Electronics click 200 days ago: Pets raw is
                   exactly the floor, 10, undecayed (5)
    cancelled      an Electronics order that was cancelled, one that was returned, and a
                   Pets view: Electronics nets to exactly zero (6)
    unmappable     actions on a "Fishing" post and on posts with malformed categories,
                   and one Home & Living like: only Home & Living is scored (7)
    views          Pets views of 2.0 s, 2.999 s, 4 s and 5 s (the last two on one post):
                   event_count for Pets is 1 (8)
    negative       a Home & Living like (+3), a Hide on Home & Living (-5) and a Pets like:
                   Home & Living clips to 0, never below (3)
    undo           an Electronics like undone, and a Pets like: no Electronics (ENG-10 undo)
    rung1 .. rung5 one user per ladder rung (10): rung1 and rung4 have 5+ actions
                   (rung4 is read 49 hours later), rung2 declared Pets with one action,
                   rung3 nothing, rung5 read with the engine store down; rung4 and
                   rung5 carry an old delivered score
    nothing        no actions and nothing declared: no score (1, by exclusion)
    tester         a test account (in the settings' test_accounts) with six Home & Living likes:
                   left out of scoring (12)

The "Fishing" post is also the unmapped category the daily check reports (13).

Pack v1.4 and Kala's answers of 16 Oct:

    returner       a Delivered Electronics order with an OPEN return request, and a
                   Pets like: the purchase is out while the request is open (14);
                   when the request ends without a return it comes back
    selfseed       three likes on their own post (is_self) and three on a seed post
                   (_seedTag), two Home & Living likes on others' posts: the seed likes
                   are left out entirely, the own-post likes still score but don't
                   count; qualified_actions is 2 (16)
    every user     the ladder's count equals the stored qualified_actions (15)

`expect` holds what the checks compare against.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from bson import ObjectId

HOME, ELEC, PETS, FASHION = "Home & Living", "Electronics", "Pets", "Fashion & Apparel"


def build_m1_dataset(now: datetime | None = None) -> tuple[dict[str, list[dict[str, Any]]], dict[str, str], dict[str, Any]]:
    now = now or datetime.now(timezone.utc)
    ago = lambda **kw: now - timedelta(**kw)  # noqa: E731

    names = ("decay", "floor", "cancelled", "unmappable", "views", "negative", "undo",
             "rung1", "rung2", "rung3", "rung4", "rung5", "nothing", "author", "tester", "returner", "selfseed")
    uid = {n: ObjectId() for n in names}
    declared = {"floor": [PETS], "rung2": [PETS]}
    delivered = {"rung4": {FASHION: 7, "Cricket": 3}, "rung5": {PETS: 3}}
    users = [
        {"_id": uid[n], "status": "Active", "accountIsPublic": True, "interest": declared.get(n, []),
         **({"interestScores": delivered[n]} if n in delivered else {})}
        for n in names
    ]

    # --- posts, by category -----------------------------------------------------------
    posts: list[dict[str, Any]] = []

    def post(categories: Any) -> ObjectId:
        pid = ObjectId()
        posts.append({"_id": pid, "userId": uid["author"], "userModel": "user", "timestamp": ago(days=100),
                      "visibility": "public", "isHidden": False, "categories": categories, "postType": "normal"})
        return pid

    home, home2, elec, pets, pets2, pets3, fashion = (post([c]) for c in (HOME, HOME, ELEC, PETS, PETS, PETS, FASHION))
    own = post([HOME])
    posts[-1]["userId"] = uid["selfseed"]  # selfseed's own post
    seeded = post([HOME])
    posts[-1]["_seedTag"] = "soco-seed-2024"  # test data (ENG-30 point 9)
    # "Fishing" has no match in the 23 or in the category map (the app's own map gives it
    # none), so it stays unmapped. ("Cricket" maps to Sports & Outdoors since 16 Oct.)
    cricket, malformed = post(["Fishing"]), post([None, 5, "", {"x": 1}])

    # --- products, through the category tree -------------------------------------------
    cat_elec = ObjectId()
    categories = [{"_id": cat_elec, "name": ELEC, "level": 0, "path": [ELEC]}]
    gadget = ObjectId()
    products = [{"_id": gadget, "createdBy": ObjectId(), "createdAt": ago(days=50), "status": "Activate",
                 "availability": {"inStock": True}, "categoryPathIds": [cat_elec]}]

    # --- postevents ---------------------------------------------------------------------
    postevents: list[dict[str, Any]] = []

    def event(who: str, kind: str, when: datetime, **fields: Any) -> ObjectId:
        eid = ObjectId()
        postevents.append({"_id": eid, "event_id": f"ev_{eid}", "event_type": kind, "user_id": uid[who],
                           "user_model": "user", "surface": "home_for_you", "item_type": "post",
                           "created_at": when, "updated_at": when, **fields})
        return eid

    # (4) decay: Home & Living 2 likes yesterday (6); Electronics 3 likes 60 days ago (9)
    for _ in range(2):
        event("decay", "like", ago(days=1), post_id=home)
    for _ in range(3):
        event("decay", "like", ago(days=60), post_id=elec)
    # (5) floor: one old click outside the windows; the Pets floor stays exactly 10
    event("floor", "click", ago(days=200), post_id=elec)
    # (6) cancelled: a qualified Pets view (orders below)
    event("cancelled", "view", ago(days=2), post_id=pets, dwell_ms=4000)
    # (7) unmappable
    event("unmappable", "like", ago(days=2), post_id=cricket)
    event("unmappable", "click", ago(days=2), post_id=malformed)
    event("unmappable", "like", ago(days=2), post_id=home)
    # (8) views
    event("views", "view", ago(days=1), post_id=pets, dwell_ms=2000)
    event("views", "view", ago(days=1), post_id=pets2, dwell_ms=2999)
    event("views", "view", ago(days=2), post_id=pets3, dwell_ms=4000)
    event("views", "view", ago(days=1), post_id=pets3, dwell_ms=5000)
    # (3) negative
    event("negative", "like", ago(days=1), post_id=home)
    event("negative", "feedback", ago(days=1), post_id=home2, feedback_type="hide")
    event("negative", "like", ago(days=1), post_id=pets)
    # undo
    liked = event("undo", "like", ago(days=3), post_id=elec, undone_at=ago(days=2))
    event("undo", "unlike", ago(days=2), post_id=elec, undo_of=f"ev_{liked}")
    event("undo", "like", ago(days=1), post_id=pets)
    # (10) the ladder: rung1 and rung4 have 5+ qualified actions; rung2 one
    for who in ("rung1", "rung4"):
        for _ in range(5):
            event(who, "like", ago(days=1), post_id=fashion)
        event(who, "view", ago(days=1), post_id=fashion, dwell_ms=6000)
    event("rung2", "like", ago(days=1), post_id=pets)
    # (14) returner: a Pets like (the purchase is below, with its open return request)
    event("returner", "like", ago(days=1), post_id=pets)
    # (16) selfseed: likes on their own post and on a seed post, and two ordinary ones
    for _ in range(3):
        event("selfseed", "like", ago(days=1), post_id=own, is_self=True)
        event("selfseed", "like", ago(days=1), post_id=seeded)
    for target in (home, home2):
        event("selfseed", "like", ago(days=1), post_id=target)
    # (12) a test account: plenty of activity, never scored
    for _ in range(6):
        event("tester", "like", ago(days=1), post_id=home)

    # --- orders -------------------------------------------------------------------------
    def order(who: str, status: str, hours: int) -> dict[str, Any]:
        oid = ObjectId()
        return {"_id": oid, "user_id": uid[who], "userModel": "user", "seller_id": ObjectId(), "product_id": gadget,
                "order_status": status, "buyer_approval_status": "Accepted", "isIncognitoMode": False,
                "total_price": 999, "quantity": 1,
                "tracking_info": [{"_id": ObjectId(), "status": "Order created by Buyer", "timestamp": ago(hours=hours)},
                                  {"_id": ObjectId(), "status": f"{status} (check)", "timestamp": ago(hours=hours - 1)}],
                "created_at": ago(hours=hours), "updated_at": ago(hours=hours - 1)}

    orders = [order("cancelled", "Cancelled", 72), order("cancelled", "Returned", 48)]
    # (14) a Delivered order with an open return request (ENG-30 points 7, 10)
    returned_order = order("returner", "Delivered", 96)
    orders.append(returned_order)
    request_id = ObjectId()
    returnrequests = [{"_id": request_id, "returnNumber": "RET-CHECK1", "orderId": returned_order["_id"],
                       "status": "requested", "isActive": True, "createdAt": ago(hours=20), "updatedAt": ago(hours=20),
                       "windowEndsAt": ago(hours=-100), "policySnapshot": {"windowDays": 7},
                       "comment": "never copied", "pickupAddress": {"phone": "+91 90000 00000"}}]

    # --- a business follow, for rung 2 (an action, and Pets) ------------------------------
    pet_shop = ObjectId()
    businesses = [{"_id": pet_shop, "user_id": uid["author"], "category": PETS, "status": "Active"}]
    follows = [{"_id": ObjectId(), "userId": str(uid["rung2"]), "followingId": str(pet_shop),
                "followingReference": "businessRegister", "createdAt": ago(days=1)}]

    dataset = {"users": users, "posts": posts, "products": products, "categories": categories,
               "businessregisters": businesses, "follows": follows, "postevents": postevents, "orders": orders,
               "recommendationrequests": [], "returnrequests": returnrequests}
    expect = {
        "scored": {"decay", "floor", "cancelled", "unmappable", "views", "negative", "undo", "rung1", "rung2", "rung4",
                   "returner", "selfseed"},
        "not_scored": {"rung3", "rung5", "nothing", "author", "tester"},
        "test_account": "tester",
        "unmapped": "Fishing",
        "return_request_id": request_id,
        "selfseed_qualified": 2,
        "rungs": {"rung1": None, "rung2": "rung_2", "rung3": "rung_3", "rung4": "rung_4", "rung5": "rung_5"},
    }
    return dataset, {n: str(i) for n, i in uid.items()}, expect
