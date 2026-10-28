import csv
import io
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo
from .property_facts import compound_dimensions, labelled_amount, split_full_address
import phonenumbers
from dateutil import parser, tz

FIELDS = {
    "external_property_id": "External property ID",
    "first_name": "First name",
    "last_name": "Last name",
    "full_name": "Full name",
    "primary_phone": "Phone number",
    "email": "Email address",
    "street_address": "Property street address",
    "city": "City",
    "state": "State",
    "zip_code": "ZIP code",
    "property_type": "Property type",
    "lead_source": "Lead source",
    "original_created_at": "Original lead creation date",
    "last_contact_at": "Last contact date",
    "contact_outcome": "Last contact outcome",
    "source_status": "Lead status",
    "assigned_manager": "Assigned acquisitions manager",
    "seller_motivation": "Seller motivation",
    "asking_price": "Asking price",
    "estimated_value": "Estimated value",
    "repair_estimate": "Repair estimate",
    "appointment_at": "Appointment date",
    "next_followup_at": "Follow-up date",
    "notes": "Notes",
    "external_id": "Existing REsimpli lead ID",
    "source_do_not_contact": "Do Not Contact status",
    "bedrooms": "Bedrooms",
    "bathrooms": "Bathrooms",
    "square_feet": "Square feet",
    "year_built": "Year built",
    "bed_bath_sqft": "Combined beds / baths / square feet",
    "county": "County",
    "lot_acres": "Lot acres",
    "tax_market_value": "Recorded county market value",
    "tax_assessed_value": "Recorded county assessed value",
    "tax_year": "Recorded tax year",
    "estimated_equity": "Recorded estimated equity",
    "mortgage_balance": "Recorded mortgage balance",
    "occupancy_status": "Recorded occupancy status",
    "property_condition": "Recorded property condition",
}
STATES = dict(
    zip(
        [
            "alabama",
            "alaska",
            "arizona",
            "arkansas",
            "california",
            "colorado",
            "connecticut",
            "delaware",
            "district of columbia",
            "florida",
            "georgia",
            "hawaii",
            "idaho",
            "illinois",
            "indiana",
            "iowa",
            "kansas",
            "kentucky",
            "louisiana",
            "maine",
            "maryland",
            "massachusetts",
            "michigan",
            "minnesota",
            "mississippi",
            "missouri",
            "montana",
            "nebraska",
            "nevada",
            "new hampshire",
            "new jersey",
            "new mexico",
            "new york",
            "north carolina",
            "north dakota",
            "ohio",
            "oklahoma",
            "oregon",
            "pennsylvania",
            "rhode island",
            "south carolina",
            "south dakota",
            "tennessee",
            "texas",
            "utah",
            "vermont",
            "virginia",
            "washington",
            "west virginia",
            "wisconsin",
            "wyoming",
            "puerto rico",
        ],
        "AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY PR".split(),
    )
)
STATES.update({"guam": "GU", "virgin islands": "VI", "american samoa": "AS", "northern mariana islands": "MP"})
DATE_FIELDS = {"original_created_at", "last_contact_at", "appointment_at", "next_followup_at"}
PRICE_FIELDS = {"asking_price", "estimated_value", "repair_estimate", "bathrooms"}
INT_FIELDS = {"bedrooms", "square_feet", "year_built", "tax_year"}
EXTRA_NUMERIC = {"lot_acres", "tax_market_value", "tax_assessed_value", "estimated_equity", "mortgage_balance"}
EMPTY = {"", "null", "none", "n/a", "na", "nan", "-"}
ALIASES = {
    "phone": "primary_phone",
    "phonenumber": "primary_phone",
    "mobile": "primary_phone",
    "sellername": "full_name",
    "name": "full_name",
    "propertyaddress": "street_address",
    "address": "street_address",
    "propertystreet": "street_address",
    "zip": "zip_code",
    "zipcode": "zip_code",
    "status": "source_status",
    "leadstatus": "source_status",
    "source": "lead_source",
    "manager": "assigned_manager",
    "assignedto": "assigned_manager",
    "createddate": "original_created_at",
    "datecreated": "original_created_at",
    "lastcontact": "last_contact_at",
    "followupdate": "next_followup_at",
    "dnc": "source_do_not_contact",
    "resimpliid": "external_id",
    "leadid": "external_id",
    "emailaddress": "email",
    "bedsbathandsqft": "bed_bath_sqft",
    "bedsbathssqft": "bed_bath_sqft",
    "bedsbathsandsqft": "bed_bath_sqft",
    "beds": "bedrooms",
    "baths": "bathrooms",
    "sqft": "square_feet",
    "squarefootage": "square_feet",
    "mv": "estimated_value",
    "marketvalue": "estimated_value",
    "arv": "estimated_value",
    "sellerfullname": "full_name",
    "ownername": "full_name",
    "sellerphone": "primary_phone",
    "subjectproperty": "street_address",
    "addressline1": "street_address",
    "propertycity": "city",
    "propertystate": "state",
}


