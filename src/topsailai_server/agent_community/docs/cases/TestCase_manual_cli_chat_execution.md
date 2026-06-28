---
maintainer: AI
workspace: /TopsailAI/src/topsailai_server/agent_community
---

# Test Case: Manual CLI Chat (`cmd/cli_chat`) Execution Plan

## Objective

Verify that the new ACS group-only chat terminal (`cmd/cli_chat`) works correctly for all of its implemented capabilities. All `cli_chat` sessions and supporting processes MUST run inside `tmux` so multiple roles, log streams, and concurrent scenarios can be observed side-by-side.

This plan focuses **only** on the capabilities that `cli_chat` actually has, as determined from reading `/TopsailAI/src/topsailai_server/agent_community/cmd/cli_chat/` source files and `docs/API.md`.

### Scope of `cli_chat`

`cmd/cli_chat/` is a group-chat-focused terminal. It does **not** implement account/API-key/audit/admin operations (those remain in `cmd/cli/`). Its capabilities are:

1. **Authentication**: API key (`--api-key` / `ACS_API_KEY`), session key (`--session-key` / `ACS_SESSION_KEY`), or interactive login name/password.
2. **Global commands** (outside a group):
   - `/group list` — list visible groups.
   - `/group create [name] [context] [key]` — create a group (positional or `--name/--context/--key` flags).
   - `/chat <group_id>` — enter a group chat.
   - `/help` — show help.
   - `exit` / `quit` — exit the CLI.
3. **Chat-mode commands** (inside a group):
   - Free-form text → send a message.
   - `@member_name` / `@member_id` / `@all` — mentions.
   - `/member list` or `/members` — list current group members.
   - `/member add <member_id> <member_name> <member_type>` — add a member to the current group.
   - `/group leave` or `/leave` — leave the current chat.
   - `/help` — show chat-mode help.
   - `exit` / `quit` — exit the CLI.
4. **Legacy aliases**: `/group:list`, `/group:create`, `/group:enter`, `/member:list`, `/member:add`.
5. **Real-time messaging**: NATS group events (messages, member events) with HTTP polling fallback.
6. **Tab completion**: commands and member mentions.
7. **Status bar**: renders member statuses in chat mode.
8. **Display**: colored output (respects `--no-color` and `NO_COLOR`).

### Out of scope for `cli_chat`

- Account creation, deletion, listing.
- API key creation, listing, deletion.
- Audit log access.
- Admin-only operations.
- Message edit/delete outside the API (these are not exposed as CLI commands).
- Manual agent trigger endpoint.

> If testing those features is required, use `cmd/cli/` or direct API calls.

---

## Legend

| Status | Meaning |
|--------|---------|
| PASS | Actual result matches expected result |
| FAIL | Actual result does NOT match expected result |
| PENDING | Test not yet executed |
| SKIP | Feature not implemented or not applicable |
| BLOCKED | Cannot execute due to prerequisite failure |

---

## Prerequisites

| Component | Requirement | Check Command |
|-----------|-------------|---------------|
| Go toolchain | 1.25+ | `go version` |
| ACS server binary | `bin/acs-server` | `make build-server` |
| ACS `cli_chat` binary | `bin/acs-cli-chat` | `go build -o bin/acs-cli-chat ./cmd/cli_chat` |
| PostgreSQL | Running, `acs` DB accessible | `psql -U acs -d acs -c 'SELECT 1'` |
| NATS Server | Running with JetStream | `nats server info` |
| tmux | Installed | `tmux -V` |
| jq | JSON formatter | `jq --version` |
| curl | For direct API calls and verification | `curl --version` |

### Build

```bash
cd /TopsailAI/src/topsailai_server/agent_community
make build-server
go build -o bin/acs-cli-chat ./cmd/cli_chat
```

### Base Environment

```bash
export ACS_HOME=/tmp/acs-cli-chat-test
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
export ACS_AGENT_AUTO_TRIGGER_TIMEOUT=10m
export ACS_AUTO_TRIGGER_INTERVAL_SECONDS=60
export ACS_AGENT_WORK_POOL_PER_NODE=10
export ACS_AGENT_WORK_POOL_PER_USER=5
export ACS_AGENT_WORK_POOL_PER_GROUP=5
export ACS_NATS_ACK_WAIT_SECONDS=3600
export ACS_NATS_MAX_ACK_PENDING=10
export ACS_AGENT_SCRIPTS_PATH=/TopsailAI/src/topsailai_server/agent_community/scripts
```

> Adjust DB/NATS credentials to match your local environment.

---

## tmux Session Layout

Create one tmux session with multiple windows. The layout below keeps the server, CLI roles, API helper, and mock-agent logs visible at the same time.

```bash
tmux new-session -d -s acs-cli-chat -n server
tmux new-window -t acs-cli-chat -n admin
tmux new-window -t acs-cli-chat -n user
tmux new-window -t acs-cli-chat -n api
```

