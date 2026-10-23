"""Extract property facts from REsimpli lead payloads into Property rows.

REsimpli's ``/lead/details`` response nests everything useful under
``propertyInfo`` (~80 fields: beds/baths/sqft/year/lot/county/lat-long plus
owner flags), plus ``valuation`` (AVM estimate), ``taxInfo`` (assessed +
market value), ``mortgageInfo`` (balance/lender), ``mlsInfo`` and
``lastSaleInfo``. Only the street address was being mapped before, so every
other column stayed empty. These helpers lift the whole block locally —
no extra API calls — so analysis, call scripts and comps criteria can rely
on real facts instead of an address alone.
"""
from __future__ import annotations

from typing import Any, Optional

from sqlalchemy.orm import Session

from app.models import Lead, Property
from app.services.leads import primary_property


def _num(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if f == f else None  # reject NaN


def _int(value: Any) -> Optional[int]:
    n = _num(value)
    if n is None:
        return None
    return int(n)


def _str(value: Any) -> Optional[str]:
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def extract_property_facts(raw: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """Return ``{column: value, ..., "extra": {block: dict}}`` or None.

    Pure function — no database access — so it is unit-testable and safe to
    reuse from the live sync and from offline backfills.
    """
    if not isinstance(raw, dict) or not raw:
        return None
    info = raw.get("propertyInfo")
    valuation = raw.get("valuation")
    tax = raw.get("taxInfo")
    mortgage = raw.get("mortgageInfo")
    mls = raw.get("mlsInfo")
    sale = raw.get("lastSaleInfo")
    info = info if isinstance(info, dict) else {}
    valuation = valuation if isinstance(valuation, dict) else None
    if not info and not valuation and not isinstance(tax, dict) and not isinstance(mortgage, dict):
        return None

    est_value = _num((valuation or {}).get("estValue"))
    facts: dict[str, Any] = {
        "address_line1": _str(info.get("stateAddress")),
        "city": _str(info.get("city")),
        "state": _str(info.get("state")),
        "zip_code": _str(info.get("zip")),
        "property_type": _str(info.get("propertyType")) or _str(info.get("propertyUseType")),
        "bedrooms": _num(info.get("bedRoomCount")),
        "bathrooms": _num(info.get("bathRoomCount")),
        "square_footage": _num(info.get("livingArea") or info.get("buildingArea") or info.get("area")),
        "year_built": _int(info.get("yearBuilt")),
        "county": _str(info.get("county")),
        "latitude": _num(info.get("latitude")),
        "longitude": _num(info.get("longitude")),
        "lot_acres": _num(info.get("lotSizeAcres")),
        "estimated_value": est_value,
    }
    extra: dict[str, Any] = {}
    for key, block in (
        ("property_info", info),
        ("valuation", valuation),
        ("tax", tax),
        ("mortgage", mortgage),
        ("mls", mls),
        ("last_sale", sale),
    ):
        if isinstance(block, dict) and block:
            extra[key] = block
    facts["extra"] = extra or None
    if not extra and all(v is None for k, v in facts.items() if k != "extra"):
        return None
    return facts


def _merge_extra(old: Optional[dict], new: dict) -> dict:
    """Block-wise merge: a payload that only refreshes ``valuation`` must not
    wipe the other blocks, and within a block the newest value wins."""
    out: dict[str, Any] = dict(old or {})
    for key, value in new.items():
        current = out.get(key)
        if isinstance(value, dict) and isinstance(current, dict):
            out[key] = {**current, **value}
        else:
            out[key] = value
    return out


def apply_property_data(db: Session, lead: Lead, raw: Optional[dict[str, Any]]) -> Optional[Property]:
    """Merge extracted facts into the lead's primary property row.

    None-valued facts never wipe an existing value; ``extra`` blocks are
    merged so re-syncs stay idempotent.
    """
    facts = extract_property_facts(raw)
    if not facts:
        return None
    prop = primary_property(lead)
    if prop is None:
        if not facts.get("address_line1"):
            return None
        from app.services.leads import link_property

        link_property(
            db,
            lead,
            address_line1=facts.get("address_line1"),
            city=facts.get("city"),
            state=facts.get("state"),
            zip_code=facts.get("zip_code"),
            property_type=facts.get("property_type"),
        )
        prop = primary_property(lead)
        if prop is None:
            return None

    for column in (
        "address_line1",
        "city",
        "state",
        "zip_code",
        "property_type",
        "bedrooms",
        "bathrooms",
        "square_footage",
        "year_built",
        "county",
        "latitude",
        "longitude",
        "lot_acres",
        "estimated_value",
    ):
        value = facts.get(column)
        if value is not None:
            setattr(prop, column, value)
    if facts.get("extra"):
        prop.extra = _merge_extra(prop.extra, facts["extra"])
    db.flush()
    return prop
