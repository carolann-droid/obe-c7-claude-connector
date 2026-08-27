"""
Minimal MCP server exposing a few Commerce7 operations as tools.

This is intentionally thin: it authenticates to Commerce7 with app credentials
stored as environment variables (never sent by the caller), and returns
Commerce7's own JSON responses mostly as-is rather than guessing at field
shapes. Once we've seen real responses via a live call, we can tighten these
up if needed.

Required environment variables (set on the Railway service, not sent by callers):
  C7_APP_ID              - Commerce7 App ID (Basic auth username)
  C7_APP_SECRET          - Commerce7 App Secret (Basic auth password)
  C7_TENANT              - Commerce7 tenant slug, e.g. "obrien-estate"
  CONNECTOR_SHARED_KEY   - shared secret required in the X-Connector-Key header
                           on every request, so this endpoint can't be used by
                           anyone who merely finds the URL.
"""

import os

import httpx
from mcp.server.fastmcp import FastMCP
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

C7_APP_ID = os.environ["C7_APP_ID"]
C7_APP_SECRET = os.environ["C7_APP_SECRET"]
C7_TENANT = os.environ.get("C7_TENANT", "obrien-estate")
SHARED_KEY = os.environ.get("CONNECTOR_SHARED_KEY")
C7_BASE = "https://api.commerce7.com/v1"

mcp = FastMCP("obe-commerce7-connector")


def _client() -> httpx.Client:
    return httpx.Client(
        auth=(C7_APP_ID, C7_APP_SECRET),
        headers={"tenant": C7_TENANT},
        timeout=15,
    )


def _call(method: str, path: str, **kwargs) -> dict:
    try:
        with _client() as c:
            r = c.request(method, f"{C7_BASE}{path}", **kwargs)
        if r.status_code >= 400:
            return {
                "error": True,
                "status": r.status_code,
                "body": r.text[:2000],
            }
        return {"error": False, "status": r.status_code, "data": r.json()}
    except httpx.HTTPError as exc:
        return {"error": True, "status": None, "body": str(exc)}


@mcp.tool()
def lookup_customer_by_email(email: str) -> dict:
    """Look up a Commerce7 customer by email address. Read-only.

    Returns Commerce7's raw customer search response (or an error object).
    """
    return _call("GET", "/customer", params={"q": email})


@mcp.tool()
def get_club_membership(customer_id: str) -> dict:
    """Get a customer's club membership record(s) by their Commerce7 customer id. Read-only."""
    return _call("GET", "/club-membership", params={"customerId": customer_id})


@mcp.tool()
def update_customer(customer_id: str, fields: dict, reason: str) -> dict:
    """Update a Commerce7 customer record.

    `fields` is a partial object of the Commerce7 customer fields to change
    (for example firstName, lastName, phones, emails). Only send the fields
    that actually need to change. `reason` is a short human-readable note on
    why this update is being made, echoed back for logging, not sent to
    Commerce7.
    """
    result = _call("PUT", f"/customer/{customer_id}", json=fields)
    result["reason"] = reason
    return result


app = mcp.streamable_http_app()

if SHARED_KEY:

    class SharedKeyMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            if request.headers.get("x-connector-key") != SHARED_KEY:
                return JSONResponse({"error": "unauthorized"}, status_code=401)
            return await call_next(request)

    app.add_middleware(SharedKeyMiddleware)


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
