"""Unified 1.2 regressions. All people/addresses/records below are synthetic."""

import hashlib
import json
import sqlite3
import pytest
from sqlalchemy import select, func
from app.models import Lead, Activity, Followup, Appointment, CallPlan
from app.schemas import MappingIn, ImportApproval
from app.services.imports import upload_batch, preview_batch, approve_batch
from app.services.normalization import normalize_record, guess_mapping
from app.services.research import prepare_plan, update_plan, plan_dict, comps_brief, fill_empty_fields
from app.services.workspace_merge import prepare_merge, commit_merge, refresh_review, _legacy_contact
from app.services.database_safety import protect_before_upgrade
from app.services.ai import context_for, analyze_lead


def legacy_database(path, leads=None):
    """Small real SQLite fixture with the source's TEXT UUID/column layout."""
    with sqlite3.connect(path) as db:
        db.executescript("""
        CREATE TABLE leads(id TEXT PRIMARY KEY,external_id TEXT,full_name TEXT,first_name TEXT,last_name TEXT,primary_phone TEXT,phone_normalized TEXT,email TEXT,email_normalized TEXT,lead_source TEXT,original_creation_date TEXT,pipeline_stage TEXT,source_status TEXT,contact_status TEXT,assigned_manager TEXT,last_contact_at TEXT,next_followup_at TEXT,do_not_contact BOOLEAN,notes TEXT,origin TEXT,raw_payload TEXT,created_at TEXT,updated_at TEXT);
        CREATE TABLE properties(id TEXT PRIMARY KEY,external_id TEXT,address_line1 TEXT,address_line2 TEXT,city TEXT,state TEXT,zip_code TEXT,address_normalized TEXT,property_type TEXT,bedrooms REAL,bathrooms REAL,square_footage REAL,year_built INTEGER,county TEXT,lot_acres REAL,asking_price REAL,estimated_value REAL,repair_estimate REAL,extra TEXT);
        CREATE TABLE lead_properties(id TEXT PRIMARY KEY,lead_id TEXT,property_id TEXT,role TEXT,is_primary BOOLEAN);
        CREATE TABLE activities(id TEXT PRIMARY KEY,lead_id TEXT,external_id TEXT,activity_type TEXT,direction TEXT,outcome TEXT,occurred_at TEXT,recorded_at TEXT,created_at TEXT,summary TEXT,detail TEXT,source TEXT,raw_payload TEXT);
        CREATE TABLE followups(id TEXT PRIMARY KEY,lead_id TEXT,due_at TEXT,priority INTEGER,reason TEXT,suggested_next_action TEXT,status TEXT,completed_at TEXT,completion_outcome TEXT,creation_source TEXT,ai_suggested BOOLEAN,created_at TEXT);
        CREATE TABLE appointments(id TEXT PRIMARY KEY,lead_id TEXT,external_id TEXT,scheduled_at TEXT,status TEXT,notes TEXT,source TEXT);
        CREATE TABLE message_drafts(id TEXT PRIMARY KEY,lead_id TEXT,body TEXT,edited_body TEXT,created_at TEXT);
        CREATE TABLE call_plans(id TEXT PRIMARY KEY,lead_id TEXT,opener TEXT,questions TEXT,created_at TEXT);
        CREATE TABLE ai_insights(id TEXT PRIMARY KEY,lead_id TEXT,summary TEXT,created_at TEXT);
        CREATE TABLE app_settings(key TEXT PRIMARY KEY,value TEXT);
        """)
        records = leads or [
            {
                "id": "uuid-one",
                "full_name": "Legacy Example",
                "primary_phone": "+12025550191",
                "external_id": "source-one",
            }
        ]
        for record in records:
            data = {
                "pipeline_stage": "qualified",
                "phone_normalized": record.get("primary_phone"),
                "origin": "import",
                "contact_status": "connected",
                "do_not_contact": False,
                "original_creation_date": "2019-05-14",
                "created_at": "2020-01-10 12:00:00",
                "updated_at": "2020-01-10 12:00:00",
                **record,
            }
            db.execute(
                "INSERT INTO leads (" + ",".join(data) + ") VALUES (" + ",".join("?" for _ in data) + ")",
                list(data.values()),
            )
        db.execute("INSERT INTO app_settings VALUES ('do_not_migrate_private_config','synthetic-settings-value')")
    return path