def clean(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", str(value)).strip()
    if len(text) > 20000:
        raise ValueError("Value exceeds 20,000 characters")
    return None if text.lower() in EMPTY else text


def normalize_phone(value):
    if not value:
        return None
    try:
        p = phonenumbers.parse(str(value), "US")
        if not phonenumbers.is_valid_number(p):
            raise ValueError("Invalid phone number")
        return phonenumbers.format_number(p, phonenumbers.PhoneNumberFormat.E164)
    except phonenumbers.NumberParseException as exc:
        raise ValueError("Invalid phone number") from exc


EPOCH_DIGITS = re.compile(r"^\d{10}$|^\d{13}$")
# 1973-03-03 .. 2100-01-01 in seconds: outside this range the number is not a timestamp.
EPOCH_FLOOR, EPOCH_CEILING = 100_000_000, 4_102_444_800


def parse_epoch(value):
    """Unix seconds or milliseconds -> aware UTC datetime, or None when it is not one.

    Vendor APIs send absolute instants. An instant has no daylight-saving ambiguity,
    so it can be read without asking the user which side of a clock change it fell on.
    """
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    elif isinstance(value, str) and EPOCH_DIGITS.match(value.strip()):
        number = float(value.strip())
    else:
        return None
    # Thirteen digits is milliseconds; ten is seconds.
    if number > EPOCH_CEILING:
        number /= 1000.0
    if not EPOCH_FLOOR <= number <= EPOCH_CEILING:
        return None
    try:
        return datetime.fromtimestamp(number, timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def parse_datetime(value, zone="America/New_York", date_order="reject"):
    if not value:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        epoch = parse_epoch(value)
        if epoch is not None:
            return epoch
        s = str(value).strip()
        match = re.match(r"^(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})(?:\D|$)", s)
        if match and date_order == "reject" and int(match[1]) <= 12 and int(match[2]) <= 12 and match[1] != match[2]:
            raise ValueError("Ambiguous date: select MDY or DMY explicitly")
        # Require a year. Never fill an unknown year with the current date.
        if not re.search(r"\b\d{4}\b", s):
            raise ValueError("Date must include a four-digit year")
        try:
            dt = parser.parse(s, dayfirst=date_order == "DMY", fuzzy=False, default=datetime(2000, 1, 1))
            alternate = parser.parse(s, dayfirst=date_order == "DMY", fuzzy=False, default=datetime(2000, 12, 28))
            if dt.date() != alternate.date():
                raise ValueError("A complete year, month and day are required; partial dates are not invented")
        except (ValueError, OverflowError) as exc:
            raise ValueError("Invalid date") from exc
    if dt.tzinfo is None:
        zoneinfo = tz.gettz(zone)
        if not tz.datetime_exists(dt, zoneinfo) or tz.datetime_ambiguous(dt, zoneinfo):
            raise ValueError("Ambiguous/nonexistent daylight-saving time: include a UTC offset")
        dt = dt.replace(tzinfo=ZoneInfo(zone))
    return dt.astimezone(timezone.utc)


def money(value):
    if value is None:
        return None
    s = re.sub(r"[$,\s]", "", str(value))
    try:
        d = Decimal(s)
        if not d.is_finite() or d < 0 or d > Decimal("100000000000"):
            raise ValueError("Invalid non-negative numeric amount")
        return float(d)
    except InvalidOperation as exc:
        raise ValueError("Invalid numeric amount") from exc


def normalize_address(data):
    # Conservative local comparison, not USPS validation/geocoding. Unit numbers are preserved.
    street = data.get("street_address")
    if not street:
        return None
    parts = [street, data.get("city"), data.get("state"), data.get("zip_code")]
    return "|".join(re.sub(r"[^a-z0-9#]", "", str(x).lower()) for x in parts if x)


def guess_mapping(headers):
    aliases = {re.sub("[^a-z0-9]", "", k.lower()): k for k in FIELDS}
    aliases.update({re.sub("[^a-z0-9]", "", label.lower()): k for k, label in FIELDS.items()})
    aliases.update(ALIASES)
    return {
        h: aliases[re.sub("[^a-z0-9]", "", h.lower())] for h in headers if re.sub("[^a-z0-9]", "", h.lower()) in aliases
    }


def normalize_record(original, mapping, zone, date_order):
    data, errors, warnings = {}, [], []
    derived = {}
    for source, target in mapping.items():
        if target not in FIELDS:
            errors.append(f"Unknown target field: {target}")
            continue
        try:
            value = clean(original.get(source))
            if value is None:
                data[target] = None
            elif target == "bed_bath_sqft" or (
                target == "bedrooms" and ("&" in value or re.search(r"[A-Za-z]", value))
            ):
                expanded = compound_dimensions(value)
                if not expanded:
                    raise ValueError("Compound property value needs labelled beds/baths/sqft")
                derived.update(expanded)
                warnings.append("Compound property cell expanded; original preserved")
            elif target == "primary_phone":
                data[target] = normalize_phone(value)
            elif target == "email":
                value = value.lower()
                if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
                    raise ValueError("Invalid email")
                data[target] = value
            elif target == "state":
                state = STATES.get(value.lower(), value.upper())
                if state not in STATES.values():
                    raise ValueError("Unknown US state or territory")
                data[target] = state
            elif target == "zip_code":
                if not re.fullmatch(r"\d{1,5}(-\d{4})?", value):
                    raise ValueError("Invalid ZIP code")
                data[target] = value.zfill(5) if "-" not in value else value
            elif target in DATE_FIELDS:
                data[target] = parse_datetime(value, zone, date_order).isoformat()
            elif target in PRICE_FIELDS | INT_FIELDS | EXTRA_NUMERIC:
                number, warning, label = labelled_amount(value)
                if warning:
                    warnings.append(FIELDS[target] + ": " + warning)
                if label:
                    data.setdefault("_value_sources", {})[target] = (
                        label + " labelled source cell; unverified reference"
                    )
                    if target == "asking_price":
                        warnings.append("A vendor-labelled value is not a verified seller asking price")
                        number = None
                if number is not None and target in INT_FIELDS and not number.is_integer():
                    raise ValueError("An integer is required")
                if (
                    number is not None
                    and target in {"year_built", "tax_year"}
                    and not 1600 <= number <= datetime.now().year + 1
                ):
                    raise ValueError("Year is outside the supported explicit range")
                data[target] = (int(number) if target in INT_FIELDS else number) if number is not None else None
            elif target == "source_do_not_contact":
                if value.lower() in {"true", "yes", "y", "1", "dnc", "do not contact"}:
                    data[target] = True
                elif value.lower() in {"false", "no", "n", "0", "clear"}:
                    data[target] = False
                elif value.lower() == "unknown":
                    data[target] = None
                else:
                    raise ValueError("Use yes/no, true/false or unknown for DNC")
            else:
                data[target] = value
        except (ValueError, TypeError) as exc:
            errors.append(f"{FIELDS.get(target, target)}: {exc}")
    for field, value in derived.items():
        if data.get(field) is not None and data[field] != value:
            errors.append("Conflicting compound/separate " + FIELDS[field])
        else:
            data[field] = value
    if data.get("street_address"):
        split = split_full_address(data["street_address"])
        if split:
            for field, value in split.items():
                if field != "street_address" and data.get(field) and str(data[field]).lower() != value.lower():
                    errors.append("Full address conflicts with " + FIELDS[field])
                elif not data.get(field) or field == "street_address":
                    data[field] = value
            warnings.append("Full property address split using explicit city/state/ZIP separators")
    if not data.get("full_name"):
        data["full_name"] = " ".join(x for x in [data.get("first_name"), data.get("last_name")] if x)
    if not data.get("full_name"):
        if data.get("street_address"):
            data["record_kind"] = "property_only"
            warnings.append("Owner identity unknown: property-only prospect, not cleared for drafting")
        else:
            errors.append("A seller name or property address is required")
    if not any(data.get(k) for k in ["primary_phone", "email", "street_address", "external_id"]):
        errors.append("At least a phone, email, property address or external ID is required")
    for field in ["primary_phone", "street_address", "original_created_at"]:
        if not data.get(field):
            warnings.append(f"Missing {FIELDS[field].lower()}")
    if data.get("source_do_not_contact") is None:
        warnings.append("Contact restriction unknown; not cleared for outreach")
    data["normalized_address"] = normalize_address(data)
    return data, errors, warnings


def safe_csv_value(value):
    if value is None:
        return ""
    s = str(value)
    # Formula detection must ignore leading spaces/control characters as spreadsheet software may do.
    if s.lstrip(" \t\r\n").startswith(("=", "+", "-", "@")) or s.startswith(("\t", "\r", "\n")):
        return "'" + s
    return s


def csv_bytes(rows, headers):
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow([safe_csv_value(x) for x in headers])
    for row in rows:
        writer.writerow([safe_csv_value(row.get(k)) for k in headers])
    return ("\ufeff" + output.getvalue()).encode("utf-8")
