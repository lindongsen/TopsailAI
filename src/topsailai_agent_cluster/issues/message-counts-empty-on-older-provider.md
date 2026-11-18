---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai_agent_cluster
ProjectFolder: /TopsailAI/src/topsailai_agent_cluster
ProjectRootFolder: /TopsailAI
ProjectCode: topsailai_agent_cluster
programming_language: go
---

# Message counts are silently empty on a node whose provider predates `--include-runtime`

## Trigger

Observed during the `1:1.0.0+3418+g90f1228f-1` fleet redeploy on 2026-11-17. After the deployment,
`topsailai2 list` showed `MESSAGES` as `-` for every `ai-dev` row while `topsail` rows showed values
such as `2/102`.

## Symptom

The Endpoint log repeats, once per row per render:

```text
"msg":"query adapter metrics","error":"provider provider_error: provider did not report runtime message counts"
```

The rows are still listed and their `DATA_STATUS` is `ok`, so nothing looks broken. Only the
`MESSAGES` column is empty, which reads as "this session has no message counts" rather than "this
node cannot measure them".

## Root cause

Two independent facts combine.

The cluster-side batch read is new in this release. `27796790 feat: add batch message count read
across cluster layers` is an ancestor of `90f1228f` and is **not** an ancestor of the previous release
`772a2b9c`. It collects counts with one provider call:

```text
providers/topsailai/query.go:449
args := []string{"workspace", "list", "--json", "--local", "--include-runtime"}
```

`--include-runtime` was added to the provider by `d839d99a feat: add runtime and metafile fields to
workspace list json`.

The `ai-dev` container runs its own TopsailAI checkout at `8e818cb6`, which does not contain
`d839d99a`. Verified directly:

```bash
docker exec ai-dev sh -c '/TopsailAI/src/topsailai/bin/topsailai workspace list --help | grep -c include-runtime'
# 0
```

The same command on the `topsail` host returns `2`.

The provider CLI parses with `parse_known_args`, so the unknown flag is discarded without an error,
without a stderr line and with exit status 0. The returned document therefore has no `runtime` field,
and `runtimeMessageCounts` (`providers/topsailai/query.go:495`) reports
`provider did not report runtime message counts`.

## Why it was not caught

The cluster-side tests use fixtures that already contain the `runtime` field, so the code path is
covered. Nothing tests the case where the provider is older than the flag the cluster sends, because
that is a deployment property rather than a code property.

The failure is also invisible in the direction that matters: the flag is accepted silently, so the
provider looks healthy and the Endpoint reports `ok`. This is the recorded `LEARN.md` pitfall "A
silently ignored flag makes a partial fix look complete", where a discarded flag and an honoured flag
are indistinguishable by exit status or stderr.

## Impact

Fail-soft. No session is lost, no command is refused, and the inventory stays fresh. The only loss is
the message-count column on the affected node, which an operator may misread as a session with no
messages.

## Remedy

Update the TopsailAI checkout inside the `ai-dev` container to a commit that contains `d839d99a`, then
restart that Endpoint so the provider is re-described. This is a provider deployment, not a cluster
change, and it was deliberately not performed during the cluster rebuild.

## Prevention

A cluster release that starts sending a new provider flag must state the minimum provider commit in
its deployment notes, and the deployment check must compare the provider's own `--help` output against
the flags the cluster sends. Comparing the provider commit alone is not enough, because the flag can
land in a commit that the node's checkout does not have.

## Prevention implemented, 2026-11-18

The Prevention section above asked for a deployment check that compares the provider's own `--help`
output against the flags the cluster sends. The code side of that check now exists as a guard test,
because the deployment half cannot be enforced from this repository.

`providers/topsailai/workspace_list_flag_guard_test.go` adds
`TestWorkspaceListFlagsAreRegisteredByTheProvider`. It reads every production `[]string` argv that
names the `workspace list` subcommand, extracts the long flags from it, then reads the provider's own
`workspace_list_parser.add_argument` registrations from
`../../../topsailai/cli/cli_topsailai/core.py` and fails if any sent flag is not registered.

It reads the registration block rather than the whole file on purpose: a flag registered on a sibling
subparser is not accepted by `list`, which is the same distinction that made `workspace list --all`
silently return one row while `workspace --all list` returned eight.

Two deliberate breakages were proven before the test was trusted:

| Break | Failure message |
|---|---|
| Add `--not-a-real-flag` to a production argv | `this executable sends [--not-a-real-flag] on a workspace list argv, but the provider does not register them` |
| Point the guard at a copy of `core.py` with the `--include-runtime` registration removed, which is the exact defect this issue describes | `this executable sends [--include-runtime] on a workspace list argv, but the provider does not register them` |

Both were restored, and the guard passes. A probe confirmed it collects a non-empty set on both sides
(`SENT=[--include-runtime --json --local]`,
`REGISTERED=map[--include-runtime:true --json:true --local:true --session:true]`), so it cannot pass by
finding nothing.

### What this guard does not cover

It proves the flags this executable sends are registered by the provider source in this repository. It
cannot prove that a deployed node runs a checkout containing that registration, because that is a
deployment property. The `ai-dev` container still runs `8e818cb6`, which predates `d839d99a`, so the
remedy in this issue is unchanged: update that checkout and restart the Endpoint. The guard is what
keeps the code side from regressing while the deployment is corrected.