def insert(path, table, **values):
    with sqlite3.connect(path) as db:
        db.execute(
            "INSERT INTO " + table + " (" + ",".join(values) + ") VALUES (" + ",".join("?" for _ in values) + ")",
            list(values.values()),
        )


def decision(sid="uuid-one", action="separate", target_id=None, fill_missing=False):
    return {"source_id": sid, "action": action, "target_id": target_id, "fill_missing": fill_missing}


def commit(db, job, decisions=None):
    return commit_merge(db, job, "MERGE REVIEWED RECORDS", decisions or [decision()])


def test_preparation_persists_without_inventing_contact(db, make_lead):
    lead = make_lead(source_do_not_contact=False, contact_outcome="Callback Requested")
    lead.contact_status = "unknown"
    lead.last_contact_at = None
    db.commit()
    activity_count_before = db.scalar(select(func.count(Activity.id)))
    plan = prepare_plan(db, lead)
    assert plan.opener and not plan.internal_only
    assert prepare_plan(db, lead).id == plan.id
    update_plan(
        db, lead, plan, {"motivation": True}, {"motivation": "Internal question to verify, not a seller answer"}
    )
    assert plan.questions[0]["reviewed"] is True
    db.refresh(lead)
    assert lead.contact_status == "unknown" and lead.last_contact_at is None
    assert db.scalar(select(func.count(Activity.id))) == activity_count_before


@pytest.mark.parametrize("flags", [{"source_do_not_contact": True}, {}, {"name": "", "source_do_not_contact": False}])
def test_preparation_restrictions_and_unknown_identity(db, make_lead, flags):
    lead = make_lead(**flags)
    plan = prepare_plan(db, lead)
    assert plan.internal_only and plan.opener is None
    with pytest.raises(ValueError, match="restrictions"):
        update_plan(db, lead, plan, {}, {}, "An unsafe opener")


def test_preparation_stale_guard_and_version_preservation(db, make_lead):
    lead = make_lead(source_do_not_contact=False, contact_outcome="Callback Requested")
    plan = prepare_plan(db, lead)
    lead.primary_phone = "+12025550198"
    db.commit()
    assert plan_dict(plan, lead)["stale"] and plan_dict(plan, lead)["opener"] is None
    with pytest.raises(ValueError, match="stale"):
        update_plan(db, lead, plan, {"price": True}, {})
    with pytest.raises(ValueError, match="regenerate"):
        prepare_plan(db, lead)
    replacement = prepare_plan(db, lead, True)
    assert replacement.id != plan.id and db.scalar(select(func.count(CallPlan.id))) == 2


def test_comps_uses_only_known_subject_and_no_invented_sales(db, make_lead):
    lead = make_lead(estimated_value=250000, asking_price=275000, bedrooms=3, square_feet=1800, tax_market_value=240000)
    result = comps_brief(lead)
    assert result["comps"] == [] and result["subject"]["bedrooms"] == 3
    assert result["subject"]["street_address"] == lead.properties[0].street_address
    assert result["criteria"]["sqft_min"] == 1440 and result["criteria"]["price_min"] == 200000
    assert all(p["url"].endswith(".com/") for p in result["portals"])
    assert result["references"][0]["value"] == 275000
    assert comps_brief(lead, 99999)["subject"] is None


def test_comps_missing_value_remains_unknown(make_lead):
    lead = make_lead()
    result = comps_brief(lead)
    assert result["criteria"]["price_min"] is None and result["references"] == []


def test_compound_address_only_import_preserves_unknown_owner(db, settings):
    content = b'Property Address,Beds Baths and Sqft,MV\n"35 Fictional Lane, Austin, TX 78701",3 beds 2 baths 1800 sqft,250k Redfin\n'
    batch, _ = upload_batch(db, content, "property-only.csv", settings)
    mapping = next(iter(batch.sheets.values()))["suggested_mapping"]
    preview_batch(db, batch, MappingIn(sheets=["CSV"], mapping=mapping), settings)
    from app.models import ImportRow

    row = db.scalar(select(ImportRow))
    assert not row.errors
    assert row.normalized["full_name"] == "" and row.normalized["record_kind"] == "property_only"
    approve_batch(db, batch, ImportApproval(row_ids=[row.id], confirmation="IMPORT LOCAL"))
    lead = db.scalar(select(Lead))
    assert lead.full_name == "" and lead.properties[0].bedrooms == 3
    assert lead.properties[0].estimated_value == 250000 and lead.original_created_at is None
    assert batch.counts["imported"] == 1 and batch.counts["warnings"] == 1
    assert prepare_plan(db, lead).opener is None


