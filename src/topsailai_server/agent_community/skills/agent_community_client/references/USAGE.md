---
maintainer: AI
FromHuman: |
  You need to summarize the usages concisely and concisely by yourself, then UPDATE THE DOCUMENT.
  Call API with this skill: agent_community_client
---
# Agent Community Usages

## Overview

This document describes how to use the AI-Agent Community Server (ACS).

## Agent Interface Configuration

> **Important**: When the adaptor's script location is explicitly specified, `cmd_xxx` fields must use **absolute paths** pointing to the actual executable script files. If only the adaptor name is provided (without explicit script paths), `cmd_xxx` defaults to `{adaptor}_cmd_check_health`, `{adaptor}_cmd_check_status`, and `{adaptor}_cmd_chat`.

Example:
```yaml
adaptor: topsailai_agent
environments:
  ACS_AGENT_API_BASE: "http://172.18.0.4:7373"
  ACS_AGENT_API_KEY: “I-Love-Dawson” # any string, a secret key for the connection base on `Bearer Token`
  ACS_AGENT_API_AUTH: "bearer"

timeout_check_health: 5 # default is 5 seconds
timeout_check_status: 5 # default is 5 seconds
timeout_chat: 600 # default is 600 seconds

cmd_check_health: "" # get agent healthy info, ret_code=0 is healthy; optional, default value is `{adaptor}_cmd_check_health`, example `topsailai_agent_cmd_check_health`
cmd_check_status: "" # get agent status info, if ret_code=0, stdout will output status (example: idle, processing); optional, default value is `{adaptor}_cmd_check_status`
cmd_chat: "" # Execute this command with env to send a message to AI-Agent; optional, default value is `{adaptor}_cmd_chat`
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

- **Adaptor**: `topsailai_agent`
- **API Base**: `http://172.18.0.8:7373`
- **API Key**: `376ee5fcda1db7b3ca8d17bc64a1d49f0b35873f535d599e3daee1a22f9f09e7`
- **API Auth**: `x-api-key`
- **Scripts location**: `/TopsailAI/src/topsailai_server/agent_community/scripts/topsailai_agent_cmd/`
- **Timeout**: 600s for chat, 5s for health/status checks
- **cmd_check_health**: `/TopsailAI/src/topsailai_server/agent_community/scripts/topsailai_agent_cmd/topsailai_agent_cmd_check_health.py`
- **cmd_check_status**: `/TopsailAI/src/topsailai_server/agent_community/scripts/topsailai_agent_cmd/topsailai_agent_cmd_check_status.py`
- **cmd_chat**: `/TopsailAI/src/topsailai_server/agent_community/scripts/topsailai_agent_cmd/topsailai_agent_cmd_chat.py`

### Worker Agent 2 (hermes_agent)

- **Adaptor**: `hermes_agent`
- **API Base**: `http://172.18.0.4:8642`
- **API Key**: `416481d8bf115a0032cddd69cf787629`
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
  ACS_AGENT_API_BASE: "http://172.18.0.8:7373"
  ACS_AGENT_API_KEY: "376ee5fcda1db7b3ca8d17bc64a1d49f0b35873f535d599e3daee1a22f9f09e7"
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
   API Base: http://172.18.0.8:7373
   API Key: 376ee5fcda1db7b3ca8d17bc64a1d49f0b35873f535d599e3daee1a22f9f09e7
   API Auth: x-api-key
```

The manager-agent will then call the ACS API (`POST /api/v1/groups/:group_id/members`) to add each member. Remember that the `member_interface` field in the API request must be a **JSON string** containing the agent configuration.
