----
status: fixed
severity: high
component: server/bootstrap
related: issues/done/issue-default-api-key-files-overwrite-existing-accounts.md
----

# Default API key regeneration on follower node invalidates other nodes' token files

## Summary

When multiple ACS server nodes start simultaneously against a shared database and NATS, the node that loses the bootstrap/migration race still acquires the bootstrap lock after the leader releases it. Because the default accounts already exist, the follower calls `ensureTokenFile`, finds the local `.acs` file missing, deletes the system-created API keys that the leader just created, generates new keys, and writes them to its own `.acs` file. The leader's `.acs` file now contains tokens that no longer exist in the database, causing `401 Unauthorized` on the leader node.

This is a regression of the behavior described in `issues/done/issue-default-api-key-files-overwrite-existing-accounts.md`.

## Environment

- Project: AI-Agent Community Server (ACS)
- Workspace: `/TopsailAI/src/topsailai_server/agent_community`
- Build: `make build` (acs-server, acs-cli)
- Database: PostgreSQL (`acs` database)
- NATS: `nats://localhost:4222` with JetStream enabled
- OS: Debian GNU/Linux 13
- Go version: 1.24.4

## Reproduction Steps

1. Clean the database and remove any existing `.acs` files:
   ```bash
   cd /TopsailAI/src/topsailai_server/agent_community
   PGPASSWORD=acs psql -h localhost -p 5432 -U acs -d acs -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public; GRANT ALL ON SCHEMA public TO acs;"
   rm -rf /tmp/acs-node1 /tmp/acs-node2
   mkdir -p /tmp/acs-node1 /tmp/acs-node2
   ```

2. Start two ACS nodes simultaneously against the same DB/NATS, using different working directories and ports:
   ```bash
   cd /tmp/acs-node1 && \
     ACS_HOME=/tmp/acs-node1 \
     ACS_DATABASE_DRIVER=postgres \
     ACS_DATABASE_HOST=localhost \
     ACS_DATABASE_PORT=5432 \
     ACS_DATABASE_USER=acs \
     ACS_DATABASE_PASSWORD=acs \
     ACS_DATABASE_NAME=acs \
     ACS_NATS_SERVERS=nats://localhost:4222 \
     ACS_DISCOVERY_ENABLED=true \
     ACS_HTTP_HOST=127.0.0.1 \
     ACS_HTTP_PORT=7372 \
     /TopsailAI/src/topsailai_server/agent_community/bin/acs-server &

   cd /tmp/acs-node2 && \
     ACS_HOME=/tmp/acs-node2 \
     ACS_DATABASE_DRIVER=postgres \
     ACS_DATABASE_HOST=localhost \
     ACS_DATABASE_PORT=5432 \
     ACS_DATABASE_USER=acs \
     ACS_DATABASE_PASSWORD=acs \
     ACS_DATABASE_NAME=acs \
     ACS_NATS_SERVERS=nats://localhost:4222 \
     ACS_DISCOVERY_ENABLED=true \
     ACS_HTTP_HOST=127.0.0.1 \
     ACS_HTTP_PORT=7373 \
     /TopsailAI/src/topsailai_server/agent_community/bin/acs-server &
   ```

3. Wait for both nodes to finish startup, then inspect the logs and files:
   ```bash
   tail -30 /tmp/acs-node1/server.log
   tail -30 /tmp/acs-node2/server.log
   cat /tmp/acs-node1/ACS_ACCOUNT_ADMIN_API_KEY.acs
   cat /tmp/acs-node2/ACS_ACCOUNT_ADMIN_API_KEY.acs
   PGPASSWORD=acs psql -h localhost -p 5432 -U acs -d acs -c "SELECT api_key_id, role, owner_id FROM api_keys;"
   ```

## Expected Behavior

- Exactly one admin and one manager API key exist in the database.
- Both nodes' `.acs` files contain the same plaintext tokens that exist in the database, OR
- Only the node that created the default accounts writes the `.acs` files, and follower nodes do not regenerate keys or write mismatched files.
- Authentication with either node's `.acs` file succeeds.

