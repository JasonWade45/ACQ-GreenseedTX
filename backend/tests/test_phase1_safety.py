"""Phase 1 safety foundations: suppression, compliance, audit, backups, secrets."""

from datetime import datetime, timezone

from app.models import AuditLog
from app.services import compliance, backups, secrets_store

# A fixed instant inside the documented contact window (Thursday 10:00 America/Chicago).
# Using the real clock made these tests pass or fail depending on when CI ran.
BUSINESS_HOURS = datetime(2026, 10, 29, 15, 0, tzinfo=timezone.utc)


def test_suppression_blocks_send(db, make_lead):
    lead = make_lead(phone="+12025550199", state="TX", county="Tarrant")
    assert not compliance.is_suppressed(db, lead.primary_phone)
    ok, reason = compliance.can_send(db, lead, BUSINESS_HOURS)
    assert ok is True and reason == "ok"

    compliance.add_suppression(db, lead.primary_phone, "manual", "test")
    assert compliance.is_suppressed(db, lead.primary_phone)
    ok, reason = compliance.can_send(db, lead, BUSINESS_HOURS)
    assert ok is False and reason == "suppressed"


def test_stop_keyword_classified_and_suppresses(db, make_lead):
    lead = make_lead(phone="+12025550198", state="TX")
    cls, candidate, _ = compliance.classify_inbound("STOP")
    assert cls == "STOP" and candidate is True
    compliance.add_suppression(db, lead.primary_phone, "stop", "inbound")
    assert compliance.is_suppressed(db, lead.primary_phone)


def test_wrong_number_and_not_interested_are_candidates():
    assert compliance.classify_inbound("This is the wrong number")[0] == "WRONG_NUMBER"
    assert compliance.classify_inbound("Please remove me")[1] is True
    assert compliance.classify_inbound("Not interested")[0] == "NOT_INTERESTED"


def test_append_opt_out_does_not_duplicate():
    body = "Hi there, are you open to selling?"
    out = compliance.append_opt_out(body, False)
    assert "Reply STOP to opt out" in out
    again = compliance.append_opt_out(out, False)
    assert again.count("Reply STOP to opt out") == 1


def test_quiet_hours_default_blocks_late_night(db):
    from app.models import Lead

    lead = Lead(full_name="T", primary_phone="+1", source_data={"state": "TX"})
    db.add(lead)
    db.commit()
    # 03:00 UTC == 22:00 previous day CT -> outside 09-20
    now = datetime(2026, 10, 29, 3, 0, tzinfo=timezone.utc)
    assert compliance.in_quiet_hours_with_settings(db, lead, now) is True
    # 15:00 UTC == 10:00 CT -> inside
    now2 = datetime(2026, 10, 29, 15, 0, tzinfo=timezone.utc)
    assert compliance.in_quiet_hours_with_settings(db, lead, now2) is False


def test_license_filter(db, make_lead):
    in_lic = make_lead(phone="+12025550197", state="TX", county="Tarrant")
    out_lic = make_lead(phone="+12025550196", state="GA", county="DeKalb")
    assert compliance.is_in_license(in_lic, ["Tarrant, TX"]) is True
    assert compliance.is_in_license(out_lic, ["Tarrant, TX"]) is False
    ok, reason = compliance.can_send(db, out_lic, BUSINESS_HOURS)
    assert ok is False and reason == "out_of_license"


def test_audit_log_written_on_suppression(db):
    before = db.query(AuditLog).count()
    compliance.add_suppression(db, "+12025550195", "manual", "test")
    # add an audit row manually to mirror the API behaviour
    db.add(AuditLog(action="suppression_added", details={"phone": "2025550195"}))
    db.commit()
    assert db.query(AuditLog).count() == before + 1


def test_secrets_store_roundtrip():
    secrets_store.set_secret("TEST_KEY_PHASE1", "secret-value-123")
    assert secrets_store.get_secret("TEST_KEY_PHASE1") == "secret-value-123"
    secrets_store.set_secret("TEST_KEY_PHASE1", None)
    assert secrets_store.get_secret("TEST_KEY_PHASE1") is None
    assert secrets_store.storage_backend() in ("keyring", "env.secrets (fallback)")


def test_backup_create_list_restore_roundtrip(tmp_path):
    import sqlite3

    db_path = tmp_path / "t.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE t (x INTEGER)")
        conn.execute("INSERT INTO t VALUES (1)")
        conn.commit()
    url = "sqlite:///" + str(db_path)
    created = backups.create_backup(url, reason="manual")
    assert created.exists()
    listed = backups.list_backups(url)
    assert any(b["name"] == created.name for b in listed)
    with sqlite3.connect(created) as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("SELECT x FROM t").fetchone()[0] == 1


def test_can_send_respects_cap(db, make_lead):
    lead = make_lead(phone="+12025550194", state="TX", county="Tarrant")
    # under cap initially
    assert compliance.under_daily_cap(db, BUSINESS_HOURS) is True
    assert compliance.under_hourly_cap(db, BUSINESS_HOURS) is True
    ok, reason = compliance.can_send(db, lead, BUSINESS_HOURS)
    assert ok is True


def test_classify_inbound_stop_keyword():
    cls, cand, _ = compliance.classify_inbound("stop")
    assert cls == "STOP" and cand is True
    cls2, cand2, _ = compliance.classify_inbound("STOPALL")
    assert cls2 == "STOP" and cand2 is True