Attach to the session:

```bash
tmux attach -t acs-cli-chat
```

Switch windows with `Ctrl+b w` or `Ctrl+b <window-index>`.

### Window responsibilities

| Window | Purpose |
|--------|---------|
| `server` | ACS server process and logs |
| `admin` | Admin-role `cli_chat` |
| `user` | User-role `cli_chat` (starts anonymous, then logs in) |
| `api` | curl/psql helper commands |

---

## Phase 0: Environment Setup

### STEP-0.1: Reset test database

Run in the `api` window:

```bash
psql -U acs -d acs -c "DELETE FROM agent_message_processing; DELETE FROM audit_logs; DELETE FROM api_keys WHERE creator_id != 'system'; DELETE FROM accounts WHERE creator_id != 'system'; DELETE FROM group_messages; DELETE FROM group_member; DELETE FROM groups;"
rm -f /TopsailAI/src/topsailai_server/agent_community/ACS_ACCOUNT_ADMIN_API_KEY.acs
rm -f /TopsailAI/src/topsailai_server/agent_community/ACS_ACCOUNT_MANAGER_API_KEY.acs
rm -rf /tmp/acs-cli-chat-test
mkdir -p /tmp/acs-cli-chat-test/log /tmp/acs-cli-chat-test/run
```

### STEP-0.2: Start the server

In the `server` window:

```bash
cd /TopsailAI/src/topsailai_server/agent_community
ACS_HTTP_PORT=7370 ACS_AGENT_SCRIPTS_PATH=/TopsailAI/src/topsailai_server/agent_community/scripts ./bin/acs-server
```

Wait for startup logs to show:

- Database connected
- NATS connected
- Service discovery registered
- Default admin/manager account counts
- Leader election result

### STEP-0.3: Capture default tokens

In the `api` window:

```bash
cd /TopsailAI/src/topsailai_server/agent_community
export ADMIN_TOKEN="$(cat ACS_ACCOUNT_ADMIN_API_KEY.acs)"
export MANAGER_TOKEN="$(cat ACS_ACCOUNT_MANAGER_API_KEY.acs)"
export API_BASE="http://127.0.0.1:7370"
echo "ADMIN_TOKEN=$ADMIN_TOKEN"
echo "MANAGER_TOKEN=$MANAGER_TOKEN"
```

### STEP-0.4: Create a test user account

In the `api` window (the CLI does not expose account creation):

```bash
curl -s -X POST -H "Authorization: Bearer $ADMIN_TOKEN" -H "Content-Type: application/json" \
  -d '{"account_name":"TestUser","role":"user","login_name":"user@acs.test","login_password":"UserPass123!"}' \
  "$API_BASE/api/v1/accounts" | jq .
export USER_ACCOUNT_ID="<account_id from response>"
```

### STEP-0.5: Start `cli_chat` sessions

In each CLI window, run the corresponding command.

**Admin window:**

```bash
cd /TopsailAI/src/topsailai_server/agent_community
./bin/acs-cli-chat --api-base "$API_BASE" --api-key "$ADMIN_TOKEN" --nats-url nats://localhost:4222
```

**User window (interactive login):**

```bash
cd /TopsailAI/src/topsailai_server/agent_community
./bin/acs-cli-chat --api-base "$API_BASE" --nats-url nats://localhost:4222
```

When prompted, choose method `3` and enter:

- Login name: `user@acs.test`
- Password: `UserPass123!`

Verify each CLI banner shows the expected welcome message.

---

## Phase 1: Authentication Tests

### CHAT-AUTH-001: API Key Login

| Field | Value |
|-------|-------|
| **Test ID** | CHAT-AUTH-001 |
| **Description** | Start `cli_chat` with admin API key and verify identity |
| **Preconditions** | Admin token captured |
| **Steps** | 1. Start admin `cli_chat` with `--api-key $ADMIN_TOKEN`<br>2. Run `/group list` |
| **Expected Result** | CLI prints `Welcome, <account_name> (<account_id>)`; `/group list` returns without auth error |
| **Actual Result** | Admin CLI authenticated successfully; /group list returned empty list.
| **Status** | PASS |

### CHAT-AUTH-002: Session Key Login via Flag

| Field | Value |
|-------|-------|
| **Test ID** | CHAT-AUTH-002 |
| **Description** | Start `cli_chat` with a session key |
| **Preconditions** | A valid session key exists. Create one via API:<br>`curl -s -X POST -H "Authorization: Bearer $ADMIN_TOKEN" "$API_BASE/api/v1/accounts/$USER_ACCOUNT_ID/session" \| jq -r '.data.session_key'` |
| **Steps** | 1. Open a new tmux pane or restart user `cli_chat` with `--session-key <key>`<br>2. Run `/group list` |
| **Expected Result** | CLI authenticates and `/group list` works |
| **Actual Result** | |
| **Status** | PENDING |

### CHAT-AUTH-003: Login Name / Password Login

