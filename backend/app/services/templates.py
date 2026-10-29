"""Template library, template selection and the hard content validator.

Two drafting modes share this module:

* ``relationship`` drafts live in ``services/ai.py`` and are unchanged.
* ``cold`` drafts (Data Syndicate leads with no documented relationship) are rendered
  here from the template library. Every cold draft, whether the raw template or an
  AI rewrite, must pass :func:`validate_message` before Jason can copy it.

Nothing in this module sends anything. A "draft" is text he copies himself.
"""

from __future__ import annotations

import re

from sqlalchemy.orm import Session

from ..models import AuditLog, Lead, Message, Template

OPT_OUT_LINE = "Reply STOP to opt out"
MAX_CHARS = 320

# Distress signals are internal context only. None of these may reach a seller.
BANNED_PATTERNS = [
    r"\btax(?:es|ation|ed)?\b",
    r"\blien\b",
    r"\bforeclos(?:ure|ed|ing)\b",
    r"\bforeclose\b",
    r"\bprobate\b",
    r"\binherit(?:ance|ed|ing)?\b",
    r"\bdeceased\b",
    r"\bpassed away\b",
    r"\bdivorce(?:d|ing)?\b",
    r"\blis pendens\b",
    r"\bauction\b",
    r"\bdelinquent\b",
    r"\bequity\b",
    r"\bscore\b",
    r"\byour data\b",
    r"\bmortgage balance\b",
]
URGENCY_PATTERNS = [r"\burgent\b", r"\blast chance\b", r"\bact now\b", r"\bimmediately\b"]
URL_PATTERN = re.compile(r"(https?://|www\.)", re.IGNORECASE)
MONEY_PATTERN = re.compile(r"\$\s?\d")
EMOJI_PATTERN = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF\u2b00-\u2bff\ufe0f]"
)
PLACEHOLDER_TOKENS = ("{", "}", "[", "]")
NULL_TOKENS = re.compile(r"\b(none|null|undefined|nan)\b", re.IGNORECASE)

# Most specific first. The first matching category wins.
CATEGORY_PRIORITY = [
    "SENIOR_OWNER",
    "INHERITANCE_PROBATE",
    "DIVORCE",
    "ABSENTEE_CORPORATE_TRUST",
    "FAILED_OR_EXPIRED_LISTING",
    "TAX_LIEN_LISPENDENS_HOA",
    "OWNER_OCCUPIED",
    "GENERIC_OPENER",
]

FOLLOWUP_CATEGORIES = ["FOLLOWUP_D3", "FOLLOWUP_D7", "FOLLOWUP_D14", "CHECKIN_D30", "MONTHLY_TOUCH"]

# Legacy names used by an earlier build. They stay readable so an existing database
# keeps working; new seeding always uses the canonical names above.
LEGACY_CATEGORY_ALIASES = {
    "TAX_LIEN_LISPENDENS": "TAX_LIEN_LISPENDENS_HOA",
    "CORPORATE_OR_TRUST": "ABSENTEE_CORPORATE_TRUST",
    "ABSENTEE_OR_CORPORATE_OR_TRUST": "ABSENTEE_CORPORATE_TRUST",
}

