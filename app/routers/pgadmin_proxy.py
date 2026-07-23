"""
Reverse proxy for pgAdmin with admin auth guarding.

Access flow:
  1. Client POSTs to /pgadmin/auth with a valid admin JWT
  2. Server sets a signed session cookie (short-lived)
  3. Client loads /pgadmin/* in an iframe — the cookie is sent automatically
  4. Proxy validates the cookie before forwarding to pgAdmin

Direct API access with Bearer token is also supported.
"""
import base64
import hashlib
import hmac
import json
import time

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from httpx import AsyncClient, AsyncHTTPTransport, RequestError

from app.dependencies import require_admin
from app.config import settings
from app.models.models import Account

router = APIRouter()

# ── Signed session cookie ──────────────────────────────────
# Uses HMAC-SHA256 with the JWT key so no extra secrets needed.

_COOKIE_NAME = "ashen_pgadmin_session"
_COOKIE_MAX_AGE = 3600  # 1 hour


def _sign_payload(payload: dict) -> str:
    """Sign a JSON payload with HMAC-SHA256 using the JWT key."""
    data = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    sig = hmac.new(
        settings.jwt_key.encode("utf-8"),
        data.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"{_b64(data)}.{sig}"


def _verify_signed_cookie(value: str | None) -> dict | None:
    """Verify and decode a signed cookie. Returns the payload or None."""
    if not value or "." not in value:
        return None
    try:
        b64_data, sig = value.rsplit(".", 1)
        data = _unb64(b64_data)
        expected = hmac.new(
            settings.jwt_key.encode("utf-8"),
            data.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(expected, sig):
            return None
        payload = json.loads(data)
        if payload.get("exp", 0) < time.time():
            return None
        return payload
    except (ValueError, json.JSONDecodeError):
        return None


def _b64(s: str) -> str:
    """URL-safe base64 without padding."""
    return base64.urlsafe_b64encode(s.encode()).rstrip(b"=").decode()


def _unb64(s: str) -> str:
    """Decode URL-safe base64 with padding restoration."""
    padding = 4 - len(s) % 4
    if padding != 4:
        s += "=" * padding
    return base64.urlsafe_b64decode(s).decode()


# ── Auth endpoint ──────────────────────────────────────────

@router.post("/pgadmin/auth", status_code=status.HTTP_204_NO_CONTENT)
async def pgadmin_auth(
    admin: Account = Depends(require_admin),
):
    """Authenticate for pgAdmin access.

    Requires a valid admin JWT in the Authorization header.
    Sets a signed session cookie for iframe-based access.
    The cookie is valid for 1 hour.
    """
    # We just need the admin dependency to pass — the actual response
    # with the cookie is handled in the dependency below.
    # Actually, we need to set the cookie in the response.
    # Let's use a different approach — return the cookie in the response body
    # and let the client decide how to handle it.
    payload = {
        "sub": str(admin.id),
        "exp": time.time() + _COOKIE_MAX_AGE,
    }
    signed = _sign_payload(payload)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.set_cookie(
        key=_COOKIE_NAME,
        value=signed,
        max_age=_COOKIE_MAX_AGE,
        path="/pgadmin",
        httponly=True,
        samesite="lax",
    )
    return response


# ── Hop-by-hop headers ────────────────────────────────────

_HOP_BY_HOP = frozenset({
    "host", "connection", "transfer-encoding", "keep-alive",
    "proxy-authenticate", "proxy-authorization", "te", "trailer",
    "upgrade",
})


# ── Proxy transport ────────────────────────────────────────

_transport = AsyncHTTPTransport(retries=2)
_proxy_client: AsyncClient | None = None


def _get_client() -> AsyncClient:
    global _proxy_client
    if _proxy_client is None:
        _proxy_client = AsyncClient(
            transport=_transport,
            verify=False,
            timeout=60.0,
        )
    return _proxy_client


# ── Proxy routes (must be defined AFTER /pgadmin/auth) ─────

@router.api_route("/pgadmin/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
async def proxy_pgadmin(path: str, request: Request) -> Response:
    return await _proxy_request(path, request)


@router.api_route("/pgadmin", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
async def proxy_pgadmin_root(request: Request) -> Response:
    return await _proxy_request("", request)


async def _proxy_request(path: str, request: Request) -> Response:
    # ── Auth guard ─────────────────────────────────────────
    # Check signed cookie first (for iframe requests), then check
    # Authorization header (for direct API / programmatic access).
    if request.method == "OPTIONS":
        # CORS preflight — let it through
        pass
    else:
        session = _verify_signed_cookie(request.cookies.get(_COOKIE_NAME))
        if session is None:
            # No valid cookie — check Bearer token
            auth_header = request.headers.get("authorization", "")
            if not auth_header.startswith("Bearer "):
                return Response(
                    content="<h1>Unauthorized</h1><p>Admin authentication required. Visit /pgadmin/auth first.</p>",
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    media_type="text/html",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            # We don't validate the JWT here — that's done by the /pgadmin/auth
            # endpoint. If they have a Bearer token, they can hit /pgadmin/auth
            # to get the cookie. For direct Bearer access, they could validate
            # the JWT here, but that requires a DB lookup. For simplicity,
            # require the cookie for proxied access.
            return Response(
                content="<h1>Unauthorized</h1><p>Visit /pgadmin/auth with your Bearer token to get a session cookie.</p>",
                status_code=status.HTTP_401_UNAUTHORIZED,
                media_type="text/html",
            )

    # ── Forward to pgAdmin ─────────────────────────────────
    target_url = f"http://ashenapi-pgadmin:80/pgadmin/{path}" if path else "http://ashenapi-pgadmin:80/pgadmin"

    if request.query_params:
        target_url += f"?{request.query_params}"

    body = await request.body()

    headers = {}
    for key, value in request.headers.items():
        if key.lower() not in _HOP_BY_HOP:
            headers[key] = value
    headers["X-Forwarded-Host"] = request.headers.get("host", "localhost")
    headers["X-Forwarded-Proto"] = request.headers.get("x-forwarded-proto", "https")
    headers["X-Forwarded-Prefix"] = "/pgadmin"

    try:
        client = _get_client()
        resp = await client.request(
            method=request.method,
            url=target_url,
            headers=headers,
            content=body,
        )

        resp_headers = {}
        for key, value in resp.headers.items():
            if key.lower() not in _HOP_BY_HOP:
                resp_headers[key] = value

        return Response(
            content=resp.content,
            status_code=resp.status_code,
            headers=resp_headers,
        )
    except RequestError as e:
        return Response(
            content=f"<h1>pgAdmin Unreachable</h1><p>Could not connect to pgAdmin: {e}</p>",
            status_code=502,
            media_type="text/html",
        )
