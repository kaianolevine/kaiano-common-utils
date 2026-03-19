# Internal API Client

`KaianoApiClient` is a thin HTTP client for calling Kaiano’s internal FastAPI
services.

## Configuration

The client is initialized from environment variables:

- `KAIANO_API_BASE_URL`: Base URL of the target service (e.g. `https://deejay-marvel-api.up.railway.app`)
- `KAIANO_API_OWNER_ID`: Owner ID sent as the `X-Owner-Id` header (falls back to `OWNER_ID` when not set)

## Retry behavior

`KaianoApiClient.post()` retries on `httpx.TransportError` (connection/transport
errors) up to `max_retries` times (default: `3`).

Non-2xx responses raise `KaianoApiError` immediately (no retry).

## Error type

`KaianoApiError` includes:

- `status_code`
- `message`
- `path`

## Clerk JWT TODO

The client currently uses the `X-Owner-Id` header.

TODO: Replace `X-Owner-Id` header with Clerk JWT authentication before
shipping real user traffic.