@pytest.mark.parametrize(
    "value,number", [("250k", 250000), ("$1.25m", 1250000), ("200k-250k", None), ("200k to 250k", None)]
)
def test_amount_suffixes_and_ranges(value, number):
    data, errors, _ = normalize_record(
        {"Name": "Example Seller", "Email": "example@example.test", "Price": value},
        {"Name": "full_name", "Email": "email", "Price": "asking_price"},
        "America/New_York",
        "reject",
    )
    assert not errors and data["asking_price"] == number


def test_compound_conflicts_do_not_silently_win():
    _, errors, _ = normalize_record(
        {"Name": "Example", "Address": "35 Fictional Lane", "Combined": "3 & 2", "Beds": "4"},
        {"Name": "full_name", "Address": "street_address", "Combined": "bed_bath_sqft", "Beds": "bedrooms"},
        "America/New_York",
        "reject",
    )
    assert any("Conflicting" in error for error in errors)
    assert guess_mapping([" First Name ", "Beds Baths and Sqft  "]) == {
        " First Name ": "first_name",
        "Beds Baths and Sqft  ": "bed_bath_sqft",
    }


def test_reviewed_empty_field_fill_is_provenanced_not_overwrite(db, make_lead, settings):
    lead = make_lead()
    prop = lead.properties[0]
    filled = fill_empty_fields(
        db,
        lead,
        {
            "full_name": lead.full_name,
            "primary_phone": lead.primary_phone,
            "email": "new@example.test",
            "seller_motivation": "Recorded reason supplied in a reviewed import",
            "estimated_value": 120000,
            "bedrooms": 3,
            "normalized_address": prop.normalized_address,
        },
        {"batch_id": 42},
    )
    db.commit()
    assert "email" in filled and prop.bedrooms == 3 and lead.email == "new@example.test"
    assert lead.source_data["normalized"].get("seller_motivation") is None
    context = context_for(db, lead)
    assert any("local_enrichment:seller_motivation" in row["ref"] for row in context)
    insight, _, _ = analyze_lead(db, lead, settings)
    assert insight.facts["seller_motivation"]["evidence"] == [f"lead:{lead.id}:local_enrichment:seller_motivation"]
    fill_empty_fields(
        db,
        lead,
        {"estimated_value": 500000, "bedrooms": 5, "normalized_address": prop.normalized_address},
        {"batch_id": 43},
    )
    assert prop.estimated_value == 120000 and prop.bedrooms == 3
    with pytest.raises(ValueError, match="Conflicting seller"):
        fill_empty_fields(db, lead, {"full_name": "Different Person", "county": "Different"}, {})


def test_merge_backup_first_no_auto_writes_and_idempotency(db, tmp_path, make_lead):
    existing = make_lead(name="Current Example", phone="+12025550192")
    source = legacy_database(tmp_path / "source.db")
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    job = prepare_merge(db, source, tmp_path / "private")
    assert db.scalar(select(func.count(Lead.id))) == 1 and job.status == "prepared"
    assert job.plan[0]["status"] == "pending" and (tmp_path / "private" / f"{job.id}-source.db").exists()
    with pytest.raises(ValueError, match="Type MERGE"):
        commit_merge(db, job, "", [decision()])
    commit(db, job)
    assert job.status == "completed" and db.scalar(select(func.count(Lead.id))) == 2
    migrated = db.get(Lead, job.mapping["uuid-one"])
    assert migrated.contact_status == "unknown" and migrated.last_contact_at is None
    assert migrated.original_created_at.year == 2019 and migrated.stage_code == "qualified"
    assert not migrated.restriction_reviewed and migrated.restriction_status == "unknown"
    assert db.get(Lead, existing.id).full_name == "Current Example"
    assert migrated.source_data["legacy_workspaces"]["uuid-one"]["archive"]["lead"]["contact_status"] == "connected"
    assert prepare_merge(db, source, tmp_path / "private").id == job.id
    commit(db, job)
    assert db.scalar(select(func.count(Lead.id))) == 2
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before
    assert "do_not_migrate_private_config" not in migrated.source_data


