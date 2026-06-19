---
status: open
priority: medium
component: testing
---
# Mock agent scripts require a live HTTP endpoint on port 18080

## Summary
The bundled mock agent scripts (`scripts/mock_agent_cmd_chat.sh` and `scripts/mock_agent_cmd_check_health.sh`) call `curl` against `ACS_AGENT_API_BASE` (default `http://127.0.0.1:18080`). This makes them unsuitable for offline CLI/manual testing unless a separate mock HTTP server is running.

## Steps to Reproduce
1. Configure the server with `ACS_GROUP_MANAGER_AGENT_CMD_CHAT=/path/to/mock_agent_cmd_chat.sh`.
2. Start the server without running a mock agent HTTP server on port 18080.
3. Create a group and send a message that triggers the manager-agent.

## Expected Result
The mock script should produce a deterministic response using only the environment variables passed by ACS, without requiring an external HTTP service.

## Actual Result
`curl` fails to connect to `127.0.0.1:18080`. The agent chat command exits with code 1 and ACS records a failure.

## Root Cause
- `scripts/mock_agent_cmd_chat.sh` builds a JSON payload and POSTs it to `${API_BASE}/chat`.
- `scripts/mock_agent_cmd_check_health.sh` GETs `${API_BASE}/health`.
- Neither script has a no-network fallback mode.

## Affected Files
- `scripts/mock_agent_cmd_chat.sh`
- `scripts/mock_agent_cmd_check_health.sh`
- `scripts/mock_agent_cmd_chat_fail.sh` (already offline, but only for failure cases)

## Suggested Fix
Add an offline mode to the mock scripts:
- If `ACS_AGENT_API_BASE` is empty or equals a sentinel such as `offline`, echo a canned response derived from `ACS_AGENT_MESSAGE`.
- Example offline response: `[Mock Agent] Received: ${ACS_AGENT_MESSAGE:0:200}`.
- Keep the HTTP mode when `ACS_AGENT_API_BASE` is explicitly set to a URL.

## Workaround
Create a custom echo mock script:
```bash
#!/bin/bash
echo "[Mock Agent] mode=${ACS_AGENT_MODE} msg=${ACS_AGENT_MESSAGE}"
```
Use this script as `cmd_chat` in `member_interface`.

## Related
- ORIGIN.md: Agent interface environment variables.
- docs/Environment_Variables.md: Agent chat environment variables.
- issue-mock-agent-empty-message-content.md: Related mock agent behavior.