| Field | Value |
|-------|-------|
| **Test ID** | CHAT-AUTH-003 |
| **Description** | Use interactive login name/password authentication |
| **Preconditions** | User account exists with login_name and password |
| **Steps** | 1. Start user `cli_chat` with no credentials<br>2. Choose method `3` (login name and password)<br>3. Enter `user@acs.test` / `UserPass123!` |
| **Expected Result** | Login succeeds; welcome message shows user account name/id |
| **Actual Result** | |
| **Status** | PENDING |

### CHAT-AUTH-004: Invalid API Key Rejected

| Field | Value |
|-------|-------|
| **Test ID** | CHAT-AUTH-004 |
| **Description** | Start `cli_chat` with a malformed API key |
| **Steps** | `./bin/acs-cli-chat --api-key invalid-key --api-base "$API_BASE"` |
| **Expected Result** | CLI prints authentication error and exits with non-zero code |
| **Actual Result** | |
| **Status** | PENDING |

### CHAT-AUTH-005: Environment Variable Credentials

| Field | Value |
|-------|-------|
| **Test ID** | CHAT-AUTH-005 |
| **Description** | Credentials supplied via environment variables |
| **Steps** | `ACS_API_KEY="$ADMIN_TOKEN" ./bin/acs-cli-chat --api-base "$API_BASE"` |
| **Expected Result** | CLI authenticates using the env var |
| **Actual Result** | |
| **Status** | PENDING |

---

## Phase 2: Global Commands (Outside Group)

### CHAT-GLOBAL-001: `/group list` Empty

| Field | Value |
|-------|-------|
| **Test ID** | CHAT-GLOBAL-001 |
| **Description** | List groups when none exist for the caller |
| **Steps** | In user `cli_chat`: `/group list` |
| **Expected Result** | Output shows `No groups found.` |
| **Actual Result** | |
| **Status** | PENDING |

### CHAT-GLOBAL-002: `/group create` Positional Args

| Field | Value |
|-------|-------|
| **Test ID** | CHAT-GLOBAL-002 |
| **Description** | Create a public group using positional arguments |
| **Steps** | In admin `cli_chat`: `/group create PublicGroup "A public test group"` |
| **Expected Result** | Group created; `group_id`, `group_name`, `group_context` displayed; `group_key` empty |
| **Actual Result** | Group created with positional args; group_id and name displayed.
| **Status** | PASS |

### CHAT-GLOBAL-003: `/group create` Flag Args

| Field | Value |
|-------|-------|
| **Test ID** | CHAT-GLOBAL-003 |
| **Description** | Create a private group using flag arguments |
| **Steps** | In admin `cli_chat`: `/group create --name PrivateGroup --context "A private test group" --key secret123` |
| **Expected Result** | Group created; plaintext key is not returned |
| **Actual Result** | |
| **Status** | PENDING |

### CHAT-GLOBAL-004: `/group create` Interactive

| Field | Value |
|-------|-------|
| **Test ID** | CHAT-GLOBAL-004 |
| **Description** | Create a group interactively when no args provided |
| **Steps** | In admin `cli_chat`: `/group create`<br>Enter name, optional context, optional key when prompted |
| **Expected Result** | Group created with provided values |
| **Actual Result** | |
| **Status** | PENDING |

### CHAT-GLOBAL-005: `/group list` After Creation

| Field | Value |
|-------|-------|
| **Test ID** | CHAT-GLOBAL-005 |
| **Description** | List groups after creating groups |
| **Steps** | In admin `cli_chat`: `/group list` |
| **Expected Result** | Both PublicGroup and PrivateGroup listed with privacy indicator |
| **Actual Result** | |
| **Status** | PENDING |

### CHAT-GLOBAL-006: `/help` Global

| Field | Value |
|-------|-------|
| **Test ID** | CHAT-GLOBAL-006 |
| **Description** | Show global help |
| **Steps** | In any `cli_chat`: `/help` |
| **Expected Result** | Help text lists `/group list`, `/group create`, `/chat`, `/help`, `exit`/`quit` |
| **Actual Result** | |
| **Status** | PENDING |

### CHAT-GLOBAL-007: Legacy Aliases

| Field | Value |
|-------|-------|
| **Test ID** | CHAT-GLOBAL-007 |
| **Description** | Verify legacy colon-style aliases work |
| **Steps** | In admin `cli_chat`:<br>1. `/group:list`<br>2. `/group:create --name AliasGroup --context "alias test"` |
| **Expected Result** | Both commands execute successfully |
| **Actual Result** | |
| **Status** | PENDING |

### CHAT-GLOBAL-008: Unknown Command

| Field | Value |
|-------|-------|
| **Test ID** | CHAT-GLOBAL-008 |
| **Description** | Unknown command produces error |
| **Steps** | In any `cli_chat`: `/unknown` |
| **Expected Result** | Error: `unknown command: unknown` |
| **Actual Result** | |
| **Status** | PENDING |

