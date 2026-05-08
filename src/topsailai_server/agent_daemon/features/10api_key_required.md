---
maintainer: human
programming_language: python
---

# Required: API Key Authentication

1. There should be an environment variable to control whether api_key is enabled or not
2. When api_key is enabled and the environment variable `TOPSAILAI_AGENT_DAEMON_DEFAULT_ADMIN_KEY` is configured, it should be automatically recorded in the table record when the service starts
3. These clients/terminals need to be well supported: `topsailai_agent_client.py`, `client_go/`, `topsailai_agent_terminal.py`
