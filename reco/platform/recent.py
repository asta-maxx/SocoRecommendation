"""Recent posts, for the post index. ENG-12 (and ENG-14, ENG-27).

    posts = await read_recent_posts(settings, since)

Every post created since `since` (posts.timestamp, else the time in its _id),
parsed by the ENG-03 rules: categories matched to the 23 (through the category
map), the seed flag (ENG-30 point 9), the repost flag. Only the fields the parser
uses are read (fetch._FIELDS).
"""

from __future__ import annotations

from datetime import datetime

from bson import ObjectId

from reco.config import PLATFORM_COLLECTIONS, Settings
from reco.platform import fetch
from reco.platform.connection import app_db
from reco.platform.records import PostRecord


async def read_recent_posts(settings: Settings, since: datetime) -> list[PostRecord]:
    parse = await fetch._parser(settings, "post")
    query = {"$or": [{"timestamp": {"$gte": since}},
                     {"timestamp": {"$exists": False}, "_id": {"$gte": ObjectId.from_datetime(since)}}]}
    cursor = app_db(settings)[PLATFORM_COLLECTIONS["post"]].find(query, fetch._FIELDS["post"])
    return [post async for doc in cursor if (post := parse(doc)).created_at and post.created_at >= since]
