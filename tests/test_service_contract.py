"""The service contract, enforced rather than merely agreed. RE-00d.

The register is the authority. The strongest test here reads the DS-003 capture
register straight out of the workbook and fails if any event carries a field the
register does not name -- beyond the few marked additions -- or lacks one it does.
"""

from __future__ import annotations

import json
import re
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4
from xml.etree import ElementTree

import pytest
from pydantic import ValidationError

from reco.config import Settings
from tests.conftest import m1_tunables
from reco.api.contract import (
    BEYOND_THE_REGISTER,
    CONTRACT_VERSION,
    EVENT_MODELS,
    EVENTS_COLLECTION,
    INGEST_PATH,
    M1_WEIGHT_KEY,
    MAX_EVENTS_PER_REQUEST,
    RECOMMENDATIONS_PATH,
    REGISTER_DECISION,
    REGISTER_ID,
    EventName,
    IngestRequest,
    IngestResponse,
    RecommendationsRequest,
    RecommendationsResponse,
    parse_batch,
    to_document,
)

REGISTER = (
    Path(__file__).resolve().parents[1]
    / "reference"
    / "SOCO-REC-DS-003_Sprint1_Activity_Pack.xlsx"
)

UTC_NOW = "2026-09-15T09:30:02.114Z"
IST_NOW = "2026-09-15T15:00:02+05:30"


def event(name: str, **overrides) -> dict:
    """A valid event, spelled the way SOCO_BE would send it."""
    per_event = {
        "recommendation_request": {
            "request_id": "req_8f2a1c", "surface": "feed", "user_id": "usr_4471",
            "session_id": None, "candidate_ids": ["p1", "p2", "p3"],
            "policy_id": "wave1a_v1", "server_ts": UTC_NOW,
        },
        "recommendation_impression": {
            "request_id": "req_8f2a1c", "item_id": "p1", "item_type": "post",
            "position": 1, "viewport_entered": True, "dwell_ms": 2400,
            "is_exploration": False, "client_ts": IST_NOW,
        },
        "recommendation_click": {
            "request_id": "req_8f2a1c", "item_id": "p1", "position": 1,
            "server_ts": UTC_NOW,
        },
        "add_to_cart": {
            "request_id": None, "product_id": "prd_5512", "quantity": 2,
            "user_id": "usr_4471",
        },
        "order_placed": {
            "order_id": "ord_2210", "request_id": "req_8f2a1c",
            "line_items": [{"product_id": "prd_5512", "qty": 1, "price": 2499.0}],
            "promoter_id": None, "order_value": 2499.0, "server_ts": UTC_NOW,
            "checkout_id": "chk_2210",
        },
        "order_state_changed": {
            "order_id": "ord_2210", "new_state": "Cancelled",
            "reason_code": "changed_mind", "state_ts": UTC_NOW,
        },
        "payment_state_changed": {
            "order_id": "ord_2210", "new_state": "settled", "state_ts": UTC_NOW,
        },
        "commission_state_changed": {
            "commission_id": "com_7781", "promoter_id": "pro_0087",
            "order_id": "ord_2210", "new_state": "confirmed", "amount": 249.9,
            "state_ts": UTC_NOW,
        },
        "social_interaction": {
            "user_id": "usr_4471", "target_id": "pst_3390", "action": "save",
            "request_id": None, "server_ts": UTC_NOW,
        },
        "opportunity_state_changed": {
            "opportunity_id": "opp_1120", "promoter_id": "pro_0087",
            "campaign_id": None, "new_state": "completed", "state_ts": UTC_NOW,
        },
        "search_performed": {
            "user_id": "usr_4471", "query_text": "cotton kurta",
            "result_count": 23, "server_ts": UTC_NOW,
        },
        "identity_stitched": {
            "anonymous_id": "anon_c81f", "user_id": "usr_4471",
            "stitch_ts": UTC_NOW,
        },
    }
    row = {"event_id": str(uuid4()), "event_name": name, **per_event[name]}
    row.update(overrides)
    return row


