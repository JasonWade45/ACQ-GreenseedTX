"""Phase 7: briefing blocks, the optional second backup folder and restore safety."""

import sqlite3
from datetime import datetime, timedelta, timezone

from app.models import AppSetting, AuditLog, Message
from app.services import backups, briefing
from app.services.imports import create_local_lead


def _lead(db, name="Dana Seller", phone="+12025550143", county="Tarrant", **extra):
    data = {
        "full_name": name,
        "primary_phone": phone,
        "street_address": "1000 Oak Ridge Dr",
        "city": "Arlington",
        "state": "TX",
        "zip_code": "76015",
        "county": county,
        "normalized_address": f"{name.lower().replace(' ', '')}|arlington|tx|76015",
        "external_id": "ds:" + name.lower().replace(" ", ""),
        "outreach_mode": "cold",
        "source_do_not_contact": False,
        **extra,
    }
    lead = create_local_lead(db, data, data, source_kind="import")
    db.commit()
    return lead


def test_briefing_puts_a_stop_reply_first(client, db):
    from app.services import replies, templates

    templates.seed_templates(db)
    lead = _lead(db)
    booked = _lead(db, name="Booked Seller", phone="+12025550144")
    replies.handle_inbound(db, lead, "STOP")
    replies.handle_inbound(db, booked, "Yes, I'm interested")

    payload = client.get("/api/briefing").json()
    assert payload["compliance_first"][0]["classification"] == "STOP"
    assert payload["replies_needing_action"][0]["classification"] == "STOP"
    assert payload["compliance_first"][0]["label"] == "Add to suppression"
    assert payload["replies_needing_action"][1]["lead_id"] == booked.id
    assert payload["replies_needing_action"][1]["confidence"] >= 0.8
    assert payload["replies_needing_action"][1]["evidence"]
    assert payload["never_sent"] is True


def test_briefing_reports_drafts_skip_trace_stalled_and_backups(client, db):
    from app.services import templates

    templates.seed_templates(db)
    ready = _lead(db)
    ready_draft = client.post(f"/api/leads/{ready.id}/draft", json={"mode": "cold"}).json()
    _lead(db, name="Unverified Owner", phone=None, needs_skip_trace=True)

    stale = _lead(db, name="Stale Seller", phone="+12025550177")
    stale.updated_at = datetime.now(timezone.utc) - timedelta(days=40)
    db.commit()

    payload = client.get("/api/briefing").json()
    assert payload["drafts_awaiting_approval"] >= 1
    assert payload["leads_needing_skip_trace"] == 1
    assert payload["skip_trace_leads"][0]["address"] == "1000 Oak Ridge Dr"
    assert payload["stalled_leads"] >= 1
    assert payload["stalled_window_days"] == 14
    assert payload["backups"]["last_backup_at"] is None
    assert payload["backups"]["second_folder"] is None
    assert db.get(Message, ready_draft["id"]).status == "DRAFT"


def test_briefing_flags_a_draft_that_fails_validation(client, db):
    lead = _lead(db)
    db.add(
        Message(
            lead_id=lead.id,
            direction="outbound",
            body="Hi, this is Jason Wade with GreenSeedTX LLC about the foreclosure.",
            status="DRAFT",
            validator_result={"ok": False, "reasons": ["banned word: foreclosure"]},
        )
    )
    db.commit()
    payload = briefing.briefing(db)
    assert payload["drafts_failing_validation"]
    assert "banned word" in payload["drafts_failing_validation"][0]["reasons"][0]


def test_second_backup_folder_must_exist_and_be_writable(tmp_path):
    missing = tmp_path / "nope"
    try:
        backups.validate_second_folder(str(missing))
        raise AssertionError("a missing folder must be refused")
    except ValueError as error:
        assert "does not exist" in str(error)
    try:
        backups.validate_second_folder("relative/folder")
        raise AssertionError("a relative path must be refused")
    except ValueError as error:
        assert "absolute" in str(error)
    folder = tmp_path / "drive"
    folder.mkdir()
    assert backups.validate_second_folder(str(folder)) == str(folder.resolve())


def test_completed_backup_is_copied_to_the_second_folder(tmp_path):
    source = tmp_path / "data" / "acquisitions.db"
    source.parent.mkdir()
    with sqlite3.connect(source) as db:
        db.execute("CREATE TABLE t (x INTEGER)")
        db.execute("INSERT INTO t VALUES (1)")
        db.commit()
    url = "sqlite:///" + str(source)
    created = backups.create_backup(url, reason="manual")
    second = tmp_path / "drive"
    second.mkdir()
    status = backups.copy_to_second_folder(url, created, str(second))
    assert status["ok"] is True
    copied = second / created.name
    assert copied.is_file()
    with sqlite3.connect(copied) as db:
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"

    failed = backups.copy_to_second_folder(url, created, str(tmp_path / "gone"))
    assert failed["ok"] is False and "not available" in failed["detail"]
    # The app never deletes anything in the second folder.
    assert copied.is_file()


def test_manual_backup_records_the_second_folder_outcome(tmp_path, monkeypatch):
    from app import main as main_module

    source = tmp_path / "data" / "acquisitions.db"
    source.parent.mkdir()
    with sqlite3.connect(source) as db:
        db.execute("CREATE TABLE t (x INTEGER)")
        db.commit()
    url = "sqlite:///" + str(source)
    second = tmp_path / "drive"
    second.mkdir()
    created = backups.create_backup(url, reason="manual")
    status = backups.copy_to_second_folder(url, created, str(second))
    assert status["configured"] and status["ok"]
    view = main_module.backup_view(
        {
            "second_folder": status,
            "name": "x",
            "size_bytes": 1,
            "created_at": datetime.now(timezone.utc),
            "reason": "manual",
        }
    )
    assert view["second_folder"]["ok"] is True
    assert view["created_at"].endswith("+00:00")


def test_backup_settings_surface_the_mirror_status(client, db, tmp_path):
    folder = tmp_path / "drive"
    folder.mkdir()
    client.patch("/api/backups/config", json={"second_folder": str(folder)})
    row = db.get(AppSetting, "backup_second_folder")
    assert row.value["path"] == str(folder.resolve())
    listed = client.get("/api/backups").json()
    assert listed["second_folder"] == str(folder.resolve())
    assert listed["status"]["ok"] is True


def test_briefing_reports_a_failed_mirror(client, db, tmp_path):
    folder = tmp_path / "drive"
    folder.mkdir()
    db.add(
        AppSetting(
            key="backup_second_folder",
            value={"path": str(folder), "status": {"ok": False, "detail": "drive disconnected"}},
        )
    )
    db.add(AuditLog(action="backup_created", details={"file": "acquisitions-20260101T020000Z-scheduled.db"}))
    db.commit()
    payload = client.get("/api/briefing").json()
    assert payload["backups"]["second_folder_ok"] is False
    assert payload["backups"]["second_folder_detail"] == "drive disconnected"
    assert payload["backups"]["last_backup_file"].endswith("-scheduled.db")


def test_verify_backup_refuses_a_corrupt_file_so_restore_cannot_use_it(tmp_path):
    broken = tmp_path / "acquisitions-20260101T020000Z-manual.db"
    broken.write_bytes(b"not a database")
    try:
        backups.verify_backup(broken)
        raise AssertionError("a corrupt file must be refused")
    except ValueError as error:
        assert "not a usable SQLite database" in str(error)

    good = tmp_path / "good.db"
    with sqlite3.connect(good) as db:
        db.execute("CREATE TABLE t (x INTEGER)")
        db.commit()
    backups.verify_backup(good)
