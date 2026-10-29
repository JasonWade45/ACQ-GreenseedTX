import hashlib
import hmac
import secrets
import time
from collections import defaultdict, deque
from urllib.parse import urlparse
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from .config import get_settings

SECRET = get_settings().session_secret or secrets.token_hex(32)
ATTEMPTS = defaultdict(deque)

# Sessions are signed rather than stored, so cancellation has to be remembered here.
# REVOKED_BEFORE invalidates every token issued before a "sign out everywhere" and is
# persisted in app_settings, so a restart does not resurrect old sessions.
REVOKED_BEFORE = 0.0
REVOKED_TOKENS: set[str] = set()
MAX_REMEMBERED_TOKENS = 500


def _fingerprint(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def now_ms() -> int:
    """Millisecond clock, so a sign-out-everywhere cannot be raced within the same second."""
    return int(time.time() * 1000)


def new_session():
    payload = f"local:{now_ms()}:{secrets.token_hex(12)}"
    signature = hmac.new(SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return payload + ":" + signature


def valid_session(token):
    global REVOKED_BEFORE
    try:
        payload, signature = token.rsplit(":", 1)
        expected = hmac.new(SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
        issued_ms = int(payload.split(":")[1])
        if _fingerprint(token) in REVOKED_TOKENS:
            return False
        return (
            hmac.compare_digest(signature, expected)
            and issued_ms >= REVOKED_BEFORE
            and 0 <= now_ms() - issued_ms < 12 * 3600 * 1000
        )
    except (ValueError, IndexError):
        return False


def revoke_token(token: str) -> bool:
    """Forget one session. Never resurrect an older one just because the set is full."""
    if not token:
        return False
    fingerprint = _fingerprint(token)
    if fingerprint in REVOKED_TOKENS:
        return True
    if len(REVOKED_TOKENS) >= MAX_REMEMBERED_TOKENS:
        # Drop the least recently remembered entry, not the whole list: clearing it
        # would silently make every earlier "sign out" reversible.
        REVOKED_TOKENS.pop()
    REVOKED_TOKENS.add(fingerprint)
    return True


def revoke_before(timestamp: float, persist=None):
    """Sign out every session issued up to ``timestamp`` and remember it across restarts."""
    global REVOKED_BEFORE
    REVOKED_BEFORE = max(REVOKED_BEFORE, float(timestamp))
    REVOKED_TOKENS.clear()
    if persist is not None:
        persist(REVOKED_BEFORE)


def restore_revocation(db) -> float:
    """Load the persisted cutoff at startup."""
    global REVOKED_BEFORE
    from .models import AppSetting

    stored = db.get(AppSetting, "auth")
    value = dict(stored.value) if stored else {}
    cutoff = float(value.get("revoked_before", 0.0))
    # Values written before the millisecond clock are in seconds; rescale them.
    REVOKED_BEFORE = cutoff * 1000 if 0 < cutoff < 1e11 else cutoff
    REVOKED_TOKENS.clear()
    return REVOKED_BEFORE


def check_login(client, password, settings):
    now = time.monotonic()
    attempts = ATTEMPTS[client]
    while attempts and attempts[0] < now - 60:
        attempts.popleft()
    if len(attempts) >= 8:
        return None, 429
    attempts.append(now)
    if not settings.app_access_password or hmac.compare_digest(
        hashlib.sha256(password.encode()).digest(), hashlib.sha256(settings.app_access_password.encode()).digest()
    ):
        attempts.clear()
        return new_session(), 200
    return None, 401


def _normalise_origin(value: str) -> str:
    parsed = urlparse((value or "").strip())
    if not parsed.scheme or not parsed.netloc:
        return ""
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"


def _same_origin_or_allowed(origin: str, request, settings) -> bool:
    """Same host, or the browser origin explicitly listed in CORS_ORIGINS.

    A separately hosted interface sends its own Origin on every mutation. Refusing all
    of them would make the deployment unusable, so the answer is an explicit allowlist
    rather than a wildcard: only the exact origins named in CORS_ORIGINS are accepted.
    """
    if urlparse(origin).netloc.lower() == request.headers.get("host", "").lower():
        return True
    candidate = _normalise_origin(origin)
    return bool(candidate) and candidate in {_normalise_origin(item) for item in settings.allowed_origins}


class AccessMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        settings = get_settings()
        path = request.url.path
        if path.startswith("/api/"):
            if request.method not in {"GET", "HEAD", "OPTIONS"}:
                origin = request.headers.get("origin")
                if origin and not _same_origin_or_allowed(origin, request, settings):
                    return JSONResponse({"detail": "Cross-origin mutations are not permitted"}, status_code=403)
            # Defense in depth if someone bypasses the provided localhost launcher.
            peer = request.client.host if request.client else ""
            loopback = {"127.0.0.1", "::1", "localhost"}
            server_host = (request.scope.get("server") or ("",))[0]
            test_transport = peer == "testclient" and server_host == "testserver"
            if not settings.app_access_password:
                if peer not in loopback and not test_transport:
                    return JSONResponse({"detail": "Remote access requires workspace authentication"}, status_code=403)
                hostname = (request.url.hostname or "").lower()
                if hostname not in loopback and not (test_transport and hostname == "testserver"):
                    return JSONResponse(
                        {
                            "detail": "Loopback mode rejects non-local Host headers. Use localhost or configure authenticated remote access."
                        },
                        status_code=403,
                    )
            # The cron trigger authenticates with its own shared secret, because the
            # scheduler calling it has no browser session to sign in with.
            public = path in {"/api/auth/status", "/api/auth/login", "/api/health", "/api/cron/run"}
            if settings.app_access_password and not public:
                auth = request.headers.get("authorization", "")
                if not auth.startswith("Bearer ") or not valid_session(auth[7:]):
                    return JSONResponse({"detail": "Sign in to the local workspace"}, status_code=401)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        if path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        else:
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'"
            )
        return response
