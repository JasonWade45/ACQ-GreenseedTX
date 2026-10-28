"""Compliance layer for outbound messaging.

Everything that decides whether a message MAY be sent lives here, so the rule
cannot be bypassed by a UI shortcut: suppression, quiet hours, daily/hourly caps,
warm-up, the automatic opt-out line, inbound STOP handling and the license-area
filter. The message engine (Phase 3) calls ``can_send`` before every send.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from ..models import AppSetting, Lead, Suppression

# ── Defaults ────────────────────────────────────────────────────────────────
DEFAULT_LICENSED_COUNTIES = ["Tarrant, TX"]
DEFAULT_QUIET_START = "09:00"
DEFAULT_QUIET_END = "20:00"
# Monday (0) .. Saturday (5). Sunday (6) is never a send day by default.
DEFAULT_QUIET_DAYS = [0, 1, 2, 3, 4, 5]
DEFAULT_DAILY_CAP = 50
DEFAULT_HOURLY_CAP = 15
DEFAULT_WARMUP_DAYS = 14
OPT_OUT_LINE = "Reply STOP to opt out"

STOP_KEYWORDS = {"stop", "stopall", "unsubscribe", "cancel", "end", "quit"}
SUPPRESS_CANDIDATE_PHRASES = {
    "wrong number",
    "remove me",
    "don't text me",
    "do not text",
    "not interested",
    "stop texting",
    "no more",
    "take me off",
}

STATE_TIMEZONES = {
    "TX": "America/Chicago",
    "OK": "America/Chicago",
    "KS": "America/Chicago",
    "NE": "America/Chicago",
    "IA": "America/Chicago",
    "MN": "America/Chicago",
    "MO": "America/Chicago",
    "AR": "America/Chicago",
    "LA": "America/Chicago",
    "MS": "America/Chicago",
    "AL": "America/Chicago",
    "TN": "America/Chicago",
    "IL": "America/Chicago",
    "WI": "America/Chicago",
    "ND": "America/Chicago",
    "SD": "America/Chicago",
    "CA": "America/Los_Angeles",
    "WA": "America/Los_Angeles",
    "OR": "America/Los_Angeles",
    "NV": "America/Los_Angeles",
    "AZ": "America/Phoenix",
    "UT": "America/Denver",
    "CO": "America/Denver",
    "NM": "America/Denver",
    "MT": "America/Denver",
    "WY": "America/Denver",
    "ID": "America/Boise",
    "NY": "America/New_York",
    "NJ": "America/New_York",
    "PA": "America/New_York",
    "OH": "America/New_York",
    "MI": "America/New_York",
    "IN": "America/Indiana/Indianapolis",
    "GA": "America/New_York",
    "FL": "America/New_York",
    "NC": "America/New_York",
    "SC": "America/New_York",
    "VA": "America/New_York",
    "MD": "America/New_York",
    "MA": "America/New_York",
    "CT": "America/New_York",
    "RI": "America/New_York",
    "NH": "America/New_York",
    "VT": "America/New_York",
    "ME": "America/New_York",
    "DE": "America/New_York",
    "WV": "America/New_York",
    "KY": "America/New_York",
}
DEFAULT_TZ = "America/Chicago"


def _settings(db: Session) -> dict:
    row = db.get(AppSetting, "compliance")
    base = {
        "licensed_counties": list(DEFAULT_LICENSED_COUNTIES),
        "quiet_start": DEFAULT_QUIET_START,
        "quiet_end": DEFAULT_QUIET_END,
        "quiet_days": list(DEFAULT_QUIET_DAYS),
        "daily_cap": DEFAULT_DAILY_CAP,
        "hourly_cap": DEFAULT_HOURLY_CAP,
        "warmup_enabled": True,
        "warmup_days": DEFAULT_WARMUP_DAYS,
        "warmup_start": None,
        "opt_out_line": OPT_OUT_LINE,
    }
    if row and isinstance(row.value, dict):
        base.update({k: v for k, v in row.value.items() if v is not None})
    return base


def save_settings(db: Session, updates: dict) -> dict:
    current = _settings(db)
    current.update({k: v for k, v in (updates or {}).items() if v is not None})
    row = db.get(AppSetting, "compliance")
    if row is None:
        db.add(AppSetting(key="compliance", value=current))
    else:
        row.value = current
    db.commit()
    return current


def normalize_phone(phone: str | None) -> str:
    if not phone:
        return ""
    digits = "".join(ch for ch in str(phone) if ch.isdigit())
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return digits


def lead_state(lead: Lead) -> str | None:
    try:
        if lead.properties:
            return (lead.properties[0].state or "").upper() or None
    except Exception:
        pass
    return None


def lead_timezone(lead: Lead) -> str:
    st = lead_state(lead)
    if st and st in STATE_TIMEZONES:
        return STATE_TIMEZONES[st]
    return DEFAULT_TZ


def is_suppressed(db: Session, phone: str | None) -> bool:
    norm = normalize_phone(phone)
    if not norm:
        return False
    return (
        db.query(Suppression.id)
        .filter(Suppression.phone_normalized == norm)
        .first()
        is not None
    )


def add_suppression(
    db: Session,
    phone: str,
    reason: str,
    source: str,
    lead_id: int | None = None,
    notes: str | None = None,
) -> Suppression:
    norm = normalize_phone(phone)
    existing = (
        db.query(Suppression).filter(Suppression.phone_normalized == norm).first()
        if norm
        else None
    )
    if existing:
        existing.reason = reason
        existing.source = source
        existing.lead_id = lead_id if lead_id is not None else existing.lead_id
        if notes:
            existing.notes = notes
        existing.updated_at = datetime.now(timezone.utc)
        db.commit()
        return existing
    now = datetime.now(timezone.utc)
    row = Suppression(
        phone=phone,
        phone_normalized=norm,
        reason=reason,
        source=source,
        lead_id=lead_id,
        notes=notes,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def remove_suppression(db: Session, phone: str) -> bool:
    norm = normalize_phone(phone)
    row = db.query(Suppression).filter(Suppression.phone_normalized == norm).first()
    if row is None:
        return False
    db.delete(row)
    db.commit()
    return True


def list_suppression(db: Session) -> list[Suppression]:
    return db.query(Suppression).order_by(Suppression.created_at.desc()).all()


def classify_inbound(text: str | None) -> tuple[str, bool, str | None]:
    """Return (classification, is_suppress_candidate, suggested_reason).

    Rule-based detection runs first for STOP and wrong number. Low-confidence
    results are left for the AI classifier / human queue (handled by callers).
    """
    if not text:
        return "OTHER", False, None
    low = text.strip().lower()
    # Exact / leading STOP keywords.
    tokens = low.replace(",", " ").replace(".", " ").split()
    if tokens and tokens[0] in STOP_KEYWORDS:
        return "STOP", True, "stop_keyword"
    if any(k in low for k in STOP_KEYWORDS):
        # keyword anywhere -> treat as stop candidate
        return "STOP", True, "stop_keyword"
    for phrase in SUPPRESS_CANDIDATE_PHRASES:
        if phrase in low:
            if "wrong number" in low:
                return "WRONG_NUMBER", True, "wrong_number"
            if "not interested" in low:
                return "NOT_INTERESTED", True, "not_interested"
            return "NOT_INTERESTED", True, "suppress_candidate"
    if any(w in low for w in ("price", "how much", "offer", "worth")):
        return "WANTS_PRICE", False, None
    if any(w in low for w in ("yes", "interested", "tell me more", "call me", "sure")):
        return "INTERESTED", False, None
    if any(w in low for w in ("later", "not now", "maybe", "next month", "busy")):
        return "NOT_NOW", False, None
    if "?" in low:
        return "QUESTION", False, None
    return "OTHER", False, None


def _parse_hhmm(value: str) -> tuple[int, int]:
    try:
        h, m = value.split(":")
        return int(h), int(m)
    except Exception:
        return 9, 0


def in_quiet_hours(lead: Lead, now_utc: datetime | None = None) -> bool:
    """True when ``now`` (in the recipient's local TZ) is outside send hours."""
    # settings resolved by caller ideally; fall back to defaults here
    cfg = {
        "quiet_start": DEFAULT_QUIET_START,
        "quiet_end": DEFAULT_QUIET_END,
        "quiet_days": list(DEFAULT_QUIET_DAYS),
    }
    now_utc = now_utc or datetime.now(timezone.utc)
    tz = ZoneInfo(lead_timezone(lead))
    local = now_utc.astimezone(tz)
    if local.weekday() not in cfg["quiet_days"]:
        return True
    sh, sm = _parse_hhmm(cfg["quiet_start"])
    eh, em = _parse_hhmm(cfg["quiet_end"])
    start_min = sh * 60 + sm
    end_min = eh * 60 + em
    now_min = local.hour * 60 + local.minute
    if start_min <= end_min:
        return not (start_min <= now_min < end_min)
    # overnight window
    return not (now_min >= start_min or now_min < end_min)


def in_quiet_hours_with_settings(db: Session, lead: Lead, now_utc: datetime | None = None) -> bool:
    cfg = _settings(db)
    now_utc = now_utc or datetime.now(timezone.utc)
    tz = ZoneInfo(lead_timezone(lead))
    local = now_utc.astimezone(tz)
    if local.weekday() not in (cfg.get("quiet_days") or DEFAULT_QUIET_DAYS):
        return True
    sh, sm = _parse_hhmm(cfg.get("quiet_start", DEFAULT_QUIET_START))
    eh, em = _parse_hhmm(cfg.get("quiet_end", DEFAULT_QUIET_END))
    start_min = sh * 60 + sm
    end_min = eh * 60 + em
    now_min = local.hour * 60 + local.minute
    if start_min <= end_min:
        return not (start_min <= now_min < end_min)
    return not (now_min >= start_min or now_min < end_min)


def _count_sends(db: Session, since: datetime) -> int:
    from ..models import AuditLog

    return (
        db.query(AuditLog.id)
        .filter(AuditLog.action == "message_sent", AuditLog.created_at >= since)
        .count()
    )


def under_daily_cap(db: Session, now_utc: datetime | None = None) -> bool:
    _settings(db)
    now_utc = now_utc or datetime.now(timezone.utc)
    cap = effective_daily_cap(db, now_utc)
    since = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
    used = _count_sends(db, since)
    return used < cap


def under_hourly_cap(db: Session, now_utc: datetime | None = None) -> bool:
    cfg = _settings(db)
    cap = int(cfg.get("hourly_cap", DEFAULT_HOURLY_CAP))
    now_utc = now_utc or datetime.now(timezone.utc)
    since = now_utc - timedelta(hours=1)
    used = _count_sends(db, since)
    return used < cap


def effective_daily_cap(db: Session, now_utc: datetime | None = None) -> int:
    cfg = _settings(db)
    base = int(cfg.get("daily_cap", DEFAULT_DAILY_CAP))
    if not cfg.get("warmup_enabled", True):
        return base
    start = cfg.get("warmup_start")
    now_utc = now_utc or datetime.now(timezone.utc)
    if not start:
        # first use: begin warm-up now
        cfg["warmup_start"] = now_utc.date().isoformat()
        save_settings(db, {"warmup_start": cfg["warmup_start"]})
        start = cfg["warmup_start"]
    try:
        start_date = datetime.fromisoformat(start).date()
    except Exception:
        return base
    days = (now_utc.date() - start_date).days
    if days < 0:
        days = 0
    if days >= int(cfg.get("warmup_days", DEFAULT_WARMUP_DAYS)):
        return base
    # ramp: day0 = 20% of cap, linearly up to base at warmup_days
    ramp = max(0.2, (days + 1) / max(1, int(cfg.get("warmup_days", DEFAULT_WARMUP_DAYS))))
    return max(1, int(base * ramp))


def is_in_license(lead: Lead, licensed_counties: list[str] | None = None) -> bool:
    if licensed_counties is None:
        licensed_counties = DEFAULT_LICENSED_COUNTIES
    # Normalize: "Tarrant, TX" style
    normalized = {c.strip().lower() for c in licensed_counties}
    # lead's county: from properties (no county field on Property!). Check source_data.
    county = None
    state = None
    try:
        if lead.properties:
            # Property has no county; fall back to source_data
            pass
    except Exception:
        pass
    sd = getattr(lead, "source_data", None) or {}
    if isinstance(sd, dict):
        nested = sd.get("normalized") if isinstance(sd.get("normalized"), dict) else {}
        county = (
            sd.get("county")
            or sd.get("County")
            or sd.get("property_county")
            or nested.get("county")
            or nested.get("County")
        )
        state = sd.get("state") or sd.get("State") or nested.get("state") or nested.get("State") or (lead_state(lead))
    if not county:
        # try lead properties city/state? county unknown -> not in license (conservative)
        return False
    state = (state or "").upper() or "TX"
    key = f"{county}, {state}".strip().lower()
    # also accept "County, ST" or just county name match
    for lic in normalized:
        if lic == key:
            return True
        if "," in lic:
            lic_county = lic.split(",")[0].strip()
            if lic_county == str(county).strip().lower():
                return True
        else:
            if lic == str(county).strip().lower():
                return True
    return False


def append_opt_out(body: str, template_has_optout: bool = False) -> str:
    if template_has_optout:
        return body
    if OPT_OUT_LINE.lower() in (body or "").lower():
        return body
    body = (body or "").rstrip()
    if body and not body.endswith("\n"):
        body = body + "\n"
    return body + OPT_OUT_LINE


def can_send(db: Session, lead: Lead, now_utc: datetime | None = None) -> tuple[bool, str]:
    """Combined gate. Returns (ok, reason_if_blocked)."""
    now_utc = now_utc or datetime.now(timezone.utc)
    phone = getattr(lead, "primary_phone", None)
    if is_suppressed(db, phone):
        return False, "suppressed"
    if not is_in_license(lead, _settings(db).get("licensed_counties")):
        return False, "out_of_license"
    if in_quiet_hours_with_settings(db, lead, now_utc):
        return False, "quiet_hours"
    if not under_daily_cap(db, now_utc):
        return False, "daily_cap"
    if not under_hourly_cap(db, now_utc):
        return False, "hourly_cap"
    return True, "ok"
