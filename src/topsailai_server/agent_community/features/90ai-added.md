---
maintainer: AI
workspace: /TopsailAI/src/topsailai_server/agent_community
---
# Feature: Phase 7 - Testing Suite

## Summary

Complete testing infrastructure for the AI-Agent Community Server (ACS) including Go unit tests, Python integration tests, and a mock AI-agent server.

## Files Added

### Go Unit Tests (5 packages, 59 tests)

1. `internal/trigger/evaluator_test.go` - 11 tests
   - Anti-trigger rules (agent sender, processed_msg_id)
   - Sliding window loop detection
   - Mention extraction (by ID, by name, multiple, @all, non-agent)
   - Trigger decisions (single agent, multiple agents, manager-agent, @all)
   - Auto-trigger conditions (single user, multiple users, timeout)

2. `internal/agent/interface_test.go` - 10 tests
   - JSON parsing (empty, invalid, minimal, full)
   - Duration string parsing
   - Default command values
   - Manager-agent fallback
   - Environment variable building
   - Environment merging

3. `internal/message/context_builder_test.go` - 12 tests
   - Message context formatting
   - Deleted message handling
   - Context building with/without last_read_message_id
   - Nil parameter handling
   - Recent message retrieval
   - Agent response message building
   - System error message building

4. `internal/workpool/semaphore_test.go` - 13 tests
   - Semaphore acquire/release
   - Capacity limits
   - Timeout handling
   - Context cancellation
   - Concurrent access (10 goroutines)
   - Release without acquire
   - Pool acquire/release
   - Pool per-user/per-group isolation
   - Pool stats

5. `internal/api/handlers/group_test.go` - 13 tests
   - Response structure validation
   - Time range parsing (valid, empty, invalid format, negative values, extra parts)
   - Request structure validation

### Python Integration Tests (3 files)

6. `tests/integration/test_api.py` - 5 test classes, 20+ test cases
   - Health endpoints (liveness, readiness, comprehensive health)
   - Group CRUD (create, get, list, update, delete, pagination, sorting, time range)
   - Member operations (join, list, update, leave, agent join)
   - Message operations (create, list, update, delete, mentions, pagination, time range)
   - End-to-end conversation flow

7. `tests/integration/test_nats.py` - 5 test classes, 15+ test cases
   - NATS pub/sub (group events, message events, member events)
   - Pending message flow (mention trigger, @all trigger)
   - Real-time delivery (rapid messages, multiple subscribers)
   - NATS connection and request-reply
   - JetStream streams and consumers

8. `tests/integration/conftest.py` - Pytest fixtures
   - Server URL and API client session
   - Unique ID generator
   - Test group/member/agent fixtures with cleanup
   - Mock agent server lifecycle
   - NATS client connection
   - Database cleanup tracking

### Mock AI-Agent Server

9. `tests/integration/mock_agent_server.py`
   - HTTP server with `/health`, `/status`, `/chat` endpoints
   - Bearer Token authentication
   - Configurable delay and error rate
   - Contextual responses based on input (@all, mentions, help, chat/agent mode)

### Dependencies

10. `tests/integration/requirements.txt`
    - pytest, pytest-asyncio, requests, nats-py, psycopg2-binary

## Test Execution

```bash
# Run all Go unit tests
cd /TopsailAI/src/topsailai_server/agent_community
make test

# Run specific package tests
go test ./internal/trigger/... -v
go test ./internal/agent/... -v
go test ./internal/message/... -v
go test ./internal/workpool/... -v
go test ./internal/api/handlers/... -v

# Run Python integration tests (requires running server)
cd tests/integration
pip install -r requirements.txt
pytest -v --color=no

# Run with coverage
pytest -v --color=no --cov=.
```

## Known Issues

- `internal/lock/distributed_lock_test.go` omitted due to NATS KV interface complexity
  - See `issues/issue-distributed-lock-testability.md` for details and proposed solution

## Build Status

- `go build ./...` - PASS
- `go test ./...` - PASS (59/59 tests)
- Python syntax check - PASS


---

# Feature: ACS CLI Terminal

## Summary

A fully-featured command-line terminal for interacting with the AI-Agent Community Server (ACS). Supports real-time chat via NATS JetStream, interactive command prompts, and comprehensive group/member/message management.

## Build

```bash
cd /TopsailAI/src/topsailai_server/agent_community
go build -o acs-cli ./cmd/cli
```

## Files Added

