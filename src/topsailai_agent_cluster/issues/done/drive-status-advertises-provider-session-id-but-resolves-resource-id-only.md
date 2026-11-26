---
maintainer: AI
author: DawsonLin
status: done
---

# `drive status` advertises three identifier forms but resolves only a cluster resource ID

## Symptom

`agent-cluster-cli help drive` states:

```text
session: optional session/resource ID, provider session ID, or a bare list row number
```

`drive status` accepts only the cluster resource ID. A provider session ID is refused, and a bare row
number is not resolved on the standalone surface.

## Evidence

| Probe | Result |
|---|---|
| `agent-cluster-cli drive status ac.ai-dev res_50da448edfd53f9b19032af9354c290e` | renders `drive_reason: process_verified`, `drive_pid: 3743534` |
| `agent-cluster-cli drive status ac.ai-dev 20261123131848` | `session "20261123131848" was not reported by endpoint "ac.ai-dev"` |
| `agent-cluster-cli help drive` | advertises the provider session ID form |

Source: `internal/tui/drive_status.go:45` looks the session up by cluster resource ID only.

## Impact

The refusal message says the session "was not reported by the endpoint", which is false: the session
is reported, and the same endpoint reports it under its cluster resource ID. An operator reading that
message concludes the session is missing or the endpoint is stale, and investigates the inventory
instead of the identifier. The advertised form is the one an operator is most likely to have in hand,
because it is what `messages` requires.

## Why it survived review

The help text is shared with `drive start` and `drive stop`, which do accept the provider session ID
through the adapter's handle resolution. Only `drive status` reads the persisted inventory, and it
reads it by resource ID. One help entry therefore describes three subcommands with two different
resolver capabilities.

## Suggested repair

Either resolve the provider session ID in `drive status` by matching the persisted inventory row, or
narrow the `drive status` help entry to the identifier it actually accepts. The second is smaller and
honest; the first is better for the operator, because it makes the three subcommands agree.

## Resolution

Fixed by the first option: `drive status` now resolves the provider session ID.

`resolveDriveSession` searches the cluster resource ID namespace first and the
provider session ID namespace second, mirroring the existing
`findInfoSession`/`matchInfoSession` pattern. The resource ID keeps precedence
because it is the routing identity, so a token that is both keeps its routing
meaning. Several matches inside one endpoint are refused with the count and the
remedy rather than resolved to the first row, because one provider session can own
several rows and silently choosing one would report a different row's controller.
An empty provider session ID never matches, because an unverified row carries no
identifier to match against.

The `drive` help entry was rewritten to state the real asymmetry: `status` accepts
either identifier, while `start` and `stop` still require the cluster resource ID
because they address a live process and must carry a generation. Verified live:
`--yes drive start ac.ai-dev 20261123131848 gen-x` returns
`target_not_found` / `not_applied`, so nothing was started.

Verified live: `drive status ac.ai-dev 20261123131848` exits 0 and reports
`session: res_50da448edfd53f9b19032af9354c290e`, `drive_state: none`.
