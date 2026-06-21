---
maintainer: AI
workspace: /TopsailAI/src/topsailai_server/agent_community
---

# AI-Agent Community Server (ACS) - Environment Variables Reference

All environment variables used by ACS are prefixed with `ACS_`.

---

## Server Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `ACS_HTTP_HOST` | `` (empty, all interfaces) | HTTP server listen host/IP. Set to `127.1.0.1` to bind a specific loopback address so multiple instances can run on the same machine. |
| `ACS_HTTP_PORT` | `7370` | HTTP server listen port |
| `ACS_SERVER_READ_TIMEOUT` | `30s` | HTTP server read timeout |
| `ACS_SERVER_WRITE_TIMEOUT` | `30s` | HTTP server write timeout |

---

## Database Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `ACS_DATABASE_DRIVER` | `postgres` | Database driver: `postgres` or `sqlite` |
| `ACS_DATABASE_HOST` | `localhost` | PostgreSQL server host |
| `ACS_DATABASE_PORT` | `5432` | PostgreSQL server port |
| `ACS_DATABASE_USER` | `acs` | Database username |
| `ACS_DATABASE_PASSWORD` | `acs` | Database password |
| `ACS_DATABASE_NAME` | `acs` (postgres) or `$ACS_HOME/agent_community.db` (sqlite) | Database name or SQLite file path |
| `ACS_DATABASE_SSLMODE` | `disable` | SSL mode: `disable`, `require`, `verify-ca`, `verify-full` |

### SQLite Default Path

When `ACS_DATABASE_DRIVER=sqlite` and `ACS_DATABASE_NAME` is not explicitly set, the SQLite file path is resolved in the following order:
1. `$ACS_HOME/agent_community.db`
2. `$TOPSAILAI_HOME/agent_community.db`
3. `/topsailai/agent_community.db`

---

## NATS Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `ACS_NATS_SERVERS` | `nats://localhost:4222` | NATS server URLs, comma-separated for multiple servers |
| `ACS_NATS_STREAM_GROUP` | `acs_group` | NATS JetStream stream name prefix |
| `ACS_NATS_SUBJECT_GROUP_PENDING_MESSAGE_PREFIX` | `acs.group.pending-message` | Subject prefix for pending messages (agent work queue) |
| `ACS_NATS_SUBJECT_GROUP_MESSAGE_PREFIX` | `acs.group.message` | Subject prefix for group events (pub/sub) |
| `ACS_NATS_PENDING_MESSAGE_NO_ACK` | `false` | When `true`, pending messages use fire-and-forget mode (no ack/nak, no InProgress heartbeat). **Warning: messages may be lost if consumer crashes.** |
| `ACS_NATS_ACK_WAIT_SECONDS` | `3600` | NATS consumer AckWait timeout in seconds. Must be greater than the longest expected agent execution time. Only effective when `ACS_NATS_PENDING_MESSAGE_NO_ACK=false`. |
| `ACS_NATS_MAX_ACK_PENDING` | `10` | Maximum number of unacknowledged messages allowed for a consumer in reliable mode. When exceeded, new messages are not delivered until existing ones are acknowledged. |
| `ACS_NATS_MAX_DELIVER` | `0` | Maximum number of delivery attempts for a pending message. `0` means unlimited redeliveries. Only effective when `ACS_NATS_PENDING_MESSAGE_NO_ACK=false`. |

### NATS Consumer Modes

#### Reliable Mode (default, `ACS_NATS_PENDING_MESSAGE_NO_ACK=false`)
- Consumer must manually acknowledge (`Ack`) each message after processing
- If processing fails, consumer sends negative acknowledgment (`Nak`) to trigger redelivery
- `InProgress()` heartbeat is sent every 20 seconds during long-running processing to prevent premature redelivery
- `AckWait` determines how long NATS waits for acknowledgment before redelivering
- `MaxDeliver` controls the maximum number of delivery attempts; `0` means unlimited
- Guarantees **at-least-once** message delivery

#### Fire-and-Forget Mode (`ACS_NATS_PENDING_MESSAGE_NO_ACK=true`)
- Consumer does not acknowledge messages
- No `InProgress()` heartbeat
- NATS removes message from queue immediately after delivery
- **No redelivery** if processing fails or consumer crashes
- Suitable for scenarios where occasional message loss is acceptable
- **Not recommended** for critical agent processing

