"""Text <-> ObjectId conversion, in exactly one place. S10.

SOCO stores identifiers inconsistently: posts and follows hold them as text,
likes and events as ObjectId, and posts.userId holds BOTH forms across different
documents. A wrong-typed query returns nothing rather than failing, so the
mistake looks like an absence of data instead of a bug. That is why this exists
once and is used everywhere, and why the match helper below queries for both
forms rather than guessing which one a collection uses.
"""

from __future__ import annotations

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
