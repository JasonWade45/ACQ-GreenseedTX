"""CRM adapter interface + CSV and REsimpli API implementations (Phase 5)."""

from __future__ import annotations

from abc import ABC, abstractmethod

import csv
import io


class CrmAdapter(ABC):
    @abstractmethod
    def pull_changes(self, since=None) -> list[dict]: ...
    @abstractmethod
    def push_lead(self, lead) -> dict | None: ...
    @abstractmethod
    def push_note(self, lead, text: str) -> bool: ...
    @abstractmethod
    def push_tags(self, lead, tags: list[str]) -> bool: ...
    @abstractmethod
    def list_inbound_messages(self, since=None) -> list[dict]: ...


class CsvAdapter(CrmAdapter):
    """Works with zero API access: import a REsimpli export, export in its format."""

    def __init__(self, export_path: str | None = None):
        self.export_path = export_path

    def pull_changes(self, since=None) -> list[dict]:
        if not self.export_path:
            return []
        try:
            with open(self.export_path, newline="", encoding="utf-8-sig") as f:
                return list(csv.DictReader(f))
        except Exception:
            return []

    def push_lead(self, lead) -> dict | None:
        return None  # CSV adapter never writes; use export_leads_csv instead

    def push_note(self, lead, text: str) -> bool:
        return False

    def push_tags(self, lead, tags: list[str]) -> bool:
        return False

    def list_inbound_messages(self, since=None) -> list[dict]:
        return []

    def export_leads_csv(self, leads) -> str:
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["first_name", "last_name", "phone", "email", "address", "city", "state", "zip", "status", "tags", "notes"])
        for lead in leads:
            addr = ""
            try:
                if lead.properties:
                    addr = lead.properties[0].street_address or ""
            except Exception:
                pass
            w.writerow([lead.first_name, lead.last_name, lead.primary_phone, lead.email, addr, "", "", "", lead.source_status, "", ""])
        return buf.getvalue()


class ApiAdapter(CrmAdapter):
    """REsimpli API adapter — only endpoints confirmed in the official docs."""

    def __init__(self, client):
        self.client = client

    def pull_changes(self, since=None) -> list[dict]:
        # Uses /lead/list + /lead/details (confirmed). Full reconciliation.
        try:
            return self.client.list_leads() or []
        except Exception:
            return []

    def push_lead(self, lead) -> dict | None:
        # /lead/add (confirmed). Requires phone.
        try:
            return self.client.add_lead({"first_name": lead.first_name or "Unknown", "phone": lead.primary_phone})
        except Exception:
            return None

    def push_note(self, lead, text: str) -> bool:
        # No documented note endpoint -> unsupported.
        return False

    def push_tags(self, lead, tags: list[str]) -> bool:
        # No documented tag endpoint -> unsupported.
        return False

    def list_inbound_messages(self, since=None) -> list[dict]:
        # /activityList (confirmed) filtered by inbound.
        try:
            return self.client.list_activities(since=since) or []
        except Exception:
            return []
