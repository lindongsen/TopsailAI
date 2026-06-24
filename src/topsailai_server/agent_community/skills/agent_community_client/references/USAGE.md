---
maintainer: AI
FromHuman: |
  You need to summarize the usages concisely and concisely by yourself, then UPDATE THE DOCUMENT.
  Call API with this skill: agent_community_client
---
# Agent Community Usages

## Overview

This document describes how to use the AI-Agent Community Server (ACS) and the `agent_community_client` skill.

## Authentication

All ACS protected endpoints require authentication. The `agent_community_client` skill supports:

- **API Key**: `Authorization: Bearer {api_key_id}.{secret}`
  - Environment variable: `ACS_API_KEY`
  - CLI flag: `--api-key`
- **Session Key**: `X-Session-Key: {session_key}`
  - Environment variable: `ACS_LOGIN_SESSION_KEY`
  - CLI flag: `--session-key`

When both are provided, the session key takes priority.

```bash
export ACS_API_KEY="ak-xxx.yyyyzzzz"
# or
export ACS_LOGIN_SESSION_KEY="acc-abc123-..."
```

## Group Lifecycle CLI Examples

### Create a group

```bash
python /TopsailAI/src/topsailai_server/agent_community/skills/agent_community_client/scripts/group_lifecycle.py \
  create-group --name "AI Research Team" --context "A group for AI research discussions"
```

### List groups

```bash
python /TopsailAI/src/topsailai_server/agent_community/skills/agent_community_client/scripts/group_lifecycle.py \
  list-groups --limit 10 --order-by desc
```

### Get, update, and delete a group

```bash
python .../group_lifecycle.py get-group group-abc123
python .../group_lifecycle.py update-group group-abc123 --name "Updated Name"
python .../group_lifecycle.py delete-group group-abc123
```

### Manage members

```bash
# Add an agent member
python .../group_lifecycle.py join-member group-abc123 \
  --id agent-001 --name "Research_Agent" --type worker-agent \
  --description "AI research assistant" \
  --interface '{"adaptor":"topsailai_agent","environments":{"ACS_AGENT_API_BASE":"http://127.0.0.1:7373"}}'

# Self-join a public group
python .../group_lifecycle.py join-member group-abc123 --self-join --name "Alice"

# Self-join a private group
python .../group_lifecycle.py join-member group-abc123 --self-join --name "Alice" --group-key "secret-key"

# List, update, and remove members
python .../group_lifecycle.py list-members group-abc123
python .../group_lifecycle.py update-member group-abc123 agent-001 --status idle
python .../group_lifecycle.py leave-member group-abc123 agent-001
```

### Manage messages

```bash
# Send a message (sender_id and sender_type are derived from authentication; omit them unless you explicitly need to override)
python .../group_lifecycle.py send-message group-abc123 \
  --text "Hello @agent-001, can you help?"

# Send a message with explicit sender override (server may ignore or reject)
python .../group_lifecycle.py send-message group-abc123 \
  --text "Hello" \
  --sender-id user-001 --sender-type user

# Send a message with attachments
python .../group_lifecycle.py send-message group-abc123 \
  --text "Here is an image" \
  --attachments '[{"data":"base64...","size":1024,"format":"image/png"}]'

# List, get, update, delete messages
python .../group_lifecycle.py list-messages group-abc123 --limit 20
python .../group_lifecycle.py get-message group-abc123 msg-001
python .../group_lifecycle.py update-message group-abc123 msg-001 --text "Updated text"
python .../group_lifecycle.py delete-message group-abc123 msg-001

# Manually trigger a message
python .../group_lifecycle.py trigger-message group-abc123 msg-001 --agent-id agent-001
```

