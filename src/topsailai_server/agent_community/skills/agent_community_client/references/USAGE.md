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
