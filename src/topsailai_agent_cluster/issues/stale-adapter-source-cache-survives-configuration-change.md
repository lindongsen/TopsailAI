---
maintainer: AI
author: DawsonLin
status: resolved
---

# Stale Adapter source cache survives configuration changes

## Symptom

After Adapter IDs changed during deployment, one online Endpoint published both the old and current Adapter snapshots. The operator `list` therefore showed the same provider sessions twice with different cluster resource IDs.

## Root cause

`NewCollector` restored every row from the Endpoint `source_cache` table without checking whether that Adapter ID still existed in current configuration. Collection updated only configured bindings, so an old row was never replaced or removed and remained in every composite inventory.

## Resolution

Collector startup now restores only configured Adapter IDs. Endpoint source cache also has a bounded lifecycle: `AGENT_CLUSTER_ENDPOINT_SOURCE_CACHE_EXPIRY` defaults to `10m`, and each collection deletes source snapshots whose last successful observation is older than the retention window. A cache that never succeeded uses its database update time. Resource mappings and command evidence are retained because they are durable identity and execution history, not inventory cache.

## Prevention

Trigger: an Adapter is renamed, removed, or fails longer than the source-cache retention window.

Action: filter restored cache by current binding identity and expire durable and in-memory source snapshots before composing the next report.

Why this prevents recurrence: removed Adapters cannot re-enter a report after restart, and a configured but unavailable Adapter cannot preserve obsolete sessions indefinitely. Automated tests cover configuration filtering, expiry before failed discovery, durable-record preservation, environment validation, and launcher forwarding.
