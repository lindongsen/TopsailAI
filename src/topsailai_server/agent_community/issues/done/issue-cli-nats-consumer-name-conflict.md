---
status: fixed
related_plan: Manual_Test_Plan_04_CLI_Commands_and_Cluster.md
related_test_case: "4.6"
component: CLI / NATS
severity: medium
---

# CLI NATS Consumer Name Conflict Prevents Multi-User Real-Time Messaging

## Summary

When two `acs-cli` instances subscribe to the same group, the second instance fails to create a NATS durable consumer because the consumer name is hardcoded as `cli-{group_id}`. NATS reports that the consumer is already bound to a subscription, and the CLI falls back to HTTP polling. This breaks the documented real-time messaging experience for multiple CLI users in the same group.

## Steps to Reproduce

1. Start an ACS server with NATS enabled and `ACS_GROUP_MANAGER_AGENT_CMD_CHAT` configured (so groups auto-join a manager-agent).
2. Create two user accounts (`CLI User A`, `CLI User B`) and API keys for each.
3. Create a public group and add both users as members.
4. Start two tmux sessions:
   - Session A: `./bin/acs-cli -api-base http://localhost:7370 -api-key <USER_A_KEY> -nats-url nats://localhost:4222`
   - Session B: `./bin/acs-cli -api-base http://localhost:7370 -api-key <USER_B_KEY> -nats-url nats://localhost:4222`
5. In session A, run `/group:enter <group_id>`. Observe "Subscribed to group ... via NATS".
6. In session B, run `/group:enter <group_id>`.

## Expected Behavior

Both CLI instances subscribe to the group via NATS and receive messages in real time.

## Actual Behavior

Session B logs:

```
Failed to subscribe via NATS: failed to subscribe to group <group_id>: consumer is already bound to a subscription
Falling back to HTTP polling mode.
```

Session B then receives messages via HTTP polling (with a noticeable delay) instead of NATS push delivery.

## Root Cause

In `internal/nats/subscriber.go`, the durable consumer name for CLI group subscriptions is hardcoded:

```go
sub, err := jsSubscribe(s.js, subject, func(msg *nats.Msg) {
    ...
}, nats.Durable("cli-"+groupID), nats.ManualAck())
```

Because the name is identical for every CLI instance (`cli-{group_id}`), only the first instance can bind the durable consumer. Subsequent instances receive the "already bound" error.

## Suggested Fix

Make the durable consumer name unique per CLI instance. Options:

1. Include a UUID or process ID in the consumer name, e.g. `cli-{instance_id}-{group_id}`.
2. Use an ephemeral (non-durable) consumer for CLI subscriptions if durability is not required.
3. Allow the CLI to specify a unique consumer name suffix via a command-line flag or generate one on startup and store it for the process lifetime.

The same issue may affect `SubscribeAllGroups` (`cli-all-groups`) and `SubscribePendingMessages` (`pending-monitor-{group_id}`) if multiple CLI/server instances use those subscribers.

## Environment

- Server: `acs-server` built from `/TopsailAI/src/topsailai_server/agent_community` at 2026-06-26 09:20 CST
- CLI: `acs-cli` built from same source
- NATS server: `nats://localhost:4222`
- Group: `group-9cd81e3e81f0474eb6c8c9d3c1798889`
- Test users: `acc-45a07dc2294c4e2285d8f6d8f05b0ff4`, `acc-a7c9185e0dab4ca582b68d97f841530b`

## Impact

- Test Case 4.6 (CLI With NATS Real-Time Messaging) cannot pass as documented.
- Any production deployment where multiple users run the CLI against the same group will experience delayed/polled message delivery instead of real-time NATS delivery.

## Resolution

- `internal/nats/subscriber.go`: Added per-subscriber `instanceID` and `NewSubscriberWithInstanceID`. Durable consumer names are now scoped per instance (`cli-{group_id}-{instance_id}`, `cli-all-groups-{instance_id}`, `pending-monitor-{group_id}-{instance_id}`, `heartbeat-monitor-{instance_id}`), allowing multiple CLI/server instances to subscribe to the same group simultaneously.
- `cmd/cli/nats.go`: `NATSManager` now generates a UUID instance ID on creation and passes it to `NewSubscriberWithInstanceID`.
- `cmd/cli/chat.go`: Updated chat help and command handling to prefer `/member:list` while keeping `/members` as an alias.
- `internal/nats/subscriber_test.go`: Added reflection-based helpers to inspect `nats.SubOpt` durable names and added tests for unique durables across instances, instance ID generation, and existing unsubscribe/handler behavior.
- `cmd/cli/nats_test.go`: Updated fake subscriber factory signatures to include `instanceID`.

Fixed by km3-programmer on 2026-06-26.
