"""Explicit property facts only; no AVM, scraping, inferred owner or midpoint prices."""

import math
import re
from decimal import Decimal, InvalidOperation

EXTRA_FACTS = {
    # REsimpli demands an APN for a land lead, so an imported one has to survive the
    # import. Without this key the value was dropped and every land lead blocked.
    "apn",
    "county",
    "lot_acres",
    "latitude",
    "longitude",
    "tax_market_value",
    "tax_assessed_value",
    "tax_year",
    "estimated_equity",
    "mortgage_balance",
    "occupancy_status",
    "property_condition",
}


def compound_dimensions(value):
    text = str(value).strip()
    out = {}
    amp = re.fullmatch(r"(\d{1,2})\s*&\s*(\d{1,2}(?:\.\d+)?)", text)
    if amp:
        return {"bedrooms": int(amp[1]), "bathrooms": float(amp[2])}
    for field, pattern in [
        ("bedrooms", r"\b(\d{1,2})\s*(?:beds?|bedrooms?|br)\b"),
        ("bathrooms", r"\b(\d{1,2}(?:\.\d+)?)\s*(?:baths?|bathrooms?|ba)\b"),
        ("square_feet", r"\b([\d,]+)\s*(?:sq\.?\s*ft\.?|sqft|square\s*feet)\b"),
    ]:
        match = re.search(pattern, text, re.I)
        if match:
            out[field] = float(match[1].replace(",", "")) if field == "bathrooms" else int(match[1].replace(",", ""))
    return out


def labelled_amount(value):
    text = str(value).strip()
    if re.search(r"\d\s*(?:[kKmM])?\s*(?:to|[-–])\s*\$?\s*\d", text):
        return None, "Price range left unknown; no midpoint was invented", None
    label = None
    labelled = re.fullmatch(r"(.+?)\s+(Redfin|Zillow|AVM|assessed|estimate)", text, re.I)
    if labelled:
        text, label = labelled[1], labelled[2]
    match = re.fullmatch(r"\$?\s*([\d,]+(?:\.\d+)?)\s*([kKmM])?", text)
    if not match:
        raise ValueError("Invalid numeric amount; map compound fields explicitly")
    number = Decimal(match[1].replace(",", "")) * ({"k": 1000, "m": 1000000}.get((match[2] or "").lower(), 1))
    if not number.is_finite() or number < 0 or number > Decimal("100000000000"):
        raise ValueError("Invalid non-negative numeric amount")
    return float(number), ("Magnitude suffix expanded without estimating" if match[2] else None), label


def split_full_address(text):
    match = re.fullmatch(r"\s*(.+),\s*([^,]+),\s*([A-Za-z]{2})\s+(\d{5}(?:-\d{4})?)\s*", str(text))
    if not match:
        return None
    return dict(street_address=match[1].strip(), city=match[2].strip(), state=match[3].upper(), zip_code=match[4])


def finite_number(value):
    try:
        if isinstance(value, bool):
            return None
        result = float(value)
        return result if math.isfinite(result) and result >= 0 else None
    except (ValueError, TypeError, InvalidOperation):
        return None


def source_property_facts(raw):
    """Known GitHub response paths are candidate mappings, not account verification."""
    if not isinstance(raw, dict):
        return {}
    info = raw.get("propertyInfo") or {}
    val = raw.get("valuation") or {}
    tax = raw.get("taxInfo") or {}
    mort = raw.get("mortgageInfo") or {}
    if not all(isinstance(block, dict) for block in [info, val, tax, mort]):
        return {}
    fields = {
        "bedrooms": info.get("bedRoomCount"),
        "bathrooms": info.get("bathRoomCount"),
        "square_feet": info.get("livingArea") or info.get("buildingArea"),
        "year_built": info.get("yearBuilt"),
        "estimated_value": val.get("estValue"),
        "lot_acres": info.get("lotSizeAcres"),
        "tax_market_value": tax.get("totalmarketValue") or tax.get("marketValue"),
        "tax_assessed_value": tax.get("totalAssessedValue"),
        "tax_year": tax.get("taxYear"),
        "estimated_equity": val.get("estEquity"),
        "mortgage_balance": mort.get("currentLoanBalance") or mort.get("amount"),
    }
    result = {k: finite_number(v) for k, v in fields.items() if v not in (None, "")}
    result = {k: v for k, v in result.items() if v is not None}
    if info.get("county"):
        result["county"] = str(info["county"])[:150]
    return result