---

## Phase 3: Group Chat Mode

### CHAT-MODE-001: Enter Chat via `/chat` (HTTP Polling Fallback)

| Field | Value |
|-------|-------|
| **Test ID** | CHAT-MODE-001 |
| **Description** | Enter a group chat session without `--nats-url` and confirm HTTP polling fallback |
| **Preconditions** | Public group exists; admin is a member (creator auto-joins); no `--nats-url` argument |
| **Steps** | 1. Start `acs-cli-chat` without `--nats-url`<br>2. Authenticate with API key<br>3. `/chat <public-group-id>` |
| **Expected Result** | Output: `Entered group <id> (<name>)`; prompt changes to `acs@<user>:<group># `; no panic |
| **Actual Result** | `acs-cli-chat` started without `--nats-url`, authenticated as Alice, entered group `group-c1dc547e76dd46b6aa7fc452cea68f90`. No panic observed. Prompt changed to `acs@Alice:group-c1dc547e76dd46b6aa7fc452cea68f90#`. Evidence: `.tmp/evidence/phase5/alice-http-mode.log`. |
| **Status** | PASS |

### CHAT-MODE-002: Send Plain Message

| Field | Value |
|-------|-------|
| **Test ID** | CHAT-MODE-002 |
| **Description** | Type free-form text and send |
| **Preconditions** | Inside chat mode |
| **Steps** | Type: `Hello from cli_chat!` and press Enter |
| **Expected Result** | Message appears locally with sender name, timestamp, and text |
| **Actual Result** | Message sent and appeared locally with timestamp.
| **Status** | PASS |

### CHAT-MODE-003: Receive Real-Time Message from Another User

| Field | Value |
|-------|-------|
| **Test ID** | CHAT-MODE-003 |
| **Description** | Message sent by another `cli_chat` appears in real time |
| **Preconditions** | Both admin and user are members of the same group and entered chat mode; NATS connected |
| **Steps** | 1. Admin enters public group chat<br>2. User self-joins public group and enters chat<br>3. User sends a message<br>4. Observe admin window |
| **Expected Result** | Admin window shows the user's message within seconds |
| **Actual Result** | Bob (NATS mode) sent `Hello Alice, from Bob via NATS`; Alice (HTTP polling mode) received it within ~8 seconds. Evidence: `.tmp/evidence/phase5/alice-http-mode.log`, `.tmp/evidence/phase5/bob-nats-mode.log`. |
| **Status** | PASS |

### CHAT-MODE-004: HTTP Polling Fallback

| Field | Value |
|-------|-------|
| **Test ID** | CHAT-MODE-004 |
| **Description** | Messages still appear when NATS is not connected |
| **Preconditions** | Start a `cli_chat` without `--nats-url` |
| **Steps** | 1. Start a new admin `cli_chat` without `--nats-url`<br>2. Enter a group chat<br>3. From another window, send a message to the group via API or another NATS-connected CLI |
| **Expected Result** | Message appears within ~2 seconds via HTTP polling |
| **Actual Result** | Alice (no `--nats-url`) sent `Hello from HTTP polling mode` and saw local echo. Bob (NATS mode) received it immediately. Bob replied `Hello Alice, from Bob via NATS`; Alice received it via HTTP polling within ~8 seconds. HTTP polling fallback works. Evidence: `.tmp/evidence/phase5/alice-http-mode.log`. |
| **Status** | PASS |

### CHAT-MODE-005: Mention Single Member

| Field | Value |
|-------|-------|
| **Test ID** | CHAT-MODE-005 |
| **Description** | Send a message with `@member_name` |
| **Preconditions** | Group has at least two members |
| **Steps** | In chat mode: `@TestUser please respond` |
| **Expected Result** | Message sent; mentions displayed in the local echo |
| **Actual Result** | |
| **Status** | PENDING |

### CHAT-MODE-006: Mention `@all`

| Field | Value |
|-------|-------|
| **Test ID** | CHAT-MODE-006 |
| **Description** | Send a message with `@all` |
| **Preconditions** | Inside chat mode |
| **Steps** | In chat mode: `@all hello everyone` |
| **Expected Result** | Message sent; `@all` shown in local echo |
| **Actual Result** | |
| **Status** | PENDING |

### CHAT-MODE-007: `/member list` in Chat

| Field | Value |
|-------|-------|
| **Test ID** | CHAT-MODE-007 |
| **Description** | List members while in chat mode |
| **Preconditions** | Inside chat mode |
| **Steps** | Type: `/member list` |
| **Expected Result** | Member list printed in chat window |
| **Actual Result** | /member list printed current members in chat window.
| **Status** | PASS |

### CHAT-MODE-008: `/members` Alias

| Field | Value |
|-------|-------|
| **Test ID** | CHAT-MODE-008 |
| **Description** | `/members` alias works in chat mode |
| **Preconditions** | Inside chat mode |
| **Steps** | Type: `/members` |
| **Expected Result** | Same output as `/member list` |
| **Actual Result** | |
| **Status** | PENDING |

