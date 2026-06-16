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
| `ACS_HTTP_PORT` | `7370` | HTTP server listen port |
| `ACS_LOG_LEVEL` | `info` | Log level: `debug`, `info`, `warn`, `error` |
| `ACS_LOG_OUTPUT` | `stdout` | Log output destination: `stdout` or `file` |
| `ACS_LOG_FILE_PATH` | `logs/acs.log` | Log file path when `ACS_LOG_OUTPUT=file` |
| `ACS_LOG_MAX_SIZE_MB` | `100` | Maximum log file size in MB before rotation |
| `ACS_LOG_MAX_BACKUPS` | `10` | Maximum number of retained log files |
| `ACS_LOG_MAX_AGE_DAYS` | `30` | Maximum number of days to retain log files |

---

## Database Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `ACS_DB_HOST` | `localhost` | PostgreSQL server host |
| `ACS_DB_PORT` | `5432` | PostgreSQL server port |
| `ACS_DB_NAME` | `agent_community` | Database name |
| `ACS_DB_USER` | `postgres` | Database username |
| `ACS_DB_PASSWORD` | `postgres` | Database password |
| `ACS_DB_SSL_MODE` | `disable` | SSL mode: `disable`, `require`, `verify-ca`, `verify-full` |
| `ACS_DB_MAX_OPEN_CONNS` | `25` | Maximum number of open database connections |
| `ACS_DB_MAX_IDLE_CONNS` | `5` | Maximum number of idle database connections |
| `ACS_DB_CONN_MAX_LIFETIME_MINUTES` | `30` | Maximum lifetime of a database connection in minutes |

---

## NATS Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `ACS_NATS_SERVERS` | `nats://localhost:4222` | NATS server URLs, comma-separated for multiple servers |
| `ACS_NATS_STREAM_GROUP` | `acs_group` | NATS JetStream stream name prefix |
| `ACS_NATS_SUBJECT_GROUP_PENDING_MESSAGE_PREFIX` | `acs.group.pending-message` | Subject prefix for pending messages (agent work queue) |
| `ACS_NATS_SUBJECT_GROUP_MESSAGE_PREFIX` | `acs.group.message` | Subject prefix for group events (pub/sub) |
| `ACS_NATS_KV_BUCKET` | `acs_locks` | NATS KV bucket name for distributed locks |
| `ACS_NATS_LOCK_TTL_SECONDS` | `7200` | TTL for distributed locks in seconds |
| `ACS_NATS_LOCK_RENEW_INTERVAL_SECONDS` | `10` | Lock renewal interval in seconds |
| `ACS_NATS_PENDING_MESSAGE_NO_ACK` | `false` | When `true`, pending messages use fire-and-forget mode (no ack/nak, no InProgress heartbeat). **Warning: messages may be lost if consumer crashes.** |
| `ACS_NATS_ACK_WAIT_SECONDS` | `3600` | NATS consumer AckWait timeout in seconds. Must be greater than the longest expected agent execution time. Only effective when `ACS_NATS_PENDING_MESSAGE_NO_ACK=false`. |
| `ACS_NATS_MAX_ACK_PENDING` | `10` | Maximum number of unacknowledged messages allowed for a consumer in reliable mode. When exceeded, new messages are not delivered until existing ones are acknowledged. |

### NATS Consumer Modes

#### Reliable Mode (default, `ACS_NATS_PENDING_MESSAGE_NO_ACK=false`)
- Consumer must manually acknowledge (`Ack`) each message after processing
- If processing fails, consumer sends negative acknowledgment (`Nak`) to trigger redelivery
- `InProgress()` heartbeat is sent every 20 seconds during long-running processing to prevent premature redelivery
- `AckWait` determines how long NATS waits for acknowledgment before redelivering
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


---

## Agent Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `ACS_GROUP_MANAGER_AGENT_API_BASE` | - | Default API base URL for manager-agents |
| `ACS_GROUP_MANAGER_AGENT_API_KEY` | - | Default API key for manager-agents |
| `ACS_GROUP_MANAGER_AGENT_API_AUTH` | `bearer` | Default authentication method for manager-agents |
| `ACS_AGENT_MAX_CHAIN_LENGTH` | `5` | Maximum number of consecutive agent responses to prevent infinite loops |
| `ACS_AGENT_CHECK_HEALTH_TIMEOUT_SECONDS` | `5` | Timeout for agent health checks |
| `ACS_AGENT_CHECK_STATUS_TIMEOUT_SECONDS` | `5` | Timeout for agent status checks |
| `ACS_AGENT_CHAT_TIMEOUT_SECONDS` | `600` | Timeout for agent chat requests |

---

## WorkPool Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `ACS_AGENT_WORK_POOL_SIZE` | `10` | Maximum concurrent agent tasks per service node |
| `ACS_AGENT_WORK_POOL_PER_USER` | `5` | Maximum concurrent agent tasks per user across all groups |
| `ACS_AGENT_WORK_POOL_PER_GROUP` | `5` | Maximum concurrent agent tasks per group |

---

## Auto-Trigger Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `ACS_AUTO_TRIGGER_INTERVAL_SECONDS` | `60` | Interval for the auto-trigger periodic task in seconds |
| `ACS_AUTO_TRIGGER_TIMEOUT_MINUTES` | `10` | Time in minutes after which a user message triggers the manager-agent automatically |

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


## CLI Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `ACS_SERVER_API_BASE` | `http://localhost:7370` | ACS server API base URL for CLI client |
| `ACS_CLI_MEMBER_ID` | - | Default member ID for CLI client |
| `ACS_CLI_MEMBER_NAME` | - | Default member name for CLI client |

---

## Example Environment File

```bash
# Server
ACS_HTTP_PORT=7370
ACS_LOG_LEVEL=info
ACS_LOG_OUTPUT=stdout

# Database
ACS_DB_HOST=localhost
ACS_DB_PORT=5432
ACS_DB_NAME=agent_community
ACS_DB_USER=postgres
ACS_DB_PASSWORD=postgres
ACS_DB_SSL_MODE=disable

# NATS
ACS_NATS_SERVERS=nats://localhost:4222
ACS_NATS_STREAM_GROUP=acs_group
ACS_NATS_SUBJECT_GROUP_PENDING_MESSAGE_PREFIX=acs.group.pending-message
ACS_NATS_SUBJECT_GROUP_MESSAGE_PREFIX=acs.group.message
ACS_NATS_PENDING_MESSAGE_NO_ACK=false
ACS_NATS_ACK_WAIT_SECONDS=3600

# Agent
ACS_GROUP_MANAGER_AGENT_API_BASE=http://127.0.0.1:7373
ACS_GROUP_MANAGER_AGENT_API_KEY=I-Love-Dawson
ACS_GROUP_MANAGER_AGENT_API_AUTH=bearer

# WorkPool
ACS_AGENT_WORK_POOL_SIZE=10
ACS_AGENT_WORK_POOL_PER_USER=5
ACS_AGENT_WORK_POOL_PER_GROUP=5

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
```
