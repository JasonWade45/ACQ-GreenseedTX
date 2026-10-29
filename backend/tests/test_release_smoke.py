"""Release 1.5.0 smoke test: the whole reviewed loop through the public API.

One test per promise in the release notes, driven only through HTTP routes so the
interface cannot pass while the API behind it is broken.
"""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from app.models import Lead, Message, SuggestedAction
from app.services import templates
from app.version import APP_VERSION

SAMPLE = Path(__file__).resolve().parents[2] / "examples" / "sample-data-syndicate.csv"
BUSINESS_HOURS = datetime(2026, 10, 29, 15, 0, tzinfo=timezone.utc)


def _import_sample(client, db):
    # Startup seeds the reviewed template library; the test session does not.
    assert client.post("/api/templates/seed").status_code == 200
    with SAMPLE.open("rb") as handle:
        batch = client.post(
            "/api/imports/upload?profile=address_only",
            files={"file": ("sample.csv", handle, "text/csv")},
        ).json()
    mapping = batch["sheets"]["CSV"]["suggested_mapping"]
    assert client.post(
        f"/api/imports/{batch['id']}/preview",
        json={"sheets": ["CSV"], "mapping": mapping, "date_order": "MDY"},
    ).status_code == 200
    eligible = client.get(f"/api/imports/{batch['id']}/eligible-ids").json()
    approved = client.post(
        f"/api/imports/{batch['id']}/approve",
        json={
            "row_ids": eligible["row_ids"],
            "resolutions": {},
            "confirmation": "IMPORT LOCAL",
            "fill_missing": False,
        },
    )
    assert approved.status_code == 200, approved.text
    return approved.json()


def test_release_version_is_one_number_everywhere():
    import json

    package = json.loads((Path(__file__).resolve().parents[2] / "frontend" / "package.json").read_text())
    assert package["version"] == APP_VERSION
    assert APP_VERSION.count(".") == 2


def test_full_loop_from_address_list_to_confirmed_opt_out(client, db):
    imported = _import_sample(client, db)
    assert imported["counts"]["imported"] == 58

    # Every imported lead is address-only, cold, and blocked from drafting.
    lead = db.query(Lead).filter(Lead.score == 92.4).one()
    assert lead.needs_skip_trace is True
    assert lead.outreach_mode == "cold"
    blocked = client.post(f"/api/leads/{lead.id}/draft", json={"regenerate": True})
    assert blocked.status_code == 400
    assert "skip trace" in blocked.json()["detail"].lower()

    # The skip-trace loop gives the lead a contact.
    results = f"lead_key,owner_name,phone1\n{lead.external_id},Dana Seller,202-555-0143\n"
    batch = client.post(
        "/api/skip-trace/upload", files={"file": ("r.csv", results.encode(), "text/csv")}
    ).json()
    applied = client.post(
        f"/api/skip-trace/{batch['batch_id']}/apply", json={"confirmation": "IMPORT LOCAL"}
    )
    assert applied.status_code == 200, applied.text
    db.expire_all()
    lead = db.get(Lead, lead.id)
    assert lead.needs_skip_trace is False and lead.primary_phone == "+12025550143"

    # The contact-restriction review is still required before any draft.
    review = client.post(
        f"/api/leads/{lead.id}/restriction",
        json={
            "restricted": False,
            "evidence": "Imported vendor list carries no opt-out; reviewed locally before contact",
            "confirm": True,
        },
    )
    assert review.status_code == 200, review.text

    # A cold draft now exists, passes the validator, and is copy-only.
    draft = client.post(f"/api/leads/{lead.id}/draft", json={"regenerate": True})
    assert draft.status_code == 200, draft.text
    body = draft.json()
    assert body["kind"] == "cold"
    assert body["validator_result"]["ok"] is True
    assert "Reply STOP to opt out" in body["body"]
    assert "GreenSeedTX LLC" in body["body"]
    assert body["why_this_template"]
    assert "sent" not in str(body.get("status", "")).lower() or body["status"] == "DRAFT"

    queue = client.get("/api/drafts").json()
    assert queue["total"] >= 1
    item = next(row for row in queue["items"] if row["lead_id"] == lead.id)
    # Editing runs the same validator; a URL is refused.
    bad = client.patch(f"/api/messages/{item['id']}", json={"body": "Visit https://spam.example now"})
    assert bad.status_code == 400
    good = client.patch(
        f"/api/messages/{item['id']}",
        json={"body": item["body"].replace(". ", "! ")},
    )
    assert good.status_code == 200, good.text
    assert client.post(f"/api/messages/{item['id']}/approve").json()["status"] == "APPROVED"

    # Bulk generation never copies or sends.
    bulk = client.post("/api/drafts/bulk", json={"tier": None, "lead_ids": [lead.id], "confirm": True})
    assert bulk.status_code == 200, bulk.text
    assert bulk.json()["bulk_copy"] is False and bulk.json()["bulk_send"] is False

    # A literal STOP lands in the compliance block first.
    reply = client.post(f"/api/leads/{lead.id}/reply", json={"text": "STOP"})
    assert reply.status_code == 200
    assert reply.json()["classification"] == "STOP"
    briefing = client.get("/api/briefing").json()
    assert briefing["compliance_first"][0]["classification"] == "STOP"
    assert briefing["never_sent"] is True

    # Suppression is a suggestion until confirmed here.
    action = (
        db.query(SuggestedAction)
        .filter(SuggestedAction.lead_id == lead.id, SuggestedAction.status == "pending")
        .order_by(SuggestedAction.id.desc())
        .first()
    )
    assert client.post(f"/api/suggested-actions/{action.id}/confirm").status_code == 200
    db.expire_all()
    assert db.get(Lead, lead.id).do_not_contact is True


