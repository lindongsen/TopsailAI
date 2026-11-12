---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai_agent_cluster
ProjectFolder: /TopsailAI/src/topsailai_agent_cluster
ProjectRootFolder: /TopsailAI
ProjectCode: topsailai_agent_cluster
programming_language: go
status: resolved-on-gd-dev
---

# gd-dev could not reach the Agent Cluster Server

## Trigger

Observed while preparing gd-dev as an Agent Cluster node. The Endpoint and CLI on gd-dev need a
usable path to the Server, but direct connectivity from gd-dev to the known Server entry points
could not be established.

## Symptom

TCP probes from gd-dev to every known Server-facing address and both published Agent Cluster ports
reported the destination as closed. A CLI on gd-dev therefore could not use the HTTPS path to the
Server, and an Endpoint using the default endpoint-initiated direction could not establish its
WebSocket channel.

## Root cause (confirmed)

gd-dev's default gateway is `192.168.2.1`. topsail has **no interface on `192.168.2.0/24`**. topsail
reaches gd-dev through a NAT hop on `tap-mgmt`:

```text
gd-dev              192.168.2.3/24   default via 192.168.2.1 dev eth0
topsail             no interface on 192.168.2.0/24
topsail -> gd-dev   192.168.2.3 via 169.254.1.3 dev tap-mgmt src 169.254.1.1
169.254.1.3         dual-homed on 192.168.2.0/24, SNATs to 192.168.2.5
```

gd-dev sent its SYN to `192.168.2.1`, which has no route to `169.254.1.0/24`. The packet never
reached topsail, so the connection failed before any TLS handshake. The `ConnectionRefusedError`
observed on `192.168.255.254` was an RST from `192.168.2.1`, not from topsail.

Evidence:

- `tcpdump -ni br0 "tcp port 59996"` → 0 packets
- `tcpdump -ni tap-mgmt "tcp port 59996"` → 0 packets
- `tcpdump -ni any "tcp and host 192.168.2.3"` → gd-dev replies present, no SYN from gd-dev
- `conntrack` → `tcp ESTABLISHED src=169.254.1.1 dst=192.168.2.3 sport=33632 dport=63943 [ASSURED]`
- topsail `iptables -S INPUT` → `-P INPUT ACCEPT`, only `LIBVIRT_INP`; `FORWARD` → `ACCEPT`
- `rp_filter=1` on `all`, `tap-mgmt`, `br0`

## Fix

One route on gd-dev:

```text
ip route add 169.254.1.0/24 via 192.168.2.5 dev eth0
```

Made persistent through `/etc/networkd-dispatcher/routable.d/50-agent-cluster-route` (mode 0755,
67 bytes).

Verified after the fix:

- `gd-dev -> 169.254.1.1:59998 CONNECTED`, listener `ACCEPTED from ('192.168.2.3', 40366)`
- gd-dev reached the test Server on `:63680` and the production Server on `:53680`
- the CLI on gd-dev listed all three endpoints as `online`

## Corrections to the earlier record

Two claims in the previous version of this issue were wrong:

- **"The reverse direction is available only over SSH."** Wrong. Arbitrary TCP from topsail to
  gd-dev works; SSH was merely the first thing tried. The earlier conclusion came from a probe that
  could not work: busybox `sh` in the Alpine container does not support `/dev/tcp`, so
  `echo > /dev/tcp/host/port` failed for every target including `1.1.1.1:443`. Re-testing with
  `nc -z` returned `OPEN 192.168.2.3:22`. This is the `LEARN.md` lesson "a probe path bypasses the
  rule under test".
- **"A CLI on gd-dev still needs direct network access to the Server API."** Correct as a
  requirement, but the earlier record treated it as unsatisfiable. It is satisfied by the route
  above. The CLI's `--server-url` is an independent setting, so the CLI can also run on any other
  host that reaches the Server; the human confirmed that placement is free.

## Impact

Resolved for gd-dev. The route is host-local, so any other node outside `192.168.2.0/24` that must
reach topsail needs the same route. This is a deployment prerequisite, not an application defect.

## Status

Resolved on gd-dev, verified end to end by the live acceptance. The route is persistent across
reboots. No application code, TLS configuration or channel-direction default was changed.