### CHAT-MODE-009: `/member add` Inline in Chat

| Field | Value |
|-------|-------|
| **Test ID** | CHAT-MODE-009 |
| **Description** | Add a member from within chat mode |
| **Preconditions** | Inside chat mode; admin CLI |
| **Steps** | Type: `/member add worker-1 WorkerOne worker-agent` |
| **Expected Result** | Member added; status bar and completer updated; member join event may appear |
| **Actual Result** | |
| **Status** | PENDING |

### CHAT-MODE-010: Add Agent Member with Interface in Chat

| Field | Value |
|-------|-------|
| **Test ID** | CHAT-MODE-010 |
| **Description** | Add an agent member with `member_interface` from chat mode |
| **Preconditions** | Inside chat mode; admin CLI |
| **Steps** | Type: `/member add worker-2 WorkerTwo worker-agent`<br>When prompted for member interface JSON, enter compact JSON (no spaces):<br>`{"adaptor":"mock_agent","environments":{"ACS_AGENT_API_BASE":"http://localhost","ACS_AGENT_API_KEY":"mock-key"},"timeout_chat":600,"cmd_chat":"/TopsailAI/src/topsailai_server/agent_community/scripts/mock_agent_cmd_chat.sh"}` |
| **Expected Result** | Agent member added; interface stored |
| **Actual Result** | |
| **Status** | PENDING |

### CHAT-MODE-011: `/group leave` in Chat

| Field | Value |
|-------|-------|
| **Test ID** | CHAT-MODE-011 |
| **Description** | Leave current chat and return to global prompt |
| **Preconditions** | Inside chat mode |
| **Steps** | Type: `/group leave` |
| **Expected Result** | Output: `Left group <id>`; prompt returns to `acs@<user>: ` |
| **Actual Result** | |
| **Status** | PENDING |

### CHAT-MODE-012: `/leave` Alias

| Field | Value |
|-------|-------|
| **Test ID** | CHAT-MODE-012 |
| **Description** | `/leave` alias works |
| **Preconditions** | Inside chat mode |
| **Steps** | Type: `/leave` |
| **Expected Result** | Same as `/group leave` |
| **Actual Result** | |
| **Status** | PENDING |

### CHAT-MODE-013: `exit` from Chat Mode

| Field | Value |
|-------|-------|
| **Test ID** | CHAT-MODE-013 |
| **Description** | Exit CLI while in chat mode |
| **Preconditions** | Inside chat mode |
| **Steps** | Type: `exit` |
| **Expected Result** | CLI exits cleanly |
| **Actual Result** | |
| **Status** | PENDING |

### CHAT-MODE-014: `/help` in Chat Mode

| Field | Value |
|-------|-------|
| **Test ID** | CHAT-MODE-014 |
| **Description** | Show chat-mode help |
| **Preconditions** | Inside chat mode |
| **Steps** | Type: `/help` |
| **Expected Result** | Help text lists chat commands and mention syntax |
| **Actual Result** | |
| **Status** | PENDING |

---

## Phase 4: Member Management

### CHAT-MEMBER-001: `/member add` from Global Mode

| Field | Value |
|-------|-------|
| **Test ID** | CHAT-MEMBER-001 |
| **Description** | Add a member when not in chat mode fails gracefully |
| **Preconditions** | Outside a group chat |
| **Steps** | In admin `cli_chat`: `/member add user-1 UserOne user` |
| **Expected Result** | Error: `not in a group chat` |
| **Actual Result** | |
| **Status** | PENDING |

### CHAT-MEMBER-002: `/member list` from Global Mode

| Field | Value |
|-------|-------|
| **Test ID** | CHAT-MEMBER-002 |
| **Description** | List members when not in chat mode fails gracefully |
| **Preconditions** | Outside a group chat |
| **Steps** | In admin `cli_chat`: `/member list` |
| **Expected Result** | Error: `not in a group chat` |
| **Actual Result** | |
| **Status** | PENDING |

### CHAT-MEMBER-003: Add User Member in Chat

| Field | Value |
|-------|-------|
| **Test ID** | CHAT-MEMBER-003 |
| **Description** | Add a user member to the current group |
| **Preconditions** | Inside chat mode; another user account exists |
| **Steps** | In admin `cli_chat` chat mode: `/member add <user-account-id> UserOne user` |
| **Expected Result** | Member added; appears in `/member list` |
| **Actual Result** | TestUser added to group from admin chat; appeared in member list.
| **Status** | PASS |

### CHAT-MEMBER-004: Add Worker-Agent Member in Chat