### MaxAckPending

In reliable mode (`ACS_NATS_PENDING_MESSAGE_NO_ACK=false`), `MaxAckPending` controls how many messages can be delivered to a consumer without being acknowledged. When this limit is reached, NATS stops delivering new messages to that consumer until some messages are acknowledged. This prevents overwhelming slow consumers.

### MaxDeliver

In reliable mode, `MaxDeliver` controls how many times NATS will attempt to deliver a pending message. The default is `0` (unlimited), which is appropriate for agent work queues where saturation is a transient backpressure signal rather than a permanent failure. If you set a finite value, ensure it is large enough to outlast the longest expected queue saturation period; otherwise messages may be silently dropped when the work pool is temporarily full.

---

## Agent Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `ACS_GROUP_MANAGER_AGENT_API_BASE` | - | Default API base URL for manager-agents |
| `ACS_GROUP_MANAGER_AGENT_API_KEY` | - | Default API key for manager-agents |
| `ACS_GROUP_MANAGER_AGENT_API_AUTH` | `bearer` | Default authentication method for manager-agents |
| `ACS_AGENT_AUTO_TRIGGER_TIMEOUT` | `10m` | Time after which a user message automatically triggers the manager-agent |
| `ACS_AGENT_PROMPT` | - | Service-wide prompt injected into agent chat environment variables |

### Default Manager-Agent Auto-Join Configuration

When `ACS_GROUP_MANAGER_AGENT_CMD_CHAT` is set, ACS automatically creates a default `manager-agent` member in every new group. This provides an out-of-the-box coordinator for groups without requiring callers to explicitly join a manager-agent via the API.

| Variable | Default | Description |
|----------|---------|-------------|
| `ACS_GROUP_MANAGER_AGENT_CMD_CHAT` | - | **Required.** Command used to send chat messages to the manager-agent. When set, auto-join is enabled. |
| `ACS_GROUP_MANAGER_AGENT_CMD_CHECK_HEALTH` | - | Optional command to check manager-agent health. If unset, the agent is always considered healthy. |
| `ACS_GROUP_MANAGER_AGENT_CMD_CHECK_STATUS` | - | Optional command to check manager-agent status (e.g., `idle`, `processing`). |
| `ACS_GROUP_MANAGER_AGENT_API_BASE` | - | Optional API base URL passed to the manager-agent via `member_interface.environments`. |
| `ACS_GROUP_MANAGER_AGENT_API_KEY` | - | Optional API key passed to the manager-agent via `member_interface.environments`. |
| `ACS_GROUP_MANAGER_AGENT_API_AUTH` | `bearer` | Optional auth method passed to the manager-agent via `member_interface.environments`. |
| `ACS_GROUP_MANAGER_AGENT_TIMEOUT_CHAT` | `600s` | Timeout for manager-agent chat commands. |
| `ACS_GROUP_MANAGER_AGENT_TIMEOUT_CHECK_HEALTH` | `5s` | Timeout for manager-agent health-check commands. |
| `ACS_GROUP_MANAGER_AGENT_TIMEOUT_CHECK_STATUS` | `5s` | Timeout for manager-agent status-check commands. |
| `ACS_GROUP_MANAGER_AGENT_MEMBER_ID` | `manager-agent` | Member ID of the auto-joined manager-agent. |
| `ACS_GROUP_MANAGER_AGENT_MEMBER_NAME` | `manager-agent` | Member name of the auto-joined manager-agent. |
| `ACS_GROUP_MANAGER_AGENT_MEMBER_DESCRIPTION` | `Default group manager agent` | Description of the auto-joined manager-agent. |
| `ACS_GROUP_MANAGER_AGENT_ADAPTOR` | `topsailai_agent` | Adaptor name used in the manager-agent `member_interface`. |

The auto-joined member uses `member_type=manager-agent` and is created inside the same database transaction as the group, ensuring atomicity. Both `group` and `group_member` create events are published to NATS when the transaction commits.

### Agent Chat Environment Variables

The following variables are passed to agent adaptors via `member_interface.environments` and built dynamically at runtime. They are documented here for completeness but are not configured directly on the ACS server.

