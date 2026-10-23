"""Extraction against the *real* REsimpli response shapes (captured live 2026-10-21).

The v6 schema is undocumented, so these payloads pin what production actually
returns: /lead/list is flat (`mainStatusTitle`, `number`, `crmQuestionTitle`),
/lead/details nests everything under `leadData` with contact info in
`contactData`, and timestamps arrive as epoch milliseconds.
"""
from __future__ import annotations

from datetime import date

from app.services.normalization import parse_date_flexible, parse_datetime_flexible
from app.services.resimpli_client import normalize_activity_payload, normalize_lead_payload
from app.services.sync_service import upsert_activity_from_api, upsert_lead_from_api

LIVE_LIST_ITEM = {
    "_id": "68daf338ece71b30c782353e",
    "address": "10312 Arvin Hill Rd, Aubrey, TX 76227",
    "leadCreated": 1759208040000,
    "isHotLead": True,
    "mainStatusId": "6aa4dc48d18014f8fc5bd815",
    "mainStatusTitle": "Dead Lead",
    "marketingCampignId": "6aa4e649ab4bfde2eb52cd52",
    "marketingTitle": "Cold Calling High Business solutions",
    "crmQuestionTitle": "Cold Calling",
    "number": "+18178357361",
    "market": "Primary Market",
    "tags": ["sd"],
    "assignUser": {"6aa4dc46d18014f8fc5bcee9": ["68d6eda2e1e2edad75b1f400"]},
}

LIVE_DETAIL = {
    "leadData": {
        "_id": "68daf338ece71b30c782353e",
        "address": "10312 Arvin Hill Rd, Aubrey, TX 76227",
        "leadCreated": 1759208040000,
        "mainStatusTitle": "Dead Lead",
        "pipelineId": "6aa4dc48d18014f8fc5bd814",
        "priorityNumber": "+18176144309",
        "assignUser": {"6aa4dc46d18014f8fc5bcee9": ["68d6eda2e1e2edad75b1f400"]},
        "contactData": [
            {
                "firstName": "Peter",
                "lastName": "Vale",
                "fullName": "Peter Vale",
                "phoneNumbers": [{"phoneNumber": "+12146361338", "isPrimary": True, "doNotCall": False}],
                "emails": [{"email": "peter@example.com", "isPrimary": True}],
                "isSellerContact": True,
                "doNotCall": False,
                "doNotText": False,
            }
        ],
    }
}

LIVE_CALL_ACTIVITY = {
    "_id": "68db053343d458eb491ead0d",
    "subModuleId": "68daf338ece71b30c782353e",
    "comment": "You placed a call to",
    "activityType": 1,
    "voiceCallStatus": "no-answer",
    "to": "+12146361338",
    "from": "+18178357361",
    "direction": "outgoingCall",
    "iscallConnected": False,
    "createdAt": 1759184167694,
}

LIVE_NOTE_ACTIVITY = {
    "_id": "68db0444f769e25dd0dc75c4",
    "subModuleId": "68daf338ece71b30c782353e",
    "comment": "<p>he is asking 1.15 mill </p><p><br></p><p>will do 1.1 or 1.08</p>",
    "activityType": 8,
    "createdAt": 1759184167694,
}

LIVE_STATUS_ACTIVITY = {
    "_id": "69149b8c1777abe40703fb0b",
    "subModuleId": "68daf338ece71b30c782353e",
    "comment": "Changed lead status from New Leads to Discovery",
    "activityType": 10,
    "createdAt": 1762958220744,
}

MOCK_ITEM = {
    "_id": "66f1c2a9e4b0a1d3c8f20417",
    "contactDetails": {
        "firstName": "Dana",
        "lastName": "Whitfield",
        "phoneNumbers": [{"phoneNumber": "6145550142", "isPrimary": True}],
        "emails": [{"email": "dana.w@example.com", "isPrimary": True}],
    },
    "propertyDetails": {"address": "12 Oak St, Columbus, OH 43215"},
    "mainStatus": {"_id": "st_0", "name": "New Lead"},
    "leadSource": {"name": "Facebook"},
    "assignUser": {"name": "Sam Rivera"},
}


def test_normalize_live_lead_list_item():
    norm = normalize_lead_payload(LIVE_LIST_ITEM)
    assert norm["external_id"] == "68daf338ece71b30c782353e"
    assert norm["source_status"] == "Dead Lead"
    assert norm["primary_phone"] == "+18178357361"
    assert norm["lead_source"] == "Cold Calling"
    assert norm["address"] == "10312 Arvin Hill Rd, Aubrey, TX 76227"
    assert norm["is_hot_lead"] is True
    assert norm["tags"] == ["sd"]
    assert norm["assigned_user_id"] == "68d6eda2e1e2edad75b1f400"
    assert norm["original_creation_date"] == 1759208040000


def test_normalize_live_lead_details_wrapped():
    norm = normalize_lead_payload(LIVE_DETAIL)
    assert norm["external_id"] == "68daf338ece71b30c782353e"
    assert norm["first_name"] == "Peter"
    assert norm["last_name"] == "Vale"
    assert norm["full_name"] == "Peter Vale"
    assert norm["primary_phone"] == "+12146361338"
    assert norm["primary_email"] == "peter@example.com"
    assert norm["source_status"] == "Dead Lead"
    assert norm["assigned_user_id"] == "68d6eda2e1e2edad75b1f400"


