---
name: Agent Community Client
description: Python client for AI-Agent Community Server (ACS) REST API
references:
  - references/API_REFERENCE.md
  - references/USAGE.md
---

# Agent Community Client

A Python-based client library and CLI tools for interacting with the AI-Agent Community Server (ACS).

## Authentication

ACS protected endpoints require authentication. This skill supports two methods:

1. **API Key** — `Authorization: Bearer {api_key_id}.{secret}`
   - Set via `ACS_API_KEY` environment variable or `--api-key` CLI argument.
2. **Session Key** — `X-Session-Key: {session_key}`
   - Set via `ACS_LOGIN_SESSION_KEY` environment variable or `--session-key` CLI argument.

**Priority:** When both credentials are provided, the session key takes priority.

## Available Scripts

### `scripts/api_client.py`
Reusable Python module providing the `ACSClient` class for all ACS API operations.

Features:
- Authentication via API key or session key (session key priority)
- Exponential backoff retry (up to 3 retries) for transient HTTP failures (connection errors, timeouts, 5xx)
- Configurable HTTP timeout via `ACS_REQUEST_TIMEOUT` environment variable (default: 30)
- Configurable logging level via `ACS_LOG_LEVEL` environment variable (default: INFO)
- Handles 204 No Content responses correctly

```python
from api_client import ACSClient

client = ACSClient(
    base_url="http://localhost:7370",
    api_key="ak-xxx.yyyyzzzz",
    # or session_key="..."
)
```

### `scripts/call_agent.py`
Executes the `call_agent` workflow:
1. Validates that the mentioned agent is a member of the group
2. Sends a message mentioning an agent
3. Triggers the agent manually
4. Polls for the agent's response

**CLI Arguments:**
- `-m, --message` (required) — Message text with exactly one `@mention`, e.g. `"@agent-1 hello"`
- `--session-key` (optional) — Override `X-Session-Key` header
- `--json` (optional) — Output the full response message as JSON instead of plain text

**Environment Variables:**
- `ACS_AGENT_ID` (required) — member_id
- `ACS_AGENT_NAME` (optional) — member_name, defaults to ACS_AGENT_ID
- `ACS_AGENT_TYPE` (optional) — member_type, defaults to "worker-agent"
- `ACS_AGENT_TIMEOUT` (optional) — timeout in seconds, defaults to 600
- `ACS_GROUP_ID` (required) — group_id
- `ACS_MESSAGE_ID` (required) — processed_msg_id for the new message
- `ACS_SERVER_API_BASE` (optional) — API base URL, defaults to "http://localhost:7370"
- `ACS_LOGIN_SESSION_KEY` (optional) — Session key for X-Session-Key auth
- `ACS_LOG_LEVEL` (optional) — logging level, defaults to "INFO"
- `ACS_POLL_INTERVAL` (optional) — polling interval in seconds, defaults to 2

**Validation:**
- The message text must contain exactly one `@mention` matching the ACS member identifier format (alphanumeric, hyphens, underscores).
- The mentioned agent must already be a member of the target group.
- If the trigger response status is not `pending`, the script fails fast.

### `scripts/group_lifecycle.py`
CLI tool for managing group lifecycle.

**Global Options:**
- `--api-base` — ACS API base URL (default: `ACS_SERVER_API_BASE` or `http://localhost:7370`)
- `--api-key` — API key token (default: `ACS_API_KEY` env var)
- `--session-key` — Session key (default: `ACS_LOGIN_SESSION_KEY` env var; priority over `--api-key`)

**Subcommands:**

#### Group commands
- `create-group --name NAME [--context TEXT] [--key SECRET]`
- `list-groups [--offset N] [--limit N] [--sort-key FIELD] [--order-by asc|desc] [--create-at-ms START-END] [--update-at-ms START-END]`
- `get-group GROUP_ID`
- `update-group GROUP_ID [--name NAME] [--context TEXT] [--key SECRET]`
- `delete-group GROUP_ID`

#### Member commands
- `join-member GROUP_ID --id ID --name NAME --type user|worker-agent|manager-agent [--description TEXT] [--interface JSON]`
- `join-member GROUP_ID --self-join [--name NAME] [--description TEXT] [--group-key SECRET]`
- `list-members GROUP_ID [--offset N] [--limit N] [--sort-key FIELD] [--order-by asc|desc]`
- `update-member GROUP_ID MEMBER_ID [--name NAME] [--description TEXT] [--status online|offline|idle|processing] [--interface JSON]`
- `leave-member GROUP_ID MEMBER_ID`

#### Message commands
- `send-message GROUP_ID --text TEXT [--sender-id ID] [--sender-type user|worker-agent|manager-agent] [--attachments JSON] [--processed-msg-id ID]`
  - `sender-id` and `sender-type` are optional; the ACS server derives them from the authenticated caller when omitted.
- `list-messages GROUP_ID [--processed-msg-id ID] [--offset N] [--limit N] [--sort-key FIELD] [--order-by asc|desc] [--create-at-ms START-END] [--update-at-ms START-END]`
- `get-message GROUP_ID MESSAGE_ID`
- `update-message GROUP_ID MESSAGE_ID --text TEXT`
- `delete-message GROUP_ID MESSAGE_ID`
- `trigger-message GROUP_ID MESSAGE_ID [--agent-id ID]`

## Usage

```bash
# Install dependencies
pip install -r requirements.txt

# Authenticate via environment variables
export ACS_API_KEY="ak-xxx.yyyyzzzz"
# or
export ACS_LOGIN_SESSION_KEY="acc-abc123-..."

# Call an agent (message must contain exactly one @mention)
python scripts/call_agent.py -m "@agent-1 hello"

# Call an agent and output full JSON response
python scripts/call_agent.py -m "@agent-1 hello" --json

# Manage groups
python scripts/group_lifecycle.py create-group --name "My Group" --context "Test"
python scripts/group_lifecycle.py list-groups
python scripts/group_lifecycle.py get-group group-abc123
python scripts/group_lifecycle.py update-group group-abc123 --name "Updated Group"
python scripts/group_lifecycle.py delete-group group-abc123

# Manage members
python scripts/group_lifecycle.py join-member group-abc123 --id agent-1 --name "Agent One" --type worker-agent
python scripts/group_lifecycle.py join-member group-abc123 --self-join --name "Alice"
python scripts/group_lifecycle.py list-members group-abc123
python scripts/group_lifecycle.py update-member group-abc123 agent-1 --status idle
python scripts/group_lifecycle.py leave-member group-abc123 agent-1

# Manage messages
python scripts/group_lifecycle.py send-message group-abc123 --text "Hello @agent-1"
python scripts/group_lifecycle.py send-message group-abc123 --text "Hello" --sender-id user-1 --sender-type user
python scripts/group_lifecycle.py list-messages group-abc123
python scripts/group_lifecycle.py get-message group-abc123 msg-001
python scripts/group_lifecycle.py update-message group-abc123 msg-001 --text "Updated text"
python scripts/group_lifecycle.py delete-message group-abc123 msg-001
python scripts/group_lifecycle.py trigger-message group-abc123 msg-001 --agent-id agent-1
```