| Variable | Source | Description |
|----------|--------|-------------|
| `ACS_AGENT_API_BASE` | `member_interface.environments` | Agent API base URL |
| `ACS_AGENT_API_KEY` | `member_interface.environments` | Agent API key |
| `ACS_AGENT_API_AUTH` | `member_interface.environments` | Agent API auth method (e.g., `bearer`) |
| `ACS_AGENT_ID` | `group_member.member_id` | Agent member ID |
| `ACS_AGENT_NAME` | `group_member.member_name` | Agent member name |
| `ACS_AGENT_TYPE` | `group_member.member_type` | Agent member type (`manager-agent` or `worker-agent`) |
| `ACS_AGENT_MODE` | Trigger context | `chat` or `agent` |
| `ACS_AGENT_MESSAGE` | Built context messages | Context messages sent to the agent |
| `ACS_AGENT_TIMEOUT` | `member_interface.timeout_chat` | Agent chat timeout in seconds |
| `ACS_AGENT_PROMPT` | `ACS_AGENT_PROMPT` env var | Service-wide agent prompt |
| `ACS_GROUP_ID` | Group ID | Current group ID |
| `ACS_GROUP_NAME` | Group name | Current group name |
| `ACS_GROUP_CONTEXT` | `group.group_context` | Group context, only passed when `last_read_message_id` is empty |
| `ACS_SENDER_ID` | Message sender ID | Original message sender ID |
| `ACS_SENDER_NAME` | Message sender name | Original message sender name |
| `ACS_MESSAGE_ID` | Message ID | ID of the message being processed |
| `ACS_MESSAGE_MENTIONS` | Message mentions JSON | Mentions extracted from the message |
| `ACS_MESSAGE_TRIGGER_TYPE` | Trigger type | `mention`, `auto`, or `manual` |
| `ACS_LOGIN_SESSION_KEY` | `accounts.login_session_key` | Plaintext login session key of the original message sender. Only injected when the triggered agent is a `manager-agent`. If the sender has no valid session or it has expired, a new session key is generated automatically. |

## Account & API Key Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `ACS_ACCOUNT_ADMIN_API_KEY` | - | Plaintext admin token. If set, startup validates it matches an active `role=admin` API key; otherwise a default admin account and key are auto-generated and written to `ACS_ACCOUNT_ADMIN_API_KEY.acs` in the process working directory (PWD). |
| `ACS_ACCOUNT_MANAGER_API_KEY` | - | Plaintext manager token. If set, startup validates it matches an active `role=manager` API key; otherwise a default manager account and key are auto-generated and written to `ACS_ACCOUNT_MANAGER_API_KEY.acs` in the process working directory (PWD). |
| `ACS_API_KEY_MAX_PER_ACCOUNT` | `10` | Maximum number of API keys allowed per account owner. |
| `ACS_LOGIN_SESSION_EXPIRY_SECONDS` | `86400` | Default expiry time in seconds for login session keys. |
| `ACS_BCRYPT_COST` | `10` | Bcrypt cost factor used for hashing `login_password`, API key secrets, and `login_session_key`. |

### Behavior

- **Default account creation** is guarded by a NATS KV distributed lock and only performed by the current `Service-Leader`. This prevents duplicate default accounts when multiple ACS instances start simultaneously.
- If `ACS_ACCOUNT_ADMIN_API_KEY` or `ACS_ACCOUNT_MANAGER_API_KEY` is provided but does not match an existing active API key with the expected role, the server logs a clear configuration error and exits.
- Auto-generated keys are written to plain text files in the process working directory. These files should be secured appropriately in production deployments.

---

## AgentWorkPool Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `ACS_AGENT_WORK_POOL_PER_NODE` | `10` | Maximum concurrent agent tasks per service node |
| `ACS_AGENT_WORK_POOL_PER_USER` | `5` | Maximum concurrent agent invocations per original message sender across all groups |
| `ACS_AGENT_WORK_POOL_PER_GROUP` | `5` | Maximum concurrent agent invocations per group |
| `ACS_AGENT_WORK_POOL_ACQUIRE_TIMEOUT` | `30s` | Maximum time to wait for a work-pool slot before giving up |
| `ACS_AGENT_WORK_POOL_STATS_LOG_INTERVAL` | `30s` | Interval for logging work pool statistics |

### Behavior

- The limits are enforced per **active agent invocation**, not per pending message.
- A single pending message that mentions multiple agents may therefore consume multiple slots for the same sender and/or group.
  - Example: a message mentioning 3 worker-agents in the same group consumes 3 of the `ACS_AGENT_WORK_POOL_PER_GROUP` slots while those agents are running.
