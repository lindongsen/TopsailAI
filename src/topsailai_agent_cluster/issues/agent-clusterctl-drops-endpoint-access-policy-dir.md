---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai_agent_cluster
ProjectFolder: /TopsailAI/src/topsailai_agent_cluster
ProjectRootFolder: /TopsailAI
ProjectCode: topsailai_agent_cluster
programming_language: go
---

# agent-clusterctl never forwards ENDPOINT_ACCESS_POLICY_DIR, so a packaged node stays permissive

## Trigger

Discovered while configuring the three deployed endpoints for the gd-dev live acceptance. The
policy directory had to be passed by hand as `--endpoint-access-policy-dir /opt/agent-cluster/policy`
on every restart, because nothing in the packaged start path supplies it.

## Symptom

A node started through `scripts/agent-clusterctl` runs with no access policy directory, so it
accepts every caller. The Endpoint log shows no `loaded endpoint access policy` line at all, and
`grep -c "access policy refused"` stays zero no matter which token the caller presents. The
failure is fail-open, which is the opposite of the `ctl.` catalog defect: an unconfigured catalog
refuses everything, while an unconfigured policy directory permits everything.

## Root cause

The binary supports the flag:

- `internal/config/config.go` registers `-endpoint-access-policy-dir`
- `src/main/agent-cluster-endpoint/main.go:208-230` loads the directory and logs
  `loaded endpoint access policy path=... tokens=N`

`scripts/agent-clusterctl` forwards the command allowlist and the control action catalog but never
the policy directory:

```text
$ grep -n "ENDPOINT_ACCESS_POLICY_DIR\|ACCESS_POLICY\|POLICY_DIR" scripts/agent-clusterctl
(no output)
$ grep -n "COMMAND_ALLOWLIST_FILE\|CONTROL_ACTION_FILE" scripts/agent-clusterctl
260:  [ -n "${COMMAND_ALLOWLIST_FILE:-}" ] && args+=(--command-allowlist-file "${COMMAND_ALLOWLIST_FILE}")
265:  [ -n "${CONTROL_ACTION_FILE:-}" ] && args+=(--control-action-file "${CONTROL_ACTION_FILE}")
```

`/opt/agent-cluster/conf/node.conf` (658 bytes) carries `COMMAND_ALLOWLIST_FILE` and
`CONTROL_ACTION_FILE` but no policy key, so the launcher has nothing to forward even if it
supported the key.

## Why it was not caught

The policy directory is a newer configuration surface than the launcher. The launcher is extended
key by key, and each new key lands in the binary, the documentation and the template while the
launcher keeps its previous key list. Every test that guards the template stays green because the
template really is correct.

This is the third instance of the same class in this file: `d0bad293` added the allowlist
forwarding, `issues/agent-clusterctl-drops-control-action-file.md` recorded the catalog omission,
and this issue records the policy omission. The pattern is that a new Endpoint conffile key is
added without a launcher test.

## Impact

Every packaged node silently stays permissive. An operator who writes a policy directory and
expects it to be enforced gets no enforcement and no error, because the directory is simply never
read. The only symptom is the absence of a log line that nobody looks for when nothing appears
broken.

The live acceptance was not affected because the three endpoints were restarted by hand with the
flag. A real deployment through the package would be.

## Fix

Mirror the existing two keys in `scripts/agent-clusterctl`:

1. `load_config()`: resolve `ENDPOINT_ACCESS_POLICY_DIR` the same way as the allowlist.
2. `doctor()`: print `policy     : ${ENDPOINT_ACCESS_POLICY_DIR:-<permissive>}`.
3. `start_node()`: append `--endpoint-access-policy-dir` when the value is non-empty.
4. `conf/node.conf`: add `ENDPOINT_ACCESS_POLICY_DIR=policy` beside the other two keys.

A test must assert all four sites, following `TestLauncherForwardsTheControlActionCatalog`. It must
be confirmed to fail before it is confirmed to pass, because a test written against the fixed
script passes by construction.

## Status

Open. Not fixed in this task, because the live acceptance used a hand-written restart path and the
launcher change needs its own red-before-green test. The three deployed endpoints currently run
with the flag supplied by hand, so they enforce the policy until the next launcher-driven restart.