DEFAULT_TEMPLATES: dict[str, dict[str, str]] = {
    "GENERIC_OPENER": {
        "A": (
            "Hi {first_name}, this is {sender_name} with {company}. I'm reaching out about the property at "
            "{address}. Have you ever thought about selling it? We buy as-is, with no repairs or agent fees. "
            "{opt_out}"
        ),
        "B": (
            "Hello {first_name}, {sender_name} here with {company}. I work with owners in the area and wanted to "
            "ask if you've considered selling {address}. We buy as-is and can close on your timeline. {opt_out}"
        ),
    },
    "INHERITANCE_PROBATE": {
        "A": (
            "Hi {first_name}, this is {sender_name} with {company}. I know this may be a lot to manage, and I "
            "wanted to share that we can help with the property at {address} whenever you're ready, with no "
            "pressure and flexible timing. {opt_out}"
        ),
        "B": (
            "Hello {first_name}, {sender_name} with {company}. If you're exploring options for {address}, I'm "
            "happy to talk through a simple as-is sale with no repairs needed and a timeline that works for you. "
            "{opt_out}"
        ),
    },
    "TAX_LIEN_LISPENDENS_HOA": {
        "A": (
            "Hi {first_name}, this is {sender_name} with {company}. I'm reaching out about {address}. We buy "
            "properties as-is and can keep the process simple and fast if that would help. {opt_out}"
        ),
        "B": (
            "Hello {first_name}, {sender_name} with {company}. We purchase homes as-is with a straightforward "
            "process. If selling {address} is something you'd consider, I'd be glad to discuss it. {opt_out}"
        ),
    },
    "DIVORCE": {
        "A": (
            "Hi {first_name}, this is {sender_name} with {company}. If you need flexibility on timing for "
            "{address}, we buy as-is and can work around your schedule, discreetly and without pressure. "
            "{opt_out}"
        ),
        "B": (
            "Hello {first_name}, {sender_name} with {company}. We can offer a simple, as-is purchase of {address} "
            "with flexible closing dates if that would make things easier right now. {opt_out}"
        ),
    },
    "ABSENTEE_CORPORATE_TRUST": {
        "A": (
            "Hi {first_name}, this is {sender_name} with {company}. I'm reaching out regarding {address}. We buy "
            "as-is with flexible closing and no showings required. {opt_out}"
        ),
        "B": (
            "Hello {first_name}, {sender_name} with {company}. We purchase properties as-is and can close on a "
            "timeline that suits your needs for {address}. {opt_out}"
        ),
    },
    "SENIOR_OWNER": {
        "A": (
            "Hi {first_name}, this is {sender_name} with {company}. I'm reaching out about {address}. If a "
            "simple, as-is sale with no repairs or showings would be helpful, I'd be glad to talk, and I'm happy "
            "to call you instead. {opt_out}"
        ),
        "B": (
            "Hello {first_name}, {sender_name} with {company}. We buy homes as-is and keep the process easy. If "
            "you'd like, I can call you to talk through {address} at a time that suits you. {opt_out}"
        ),
    },
    "OWNER_OCCUPIED": {
        "A": (
            "Hi {first_name}, this is {sender_name} with {company}. I'm reaching out about {address}. We buy "
            "as-is and can offer flexible move-out timing that works for you. {opt_out}"
        ),
        "B": (
            "Hello {first_name}, {sender_name} with {company}. If selling {address} is something you'd consider, "
            "we purchase as-is with flexible closing and move-out dates. {opt_out}"
        ),
    },
    "FAILED_OR_EXPIRED_LISTING": {
        "A": (
            "Hi {first_name}, this is {sender_name} with {company}. If selling {address} hasn't worked out the "
            "way you hoped, we offer a no-hassle, as-is alternative with no repairs. {opt_out}"
        ),
        "B": (
            "Hello {first_name}, {sender_name} with {company}. We offer a no-hassle, as-is option for {address} "
            "if you'd rather avoid showings and repairs. {opt_out}"
        ),
    },
    "FOLLOWUP_D3": {
        "A": (
            "Hi {first_name}, this is {sender_name} with {company}, following up on my note about {address}. "
            "Still open to a quick chat about your options? {opt_out}"
        ),
        "B": (
            "Hello {first_name}, {sender_name} with {company}. Just checking whether you saw my note about "
            "{address}. Happy to answer anything. {opt_out}"
        ),
    },
    "FOLLOWUP_D7": {
        "A": (
            "Hi {first_name}, this is {sender_name} with {company}, checking in on {address}. Happy to answer "
            "any questions or share what we could offer. {opt_out}"
        ),
        "B": (
            "Hello {first_name}, {sender_name} with {company}. No rush at all on {address}, just letting you "
            "know I'm still glad to talk whenever it suits you. {opt_out}"
        ),
    },
    "FOLLOWUP_D14": {
        "A": (
            "Hi {first_name}, this is {sender_name} with {company}, reaching out once more about {address}. If "
            "now isn't a good time, no worries at all. {opt_out}"
        ),
        "B": (
            "Hello {first_name}, {sender_name} with {company}. I'll leave this with you about {address}, and I'm "
            "easy to reach if anything changes. {opt_out}"
        ),
    },
    "CHECKIN_D30": {
        "A": (
            "Hi {first_name}, this is {sender_name} with {company}, just a friendly check-in on {address}. Let "
            "me know if anything has changed. {opt_out}"
        ),
        "B": (
            "Hello {first_name}, {sender_name} with {company}. Checking in on {address}, in case your plans "
            "have shifted. {opt_out}"
        ),
    },
    "MONTHLY_TOUCH": {
        "A": (
            "Hi {first_name}, this is {sender_name} with {company}, checking in on {address}. Still here if "
            "you'd like to explore options. {opt_out}"
        ),
        "B": (
            "Hello {first_name}, {sender_name} with {company}. A quick monthly note on {address}, in case you'd "
            "like to talk anything through. {opt_out}"
        ),
    },
}


