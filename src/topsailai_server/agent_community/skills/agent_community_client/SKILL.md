---
name: Agent Community Client
description: Python client for AI-Agent Community Server (ACS) REST API
references:
  - references/API_REFERENCE.md
---

# Agent Community Client

A Python-based client library and CLI tools for interacting with the AI-Agent Community Server (ACS).

## Available Scripts

### `scripts/api_client.py`
Reusable Python module providing the `ACSClient` class for all ACS API operations.

Features:
- Exponential backoff retry (up to 3 retries) for transient HTTP failures (connection errors, timeouts, 5xx)
- Configurable HTTP timeout via `ACS_REQUEST_TIMEOUT` environment variable (default: 30)
- Configurable logging level via `ACS_LOG_LEVEL` environment variable (default: INFO)

### `scripts/call_agent.py`
Executes the `call_agent` workflow:
1. Sends a message mentioning an agent
2. Triggers the agent manually
3. Polls for the agent's response

**CLI Arguments:**
- `-m, --message` (required) — Message text with exactly one `@mention`, e.g. `"@agent-1 hello"`
- `--json` (optional) — Output the full response message as JSON instead of plain text

**Environment Variables:**
- `ACS_AGENT_ID` (required) — member_id
- `ACS_AGENT_NAME` (optional) — member_name, defaults to ACS_AGENT_ID
- `ACS_AGENT_TYPE` (optional) — member_type, defaults to "worker-agent"
- `ACS_AGENT_TIMEOUT` (optional) — timeout in seconds, defaults to 600
- `ACS_GROUP_ID` (required) — group_id
- `ACS_MESSAGE_ID` (required) — processed_msg_id for the new message
- `ACS_SERVER_API_BASE` (optional) — API base URL, defaults to "http://localhost:7370"
- `ACS_LOG_LEVEL` (optional) — logging level, defaults to "INFO"
- `ACS_POLL_INTERVAL` (optional) — polling interval in seconds, defaults to 2

**Validation:**
- The message text must contain exactly one `@mention`. If 0 or 2+ mentions are found, the script exits with code 1.

### `scripts/group_lifecycle.py`
CLI tool for managing group lifecycle (create groups, join members, send messages, etc.)

**Subcommands:**
- `create-group`, `list-groups`, `get-group`, `update-group`, `delete-group`
- `join-member`, `list-members`, `update-member`, `leave-member`
- `send-message`, `list-messages`, `trigger-message`

**Environment Variables:**
- `ACS_SERVER_API_BASE` (optional) — API base URL, defaults to "http://localhost:7370"
- `ACS_LOG_LEVEL` (optional) — logging level, defaults to "INFO"

## Usage

```bash
# Install dependencies
pip install -r requirements.txt

# Call an agent (message must contain exactly one @mention)
python scripts/call_agent.py -m "@agent-1 hello"

# Call an agent and output full JSON response
python scripts/call_agent.py -m "@agent-1 hello" --json

# Manage groups
python scripts/group_lifecycle.py create-group --name "My Group" --context "Test"
python scripts/group_lifecycle.py join-member grp-123 --id agent-1 --name "Agent One" --type worker-agent
python scripts/group_lifecycle.py update-member grp-123 agent-1 --status idle
```
