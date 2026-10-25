"""Merged local preparation/research tools. No dialer, provider calls or CRM writes."""

from copy import deepcopy
import re
from sqlalchemy import select
from sqlalchemy.orm import object_session
from ..models import CallPlan, AuditLog
from .ai import context_for, context_hash
from .imports import PROPERTY_FIELDS
from .property_facts import EXTRA_FACTS, finite_number
from ..db import utcnow


def display_name(lead):
    return lead.full_name or (
        "Owner unknown · " + (lead.properties[0].street_address or "Address unknown")
        if lead.properties
        else "Owner identity unknown"
    )


def fill_empty_fields(db, lead, data, provenance):
    # A property match is not proof of the same person. Never fill across a known identity conflict.
    for field in ("full_name", "primary_phone", "email"):
        old, new = getattr(lead, field), data.get(field)
        if old and new and re.sub(r"\W", "", old.lower()) != re.sub(r"\W", "", str(new).lower()):
            raise ValueError("Conflicting seller identity: review separately; missing fields were not filled")
    enriched = deepcopy(lead.source_data.get("local_enrichment", {}))
    changed = []
    for field in ("full_name", "first_name", "last_name", "primary_phone", "email", "lead_source", "assigned_manager"):
        if not getattr(lead, field) and data.get(field) not in (None, ""):
            setattr(lead, field, data[field])
            enriched[field] = {"value": data[field], "provenance": provenance, "recorded_at": utcnow().isoformat()}
            changed.append(field)
    for field in ("seller_motivation", "notes"):
        if data.get(field) and not lead.source_data.get("normalized", {}).get(field) and field not in enriched:
            enriched[field] = {"value": data[field], "provenance": provenance, "recorded_at": utcnow().isoformat()}
            changed.append(field)
    if data.get("source_do_not_contact") is True and not lead.do_not_contact:
        lead.local_do_not_contact = True
        changed.append("local_do_not_contact")
    for prop in lead.properties:
        matched = (data.get("external_property_id") and prop.external_id == data["external_property_id"]) or (
            data.get("normalized_address") and prop.normalized_address == data["normalized_address"]
        )
        if not matched:
            continue
        metadata = deepcopy(prop.property_metadata)
        filled = metadata.setdefault("local_enrichment", {})
        for field in PROPERTY_FIELDS:
            if getattr(prop, field) is None and data.get(field) is not None:
                setattr(prop, field, data[field])
                filled[field] = {"value": data[field], "provenance": provenance}
                changed.append("property." + field)
        facts = metadata.setdefault("facts", {})
        for field in EXTRA_FACTS:
            if facts.get(field) in (None, "") and data.get(field) not in (None, ""):
                facts[field] = data[field]
                filled[field] = {"value": data[field], "provenance": provenance}
                changed.append("property." + field)
        prop.property_metadata = metadata
    if changed:
        lead.source_data = {**lead.source_data, "local_enrichment": enriched}
        db.add(
            AuditLog(
                lead_id=lead.id,
                action="missing_fields_filled_locally",
                details={"fields": changed, "provenance": provenance, "crm_write": False},
            )
        )
    return changed


def plan_dict(plan, lead):
    stale = plan.context_hash != context_hash(lead, context_for(object_session(plan), lead))
    restricted = (
        lead.do_not_contact
        or lead.restriction_status != "reviewed_clear"
        or not lead.full_name
        or not lead.primary_phone
    )
    return {
        **{
            key: getattr(plan, key)
            for key in (
                "id",
                "lead_id",
                "talking_points",
                "questions",
                "guardrails",
                "reason",
                "source",
                "created_at",
                "updated_at",
            )
        },
        "opener": None if restricted or stale else plan.opener,
        "internal_only": plan.internal_only or restricted,
        "stale": stale,
        "communication": False,
    }


def get_plan(db, lead):
    return db.scalar(select(CallPlan).where(CallPlan.lead_id == lead.id).order_by(CallPlan.id.desc()))