1. `cmd/cli/main.go` - Entry point, flag parsing, main readline loop, yellow PS1 prompt
2. `cmd/cli/display.go` - ANSI color support, time formatting (`YYYY-MM-DDTHH:MM:SS`), message/event rendering
3. `cmd/cli/api.go` - HTTP API client with response envelope parsing
4. `cmd/cli/nats.go` - NATS JetStream subscription and HTTP polling fallback (2s interval)
5. `cmd/cli/interactive.go` - Step-by-step readline prompts with Ctrl+C cancellation
6. `cmd/cli/chat.go` - Chat window mode with real-time message input/output
7. `cmd/cli/commands.go` - All command handlers and dispatch table

### Go Unit Tests (4 files, 20+ tests)

8. `cmd/cli/display_test.go` - Color enable/disable, time formatting, PS1 rendering
9. `cmd/cli/api_test.go` - Response envelope parsing, error handling
10. `cmd/cli/commands_test.go` - Command parsing, inline args, alias resolution
11. `cmd/cli/chat_test.go` - Chat mode input handling, command detection

## Available Commands

### Group Management
- `/group:list` - List all groups with details
- `/group:create` - Create a new group (interactive)
- `/group:enter {group_id}` - Enter a group chat
- `/group:update {group_id}` - Update group info (interactive)
- `/group:delete {group_id}` - Delete a group

### Member Management
- `/member:add {group_id}` - Add a member to a group (interactive)
- `/member:remove {group_id} {member_id}` - Remove a member
- `/member:update {group_id} {member_id}` - Update member info (interactive)
- `/member:list {group_id}` - List group members

### Message Management
- `/message:edit {group_id} {message_id}` - Edit a message (interactive)
- `/message:delete {group_id} {message_id}` - Delete (recall) a message

### General
- `/help` or `help` - Show available commands
- `/exit`, `exit`, `quit` - Exit the terminal

### Chat Mode Commands (inside `/group:enter`)
- `/exit` or `exit` - Leave chat and return to normal mode
- `/members` - Show group members
- `/help` - Show chat help
- Any other text - Sent as a message to the group

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `ACS_SERVER_API_BASE` | ACS server API base URL | `http://localhost:7370` |
| `ACS_NATS_SERVERS` | NATS server URLs | `nats://localhost:4222` |
| `ACS_CLI_MEMBER_ID` | Default member ID for CLI user | (none) |
| `ACS_CLI_MEMBER_NAME` | Default member name for CLI user | (none) |
| `NO_COLOR` | Disable ANSI colors when set | (none) |

## CLI Flags

| Flag | Description |
|------|-------------|
| `-api-base` | ACS server API base URL |
| `-nats-url` | NATS server URL |
| `-member-id` | Member ID for CLI user |
| `-member-name` | Member name for CLI user |
| `-no-color` | Disable ANSI colors |

## Chat Mode Features

- **Real-time messaging**: Messages delivered instantly via NATS JetStream
- **HTTP fallback**: Automatically polls every 2 seconds when NATS is unavailable
- **Message display**: Shows sender name, timestamp (`YYYY-MM-DDTHH:MM:SS`), and content
- **System events**: Displays member join/leave notifications
- **Multi-byte support**: Full UTF-8 support for Chinese, Emoji, etc. via `github.com/chzyer/readline`

## Interactive Mode

All management commands support interactive mode:
- Type the command without arguments (e.g., `/group:create`)
- The terminal prompts step-by-step for each required parameter
- Press **Ctrl+C** or **Enter** without typing to cancel
- Inline arguments execute in non-interactive mode for scripting compatibility

## PS1 Prompt

- **Normal mode**: `acs@{userName}: ` (yellow)
- **Chat mode**: `acs@{userName}:{groupId}# ` (yellow)

## Dependencies Added

- `github.com/chzyer/readline v1.5.1` - Terminal input handling with history and line editing

## Build Status

- `go build ./cmd/cli/...` - PASS
- `go test ./cmd/cli/...` - PASS (all tests pass)


---

# Feature: topsailai_agent_cmd Scripts

## Summary

Implemented three Python executable scripts that serve as adaptor commands for the AI-Agent Community Server (ACS). These scripts translate ACS environment variables into calls to existing CLI tools (`topsailai_send_message` and `topsailai_llm_chat`).

## Files Added