def batch(*events: dict) -> dict:
    return {"contract_version": "1.0", "sent_at": UTC_NOW, "events": list(events)}


def only_error(body: dict) -> str:
    parsed = parse_batch(body)
    assert not parsed.events, "expected the event to be rejected"
    assert len(parsed.rejected) == 1
    return " ".join(parsed.rejected[0].errors)


# --- the register -----------------------------------------------------------------


def _register_rows() -> list[dict[str, str]]:
    """Every row of the Capture register sheet, as {column letter: text}."""
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    rel = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
    with zipfile.ZipFile(REGISTER) as book:
        strings = [
            "".join(t.text or "" for t in si.iter(f"{{{ns['m']}}}t"))
            for si in ElementTree.fromstring(book.read("xl/sharedStrings.xml"))
        ]
        rels = {
            r.get("Id"): r.get("Target")
            for r in ElementTree.fromstring(book.read("xl/_rels/workbook.xml.rels"))
        }
        sheets = ElementTree.fromstring(book.read("xl/workbook.xml")).find("m:sheets", ns)
        target = next(
            rels[s.get(rel)] for s in sheets if s.get("name") == "Capture register"
        )
        target = target.lstrip("/")
        sheet = ElementTree.fromstring(
            book.read(target if target.startswith("xl/") else f"xl/{target}")
        )

    rows = []
    for row in sheet.iter(f"{{{ns['m']}}}row"):
        cells = {}
        for cell in row.findall("m:c", ns):
            value = cell.find("m:v", ns)
            if value is None:
                continue
            text = strings[int(value.text)] if cell.get("t") == "s" else value.text
            cells[re.sub(r"\d", "", cell.get("r"))] = text
        rows.append(cells)
    return rows


needs_register = pytest.mark.skipif(
    not REGISTER.exists(), reason="DS-003 workbook not present in reference/"
)


@needs_register
def test_the_twelve_events_are_the_registers_twelve() -> None:
    registered = {
        row["B"]: row["A"]
        for row in _register_rows()
        if re.fullmatch(r"E\d+", row.get("A", ""))
    }
    assert len(registered) == 12
    assert {name.value: REGISTER_ID[name] for name in EventName} == registered


@needs_register
def test_the_event_decisions_match_the_register() -> None:
    decisions = {
        row["B"]: row.get("J")
        for row in _register_rows()
        if re.fullmatch(r"E\d+", row.get("A", ""))
    }
    assert {name.value: REGISTER_DECISION[name] for name in EventName} == decisions


@needs_register
def test_every_field_is_the_registers_plus_the_marked_additions() -> None:
    """A field the register does not name must be declared as an addition, with
    a reason in the module. A registered field the contract dropped fails here."""
    registered: dict[str, set[str]] = {}
    for row in _register_rows():
        if re.fullmatch(r"F\d+", row.get("A", "")):
            registered.setdefault(row["B"], set()).add(row["C"])

    for name, model in EVENT_MODELS.items():
        assert set(model.model_fields) == registered[name.value] | BEYOND_THE_REGISTER[name], name


# --- the agreed names -----------------------------------------------------------------


def test_one_endpoint_for_all_twelve() -> None:
    assert INGEST_PATH == "/v1/events"
    assert RECOMMENDATIONS_PATH == "/v1/recommendations"
    assert EVENTS_COLLECTION.startswith("ml_")


def test_every_event_validates_through_the_one_request_shape() -> None:
    body = batch(*(event(name) for name in EventName))
    parsed = parse_batch(body)
    assert parsed.rejected == []
    assert {e.event_name for e in parsed.events} == set(EventName)
    IngestRequest.model_validate(body)