def test_merge_preserves_children_and_historical_ai_without_promoting_it(db, tmp_path):
    source = legacy_database(tmp_path / "legacy.db")
    insert(
        source,
        "properties",
        id="p-one",
        address_line1="35 Fictional Lane",
        city="Austin",
        state="TX",
        zip_code="78701",
        bedrooms=3,
        bathrooms=2,
        square_footage=1800,
        estimated_value=240000,
        county="Example County",
        extra=json.dumps({"tax": {"marketValue": 235000}}),
    )
    insert(source, "lead_properties", id="r-one", lead_id="uuid-one", property_id="p-one")
    insert(
        source,
        "activities",
        id="a-one",
        lead_id="uuid-one",
        activity_type="call",
        outcome="connected",
        source="local",
        summary="User-recorded connection, synthetic",
        occurred_at="2021-02-02 16:00:00",
        created_at="2021-02-02 16:00:00",
    )
    insert(
        source,
        "followups",
        id="f-one",
        lead_id="uuid-one",
        status="completed",
        priority=4,
        due_at="2021-02-03 16:00:00",
        reason="Recorded historical task",
        completion_outcome="no_answer",
        created_at="2021-02-02 16:00:00",
    )
    insert(
        source,
        "appointments",
        id="ap-one",
        lead_id="uuid-one",
        scheduled_at="2021-02-03 16:00:00",
        status="scheduled",
        source="local",
    )
    insert(
        source,
        "message_drafts",
        id="d-one",
        lead_id="uuid-one",
        body="Historical unverified output",
        edited_body="Human-edited historical output",
    )
    insert(source, "call_plans", id="c-one", lead_id="uuid-one", opener="Historical opener")
    insert(source, "ai_insights", id="i-one", lead_id="uuid-one", summary="Historical unverified summary")
    job = prepare_merge(db, source, tmp_path / "private")
    commit(db, job)
    lead = db.get(Lead, job.mapping["uuid-one"])
    assert lead.contact_status == "contacted" and lead.last_contact_at.year == 2021
    assert lead.properties[0].property_metadata["facts"]["tax_market_value"] == 235000
    assert db.scalar(select(Followup)).status == "completed" and db.scalar(select(Appointment)).starts_at.year == 2021
    archive = lead.source_data["legacy_workspaces"]["uuid-one"]["archive"]
    assert (
        archive["drafts"][0]["edited_body"] == "Human-edited historical output"
        and archive["call_plans"][0]["opener"] == "Historical opener"
    )
    assert archive["insights"][0]["summary"] == "Historical unverified summary"
    assert db.scalar(select(CallPlan)) is None


def test_same_property_different_known_people_cannot_be_linked_without_identity(db, make_lead, tmp_path):
    current = make_lead(name="Current Person", phone="+12025550192")
    source = legacy_database(tmp_path / "source.db")
    insert(source, "properties", id="p-one", address_line1="12 Example St", city="Austin", state="TX", zip_code="78701")
    insert(source, "lead_properties", id="r-one", lead_id="uuid-one", property_id="p-one")
    # Use canonical address normalization for a true exact property candidate.
    from app.services.normalization import normalize_address

    current.properties[0].normalized_address = normalize_address(
        {"street_address": "12 Example St", "city": "Austin", "state": "TX", "zip_code": "78701"}
    )
    db.commit()
    job = prepare_merge(db, source, tmp_path / "private")
    assert job.plan[0]["kind"] == "same_property_different_seller"
    with pytest.raises(ValueError, match="Same property"):
        commit(db, job, [decision(action="link", target_id=current.id)])
    assert db.scalar(select(func.count(Lead.id))) == 1
    commit(db, job)
    assert db.scalar(select(func.count(Lead.id))) == 2


def test_link_requires_current_review_and_fills_only_when_explicit(db, make_lead, tmp_path):
    current = make_lead(name="Legacy Example", phone="+12025550191")
    source = legacy_database(
        tmp_path / "source.db",
        [
            {
                "id": "uuid-one",
                "full_name": "Legacy Example",
                "primary_phone": current.primary_phone,
                "email": "legacy@example.test",
            }
        ],
    )
    job = prepare_merge(db, source, tmp_path / "private")
    current.assigned_manager = "New assignment"
    db.commit()
    # This field is part of missing-information/context hash.
    with pytest.raises(ValueError, match="Target changed"):
        commit(db, job, [decision(action="link", target_id=current.id)])
    refresh_review(db, job)
    commit(db, job, [decision(action="link", target_id=current.id, fill_missing=False)])
    assert current.email is None and current.assigned_manager == "New assignment"
    assert db.scalar(select(func.count(Lead.id))) == 1


