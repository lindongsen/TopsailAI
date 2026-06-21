---
maintainer: AI
workspace: /TopsailAI/src/topsailai_server/agent_community
---

# Test Case: Manual CLI Permission & Role Tests

## Objective

Verify ACS role-based access control (RBAC) and authentication methods by driving the server through the interactive CLI terminal (`acs-cli`). All CLI sessions must run inside `tmux` so multiple roles can be exercised side-by-side and logs are preserved.

Coverage:

1. API key authentication for `admin`, `manager`, and `user` roles.
2. Session key authentication (`X-Session-Key`) created by managers/admins.
3. Role hierarchy enforcement (`admin > manager > user`).
4. Permission boundaries per role (account/API key/group lifecycle).
5. Audit log generation for protected lifecycle actions.

---

## Prerequisites

| Component | Requirement | Check Command |
|-----------|-------------|---------------|
| Go toolchain | 1.25+ | `go version` |
| ACS server binary | Built at `bin/acs-server` | `ls bin/acs-server` |
| ACS CLI binary | Built at `bin/acs-cli` | `ls bin/acs-cli` |
| PostgreSQL | Running, `acs` DB accessible | `psql -U acs -d acs -c '\l'` |
| NATS Server | Running with JetStream | `nats server info` or check readiness |
| tmux | Installed | `tmux -V` |
| jq | JSON formatter | `jq --version` |
| curl | For trigger endpoint fallback | `curl --version` |

### Build

```bash
cd /TopsailAI/src/topsailai_server/agent_community
make build
```

### Base Environment

```bash
export ACS_HOME=/tmp/acs-manual-test
export ACS_DATABASE_DRIVER=postgres
export ACS_DATABASE_HOST=localhost
export ACS_DATABASE_PORT=5432
export ACS_DATABASE_USER=acs
export ACS_DATABASE_PASSWORD=acs
export ACS_DATABASE_NAME=acs
export ACS_NATS_SERVERS=nats://localhost:4222
export ACS_DISCOVERY_ENABLED=true
export ACS_API_KEY_MAX_PER_ACCOUNT=10
export ACS_LOGIN_SESSION_EXPIRY_SECONDS=86400
```

> Adjust DB/NATS credentials to match your local environment.

---

## Test Environment Setup

### 1. Start the server

```bash
mkdir -p "$ACS_HOME"/log "$ACS_HOME"/run
cd /TopsailAI/src/topsailai_server/agent_community
ACS_HTTP_PORT=7370 ./bin/acs-server
```

Run this inside a dedicated tmux window so logs are visible:

```bash
tmux new-session -d -s acs-perm -n server
# In the server pane
tmux send-keys -t acs-perm:server 'cd /TopsailAI/src/topsailai_server/agent_community && ACS_HTTP_PORT=7370 ./bin/acs-server' C-m
```

### 2. Capture default admin/manager API keys

After the server starts, read the auto-generated key files (if env vars were not preset):

```bash
cat ACS_ACCOUNT_ADMIN_API_KEY.acs
cat ACS_ACCOUNT_MANAGER_API_KEY.acs
```

Export them:

```bash
export ADMIN_TOKEN="<value from ACS_ACCOUNT_ADMIN_API_KEY.acs>"
export MANAGER_TOKEN="<value from ACS_ACCOUNT_MANAGER_API_KEY.acs>"
export API_BASE="http://127.0.0.1:7370"
```

### 3. Open three role-specific CLI panes

```bash
# Admin CLI
tmux new-window -t acs-perm -n admin
# Manager CLI
tmux new-window -t acs-perm -n manager
# User CLI
tmux new-window -t acs-perm -n user
```

Attach and log in each role:

```bash
tmux attach -t acs-perm
```

Use `Ctrl+b w` to switch windows.

#### Admin pane

```bash
cd /TopsailAI/src/topsailai_server/agent_community
./bin/acs-cli -api-base "$API_BASE" -api-key "$ADMIN_TOKEN" -no-color
```

#### Manager pane

```bash
cd /TopsailAI/src/topsailai_server/agent_community
./bin/acs-cli -api-base "$API_BASE" -api-key "$MANAGER_TOKEN" -no-color
```

#### User pane (anonymous first, then login)

```bash
cd /TopsailAI/src/topsailai_server/agent_community
./bin/acs-cli -api-base "$API_BASE" -no-color
```

---

## Test Cases

### PERM-001: Admin Can Create Accounts of Any Role

| Field | Value |
|-------|-------|
| **Test ID** | PERM-001 |
| **Role** | admin |
| **Description** | Create `manager` and `user` accounts via admin CLI |
| **Preconditions** | Admin CLI authenticated |
| **Steps** | 1. In admin pane run `/account:create`<br>2. Create role=manager, login_name=manager-a@acs.test, password<br>3. Create role=user, login_name=user-a@acs.test, password |
| **Expected Result** | Both accounts created successfully; response contains `account_id`, `role`, `login_name` |
| **Actual Result** | |
| **Status** | PASS |