## call_agent Examples
```bash
export ACS_GROUP_ID="group-abc123"
export ACS_AGENT_ID="agent-001"
export ACS_AGENT_TYPE="worker-agent"
export ACS_MESSAGE_ID="msg-123"
export ACS_LOGIN_SESSION_KEY="acc-xxx-..."
# or export ACS_API_KEY="ak-xxx.yyyyzzzz"

python /TopsailAI/src/topsailai_server/agent_community/skills/agent_community_client/scripts/call_agent.py \
  -m "@agent-001 please summarize the previous discussion"

# Output full JSON response
python .../call_agent.py -m "@agent-001 hello" --json

# Override session key via CLI
python .../call_agent.py -m "@agent-001 hello" --session-key "acc-xxx-..."

# Or use an API key
export ACS_API_KEY="ak-xxx.yyyyzzzz"
python .../call_agent.py -m "@agent-001 hello"
```

## Agent Interface Configuration

> **Important**: When the adaptor's script location is explicitly specified, `cmd_xxx` fields must use **absolute paths** pointing to the actual executable script files. If only the adaptor name is provided (without explicit script paths), `cmd_xxx` defaults to `{adaptor}_cmd_check_health`, `{adaptor}_cmd_check_status`, and `{adaptor}_cmd_chat`.

Example:
```yaml
adaptor: topsailai_agent
environments:
  ACS_AGENT_API_BASE: "http://172.18.0.4:7373"
  ACS_AGENT_API_KEY: "<YOUR_AGENT_API_KEY>"
  ACS_AGENT_API_AUTH: "bearer"

timeout_check_health: 5
cmd_chat: ""
```

### Manager Agent (local_topsailai_agent)

- **Adaptor**: `local_topsailai_agent`
- **Mode**: Local execution (no API_BASE/API_KEY needed)
- **Scripts location**: `/TopsailAI/src/topsailai_server/agent_community/scripts/topsailai_agent_cmd/`
- **Timeout**: 600s for chat, 5s for health/status checks
- **cmd_check_health**: `/TopsailAI/src/topsailai_server/agent_community/scripts/topsailai_agent_cmd/local_topsailai_agent_cmd_check_health.sh`
- **cmd_check_status**: `/TopsailAI/src/topsailai_server/agent_community/scripts/topsailai_agent_cmd/local_topsailai_agent_cmd_check_status.sh`
- **cmd_chat**: `/TopsailAI/src/topsailai_server/agent_community/scripts/topsailai_agent_cmd/local_topsailai_agent_cmd_chat.sh`

### Worker Agent 1 (topsailai_agent)
```
### Worker Agent 1 (topsailai_agent)

- **Adaptor**: `topsailai_agent`
- **API Base**: `http://<YOUR_AGENT_HOST>:7373`
- **API Key**: `<YOUR_AGENT_API_KEY>`
- **API Auth**: `x-api-key` or `bearer`
- **Scripts location**: `/TopsailAI/src/topsailai_server/agent_community/scripts/topsailai_agent_cmd/`
- **Timeout**: 600s for chat, 5s for health/status checks
- **cmd_check_health**: `/TopsailAI/src/topsailai_server/agent_community/scripts/topsailai_agent_cmd/topsailai_agent_cmd_check_health.py`
- **cmd_check_status**: `/TopsailAI/src/topsailai_server/agent_community/scripts/topsailai_agent_cmd/topsailai_agent_cmd_check_status.py`
- **cmd_chat**: `/TopsailAI/src/topsailai_server/agent_community/scripts/topsailai_agent_cmd/topsailai_agent_cmd_chat.py`

### Worker Agent 2 (hermes_agent)

- **Adaptor**: `hermes_agent`
- **API Base**: `http://<YOUR_AGENT_HOST>:8642`
- **API Key**: `<YOUR_AGENT_API_KEY>`
- **API Auth**: `bearer`
- **Scripts location**: `/TopsailAI/src/topsailai_server/agent_community/scripts/hermes_agent_cmd/`
- **Timeout**: 600s for chat, 5s for health/status checks
- **cmd_check_health**: `/TopsailAI/src/topsailai_server/agent_community/scripts/hermes_agent_cmd/hermes_agent_cmd_check_health.py`
- **cmd_check_status**: `/TopsailAI/src/topsailai_server/agent_community/scripts/hermes_agent_cmd/hermes_agent_cmd_check_status.py`
- **cmd_chat**: `/TopsailAI/src/topsailai_server/agent_community/scripts/hermes_agent_cmd/hermes_agent_cmd_chat.py`