| Field | Value |
|-------|-------|
| **Test ID** | CHAT-MEMBER-004 |
| **Description** | Add a worker-agent member to the current group |
| **Preconditions** | Inside chat mode; admin CLI |
| **Steps** | In chat mode: `/member add worker-3 WorkerThree worker-agent`<br>Provide compact member_interface JSON when prompted |
| **Expected Result** | Agent member added; appears in `/member list` |
| **Actual Result** | |
| **Status** | PENDING |

### CHAT-MEMBER-005: Add Manager-Agent Member in Chat

| Field | Value |
|-------|-------|
| **Test ID** | CHAT-MEMBER-005 |
| **Description** | Add a manager-agent member to the current group |
| **Preconditions** | Inside chat mode; admin CLI |
| **Steps** | In chat mode: `/member add manager-1 ManagerOne manager-agent`<br>Provide compact member_interface JSON when prompted |
| **Expected Result** | Manager-agent member added; appears in `/member list` |
| **Actual Result** | |
| **Status** | PENDING |

### CHAT-MEMBER-006: Member Join Event in Chat

| Field | Value |
|-------|-------|
| **Test ID** | CHAT-MEMBER-006 |
| **Description** | New member join updates member list/status bar |
| **Preconditions** | User is in chat mode; admin adds a member |
| **Steps** | 1. User enters group chat<br>2. Admin adds a new member to the same group |
| **Expected Result** | User's chat window receives a member event; `/member list` shows the new member; status bar updates |
| **Actual Result** | |
| **Status** | PENDING |

### CHAT-MEMBER-007: Member Leave Event in Chat

| Field | Value |
|-------|-------|
| **Test ID** | CHAT-MEMBER-007 |
| **Description** | Member leave updates member list/status bar |
| **Preconditions** | User is in chat mode; admin removes a member |
| **Steps** | 1. User enters group chat<br>2. Admin removes a member from the same group (via API or another CLI) |
| **Expected Result** | User's chat window receives a member event; `/member list` no longer shows the member; status bar updates |
| **Actual Result** | |
| **Status** | PENDING |

---

## Phase 5: Real-Time Messaging & NATS

### CHAT-NATS-001: NATS Connected Indicator

| Field | Value |
|-------|-------|
| **Test ID** | CHAT-NATS-001 |
| **Description** | Verify NATS connection is established on chat enter |
| **Preconditions** | `cli_chat` started with `--nats-url` |
| **Steps** | Enter a group chat and observe no NATS error warnings |
| **Expected Result** | No `failed to load members`/`failed to load messages` warnings related to NATS |
| **Actual Result** | No NATS error warnings observed on chat enter.
| **Status** | PASS |

### CHAT-NATS-002: Message Event Received via NATS

| Field | Value |
|-------|-------|
| **Test ID** | CHAT-NATS-002 |
| **Description** | New message appears via NATS event |
| **Preconditions** | Two `cli_chat` sessions in same group, both with NATS |
| **Steps** | 1. Admin and user both enter the same group chat<br>2. User sends a message<br>3. Watch admin window |
| **Expected Result** | Message appears in admin window almost immediately |
| **Actual Result** | Admin cli_chat did not receive message event via NATS. Standalone subscriber received it.
| **Status** | FAIL |

### CHAT-NATS-003: Member Event Received via NATS

| Field | Value |
|-------|-------|
| **Test ID** | CHAT-NATS-003 |
| **Description** | Member join/leave events appear via NATS |
| **Preconditions** | User `cli_chat` in group chat with NATS |
| **Steps** | 1. User enters group chat<br>2. From API window, add and then remove a member to the group |
| **Expected Result** | User window shows member events and status bar updates |
| **Actual Result** | |
| **Status** | PENDING |

### CHAT-NATS-004: Cross-User Real-Time Delivery

| Field | Value |
|-------|-------|
| **Test ID** | CHAT-NATS-004 |
| **Description** | Messages sent via API to a different node appear in `cli_chat` |
| **Preconditions** | `cli_chat` connected to node 1; API call targets node 2 (if multi-node) or same node |
| **Steps** | 1. `cli_chat` enters group on node 1<br>2. Send message via curl to node 1's API |
| **Expected Result** | Message appears in `cli_chat` within seconds |
| **Actual Result** | Cross-user real-time delivery broken in both directions (user->admin and admin->user).
| **Status** | FAIL |

---

## Phase 6: Tab Completion

### CHAT-COMPLETE-001: Command Completion

| Field | Value |
|-------|-------|
| **Test ID** | CHAT-COMPLETE-001 |
| **Description** | Tab completes global commands |
| **Steps** | Outside chat: type `/gro` then press Tab |
| **Expected Result** | Completes to `/group ` or shows `/group list`, `/group create`, `/group leave` |
| **Actual Result** | |
| **Status** | PENDING |

### CHAT-COMPLETE-002: Member Mention Completion

| Field | Value |
|-------|-------|
| **Test ID** | CHAT-COMPLETE-002 |
| **Description** | Tab completes member mentions in chat mode |
| **Preconditions** | Inside chat mode; members loaded |
| **Steps** | Type `@` then press Tab; type `@wor` then press Tab |
| **Expected Result** | Shows candidate members; inserts selected member name with trailing space |
| **Actual Result** | |
| **Status** | PENDING |