1. `scripts/topsailai_agent_cmd_check_health.py`
   - Checks agent health via `topsailai_send_message` with `TOPSAILAI_MESSAGE="/health"`
   - Maps `ACS_AGENT_API_BASE` -> `TOPSAILAI_AGENT_DAEMON_API_BASE`
   - Maps `ACS_AGENT_API_KEY` -> `TOPSAILAI_AGENT_DAEMON_API_KEY`
   - Maps `ACS_AGENT_API_AUTH` -> `TOPSAILAI_AGENT_DAEMON_AUTH_STYLE`
   - Passes through stdout/stderr and exit code

2. `scripts/topsailai_agent_cmd_check_status.py`
   - Checks agent session status via `topsailai_send_message` with `TOPSAILAI_MESSAGE="/status"`
   - Sets `TOPSAILAI_SESSION_ID` from `ACS_GROUP_ID`
   - Same API base/key/auth mapping as health check
   - Passes through stdout/stderr and exit code

3. `scripts/topsailai_agent_cmd_chat.py`
   - Handles chat message dispatch with complex logic:
     - When `ACS_GROUP_CONTEXT` exists and session not found, initializes session with assistant role message
     - When `ACS_AGENT_MODE=chat` and `ACS_AGENT_TYPE=manager-agent`, calls `topsailai_llm_chat`
     - When `ACS_AGENT_MODE=chat` and non-manager agent, appends direct-answer instruction and calls `topsailai_send_message`
     - Default agent mode calls `topsailai_send_message` directly
   - Maps `ACS_AGENT_TIMEOUT` -> `MAX_WAIT_TIME`
   - Passes through stdout/stderr and exit code

## Build Status

- `python3 -m py_compile` on all three scripts - PASS
- All scripts are executable (`chmod +x`)

## Fixes (2026-06-12)

### 1. Missing Agent Environment Variables
- **Files**: `internal/agent/interface.go`, `internal/config/config.go`, `internal/nats/consumer.go`
- **Changes**:
  - Added `AgentPrompt` field to `config.AgentConfig` with default `""`
  - Extended `BuildChatEnv()` signature to accept `agentPrompt`, `groupContext`, `mentionsJSON`, `triggerType`
  - `consumer.go` now passes all 4 missing env vars when calling `BuildChatEnv()`
  - Added assertions in `interface_test.go` for `ACS_AGENT_PROMPT`, `ACS_GROUP_CONTEXT`, `ACS_MESSAGE_MENTIONS`, `ACS_MESSAGE_TRIGGER_TYPE`

### 2. Message Append for Multiple Agents Without Manager
- **Files**: `internal/trigger/evaluator.go`, `internal/nats/consumer.go`
- **Changes**:
  - `evaluator.go` already set `MessageAppend` on `AgentTarget` for multiple agents without manager
  - `ParseTriggerFromNATS()` now parses `message_append` field
  - `consumer.go` now appends `target.MessageAppend` to `contextText` before sending to agent

### 3. Manager-Agent Error Fallback
- **File**: `internal/nats/consumer.go`
- **Changes**:
  - `sendSystemError()` already creates a system-level error message when no manager-agent exists
  - Uses `MemberID: "acs-system"`, `MemberName: "System"`, `MemberType: MemberTypeManagerAgent`
  - Ensures error messages are always recorded, even in groups without a manager-agent

### 4. Sliding Window Test Quality
- **File**: `internal/trigger/evaluator_test.go`
- **Changes**:
  - Added `makeMember("mgr1", "Manager", models.MemberTypeManagerAgent)` to `TestEvaluateSlidingWindow`
  - Test now properly exercises the sliding window anti-loop logic (would trigger manager-agent if not for the window)

### 5. Build Fix
- **File**: `cmd/server/main.go`
- **Changes**:
  - Updated `nats.NewConsumer()` call to pass `cfg` as the 5th argument


---

# Feature: NATS Service Discovery by Micro-Framework (Service-Leader)

## Summary

Implemented NATS-based service discovery and Service-Leader election for the AI-Agent Community Server (ACS). Each service instance registers itself to a NATS KV bucket with a unique UUID. All instances can discover each other, and the instance with the smallest `id` is elected as the `Service-Leader`.

## Files Added