def test_source_snapshot_tamper_is_rejected(db, tmp_path):
    source = legacy_database(tmp_path / "source.db")
    job = prepare_merge(db, source, tmp_path / "private")
    with sqlite3.connect(job.snapshot_path) as snapshot:
        snapshot.execute("UPDATE leads SET full_name='Changed after review'")
    with pytest.raises(ValueError, match="snapshot changed"):
        commit(db, job)
    assert db.scalar(select(func.count(Lead.id))) == 0


def test_modified_source_reuses_uuid_mapping_without_duplicating_children(db, tmp_path):
    source = legacy_database(tmp_path / "source.db")
    insert(source, "followups", id="f-one", lead_id="uuid-one", status="open", priority=3, reason="Original task")
    first = prepare_merge(db, source, tmp_path / "private")
    commit(db, first)
    with sqlite3.connect(source) as src:
        src.execute("UPDATE leads SET notes='An additional source note' WHERE id='uuid-one'")
        src.execute("UPDATE followups SET reason='Updated text, same task' WHERE id='f-one'")
    second = prepare_merge(db, source, tmp_path / "private")
    assert second.id != first.id and second.plan[0]["kind"] == "previously_migrated"
    with pytest.raises(ValueError, match="already migrated"):
        commit(db, second)
    commit(db, second, [decision(action="link", target_id=first.mapping["uuid-one"])])
    assert db.scalar(select(func.count(Lead.id))) == 1 and db.scalar(select(func.count(Followup.id))) == 1


@pytest.mark.parametrize(
    "raw,expected",
    [
        ({"voiceCallStatus": "completed", "isConnected": False}, None),
        ({"outcome": "disconnected"}, "Wrong Number"),
        ({"outcome": "no-answer"}, "No Answer"),
        ({"isConnected": True}, "Connected"),
        ({"isConnected": "false"}, None),
    ],
)
def test_legacy_source_contact_is_not_guessed_from_old_inferences(raw, expected):
    outcome, stamp = _legacy_contact(
        {
            "source": "resimpli",
            "outcome": "connected",
            "occurred_at": "2026-10-25T12:00:00",
            "raw_payload": json.dumps(raw),
        }
    )
    assert outcome == expected and stamp is None


def test_incompatible_database_never_receives_our_migrations(tmp_path):
    source = legacy_database(tmp_path / "source.db")
    before = source.read_bytes()
    with pytest.raises(ValueError, match="Incompatible GitHub"):
        protect_before_upgrade("sqlite:///" + str(source))
    assert source.read_bytes() == before


def test_merge_api_restrictions_and_local_refresh_never_calls_cloud(client, make_lead, monkeypatch):
    lead = make_lead()
    assert client.get(f"/api/leads/{lead.id}/call-plan").json() is None
    plan = client.post(f"/api/leads/{lead.id}/call-plan", json={}).json()
    assert plan["communication"] is False
    response = client.patch(f"/api/call-plans/{plan['id']}", json={"checks": {"motivation": True}})
    assert response.status_code == 200
    assert client.get(f"/api/leads/{lead.id}").json()["contact_status"] == "unknown"
    import app.routes_unified as routes
    from app.config import Settings

    monkeypatch.setattr(
        routes,
        "get_settings",
        lambda: Settings(
            _env_file=None,
            app_host="0.0.0.0",
            groq_enabled=True,
            groq_api_key="synthetic-not-real",
            ollama_enabled=True,
        ),
    )
    assert client.get("/api/workspace-merges/capabilities").json()["local_selection_available"] is False
    assert (
        client.post(
            "/api/workspace-merges/prepare",
            json={"source_path": "not-a-real-source", "confirmation": "PREPARE READ ONLY SNAPSHOT"},
        ).status_code
        == 403
    )

    def forbidden(*a, **k):
        raise AssertionError("A provider must never be called by a local refresh")

    monkeypatch.setattr("app.services.ai.infer_locally", forbidden)
    assert client.post("/api/insights/refresh-local", json={"confirm": False}).status_code == 400
    result = client.post("/api/insights/refresh-local", json={"confirm": True}).json()
    assert result["cloud_requests"] == 0 and result["updated"] == 1
    assert client.post("/api/insights/refresh-local", json={"confirm": True}).json()["cached"] == 1


