---
maintainer: AI
author: DawsonLin
status: open
created: 2026-11-15
---

# Capability revision is a hardcoded label, not a capability fingerprint

## Symptom

> This section records the state on 2026-11-15. The uniform `unknown` column it describes was fixed by
> `63163fcd`; see the Symptom correction at the end of this file. The deeper defect described below is
> unchanged.

Every row of the `endpoints` table renders `CAPABILITY_REVISION = unknown`, on every node, in every
state, including nodes that advertise 59 capabilities. An operator reads a full column of `unknown`
as "no node has reported its capability version", which is a false statement about the fleet.

Verified on the live fleet on 2026-11-15 after all four Endpoints were upgraded to
`1.0.0+3233+g7dae9d69-1` and each one advertised 59 capabilities with revision `topsailai-v1`:

```text
ac.topsail           rev=topsailai-v1 caps=59 std=11 ctl=48 exec=True
ac.gd-dev            rev=topsailai-v1 caps=59 std=11 ctl=48 exec=True
ac.ai-dev            rev=topsailai-v1 caps=59 std=11 ctl=48 exec=True
ac.topsailai-dev     rev=topsailai-v1 caps=59 std=11 ctl=48 exec=True

agent-cluster-cli endpoints
ENDPOINT_ID      │ ... │ CAPABILITY_REVISION
ac.ai-dev        │ ... │ unknown
ac.gd-dev        │ ... │ unknown
ac.topsail       │ ... │ unknown
ac.topsailai-dev │ ... │ unknown
```

The two views disagree because they read different sources. `GET /api/v1/endpoints/{id}/capabilities`
reads the persisted inventory and reports the real revision. The table reads the `endpoints` row,
which the Server writes with a literal `"unknown"`.

## Evidence

- `src/main/agent-cluster-server/main.go:135` writes `CapabilityRevision: capabilityRevisionUnknown` when
  a peer connects. This is the only writer of that column on the connection path.
- `internal/storage/server/endpoints.go:35` persists whatever it is given, so the literal reaches the
  database unchanged.
- `internal/storage/server/query.go:42,54` read it back and hand it to the API and the TUI.
- `internal/tui/endpoints.go:109` renders `endpoint.CapabilityRevision` through `orDash`, so the
  literal is displayed verbatim.
- `internal/storage/server/inventory.go:20-60` (`ReplaceInventoryCommitted`) writes only
  `endpoint_session_state`. It never updates `endpoints.capability_revision`, so a successful
  inventory commit cannot correct the column.
- `internal/channel/frames.go` carries no capability revision field. The handshake exchanges protocol
  version, endpoint identity, instance ID, hostname and connection generation only, so the Server has
  no revision to record at connect time even if it wanted to.
- `internal/server/http.go:373` (`putEndpoint`) can write the column through
  `PUT /api/v1/endpoints/{id}`, but no client calls that route. It is an unused write path.

## Root cause

The column has a writer that supplies a constant and no writer that supplies an observation.

The Server learns the capability revision only after the first inventory report is committed, and that
report lands in a different table. Nothing joins the two, so the column keeps the value written at
connect time. The literal `"unknown"` is therefore not a placeholder for a value that arrives later;
it is the final value for the lifetime of the connection.

## A real value would not fix the deeper problem

Populating the column from the inventory is a small change, but it would replace one misleading
display with another, because the value it would show is not a fingerprint of the capability set.

`internal/adapter/genericcli/adapter.go:949` builds the effective descriptor as
`protocol.CapabilityDescriptor{Revision: configured.Revision}`. The revision is copied verbatim from
the `ADAPTERS` document in `node.conf`. It is never derived from the capability list, and no code
hashes the capability set:

```text
grep -rn 'sha256|Sum256' internal/adapter/genericcli/ internal/endpoint/
  internal/endpoint/replace.go:338        hashes a Provider executable
  internal/endpoint/accesspolicy.go:550   hashes a caller token
  (no capability hash anywhere)
```

Consequences of that, all verified:

- Two nodes with completely different capability sets can carry the same revision, because the
  revision is whatever the operator typed. A node that declares 3 capabilities and a node that
  declares 59 both read `topsailai-v1` if both templates say so.
- A node whose capability set changes without the operator editing `revision` keeps advertising the
  old value. Removing a `ctl.` entry from `ADAPTERS` changes the served surface and leaves the
  revision untouched.