- Each agent invocation acquires its own slot before calling the agent and releases it when the call completes.
- When a limit is reached, additional invocations wait (with a timeout) for a slot to become available.

----

## Log Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `ACS_LOG_OUTPUT` | `stdout` | Log output destination: `stdout` or `file` |
| `ACS_LOG_LEVEL` | `info` | Log level: `debug`, `info`, `warn`, `error` |
| `ACS_LOG_FILE_PATH` | `/var/log/acs/acs.log` | Log file path when `ACS_LOG_OUTPUT=file` |
| `ACS_LOG_MAX_SIZE_MB` | `100` | Maximum log file size in MB before rotation |
| `ACS_LOG_MAX_AGE_DAYS` | `30` | Maximum number of days to retain log files |
| `ACS_LOG_MAX_BACKUPS` | `10` | Maximum number of retained log files |

### Audit Logging

Audit logs are written to the `audit_logs` table and record security-relevant events such as account/API key lifecycle actions and authentication attempts. The audit logger is invoked automatically by the HTTP middleware for protected endpoints. There are no dedicated environment variables for audit logging; behavior is controlled by the database connection and the general log configuration above.

---

## Auto-Trigger Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `ACS_AUTO_TRIGGER_INTERVAL_SECONDS` | `60` | Interval for the auto-trigger periodic task in seconds |
| `ACS_AUTO_TRIGGER_TIMEOUT_MINUTES` | `10` | Time in minutes after which a user message triggers the manager-agent automatically |

> **Note:** `ACS_AUTO_TRIGGER_TIMEOUT_MINUTES` is kept for backward compatibility. The canonical variable is `ACS_AGENT_AUTO_TRIGGER_TIMEOUT` (see Agent Configuration).

---

## Cleanup Configuration

Controls the periodic cleanup of `agent_message_processing` table records.

| Variable | Default | Description |
|----------|---------|-------------|
| `ACS_CLEANUP_ENABLED` | `true` | Enable or disable the cleanup background task |
| `ACS_CLEANUP_INTERVAL` | `1h` | Interval between cleanup executions (e.g., `30m`, `1h`, `24h`) |
| `ACS_CLEANUP_RETENTION_DAYS` | `7` | Number of days to retain terminal (completed/failed) records |
| `ACS_CLEANUP_STALE_PENDING_HOURS` | `24` | Hours after which pending records are considered stale and eligible for deletion |
| `ACS_CLEANUP_BATCH_SIZE` | `1000` | Maximum number of records to delete per cleanup execution |

### Behavior

- **Terminal records** (status = `completed` or `failed`) older than `ACS_CLEANUP_RETENTION_DAYS` are deleted
- **Pending records** older than `ACS_CLEANUP_STALE_PENDING_HOURS` are considered stale and deleted
- Cleanup runs immediately on service start, then on each interval tick
- When disabled (`ACS_CLEANUP_ENABLED=false`), no cleanup occurs and records accumulate

---

## Service Discovery Configuration

Controls NATS-based service discovery and Service-Leader election.

| Variable | Default | Description |
|----------|---------|-------------|
| `ACS_DISCOVERY_ENABLED` | `true` | Enable or disable service discovery registration |
| `ACS_DISCOVERY_SERVICE_NAME` | `acs` | Service name used in discovery registry |
| `ACS_DISCOVERY_BUCKET_NAME` | `acs_service_discovery` | NATS KV bucket name for service registry |
| `ACS_DISCOVERY_HEARTBEAT` | `30s` | Interval between heartbeat updates to NATS KV |
| `ACS_DISCOVERY_TTL` | `120s` | TTL for service registration entries in NATS KV |

### Behavior

- Each service instance registers itself with a unique UUID to the NATS KV bucket on startup
- A background heartbeat loop refreshes the registration at the configured interval
- On graceful shutdown, the instance deregisters itself from the bucket
- The instance with the smallest `id` among all registered services is elected as `Service-Leader`
- When disabled (`ACS_DISCOVERY_ENABLED=false`), no registration occurs and leader election APIs return 503

---

## Daemon Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `ACS_HOME` | `/topsailai` | Base directory for ACS daemon logs, PID files, and SQLite database |
| `TOPSAILAI_HOME` | `/topsailai` | Fallback base directory when `ACS_HOME` is not set |

