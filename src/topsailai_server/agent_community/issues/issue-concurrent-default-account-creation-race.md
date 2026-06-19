---
status: open
priority: low
component: server/bootstrap
---
# Concurrent default account creation race during multi-node startup

## Symptom
When three ACS server nodes are started simultaneously against a fresh shared database, the server logs contain transient errors such as `login name already exists` during default admin/manager account creation. The final database state is correct (exactly one admin account and one manager account), but the error indicates the NATS KV distributed lock did not fully serialize the creation attempts.

## Expected
Per `ORIGIN.md`, default account creation is guarded by a NATS KV distributed lock (and Service-Leader election). With the lock in place, only the leader should attempt to create default accounts; follower nodes should skip creation silently without attempting an INSERT that conflicts on the unique `login_name` index.

## Actual
- Three nodes booted simultaneously (127.1.0.1, 127.1.0.2, 127.1.0.3) sharing SQLite and NATS.
- Final DB state: exactly 1 admin account and 1 manager account (correct).
- Transient `login name already exists` errors were observed, suggesting multiple nodes attempted the INSERT before the lock or uniqueness constraint resolved the race.

## Impact
- Functional: **None** — no duplicate accounts are created.
- Operational: Noisy startup logs may be misinterpreted as a startup failure.
- Robustness: The system currently relies on the database unique constraint as a backstop rather than preventing the race at the lock layer.

## Root Cause Hypothesis
The distributed lock acquisition and the default-account existence check may form a check-then-act race:
1. Node A acquires lock, sees no admin account, begins creation.
2. Node B fails to acquire lock (or lock is released), then performs its own existence check.
3. Node B sees no account yet and attempts INSERT, which fails when Node A commits.

Alternatively, the lock may be acquired per-role but not cover the entire default-account bootstrap sequence, or the lock TTL/renewal may allow overlap.

## Reproduction Steps
1. Reset database and remove `ACS_ACCOUNT_ADMIN_API_KEY.acs` / `ACS_ACCOUNT_MANAGER_API_KEY.acs`.
2. Start NATS with JetStream.
3. Start three ACS nodes simultaneously against the same DB/NATS:
   ```bash
   ACS_HTTP_PORT=7370 ./bin/acs-server start &
   ACS_HTTP_PORT=7371 ./bin/acs-server start &
   ACS_HTTP_PORT=7372 ./bin/acs-server start &
   ```
4. Inspect logs for `login name already exists` or similar unique-constraint errors.

## Recommendation
Review the default account bootstrap logic to ensure:
1. The existence check and INSERT are atomic with respect to the distributed lock.
2. Followers that fail to acquire the lock skip all account-creation attempts entirely.
3. Any unique-constraint violation during creation is treated as a benign "already created by another node" case and logged at `info`/`debug` rather than `error`.

## Related Documentation
- `ORIGIN.md` — Default Accounts (admin/manager role)
- `docs/Environment_Variables.md` — `ACS_ACCOUNT_ADMIN_API_KEY`, `ACS_ACCOUNT_MANAGER_API_KEY`
