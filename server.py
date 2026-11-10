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
from urllib.parse import parse_qs

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.datastructures import Headers
from starlette.responses import JSONResponse

C7_APP_ID = os.environ["C7_APP_ID"]
C7_APP_SECRET = os.environ["C7_APP_SECRET"]
C7_TENANT = os.environ.get("C7_TENANT", "obrien-estate")
SHARED_KEY = os.environ.get("CONNECTOR_SHARED_KEY")
C7_BASE = "https://api.commerce7.com/v1"

# The mcp SDK's StreamableHTTP transport validates the Host header against an
# allow-list (DNS-rebinding protection) that defaults to empty, i.e. it
# rejects every host -- including our own Railway domain -- with
# HTTP 421 "Invalid Host header". Access here is already gated by the
# shared-key check below, so it's safe to turn that extra check off rather
# than hardcode Railway's (occasionally-changing) domain name.
mcp = FastMCP(
    "obe-commerce7-connector",
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)


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
def list_club_memberships(params: dict | None = None) -> dict:
    """List/search Commerce7 club membership records in bulk (not limited to one customer). Read-only.

    `params` is passed through as-is as query parameters to Commerce7's
    GET /club-membership endpoint (for example {"clubId": "...", "page": "1"}).
    Omit `params` (or pass {}) to list without filters. Commerce7 paginates
    results, so check the response shape for a page/cursor field and call
    again with an updated `page` param to get subsequent pages.
    """
    return _call("GET", "/club-membership", params=params or {})


@mcp.tool()
def list_orders(params: dict | None = None) -> dict:
    """List/search Commerce7 orders in bulk (not limited to one customer). Read-only.

    Club shipments/allocations are orders in Commerce7, so this is the way to
    pull allocation history across many members at once instead of looking
    each one up individually. `params` is passed through as-is as query
    parameters to Commerce7's GET /order endpoint -- for example date-range,
    order type/status, or club-related filters. The exact parameter names
    aren't confirmed yet from documentation (Commerce7's docs site couldn't
    be read), so start with an empty/small params dict, inspect the raw
    response and any error body Commerce7 sends back for accepted filter
    names, and iterate from there. Commerce7 paginates results (look for a
    page/cursor field in the response and pass an updated `page` param for
    subsequent pages).
    """
    return _call("GET", "/order", params=params or {})


# --- Event-page reads (products, collections, coupons, promotions) ----------
# Added so Claude can verify the Commerce7 side of an event build instead of
# relying on the user reading fields off the admin by hand. All read-only.
# Endpoint paths follow Commerce7's singular-resource convention (same as
# /customer, /order, /club-membership above). Exact query-param and response
# field names aren't confirmed from docs, so on the first real call inspect
# the raw response (and any error body) and iterate, same as list_orders.


@mcp.tool()
def list_products(params: dict | None = None) -> dict:
    """List/search Commerce7 products, including event-ticket products. Read-only.

    `params` is passed through as-is as query parameters to Commerce7's
    GET /product endpoint -- for example {"q": "pickup party"} to search by
    title. Use this to find an event's ticket product so its prices, web
    status, and slug can be read back (see get_product). Prices are in cents.
    Commerce7 paginates; look for a page/cursor field and pass an updated
    `page` param for more.
    """
    return _call("GET", "/product", params=params or {})


@mcp.tool()
def get_product(product_id: str) -> dict:
    """Get one Commerce7 product by its id. Read-only.

    Returns the product's full record, which for an event ticket includes the
    regular price, any member/club pricing, web status (whether the public
    page is live), the slug (used to build the public obrienestate.com URL),
    and the collections it belongs to. Prices are in cents.
    """
    return _call("GET", f"/product/{product_id}")


@mcp.tool()
def list_collections(params: dict | None = None) -> dict:
    """List/search Commerce7 collections. Read-only.

    `params` is passed through as-is to GET /collection (for example
    {"q": "pickup"}). Use this to find the collection behind an Events-page
    button and read its slug.
    """
    return _call("GET", "/collection", params=params or {})


@mcp.tool()
def get_collection(collection_id: str) -> dict:
    """Get one Commerce7 collection by its id, including the products in it. Read-only.

    Use this to confirm a collection holds the right ticket products and that
    they are available, before an Events-page button points at the
    collection's public page.
    """
    return _call("GET", f"/collection/{collection_id}")


