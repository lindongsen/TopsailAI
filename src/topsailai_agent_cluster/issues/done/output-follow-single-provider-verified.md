---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai_agent_cluster
ProjectFolder: /TopsailAI/src/topsailai_agent_cluster
---

# Output follow is verified against one provider only

## Trigger

An operator runs `logs --follow` against an Endpoint whose adapter is not the
TopsailAI adapter, for example a deployment configured with the generic
`command` provider type.

## Observed behavior

The generic `commandAdapter` (`internal/adapter/command.go`) implements
`Describe`, `Discover`, `Inspect`, `Execute`, `ReadOutput`, `QueryCommand`,
`Watch` and `Close`. It has no `FollowOutput` method, so it does not satisfy
`adapter.OutputFollower`. A follow request against it correctly returns
`unsupported`.

Every live follow verification therefore runs through the TopsailAI adapter and
the TopsailAI fixture. The BDD scenarios, the harness smoke test and the manual
checks all use that one provider.

## Impact

The protocol claims `output.follow` is a capability an Endpoint may advertise,
and the Server, channel, Endpoint and CLI layers are provider-neutral. Only the
adapter layer has been exercised with a real streaming provider, so the following
remain unproven:

- Whether a second provider can satisfy the `OutputFollower` contract without
  changing any Server, channel or CLI code.
- Whether the record shape the CLI renders is genuinely provider-neutral, or
  whether it happens to match the TopsailAI line format.
- Whether the `unsupported` path is the only honest answer for a provider that
  cannot stream, or whether some providers need a different degradation.

The abstraction is therefore asserted by design and by unit tests with fakes, but
not demonstrated by a second real implementation.

## Root cause

The first release deliberately shipped one adapter. Adding `FollowOutput` to the
generic `commandAdapter` was rejected because it would advertise streaming for
every `command`-type deployment, including executables that cannot stream, which
is exactly the false capability the protocol forbids. That decision is correct,
but it left no second real provider to prove the seam.

## Proposed resolution

- Implement a second adapter, ideally one with materially different streaming
  semantics rather than a copy of TopsailAI, and run the same follow scenarios
  against it.
- Keep the generic `commandAdapter` without `FollowOutput`; a provider that can
  stream should declare it explicitly rather than inherit it.
- Add a contract test that any adapter advertising `output.follow` satisfies
  `adapter.OutputFollower`, so a future adapter cannot advertise a capability it
  does not implement.
- Record in the adapter document which provider proved which capability, so the
  claim is traceable rather than implied.

## Verification

- The follow BDD scenarios run against the second provider and pass unchanged,
  proving no Server, channel or CLI change was needed.
- A contract test enumerates adapters that advertise `output.follow` and asserts
  each implements `adapter.OutputFollower`.
- A test asserts a provider without the capability still returns `unsupported`
  rather than an empty successful stream.

## Resolution

Resolved on 2026-11-18 by commit `864ecf6e`. The contract test this issue asks for
is implemented, and writing it exposed a real defect that made the test vacuous
until it was fixed.

### The quoted code no longer exists

`internal/adapter/command.go` and its `commandAdapter` were deleted when the
independent Provider CLI replaced the command-based seam. The issue's Trigger and
Observed behavior sections therefore describe a component that is gone. The
underlying question is still valid, but it now applies to the Generic CLI Adapter
and the Provider CLI contract.

### The contract test would have proven nothing

The proposed resolution asks for "a contract test that any adapter advertising
`output.follow` satisfies `adapter.OutputFollower`". A probe showed that no
adapter could ever advertise it, so the test would have enumerated an empty set
and passed while proving nothing:

```text
configured=3 survived=1 names=[message.send]
capability "output.read" was dropped by the intersection
capability "output.follow" was dropped by the intersection
```

`intersectCapabilities` compared every configured capability name against the
provider's **operation** list only. A read surface is served by a function or a
query, and the two vocabularies differ: the Cluster names a capability after what
the operator asks for (`output.follow`), while the Provider names the function
after what it does (`follow_output`). Three capabilities were affected, not one:

| Cluster capability | Provider contract | Kind | Implementation site |
|---|---|---|---|
| `output.read` | `read_output` | function | `adapter.go:329` |
| `output.follow` | `follow_output` | function | `adapter.go:344` |
| `agent.model.list` | `model.catalog` | query | `adapter.go:444` |

The defect was latent rather than user-visible, because no deployed configuration
declares any of the three: `/opt/agent-cluster/conf/endpoint/node.conf` has 42
capabilities and none of them is an output or model capability. The follow path
worked because it gates on an interface assertion (`executor.go:396`,
`follow.go:36`) rather than on the advertised capability, so "what is advertised"
and "what is implemented" were two independent mechanisms that could disagree —
exactly the false-capability condition the protocol forbids.

### What was changed

`intersectCapabilities` now takes the whole `providercli.Descriptor` instead of
individual contract lists, so a fifth list cannot be forgotten. A new
adapter-local table `capabilityProviderContract` translates the three affected
capabilities onto their Provider contracts. A function is matched by name because
it carries no version; a query is matched by name and version because it does. An
unknown capability name is still dropped, so the intersection stays fail-closed.

The table lives in the adapter rather than the protocol because translating a
Cluster capability onto a Provider contract is the adapter's job; the Cluster
vocabulary stays closed and provider-neutral.

### Tests

`capability_contract_test.go` holds eight intersection tests, each with its
positive and negative pair: a configured capability survives when the provider
advertises the implementing contract, and is dropped when it does not. The query
kind also has a version-mismatch case, and one test asserts an unknown name is
dropped while the provider advertises everything the table knows about.

`capability_advertisement_test.go` holds the contract test this issue asks for. It
drives the real `Describe` and `FollowOutput` methods and asserts the two agree in
both directions: a provider that implements the stream must advertise the
capability and must not report `unsupported`, and a provider that cannot stream
must not advertise it and must report `unsupported`. The same pair is asserted for
`output.read` and `agent.model.list`.

Four deliberate breakages were each confirmed to fail before being restored:

| Breakage | Failure |
|---|---|
| Function branch always false | `effective capabilities = [], want the configured read kept because the provider advertises "read_output"` |
| Query matched by name only | `effective capabilities = [agent.model.list], want none because the provider advertises "model.catalog" at another version` |
| Unknown name kept (fail-open) | `effective capabilities = [fixture.unknown_read], want none because no Provider contract implements "fixture.unknown_read"` |
| Original defect restored | `advertised output.follow = false, want true; published capabilities = []` |
| `FollowOutput` always unsupported | `advertised output.follow = true but FollowOutput reported unsupported = true: the published surface and the implementation disagree` |

The last breakage is the one that proves the contract test is not vacuous: it
detects the advertisement and the implementation disagreeing, which is the
property the issue exists to protect.

### Still open

Two parts of the proposed resolution are not done, and neither is a defect fix:

- A second real provider with materially different streaming semantics. This
  remains the only way to prove the seam end to end, and it is a feature rather
  than a correction.
- Recording in the adapter document which provider proved which capability. The
  document currently states the contract but not the evidence behind it.