def canonical_category(category: str | None) -> str | None:
    if not category:
        return category
    return LEGACY_CATEGORY_ALIASES.get(category, category)


# ── Identity and validation ──────────────────────────────────────────────────
def sender_identity(settings=None) -> tuple[str, str]:
    """Return (sender_name, company_name) from Settings without inventing values."""
    if settings is None:
        from ..config import get_settings

        settings = get_settings()
    name = (getattr(settings, "sender_name", "") or getattr(settings, "draft_manager_name", "") or "").strip()
    company = (getattr(settings, "company_name", "") or getattr(settings, "draft_company", "") or "").strip()
    return name, company


def template_has_optout(body: str) -> bool:
    low = (body or "").lower()
    return "stop" in low and ("opt out" in low or "unsubscribe" in low)


def validate_message(
    body: str,
    first_name_present: bool = True,
    sender_name: str | None = None,
    company: str | None = None,
    first_message: bool = True,
) -> tuple[bool, list[str]]:
    """Hard content rules applied to every cold draft. Returns (ok, reasons)."""
    reasons: list[str] = []
    if not body or not body.strip():
        return False, ["empty body"]
    if len(body) > MAX_CHARS:
        reasons.append(f"over {MAX_CHARS} chars ({len(body)})")
    low = body.lower()
    for pattern in BANNED_PATTERNS:
        match = re.search(pattern, low)
        if match:
            reasons.append(f"banned word: {match.group(0)}")
    for pattern in URGENCY_PATTERNS:
        match = re.search(pattern, low)
        if match:
            reasons.append(f"false urgency: {match.group(0)}")
    if any(token in body for token in PLACEHOLDER_TOKENS):
        reasons.append("raw placeholder")
    null_match = NULL_TOKENS.search(body)
    if null_match:
        reasons.append(f"null/undefined placeholder: {null_match.group(0)}")
    if not first_name_present and "{first_name}" in body:
        reasons.append("first_name placeholder with no name")
    if EMOJI_PATTERN.search(body):
        reasons.append("emoji present")
    if URL_PATTERN.search(body):
        reasons.append("link in first message")
    if first_message and MONEY_PATTERN.search(body):
        reasons.append("dollar amount in first message")
    if not template_has_optout(body):
        reasons.append("missing opt-out line")
    if sender_name and company:
        if f"{sender_name} with {company}" not in body:
            if sender_name not in body:
                reasons.append("missing sender name")
            if company not in body:
                reasons.append("missing company identification")
    else:
        if "GreenSeed" not in body:
            reasons.append("missing company identification")
        if "Jason Wade" not in body:
            reasons.append("missing sender name")
    return (len(reasons) == 0), reasons


# ── Selection ────────────────────────────────────────────────────────────────
def lead_flags(lead) -> dict:
    """Read the normalised Data Syndicate flags for this lead, tolerating old rows."""
    flags = getattr(lead, "ds_flags", None)
    if isinstance(flags, dict) and flags:
        return flags
    source = getattr(lead, "source_data", None) or {}
    normalized = source.get("normalized") if isinstance(source.get("normalized"), dict) else source
    flags = (normalized or {}).get("flags") if isinstance(normalized, dict) else None
    return flags if isinstance(flags, dict) else {}


