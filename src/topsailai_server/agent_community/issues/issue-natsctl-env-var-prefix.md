---
status: fixed
related_files:
  - cmd/natsctl/main.go
---

# natsctl Uses Non-ACS-Prefixed Environment Variables

## Problem

`cmd/natsctl/main.go` reads environment variables without the `ACS_` prefix that the
project convention and `docs/Environment_Variables.md` require:

- `NATS_URL` (should be `ACS_NATS_SERVERS`)
- `NATS_USER`
- `NATS_PASSWORD`
- `NATS_TOKEN`
- `NATS_CREDS`
- `NATS_NKEY`

`docs/Environment_Variables.md` states:

> All environment variables used by ACS are prefixed with `ACS_`.

and explicitly documents:

> `ACS_NATS_SERVERS` defaults to `nats://localhost:4222`.

## Impact

Users configuring ACS via the documented `ACS_NATS_SERVERS` variable will find that
`natsctl` ignores it and falls back to `nats://localhost:4222` (or `NATS_URL`).

## Fix

Update `cmd/natsctl/main.go` to read `ACS_`-prefixed environment variables as the
primary source, while keeping the legacy `NATS_*` names as a fallback for backward
compatibility.

## Verification

- Unit tests in `cmd/natsctl/main_test.go` verify that `ACS_NATS_SERVERS` is honored,
  that it takes precedence over `NATS_URL`, and that the default URL is applied when
  neither variable is set.
