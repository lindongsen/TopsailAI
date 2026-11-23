---
maintainer: AI
author: DawsonLin
status: resolved
severity: high
created: 2026-11-23
resolved: 2026-11-23
---

# The daily task cannot commit because the systemd unit makes the repository read-only

## Symptom

The `work` task ran on schedule on 2026-11-23 (started 08:00:00, finished 08:24:01,
`exit_code: 0`, `timed_out: false`), and the scheduler correctly recorded the run as
finished. The task's own report, however, says Job 1 produced nothing:

```text
## 1. What was committed
**Nothing.** No commit hash to report.
```

The last commit in `/work` is `f8c96a5` at 2026-11-23 01:07:20, which predates the run.
So the run was supervised as successful while half of its work was impossible.

## Root cause

The scheduler's own systemd unit makes the whole filesystem read-only and then
re-opens only two paths for writing:

```ini
ProtectSystem=strict
ReadWritePaths=/work/hosts/.topsailai /work/scheduler
```

`/work` is a symlink to `/opt/git/ai/lindongsen/work`, so the repository root is
covered by `ProtectSystem=strict` and is **not** in `ReadWritePaths`. The daemon
therefore starts in a mount namespace where `/opt` is `ro`, and every process it
spawns — provider, then agent — inherits that namespace. The provider performs no
namespace isolation of its own, so this is pure inheritance, not an agent-side
sandbox.

Verified by entering the daemon's own mount namespace, which is the namespace the
agent ran in:

```text
$ nsenter -t 2748173 -m -- sh -c 'touch /work/.git/probe; touch /work/scheduler/probe'
touch: cannot touch '/work/.git/probe': Read-only file system
exit=1
# /work/scheduler/probe succeeded
```

The daemon's mountinfo shows exactly the two writable bind mounts the unit names:

```text
2809 2757 259:3 / /opt ro,relatime ... - ext4 /dev/nvme0n1p3 rw
2922 2809 259:3 /git/ai/lindongsen/work/hosts/.topsailai ... rw ...
2923 2809 259:3 /git/ai/lindongsen/work/scheduler ... rw ...
```

## Reproduction

```bash
nsenter -t "$(systemctl show -p MainPID --value topsailai_scheduler)" -m -- \
  sh -c 'touch /work/.git/probe; echo exit=$?'
```

Or from inside a task run:

```text
$ git -C /work add hosts/topsail/etc/gfw.list
fatal: Unable to create '/work/.git/index.lock': Read-only file system
```

The agent hit this 10 times, and also failed to edit `.gitignore`:

```text
[Errno 30] Read-only file system: '/work/.gitignore'
```

## Why it was not caught earlier

This was the task's first scheduled run: the journal contains exactly one
`run starting` record. The unit's `ReadWritePaths` was written for the scheduler's
own needs — the control socket, the task lock files, and the run workspace — and
those are precisely the two paths it lists. A task that only reads the repository
works fine; a task that must write `/work/.git` does not, and nothing in the unit
or the task file states that requirement.

## Impact

- The daily commit job silently degrades to an analysis-only report. Nothing is
  lost, but the repository accumulates 32 modified, 19 untracked and 9 deleted
  paths that no run can commit.
- The scheduler cannot detect this: by design it supervises liveness, not outcome,
  and the agent exits 0 after writing its report. `exit_code: 0` therefore does not
  mean the task's stated goal was met.
- The task's own "Done when" clause is satisfied on paper (the report answers all
  five points), so the failure is invisible unless someone reads the report.

## Options

1. Add the repository root, or at least `/work/.git`, to `ReadWritePaths`. This
   widens the daemon's write surface for every task, so it should be a deliberate
   decision rather than a quick patch.
2. Run commit tasks through a launcher outside the hardened unit, for example a
   separate service with its own sandbox profile.
3. Keep the sandbox and change the task so it stages its work in a writable path,
   with a host-side step performing the commit.

## Resolution

Option 1 was chosen and applied on 2026-11-23. The unit now reads:

```ini
ReadWritePaths=/work/hosts/.topsailai /work/scheduler /work/.git /work/.gitignore
```

`/work/.git` is a directory bind mount, so `git add` and `git commit` can create
`index.lock` and rewrite `index`, `HEAD`, `refs`, `logs` and `objects`.
`/work/.gitignore` is a single-file bind mount, so the daily task can add ignore
rules without opening the rest of the repository root for writing. The file must
exist before the unit starts, because systemd refuses to bind-mount a missing path.

The repository root itself stays read-only, which is intentional: the task only
needs `.git` and `.gitignore`, and keeping the rest closed means a task cannot
rewrite tracked sources by accident.

### Verification

The daemon was restarted (`systemctl daemon-reload` then `restart`) and the new
namespace was probed directly:

```text
$ nsenter -t 2018920 -m -- sh -c 'touch /work/.git/index.lock && echo OK && rm -f /work/.git/index.lock'
OK

$ nsenter -t 2018920 -m -- sh -c 'cd /work && git add README.md; echo exit=$?'
exit=0
```

The mountinfo of the running daemon shows both new bind mounts:

```text
2921 ... /git/ai/lindongsen/work/.git      /opt/git/ai/lindongsen/work/.git      rw ...
2922 ... /git/ai/lindongsen/work/.gitignore /opt/git/ai/lindongsen/work/.gitignore rw ...
```

A real commit object was written into `/work/.git` with `git commit-tree` to prove
the object store is writable, then the probe object was deleted and `HEAD` was
confirmed unchanged. The `.gitignore` round trip was also verified: append a rule,
`git status` reports the modification, restore the original, `git status` is clean
again, and the md5 returns to `b83d46dfe9b32f22388838058e74cab1`.

The service restarted cleanly with `NRestarts=0` and no WARN or ERROR records.

### Remaining limitation

The scheduler still cannot tell whether a run achieved its goal: `exit_code` comes
from the launcher and is 0 whenever the agent exits normally. The task file now
carries a `last-run.json` status marker and a mandatory `RESULT:` first line so the
outcome is machine-readable and visible without reading the whole report.

### Correction to the symptom section

The last commit before the run was `f8c96a5` at 01:07:20. A manual commit
`43e82d8` ("update", DawsonLin) was made at 08:56:53, after the run finished, so
`HEAD` is now `43e82d8`. This does not change the analysis: the run itself
committed nothing.