def prepare_plan(db, lead, regenerate=False):
    context = context_for(db, lead)
    hashed = context_hash(lead, context)
    old = get_plan(db, lead)
    if old and not regenerate:
        if old.context_hash != hashed:
            raise ValueError("Source context changed. Explicitly regenerate; prior checklist is preserved.")
        return old
    permission = lead.restriction_status == "reviewed_clear" and bool(lead.full_name and lead.primary_phone)
    relationship = lead.contact_outcome == "Callback Requested" or bool(
        lead.source_data.get("normalized", {}).get("seller_motivation")
    )
    opener = None
    reason = None
    if lead.do_not_contact:
        reason = "Do Not Contact: internal record review only; no outreach script prepared."
    elif not permission:
        reason = "Identity, phone or contact restrictions are incomplete. Internal preparation only."
    elif not relationship:
        reason = "No verified callback/motivation relationship context. Confirm the approved workflow; no generic opener prepared."
    else:
        first = lead.first_name or lead.full_name.split()[0]
        opener = f"Hi {first}, this is [your name] with [company]. "
        opener += (
            "I’m responding to your callback request. "
            if lead.contact_outcome == "Callback Requested"
            else "Are you still considering selling your property? "
        )
        opener += "Is now a convenient time to talk?"
    points = []
    for prop in lead.properties:
        for field, label in [
            ("bedrooms", "Recorded bedrooms"),
            ("bathrooms", "Recorded bathrooms"),
            ("square_feet", "Recorded square feet"),
            ("year_built", "Recorded year built"),
            ("asking_price", "Seller asking-price record, not our offer"),
            ("estimated_value", "Recorded estimate, not a verified ARV or offer"),
        ]:
            value = getattr(prop, field)
            if value is not None:
                points.append(
                    {
                        "key": f"{prop.id}:{field}",
                        "text": f"{label}: {value}",
                        "evidence": [f"property:{prop.id}:{field}"],
                        "reviewed": False,
                    }
                )
    questions = [
        {"key": key, "text": text, "required": required, "reviewed": False, "answer": ""}
        for key, text, required in [
            ("motivation", "Confirm the actual reason for considering a sale.", True),
            ("timeline", "Ask the preferred timeline; do not promise a date.", True),
            ("price", "Ask price expectations; do not imply a company offer.", True),
            ("condition", "Confirm condition and any repairs, rather than assuming.", False),
            ("occupancy", "Confirm who occupies the property and any tenancy.", False),
            ("decision", "Confirm decision makers and authorized access.", False),
            ("liens", "Ask whether there are liens or mortgages; do not infer a balance.", False),
        ]
    ]
    if lead.do_not_contact:
        questions = [
            {
                "key": "restriction",
                "text": "Verify and preserve the source contact restriction internally.",
                "required": True,
                "reviewed": False,
                "answer": "",
            }
        ]
    plan = CallPlan(
        lead_id=lead.id,
        context_hash=hashed,
        opener=opener,
        talking_points=points[:20],
        questions=questions,
        guardrails=[
            "This is preparation, not a call log. Checking an item never records seller contact.",
            "No dialing, invitations, SMS or email are implemented.",
            "Recorded valuations/equity are unverified references; never promise purchase, pricing or closing.",
            "Confirm source facts and company eligibility; do not invent conversations or timing.",
        ],
        internal_only=opener is None,
        reason=reason,
    )
    db.add(plan)
    db.add(
        AuditLog(
            lead_id=lead.id,
            action="call_preparation_created",
            details={"local_rules_only": True, "contact_occurred": False},
        )
    )
    db.commit()
    return plan


