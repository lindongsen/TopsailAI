---
maintainer: AI
author: DawsonLin
---

# `agent.model.set` is declared at the payload version, so the capability is dropped

## Symptom

The shipped Endpoint configuration declares `agent.model.set` at version `"1"`, while the
Provider advertises the same operation at `"v1"`. The capability intersection keys on
name **and** version, so the operation is silently removed from the advertised set. The
new `model set` command therefore reaches an Endpoint that does not advertise it and is
refused as unsupported, with no error at startup and no log line naming the drop.

## Evidence

Provider descriptor, read from the installed binary:

```text
$ /opt/agent-cluster/providers/topsailai/agent-cluster-provider-topsailai < describe.json
descriptor_revision: topsailai-provider-v4
  op agent.model.select v1
  op agent.model.set v1
```

Shipped template, `conf/node.endpoint.conf.example:84-85`:

```text
{"name": "agent.model.select", "version": "v1", ...}
{"name": "agent.model.set",    "version": "1",  ...}
```

Live fleet configuration, `/opt/agent-cluster/conf/endpoint/node.conf`: 62 capabilities.
Shipped template: 63 capabilities. The only name difference is `agent.model.set`, which
the live file does not declare at all, because the live file predates the template entry.

## Root cause

Two different version vocabularies were conflated. `ModelSetPayloadVersion` is `"1"`
(`internal/protocol/model_set.go:75`), and that is the **payload schema** version. The
**capability** version of every mutation operation is `operationVersion = "v1"`
(`providers/topsailai/src/protocol.go:51`, applied by `mutationOperations` at
`providers/topsailai/src/mutation.go:62`).

The sibling operation proves the distinction: `agent.model.select` is declared at `"v1"`
in the same template, and its payload version is also `"1"`
(`internal/protocol/model.go:170`). So `"v1"` is the capability version and `"1"` is the
payload version, and only `agent.model.set` was written with the wrong one.

## Why it is silent

`intersectCapabilities` (`internal/adapter/genericcli/adapter.go:1112`) builds its allowed
set from `item.Name + "\x00" + item.Version` and drops a configured capability whose key is
absent. A version mismatch is therefore indistinguishable from "the Provider does not
implement it", which is a legitimate reason to drop a capability. Nothing logs the
difference, and the Endpoint starts healthy.

The Endpoint then matches an intent on name and version
(`internal/endpoint/executor.go:691`), so the refusal is `unsupported capability`, which
reads as a client defect rather than a configuration defect.

## Why the test did not catch it

`TestEndpointConfigDeclaresTheModelSetCapability`
(`internal/tui/model_registry_test.go:44-58`) asserts that the template contains
`"version": "` + `protocol.ModelSetPayloadVersion` + `"`. It pins the payload version as if
it were the capability version, so it certifies the defect. The test's own comment states
the correct rule — "a config that names `v1` while the protocol sends `1` refuses every
request" — and then asserts the opposite of what the Provider actually advertises.

## Fix

Declare the capability at `"v1"` in the template, and change the test to assert the
capability version rather than the payload version, so the two vocabularies cannot be
confused again. The live `node.conf` files must also gain the entry, because they predate
it; that is a site-configuration correction, not a package change.

## Scope

This is a configuration and test defect, not a protocol change. The advertised capability
set of the Provider is unchanged, so `DescriptorRevision` stays at
`topsailai-provider-v4`.