@mcp.tool()
def list_coupons(params: dict | None = None) -> dict:
    """List/search Commerce7 coupons (the Marketing > Coupons area). Read-only.

    `params` is passed through as-is to GET /coupon. Use this to read a
    ticket coupon back after it is set up and confirm its product scope,
    amount, quantity cap, active state, and dates.
    """
    return _call("GET", "/coupon", params=params or {})


@mcp.tool()
def list_promotions(params: dict | None = None) -> dict:
    """List/search Commerce7 promotions. Read-only.

    Commerce7's discount engine is "Promotions," and a per-ticket cap (like a
    "first 2 tickets" deal) may live here rather than on a plain coupon, so
    this is how to see how such a deal is actually built. `params` is passed
    through as-is to GET /promotion.
    """
    return _call("GET", "/promotion", params=params or {})


# --- End event-page reads ---------------------------------------------------


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

@mcp.tool()
def list_reservations(params: dict | None = None) -> dict:
    """List/search Commerce7 reservations. Read-only.

    `params` is passed through as-is as query parameters to Commerce7's
    GET /reservation endpoint. Exact accepted filter names aren't confirmed
    from docs -- start with an empty/small params dict, inspect the raw
    response (and any error body) for accepted names, and iterate, same as
    list_orders. Commerce7 paginates; look for a page/cursor field and pass
    an updated `page` param for more.
    """
    return _call("GET", "/reservation", params=params or {})


@mcp.tool()
def get_reservation(reservation_id: str) -> dict:
    """Get one Commerce7 reservation by its id. Read-only."""
    return _call("GET", f"/reservation/{reservation_id}")


@mcp.tool()
def create_reservation(payload: dict, reason: str) -> dict:
    """Create a Commerce7 reservation, blocking the corresponding calendar time.

    `payload` is sent as-is as the JSON body to Commerce7's POST /reservation
    endpoint -- it must follow Commerce7's reservation shape (reservation
    type/option id, date/time, guest count, customer id, note, etc.). Inspect
    a real response (or error body) on first use and adjust field names if
    Commerce7 rejects something, same as the other write tools here.
    `reason` is a short human-readable note on why this reservation is being
    created, echoed back for logging, not sent to Commerce7.
    """
    result = _call("POST", "/reservation", json=payload)
    result["reason"] = reason
    return result


@mcp.tool()
def update_reservation(reservation_id: str, fields: dict, reason: str) -> dict:
    """Update (including cancel, via a status field) a Commerce7 reservation.

    `fields` is a partial object of the Commerce7 reservation fields to
    change, sent as the JSON body to PUT /reservation/{reservation_id}.
    `reason` is a short human-readable note on why this update is being made,
    echoed back for logging, not sent to Commerce7.
    """
    result = _call("PUT", f"/reservation/{reservation_id}", json=fields)
    result["reason"] = reason
    return result
app = mcp.streamable_http_app()

if SHARED_KEY:

    class SharedKeyASGIMiddleware:
        """Plain ASGI middleware (NOT starlette.middleware.base.BaseHTTPMiddleware).

        BaseHTTPMiddleware buffers/re-wraps the response body, which deadlocks
        or hangs indefinitely against a streaming (SSE) response like the one
        FastMCP's streamable_http_app() returns for MCP requests -- that hang
        is what was causing connector checks to time out (HTTP 499, "client
        has closed the request before the server could send a response").
        A raw ASGI middleware inspects the request and, for authorized
        requests, just calls through to the wrapped app untouched.
        """

        def __init__(self, app):
            self.app = app

        async def __call__(self, scope, receive, send):
            if scope["type"] != "http":
                await self.app(scope, receive, send)
                return

            headers = Headers(scope=scope)
            query = parse_qs(scope.get("query_string", b"").decode())
            got = headers.get("x-connector-key") or (query.get("key", [None])[0])
            if got != SHARED_KEY:
                response = JSONResponse({"error": "unauthorized"}, status_code=401)
                await response(scope, receive, send)
                return

            await self.app(scope, receive, send)

    app = SharedKeyASGIMiddleware(app)


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