def select_category(lead) -> str:
    """Pick the most specific matching template category for a lead."""
    flags = lead_flags(lead)
    lead_type = (getattr(lead, "lead_type", None) or "").lower()
    if flags.get("senior_owner"):
        return "SENIOR_OWNER"
    if "inherit" in lead_type or "probate" in lead_type:
        return "INHERITANCE_PROBATE"
    if "divorce" in lead_type:
        return "DIVORCE"
    if (
        "corporate" in lead_type
        or "trust" in lead_type
        or flags.get("corporate_owned")
        or flags.get("trust_owned")
        or flags.get("absentee_in_state")
    ):
        return "ABSENTEE_CORPORATE_TRUST"
    if flags.get("failed_listing") or flags.get("expired_listing") or flags.get("below_market_listing"):
        return "FAILED_OR_EXPIRED_LISTING"
    if (
        "tax" in lead_type
        or "lien" in lead_type
        or "lis pendens" in lead_type
        or "hoa" in lead_type
        or flags.get("involuntary_lien")
        or flags.get("hoa_fees")
    ):
        return "TAX_LIEN_LISPENDENS_HOA"
    if flags.get("owner_occupied") or lead_type in {"owner occupied", "owner_occupied"}:
        return "OWNER_OCCUPIED"
    return "GENERIC_OPENER"


def selection_reason(lead) -> dict:
    """Explain the chosen category with the tags that matched (shown in the UI)."""
    flags = lead_flags(lead)
    lead_type = (getattr(lead, "lead_type", None) or "").strip()
    tags = []
    for name in (
        "senior_owner",
        "corporate_owned",
        "trust_owned",
        "absentee_in_state",
        "failed_listing",
        "expired_listing",
        "below_market_listing",
        "involuntary_lien",
        "hoa_fees",
        "owner_occupied",
        "free_and_clear",
        "high_equity",
        "low_equity",
        "for_sale_by_owner",
        "recently_sold",
    ):
        if flags.get(name):
            tags.append(name)
    if lead_type:
        tags.append(f"lead_type:{lead_type}")
    return {"category": select_category(lead), "tags": tags}


# ── Rendering ────────────────────────────────────────────────────────────────
def _first_name(lead) -> str:
    first = (getattr(lead, "first_name", None) or "").strip()
    if first:
        return first
    full = (getattr(lead, "full_name", None) or "").strip()
    if full:
        return full.split()[0]
    return ""


def _property(lead):
    try:
        return lead.properties[0] if lead.properties else None
    except Exception:
        return None


def render_template(body: str, lead, sender_name: str | None = None, company: str | None = None) -> str:
    name, org = sender_identity()
    sender_name = (sender_name or name or "").strip()
    company = (company or org or "").strip()
    prop = _property(lead)
    address = (getattr(prop, "street_address", None) or "").strip()
    city = (getattr(prop, "city", None) or "").strip()
    out = body
    first = _first_name(lead)
    if not first:
        # A lead with no verified owner name must not read "Hi Hello". Drop the
        # greeting word instead, and keep the sentence grammatical.
        for opener in ("Hi {first_name}, ", "Hi {first_name} — ", "Hi {first_name} ", "Hi {first_name},"):
            if opener in out:
                out = out.replace(opener, "Hello, ", 1)
                break
        else:
            out = out.replace("{first_name}", "there")
        first = ""
    out = out.replace("{first_name}", first)
    out = out.replace("{address}", address or "your property")
    out = out.replace("{city}", city)
    out = out.replace("{sender_name}", sender_name)
    out = out.replace("{company}", company)
    out = out.replace("{opt_out}", OPT_OUT_LINE)
    return out


def lookup_template(db: Session, category: str, variant: str | None = None) -> Template | None:
    """Find an active template, honouring legacy category names."""
    names = [category] + [legacy for legacy, new in LEGACY_CATEGORY_ALIASES.items() if new == category]
    query = db.query(Template).filter(Template.category.in_(names), Template.active.is_(True))
    if variant:
        exact = query.filter(Template.variant == variant).first()
        if exact:
            return exact
    rows = query.order_by(Template.variant).all()
    return rows[0] if rows else None


