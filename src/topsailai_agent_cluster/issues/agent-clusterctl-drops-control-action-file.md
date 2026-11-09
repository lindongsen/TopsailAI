---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai_agent_cluster
ProjectFolder: /TopsailAI/src/topsailai_agent_cluster
ProjectRootFolder: /TopsailAI
ProjectCode: topsailai_agent_cluster
programming_language: go
---

# agent-clusterctl never forwards CONTROL_ACTION_FILE, so no ctl. action is advertised

## Trigger

Discovered while redeploying the endpoint packages to the three nodes. The endpoint log
printed `control action file is not configured; no ctl. action is advertised and every
ctl. operation is refused` on every node, even though `node.conf` sets
`CONTROL_ACTION_FILE=conf/control-actions.conf` and the file exists with 48 actions.

## Symptom

`GET /api/v1/endpoints/{endpoint_id}/capabilities` returns 12 operations and **zero**
`ctl.` operations. The catalog file is installed and readable, but the daemon never
receives its path.

## Root cause

The binary supports the flag and the environment variable:

- `src/main/agent-cluster-endpoint/main.go:131` reads `cfg.ControlActionFile`
- `internal/config/config.go:185` registers `-control-action-file`
- `internal/config/config.go:106` reads `AGENT_CLUSTER_CONTROL_ACTION_FILE`

`scripts/agent-clusterctl` forwards the command allowlist but never the control action
file. In `start_node()` the endpoint branch builds its argv and stops after
`--command-allowlist-file`:

```bash
[ -n "${COMMAND_ALLOWLIST_FILE:-}" ] && args+=(--command-allowlist-file "${COMMAND_ALLOWLIST_FILE}")
# Adapters are supplied through the environment; no flag exists for them.
```

`load_config()` likewise resolves `COMMAND_ALLOWLIST_FILE` but not `CONTROL_ACTION_FILE`,
and `doctor()` prints the allowlist but not the catalog. The environment variable is not
set anywhere in `scripts/`, `conf/` or `docker/`, so nothing supplies the path.

## Why it was not caught

`CONTROL_ACTION_FILE` was added to the configuration template in `302f205e`, whose commit
message reads `feat: add driver column to the session list table` and does not mention the
catalog at all, and
`internal/adapter/topsailai/ctl_config_shipped_test.go` guards the template, the shipped
catalog and the deb scripts. No test asserts that the launcher forwards the key, so the
template and the launcher disagree while every test stays green.

This is the same class of defect that `d0bad293` fixed for the command allowlist. That
commit added the resolve, the doctor line and the argv entry for
`COMMAND_ALLOWLIST_FILE`; the control action file was added later and never received the
same treatment.

## Impact

Every packaged node silently loses the entire `ctl.<action>` family. The failure is
fail-closed, so nothing unsafe happens, but an operator sees an empty action surface and
cannot tell a missing catalog from a catalog that was never loaded. The bundle installer
path is unaffected only if it sets the environment variable; the packaged path is not.

## Fix

Mirrored `d0bad293` for the control action file, in `scripts/agent-clusterctl`:

1. `load_config()`: resolves `CONTROL_ACTION_FILE` the same way as the allowlist.
2. `doctor()`: prints `catalog    : ${CONTROL_ACTION_FILE:-<disabled>}`.
3. `start_node()`: appends `--control-action-file` when the value is non-empty.

`internal/adapter/topsailai/ctl_config_shipped_test.go` now carries
`TestLauncherForwardsTheControlActionCatalog`, which asserts all three sites. Asserting
only the argv entry would miss a resolve that was dropped, and asserting only the resolve
would miss a path that never reaches the binary.

### Verification

The test was confirmed to fail before it was confirmed to pass, because a test written
against the fixed script passes by construction. Reverting the script to `HEAD` produced
three failures, one per site:

```text
--- FAIL: TestLauncherForwardsTheControlActionCatalog
    the launcher must resolve CONTROL_ACTION_FILE like COMMAND_ALLOWLIST_FILE
    doctor must print the resolved catalog path
    the launcher must pass --control-action-file to the endpoint binary
```

The argv forwarding was then verified end to end against a throwaway bundle with a stub
binary that records its arguments. With `CONTROL_ACTION_FILE` configured the captured argv
contains `--control-action-file` followed by the resolved absolute path; with the key
removed the flag is absent and `doctor` prints `catalog    : <disabled>`. The live nodes
were not restarted, so the running endpoints still advertise no `ctl.` action until the
next install.

## Status

Fixed in `scripts/agent-clusterctl`, guarded by
`TestLauncherForwardsTheControlActionCatalog`. The three deployed nodes still run the
previous launcher, so they keep advertising no `ctl.` action until the package is
reinstalled. Reinstalling is an install, not a container restart: the endpoint process is
replaced by the package's own start path, and no Agent is killed by that.