def test_wal_source_snapshot_and_file_target_backup_are_consistent(tmp_path):
    from sqlalchemy.orm import sessionmaker
    from app.db import Base, make_engine
    from app.seed import initialize_defaults
    from app.services.imports import create_local_lead

    source = legacy_database(tmp_path / "source.db")
    target = tmp_path / "unified.db"
    engine = make_engine("sqlite:///" + str(target))
    Base.metadata.create_all(engine)
    maker = sessionmaker(bind=engine, expire_on_commit=False)
    with sqlite3.connect(source) as live:
        live.execute("PRAGMA journal_mode=WAL")
        live.execute("UPDATE leads SET notes='Committed in WAL, not a raw main-file copy'")
        live.commit()
        with maker() as session:
            initialize_defaults(session)
            create_local_lead(
                session, {"full_name": "Existing Example", "email": "current@example.test"}, {}, source_kind="local"
            )
            session.commit()
            job = prepare_merge(session, source, tmp_path / "private")
            backup = tmp_path / "private" / f"{job.id}-target-before.db"
            assert backup.exists()
            with sqlite3.connect(backup) as copy:
                assert copy.execute("SELECT count(*) FROM leads").fetchone()[0] == 1
                assert copy.execute("SELECT count(*) FROM workspace_merges").fetchone()[0] == 0
                assert copy.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            commit(session, job)
            migrated = session.get(Lead, job.mapping["uuid-one"])
            assert (
                "Committed in WAL" in migrated.source_data["legacy_workspaces"]["uuid-one"]["archive"]["lead"]["notes"]
            )
            assert session.scalar(select(func.count(Lead.id))) == 2
    engine.dispose()


def test_future_verified_sync_reconciles_stable_migrated_event_without_duplicates(db, tmp_path, settings):
    from app.services.sync import upsert_activity
    from app.services.resimpli import load_adapter

    source = legacy_database(tmp_path / "source.db")
    insert(
        source,
        "activities",
        id="a-one",
        lead_id="uuid-one",
        external_id="real-source-event-id",
        activity_type="call",
        source="resimpli",
        outcome="no_answer",
        summary="Synthetic source call",
        occurred_at="2024-01-02 12:00:00",
        raw_payload=json.dumps({"outcome": "no-answer", "activityDate": "2024-01-02T12:00:00Z"}),
    )
    job = prepare_merge(db, source, tmp_path / "private")
    commit(db, job)
    lead = db.get(Lead, job.mapping["uuid-one"])
    record = {
        "external_id": "real-source-event-id",
        "lead_external_id": lead.external_id,
        "activity_type": "call",
        "summary": "Verified adapter event",
        "outcome": "no_answer",
        "occurred_at": "2024-01-02T12:00:00Z",
    }
    upsert_activity(db, lead, record, "call", load_adapter(settings), settings.app_timezone)
    db.commit()
    assert db.scalar(select(func.count(Activity.id)).where(Activity.activity_type == "call")) == 1
    upsert_activity(db, lead, record, "activity", load_adapter(settings), settings.app_timezone)
    db.commit()
    activities = db.scalars(select(Activity).where(Activity.activity_type == "call")).all()
    assert len(activities) == 1 and activities[0].source_metadata["legacy_record"]["id"] == "a-one"


def test_second_stale_review_cannot_duplicate_a_migrated_uuid(db, tmp_path):
    source = legacy_database(tmp_path / "source.db")
    first = prepare_merge(db, source, tmp_path / "private")
    with sqlite3.connect(source) as live:
        live.execute("UPDATE leads SET notes='Changed source, same UUID'")
    second = prepare_merge(db, source, tmp_path / "private")
    commit(db, first)
    with pytest.raises(ValueError, match="already migrated"):
        commit(db, second)
    refresh_review(db, second)
    assert second.plan[0]["kind"] == "previously_migrated"
    commit(db, second, [decision(action="link", target_id=first.mapping["uuid-one"])])
    assert db.scalar(select(func.count(Lead.id))) == 1


def test_explicit_person_link_binds_available_crm_id_without_overwriting_known_fields(db, make_lead, tmp_path):
    current = make_lead(name="Legacy Example", phone="+12025550191", lead_source="Current source")
    source = legacy_database(tmp_path / "legacy.db")
    job = prepare_merge(db, source, tmp_path / "private")
    commit(db, job, [decision(action="link", target_id=current.id)])
    assert current.external_id == "source-one" and current.lead_source == "Current source"
    assert current.source_data["legacy_crm_binding"]["approved_link"]