- `docs/agent-cluster-protocol.md` stated that the Endpoint "hashes the normalized result into
  the effective capability revision advertised to the Server". No such hash exists. The document
  describes a mechanism that was never implemented.

So the column cannot be made truthful by wiring it up. It can only be made truthful by first deciding
what the value is supposed to mean.

## The revision is also a deduplication input, so a computed value would churn

`internal/protocol/command.go:266` requires the field to be non-empty, and `command.go:275,279`
include it in the canonical struct that `CanonicalHash` digests. Measured behaviour:

```text
revision "topsailai-v1"  -> 8565fa36f50f97009913c241127e4805c3fa6488c14c703cbb45d2f35b281ddb
revision ""              -> error: required immutable intent field is missing
revision "other-rev"     -> 8851c3847f1e258d7dd06ecf3f4c2a81861dca8ae224af3ba8db13ef2f3794e2
```

The hash is compared in two places, and a mismatch is a hard conflict rather than a retry:

- `internal/server/commands.go:68` returns `command ID conflicts with a different intent` when a
  repeated command ID carries a different hash.
- `internal/storage/endpoint/journal.go:44` returns `command %q conflicts with existing request`
  for the same reason.

If the revision were computed from the capability set, as the protocol document claims, then every
descriptor refresh would change it, and every in-flight command would fail its deduplication check on
replay. The Endpoint refreshes a descriptor on startup, on Adapter add or change, and on Provider
executable switch, so this is not a rare event.

`HashVersion` exists in the intent (`internal/protocol/command.go:14`) and looks like the migration
seam for exactly this problem, but it is only ever set to `"v1"`. It is never validated, never
branched on, and never used to select a hash algorithm, so the seam does not work.

## The revision gates nothing

No admission path compares the intent's revision against the Endpoint's current revision:

```text
grep -rn 'CapabilityRevision' internal/endpoint/ | grep -v _test
  (no matches)
```

The only revision comparison in the executor is `internal/endpoint/executor.go:168`, and it compares
`intent.ProfileRevision` against a launch profile revision, which is a different field with a
different meaning.

What actually decides whether an operation is served is `supports()`
(`internal/endpoint/executor.go:561`), which matches on name and version only. So a command
carrying a stale revision is accepted as long as the operation name and version are still advertised.

This contradicted `docs/agent-cluster-protocol.md`: "Capability revisions are bound to admitted
commands; a changed descriptor triggers revalidation, not silent reinterpretation." No revalidation
happens.

## Detection failure

No test asserted that the column ever held an observed value at the time this issue was written. The
TUI tests supply `CapabilityRevision` by hand, so the renderer is covered while the producer is not,
which is the same shape as `issues/model-current-column-never-populated.md`.

That gap was closed by `63163fcd`, which added
`src/main/agent-cluster-server/capability_revision_test.go`. It asserts the revision is read from the
report, that no declaring adapter yields `unknown`, and that the last declaring adapter wins. The
producer is now covered.

The protocol document was treated as a specification of implemented behaviour during review, so the
missing hash and the missing revalidation were read as existing. Both were described in the present
tense and neither existed. Both were corrected on 2026-11-18.

## Impact

At the time this issue was written the column was misleading rather than merely empty: an operator
scanning the fleet table saw a uniform `unknown` and could not tell three different situations apart:

- a node that advertises a full capability set,
- a node that advertises nothing because its `ADAPTERS` document declares no capabilities,
- a node whose adapter failed to describe itself.

The first case is healthy, the second refuses every command, and the third refuses every command with
a different error. The table rendered all three identically.

That part is fixed: the column now shows the declared revision, so the first case is distinguishable
from the other two. A node that declares no capabilities and a node whose adapter failed to describe
itself both still read `unknown`, so those two remain indistinguishable.

The deeper impact is unchanged and is the reason this issue stays open: the cluster has no working way
to detect a capability change. A node whose served surface shrinks keeps advertising the old revision,
and no admission check notices. The protocol document used to promise that a changed descriptor
triggers revalidation; nothing does, and the document now says so.

## Options

Recorded for a decision, not yet chosen.

**A. Remove the column.** Zero risk, removes a false statement. The fleet table loses a column that
currently carries no information. The `endpoints.capability_revision` column and the
`protocol.Endpoint` field can stay, because removing them needs a migration and buys nothing.

**B. Populate the column from the committed inventory.** Small change: update
`endpoints.capability_revision` inside the same transaction that commits the inventory, or read it
from `endpoints/{id}/capabilities` when rendering. This makes the table agree with the capabilities
API. It does not make the value a fingerprint, so the column would then truthfully display a
hand-written label. Acceptable only if the column is renamed or documented to mean "the revision
string this node's configuration declares", not "the version of the capability set".