# ── Seeding / resetting ──────────────────────────────────────────────────────
def seed_templates(db: Session, force: bool = False) -> int:
    """Seed any missing default template. Existing rows are never overwritten."""
    created = 0
    for category, variants in DEFAULT_TEMPLATES.items():
        for variant, body in variants.items():
            exists = (
                db.query(Template)
                .filter(Template.category == category, Template.variant == variant)
                .first()
            )
            if exists:
                continue
            db.add(
                Template(
                    category=category,
                    variant=variant,
                    body=body,
                    active=True,
                    stats={"used": 0, "copied": 0, "replied": 0},
                )
            )
            created += 1
    if created:
        db.add(AuditLog(action="templates_seeded", details={"created": created, "force": force}))
    db.commit()
    return created


def reset_templates(db: Session) -> dict:
    """Restore the default bodies for every default category (explicit user action)."""
    updated = 0
    created = 0
    for category, variants in DEFAULT_TEMPLATES.items():
        for variant, body in variants.items():
            row = (
                db.query(Template)
                .filter(Template.category == category, Template.variant == variant)
                .first()
            )
            if row is None:
                db.add(Template(category=category, variant=variant, body=body, active=True, stats={}))
                created += 1
            else:
                if row.body != body or row.version < 2:
                    row.body = body
                    row.version = max(row.version, 2)
                    row.active = True
                    updated += 1
    db.add(AuditLog(action="templates_reset", details={"updated": updated, "created": created}))
    db.commit()
    return {"updated": updated, "created": created}


# ── Gates and rendering for cold outreach ────────────────────────────────────
def draft_gates(db: Session, lead) -> tuple[list[str], list[str]]:
    """Return (blocking reasons, copy-time warnings) for a cold draft."""
    from .compliance import can_send, is_in_license, is_suppressed, _settings

    blocking: list[str] = []
    warnings: list[str] = []
    if lead.needs_skip_trace:
        blocking.append("Needs skip trace: no owner name or phone is verified yet")
    if lead.do_not_contact:
        blocking.append("Do Not Contact restriction: outreach drafts are blocked")
    elif lead.restriction_status != "reviewed_clear":
        blocking.append("Contact restrictions are not reviewed; record an evidence-based review first")
    if not (lead.full_name or "").strip():
        blocking.append("Needs skip trace: the owner name is missing")
    if not (lead.primary_phone or "").strip():
        blocking.append("Needs skip trace: no verified phone number")
    elif is_suppressed(db, lead.primary_phone):
        blocking.append("This phone number is on the suppression list")
    licensed = _settings(db).get("licensed_counties")
    if getattr(lead, "in_license", True) is False or not is_in_license(lead, licensed):
        blocking.append("Out of license: this property is outside the licensed counties")
    ok, reason = can_send(db, lead)
    if not ok and reason in {"quiet_hours", "daily_cap", "hourly_cap"}:
        warnings.append(
            {
                "quiet_hours": "Outside the allowed contact window right now (09:00-20:00 seller local time)",
                "daily_cap": "The daily contact cap is reached",
                "hourly_cap": "The hourly contact cap is reached",
            }[reason]
        )
    elif not ok and reason == "suppressed":
        if "suppression" not in " ".join(blocking):
            blocking.append("This phone number is on the suppression list")
    elif not ok and reason == "out_of_license" and not any("license" in b for b in blocking):
        blocking.append("Out of license: this property is outside the licensed counties")
    return blocking, warnings


