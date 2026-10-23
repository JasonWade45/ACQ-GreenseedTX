"""Field normalization helpers.

Every normalizer returns the normalized value plus any warnings. Original
source values are preserved by callers (import records keep the raw row), so
normalization never silently destroys source data.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

import phonenumbers
from dateutil import parser as date_parser

US_STATES = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR", "california": "CA",
    "colorado": "CO", "connecticut": "CT", "delaware": "DE", "district of columbia": "DC",
    "florida": "FL", "georgia": "GA", "hawaii": "HI", "idaho": "ID", "illinois": "IL",
    "indiana": "IN", "iowa": "IA", "kansas": "KS", "kentucky": "KY", "louisiana": "LA",
    "maine": "ME", "maryland": "MD", "massachusetts": "MA", "michigan": "MI",
    "minnesota": "MN", "mississippi": "MS", "missouri": "MO", "montana": "MT",
    "nebraska": "NE", "nevada": "NV", "new hampshire": "NH", "new jersey": "NJ",
    "new mexico": "NM", "new york": "NY", "north carolina": "NC", "north dakota": "ND",
    "ohio": "OH", "oklahoma": "OK", "oregon": "OR", "pennsylvania": "PA",
    "rhode island": "RI", "south carolina": "SC", "south dakota": "SD", "tennessee": "TN",
    "texas": "TX", "utah": "UT", "vermont": "VT", "virginia": "VA", "washington": "WA",
    "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY",
}
VALID_STATE_ABBREVS = set(US_STATES.values()) | {"PR", "VI", "GU", "AS", "MP", "AA", "AE", "AP"}

STREET_SUFFIXES = {
    "st": "street", "str": "street", "street": "street",
    "ave": "avenue", "av": "avenue", "avenue": "avenue",
    "rd": "road", "road": "road",
    "blvd": "boulevard", "boulevard": "boulevard",
    "dr": "drive", "drive": "drive",
    "ln": "lane", "lane": "lane",
    "ct": "court", "court": "court",
    "pl": "place", "place": "place",
    "cir": "circle", "circle": "circle",
    "pkwy": "parkway", "parkway": "parkway",
    "hwy": "highway", "highway": "highway",
    "ter": "terrace", "terrace": "terrace",
    "way": "way", "trl": "trail", "trail": "trail",
}

_DIRECTIONALS = {"n": "north", "s": "south", "e": "east", "w": "west",
                 "ne": "northeast", "nw": "northwest", "se": "southeast", "sw": "southwest"}


def is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and value.strip() in {"", "nan", "NaN", "None", "null", "-", "--", "n/a", "N/A", "#N/A"}:
        return True
    try:  # pandas / openpyxl NaN
        import math

        if isinstance(value, float) and math.isnan(value):
            return True
    except Exception:  # pragma: no cover
        pass
    return False


def clean_str(value: Any) -> Optional[str]:
    if is_empty(value):
        return None
    text = str(value).strip()
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r"\s+", " ", text)
    return text or None


def normalize_phone(value: Any, region: str = "US") -> tuple[Optional[str], Optional[str], list[str]]:
    """Return (e164_digits, display, warnings). Digits only, 10-digit US form."""
    raw = clean_str(value)
    if not raw:
        return None, None, []
    warnings: list[str] = []
    try:
        parsed = phonenumbers.parse(raw, region)
        if phonenumbers.is_valid_number(parsed):
            e164 = phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
            national = phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.NATIONAL)
            return e164.lstrip("+"), national, warnings
        warnings.append(f"Unparseable phone value '{raw}' kept as-is")
        digits = re.sub(r"\D", "", raw)
        return (digits or None), raw, warnings
    except phonenumbers.NumberParseException:
        digits = re.sub(r"\D", "", raw)
        if len(digits) == 11 and digits.startswith("1"):
            digits = digits[1:]
        if len(digits) == 10:
            return digits, f"({digits[0:3]}) {digits[3:6]}-{digits[6:]}", ["Formatted from digits only"]
        if digits:
            warnings.append(f"Phone '{raw}' is not a 10-digit US number")
            return digits, raw, warnings
        return None, None, warnings


def normalize_email(value: Any) -> Optional[str]:
    raw = clean_str(value)
    if not raw:
        return None
    raw = raw.strip().strip(",").strip(";").lower()
    if "@" not in raw or raw.startswith("@") or raw.endswith("@"):
        return None if "@" not in raw else raw
    return raw


def normalize_state(value: Any) -> tuple[Optional[str], list[str]]:
    raw = clean_str(value)
    if not raw:
        return None, []
    upper = raw.upper()
    if upper in VALID_STATE_ABBREVS:
        return upper, []
    lower = raw.lower()
    if lower in US_STATES:
        return US_STATES[lower], [f"State '{raw}' abbreviated to {US_STATES[lower]}"]
    if len(upper) <= 3 and upper.isalpha():
        return upper, [f"State value '{raw}' used as-is (not a recognised US state)"]
    return None, [f"Could not interpret state value '{raw}'"]


def normalize_name(value: Any) -> Optional[str]:
    raw = clean_str(value)
    if not raw:
        return None
    return raw.title() if raw.isupper() or raw.islower() else raw


def split_full_name(full: Any, first: Any = None, last: Any = None) -> tuple[Optional[str], Optional[str]]:
    f = normalize_name(first)
    last_name = normalize_name(last)
    if f or last_name:
        return f, last_name
    raw = clean_str(full)
    if not raw:
        return None, None
    # drop common suffixes
    raw = re.sub(r"\b(jr|sr|ii|iii|iv|md|phd)\.?\b", "", raw, flags=re.I).strip(" ,")
    parts = raw.split(" ")
    if len(parts) == 1:
        return parts[0], None
    return parts[0], " ".join(parts[1:])


def normalize_money(value: Any) -> tuple[Optional[float], list[str]]:
    raw = value
    if is_empty(raw):
        return None, []
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return float(raw), []
    text = str(raw).strip()
    warnings: list[str] = []
    negative = text.startswith("(") and text.endswith(")")
    text = text.strip("()").replace("$", "").replace(",", "").strip()
    if text.endswith("k") or text.endswith("K"):
        text = text[:-1]
        try:
            return float(text) * (1000 if not negative else -1000), warnings
        except ValueError:
            return None, [f"Could not parse numeric value '{raw}'"]
    try:
        number = float(text)
        return (-number if negative else number), warnings
    except ValueError:
        warnings.append(f"Could not parse numeric value '{raw}'")
        return None, warnings


_AMBIGUOUS = re.compile(r"^(\d{1,2})[\/\-.](\d{1,2})[\/\-.](\d{2,4})$")
_ISOISH = re.compile(r"^(\d{4})[\/\-.](\d{1,2})[\/\-.](\d{1,2})")


def _epoch_to_datetime(value: Any) -> Optional[datetime]:
    """REsimpli sends epoch timestamps (usually milliseconds).

    Returns a naive UTC datetime, or None when the value is not an epoch
    inside 2001-09-09 .. 2096-10-02 (so out-of-range numbers are never
    silently converted into nonsense dates).
    """
    num: Optional[float] = None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        num = float(value)
    elif isinstance(value, str):
        text = value.strip()
        # >= 11 digits: epoch strings in practice are 13-digit milliseconds.
        # 10-digit strings are too easily a phone number to guess.
        if text.isdigit() and len(text) >= 11:
            num = float(text)
    if num is None:
        return None
    if abs(num) >= 1e14:  # microseconds
        num /= 1_000_000
    elif abs(num) >= 1e11:  # milliseconds
        num /= 1000
    if not (1e9 <= num <= 4e9):  # seconds: 2001-09-09 .. 2096-10-02
        return None
    try:
        return datetime.fromtimestamp(num, tz=timezone.utc).replace(tzinfo=None)
    except (OverflowError, OSError, ValueError):
        return None


def parse_date_flexible(value: Any, field_name: str = "date") -> tuple[Optional[date], list[str], bool]:
    """Parse a date, flagging ambiguous DD/MM vs MM/DD forms.

    Returns (date, warnings, was_ambiguous). Ambiguous values default to the
    US convention MM/DD/YYYY and keep a warning so the UI can surface them.
    """
    if is_empty(value):
        return None, [], False
    if isinstance(value, datetime):
        return value.date(), [], False
    if isinstance(value, date):
        return value, [], False
    epoch = _epoch_to_datetime(value)
    if epoch is not None:
        return epoch.date(), [], False
    text = str(value).strip()
    warnings: list[str] = []
    ambiguous = False

    m = _ISOISH.match(text)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3))), warnings, False
        except ValueError:
            warnings.append(f"{field_name}: value '{text}' is not a valid date")
            return None, warnings, False

    m = _AMBIGUOUS.match(text)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        if a > 12 and b <= 12:
            day, month = a, b  # clearly DD/MM
            ambiguous = True
            warnings.append(f"{field_name}: '{text}' looks like DD/MM/YYYY; interpreted as day-first")
        elif b > 12 and a <= 12:
            month, day = a, b  # clearly MM/DD
        elif a <= 12 and b <= 12:
            month, day = a, b  # ambiguous -> US default
            ambiguous = True
            warnings.append(
                f"{field_name}: '{text}' is ambiguous (MM/DD vs DD/MM); assumed MM/DD/YYYY (US)"
            )
        else:
            warnings.append(f"{field_name}: '{text}' is not a valid date")
            return None, warnings, False
        year = int(m.group(3))
        if year < 100:
            year += 2000 if year < 70 else 1900
        try:
            return date(year, month, day), warnings, ambiguous
        except ValueError:
            warnings.append(f"{field_name}: '{text}' is not a valid calendar date")
            return None, warnings, False

    try:
        parsed = date_parser.parse(text, fuzzy=False)
        return parsed.date(), warnings, False
    except (ValueError, OverflowError):
        pass
    try:
        parsed = date_parser.parse(text, fuzzy=True)
        warnings.append(f"{field_name}: '{text}' was interpreted loosely as {parsed.date().isoformat()}")
        return parsed.date(), warnings, True
    except (ValueError, OverflowError):
        warnings.append(f"{field_name}: could not parse date '{text}'")
        return None, warnings, False


def parse_datetime_flexible(
    value: Any, field_name: str = "datetime"
) -> tuple[Optional[datetime], list[str], bool]:
    if is_empty(value):
        return None, [], False
    if isinstance(value, datetime):
        return value.replace(tzinfo=None), [], False
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day), [], False
    epoch = _epoch_to_datetime(value)
    if epoch is not None:
        return epoch, [], False
    text = str(value).strip()
    d, warnings, ambiguous = parse_date_flexible(text, field_name)
    if d and not re.search(r"\d:\d", text):
        return datetime(d.year, d.month, d.day), warnings, ambiguous
    if d is None:
        return None, warnings, ambiguous
    try:
        parsed = date_parser.parse(text)
        return parsed.replace(tzinfo=None), warnings, ambiguous
    except (ValueError, OverflowError):
        warnings.append(f"{field_name}: could not parse time from '{text}'")
        return datetime(d.year, d.month, d.day), warnings, ambiguous


def normalize_address_line(value: Any) -> Optional[str]:
    raw = clean_str(value)
    if not raw:
        return None
    return raw


def address_key(address_line1: Any, city: Any = None, state: Any = None, zip_code: Any = None) -> Optional[str]:
    """Stable key used for duplicate detection."""
    line = clean_str(address_line1)
    if not line:
        return None
    line = line.lower().rstrip(".")
    line = re.sub(r"[.,]", " ", line)
    words = line.split()
    out = []
    for word in words:
        out.append(STREET_SUFFIXES.get(word, _DIRECTIONALS.get(word, word)))
    line = " ".join(out)
    line = re.sub(r"\s+", " ", line).strip()
    city_s = (clean_str(city) or "").lower()
    state_s = (clean_str(state) or "").lower()
    zip_s = re.sub(r"\D", "", clean_str(zip_code) or "")
    if not city_s and not state_s and not zip_s:
        return line or None
    return f"{line}|{city_s}|{state_s}|{zip_s}"


_CSV_FORMULA = re.compile(r"^[\t\r\n=+\-@]")


def csv_safe(value: Any) -> Any:
    """Neutralise spreadsheet formula injection in CSV exports."""
    if value is None:
        return ""
    if isinstance(value, (int, float, bool)):
        return value
    text = str(value)
    if _CSV_FORMULA.match(text):
        return "'" + text
    return text


def to_utc_naive(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is not None:
        return dt.astimezone(tz=None).replace(tzinfo=None) if False else dt.replace(tzinfo=None)
    return dt


def days_between(a: datetime, b: datetime) -> int:
    return abs((b.date() - a.date()).days)


def clamp_age_days(dt: Optional[datetime], now: datetime) -> Optional[int]:
    if dt is None:
        return None
    return max(0, (now.date() - dt.date()).days)


def relative_time_words(dt: Optional[datetime], now: Optional[datetime] = None) -> Optional[str]:
    if dt is None:
        return None
    now = now or datetime.utcnow()
    delta = now - dt
    seconds = delta.total_seconds()
    if seconds < 0:
        ahead = -seconds
        if ahead < 3600:
            return f"in {int(ahead // 60)}m"
        if ahead < 86400:
            return f"in {int(ahead // 3600)}h"
        return f"in {int(ahead // 86400)}d"
    if seconds < 3600:
        return f"{int(seconds // 60)}m ago"
    if seconds < 86400:
        return f"{int(seconds // 3600)}h ago"
    return f"{int(seconds // 86400)}d ago"


def add_days(dt: datetime, days: float) -> datetime:
    return dt + timedelta(days=days)
