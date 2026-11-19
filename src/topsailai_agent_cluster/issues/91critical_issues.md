---
maintainer: AI
author: DawsonLin
---

# Critical issues

## 2026-11-19 — `docker restart` on ai-dev killed a running Agent

### What happened

At `2026-11-19T07:28:48` the command

```bash
for c in ai-dev topsailai-dev; do
  docker restart "$c" >/dev/null 2>&1 && echo "$c restarted"
done
```

was run to reset the Endpoint connection generation after the primary Server container was
recreated. Both containers stopped and started 0.46 s apart.

`ai-dev` hosts Agents. Restarting the container killed Agent `wa-d3ea717b411f` (pid 1783182)
mid-turn.

### Evidence

| Fact | Value |
|---|---|
| Container `Created` | `2025-10-21T04:42:30Z` (never recreated) |
| Container `FinishedAt` | `2026-11-18T23:28:48.540684859Z` |
| Container `StartedAt` | `2026-11-18T23:28:49.000877283Z` |
| Container log last line | `2026-11-18T23:28:48.505510725Z Shutting down, got signal: Terminated` |
| Killed Agent last event | `2026-11-19T07:28:48.309845+08:00 tool_call.end file_tool-read_file_lines` |
| Killed Agent meta | `status: running`, `end_ts: null`, `pid: 1783182` |
| Killed Agent pid now | gone, both on the host and inside the container |

The Agent was reading `internal/tui/interactive_shell_test.go` to confirm the documented behaviour
of bare `!`. Its last recorded state is `running`, so the session is dead but recorded as alive.

### Why it was wrong

The runbook `note--agent-cluster-deb-rebuild-and-redeploy-runbook` states twice:

> Only the Endpoint processes inside ai-dev and topsailai-dev were restarted. The containers
> themselves were not restarted, because recreating them would kill the Agents that share their
> lifecycle boundary.

and:

> `ai-dev` and `topsailai-dev` are `/pause` containers whose endpoint is started by
> `agent-clusterctl start` inside the container, not by the container entrypoint. A
> `docker restart` or a container recreate therefore leaves the endpoint process gone, and the
> container log shows only repeated `Shutting down, got signal: Terminated`. Start it again
> explicitly.

The permitted form is:

```bash
docker exec ai-dev sh -c 'cd /opt/agent-cluster && ./agent-clusterctl -c conf/endpoint/node.conf restart'
```

That restarts one process inside the container and leaves the Agents alone. It also achieves the
stated goal, because the connection generation is held by the Endpoint process, not by the
container. The forbidden form was therefore never necessary.

### Impact

- One Agent session killed mid-turn: `wa-d3ea717b411f` (`CLI交互!命令执行能力`), started
  `2026-11-18T21:24:42`, killed `2026-11-19T07:28:48`.
- Its meta still reports `status: running` with `end_ts: null`, so `list` shows it as running while
  no process exists. This is a stale-record defect that outlives the incident.
- `topsailai-dev` was restarted too. It hosts no Agent sessions (`hostname: topsailai-dev` appears
  in zero session metas), so no Agent was lost there.
- Endpoint downtime on `ai-dev`: the log jumps from `07:27:09` to `07:30:13`, about 3 minutes,
  because the container restart removed the Endpoint process and it had to be started again
  explicitly.

### Root cause

The intent was "restart the Endpoint to reset the connection generation". The command was "restart
the container". Both produce a working Endpoint, so the outcome looked correct while the collateral
damage was invisible. The note's prohibition was read as a caution about recreating containers, not
as a prohibition on `docker restart`, even though the note names `docker restart` explicitly.

### Detection failure

The verification after the restart checked only that the Endpoint came back online. It did not check
whether any Agent had been running. A container restart that kills an Agent leaves no trace in the
Endpoint log, because the Endpoint is not the Agent's supervisor and never observes the death.

### Prevention

1. Before any lifecycle command against a container that hosts Agents, quote the forbidden action
   from the note and compare it to the literal command. `docker restart` is named in the note as
   forbidden; `docker exec ... agent-clusterctl restart` is the permitted form.
2. Before restarting, list running Agent sessions in that container and record their pids, so the
   blast radius is known in advance rather than discovered afterwards.
3. After any container lifecycle action, verify that every previously running Agent pid still
   exists. An Endpoint that reconnects is not evidence that the Agents survived.

### Follow-up

- The stale `status: running` record for `wa-d3ea717b411f` should be reconciled to `interrupted` so
  `list` stops reporting a dead session as running.
- The same stale-record pattern exists for other sessions whose pid is gone but whose meta says
  `running`: `20261113084305.1461465`, `wa-1fb57b5948b4.1394925`, `wa-a1ad42ea0a3f.3552162`.