def test_legacy_actual_epoch_event_date_preserved_but_absent_date_is_not_filled():
    from datetime import datetime, timezone

    value = int(datetime(2024, 1, 2, 12, tzinfo=timezone.utc).timestamp() * 1000)
    outcome, stamp = _legacy_contact(
        {
            "source": "resimpli",
            "outcome": "connected",
            "raw_payload": json.dumps({"isConnected": True, "activityDate": value}),
        }
    )
    assert outcome == "Connected" and stamp.isoformat() == "2024-01-02T12:00:00+00:00"


def test_comparables_are_the_ones_the_reviewer_entered(db, make_lead):
    """Comps are arithmetic on real input, never a fabricated sold price."""
    from app.services.research import add_comp, comps_brief, remove_comp

    lead = make_lead(bedrooms=3, square_feet=2000, address="12 Example St")
    prop = lead.properties[0]

    first = add_comp(
        db,
        lead,
        prop.id,
        {
            "address": "14 Example St",
            "sold_price": 300000,
            "square_feet": 2000,
            "sold_date": "2026-08-01",
            "source": "County deed",
        },
    )
    assert first["price_per_sqft"] == 150.0
    add_comp(db, lead, prop.id, {"address": "16 Example St", "sold_price": 320000, "square_feet": 2000})

    brief = comps_brief(lead, prop.id)
    assert len(brief["comps"]) == 2
    summary = brief["comps_summary"]
    assert summary["count"] == 2
    assert summary["median_price_per_sqft"] == 155.0
    # 2000 sqft at the median rate, minus and plus five percent.
    assert summary["suggested_low"] == 294500
    assert summary["suggested_high"] == 325500

    remove_comp(db, lead, first["id"])
    remaining = comps_brief(lead, prop.id)
    assert len(remaining["comps"]) == 1
    assert remaining["comps_summary"]["count"] == 1


def test_a_comparable_without_a_price_or_address_is_refused(db, make_lead):
    import pytest as _pytest

    from app.services.research import add_comp

    lead = make_lead()
    prop = lead.properties[0]
    with _pytest.raises(ValueError, match="street address"):
        add_comp(db, lead, prop.id, {"address": "", "sold_price": 1})
    with _pytest.raises(ValueError, match="price it sold for"):
        add_comp(db, lead, prop.id, {"address": "14 Example St", "sold_price": 0})
    with _pytest.raises(ValueError, match="Living area"):
        add_comp(db, lead, prop.id, {"address": "14 Example St", "sold_price": 100, "square_feet": 5})


def test_comparables_survive_a_reload_and_stay_off_other_properties(db, make_lead):
    from app.services.research import add_comp, comps_brief

    lead = make_lead()
    prop = lead.properties[0]
    add_comp(db, lead, prop.id, {"address": "14 Example St", "sold_price": 250000, "square_feet": 1500})
    db.expire_all()
    again = db.get(type(lead), lead.id)
    assert len(comps_brief(again, prop.id)["comps"]) == 1


def test_subject_living_area_fills_only_an_empty_field(client, db, make_lead):
    """The range needs a living area; a reviewer may supply it, never overwrite the source."""
    from app.models import Property

    lead = make_lead()
    prop = lead.properties[0]
    assert prop.square_feet is None

    first = client.patch(f"/api/leads/{lead.id}/properties/{prop.id}", json={"square_feet": 2000})
    assert first.status_code == 200
    body = first.json()
    assert body["filled"] == {"square_feet": 2000}
    assert body["kept_from_source"] == {}
    db.expire_all()
    assert db.get(Property, prop.id).square_feet == 2000

    # A second attempt must not silently rewrite what is already recorded.
    second = client.patch(f"/api/leads/{lead.id}/properties/{prop.id}", json={"square_feet": 3000})
    assert second.status_code == 200
    assert second.json()["filled"] == {}
    assert second.json()["kept_from_source"] == {"square_feet": 2000}
    db.expire_all()
    assert db.get(Property, prop.id).square_feet == 2000


def test_subject_facts_reject_a_property_that_is_not_this_seller(client, db, make_lead):
    lead = make_lead()
    other = make_lead(name="Other Owner", phone="+12025550188", address="99 Elsewhere Rd")
    response = client.patch(
        f"/api/leads/{lead.id}/properties/{other.properties[0].id}", json={"square_feet": 2000}
    )
    assert response.status_code == 404