def test_no_endpoint_can_send_or_bulk_copy(client, db):
    from app.main import app

    paths = {
        route.path
        for route in app.routes
        if getattr(route, "path", "").startswith("/api/")
    }
    assert not any(path.endswith(("/send", "/sms", "/email", "/call")) for path in paths)
    assert not [path for path in paths if "bulk-copy" in path or "bulk-send" in path]
    # And the schema itself has no way to express "sent".
    assert {column.name for column in Message.__table__.columns}.isdisjoint({"sent_at", "sent", "delivered_at"})


def test_templates_render_without_vendor_language():
    sample = type(
        "Lead",
        (),
        {"first_name": "Dana", "full_name": "Dana Seller", "properties": []},
    )()
    for category, variants in templates.DEFAULT_TEMPLATES.items():
        for body in variants.values():
            rendered = templates.render_template(body, sample, "Jason Wade", "GreenSeedTX LLC")
            ok, reasons = templates.validate_message(
                rendered, True, sender_name="Jason Wade", company="GreenSeedTX LLC"
            )
            assert ok, (category, reasons)
            for banned in ("equity", "distress", "tax lien", "probate", "score"):
                assert banned not in rendered.lower(), (category, banned)


def test_backups_support_a_verified_second_folder(client, db, tmp_path, monkeypatch):
    # A backup copies a real database file, so point the app at a scratch one instead
    # of any developer database that happens to exist in this checkout.
    import os

    from app.config import get_settings

    scratch = tmp_path / "acquisitions.db"
    with sqlite3.connect(scratch) as connection:
        connection.execute("CREATE TABLE leads (id INTEGER PRIMARY KEY, full_name TEXT)")
        connection.execute("INSERT INTO leads (full_name) VALUES ('Keep Me')")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{scratch}")
    get_settings.cache_clear()
    try:
        _assert_second_folder_backup(client, tmp_path)
    finally:
        os.environ.pop("DATABASE_URL", None)
        get_settings.cache_clear()


def _assert_second_folder_backup(client, tmp_path):
    folder = tmp_path / "second-drive"
    folder.mkdir()
    assert client.patch("/api/backups/config", json={"second_folder": str(folder)}).status_code == 200
    created = client.post("/api/backups")
    assert created.status_code == 200, created.text
    mirror = created.json()["second_folder"]
    assert mirror["ok"] is True, mirror
    assert mirror["folder"] == str(folder.resolve())
    assert (folder.resolve() / created.json()["name"]).exists()
    overview = client.get("/api/backups").json()
    assert overview["second_folder"] == str(folder.resolve())
    assert overview["status"]["ok"] is True
    # A folder that does not exist is refused instead of silently ignored.
    assert client.patch(
        "/api/backups/config", json={"second_folder": str(tmp_path / "missing")}
    ).status_code == 400