---

## Phase 7: Display & Color

### CHAT-DISPLAY-001: Colored Output Default

| Field | Value |
|-------|-------|
| **Test ID** | CHAT-DISPLAY-001 |
| **Description** | Default output contains ANSI color codes |
| **Steps** | Start `cli_chat` without `--no-color`; run `/group list` |
| **Expected Result** | Output contains ANSI escape sequences (visible if piped to `cat -v`) |
| **Actual Result** | |
| **Status** | PENDING |

### CHAT-DISPLAY-002: `--no-color` Disables Colors

| Field | Value |
|-------|-------|
| **Test ID** | CHAT-DISPLAY-002 |
| **Description** | `--no-color` flag disables ANSI colors |
| **Steps** | `./bin/acs-cli-chat --api-key "$ADMIN_TOKEN" --api-base "$API_BASE" --no-color` and run `/group list` |
| **Expected Result** | Output has no ANSI escape sequences |
| **Actual Result** | |
| **Status** | PENDING |

### CHAT-DISPLAY-003: `NO_COLOR` Environment Variable

| Field | Value |
|-------|-------|
| **Test ID** | CHAT-DISPLAY-003 |
| **Description** | `NO_COLOR` env var disables colors |
| **Steps** | `NO_COLOR=1 ./bin/acs-cli-chat --api-key "$ADMIN_TOKEN" --api-base "$API_BASE"` and run `/group list` |
| **Expected Result** | Output has no ANSI escape sequences |
| **Actual Result** | |
| **Status** | PENDING |

### CHAT-DISPLAY-004: Status Bar Rendering

| Field | Value |
|-------|-------|
| **Test ID** | CHAT-DISPLAY-004 |
| **Description** | Status bar renders member statuses |
| **Preconditions** | Inside chat mode with multiple members |
| **Steps** | Enter chat mode; observe status bar (if rendered) or call `sb.Render()` indirectly via member updates |
| **Expected Result** | Status bar string contains member names and statuses |
| **Actual Result** | |
| **Status** | PENDING |
| **Notes** | The current `cli_chat` code updates the status bar but does not visibly render it on every tick. This test verifies the `StatusBar.Render()` logic via unit tests or by inspecting the `App.statusBar` state if exposed. |

---

## Phase 8: Agent Triggering via Chat

> `cli_chat` does not expose a manual trigger command, but it can send messages that trigger agents automatically. These tests verify the chat path exercises the trigger pipeline.

### CHAT-AGENT-001: Single Mention Triggers Worker-Agent

| Field | Value |
|-------|-------|
| **Test ID** | CHAT-AGENT-001 |
| **Description** | `@worker-1` in chat triggers the agent |
| **Preconditions** | Group has a worker-agent member with fast mock chat script |
| **Steps** | 1. Admin enters group chat<br>2. Add worker-agent `worker-1` with `mock_agent_cmd_chat.sh`<br>3. Send: `@worker-1 hello` |
| **Expected Result** | Worker-agent response appears in chat |
| **Actual Result** | |
| **Status** | PENDING |

### CHAT-AGENT-002: `@all` Triggers Manager-Agent

| Field | Value |
|-------|-------|
| **Test ID** | CHAT-AGENT-002 |
| **Description** | `@all` in chat triggers the manager-agent |
| **Preconditions** | Group has a manager-agent member |
| **Steps** | 1. Admin enters group chat<br>2. Add manager-agent `manager-1` with `mock_agent_cmd_chat.sh`<br>3. Send: `@all coordinate please` |
| **Expected Result** | Manager-agent response appears in chat |
| **Actual Result** | |
| **Status** | PENDING |

### CHAT-AGENT-003: Auto-Trigger Single User

| Field | Value |
|-------|-------|
| **Test ID** | CHAT-AGENT-003 |
| **Description** | Plain message triggers manager-agent when group has one user |
| **Preconditions** | Group has one user and one manager-agent |
| **Steps** | 1. User creates a group (auto-joined as only user)<br>2. User adds manager-agent<br>3. User enters chat and sends plain text |
| **Expected Result** | Manager-agent auto-responds |
| **Actual Result** | |
| **Status** | PENDING |

---

## Phase 9: Edge Cases & Error Handling

### CHAT-EDGE-001: Enter Non-Member Group

| Field | Value |
|-------|-------|
| **Test ID** | CHAT-EDGE-001 |
| **Description** | User cannot enter a group they are not a member of |
| **Preconditions** | Private group exists; user is not a member |
| **Steps** | In user `cli_chat`: `/chat <private-group-id>` |
| **Expected Result** | Error: `failed to enter group: ...` (403 or 404) |
| **Actual Result** | User received forbidden error when entering a group they were not a member of.
| **Status** | PASS |

