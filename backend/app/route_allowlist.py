"""Every route that can reach an external system, declared in one place.

The audit in ``route_audit.py`` catches a route that is unreachable or registered twice.
This file answers a different question: *what can this application still do to the outside
world?* Each entry says which routes may make a request to REsimpli or xAI, and a test
asserts that every registered route under these prefixes is declared here -- so a new
route cannot quietly appear in one of these modules, and the send-shaped check in
``tests/test_routes.py`` keeps failing on anything that looks like outreach.
"""

from .route_audit import all_routes

# Prefixes whose routes must be listed below, one by one.
COVERED_PREFIXES = (
    "/api/leads/{lead_id}/crm",
    "/api/leads/{lead_id}/grok",
    "/api/leads/{lead_id}/notes",
    "/api/leads/{lead_id}/checklists",
    "/api/integrations/resimpli/push",
    "/api/integrations/grok",
    "/api/checklists",
    "/api/grok/suggestions",
    "/api/dashboard/integrations",
)

DECLARED = frozenset(
    {
        # CRM settings and queue: local reads and local writes to app_settings.
        ("GET", "/api/integrations/resimpli/push/settings"),
        ("PATCH", "/api/integrations/resimpli/push/settings"),
        ("GET", "/api/integrations/resimpli/push/accounts"),
        ("GET", "/api/integrations/resimpli/push/queue"),
        # CRM: a read-only duplicate search, one create, one batch create, one manual link.
        ("POST", "/api/leads/{lead_id}/crm/preview"),
        ("POST", "/api/leads/{lead_id}/crm/push"),
        ("POST", "/api/leads/{lead_id}/crm/link"),
        ("POST", "/api/integrations/resimpli/push/batch"),
        # Notes are local: the CRM has no note endpoint.
        ("GET", "/api/leads/{lead_id}/notes"),
        ("POST", "/api/leads/{lead_id}/notes"),
        # Checklists.
        ("GET", "/api/checklists/templates"),
        ("PATCH", "/api/checklists/templates/{key}"),
        ("PATCH", "/api/checklists/items/{item_id}"),
        ("GET", "/api/leads/{lead_id}/checklists"),
        ("POST", "/api/leads/{lead_id}/checklists/items"),
        # AI: status and preview are local; the three POST routes call xAI.
        ("GET", "/api/integrations/grok/status"),
        ("POST", "/api/leads/{lead_id}/grok/preview"),
        ("POST", "/api/leads/{lead_id}/grok/followup"),
        ("POST", "/api/leads/{lead_id}/grok/checklist"),
        ("GET", "/api/leads/{lead_id}/grok/checklist"),
        ("POST", "/api/grok/suggestions/{suggestion_id}"),
        ("POST", "/api/leads/{lead_id}/grok/advice"),
        ("GET", "/api/leads/{lead_id}/grok/advice"),
        # Cards and widgets.
        ("GET", "/api/dashboard/integrations"),
    }
)

# The routes that may actually leave this machine. Everything else here is local.
OUTBOUND = frozenset(
    {
        ("GET", "/api/integrations/resimpli/push/accounts"),
        ("POST", "/api/leads/{lead_id}/crm/preview"),
        ("POST", "/api/leads/{lead_id}/crm/push"),
        ("POST", "/api/integrations/resimpli/push/batch"),
        ("POST", "/api/leads/{lead_id}/grok/preview"),
        ("POST", "/api/leads/{lead_id}/grok/followup"),
        ("POST", "/api/leads/{lead_id}/grok/checklist"),
        ("POST", "/api/leads/{lead_id}/grok/advice"),
    }
)

# What each outbound route is allowed to do, in words a reviewer can check.
SCOPE = {
    ("GET", "/api/integrations/resimpli/push/accounts"): "read three documented lists",
    ("POST", "/api/leads/{lead_id}/crm/preview"): "read-only duplicate search in the CRM",
    ("POST", "/api/leads/{lead_id}/crm/push"): "create one lead",
    ("POST", "/api/integrations/resimpli/push/batch"): "create the selected leads",
    ("POST", "/api/leads/{lead_id}/grok/preview"): "no request: builds the preview locally",
    ("POST", "/api/leads/{lead_id}/grok/followup"): "one AI call, draft only",
    ("POST", "/api/leads/{lead_id}/grok/checklist"): "one AI call, suggestions only",
    ("POST", "/api/leads/{lead_id}/grok/advice"): "one AI call, advice only",
}


def key(route):
    methods = sorted(method.upper() for method in (getattr(route, "methods", None) or set()) if method != "HEAD")
    return (methods[0] if methods else "", getattr(route, "path", ""))


def covered(path: str) -> bool:
    return any(path == prefix or path.startswith(prefix) for prefix in COVERED_PREFIXES)


def undeclared(app) -> list[tuple[str, str]]:
    """Registered routes in a covered prefix that nobody declared here."""
    return sorted({key(route) for route in all_routes(app) if covered(getattr(route, "path", ""))} - DECLARED)


def missing(app) -> list[tuple[str, str]]:
    """Declared routes that are not actually registered."""
    return sorted(DECLARED - {key(route) for route in all_routes(app)})
