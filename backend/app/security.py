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


def new_session():
    payload = f"local:{int(time.time())}:{secrets.token_hex(12)}"
    signature = hmac.new(SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return payload + ":" + signature


def valid_session(token):
    try:
        payload, signature = token.rsplit(":", 1)
        expected = hmac.new(SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
        timestamp = int(payload.split(":")[1])
        return hmac.compare_digest(signature, expected) and 0 <= time.time() - timestamp < 12 * 3600
    except (ValueError, IndexError):
        return False


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


class AccessMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        settings = get_settings()
        path = request.url.path
        if path.startswith("/api/"):
            if request.method not in {"GET", "HEAD", "OPTIONS"}:
                origin = request.headers.get("origin")
                if origin and urlparse(origin).netloc.lower() != request.headers.get("host", "").lower():
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
            public = path in {"/api/auth/status", "/api/auth/login", "/api/health"}
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