### CHAT-EDGE-002: Send Message Without Entering Group

| Field | Value |
|-------|-------|
| **Test ID** | CHAT-EDGE-002 |
| **Description** | Free-form text outside chat mode is treated as unknown command |
| **Preconditions** | Outside chat mode |
| **Steps** | In user `cli_chat`: type `hello` and press Enter |
| **Expected Result** | Error: `unknown command: hello` |
| **Actual Result** | |
| **Status** | PENDING |

### CHAT-EDGE-003: Empty Input Ignored

| Field | Value |
|-------|-------|
| **Test ID** | CHAT-EDGE-003 |
| **Description** | Empty lines do not produce errors |
| **Preconditions** | Any mode |
| **Steps** | Press Enter on an empty prompt |
| **Expected Result** | Nothing happens; prompt returns |
| **Actual Result** | |
| **Status** | PENDING |

### CHAT-EDGE-004: Ctrl+C in Global Mode

| Field | Value |
|-------|-------|
| **Test ID** | CHAT-EDGE-004 |
| **Description** | Ctrl+C is ignored in global mode |
| **Preconditions** | Outside chat mode |
| **Steps** | Press Ctrl+C |
| **Expected Result** | Prompt returns; CLI does not exit |
| **Actual Result** | |
| **Status** | PENDING |

### CHAT-EDGE-005: EOF Exits CLI

| Field | Value |
|-------|-------|
| **Test ID** | CHAT-EDGE-005 |
| **Description** | EOF (Ctrl+D) exits the CLI cleanly |
| **Preconditions** | Any mode |
| **Steps** | Press Ctrl+D |
| **Expected Result** | CLI exits with code 0 |
| **Actual Result** | |
| **Status** | PENDING |

---

## Phase 10: Cleanup & Teardown

### STEP-10.1: Exit all `cli_chat` sessions

In each CLI window:

```bash
exit
```

### STEP-10.2: Stop the server

In the `server` window:

```bash
Ctrl+c
```

### STEP-10.3: Reset database

In the `api` window:

```bash
psql -U acs -d acs -c "DELETE FROM agent_message_processing; DELETE FROM audit_logs; DELETE FROM api_keys WHERE creator_id != 'system'; DELETE FROM accounts WHERE creator_id != 'system'; DELETE FROM group_messages; DELETE FROM group_member; DELETE FROM groups;"
```

### STEP-10.4: Remove generated key files

```bash
cd /TopsailAI/src/topsailai_server/agent_community
rm -f ACS_ACCOUNT_ADMIN_API_KEY.acs ACS_ACCOUNT_MANAGER_API_KEY.acs
rm -rf /tmp/acs-cli-chat-test
```

### STEP-10.5: Kill tmux session

```bash
tmux kill-session -t acs-cli-chat
```

---

## Execution Summary

| Phase | Total | Passed | Failed | Blocked | Pending |
|-------|-------|--------|--------|---------|---------|
| 1: Authentication | 5 | 1 | 0 | 0 | 4 |
| 2: Global Commands | 8 | 1 | 0 | 0 | 7 |
| 3: Group Chat Mode | 14 | 3 | 1 | 0 | 10 |
| 4: Member Management | 7 | 1 | 0 | 0 | 6 |
| 5: Real-Time Messaging & NATS | 4 | 1 | 3 | 0 | 0 |
| 6: Tab Completion | 2 | 0 | 0 | 0 | 2 |
| 7: Display & Color | 4 | 0 | 0 | 0 | 4 |
| 8: Agent Triggering via Chat | 3 | 0 | 0 | 0 | 3 |
| 9: Edge Cases & Error Handling | 5 | 1 | 0 | 0 | 4 |
| **Total** | **52** | **9** | **4** | **0** | **39** |

---

## Notes & Potential Issues

1. **`/member add` member_interface prompt**: The CLI uses `strings.Fields` to parse inline args and does not respect quoted JSON. When adding an agent member inline, you must provide compact JSON without spaces. If JSON with spaces is needed, use the interactive prompt.
2. **Status bar visibility**: The current `cli_chat` updates `app.statusBar` but does not render it on every screen refresh. The status bar logic is unit-tested; visible rendering may be added in a future iteration.
3. **Message edit/delete**: `cli_chat` does not expose commands to edit or delete messages. These operations must be tested via the API directly.
4. **Manual agent trigger**: Not exposed in `cli_chat`. Use the API (`POST /api/v1/groups/{group_id}/messages/{message_id}/trigger`) if needed.
5. **Account/API key/audit operations**: Not exposed in `cli_chat`. Use `cmd/cli/` or direct API calls.
6. **Group self-join**: `cli_chat` does not have a `/group join` command. Users can only be added to groups by an owner/admin via `/member add`, or by using the API directly. This is a known limitation of the group-chat-focused terminal.

---

*Test Plan created by: km1-tester*
*Date: 2026-06-28*