def test_every_event_has_a_decision_about_what_m1_reads() -> None:
    assert set(M1_WEIGHT_KEY) == set(EventName)
    weight_keys = set(m1_tunables()["P-06"])
    for weight in M1_WEIGHT_KEY.values():
        assert weight is None or weight in weight_keys
    # Every P-06 weight has an event to be paid on: in this (pre-v1.3) contract, or,
    # since ENG-10, among the actions read from the engine's copies.
    from reco.slots.interest.common import WEIGHT_KEY
    from reco.slots.interest.copies import ACTION
    from reco.slots.interest.events import EventType

    from_copies = {WEIGHT_KEY[a] for a in ACTION.values()} | {WEIGHT_KEY[EventType.PURCHASE], WEIGHT_KEY[EventType.BUSINESS_FOLLOW]}
    assert weight_keys <= set(M1_WEIGHT_KEY.values()) | from_copies


def test_a_renamed_field_is_rejected() -> None:
    row = event("recommendation_click")
    row["requestId"] = row.pop("request_id")
    assert parse_batch(batch(row)).rejected


def test_a_weight_on_the_event_is_rejected() -> None:
    """Weights come from P-06. A caller-supplied one would make P-06 decorative."""
    assert parse_batch(batch(event("order_placed", weight=20))).rejected


def test_an_absent_nullable_key_is_rejected_but_an_explicit_null_is_not() -> None:
    row = event("recommendation_impression", dwell_ms=None)
    assert parse_batch(batch(row)).rejected == []
    del row["dwell_ms"]
    assert "dwell_ms" in only_error(batch(row))


def test_a_blank_identifier_is_rejected() -> None:
    assert "request_id" in only_error(batch(event("recommendation_click", request_id="  ")))


# --- R7, time discipline ------------------------------------------------------------------


@pytest.mark.parametrize(
    "name, field",
    [
        ("recommendation_request", "server_ts"),
        ("order_state_changed", "state_ts"),
        ("identity_stitched", "stitch_ts"),
    ],
)
def test_a_server_time_must_be_utc(name: str, field: str) -> None:
    assert "UTC" in only_error(batch(event(name, **{field: IST_NOW})))
    assert "UTC" in only_error(batch(event(name, **{field: "2026-09-15T09:30:02"})))


def test_client_ts_must_carry_an_offset_and_keeps_it() -> None:
    naive = event("recommendation_impression", client_ts="2026-09-15T15:00:02")
    assert "offset" in only_error(batch(naive))

    row = event("recommendation_impression")
    stored = to_document(parse_batch(batch(row)).events[0], datetime.now(timezone.utc))
    assert stored["client_ts"].endswith("+05:30")


# --- the rules that carry meaning -----------------------------------------------------------


def test_positions_count_from_one() -> None:
    assert "position" in only_error(batch(event("recommendation_impression", position=0)))


def test_order_states_are_order_status_values() -> None:
    """Q06: order_status is canonical. Returned and Refunded do not exist (D1)."""
    for state in ("returned", "Pending", "delivered"):
        assert "new_state" in only_error(batch(event("order_state_changed", new_state=state)))


def test_a_campaign_id_may_be_null_until_q02() -> None:
    assert parse_batch(batch(event("opportunity_state_changed", campaign_id=None))).rejected == []


def test_an_order_has_at_least_one_line() -> None:
    assert "line_items" in only_error(batch(event("order_placed", line_items=[])))


# --- the batch ---------------------------------------------------------------------------------


def test_one_bad_event_does_not_discard_the_rest() -> None:
    good = event("order_placed")
    bad = event("recommendation_impression", dwell_ms=-1)
    parsed = parse_batch(batch(good, bad))
    assert [str(e.event_id) for e in parsed.events] == [good["event_id"]]
    assert parsed.rejected[0].index == 1
    assert parsed.rejected[0].event_id == bad["event_id"]


def test_a_repeated_event_id_in_one_request_is_a_duplicate_not_an_error() -> None:
    row = event("social_interaction")
    parsed = parse_batch(batch(row, dict(row)))
    assert len(parsed.events) == 1
    assert parsed.duplicates_in_request == 1
    assert parsed.rejected == []