## Actual Behavior

- Node 2 (leader) creates the default accounts and writes `.acs` files with keys `ak-ea78...` (admin) and `ak-98b2...` (manager).
- Node 1 (follower) waits for the migration lock, then acquires the bootstrap lock, sees that accounts exist, and calls `ensureTokenFile`.
- `ensureTokenFile` finds the local `.acs` file missing, deletes the system-created API keys, and regenerates new keys `ak-9370...` (admin) and `ak-1a8a...` (manager).
- Node 1 writes the new keys to `/tmp/acs-node1/ACS_ACCOUNT_*.acs`.
- The database now only contains Node 1's keys.
- Authentication with Node 2's `.acs` files fails with `401 Unauthorized`.

## Evidence

Database state after both nodes start:
```text
             api_key_id              |  role   |               owner_id
-------------------------------------+---------+--------------------------------------
 ak-93701f73212d43e3a3f2e713903a2502 | admin   | acc-c1d99b2c85ed406d9e20a77c3ff38c25
 ak-1a8a7c5063444510ab007a85c0906bd6 | manager | acc-4b2c1bc9ffcb4f738c29347e06f6f312
```

Node 1 file content:
```text
ak-93701f73212d43e3a3f2e713903a2502.-cz-rqw7ILL-FaOi0cJLtx9RaaQ7VPvQwahOrlMKvbI
ak-1a8a7c5063444510ab007a85c0906bd6.JKnxFze5m3L0rgOVSWq6UplUZfUIqAtJr_HxFqZx2uE
```

Node 2 file content:
```text
ak-ea78ffa5f81e453a933ae26a3f64795c.Ax3hCyFc8_clSDE_XVHNbOAw5L4uT81hVtfaWzbz3jY
ak-98b276e317db4df09f790272bddf1146.r938HZ9xMCFbYj_UKoPYts0WFGFhcVW2pdK1aPvdge0
```

Authentication results:
```text
Node 1 admin: 200 OK
Node 2 admin: 401 authentication required
Node 1 manager: 200 OK
Node 2 manager: 401 authentication required
```

## Root Cause

In `internal/services/bootstrap.go`, the `ensureDefaultAccount` function checks whether an account with the target role exists. If it does, it calls `ensureTokenFile`, which:
1. Reads the local `.acs` file.
2. If the file is missing or invalid, deletes all system-created API keys for the account.
3. Creates a new API key and writes it to the `.acs` file.

This logic assumes single-node operation. In a multi-node setup, the follower node does not have the leader's `.acs` file, so it always regenerates, deleting the leader's keys and invalidating the leader's file.

## Impact

- Multi-node ACS deployments cannot rely on auto-generated default API key files.
- The leader node's `.acs` files become invalid after a follower starts.
- Manual Test Case 4.8 (Default Account Creation Race Protection) fails.
- Operators following README instructions for multi-node setups will experience authentication failures.

## Suggested Fix

1. Only regenerate API keys and write `.acs` files when the current node actually creates the default account in this bootstrap run.
2. If the account already exists (created by another node), do not delete or regenerate system-created API keys.
3. If the local `.acs` file is missing on a follower node, log a warning that the file cannot be recovered because the keys were created by another node, and skip writing.
4. Consider persisting the plaintext token in a shared location (e.g., NATS KV) or requiring pre-configured `ACS_ACCOUNT_ADMIN_API_KEY`/`ACS_ACCOUNT_MANAGER_API_KEY` for multi-node deployments.

## Workaround

Set `ACS_ACCOUNT_ADMIN_API_KEY` and `ACS_ACCOUNT_MANAGER_API_KEY` to valid pre-created tokens before starting any node in a multi-node deployment. Do not rely on auto-generated key files.

## Related Documentation

- `docs/Environment_Variables.md` — "Account & API Key Configuration"
- `README.md` — "Default Accounts"
- `ORIGIN.md` — "Default Accounts (admin/manager role)"
- `issues/done/issue-default-api-key-files-overwrite-existing-accounts.md`