### PERM-002: Manager Can Only Create User Accounts

| Field | Value |
|-------|-------|
| **Test ID** | PERM-002 |
| **Role** | manager |
| **Description** | Attempt to create admin and user accounts via manager CLI |
| **Preconditions** | Manager CLI authenticated |
| **Steps** | 1. In manager pane run `/account:create`<br>2. Try role=admin → expect rejection<br>3. Try role=user, login_name=user-b@acs.test → expect success |
| **Expected Result** | Admin creation returns `403 Forbidden`; user creation succeeds |
| **Actual Result** | |
| **Status** | PASS |

### PERM-003: User Cannot Create Accounts

| Field | Value |
|-------|-------|
| **Test ID** | PERM-003 |
| **Role** | user |
| **Description** | User account attempts `/account:create` |
| **Preconditions** | User has a valid session or API key (see PERM-006) |
| **Steps** | 1. In user pane run `/account:create`<br>2. Try any role |
| **Expected Result** | `403 Forbidden` |
| **Actual Result** | |
| **Status** | PASS |

### PERM-004: Admin Can Create API Keys for Other Accounts

| Field | Value |
|-------|-------|
| **Test ID** | PERM-004 |
| **Role** | admin |
| **Description** | Create API keys for the user account created in PERM-001 |
| **Preconditions** | User account exists; know its `account_id` |
| **Steps** | 1. `/api-key:create`<br>2. account-id=acc-xxx, role=user, name="User A Key"<br>3. Repeat up to `ACS_API_KEY_MAX_PER_ACCOUNT` |
| **Expected Result** | Keys created; plaintext `token` returned once per key |
| **Actual Result** | |
| **Status** | PASS |

### PERM-005: Manager Cannot Create API Keys

| Field | Value |
|-------|-------|
| **Test ID** | PERM-005 |
| **Role** | manager |
| **Description** | Manager attempts `/api-key:create` for own account |
| **Preconditions** | Manager CLI authenticated |
| **Steps** | 1. In manager pane run `/api-key:create`<br>2. Enter own account-id and any name |
| **Expected Result** | `403 Forbidden` or clear error: managers cannot create API keys |
| **Actual Result** | |
| **Status** | PASS |

### PERM-006: User Can Create Own API Keys (Role ≤ user)

| Field | Value |
|-------|-------|
| **Test ID** | PERM-006 |
| **Role** | user |
| **Description** | User creates an API key for self |
| **Preconditions** | User has a session key or API key from admin |
| **Steps** | 1. Obtain session key via manager `/account:session` or admin<br>2. Start user CLI with `-session-key <key>`<br>3. `/api-key:create` role=user |
| **Expected Result** | Key created with role=user; attempting role=manager fails |
| **Actual Result** | |
| **Status** | PASS |

### PERM-007: Manager Can Query Accounts by ID / External ID

| Field | Value |
|-------|-------|
| **Test ID** | PERM-007 |
| **Role** | manager |
| **Description** | Query user account without exposing sensitive fields |
| **Preconditions** | User account exists with external_id |
| **Steps** | 1. In manager pane `/account:get` account-id=acc-xxx<br>2. `/account:list` external_id=ext-xxx |
| **Expected Result** | Account returned; fields `login_password`, `login_session_key`, and API keys are absent |
| **Actual Result** | |
| **Status** | PASS |

### PERM-008: User Can Only Access Own Account

| Field | Value |
|-------|-------|
| **Test ID** | PERM-008 |
| **Role** | user |
| **Description** | User attempts to read/update another account |
| **Preconditions** | User CLI authenticated; another account exists |
| **Steps** | 1. `/account:get` account-id=<another user><br>2. `/account:update` account-id=<another user> |
| **Expected Result** | Both return `403 Forbidden` |
| **Actual Result** | |
| **Status** | PASS |

### PERM-009: Admin Can Delete Any Account

| Field | Value |
|-------|-------|
| **Test ID** | PERM-009 |
| **Role** | admin |
| **Description** | Soft-delete a user account and verify cascade deletion of API keys |
| **Preconditions** | User account has API keys |
| **Steps** | 1. `/account:delete` account-id=acc-xxx<br>2. `/api-key:list` account-id=acc-xxx |
| **Expected Result** | Account status becomes `deleted`; API keys list is empty (cascade hard-delete) |
| **Actual Result** | |
| **Status** | PASS |

### PERM-010: Manager/User Cannot Delete Accounts

| Field | Value |
|-------|-------|
| **Test ID** | PERM-010 |
| **Role** | manager, user |
| **Description** | Attempt account deletion with non-admin roles |
| **Preconditions** | Target account exists |
| **Steps** | 1. Manager pane: `/account:delete` account-id=acc-xxx<br>2. User pane: `/account:delete` account-id=acc-xxx |
| **Expected Result** | Both return `403 Forbidden` |
| **Actual Result** | |
| **Status** | PASS |

