"""Template library, selection and the hard content validator (Phase 3)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from ..models import Template, Message

OPT_OUT_LINE = "Reply STOP to opt out"
BANNED_WORDS = {
    "tax", "lien", "foreclosure", "probate", "divorce", "deceased", "death",
    "lis pendens", "equity", "score", "your data", "mortgage balance",
}
MAX_CHARS = 320

# Priority order for template selection (most specific first).
CATEGORY_PRIORITY = [
    "SENIOR_OWNER",
    "INHERITANCE_PROBATE",
    "DIVORCE",
    "CORPORATE_OR_TRUST",
    "ABSENTEE",
    "FAILED_OR_EXPIRED_LISTING",
    "TAX_LIEN_LISPENDENS",
    "OWNER_OCCUPIED",
    "GENERIC_OPENER",
]

OPT_OUT_VARIANTS = ["Reply STOP to opt out", "Reply STOP to unsubscribe"]


def template_has_optout(body: str) -> bool:
    low = (body or "").lower()
    return "stop" in low and ("opt out" in low or "unsubscribe" in low)


def validate_message(body: str, first_name_present: bool = True) -> tuple[bool, list[str]]:
    """Hard content rules. Returns (ok, list of failure reasons)."""
    reasons = []
    if not body or not body.strip():
        reasons.append("empty body")
        return False, reasons
    if len(body) > MAX_CHARS:
        reasons.append(f"over {MAX_CHARS} chars ({len(body)})")
    low = body.lower()
    for w in BANNED_WORDS:
        if w in low:
            reasons.append(f"banned word: {w}")
    if "{" in body or "}" in body:
        reasons.append("raw placeholder")
    if "None" in body or "null" in body.lower() or "undefined" in body.lower():
        reasons.append("null/undefined placeholder")
    if not first_name_present and "{first_name}" in body:
        reasons.append("first_name placeholder with no name")
    # no emojis
    if any(ord(c) > 0x1F300 for c in body):
        reasons.append("emoji present")
    # first message must not contain links
    if "http://" in low or "https://" in low or "www." in low:
        reasons.append("link in first message")
    # must identify
    if "GreenSeedTX" not in body and "GreenSeed" not in body:
        reasons.append("missing company identification")
    if "Jason Wade" not in body:
        reasons.append("missing sender name")
    return (len(reasons) == 0), reasons


def select_category(lead) -> str:
    """Pick the most specific matching template category for a lead."""
    sd = getattr(lead, "source_data", None) or {}
    norm = sd.get("normalized") if isinstance(sd.get("normalized"), dict) else (sd if isinstance(sd, dict) else {})
    flags = (norm.get("flags") if isinstance(norm.get("flags"), dict) else {}) or {}
    lead_type = (getattr(lead, "lead_type", None) or "").lower()
    senior = bool(flags.get("senior_owner"))
    inheritance = "inheritance" in lead_type or "probate" in lead_type
    divorce = "divorce" in lead_type
    corporate = "corporate" in lead_type or bool(flags.get("corporate_owned")) or bool(flags.get("trust_owned"))
    absentee = bool(flags.get("absentee_in_state")) or bool(flags.get("absentee_out_of_state"))
    listing = bool(flags.get("failed_listing")) or bool(flags.get("expired_listing"))
    taxlien = "tax" in lead_type or "lien" in lead_type or bool(flags.get("involuntary_lien"))
    owner_occ = bool(flags.get("owner_occupied")) or lead_type == "owner occupied"
    if senior:
        return "SENIOR_OWNER"
    if inheritance:
        return "INHERITANCE_PROBATE"
    if divorce:
        return "DIVORCE"
    if corporate or absentee:
        return "CORPORATE_OR_TRUST" if corporate else "ABSENTEE_OR_CORPORATE_OR_TRUST"
    if listing:
        return "FAILED_OR_EXPIRED_LISTING"
    if taxlien:
        return "TAX_LIEN_LISPENDENS"
    if owner_occ:
        return "OWNER_OCCUPIED"
    return "GENERIC_OPENER"


def render_template(body: str, lead, sender_name: str = "Jason Wade", company: str = "GreenSeedTX LLC") -> str:
    first = (getattr(lead, "first_name", None) or "").strip()
    if not first and getattr(lead, "full_name", None):
        first = (lead.full_name or "").split()[0] if lead.full_name.split() else ""
    address = ""
    try:
        if lead.properties:
            address = lead.properties[0].street_address or ""
    except Exception:
        pass
    city = ""
    try:
        if lead.properties:
            city = lead.properties[0].city or ""
    except Exception:
        pass
    greeting = first if first else "Hello"
    out = body.replace("{first_name}", greeting)
    out = out.replace("{address}", address or "your property")
    out = out.replace("{city}", city or "")
    out = out.replace("{sender_name}", sender_name)
    out = out.replace("{company}", company)
    out = out.replace("{opt_out}", OPT_OUT_LINE)
    return out


def seed_templates(db: Session) -> int:
    """Seed the default template library if empty. Returns count created."""
    if db.query(Template).count() > 0:
        return 0
    seeds = [
        ("GENERIC_OPENER", "A", "Hi {first_name}, this is Jason Wade with GreenSeedTX LLC. I'm reaching out about the property at {address}. Have you ever thought about selling it? We buy as-is, with no repairs or agent fees. {opt_out}"),
        ("GENERIC_OPENER", "B", "Hello {first_name}, Jason Wade here with GreenSeedTX LLC. I work with homeowners in the area and wanted to ask if you've considered selling {address}. We purchase as-is and can close on your timeline. {opt_out}"),
        ("INHERITANCE_PROBATE", "A", "Hi {first_name}, this is Jason Wade with GreenSeedTX LLC. I know this may be a lot to manage, and I wanted to share that we can help with the property at {address} whenever you're ready, with no pressure and flexible timing. {opt_out}"),
        ("INHERITANCE_PROBATE", "B", "Hello {first_name}, Jason Wade with GreenSeedTX LLC. If you're exploring options for {address}, I'm happy to talk through a simple as-is sale with no repairs needed and a timeline that works for you. {opt_out}"),
        ("TAX_LIEN_LISPENDENS", "A", "Hi {first_name}, this is Jason Wade with GreenSeedTX LLC. I'm reaching out about {address}. We buy properties as-is and can close quickly and simply if that would help. {opt_out}"),
        ("TAX_LIEN_LISPENDENS", "B", "Hello {first_name}, Jason Wade with GreenSeedTX LLC. We purchase homes as-is with a straightforward process. If selling {address} is something you'd consider, I'd be glad to discuss. {opt_out}"),
        ("DIVORCE", "A", "Hi {first_name}, this is Jason Wade with GreenSeedTX LLC. If you're navigating a transition and need flexibility on timing for {address}, we buy as-is and can work around your schedule. {opt_out}"),
        ("DIVORCE", "B", "Hello {first_name}, Jason Wade with GreenSeedTX LLC. We can offer a simple, as-is purchase of {address} with flexible closing dates if that would help right now. {opt_out}"),
        ("CORPORATE_OR_TRUST", "A", "Hi {first_name}, this is Jason Wade with GreenSeedTX LLC. I'm reaching out regarding {address}. We buy as-is with flexible closing and no showings required. {opt_out}"),
        ("CORPORATE_OR_TRUST", "B", "Hello {first_name}, Jason Wade with GreenSeedTX LLC. We purchase properties as-is and can close on a timeline that suits your needs for {address}. {opt_out}"),
        ("ABSENTEE_OR_CORPORATE_OR_TRUST", "A", "Hi {first_name}, this is Jason Wade with GreenSeedTX LLC. I'm reaching out regarding {address}. We buy as-is with flexible closing and no showings required. {opt_out}"),
        ("ABSENTEE_OR_CORPORATE_OR_TRUST", "B", "Hello {first_name}, Jason Wade with GreenSeedTX LLC. We purchase properties as-is and can close on a timeline that suits your needs for {address}. {opt_out}"),
        ("SENIOR_OWNER", "A", "Hi {first_name}, this is Jason Wade with GreenSeedTX LLC. I'm reaching out about {address}. If a simple, as-is sale with no repairs or showings would be helpful, I'd be glad to talk. {opt_out}"),
        ("SENIOR_OWNER", "B", "Hello {first_name}, Jason Wade with GreenSeedTX LLC. We buy homes as-is and can make the process easy. If you'd like, I can call you to discuss {address}. {opt_out}"),
        ("OWNER_OCCUPIED", "A", "Hi {first_name}, this is Jason Wade with GreenSeedTX LLC. I'm reaching out about {address}. We buy as-is and can offer flexible move-out timing that works for you. {opt_out}"),
        ("OWNER_OCCUPIED", "B", "Hello {first_name}, Jason Wade with GreenSeedTX LLC. If selling {address} is something you'd consider, we purchase as-is with flexible closing and move-out dates. {opt_out}"),
        ("FAILED_OR_EXPIRED_LISTING", "A", "Hi {first_name}, this is Jason Wade with GreenSeedTX LLC. I noticed {address} may not have been the right fit on the market. We buy as-is with no repairs and a straightforward process if that helps. {opt_out}"),
        ("FAILED_OR_EXPIRED_LISTING", "B", "Hello {first_name}, Jason Wade with GreenSeedTX LLC. We offer a no-hassle, as-is alternative for {address} if the listing route didn't work out. {opt_out}"),
        ("FOLLOWUP_D3", "A", "Hi {first_name}, just following up on my note about {address}. Still open to a quick chat about your options? {opt_out}"),
        ("FOLLOWUP_D7", "A", "Hi {first_name}, checking in on {address}. Happy to answer any questions or share what we could offer. {opt_out}"),
        ("FOLLOWUP_D14", "A", "Hi {first_name}, reaching out once more about {address}. If now isn't a good time, no worries at all. {opt_out}"),
        ("CHECKIN_D30", "A", "Hi {first_name}, just a friendly check-in on {address}. Let me know if anything has changed. {opt_out}"),
        ("MONTHLY_TOUCH", "A", "Hi {first_name}, Jason Wade with GreenSeedTX LLC checking in on {address}. Still here if you'd like to explore options. {opt_out}"),
    ]
    n = 0
    for cat, var, body in seeds:
        t = Template(category=cat, variant=var, body=body, active=True, stats={"sent": 0, "replies": 0, "positive": 0})
        db.add(t)
        n += 1
    db.commit()
    return n


def personalize(db: Session, lead, template: Template, use_ai: bool = False) -> tuple[str, str]:
    """Render (and optionally AI-rewrite) a template. Returns (body, reason)."""
    base = render_template(template.body, lead)
    if not use_ai:
        ok, reasons = validate_message(base, bool(getattr(lead, "first_name", None) or getattr(lead, "full_name", None)))
        if not ok:
            return base, "validator_failed:" + ",".join(reasons)
        return base, "template_rendered"
    # AI rewrite placeholder: callers pass use_ai=True and provide an ai function.
    # Here we just validate the base; actual AI rewrite is wired in routes.
    ok, reasons = validate_message(base, bool(getattr(lead, "first_name", None) or getattr(lead, "full_name", None)))
    if not ok:
        return base, "validator_failed:" + ",".join(reasons)
    return base, "template_rendered"


def create_draft(db: Session, lead, template_id: int | None = None, variant: str = "A", body: str | None = None) -> Message:
    if template_id is None:
        cat = select_category(lead)
        tmpl = db.query(Template).filter(Template.category == cat, Template.active.is_(True)).first()
        template_id = tmpl.id if tmpl else None
        if tmpl and body is None:
            body = render_template(tmpl.body, lead)
    if body is None:
        body = ""
    tmpl = db.get(Template, template_id) if template_id else None
    final_body = body
    # enforce opt-out line
    if not template_has_optout(final_body):
        final_body = final_body.rstrip() + "\n" + OPT_OUT_LINE
    ok, reasons = validate_message(final_body, bool(getattr(lead, "first_name", None) or getattr(lead, "full_name", None)))
    m = Message(
        lead_id=lead.id,
        direction="outbound",
        body=final_body,
        template_id=template_id,
        variant=variant,
        status="DRAFT",
        validator_result={"ok": ok, "reasons": reasons},
    )
    db.add(m)
    db.commit()
    db.refresh(m)
    return m


def approve_message(db: Session, message_id: int) -> Message:
    m = db.get(Message, message_id)
    if m is None:
        raise ValueError("Message not found")
    if m.status != "DRAFT":
        raise ValueError("Only drafts can be approved")
    ok, reasons = validate_message(m.body, True)
    if not ok:
        raise ValueError("Message failed validation: " + ", ".join(reasons))
    m.status = "APPROVED"
    db.commit()
    db.refresh(m)
    return m