# LocalMind protocol

All API requests that are part of the authenticated worker/admin protocol must include the `X-LocalMind-Protocol` header.

- Header name: `X-LocalMind-Protocol`
- Current value: `1`
- Compatibility behavior: requests with a missing or mismatched version return HTTP 426.

## Pairing

`POST /api/pair`

Request body:

```json
{
  "code": "K7QM-93TX",
  "worker_name": "lab-worker-1"
}
```

Successful response:

```json
{
  "worker_id": "...",
  "worker_token": "...",
  "protocol_version": 1,
  "admin_url": "http://192.168.1.10:8000"
}
```

The pairing code is single-use and expires after 10 minutes. The plaintext worker token is returned only once in the response and stored on the admin side only as a SHA-256 hash.

## Worker heartbeat

`POST /api/worker/heartbeat`

Requires:

- `Authorization: Bearer <worker_token>`
- `X-LocalMind-Protocol: 1`

Accepted fields:

- `cpu_percent`
- `ram_total_mb`
- `ram_available_mb`
- `battery_percent` (optional)
- `battery_charging` (optional)
- `software_version`

The admin server derives the authenticated worker identity from the bearer token and ignores any attempt to change the worker ID from the request body.

## Worker status

`GET /api/worker/status`

Requires a valid bearer token and protocol header. Returns the worker's online state, heartbeat information, and resource metrics.

## Revoke worker

`POST /api/worker/revoke`

Requires an authenticated admin session or bearer admin password and the protocol header. Revoking a worker marks it unusable for future authenticated requests.
