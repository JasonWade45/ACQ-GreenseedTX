"""Duplicate detection for imported / synced seller leads.

Matching priority (strongest first):
1. REsimpli external id
2. Normalized phone + email together
3. Normalized phone
4. Normalized email
5. Normalized seller name (no contact keys at all — review only)
6. Normalized property address

Uncertain matches are returned for human review — nothing is merged
automatically.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.models import Lead, LeadProperty, Property

EXACT = "exact_duplicate"
LIKELY = "likely_duplicate"
SAME_SELLER_DIFF_PROPERTY = "same_seller_diff_property"
SAME_PROPERTY_DIFF_SELLER = "same_property_diff_seller"
EXISTING = "existing_resimpli"
NEW = "new"

DUPLICATE_STATUSES = {EXACT, LIKELY, SAME_SELLER_DIFF_PROPERTY, SAME_PROPERTY_DIFF_SELLER, EXISTING}

_NAME_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}


def _norm_name(value: Optional[str]) -> str:
    # Strip punctuation entirely (no space insertion): "O'Brien" == "Obrien".
    cleaned = re.sub(r"[^a-z\s]", "", (value or "").lower())
    tokens = [t for t in cleaned.split() if t and t not in _NAME_SUFFIXES]
    return " ".join(tokens)


@dataclass
class Candidate:
    external_id: Optional[str] = None
    phone_normalized: Optional[str] = None
    email_normalized: Optional[str] = None
    address_key: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None


@dataclass
class MatchResult:
    status: str
    reason: str
    matched_lead_ids: list[str] = field(default_factory=list)
    matched_details: list[dict[str, Any]] = field(default_factory=list)


def _lead_brief(lead: Lead) -> dict[str, Any]:
    address = None
    if lead.properties:
        primary = next((lp.property for lp in lead.properties if lp.is_primary), None)
        address = (primary or lead.properties[0].property).formatted_address
    return {
        "id": lead.id,
        "external_id": lead.external_id,
        "name": lead.display_name,
        "phone": lead.primary_phone,
        "email": lead.email,
        "address": address,
        "stage": lead.pipeline_stage,
        "origin": lead.origin,
    }


def _load_address_keys(db: Session, lead_ids: list[str]) -> dict[str, str]:
    if not lead_ids:
        return {}
    rows = (
        db.query(LeadProperty.lead_id, Property.address_normalized)
        .join(Property, Property.id == LeadProperty.property_id)
        .filter(LeadProperty.lead_id.in_(lead_ids), Property.address_normalized.isnot(None))
        .all()
    )
    return {lead_id: key for lead_id, key in rows}


def _find_by_name(db: Session, candidate: Candidate, exclude_lead_id: Optional[str] = None) -> list[Lead]:
    """Name-only lookup for rows with no phone/email/external id to match on."""
    first = _norm_name(candidate.first_name)
    last = _norm_name(candidate.last_name)
    if len(first) < 2 or len(last) < 2:
        return []
    query = db.query(Lead).filter(func.lower(Lead.first_name) == first)
    if exclude_lead_id:
        query = query.filter(Lead.id != exclude_lead_id)
    return [lead for lead in query.limit(50).all() if _norm_name(lead.last_name) == last]


def find_matches(db: Session, candidate: Candidate, exclude_lead_id: Optional[str] = None) -> MatchResult:
    conditions = []
    if candidate.external_id:
        conditions.append(Lead.external_id == candidate.external_id)
    if candidate.phone_normalized:
        conditions.append(Lead.phone_normalized == candidate.phone_normalized)
    if candidate.email_normalized:
        conditions.append(Lead.email_normalized == candidate.email_normalized)

    query = db.query(Lead)
    if exclude_lead_id:
        query = query.filter(Lead.id != exclude_lead_id)
    leads: list[Lead] = []
    if conditions:
        leads = query.filter(or_(*conditions)).limit(25).all()

    if not leads:
        # Name-only identity: the row has no contact keys to match on, but the
        # seller name may already exist — review-only, never merged.
        name_hits = _find_by_name(db, candidate, exclude_lead_id)
        if name_hits:
            name_keys = _load_address_keys(db, [lead.id for lead in name_hits])
            same_address = bool(
                candidate.address_key
                and any(name_keys.get(lead.id) == candidate.address_key for lead in name_hits)
            )
            return MatchResult(
                status=LIKELY,
                reason=(
                    "Same seller name and property address as an existing lead — review required"
                    if same_address
                    else "Same seller name as an existing lead (no phone/email match) — review required"
                ),
                matched_lead_ids=[lead.id for lead in name_hits],
                matched_details=[_lead_brief(lead) for lead in name_hits],
            )
        # Fall back to address-only matching when we have an address
        if candidate.address_key:
            prop_ids = [
                row[0]
                for row in db.query(Property.id)
                .filter(Property.address_normalized == candidate.address_key)
                .limit(10)
                .all()
            ]
            if prop_ids:
                link_rows = (
                    db.query(LeadProperty.lead_id)
                    .filter(LeadProperty.property_id.in_(prop_ids))
                    .limit(10)
                    .all()
                )
                if link_rows:
                    leads = (
                        db.query(Lead)
                        .filter(Lead.id.in_([r[0] for r in link_rows]))
                        .limit(10)
                        .all()
                    )
                    address_keys = _load_address_keys(db, [lead.id for lead in leads])
                    same_property_other_seller = []
                    for lead in leads:
                        same_seller_identity = (
                            candidate.phone_normalized and lead.phone_normalized == candidate.phone_normalized
                        ) or (
                            candidate.email_normalized and lead.email_normalized == candidate.email_normalized
                        )
                        if not same_seller_identity:
                            same_property_other_seller.append(lead)
                    if same_property_other_seller and all(
                        address_keys.get(lead.id) == candidate.address_key for lead in same_property_other_seller
                    ):
                        return MatchResult(
                            status=SAME_PROPERTY_DIFF_SELLER,
                            reason="Same property address but a different seller identity",
                            matched_lead_ids=[lead.id for lead in same_property_other_seller],
                            matched_details=[_lead_brief(lead) for lead in same_property_other_seller],
                        )
        return MatchResult(status=NEW, reason="No existing record matched")

    address_keys = _load_address_keys(db, [lead.id for lead in leads])
    details = [_lead_brief(lead) for lead in leads]
    matched_ids = [lead.id for lead in leads]

    if candidate.external_id and any(lead.external_id == candidate.external_id for lead in leads):
        return MatchResult(
            status=EXACT,
            reason=f"Same REsimpli lead id ({candidate.external_id})",
            matched_lead_ids=matched_ids,
            matched_details=details,
        )

    same_phone = [lead for lead in leads if candidate.phone_normalized and lead.phone_normalized == candidate.phone_normalized]
    same_email = [lead for lead in leads if candidate.email_normalized and lead.email_normalized == candidate.email_normalized]
    both = [lead for lead in leads if lead in same_phone and lead in same_email]

    if both:
        same_address = [lead for lead in both if address_keys.get(lead.id) == candidate.address_key] if candidate.address_key else both
        if candidate.address_key and not same_address:
            return MatchResult(
                status=SAME_SELLER_DIFF_PROPERTY,
                reason="Same phone and email but a different property address",
                matched_lead_ids=[lead.id for lead in both],
                matched_details=[_lead_brief(lead) for lead in both],
            )
        return MatchResult(
            status=EXACT,
            reason="Same normalized phone and email",
            matched_lead_ids=[lead.id for lead in both],
            matched_details=[_lead_brief(lead) for lead in both],
        )

    if same_phone or same_email:
        basis = "phone" if same_phone else "email"
        pool = same_phone or same_email
        if candidate.address_key:
            diff_prop = [lead for lead in pool if address_keys.get(lead.id) and address_keys.get(lead.id) != candidate.address_key]
            if diff_prop and len(diff_prop) == len(pool):
                return MatchResult(
                    status=SAME_SELLER_DIFF_PROPERTY,
                    reason=f"Same {basis} but a different property address",
                    matched_lead_ids=[lead.id for lead in pool],
                    matched_details=[_lead_brief(lead) for lead in pool],
                )
        existing = [lead for lead in pool if lead.origin == "resimpli"]
        if existing and not candidate.external_id:
            return MatchResult(
                status=EXISTING,
                reason=f"Matches an existing REsimpli record by {basis}",
                matched_lead_ids=[lead.id for lead in existing],
                matched_details=[_lead_brief(lead) for lead in existing],
            )
        return MatchResult(
            status=LIKELY,
            reason=f"Matches on normalized {basis} only — review required",
            matched_lead_ids=[lead.id for lead in pool],
            matched_details=[_lead_brief(lead) for lead in pool],
        )

    return MatchResult(status=NEW, reason="No existing record matched")


@dataclass
class FileSeenIndex:
    """Tracks keys already seen inside a single import file."""

    external: dict[str, int] = field(default_factory=dict)
    phone: dict[str, int] = field(default_factory=dict)
    email: dict[str, int] = field(default_factory=dict)
    address: dict[str, int] = field(default_factory=dict)
    by_row: dict[int, Candidate] = field(default_factory=dict)

    def check(self, candidate: Candidate, row_number: int) -> tuple[bool, str, str, int]:
        if candidate.external_id and candidate.external_id in self.external:
            first = self.external[candidate.external_id]
            return True, f"Duplicate of row {first} (same REsimpli id)", "external", first
        if candidate.phone_normalized and candidate.phone_normalized in self.phone:
            first = self.phone[candidate.phone_normalized]
            return True, f"Duplicate of row {first} (same phone)", "phone", first
        if candidate.email_normalized and candidate.email_normalized in self.email:
            first = self.email[candidate.email_normalized]
            return True, f"Duplicate of row {first} (same email)", "email", first
        if candidate.address_key and candidate.address_key in self.address:
            first = self.address[candidate.address_key]
            return True, f"Duplicate of row {first} (same property address)", "address", first
        return False, "", "", -1

    def add(self, candidate: Candidate, row_number: int) -> None:
        self.by_row.setdefault(row_number, candidate)
        if candidate.external_id:
            self.external.setdefault(candidate.external_id, row_number)
        if candidate.phone_normalized:
            self.phone.setdefault(candidate.phone_normalized, row_number)
        if candidate.email_normalized:
            self.email.setdefault(candidate.email_normalized, row_number)
        if candidate.address_key:
            self.address.setdefault(candidate.address_key, row_number)
