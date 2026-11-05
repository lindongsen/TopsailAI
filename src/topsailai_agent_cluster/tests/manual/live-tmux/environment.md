---
maintainer: AI
author: DawsonLin
---

# Environment and ownership

## ENV-01 Build and prerequisites

Require tmux, Go, the real TopsailAI provider, model connectivity and a valid isolated provider configuration. Build server, endpoint and CLI from the same working tree into workspace `.tmp/live-tmux-audit/bin/`; do not use stale binaries. Record build hashes, tool versions and repository revision plus dirty status. Do not persist authentication material in command transcripts.

## ENV-02 Isolation

Create a uniquely owned tmux session and server/endpoint database, ephemeral loopback ports and protected TLS/auth configuration. Start services in their own window using a supervisor; startup scripts must not drive terminal interaction. CLI configuration resides beside the binary or is passed through its supported boundary. Readiness requires a live endpoint and fresh inventory, not just a printed startup message. Keep existing user sessions untouched.

Create a test project under workspace `.tmp/live-tmux-audit/project/`, with a real chat-mode agent instructed to answer briefly and not use tools or modify files. Start agents through the CLI under test. Record every created provider ID, PID and generation in an ownership ledger. Never send or stop an agent absent from this ledger.

## ENV-03 Evidence and timing

Set terminal to 180 columns by 40 rows with scrollback sufficient for help all. For each command, capture plain and ANSI text before and after. Synchronize on a new bottom prompt and new output, not a substring remaining in scrollback. Save one transcript per case and an append-only bounded run ledger; use task-scoped retention and retain current acceptance evidence only. Model operations may need longer than inventory operations; record timeouts as failures, not empty successes. Logs may contain context; keep raw evidence local, do not copy secrets to maintained documents.

## ENV-04 Startup

Launch interactive CLI in a dedicated window. Expect table headings NO, ENDPOINT, ADAPTER, SESSION_NAME, SESSION_ID, SESSION_STATUS, DATA_STATUS, LAST_SUCCESS and one green `workspace>` prompt. A healthy session has DATA_STATUS ok; LAST_SUCCESS is local time, not an ID. Verify startup does not create an agent. Save evidence and process ownership before proceeding.