**C. Make the revision a real fingerprint and implement revalidation.** This is what the protocol
document describes. It requires: computing the revision from the normalized capability set, versioning
`CanonicalHash` through `HashVersion` so old journal rows keep verifying, defining the compatibility
window during which a stale revision is still accepted, and deciding what happens to in-flight
commands when a descriptor changes. This is a cross-version migration, not a local edit.

**D. Leave it and document the limitation.** Cheapest, but the column keeps lying and the protocol
document keeps promising behaviour that does not exist.

## Related

- `issues/model-current-column-never-populated.md` — same shape: a column renders a definite value
  that no producer observes.
- `docs/agent-cluster-protocol.md` — the four claims that did not match the code were corrected on
  2026-11-18; see the Documentation correction section below.

## Documentation correction, 2026-11-18

Four statements in `docs/agent-cluster-protocol.md` described a mechanism that does not exist. All
four were corrected to state what the code does. The code was not changed.

| Line before | Claim | Correction |
|---|---|---|
| `:140` | "Capability revisions are bound to admitted commands; a changed descriptor triggers revalidation, not silent reinterpretation." | The revision is carried on every command and is part of the deduplication hash, but no admission path compares it against the Endpoint's current revision. An operation is served when its name and version are still advertised. |
| `:200` | "A descriptor or policy change produces a new Endpoint-computed effective capability revision." | A descriptor or policy change republishes the effective capability set. The revision string does not change unless the operator edits the Adapter configuration. |
| `:652` | "It hashes the normalized result into the effective capability revision advertised to the Server." | The advertised revision is the `revision` string the Adapter configuration declares, copied through unchanged. |
| `:662-663` | "Recovery computes and publishes a new effective capability revision before admitting new mutation." | Recovery re-describes the Adapter and republishes the inventory. The revision string is unchanged by that recovery. |

Verified against the code before writing:

- `internal/adapter/genericcli/adapter.go:949` builds the descriptor as
  `protocol.CapabilityDescriptor{Revision: configured.Revision}`, so the revision is the configured
  string.
- `grep -rn 'sha256|Sum256' internal/adapter/genericcli/ internal/endpoint/` finds only
  `replace.go:338` (a Provider executable) and `accesspolicy.go:550` (a caller token). No capability
  hash exists.
- `grep -rn 'CapabilityRevision' internal/endpoint/` returns nothing, so the Endpoint never produces
  or compares one.
- `internal/endpoint/executor.go:561` `supports()` matches on name and version only.
- `internal/protocol/command.go:266,279` require the revision to be non-empty and include it in the
  canonical hash struct.

The deep defect described in this issue is unchanged: the revision is still a configured label, not a
fingerprint, and no revalidation happens. Options A to D remain open.

## Symptom correction, 2026-11-18

The Symptom section above is out of date. The uniform `unknown` column it describes was fixed by
`63163fcd`: `src/main/agent-cluster-server/main.go:143` now writes
`CapabilityRevision: inventoryCapabilityRevision(report)` on the inventory path, and
`inventoryCapabilityRevision` (`:31-39`) reads the revision the adapters declared. The connect path
(`:135`) still writes `capabilityRevisionUnknown`, which is correct because no adapter declaration has
been decoded at that point.

`src/main/agent-cluster-server/capability_revision_test.go` pins the behaviour, including the case
where no adapter declares a revision and the case where the last declaring adapter wins.

So the column now shows the declared revision. It still does not show a fingerprint, which is the
defect this issue is about.

## Documentation correction, 2026-11-18 (second pass)

Four more statements described a capability revision the code does not produce. All four were
corrected to state what the code does. The code was not changed, because the deep defect is still
option A to D.

