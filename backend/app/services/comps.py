"""Comparable-property brief for a subject property.

REsimpli's documented API has no comps feed and this project has no MLS key,
so this module NEVER fabricates sale prices or comp addresses. It assembles
only what we actually hold:

  * subject facts (from the lead payload's ``propertyInfo`` / import),
  * the official value references REsimpli already returned (AVM estimate,
    county tax values, equity) with their provenance,
  * a deterministic search criteria set (±1 bed/bath, ±20% sqft and price,
    same ZIP / within a mile, sold in the last 12 months),
  * deep links that open Zillow / Redfin / Realtor.com for the address so a
    human can pull real comps from the live portals.

If a comps data source (API key) is ever added, swap the ``links`` block for
its results — the shape stays stable for the UI.
"""
from __future__ import annotations

import re
import urllib.parse
from typing import Any, Optional

from app.models import Lead
from app.services.leads import primary_property


def _num(value: Any) -> Optional[float]:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value:
        return float(value)
    return None


def _band(value: Optional[float], pct: float) -> tuple[Optional[int], Optional[int]]:
    if not value:
        return None, None
    return int(round(value * (1 - pct / 100))), int(round(value * (1 + pct / 100)))


def comps_brief(lead: Lead) -> dict[str, Any]:
    prop = primary_property(lead)
    if prop is None or not prop.address_line1:
        return {"subject": None, "reason": "No property linked to this lead."}

    extra = prop.extra or {}
    tax = extra.get("tax") if isinstance(extra.get("tax"), dict) else {}
    valuation = extra.get("valuation") if isinstance(extra.get("valuation"), dict) else {}
    mortgage = extra.get("mortgage") if isinstance(extra.get("mortgage"), dict) else {}

    subject: dict[str, Any] = {
        "address": prop.formatted_address,
        "city": prop.city,
        "state": prop.state,
        "zip": prop.zip_code,
        "county": prop.county,
        "property_type": prop.property_type,
        "beds": prop.bedrooms,
        "baths": prop.bathrooms,
        "sqft": prop.square_footage,
        "year_built": prop.year_built,
        "lot_acres": prop.lot_acres,
        "latitude": prop.latitude,
        "longitude": prop.longitude,
    }

    est_value = _num(prop.estimated_value)
    tax_year = tax.get("taxYear") or tax.get("assessedYear")
    market_value = _num(tax.get("totalmarketValue")) or _num(tax.get("marketValue"))
    assessed = _num(tax.get("totalAssessedValue"))

    price_anchor = est_value or market_value
    price_min, price_max = _band(price_anchor, 20)
    beds = prop.bedrooms
    baths = prop.bathrooms
    sqft = prop.square_footage
    sqft_min, sqft_max = _band(sqft, 20)

    criteria: dict[str, Any] = {
        "beds_min": max(1, int(beds) - 1) if beds else None,
        "beds_max": (int(beds) + 1) if beds else None,
        "baths_min": max(1, int(baths) - 1) if baths else None,
        "baths_max": (int(baths) + 1) if baths else None,
        "sqft_min": sqft_min,
        "sqft_max": sqft_max,
        "price_min": price_min,
        "price_max": price_max,
        "sold_within_months": 12,
        "radius": f"same ZIP {prop.zip_code}" if prop.zip_code else "within 1 mile",
        "property_type": prop.property_type,
        "min_comps": 3,
    }

    value_refs: list[dict[str, Any]] = []
    if est_value:
        value_refs.append(
            {
                "label": "REsimpli valuation estimate",
                "value": int(est_value),
                "source": "lead payload · valuation.estValue",
            }
        )
    if market_value:
        value_refs.append(
            {
                "label": "County market value",
                "value": int(market_value),
                "source": f"tax record{f' · {tax_year}' if tax_year else ''}",
            }
        )
    if assessed:
        value_refs.append(
            {
                "label": "County assessed value",
                "value": int(assessed),
                "source": f"tax record{f' · {tax_year}' if tax_year else ''}",
            }
        )
    equity = _num(valuation.get("estEquity"))
    if equity:
        value_refs.append(
            {"label": "Estimated equity", "value": int(equity), "source": "REsimpli valuation"}
        )
    balance = _num(mortgage.get("amount")) or _num(mortgage.get("currentLoanBalance"))
    if balance:
        lender = mortgage.get("lenderName") or "recorded lender"
        value_refs.append(
            {"label": "Mortgage balance", "value": int(balance), "source": str(lender)}
        )

    q = prop.formatted_address
    q_enc = urllib.parse.quote(q)
    kebab = re.sub(r"[^A-Za-z0-9]+", "-", q).strip("-")
    links: dict[str, str] = {
        "zillow": f"https://www.zillow.com/homes/{q_enc}_rb/",
        "redfin": f"https://www.redfin.com/address/{kebab}",
    }
    if prop.city and prop.state:
        city_slug = re.sub(r"[^A-Za-z0-9]+", "-", prop.city).strip("-")
        links["realtor"] = f"https://www.realtor.com/realestateandhomes-search/{city_slug}_{prop.state.upper()}"

    return {
        "subject": {k: v for k, v in subject.items() if v is not None},
        "criteria": criteria,
        "value_refs": value_refs,
        "links": links,
        "comps": [],
        "notes": (
            "Criteria derived from the subject property records we hold. This app has no "
            "MLS/comps feed, so comp addresses and sold prices are never invented here — "
            "open a portal link, filter to the criteria above, and record real comps in "
            "the lead's notes."
        ),
        "provenance": (
            "Subject facts: REsimpli propertyInfo (extracted at sync) or imported row. "
            "Values: REsimpli valuation + county tax record from the lead payload."
        ),
    }