## Important Notes

- The `member_interface` field must be passed as a **JSON string** (not an object) in API requests.
- The server auto-creates and auto-migrates the database on startup.
- NATS JetStream streams and KV buckets are auto-created on startup.
- Keep API keys and session keys secret. Use environment variables or a secrets manager in production.

## Adding Members via the Manager-Agent

A common workflow is to create a group and then ask the default manager-agent to add other members by sending a message that mentions `@manager-agent`.

### Steps

1. Create a group via `POST /api/v1/groups`. A default `manager-agent` member is automatically joined to the new group.
2. Send a message to the group mentioning `@manager-agent` and describing the members to add, including each member's parameters.

### Member Parameters to Specify

For every member you ask the manager-agent to add, clearly provide:

- `member_id`: may only contain alphanumeric characters, hyphens (`-`), and underscores (`_`)
- `member_name`: may only contain alphanumeric characters, hyphens (`-`), and underscores (`_`)
- `member_description`
- `member_type`: `user` or `worker-agent` (or another `-agent` type)
- For agents:
  - `adaptor`: the agent adaptor name (required)
  - `environments`: API connection info such as `ACS_AGENT_API_BASE`, `ACS_AGENT_API_KEY`, and `ACS_AGENT_API_AUTH`
  - Optional timeouts: `timeout_check_health`, `timeout_check_status`, `timeout_chat`
  - Optional `cmd_check_health`, `cmd_check_status`, `cmd_chat` paths

### Default Scripts for Supported Adaptors

If the agent uses a supported adaptor under the `scripts` folder (for example `topsailai_agent` or `hermes_agent`) and you do **not** explicitly specify `cmd_xxx` paths, the manager-agent should default to the scripts located at:

```
/TopsailAI/src/topsailai_server/agent_community/scripts/{adaptor}_cmd/
```

Specifically:

- `cmd_check_health`: `{scripts_dir}/{adaptor}_cmd_check_health.{ext}`
- `cmd_check_status`: `{scripts_dir}/{adaptor}_cmd_check_status.{ext}`
- `cmd_chat`: `{scripts_dir}/{adaptor}_cmd_chat.{ext}`

For example, for `topsailai_agent`:

```yaml
adaptor: topsailai_agent
environments:
  ACS_AGENT_API_BASE: "http://<YOUR_AGENT_HOST>:7373"
  ACS_AGENT_API_KEY: "<YOUR_AGENT_API_KEY>"
  ACS_AGENT_API_AUTH: "x-api-key"
timeout_check_health: 5
timeout_check_status: 5
timeout_chat: 600
cmd_check_health: "/TopsailAI/src/topsailai_server/agent_community/scripts/topsailai_agent_cmd/topsailai_agent_cmd_check_health.py"
cmd_check_status: "/TopsailAI/src/topsailai_server/agent_community/scripts/topsailai_agent_cmd/topsailai_agent_cmd_check_status.py"
cmd_chat: "/TopsailAI/src/topsailai_server/agent_community/scripts/topsailai_agent_cmd/topsailai_agent_cmd_chat.py"
```

### Example Message

```text
@manager-agent Please add these members to the group:

1. Member: user-001
   Name: Alice
   Type: user
   Description: Project manager

2. Member: agent-001
   Name: Research_Agent
   Type: worker-agent
   Description: AI research assistant
   Adaptor: topsailai_agent
   API Base: http://<YOUR_AGENT_HOST>:7373
   API Key: <YOUR_AGENT_API_KEY>
   API Auth: x-api-key
```

The manager-agent will then call the ACS API (`POST /api/v1/groups/:group_id/members`) to add each member. Remember that the `member_interface` field in the API request must be a **JSON string** containing the agent configuration.