### Behavior

- Daemon log file: `$ACS_HOME/log/agent_community.log`
- Daemon PID file: `$ACS_HOME/run/agent_community.pid`
- SQLite default path: `$ACS_HOME/agent_community.db`

---

## CLI Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `ACS_SERVER_API_BASE` | `http://localhost:7370` | ACS server API base URL for CLI client |
| `ACS_NATS_SERVERS` | `nats://localhost:4222` | NATS server URL(s) for CLI client |

---

## Example Environment File

```bash
# Server
ACS_HTTP_HOST=
ACS_HTTP_PORT=7370
ACS_SERVER_READ_TIMEOUT=30s
ACS_SERVER_WRITE_TIMEOUT=30s

# Database
ACS_DATABASE_DRIVER=postgres
ACS_DATABASE_HOST=localhost
ACS_DATABASE_PORT=5432
ACS_DATABASE_NAME=acs
ACS_DATABASE_USER=acs
ACS_DATABASE_PASSWORD=acs
ACS_DATABASE_SSL_MODE=disable

# NATS
ACS_NATS_SERVERS=nats://localhost:4222
ACS_NATS_STREAM_GROUP=acs_group
ACS_NATS_SUBJECT_GROUP_PENDING_MESSAGE_PREFIX=acs.group.pending-message
ACS_NATS_SUBJECT_GROUP_MESSAGE_PREFIX=acs.group.message
ACS_NATS_PENDING_MESSAGE_NO_ACK=false
ACS_NATS_ACK_WAIT_SECONDS=3600
ACS_NATS_MAX_ACK_PENDING=10
ACS_NATS_MAX_DELIVER=0

# Agent
ACS_GROUP_MANAGER_AGENT_API_BASE=http://127.0.0.1:7373
ACS_GROUP_MANAGER_AGENT_API_KEY=I-Love-Dawson
ACS_GROUP_MANAGER_AGENT_API_AUTH=bearer
ACS_AGENT_AUTO_TRIGGER_TIMEOUT=10m
ACS_AGENT_PROMPT="You are a helpful AI assistant."

# AgentWorkPool
ACS_AGENT_WORK_POOL_PER_NODE=10
ACS_AGENT_WORK_POOL_PER_USER=5
ACS_AGENT_WORK_POOL_PER_GROUP=5
ACS_AGENT_WORK_POOL_ACQUIRE_TIMEOUT=30s
ACS_AGENT_WORK_POOL_STATS_LOG_INTERVAL=30s

# Log
ACS_LOG_OUTPUT=stdout
ACS_LOG_LEVEL=info
ACS_LOG_FILE_PATH=/var/log/acs/acs.log
ACS_LOG_MAX_SIZE_MB=100
ACS_LOG_MAX_AGE_DAYS=30
ACS_LOG_MAX_BACKUPS=10

# Auto-Trigger
ACS_AUTO_TRIGGER_INTERVAL_SECONDS=60
ACS_AUTO_TRIGGER_TIMEOUT_MINUTES=10
# Cleanup
ACS_CLEANUP_ENABLED=true
ACS_CLEANUP_INTERVAL=1h
ACS_CLEANUP_RETENTION_DAYS=7
ACS_CLEANUP_STALE_PENDING_HOURS=24
ACS_CLEANUP_BATCH_SIZE=1000

# Service Discovery
ACS_DISCOVERY_ENABLED=true
ACS_DISCOVERY_SERVICE_NAME=acs
ACS_DISCOVERY_BUCKET_NAME=acs_service_discovery
ACS_DISCOVERY_HEARTBEAT=30s
ACS_DISCOVERY_TTL=120s

# Account & API Key
ACS_ACCOUNT_ADMIN_API_KEY=ak-admin.xxxxxxxx
ACS_ACCOUNT_MANAGER_API_KEY=ak-manager.xxxxxxxx
ACS_API_KEY_MAX_PER_ACCOUNT=10
ACS_LOGIN_SESSION_EXPIRY_SECONDS=86400
ACS_BCRYPT_COST=10

# Daemon
ACS_HOME=/topsailai
TOPSAILAI_HOME=/topsailai

# CLI
ACS_SERVER_API_BASE=http://localhost:7370
ACS_NATS_SERVERS=nats://localhost:4222
```