def update_plan(db, lead, plan, checks, answers, opener=None):
    if plan.context_hash != context_hash(lead, context_for(db, lead)):
        raise ValueError("Preparation is stale. Review/regenerate before editing it.")
    allowed = {item["key"] for item in plan.questions + plan.talking_points}
    if set(checks) - allowed or set(answers) - {q["key"] for q in plan.questions}:
        raise ValueError("Unknown preparation item")
    if opener is not None:
        if plan.internal_only or lead.restriction_status != "reviewed_clear":
            raise ValueError("Current restrictions prevent an outreach opener")
        plan.opener = opener
    plan.questions = [
        {**q, "reviewed": checks.get(q["key"], q["reviewed"]), "answer": answers.get(q["key"], q.get("answer", ""))}
        for q in plan.questions
    ]
    plan.talking_points = [{**p, "reviewed": checks.get(p["key"], p["reviewed"])} for p in plan.talking_points]
    db.add(
        AuditLog(
            lead_id=lead.id,
            action="preparation_checklist_saved",
            details={"plan_id": plan.id, "contact_inferred": False},
        )
    )
    db.commit()
    return plan


def comps_brief(lead, property_id=None):
    properties = lead.properties
    prop = (
        next((p for p in properties if p.id == property_id), None)
        if property_id
        else (properties[0] if len(properties) == 1 else None)
    )
    if not prop:
        return {
            "subject": None,
            "properties": [{"id": p.id, "address": p.street_address} for p in properties],
            "reason": "Select an exact subject property; no address or comparable will be guessed.",
            "comps": [],
        }
    facts = prop.property_metadata.get("facts", {})
    anchor = finite_number(prop.estimated_value)
    references = []
    for key, label, value in [
        ("asking_price", "Recorded seller asking price (not an offer)", prop.asking_price),
        ("estimated_value", "Recorded value estimate (not verified ARV)", prop.estimated_value),
        ("tax_market_value", "County market-value record", facts.get("tax_market_value")),
        ("tax_assessed_value", "County assessed-value record", facts.get("tax_assessed_value")),
        ("estimated_equity", "Recorded equity estimate", facts.get("estimated_equity")),
        ("mortgage_balance", "Recorded mortgage balance", facts.get("mortgage_balance")),
    ]:
        if value is not None:
            references.append(
                {
                    "field": key,
                    "label": label,
                    "value": value,
                    "source": prop.property_metadata.get("value_source_labels", {}).get(
                        key,
                        prop.property_metadata.get(
                            "fact_source", prop.property_metadata.get("source", "recorded source")
                        ),
                    ),
                    "as_of": facts.get("tax_year") if key.startswith("tax_") else None,
                }
            )
    if anchor is None:
        anchor = finite_number(facts.get("tax_market_value"))
    criteria = {
        "radius_miles": 1,
        "same_zip": prop.zip_code,
        "sold_within_months": 12,
        "minimum_comps": 3,
        "property_type": prop.property_type,
        "beds_min": max(0, prop.bedrooms - 1) if prop.bedrooms is not None else None,
        "beds_max": prop.bedrooms + 1 if prop.bedrooms is not None else None,
        "sqft_min": round(prop.square_feet * 0.8) if prop.square_feet else None,
        "sqft_max": round(prop.square_feet * 1.2) if prop.square_feet else None,
        "price_min": round(anchor * 0.8) if anchor else None,
        "price_max": round(anchor * 1.2) if anchor else None,
    }
    return {
        "subject": {
            "id": prop.id,
            "address": prop.street_address,
            "street_address": prop.street_address,
            "city": prop.city,
            "state": prop.state,
            "zip_code": prop.zip_code,
            "bedrooms": prop.bedrooms,
            "bathrooms": prop.bathrooms,
            "square_feet": prop.square_feet,
            "year_built": prop.year_built,
            **facts,
        },
        "criteria": criteria,
        "references": references,
        "comps": [],
        "portals": [
            {"label": "Zillow", "url": "https://www.zillow.com/"},
            {"label": "Redfin", "url": "https://www.redfin.com/"},
            {"label": "Realtor.com", "url": "https://www.realtor.com/"},
        ],
        "notice": "Suggested research criteria, not actual sold comparables or an appraisal. No MLS feed, scraping or automatic portal requests. Copy the subject address and research using an approved source.",
    }
