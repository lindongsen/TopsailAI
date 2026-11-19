---
maintainer: AI
author: DawsonLin
status: open
severity: medium
created: 2026-11-19
platform: windows
---

# Two Node processes share one identity and evict each other every five seconds

## Symptom

The Server log shows one node id reconnecting every five seconds, forever:

```
level=INFO msg="replacing a live connection for the same node" node_id=node_ysj64hfylk2ke3aui65fygln2e
level=INFO msg="channel established" node_id=node_ysj64hfylk2ke3aui65fygln2e generation=306
level=INFO msg="replacing a live connection for the same node" node_id=node_ysj64hfylk2ke3aui65fygln2e
level=INFO msg="channel established" node_id=node_ysj64hfylk2ke3aui65fygln2e generation=307
```

The `generation` counter reached 366 in one afternoon. The Node log shows the
matching half of the loop:

```
level=INFO  msg="handshake accepted" node_id=node_ysj64hfylk2ke3aui65fygln2e generation=344
level=INFO  msg="channel established" node_id=node_ysj64hfylk2ke3aui65fygln2e server=ws://192.168.2.3:18444/channel
level=WARN  msg="channel ended" error="websocket: close 1006 (abnormal closure): unexpected EOF" retry_in=5s
level=INFO  msg="handshake accepted" node_id=node_ysj64hfylk2ke3aui65fygln2e generation=346
```

Each side reads the loop as a network problem. Neither log names the cause,
because the cause is a second process the Node does not know about.

## Root cause

Two `connector-node.exe` processes were running from the same directory, so both
read the same `config/identity` and presented the same node id:

```
  Id StartTime              Path
2068 11/18/2026 9:54:12 PM  C:\connector-hmac\connector-node-windows-amd64\connector-node.exe
4076 11/19/2026 9:07:24 AM  C:\connector-embedded\connector-node.exe
4980 11/19/2026 10:04:45 AM C:\connector-embedded\connector-node.exe
```

PID 4076 and PID 4980 are both embedded Nodes from `C:\connector-embedded`. The
Server keeps one connection per node id, so each new connection replaces the
previous one. The replaced connection is closed, the evicted process waits its
retry interval, reconnects, and evicts the other. The cycle is stable and
self-sustaining.

PID 4076 was an orphan: its parent, PID 5508, had already exited. PID 4980 was
started by the scheduled task through `start_node.ps1`. The scheduled task
restarted the Node without terminating the previous instance, and the previous
instance survived because nothing owned it any more.

## Why the deployment did not notice

- The CLI kept working throughout. Every request landed on whichever process held
  the connection at that instant, and both processes serve the same scope, so the
  answers were correct. A functional test cannot see this defect.
- The Server log line is `level=INFO`, not a warning. A repeated INFO line that
  says "replacing a live connection" reads as normal churn rather than as a
  fault.
- The Node log line is `level=WARN` with `retry_in=5s`, which reads as a network
  fault. The retry loop is the designed behaviour for a dropped channel, so the
  log is correct about what it did and silent about why.
- Nothing in the deployment procedure checks that exactly one Node process is
  running. The procedure starts the Node and confirms the channel; it never
  counts the processes.

## Impact

- The channel is unavailable for a fraction of every five-second window, so a
  request that arrives during the swap fails with `node_offline`.
- The Server's routing registry is rewritten continuously, which is unnecessary
  load and unnecessary log volume.
- A regenerated identity would be adopted by one process and not the other,
  because each polls its own copy of the file. The two would then disagree about
  which node id they are, and the operator would see two node ids where one
  machine exists.
- The defect hides a real one: if the channel ever fails for a genuine reason,
  the log looks exactly the same.

## Fix direction

1. **The start script must refuse to start a second instance.** A lock file, a
   named mutex, or a check for an existing process from the same directory. The
   refusal must name the running process id, so the operator can act on it.
2. **The scheduled task must terminate the previous instance.** A task that
   restarts a long-lived process needs to own its lifetime, otherwise every
   restart leaves an orphan.
3. **The Node should detect a duplicate identity.** Two processes presenting one
   node id is a state the Server already reports; the Node could report it too,
   from the other side, so the operator sees the cause rather than the symptom.

Option 1 is the smallest change that removes the state. Option 2 is the correct
fix for the deployment. Option 3 is defence in depth.

## Immediate remediation applied

The orphan PID 4076 was terminated by exact process id. The Server log then
showed zero `replacing a live connection` lines over the following 45 seconds,
and the three read operations returned success. The scheduled-task instance
PID 4980 remains the only embedded Node.

## Scope

No data loss, no authorization bypass, no credential exposure. The defect is
availability and diagnosability: a channel that flaps every five seconds, and a
log that describes the flap without naming its cause.
