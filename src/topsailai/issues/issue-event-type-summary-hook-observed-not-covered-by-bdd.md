---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai
ProjectFolder: /TopsailAI/src/topsailai
ProjectRootFolder: /TopsailAI
ProjectCode: TOPSAILAI
programming_language: python
status: open
---

# Event type not covered by BDD: summary.hook.observed

## Status

Registered only. Not fixed in this change.

## Summary

`summary.hook.observed` is a real production event type, but no BDD scenario
asserts it. The other three previously uncovered event types
(`llm.response.raw`, `tool_call.warning`, `thought.line_pattern.warning`) were
covered by the same change that registers this issue.

## Producer

| Item | Value |
|---|---|
| Event type | `summary.hook.observed` |
| Producer | `hooks/points/context/summary_events_observer/observer.py:20` |
| Trigger | A context summarization Hook Point runs |
| Default state | Active whenever summarization runs |

## Why it is not covered

Reaching this producer requires a full summarization cycle: enough messages to
cross a quantity or token threshold, a real summarization LLM request, and the
Hook Point dispatch that follows. That is a materially larger scenario than the
other three, which each need only one configuration switch and one production
call.

The event is also not part of the change that wired approval and LLM request
events (`3d48db8d`, `a1b2febb`, `0ae9e7fe`), so it carries no regression risk
from that work.

## Risk assessment

| Dimension | Assessment |
|---|---|
| Changed by recent event-source work | No |
| Default enabled | Yes |
| Observed in real session files | Yes (28 and 84 records in two real sessions) |
| Failure impact if broken | Missing observability only; no business behavior change |
| Overall risk | Low |

## Evidence that it does produce records

Two real session event files written by production code contain this type:

```text
wa-a1ad42ea0a3f.3552162.session.events     28  summary.hook.observed
topsailai.282221.session.events            84  summary.hook.observed
```

This confirms the producer is reachable in real usage. It does not confirm the
payload shape, because no assertion checks it.

## What a future scenario must assert

1. A real summarization cycle runs through the real Hook Point dispatch.
2. The events file holds at least one `summary.hook.observed` record.
3. The payload carries the fields the observer writes.
4. Summarization output is unchanged by the event recording.

## Reproduction of the current gap

```text
grep -c "summary.hook.observed" tests/bdd/features/event_source_file.feature
0
```

## Scope statement

No production code, test code, or configuration was changed by this issue
record. It documents a known coverage gap so the gap is traceable rather than
silently forgotten.
