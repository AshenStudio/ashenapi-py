from fastapi import APIRouter, Request, Response
from httpx import AsyncClient, AsyncHTTPTransport, RequestError
from starlette.background import BackgroundTask

router = APIRouter()

# Persistent client with connection pooling
_transport = AsyncHTTPTransport(retries=2)
_proxy_client: AsyncClient | None = None


def _get_client() -> AsyncClient:
    global _proxy_client
    if _proxy_client is None:
        _proxy_client = AsyncClient(
            transport=_transport,
            verify=False,  # pgAdmin uses self-signed cert
            timeout=60.0,
        )
    return _proxy_client


# ── Hop-by-hop headers that must not be forwarded ──────────
_HOP_BY_HOP = frozenset({
    "host", "connection", "transfer-encoding", "keep-alive",
    "proxy-authenticate", "proxy-authorization", "te", "trailer",
    "upgrade",
})


@router.api_route("/pgadmin/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
async def proxy_pgadmin(path: str, request: Request) -> Response:
    return await _proxy_request(path, request)


@router.api_route("/pgadmin", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
async def proxy_pgadmin_root(request: Request) -> Response:
    return await _proxy_request("", request)


async def _proxy_request(path: str, request: Request) -> Response:
    # Forward to pgAdmin's internal HTTP endpoint.
    # APPLICATION_ROOT is set to /pgadmin so pgAdmin generates correct URLs.
    target_url = f"http://ashenapi-pgadmin:80/pgadmin/{path}" if path else "http://ashenapi-pgadmin:80/pgadmin"

    # Build query string
    if request.query_params:
        target_url += f"?{request.query_params}"

    # Read request body
    body = await request.body()

    # Forward headers (strip hop-by-hop)
    headers = {}
    for key, value in request.headers.items():
        if key.lower() not in _HOP_BY_HOP:
            headers[key] = value

    try:
        client = _get_client()
        resp = await client.request(
            method=request.method,
            url=target_url,
            headers=headers,
            content=body,
        )

        # Build response headers (strip hop-by-hop from response too)
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
