# Issue: ACS_HTTP_PORT and ACS_DATABASE_NAME ignored by server

## Status
open

## Description
When starting the ACS server with environment variables `ACS_HTTP_PORT` and `ACS_DATABASE_NAME` set, the server ignores both values and falls back to defaults (port 7370 and `/topsailai/agent_community.db` for SQLite).

## Reproduction
```bash
cd /TopsailAI/src/topsailai_server/agent_community
rm -f /tmp/acs_test.db /topsailai/agent_community.db
ACS_HTTP_PORT=7371 ACS_DATABASE_DRIVER=sqlite ACS_DATABASE_NAME=/tmp/acs_test.db ACS_NATS_SERVERS= /tmp/acs-server
```

## Expected
- Server listens on port 7371.
- SQLite database file created at `/tmp/acs_test.db`.

## Actual
- Server listens on port 7370.
- SQLite database file created at `/topsailai/agent_community.db`.

## Impact
- Cannot run multiple server instances on different ports without conflicts.
- Cannot use a temporary SQLite database for testing, causing state pollution in `/topsailai/agent_community.db`.

## Root Cause (preliminary)
`internal/config/config.go` relies on Viper's `AutomaticEnv` with `SetEnvKeyReplacer(".", "_")` to map env vars like `ACS_HTTP_PORT` to `server.port`. This mapping appears unreliable for both `IsSet` checks (used for `database.name`) and direct `Unmarshal` (used for `server.port`) in the current Viper configuration.

## Suggested Fix
Explicitly bind critical top-level environment variables with `v.BindEnv` before `Unmarshal`, or read them via `os.Getenv` as a fallback.