@pytest.mark.parametrize(
    "body",
    [
        {"contract_version": "2.0", "sent_at": UTC_NOW, "events": [{}]},
        {"contract_version": "1.0", "sent_at": UTC_NOW, "events": []},
        {"contract_version": "1.0", "events": [{}]},
        {"contract_version": "1.0", "sent_at": UTC_NOW, "events": [{}], "extra": 1},
    ],
)
def test_an_unusable_envelope_is_refused_whole(body: dict) -> None:
    with pytest.raises(ValidationError):
        parse_batch(body)


def test_the_batch_limit() -> None:
    rows = [event("social_interaction") for _ in range(MAX_EVENTS_PER_REQUEST + 1)]
    with pytest.raises(ValidationError):
        parse_batch(batch(*rows))


def test_the_response_accounts_for_every_event_sent() -> None:
    response = IngestResponse(
        contract_version="1.0", received_at=UTC_NOW, accepted=3, duplicates=1,
        rejected=[{"index": 4, "event_id": None, "errors": ["x"]}],
    )
    assert response.accepted + response.duplicates + len(response.rejected) == 5


def test_the_stored_document_is_the_event_plus_two_server_fields() -> None:
    row = event("order_placed")
    received = datetime.now(timezone.utc)
    stored = to_document(parse_batch(batch(row)).events[0], received)
    assert stored["event_id"] == row["event_id"]
    assert stored["received_at"] == received
    assert stored["contract_version"] == CONTRACT_VERSION
    assert set(stored) - set(row) == {"received_at", "contract_version"}


# --- POST /v1/recommendations -------------------------------------------------------------


def recommendations_response(**overrides) -> dict:
    body = {
        "contract_version": "1.0",
        "request_id": "req_8f2a1c",
        "policy_id": "wave1a_v1",
        "server_ts": UTC_NOW,
        "is_exploration": False,
        "personalised": True,
        "items": [
            {"item_id": "p1", "item_type": "post", "position": 1},
            {"item_id": "x9", "item_type": "product", "position": 2},
        ],
    }
    body.update(overrides)
    return body


def test_the_request_carries_what_dashboard_feed_already_sends() -> None:
    RecommendationsRequest.model_validate({
        "contract_version": "1.0", "user_id": "usr_4471", "surface": "feed",
        "limit": 20, "page": 1, "is_business_account": False, "refresh_seed": None,
    })


def test_the_response_carries_the_stamp_every_event_joins_to() -> None:
    response = RecommendationsResponse.model_validate(recommendations_response())
    assert response.request_id and response.policy_id

    # The fields a client echoes are spelled the same on both sides.
    impression = EVENT_MODELS[EventName.RECOMMENDATION_IMPRESSION].model_fields
    assert {"request_id", "is_exploration", "position", "item_id", "item_type"} <= set(impression)


@pytest.mark.parametrize("positions", [[0, 1], [1, 3], [2, 1]])
def test_response_positions_run_from_one_without_gaps(positions: list[int]) -> None:
    items = [
        {"item_id": f"p{i}", "item_type": "post", "position": p}
        for i, p in enumerate(positions)
    ]
    with pytest.raises(ValidationError):
        RecommendationsResponse.model_validate(recommendations_response(items=items))


def test_candidate_ids_are_never_returned_to_the_client() -> None:
    """F05 is held in the service. It belongs on the event, not the response."""
    assert "candidate_ids" not in RecommendationsResponse.model_fields
    with pytest.raises(ValidationError):
        RecommendationsResponse.model_validate(
            recommendations_response(candidate_ids=["p1"])
        )


# --- the file the backend reads ------------------------------------------------------------


def test_the_exported_schema_is_current() -> None:
    """Regenerate with: python scripts/export_contract_schema.py"""
    from scripts.export_contract_schema import OUT, render

    assert OUT.exists(), "run scripts/export_contract_schema.py"
    assert OUT.read_text(encoding="utf-8") == render(), (
        "docs/service_contract.schema.json is stale -- "
        "run scripts/export_contract_schema.py"
    )
    exported = json.loads(render())
    assert exported["x-endpoints"]["ingest"] == "POST /v1/events"
    assert len(exported["x-register"]) == 12
