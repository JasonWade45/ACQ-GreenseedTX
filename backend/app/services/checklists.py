"""Two editable checklists that every lead gets, and the progress on them.

A checklist is a template plus a copy: the template is the definition a person maintains
in Settings, and the copy is what sits on a lead. Editing a template never rewrites the
checklist of a lead that already exists -- the work someone did in January should not
change because a line was reworded in March.

The defaults are the two things this business actually does: manage the lead (address,
restriction review, contact, motivation, follow-up) and acquire the property (comps,
repairs, offer, exit, closing, wholesale paperwork). They are starting points, not
policy: every item can be renamed, reordered, removed or added, and a template can be
switched off.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import utcnow
from ..models import ChecklistTemplate, ChecklistTemplateItem, Lead, LeadChecklistItem

LEAD_MANAGER = "lead_manager"
ACQUISITION = "acquisition"
CACHE_KEY = "checklist_templates_cache"

DEFAULT_TEMPLATES = [
    {
        "key": LEAD_MANAGER,
        "name": "Lead Manager",
        "description": "Everything that must be true before this lead is worked.",
        "items": [
            ("Confirm the property address and county", "Street, city, state and ZIP must be right before anything else."),
            ("Review contact restrictions", "Record do-not-contact, licensing and suppression status with the evidence."),
            ("Verify an owner name and a working phone", "Skip trace if either is missing; never invent a name."),
            ("Record the seller's motivation and timeline", "Ask, do not assume. Leave it blank if the seller did not say."),
            ("Log the last contact outcome", "Connected, no answer, callback or voicemail, with the date."),
            ("Set the next follow-up date", "One clear next action beats a list of maybes."),
        ],
    },
    {
        "key": ACQUISITION,
        "name": "Acquisition",
        "description": "The path from a qualified lead to a signed contract.",
        "items": [
            ("Pull comparable sales for the county", "Recent, same property type, and note the source."),
            ("Estimate repairs and confirm condition", "Walk the property or use a documented estimate; label it as an estimate."),
            ("Calculate the maximum offer", "Comps minus repairs minus the target margin; show the arithmetic."),
            ("Choose the exit strategy", "Cash, subject-to, seller finance or novation, with the reason written down."),
            ("Confirm the title company and closing timeline", "Who closes, and what the realistic date is."),
            ("Prepare the wholesale disclosure and assignment paperwork", "Disclose in writing that you are the buyer, not the agent, and that you may assign."),
        ],
    },
]


def ensure_templates(db: Session):
    """Create the two templates once. An existing template is never overwritten."""
    existing = {row.key for row in db.scalars(select(ChecklistTemplate)).all()}
    created = 0
    for template in DEFAULT_TEMPLATES:
        if template["key"] in existing:
            continue
        row = ChecklistTemplate(
            key=template["key"], name=template["name"], description=template["description"], active=True
        )
        db.add(row)
        db.flush()
        for position, (title, detail) in enumerate(template["items"]):
            db.add(
                ChecklistTemplateItem(
                    template_id=row.id, position=position, title=title, detail=detail, default_done=False
                )
            )
        created += 1
    db.flush()
    return created


def active_templates(db: Session):
    """The templates and their items, cached per session so an import is not N+1."""
    cached = db.info.get(CACHE_KEY)
    if cached is not None:
        return cached
    ensure_templates(db)
    result = []
    for template in db.scalars(select(ChecklistTemplate).where(ChecklistTemplate.active.is_(True))).all():
        items = db.scalars(
            select(ChecklistTemplateItem)
            .where(ChecklistTemplateItem.template_id == template.id)
            .order_by(ChecklistTemplateItem.position)
        ).all()
        result.append((template, list(items)))
    db.info[CACHE_KEY] = result
    return result


def apply_to_lead(db: Session, lead):
    """Give a lead the current copy of every active checklist, once.

    Called for every lead created anywhere -- import, sync or workspace merge -- so a
    lead never exists without its checklists. A second call is a no-op; the copy that is
    already there is left exactly as a person left it.
    """
    if lead.id is None:
        db.flush()
    existing = {
        row.template_key
        for row in db.scalars(select(LeadChecklistItem).where(LeadChecklistItem.lead_id == lead.id)).all()
    }
    added = 0
    for template, items in active_templates(db):
        if template.key in existing:
            continue
        for position, item in enumerate(items):
            db.add(
                LeadChecklistItem(
                    lead_id=lead.id,
                    template_key=template.key,
                    template_item_id=item.id,
                    position=position,
                    title=item.title,
                    detail=item.detail,
                    done=item.default_done,
                    done_at=utcnow() if item.default_done else None,
                    source="template",
                )
            )
            added += 1
    db.flush()
    return added


def progress(db: Session, lead_id):
    """Progress per template, plus the overall picture the profile card and dashboard use."""
    rows = db.scalars(
        select(LeadChecklistItem)
        .where(LeadChecklistItem.lead_id == lead_id)
        .order_by(LeadChecklistItem.position, LeadChecklistItem.id)
    ).all()
    names = {template.key: template.name for template in db.scalars(select(ChecklistTemplate)).all()}
    groups = {}
    for row in rows:
        group = groups.setdefault(
            row.template_key, {"key": row.template_key, "name": names.get(row.template_key, row.template_key), "items": []}
        )
        group["items"].append(
            {
                "id": row.id,
                "title": row.title,
                "detail": row.detail,
                "done": row.done,
                "done_at": row.done_at,
                "source": row.source,
            }
        )
    result = []
    for group in groups.values():
        total = len(group["items"])
        done = sum(1 for item in group["items"] if item["done"])
        result.append(
            {
                **group,
                "done": done,
                "total": total,
                "percent": round(100 * done / total) if total else 0,
                "complete": bool(total) and done == total,
            }
        )
    total = sum(group["total"] for group in result)
    done = sum(group["done"] for group in result)
    return {
        "checklists": sorted(result, key=lambda group: group["key"] != LEAD_MANAGER),
        "done": done,
        "total": total,
        "percent": round(100 * done / total) if total else 0,
        "complete": bool(total) and done == total,
    }


def set_item(db: Session, item_id, done: bool):
    row = db.get(LeadChecklistItem, item_id)
    if row is None:
        raise ValueError("Checklist item not found")
    row.done = bool(done)
    row.done_at = utcnow() if done else None
    db.commit()
    return {"id": row.id, "done": row.done, "done_at": row.done_at, "lead_id": row.lead_id}


def add_item(db: Session, lead_id, title, detail=None, template_key=LEAD_MANAGER):
    text = (title or "").strip()
    if not text or len(text) > 200:
        raise ValueError("A checklist item needs a title of at most 200 characters")
    lead = db.get(Lead, lead_id)
    if lead is None:
        raise ValueError("Lead not found")
    position = max(
        [row.position for row in db.scalars(select(LeadChecklistItem).where(LeadChecklistItem.lead_id == lead_id)).all()]
        or [0]
    )
    row = LeadChecklistItem(
        lead_id=lead_id,
        template_key=template_key,
        position=position + 1,
        title=text,
        detail=detail,
        source="manual",
    )
    db.add(row)
    db.commit()
    return {"id": row.id, "title": row.title, "detail": row.detail, "done": row.done}


def template_view(db: Session):
    """The editable definitions behind the lead checklists."""
    ensure_templates(db)
    db.commit()
    return [
        {
            "id": template.id,
            "key": template.key,
            "name": template.name,
            "description": template.description,
            "active": template.active,
            "items": [
                {"id": item.id, "position": item.position, "title": item.title, "detail": item.detail}
                for item in db.scalars(
                    select(ChecklistTemplateItem)
                    .where(ChecklistTemplateItem.template_id == template.id)
                    .order_by(ChecklistTemplateItem.position)
                ).all()
            ],
        }
        for template in db.scalars(select(ChecklistTemplate).order_by(ChecklistTemplate.id)).all()
    ]


def update_template(db: Session, key, *, name=None, description=None, active=None, items=None):
    """Edit the definition. Leads that already have their copy are untouched."""
    template = db.scalar(select(ChecklistTemplate).where(ChecklistTemplate.key == key))
    if template is None:
        raise ValueError("Checklist template not found")
    if name is not None:
        text = str(name).strip()
        if not text or len(text) > 120:
            raise ValueError("A template name must be 1-120 characters")
        template.name = text
    if description is not None:
        template.description = str(description)[:2000]
    if active is not None:
        template.active = bool(active)
    if items is not None:
        for item in db.scalars(
            select(ChecklistTemplateItem).where(ChecklistTemplateItem.template_id == template.id)
        ).all():
            db.delete(item)
        db.flush()
        for position, item in enumerate(items):
            title = str(item.get("title") or "").strip()
            if not title or len(title) > 200:
                raise ValueError("Every item needs a title of at most 200 characters")
            db.add(
                ChecklistTemplateItem(
                    template_id=template.id,
                    position=position,
                    title=title,
                    detail=(str(item.get("detail"))[:2000] if item.get("detail") else None),
                )
            )
    db.info.pop(CACHE_KEY, None)
    db.commit()
    return template_view(db)


def open_items(db: Session):
    """What the dashboard needs: how many leads still have checklist work."""
    rows = db.scalars(select(LeadChecklistItem).where(LeadChecklistItem.done.is_(False))).all()
    return {"open_items": len(rows), "leads_due": len({row.lead_id for row in rows})}
