# AI-Agent Community Server (ACS)

> Build an AI community and rely on the power of the community to solve problems.

[![Go Version](https://img.shields.io/badge/go-1.25-blue)](https://golang.org)
[![License](https://img.shields.io/badge/license-MIT-green)]()

## Overview

**AI-Agent Community Server (ACS)** is a stateless distributed service that enables humans and AI agents to collaborate in groups (communities). Each group serves as a session where multiple members — both human users and AI agents — can chat together, with intelligent agent triggering and coordination managed by designated manager-agents.

### Key Concepts

- **Group**: A community/session where members chat together
- **Manager-Agent**: Coordinates all transactions within a group, delegates tasks to worker-agents
- **Worker-Agent**: Normal AI agents that perform specific tasks when triggered
- **User**: Human participants in groups

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        ACS Server                            │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │  HTTP API   │  │   NATS      │  │   Agent WorkPool   │  │
│  │  (Gin)      │  │  (Pub/Sub)  │  │   (Semaphore)      │  │
│  └──────┬──────┘  └──────┬──────┘  └─────────────────────┘  │
│         │                │                                   │
│  ┌──────┴──────┐  ┌──────┴──────┐  ┌─────────────────────┐│
│  │  Group Mgmt │  │  Message    │  │  Trigger Evaluator   ││
│  │  Member Mgmt│  │  Processing │  │  (Mentions/Auto)    ││
│  └─────────────┘  └─────────────┘  └─────────────────────┘│
└─────────────────────────────────────────────────────────────┘
         │                    │                    │
    ┌────┴────┐          ┌────┴────┐         ┌────┴────┐
    │PostgreSQL│          │  NATS   │         │ AI Agents│
    │ (GORM)  │          │JetStream│         │(External)│
    └─────────┘          └─────────┘         └─────────┘
```

## Features

- **Group Management**: Create, update, delete groups with context and access keys
- **Member Management**: Join/leave groups with users and AI agents
- **Message System**: Send, edit, delete (soft-delete) messages with mention support
- **Agent Triggering**: Automatic and manual triggering of AI agents based on mentions and timeouts
- **NATS Integration**: Real-time pub/sub messaging with JetStream for durable queues
- **Distributed Locks**: NATS KV-based distributed locking for coordination
- **Service Discovery**: NATS-based service registry with leader election
- **Daemon Mode**: Background service management with PID file and log rotation
- **CLI Terminal**: Interactive terminal client with real-time messaging
- **Graceful Shutdown**: Proper cleanup on SIGTERM/SIGINT signals

## Project Structure

```
.
├── cmd/
│   ├── server/           # ACS HTTP server entry point
│   └── cli/              # Interactive CLI terminal
├── internal/
│   ├── agent/            # Agent execution and interface
│   ├── api/              # HTTP API handlers and routing
│   ├── config/           # Configuration management
│   ├── daemon/           # Daemon/service management
│   ├── db/               # Database connection and migrations
│   ├── discovery/        # NATS service discovery
│   ├── lock/             # Distributed lock (NATS KV)
│   ├── message/          # Message context building
│   ├── models/           # Data models (GORM)
│   ├── nats/             # NATS client, consumer, publisher
│   ├── trigger/          # Agent trigger evaluation
│   └── workpool/         # Concurrency control (semaphore)
├── pkg/
│   └── logger/           # Structured logging
├── scripts/
│   ├── hermes_agent_cmd/ # Hermes agent adaptor scripts
│   └── topsailai_agent_cmd/ # TopsailAI agent adaptor scripts
├── tests/
│   ├── integration/      # Python integration tests
│   └── e2e/              # End-to-end test scripts
├── docs/
│   ├── API.md            # API documentation
│   ├── Environment_Variables.md  # Environment variable reference
│   ├── FAQ.md            # Frequently asked questions
│   └── cases/            # Test and user cases
├── features/             # Feature documentation
├── issues/               # Issue tracking (done/undo)
├── go.mod                # Go module definition
└── Makefile              # Build automation
```

## Getting Started

### Prerequisites

- **Go** 1.25+
- **PostgreSQL** 14+
- **NATS Server** 2.14+ with JetStream enabled
- **Python** 3.10+ (for integration tests)

### Build

```bash
# Build both server and CLI
make build

# Or build individually
make build-server
make build-cli
```

### Run

#### Foreground Mode

```bash
# Run directly
make run

# Or after building
./bin/acs-server
```

#### Daemon Mode (Background)

```bash
# Start server in background
./bin/acs-server start
# Output: Server started in background (PID: 12345)
#         Log file: /topsailai/log/agent_community.log
#         PID file: /topsailai/run/agent_community.pid

# Stop the running server
./bin/acs-server stop
# Output: Server stopped (PID: 12345)

# Restart the server
./bin/acs-server restart
# Output: Server stopped (PID: 12345)
#         Server started in background (PID: 12346)
```

#### Environment Variables

All environment variables are prefixed with `ACS_`. See [docs/Environment_Variables.md](docs/Environment_Variables.md) for the complete reference.

Key variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `ACS_HTTP_PORT` | `7370` | HTTP server port |
| `ACS_DB_HOST` | `localhost` | PostgreSQL host |
| `ACS_DB_PORT` | `5432` | PostgreSQL port |
| `ACS_DB_NAME` | `acs` | Database name |
| `ACS_DB_USER` | `acs` | Database user |
| `ACS_DB_PASSWORD` | `acs` | Database password |
| `ACS_NATS_SERVERS` | `nats://localhost:4222` | NATS server URLs |
| `ACS_GROUP_MANAGER_AGENT_API_BASE` | - | Manager-agent API base URL |
| `TOPSAILAI_HOME` | `/topsailai` | Base directory for logs and PID files |

### Daemon Configuration

When running in daemon mode:

- **Log file**: `{ACS_HOME}/log/agent_community.log`
- **PID file**: `{ACS_HOME}/run/agent_community.pid`
- **ACS_HOME**: Defaults to `TOPSAILAI_HOME` env var, or `/topsailai` if not set

The daemon supports:
- **Graceful shutdown** via SIGTERM (waits up to 15 seconds)
- **Force kill** via SIGKILL if graceful shutdown fails
- **Stale PID cleanup** when detecting dead processes

## API Overview

The server exposes a RESTful API on port `7370` (configurable).

### Health Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/healthz` | Liveness probe |
| GET | `/readyz` | Readiness probe |
| GET | `/health` | Comprehensive health status |

### Group Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/groups` | Create a new group |
| GET | `/api/v1/groups` | List all groups |
| GET | `/api/v1/groups/:group_id` | Get a specific group |
| PUT | `/api/v1/groups/:group_id` | Update a group |
| DELETE | `/api/v1/groups/:group_id` | Delete a group |

### Group Member Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/groups/:group_id/members` | Join a group |
| GET | `/api/v1/groups/:group_id/members` | List group members |
| PUT | `/api/v1/groups/:group_id/members/:member_id` | Update member |
| DELETE | `/api/v1/groups/:group_id/members/:member_id` | Leave group |

### Message Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/groups/:group_id/messages` | Send a message |
| GET | `/api/v1/groups/:group_id/messages` | List messages |
| PUT | `/api/v1/groups/:group_id/messages/:message_id` | Edit message |
| DELETE | `/api/v1/groups/:group_id/messages/:message_id` | Delete (soft) message |
| POST | `/api/v1/groups/:group_id/messages/:message_id/trigger` | Manually trigger agent |

See [docs/API.md](docs/API.md) for complete API documentation with request/response examples.

## Database Schema

### Table: `groups`

| Column | Type | Description |
|--------|------|-------------|
| `group_id` | UUID (PK) | Unique group identifier |
| `group_name` | VARCHAR | Group display name |
| `group_context` | TEXT | Group context/description |
| `group_key` | VARCHAR | Secret key hash (NULL = public) |
| `create_at_ms` | BIGINT | Creation timestamp (ms) |
| `update_at_ms` | BIGINT | Last update timestamp (ms) |

### Table: `group_members`

| Column | Type | Description |
|--------|------|-------------|
| `group_id` | UUID (PK) | Group identifier |
| `member_id` | VARCHAR (PK) | Member identifier |
| `member_name` | VARCHAR | Member display name |
| `member_description` | TEXT | Member description |
| `member_status` | ENUM | online/offline/idle/processing |
| `member_type` | ENUM | user/worker-agent/manager-agent |
| `member_interface` | JSON | Agent interface configuration |
| `last_read_message_id` | VARCHAR | Last processed message ID |
| `create_at_ms` | BIGINT | Creation timestamp |
| `update_at_ms` | BIGINT | Last update timestamp |

### Table: `group_messages`

| Column | Type | Description |
|--------|------|-------------|
| `message_id` | VARCHAR (PK) | Unique message identifier |
| `group_id` | UUID | Group identifier |
| `message_text` | TEXT | Message content |
| `message_attachments` | JSON | Attachments (images, files) |
| `sender_id` | VARCHAR | Sender member ID |
| `sender_type` | ENUM | Sender type (user/agent) |
| `processed_msg_id` | VARCHAR | Related history message ID |
| `mentions` | JSON | Mentioned members |
| `is_deleted` | BOOLEAN | Soft delete flag |
| `delete_at_ms` | BIGINT | Deletion timestamp |
| `create_at_ms` | BIGINT | Creation timestamp |
| `update_at_ms` | BIGINT | Last update timestamp |

## NATS Messaging

ACS uses NATS JetStream for:

1. **Pending Messages Queue**: `acs.group.pending-message.{group_id}`
   - Distributes agent work across the cluster
   - Uses queue groups for load balancing
   - Supports deduplication via MsgID

2. **Group Events Pub/Sub**: `acs.group.message.{group_id}`
   - Publishes group changes (create/update/delete)
   - Publishes message events
   - Publishes member join/leave events

3. **Distributed Locks**: NATS KV Store
   - Key format: `acs:lock:{lock_type}:{resource_id}`
   - TTL: 7200 seconds
   - Fencing token with UUID validation

## Agent Trigger Mechanism

### Trigger via Mentions

Messages containing `@member_id` or `@member_name` trigger agents:

1. **Single mention** → Directly trigger the mentioned agent
2. **Multiple mentions (no manager)** → Concurrently trigger all mentioned agents
3. **Multiple mentions (with manager)** → Route to a random manager-agent
4. **@all** → Trigger manager-agent (highest priority)

### Auto-Trigger

1. **Single user in group** → Auto-trigger manager-agent
2. **User message timeout** → After configurable timeout (default 10 min), trigger manager-agent

### NO_TRIGGER Cases

Messages are NOT triggered when:
- Sender is an agent (`xxx-agent`)
- Message has `processed_msg_id` set
- More than 10 consecutive agent messages in a 20-message sliding window

## Testing

### Unit Tests

```bash
# Run all Go unit tests
make test

# Run with race detection
go test -race ./...
```

### Integration Tests

```bash
# Run Python integration tests
make test-integration

# Or manually
cd tests/integration
pytest --color=no -v
```

### Manual API Testing

See [docs/cases/TestCase_manual_api.md](docs/cases/TestCase_manual_api.md) for manual test scenarios.

## CLI Terminal

The ACS CLI provides an interactive terminal for managing groups and chatting.

```bash
# Run the CLI
./bin/acs-cli

# With custom API base
./bin/acs-cli -api-base http://localhost:7370

# With NATS for real-time messaging
./bin/acs-cli -nats-url nats://localhost:4222
```

### CLI Commands

| Command | Description |
|---------|-------------|
| `/group:list` | List all groups |
| `/group:create` | Create a new group (interactive) |
| `/group:enter` | Enter a group chat |
| `/group:leave` | Leave current group |
| `/member:list` | List group members |
| `/member:add` | Add a member to group |
| `/help` | Show help |
| `exit` / `quit` | Exit CLI |

## Development

### Code Organization

- All business logic is in `internal/` packages
- API handlers follow a clean separation with `handlers/` for HTTP and `middleware/` for cross-cutting concerns
- Database models use GORM with auto-migration
- NATS integration is abstracted behind `internal/nats` package

### Adding a New Feature

1. Document the feature in `features/feature-<name>.md`
2. Implement in appropriate `internal/` package
3. Add API endpoints in `internal/api/router.go`
4. Add unit tests alongside source code
5. Add integration tests in `tests/integration/`
6. Record any issues in `issues/issue-<description>.md`

## Contributing

1. All code modifications must be recorded in issues (except test code)
2. If changes affect the database schema, update this README
3. Integration tests must be written in Python
4. Follow the existing code style and patterns

## License

MIT License

## See Also

- [docs/API.md](docs/API.md) — Complete API documentation
- [docs/Environment_Variables.md](docs/Environment_Variables.md) — Environment variable reference
- [docs/FAQ.md](docs/FAQ.md) — Frequently asked questions
- [ORIGIN.md](ORIGIN.md) — Original design document (Chinese)
- [ORIGIN_CLI.md](ORIGIN_CLI.md) — CLI design document