def draft_cold(
    db: Session,
    lead: Lead,
    settings,
    template_id: int | None = None,
    variant: str | None = None,
    body: str | None = None,
    regenerate: bool = False,
) -> dict:
    """Render (or re-render) a cold template draft. Never sends, never guesses."""
    sender_name, company = sender_identity(settings)
    if not sender_name or not company:
        raise ValueError("Sender identity is missing. Set the sender name and company in Settings first")

    blocking, warnings = draft_gates(db, lead)
    if blocking:
        raise ValueError("; ".join(blocking))

    if not regenerate and body is None and template_id is None:
        existing = (
            db.query(Message)
            .filter(Message.lead_id == lead.id, Message.status == "DRAFT", Message.direction == "outbound")
            .order_by(Message.id.desc())
            .first()
        )
        if existing and existing.body:
            return message_view(existing)

    reason = selection_reason(lead)
    template = db.get(Template, template_id) if template_id else lookup_template(db, reason["category"], variant)
    if template is None and body is None:
        raise ValueError("No active template is available for this lead; restore the defaults in Settings")
    chosen_variant = (variant or (template.variant if template else "A") or "A")[:4]

    rendered = body if body is not None else render_template(template.body, lead, sender_name, company)
    if not template_has_optout(rendered):
        rendered = rendered.rstrip() + " " + OPT_OUT_LINE
    ok, failures = validate_message(
        rendered,
        bool(_first_name(lead)),
        sender_name=sender_name,
        company=company,
    )
    record = Message(
        lead_id=lead.id,
        direction="outbound",
        body=rendered,
        template_id=template.id if template else None,
        variant=chosen_variant,
        status="DRAFT",
        validator_result={"ok": ok, "reasons": failures},
        reason_tags=(reason["tags"] if body is None else []),
        classification=None,
    )
    db.add(record)
    db.add(
        AuditLog(
            lead_id=lead.id,
            action="draft_prepared",
            details={
                "mode": "cold",
                "template_category": reason["category"],
                "template_id": template.id if template else None,
                "variant": chosen_variant,
                "validator_ok": ok,
                "why": reason["tags"],
                "never_sent": True,
            },
        )
    )
    db.commit()
    db.refresh(record)
    view = message_view(record)
    view.update(
        {
            "category": reason["category"],
            "why_this_template": reason["tags"],
            "mode": "cold",
            "warnings": warnings,
            "model_id": "local-template-render (not AI)",
        }
    )
    return view


def message_view(record: Message) -> dict:
    return {
        "id": record.id,
        "lead_id": record.lead_id,
        "body": record.body,
        "status": record.status,
        "template_id": record.template_id,
        "variant": record.variant,
        "validator_result": record.validator_result or {},
        "reason_tags": record.reason_tags or [],
        "why_this_template": record.reason_tags or [],
        "mode": "cold",
        "model_id": "local-template-render (not AI)",
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "updated_at": record.created_at.isoformat() if record.created_at else None,
    }


def draft_view(view: dict) -> dict:
    """Compatibility shim: the unified API keeps one shape for both modes."""
    return view


def create_draft(db: Session, lead, template_id: int | None = None, variant: str = "A", body: str | None = None) -> Message:
    """Legacy helper kept for the sequence/reply services. Renders a validated draft."""
    from ..config import get_settings

    view = draft_cold(
        db,
        lead,
        get_settings(),
        template_id=template_id,
        variant=variant,
        body=body,
        regenerate=True,
    )
    return db.get(Message, view["id"])


def approve_message(db: Session, message_id: int) -> Message:
    """Mark a draft reviewed. Approving never sends it anywhere."""
    m = db.get(Message, message_id)
    if m is None:
        raise ValueError("Message not found")
    if m.status != "DRAFT":
        raise ValueError("Only drafts can be approved")
    sender_name, company = sender_identity()
    ok, reasons = validate_message(m.body, True, sender_name=sender_name, company=company)
    if not ok:
        raise ValueError("Message failed validation: " + ", ".join(reasons))
    m.status = "APPROVED"
    db.add(AuditLog(lead_id=m.lead_id, action="draft_approved", details={"message_id": m.id, "never_sent": True}))
    db.commit()
    db.refresh(m)
    return m


def bulk_drafts(db: Session, leads, settings, variant: str | None = None) -> list[dict]:
    """Generate drafts for a reviewed selection. Results appear in the review queue only."""
    results = []
    for lead in leads:
        try:
            view = draft_cold(db, lead, settings, variant=variant)
            results.append({"lead_id": lead.id, "ok": True, "message_id": view["id"], "body": view["body"]})
        except Exception as error:
            db.rollback()
            results.append({"lead_id": lead.id, "ok": False, "reason": str(error)})
    return results
