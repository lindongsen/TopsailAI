---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai_agent_cluster
ProjectFolder: /TopsailAI/src/topsailai_agent_cluster
ProjectRootFolder: /TopsailAI
ProjectCode: topsailai_agent_cluster
programming_language: go
---

# The Server container can read the Endpoint database because the file is world-readable

## Trigger

Observed during the `1:1.0.0+3418+g90f1228f-1` fleet redeploy on 2026-11-17, while running the
container data-isolation check from the runbook.

## Symptom

The runbook expects `denied`:

```bash
docker exec agent-cluster-server-primary sh -c \
  'cat /opt/agent-cluster/data/endpoint/ac.topsail/endpoint.sqlite >/dev/null 2>&1 && echo READABLE || echo denied'
```

The actual result is:

```text
READABLE
```

## Root cause

Ownership is correct and the directory was not recursively handed to the container:

```text
drwxr-xr-x 2 root root    4096 /opt/agent-cluster/data/endpoint/ac.topsail
-rw-r--r-- 1 root root 1085440 /opt/agent-cluster/data/endpoint/ac.topsail/endpoint.sqlite
```

The container runs as uid `10001`. It cannot read through ownership, but it can read through the
world-readable bit on mode `644`. The isolation the runbook describes is therefore enforced at the
ownership layer only, and the permission layer silently defeats it.

## Why it was not caught

The check exists precisely to catch this, but it was recorded as an expectation rather than asserted
by a test, so the first time it was actually executed was during a deployment. The ownership check
(`ls -la`) passes, and ownership is the property the runbook's prose describes, so a reviewer reading
the ownership output would conclude the isolation holds.

## Impact

A Server container can read the Endpoint's SQLite database, which holds the Endpoint command journal
and resource mapping. The Server is not supposed to hold Endpoint state. The exposure is local to the
host filesystem and requires the container to be running, so it is a defence-in-depth gap rather than
a remote vulnerability.

## Remedy

Create the Endpoint database with mode `600` and its directory with mode `750`, owned by the Endpoint's
own account, so the container's uid cannot read it through any permission bit. Verify by re-running the
`cat` probe and requiring `denied`, and assert it in the packaging test rather than leaving it as a
documented expectation.

## Prevention

A documented expectation is not a check. Any isolation claim in the runbook must be backed by an
executed assertion whose failure is visible, because prose that describes ownership will keep passing
while a permission bit defeats it.

## Resolution

Fixed in `internal/storage/endpoint/db.go`. `Open` now calls `prepareDatabaseFile` before
`sql.Open`, which creates the directory at `0750` and the file at `0600`, and applies both modes
explicitly so an existing permissive file and directory are corrected on open.

### The issue's diagnosis was correct, and the creation path was confirmed

The file and directory are created by SQLite from the process umask, not by the application. No
`MkdirAll`, `Chmod` or `OpenFile` existed anywhere in `internal/storage/`, and no script creates the
per-endpoint `data/endpoint/<endpoint-id>` directory, so SQLite created both at `0755`/`0644`.

### The upgrade path is the part that matters

`os.OpenFile` applies its mode only when it creates the file, and `os.MkdirAll` leaves an existing
directory's mode untouched. A fix that only affected new installs would therefore leave every
deployed Endpoint exposed, because all of them already hold a `0644` database inside a `0755`
directory. Both modes are applied with an explicit `Chmod` for that reason.

### Verified against a copy of the real deployed database

A copy of `/opt/agent-cluster/data/endpoint/ac.topsail/endpoint.sqlite` was opened through the fixed
`Open`:

```text
before: drwxr-xr-x  .tmp/permprobe            -rw-r--r--  endpoint.sqlite
after:  drwxr-x---  .tmp/permprobe            -rw-------  endpoint.sqlite
OPEN OK
```

The real schema still opens, so the mode change does not disturb an existing database.

### Tests, each proven by deliberate breakage

`internal/storage/endpoint/db_permissions_test.go` holds four tests. Three breakages were applied and
each failed with a message naming the mode it found:

| Breakage | Failure |
|---|---|
| Remove the file `Chmod` | `endpoint.sqlite mode=0644 want=0600` |
| Remove the directory `Chmod` | `ac.topsail mode=0755 want=0750` |
| Remove the `prepareDatabaseFile` call | `unable to open database file: out of memory (14)` and `mode=0644 want=0600` |

The third breakage is the decisive one: without the fix SQLite cannot create the directory at all, and
where the directory pre-exists the file lands at `0644`, which is the deployed state.

The full mode is compared rather than only the world-readable bit, because a group-readable file would
still be readable by a container that shares the Endpoint's group.

### The documented claim was corrected

`docs/agent-cluster-architecture.md` stated that `endpoint.sqlite` "keeps its own owner, so the
container cannot read it". That sentence described ownership and was false about readability, which is
exactly the failure mode this issue's Prevention section names. It now states that ownership alone does
not provide the isolation, records the observed `READABLE` result, and points at the test that asserts
the mode.

### Not covered here

The Server database (`data/server/server.sqlite`, mode `0644`) is readable by any local account. The
Server container runs as its owner, so that is not a container-isolation defect, but the file is still
world-readable on the host. That is a separate exposure and is recorded separately rather than widened
into this fix.
