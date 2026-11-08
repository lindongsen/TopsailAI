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
