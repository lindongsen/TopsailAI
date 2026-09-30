---
maintainer: AI
author: DawsonLin
---
# Initial Hooks cleanup signals historical process groups

Status: resolved by the follow-up Logical Unit 2 process-group authorization fix.

## Finding

`hooks/process_cleanup.py` `_finish_record` called `_terminate_owned` without an exited-leader guard. `_terminate_owned` sent SIGTERM before polling, and after polling/reaping a leader could still send SIGKILL on a later iteration using only the historical numeric PGID. Unlike retry cleanup and the teardown fixture, it did not fail closed when ownership became uncertain.

## Safe reproduction

Use an already-exited fake process, mock `os.killpg`, and return false from `_group_exists`. Calling the real `_finish_record` emitted one mocked SIGTERM despite the leader already being exited and the group absent. No real process or signal was used. Independent evidence: `.tmp/hooks-commit-acceptance/probe.txt`.

## Resolution

Every TERM and KILL attempt now requires the exact leader to be live and `os.getpgid(leader_pid)` to equal the owned PGID immediately before signaling. An exited leader settles only when the group is also absent; a surviving historical group, lookup error, or mismatched group identity remains cleanup debt without receiving a signal, while channel cleanup continues independently.

Deterministic regressions cover initial cleanup with a disappeared group, an uncertain surviving group, mismatched/reused group identity, leader exit between TERM and KILL, and positive escalation for a continuously live owned group.

## Verification

Complete focused colorless suite: 105 passed. Compilation, whitespace, line-limit, residual-process, and per-file diff checks passed; evidence is under `.tmp/hooks-pgid-fix/`.
