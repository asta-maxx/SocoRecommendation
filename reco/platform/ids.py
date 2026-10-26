"""Text <-> ObjectId conversion, in exactly one place. S10.

SOCO stores identifiers inconsistently: posts and follows hold them as text,
likes and events as ObjectId, and posts.userId holds BOTH forms across different
documents. A wrong-typed query returns nothing rather than failing, so the
mistake looks like an absence of data instead of a bug. That is why this exists
once and is used everywhere, and why the match helper below queries for both
forms rather than guessing which one a collection uses.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from bson import ObjectId
from bson.errors import InvalidId


def is_object_id(value: Any) -> bool:
    """Whether a value is, or could be parsed as, an ObjectId."""
    if isinstance(value, ObjectId):
        return True
    if not isinstance(value, str):
        return False
    return ObjectId.is_valid(value)


def to_object_id(value: Any) -> ObjectId:
    """Coerce to ObjectId, raising on anything that is not one.

    Raises rather than returning None: a silent None becomes a query that matches
    nothing, which is the exact failure this module exists to prevent.
    """
    if isinstance(value, ObjectId):
        return value
    if isinstance(value, str):
        try:
            return ObjectId(value)
        except (InvalidId, TypeError) as exc:
            raise ValueError(f"not a valid ObjectId: {value!r}") from exc
    raise ValueError(f"not a valid ObjectId: {value!r}")


def to_str(value: Any) -> str:
    """Coerce an identifier to its text form.

    Score documents key on the text form: it round-trips through JSON, and the
    store must not depend on which type a given source collection happened to use.
    """
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, str):
        return value
    raise ValueError(f"not an identifier: {value!r}")


def id_match(value: Any) -> dict[str, list[Any]]:
    """A query fragment matching an identifier stored as EITHER text or ObjectId.

    Use for any field known to hold both -- posts.userId is the documented case.
    Matching one form returns a partial result set, which is worse than an empty
    one because it looks like the query worked.

        collection.find({"userId": id_match(user_id)})
    """
    text = to_str(value)
    forms: list[Any] = [text]
    if ObjectId.is_valid(text):
        forms.append(ObjectId(text))
    return {"$in": forms}


def maybe_str(value: Any) -> str | None:
    """The text form of an identifier, or None when the field is empty.

    For optional references (an order's post_id, a cart line's request_id). A
    required identifier uses to_str(), which raises instead.
    """
    if value is None or value == "":
        return None
    return to_str(value)


def as_utc(value: Any) -> datetime | None:
    """A stored time as an aware UTC datetime, or None if it is not a time."""
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return None


def time_of(doc: dict[str, Any], *fields: str) -> datetime | None:
    """ENG-03: the record's time from its named field, else from its _id.

    "Where a time field is missing, the time is read from the record's _id": an
    ObjectId carries the second it was created. Returns None only when neither
    the field nor the _id gives a time.
    """
    for field in fields:
        found = as_utc(doc.get(field))
        if found is not None:
            return found
    raw_id = doc.get("_id")
    if isinstance(raw_id, str) and ObjectId.is_valid(raw_id):
        raw_id = ObjectId(raw_id)
    if isinstance(raw_id, ObjectId):
        return raw_id.generation_time.astimezone(timezone.utc)
    return None
