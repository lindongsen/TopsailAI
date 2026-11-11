---
maintainer: AI
author: DawsonLin
status: specification
---

# Feature: Live inventory is current, bounded, and honest

## Background

Given the live environment and authentication baseline passed
And at least one Endpoint reports a real provider inventory
And the operator recorded the expected test-owned sessions
And inventory reads use the Server's persisted latest state

## Scenario INV-LIVE-001: List every registered Endpoint

Given multiple Endpoints are registered
When the CLI lists the workspace
Then every registered Endpoint appears exactly once
And online, suspect, and offline state is shown separately from Agent state
And list order is deterministic across unchanged reads

## Scenario INV-LIVE-002: List sessions from the persisted latest document

Given the Endpoint has published a valid complete inventory
When the CLI lists sessions without forcing collection
Then the rows match the latest committed document
And each row is associated with the correct Endpoint
And the read does not invoke provider discovery

## Scenario INV-LIVE-003: Show a session using its stable identity

Given a test session appears in inventory
When the operator selects it by Endpoint and stable session ID
Then complete standard details are shown
And a row number, display name, or bare PID is not used as routing identity
And observation time and freshness are visible

## Scenario INV-LIVE-004: Forced refresh commits before returning

Given the provider inventory changes after the last periodic report
When the operator forces collection for that Endpoint
Then one fresh collection attempt occurs
And the response is the document re-read after commit
And an immediate ordinary read returns the same revision and document
And the response does not claim every adapter was fresh when collection is degraded

## Scenario INV-LIVE-005: Workspace refresh isolates one Endpoint failure

Given at least two Endpoints are registered
And one Endpoint can refresh while another is unavailable
When the operator refreshes workspace scope
Then healthy Endpoint results are rendered
And the unavailable Endpoint has a per-Endpoint diagnostic
And one failure does not erase or replace healthy data
And each Endpoint is requested at most once for this command

## Scenario INV-LIVE-006: One failed adapter preserves its last-known section as stale

Given an Endpoint has at least two adapter sources with previous successful data
And one source fails its next collection
When a new composite inventory is committed
Then the healthy source publishes its new data
And the failed source retains last-known returned data marked stale with an error
And the whole report is degraded rather than fabricated as empty

## Scenario INV-LIVE-007: A source that never succeeded is unknown

Given one configured adapter source has never completed successfully
When the Endpoint publishes a structurally complete report
Then that source is represented as unknown with its bounded error
And it is not represented as a successful empty inventory
And healthy sources remain visible

## Scenario INV-LIVE-008: A successful empty source clears only that source

Given a source previously reported sessions
And the provider now successfully reports no sessions for that source
When the new composite inventory commits
Then old rows for that source disappear
And rows from other sources remain unchanged
And no per-session deletion history is invented

## Scenario INV-LIVE-009: Malformed or incomplete inventory never replaces valid state

Given the Server has a valid committed inventory
When an oversized, malformed, truncated, incomplete, or identity-mismatched report is submitted
Then the report is rejected visibly
And the prior committed inventory remains readable
And the rejection is not interpreted as an empty inventory

## Scenario INV-LIVE-010: Older and duplicate revisions cannot overwrite newer state

Given a newer snapshot revision is committed
When an older revision arrives
Then it is ignored or rejected without changing stored state
When the same revision and identical content arrives
Then it is acknowledged idempotently
When the same revision with different content arrives
Then it is rejected as a conflict
And timestamps alone do not override revision ordering
