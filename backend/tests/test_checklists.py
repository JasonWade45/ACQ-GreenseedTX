"""Checklists: two templates, a copy on every lead, and progress that a person controls."""

import pytest
from sqlalchemy import select

from app.models import ChecklistTemplate, LeadChecklistItem, Lead
from app.services import checklists


def test_the_two_default_templates_exist_with_wholesaling_work_in_them(db):
    templates = {row["key"]: row for row in checklists.template_view(db)}
    assert set(templates) == {"lead_manager", "acquisition"}
    titles = [item["title"] for item in templates["acquisition"]["items"]]
    assert any("disclosure" in title.lower() for title in titles), "wholesaling paperwork is a default item"
    assert len(templates["lead_manager"]["items"]) >= 5


def test_creating_the_templates_twice_changes_nothing(db):
    checklists.template_view(db)
    before = len(db.scalars(select(ChecklistTemplate)).all())
    checklists.ensure_templates(db)
    db.commit()
    assert len(db.scalars(select(ChecklistTemplate)).all()) == before


def test_every_lead_is_created_with_its_checklists(make_lead, db):
    lead = make_lead("Checklist Seller")
    rows = db.scalars(select(LeadChecklistItem).where(LeadChecklistItem.lead_id == lead.id)).all()
    assert {row.template_key for row in rows} == {"lead_manager", "acquisition"}
    assert all(row.source == "template" for row in rows)
    assert all(row.done is False for row in rows)


def test_applying_twice_does_not_duplicate_and_does_not_reset_work(make_lead, db):
    lead = make_lead("Checklist Seller")
    first = db.scalars(select(LeadChecklistItem).where(LeadChecklistItem.lead_id == lead.id)).all()
    checklists.set_item(db, first[0].id, True)
    checklists.apply_to_lead(db, lead)
    db.commit()
    rows = db.scalars(select(LeadChecklistItem).where(LeadChecklistItem.lead_id == lead.id)).all()
    assert len(rows) == len(first)
    assert db.get(LeadChecklistItem, first[0].id).done is True


def test_progress_counts_what_is_done(make_lead, db):
    lead = make_lead("Checklist Seller")
    rows = db.scalars(
        select(LeadChecklistItem).where(LeadChecklistItem.lead_id == lead.id, LeadChecklistItem.template_key == "lead_manager")
    ).all()
    assert checklists.progress(db, lead.id)["done"] == 0
    for row in rows[:-1]:
        checklists.set_item(db, row.id, True)
    view = checklists.progress(db, lead.id)
    manager = next(group for group in view["checklists"] if group["key"] == "lead_manager")
    assert manager["done"] == len(rows) - 1
    assert manager["percent"] == round(100 * (len(rows) - 1) / len(rows))
    assert view["complete"] is False
    checklists.set_item(db, rows[-1].id, True)
    manager = next(group for group in checklists.progress(db, lead.id)["checklists"] if group["key"] == "lead_manager")
    assert manager["complete"] is True


def test_a_template_edit_does_not_rewrite_an_existing_leads_copy(make_lead, db):
    lead = make_lead("Checklist Seller")
    before = [row.title for row in db.scalars(select(LeadChecklistItem).where(LeadChecklistItem.lead_id == lead.id)).all()]
    checklists.update_template(
        db, "lead_manager", name="Lead Manager v2", items=[{"title": "Only one item now", "detail": "rewritten"}]
    )
    after = [row.title for row in db.scalars(select(LeadChecklistItem).where(LeadChecklistItem.lead_id == lead.id)).all()]
    assert after == before, "work already done on a lead is never rewritten under it"


def test_a_new_lead_gets_the_edited_template(make_lead, db):
    checklists.update_template(db, "lead_manager", items=[{"title": "Fresh start", "detail": None}])
    lead = make_lead("Later Seller")
    rows = db.scalars(
        select(LeadChecklistItem).where(
            LeadChecklistItem.lead_id == lead.id, LeadChecklistItem.template_key == "lead_manager"
        )
    ).all()
    assert [row.title for row in rows] == ["Fresh start"]


def test_a_template_can_be_switched_off(make_lead, db):
    checklists.update_template(db, "acquisition", active=False)
    lead = make_lead("Quiet Seller")
    rows = db.scalars(select(LeadChecklistItem).where(LeadChecklistItem.lead_id == lead.id)).all()
    assert {row.template_key for row in rows} == {"lead_manager"}


def test_a_person_can_add_an_item_to_one_lead(make_lead, db):
    lead = make_lead("Checklist Seller")
    added = checklists.add_item(db, lead.id, "Call the title company", detail="Ask for the file number")
    row = db.get(LeadChecklistItem, added["id"])
    assert row.source == "manual" and row.done is False
    assert any(item["title"] == "Call the title company" for group in checklists.progress(db, lead.id)["checklists"] for item in group["items"])


def test_an_empty_item_title_is_refused(db, make_lead):
    lead = make_lead("Checklist Seller")
    with pytest.raises(ValueError):
        checklists.add_item(db, lead.id, "   ")


def test_completing_an_unknown_item_is_an_error(db):
    with pytest.raises(ValueError, match="not found"):
        checklists.set_item(db, 99999, True)


def test_the_dashboard_counts_leads_with_open_items(db, make_lead):
    counts = checklists.open_items(db)
    assert counts["leads_due"] == 0
    make_lead("Checklist Seller")
    counts = checklists.open_items(db)
    assert counts["leads_due"] == 1
    assert counts["open_items"] >= 10


def test_the_checklist_state_survives_a_reload(make_lead, db, factory):
    lead = make_lead("Checklist Seller")
    item = db.scalars(select(LeadChecklistItem).where(LeadChecklistItem.lead_id == lead.id)).all()[0]
    checklists.set_item(db, item.id, True)
    db.commit()
    db.expire_all()
    assert db.get(LeadChecklistItem, item.id).done is True
    assert db.get(Lead, lead.id) is not None