1. `internal/discovery/discovery.go`
   - `ServiceInfo` struct with `id`, `name`, `address`, `port`, `version`, `started_at_ms`
   - `Discovery` struct managing registration, heartbeat, deregistration, and leader election
   - `New()` creates the NATS KV bucket (or opens existing) and initializes self info with UUID
   - `Register()` publishes self info to KV and starts background heartbeat loop
   - `Deregister()` stops heartbeat and removes self from KV
   - `Discover()` fetches all registered services from KV
   - `IsLeader()` returns true if local instance has the smallest ID
   - `LeaderInfo()` returns the `ServiceInfo` of the current leader
   - `SelfInfo()` returns the local instance's registration info
   - Heartbeat interval and TTL are configurable

2. `internal/discovery/discovery_test.go`
   - 8 unit tests using embedded NATS server with JetStream
   - `TestNewDiscovery` - validates struct initialization
   - `TestDiscovery_RegisterAndDeregister` - full register/deregister lifecycle
   - `TestDiscovery_Discover` - multi-instance discovery
   - `TestDiscovery_IsLeader` - leader election with 2 instances
   - `TestDiscovery_LeaderInfo` - leader info retrieval
   - `TestDiscovery_DiscoverEmptyBucket` - empty bucket handling
   - `TestDiscovery_DoubleRegister` - idempotent protection
   - `TestDiscovery_SelfInfo` - self info correctness

## Files Modified

3. `internal/config/config.go`
   - Added `DiscoveryConfig` struct with `Enabled`, `ServiceName`, `BucketName`, `Heartbeat`, `TTL`
   - Added defaults: `ACS_DISCOVERY_ENABLED=true`, `ACS_DISCOVERY_SERVICE_NAME=acs`, `ACS_DISCOVERY_BUCKET_NAME=acs_service_discovery`, `ACS_DISCOVERY_HEARTBEAT=30s`, `ACS_DISCOVERY_TTL=120s`
   - Added `GetListenAddress()` helper on `ServerConfig`

4. `cmd/server/main.go`
   - Added discovery registration after NATS client initialization (step 12.6)
   - Added deregistration on graceful shutdown via defer
   - Discovery is conditional on `cfg.Discovery.Enabled`

5. `internal/api/router.go`
   - Added `GET /discovery/services` endpoint
   - Added `GET /health/leader` endpoint

6. `internal/api/handlers/health.go`
   - Added `DiscoveryServices` handler for `GET /discovery/services`
   - Added `LeaderStatus` handler for `GET /health/leader`
   - Added `DiscoveryServicesResponse` and `LeaderStatusResponse` structs
   - `HealthHandler` now accepts optional `*discovery.Discovery`

7. `docs/Environment_Variables.md`
   - Added "Service Discovery Configuration" section documenting all `ACS_DISCOVERY_*` variables
   - Added discovery variables to the example environment file

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/discovery/services` | List all registered services from NATS KV |
| `GET` | `/health/leader` | Check if this instance is the current Service-Leader |

### Example Responses

**GET /discovery/services**
```json
{
  "services": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "name": "acs",
      "address": "0.0.0.0",
      "port": 7370,
      "version": "1.0.0",
      "started_at_ms": 1781516703000
    }
  ],
  "count": 1
}
```

**GET /health/leader**
```json
{
  "is_leader": true,
  "self": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "name": "acs",
    "address": "0.0.0.0",
    "port": 7370,
    "version": "1.0.0",
    "started_at_ms": 1781516703000
  },
  "leader": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "name": "acs",
    "address": "0.0.0.0",
    "port": 7370,
    "version": "1.0.0",
    "started_at_ms": 1781516703000
  },
  "timestamp": 1781516703000
}
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ACS_DISCOVERY_ENABLED` | `true` | Enable service discovery |
| `ACS_DISCOVERY_SERVICE_NAME` | `acs` | Service name in registry |
| `ACS_DISCOVERY_BUCKET_NAME` | `acs_service_discovery` | NATS KV bucket name |
| `ACS_DISCOVERY_HEARTBEAT` | `30s` | Heartbeat interval |
| `ACS_DISCOVERY_TTL` | `120s` | KV entry TTL |

## Design Notes

- Uses NATS KV (Key-Value) Store for persistent service registry
- Each instance uses a UUIDv4 as its unique service ID
- Heartbeat loop refreshes the KV entry to prevent TTL expiration
- On graceful shutdown, the instance explicitly deletes its KV entry
- Leader election is deterministic: smallest UUID string wins
- If discovery is disabled, the API endpoints return HTTP 503

## Build Status

- `go build ./...` - PASS
- `go test ./internal/discovery/...` - PASS (8/8 tests)