def test_normalize_mock_shape_still_works():
    norm = normalize_lead_payload(MOCK_ITEM)
    assert norm["first_name"] == "Dana"
    assert norm["primary_phone"] == "6145550142"
    assert norm["primary_email"] == "dana.w@example.com"
    assert norm["source_status"] == "New Lead"
    assert norm["lead_source"] == "Facebook"
    assert norm["assigned_manager"] == "Sam Rivera"
    assert norm["assigned_user_id"] is None  # `{name: ...}` is a name, not an id


def test_epoch_millisecond_timestamps_parse():
    d, warnings, ambiguous = parse_date_flexible(1759208040000, "leadCreated")
    assert d == date(2025, 9, 30)
    assert warnings == [] and ambiguous is False

    dt, _w, _a = parse_datetime_flexible(1759208040000, "activityDate")
    assert dt is not None and dt.year == 2025 and dt.month == 9

    # seconds and string forms
    assert parse_date_flexible(1759208040, "x")[0] == date(2025, 9, 30)
    assert parse_date_flexible("1759208040000", "x")[0] == date(2025, 9, 30)
    # out-of-range values are rejected as epochs, not mangled into 1970
    assert parse_date_flexible(9_999_999_999_999_999, "x")[0] is None
    # 10-digit strings are treated as plain text (they look like phone numbers)
    assert parse_date_flexible("3125550142", "x")[0] is None


def test_upsert_stores_raw_payload_and_maps_stage(db):
    norm = normalize_lead_payload(LIVE_LIST_ITEM)
    lead, created = upsert_lead_from_api(db, norm, {})
    db.commit()
    assert created is True
    assert lead.raw_payload == LIVE_LIST_ITEM
    assert lead.source_status == "Dead Lead"
    assert lead.pipeline_stage == "dead"
    assert lead.lead_source == "Cold Calling"
    assert lead.phone_normalized == "18178357361"
    assert lead.original_creation_date == date(2025, 9, 30)
    assert lead.is_hot_lead is True
    # detail pass fills the contact fields on top of the list record
    detail_norm = normalize_lead_payload(LIVE_DETAIL)
    detail_norm["external_id"] = lead.external_id
    upsert_lead_from_api(db, detail_norm, {})
    db.commit()
    db.refresh(lead)
    assert lead.first_name == "Peter"
    assert lead.full_name == "Peter Vale"
    assert lead.raw_payload == LIVE_DETAIL["leadData"]


def test_normalize_live_call_activity():
    norm = normalize_activity_payload(LIVE_CALL_ACTIVITY, fallback_lead_id="x")
    assert norm["activity_type"] == "call"
    assert norm["direction"] == "outbound"
    assert norm["outcome"] == "no-answer"
    assert norm["summary"] == "You placed a call to"
    occurred, _w, _a = parse_datetime_flexible(norm["occurred_at"], "activityDate")
    assert occurred is not None and occurred.year == 2025


def test_normalize_live_note_activity_strips_html():
    norm = normalize_activity_payload(LIVE_NOTE_ACTIVITY)
    assert norm["activity_type"] == "note"
    assert norm["direction"] == "internal"
    assert norm["summary"] == "he is asking 1.15 mill will do 1.1 or 1.08"
    assert "<p>" not in (norm["detail"] or "")


def test_normalize_live_status_change_activity():
    norm = normalize_activity_payload(LIVE_STATUS_ACTIVITY)
    assert norm["activity_type"] == "status_change"
    assert norm["direction"] == "internal"
    assert norm["summary"] == "Changed lead status from New Leads to Discovery"


def test_commentless_call_log_gets_plain_label_and_scalar_outcome():
    # /callLogList rows can have no comment, and `status` may be an object
    # ({_id, name, color}) — the name is kept, the object never stringified.
    log = {
        "_id": "68db0abc1234567890abcdef",
        "direction": "outgoingCall",
        "to": "+12146361338",
        "from": "+18178357361",
        "duration": 42,
        "status": {"_id": "6aa4dc48d18014f8fc5bd7be", "name": "moved to dead lead", "color": "#ed9f00"},
        "createdAt": 1759184167694,
    }
    norm = normalize_activity_payload(log)
    assert norm["activity_type"] == "call"
    assert norm["direction"] == "outbound"
    assert norm["summary"] == "Outgoing call to +12146361338"
    assert norm["outcome"] == "moved to dead lead"
    assert "{" not in (norm["outcome"] or "")


def test_live_activities_upsert_with_types_and_outcomes(db):
    norm = normalize_lead_payload(LIVE_LIST_ITEM)
    lead, _ = upsert_lead_from_api(db, norm, {})

    call_norm = normalize_activity_payload(LIVE_CALL_ACTIVITY, fallback_lead_id=lead.external_id)
    act, created = upsert_activity_from_api(db, lead, LIVE_CALL_ACTIVITY)
    assert created is True
    assert act.activity_type == "call"
    assert act.direction == "outbound"
    assert act.outcome == "no_answer"  # inferred from "no-answer"
    assert act.occurred_at.year == 2025  # epoch ms honoured, not sync-time
    assert act.raw_payload == LIVE_CALL_ACTIVITY

    note, _ = upsert_activity_from_api(db, lead, LIVE_NOTE_ACTIVITY)
    assert note.activity_type == "note"
    assert note.direction == "internal"

    # a connected call flips the rollup to a real contact
    connected = dict(LIVE_CALL_ACTIVITY, _id="68db053343d458eb491ead0e",
                     voiceCallStatus="completed", iscallConnected=True)
    upsert_activity_from_api(db, lead, connected)
    db.commit()
    from app.services.leads import refresh_lead_rollups

    refresh_lead_rollups(db, lead)
    db.commit()
    db.refresh(lead)
    assert lead.contact_status == "connected"
    assert lead.last_contact_at is not None
    assert call_norm["lead_external_id"] == lead.external_id