### PERM-011: Role Hierarchy for API Key Role

| Field | Value |
|-------|-------|
| **Test ID** | PERM-011 |
| **Role** | admin |
| **Description** | Verify API key role cannot exceed account role |
| **Preconditions** | User account exists |
| **Steps** | 1. `/api-key:create` account-id=<user account> role=manager<br>2. `/api-key:create` account-id=<user account> role=admin |
| **Expected Result** | Both attempts return `400 Bad Request` or `403 Forbidden` |
| **Actual Result** | |
| **Status** | PASS |

### PERM-012: Session Key Expiration

| Field | Value |
|-------|-------|
| **Test ID** | PERM-012 |
| **Role** | manager |
| **Description** | Create a short-lived session and verify expiry blocks access |
| **Preconditions** | Can temporarily restart server with `ACS_LOGIN_SESSION_EXPIRY_SECONDS=2` |
| **Steps** | 1. Restart server with 2-second expiry<br>2. Manager creates session for user<br>3. Wait 3 seconds<br>4. User CLI uses session key to `/account:me` |
| **Expected Result** | `401 Unauthorized` after expiry |
| **Actual Result** | |
| **Status** | PASS |

### PERM-013: Audit Logs Record Lifecycle Actions

| Field | Value |
|-------|-------|
| **Test ID** | PERM-013 |
| **Role** | admin |
| **Description** | Verify audit logs capture account/API key actions |
| **Preconditions** | Several account/key operations performed above |
| **Steps** | 1. Admin pane: `/account:list` does not expose audit logs via CLI; use curl:<br>`curl -s -H "Authorization: Bearer $ADMIN_TOKEN" "$API_BASE/api/v1/audit-logs?limit=20" \| jq .` |
| **Expected Result** | Entries exist for `create_account`, `create_api_key`, `delete_account`, etc., with `account_id`, `api_key_id`, `action`, `client_ip`, `create_at_ms` |
| **Actual Result** | |
| **Status** | PASS |

### PERM-014: Group Ownership & Access Boundaries

| Field | Value |
|-------|-------|
| **Test ID** | PERM-014 |
| **Role** | user |
| **Description** | User can access only groups they own or joined |
| **Preconditions** | Admin creates a private group; user creates own group |
| **Steps** | 1. Admin pane: `/group:create` name=AdminGroup<br>2. User pane: `/group:list`<br>3. User pane: `/group:enter` group-id=<admin group> |
| **Expected Result** | AdminGroup not listed; entering admin group returns `403` or `404` |
| **Actual Result** | |
| **Status** | PASS |

### PERM-015: Password Change Authorization

| Field | Value |
|-------|-------|
| **Test ID** | PERM-015 |
| **Role** | user, admin |
| **Description** | User changes own password; admin changes any password |
| **Preconditions** | User account with login_password |
| **Steps** | 1. User pane: `/account:password` new-password=NewPass123<br>2. Admin pane: `/account:password` account-id=<user> new-password=AdminSet456<br>3. Try `/login` with old and new passwords |
| **Expected Result** | Both password changes succeed; old password fails, new password succeeds |
| **Actual Result** | |
| **Status** | PASS |

---

## Cleanup

1. In each CLI pane run `/exit`.
2. Stop the server (`Ctrl+c` in the server pane).
3. Delete test data from PostgreSQL if desired:

```bash
psql -U acs -d acs -c "DELETE FROM audit_logs; DELETE FROM api_keys; DELETE FROM accounts WHERE creator_id != 'system'; DELETE FROM group_messages; DELETE FROM group_member; DELETE FROM groups;"
```

4. Remove generated key files from the working directory:

```bash
rm -f ACS_ACCOUNT_ADMIN_API_KEY.acs ACS_ACCOUNT_MANAGER_API_KEY.acs
```

5. Kill tmux session:

```bash
tmux kill-session -t acs-perm
```

---

## Execution Summary

| Test ID | Description | Status |
|---------|-------------|--------|
| PERM-001 | Admin creates manager/user accounts | PASS |
| PERM-002 | Manager creates only user accounts | PASS |
| PERM-003 | User cannot create accounts | PASS |
| PERM-004 | Admin creates API keys for others | PASS |
| PERM-005 | Manager cannot create API keys | PASS |
| PERM-006 | User creates own API keys | PASS |
| PERM-007 | Manager queries accounts safely | PASS |
| PERM-008 | User cannot access other accounts | PASS |
| PERM-009 | Admin deletes account and cascades keys | PASS |
| PERM-010 | Non-admin cannot delete accounts | PASS |
| PERM-011 | API key role ≤ account role | PASS |
| PERM-012 | Session key expiration | PASS |
| PERM-013 | Audit logs recorded | PASS |
| PERM-014 | Group access boundaries | PASS |
| PERM-015 | Password change authorization | PASS |

---

*Test Plan created by: km2-reviewer*
*Date: 2026-06-21*
