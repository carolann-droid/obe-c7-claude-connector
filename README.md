# O'Brien Estate Commerce7 Connector (test)

A small MCP server that exposes three Commerce7 operations as tools, so Claude
can be connected to it as a custom connector the same way HighLevel is:

- `lookup_customer_by_email(email)` — read-only
- `get_club_membership(customer_id)` — read-only
- `update_customer(customer_id, fields, reason)` — write

## Deploying (Railway)

1. Push this repo to GitHub.
2. In Railway, create a new project from this repo.
3. Set these environment variables on the service:
   - `C7_APP_ID` — the Commerce7 test app's App ID
   - `C7_APP_SECRET` — the Commerce7 test app's App Secret
   - `C7_TENANT` — `obrien-estate`
   - `CONNECTOR_SHARED_KEY` — any random string; this must also be sent as the
     `X-Connector-Key` header when adding this as a Claude custom connector,
     so the endpoint can't be used by anyone who just finds the URL.
4. Generate a public domain for the service.
5. In Claude, add a custom connector pointing at `https://<that-domain>/mcp`,
   with Authentication set to "None" and one additional request header:
   `X-Connector-Key: <the same random string>`.

This is a test/prototype credential set, isolated from O'Brien Estate's
production Commerce7 app.