| Document | Claim before | Correction |
|---|---|---|
| `docs/agent-cluster-protocol.md:979` | The WebSocket handshake exchanges "standard Endpoint capability revision". | The handshake exchanges protocol version, endpoint identity, instance_id, connection generation and the Server database identity. The `Frame` envelope (`internal/channel/frames.go:114-175`) has no capability revision field, so the Server learns the revision only from the first committed inventory report. |
| `docs/agent-cluster-protocol.md:424` | The Endpoint owns "effective capability revisions". | The Endpoint owns the effective capability *set*. The revision string attached to it is the Adapter configuration's own `revision` value, copied through unchanged. |
| `docs/agent-cluster-database.md:43` | "Endpoint revalidates current profile/capability revisions and local policy before execution." | The Endpoint revalidates the launch profile revision (`internal/endpoint/executor.go:168`) and local policy. It does not revalidate the capability revision: no admission path compares the intent's `capability_revision` against the Endpoint's current value, and an operation is served when its name and version are still advertised (`supports()`, `executor.go:561`). |
| `docs/agent-cluster-architecture.md:291,360,421` | The Endpoint computes and publishes an "effective capability revision". | The Endpoint publishes the effective capability set. The revision beside it is the declared `revision` string, so a changed capability set does not change the revision. |

Verified before writing:

- `grep -n "CapabilityRevision" internal/channel/frames.go` returns nothing.
- `grep -rn "CapabilityRevision" internal/endpoint/*.go` returns nothing.
- `internal/adapter/genericcli/adapter.go:949` builds the descriptor as
  `protocol.CapabilityDescriptor{Revision: configured.Revision}`, and its own doc comment at `:922-923`
  states the revision is carried through unchanged.
- `internal/endpoint/executor.go:154-170` revalidates `ProfileRevision` only.

The documentation guards that read these files still pass:
`go test ./src/main/agent-cluster-endpoint/ ./internal/providercli/` is green.

## Documentation correction, 2026-11-18 (third pass)

Two more statements described a capability revision the code does not produce. Both were corrected to
state what the code does. The code was not changed, because the deep defect is still option A to D.

| Document | Claim before | Correction |
|---|---|---|
| `docs/agent-cluster-protocol.md:1047` | "the legacy launch_profile_id identifies the selected configured adapter and profile_revision carries its live capability revision." | `profile_revision` carries the launch profile's own revision, which is the provider-declared profile revision returned by `LaunchProfile` (`internal/adapter/genericcli/adapter.go:417`) and revalidated before execution (`internal/endpoint/executor.go:168`). It is not the capability revision. |
| `internal/tui/help.go:60` (the `CAPABILITY_REVISION` field help, which is also the text `agent-cluster-cli endpoints --help` prints) | "the revision of the effective capability set the endpoint advertised ... A changed revision means the endpoint's served operations changed, so a command admitted against an older revision may be refused." | The value is the `revision` string the Adapter configuration declares, copied through unchanged. It is not derived from the capability set, so a changed capability set does not change it, and no admission path compares it against a command's revision: an operation is served when its name and version are still advertised. |

The second one is the more damaging of the two, because it is the only place an operator learns what
the column means. It made three separate false claims in one sentence: that the value describes the
capability set, that a changed value implies a changed served surface, and that an older revision can
cause a refusal. All three are contradicted by the code cited in this issue.

Verified before writing:

- `internal/adapter/genericcli/adapter.go:417` returns
  `protocol.LaunchHandler{... Revision: result.Profile.Revision}`, and `result.Profile.Revision` is the
  provider-declared launch profile revision (`internal/providercli/query_types.go:22`), validated as an
  identifier at `internal/providercli/query_types.go:350`.
- `internal/endpoint/executor.go:154,168` require `intent.ProfileRevision` to be non-empty and equal to
  the current launch profile revision. That is the only revision comparison in the executor.
- `internal/adapter/genericcli/adapter.go:962` builds the capability descriptor as
  `protocol.CapabilityDescriptor{Revision: configured.Revision}`.
- `internal/endpoint/executor.go:561` `supports()` matches on capability name and version only.

### Regression guard

`internal/tui/capability_revision_help_guard_test.go` pins the corrected help text. It rejects the three
false claims and, separately, requires the entry to state what the value actually is, so an entry that
says nothing cannot pass. Both halves were proven by deliberate breakage:

- restoring the original text fails with all three claims named;
- replacing the entry with a vacuous one ("the capability revision the endpoint reported") fails the
  second test, which is the half that stops a silent deletion from passing.

The guard reads the header from `endpointColumns` rather than a literal, so a renamed column is covered
without editing the test.

### Live confirmation

The fleet still shows one revision across three nodes, which is the defect this issue is about:

```text
ac.ai-dev        CAPABILITY_REVISION topsailai-v1
ac.topsail        CAPABILITY_REVISION topsailai-v1
ac.topsailai-dev  CAPABILITY_REVISION topsailai-v1
```

The column is now truthful about what it contains: a configured label, not a fingerprint. It still
cannot tell an operator that a node's served surface changed, because nothing computes or compares one.
