---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai_agent_cluster
ProjectFolder: /TopsailAI/src/topsailai_agent_cluster
ProjectRootFolder: /TopsailAI/src
ProjectCode: topsailai_agent_cluster
programming_language: go
status: resolved-by-topology
---

# gd-dev could not reach the Agent Cluster Server

## Trigger

Observed while preparing gd-dev as an Agent Cluster node. The CLI on gd-dev needed a usable path to
the Server, but direct connectivity from gd-dev to the known Server entry points could not be
established.

## Symptom

TCP probes from gd-dev to every known Server-facing address and both published Agent Cluster ports
reported the destination as closed. A CLI on gd-dev therefore could not use the HTTPS path to the
Server.

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

## The requirement was wrong, not the network

The human corrected the framing:

> gd-dev不需要主动访问endpoint啊！endpoint只要能连上gd-dev里面的server就行了，链路就建立起来了

That is the whole answer. The Server never dials an Endpoint in the default direction. The Endpoint
dials the Server, and the link exists from that moment. So the only path that ever had to work is
**Endpoint → Server**, and gd-dev needed no outbound route at all.

The earlier record treated "the CLI on gd-dev must reach the Server API" as a network problem to be
solved with a route. The correct fix was a topology change: run the Server on gd-dev. Then the CLI
talks to `127.0.0.1:53680`, and the Endpoints dial `wss://192.168.2.3:53943`. Neither direction
requires gd-dev to originate a connection.

## What was tried and then removed

A route was added on gd-dev and made persistent:

```text
ip route add 169.254.1.0/24 via 192.168.2.5 dev eth0
/etc/networkd-dispatcher/routable.d/50-agent-cluster-route
```

It was then **deleted**, together with its persistence file, because the topology change made it
unnecessary. The fleet stayed `online(3)` after the deletion, which is the proof that gd-dev never
needed it:

```text
route deleted
persistence file deleted
no 169.254 route remains

ai-dev         online
local-endpoint online
topsailai-dev  online
online(3)
```

## Verified direction after the topology change

```text
Server on gd-dev
  channel_direction: endpoint-initiated
  listening :53680 (API), :53943 (channel)

local-endpoint node.conf
  CHANNEL_ADDRESS=wss://192.168.2.3:53943
  SERVER_API_URL=http://192.168.2.3:53680

established socket on topsail
  ESTAB 169.254.1.1:55908 -> 192.168.2.3:53943  agent-cluster-e pid=4124440
```

The socket is outbound from the Endpoint side. gd-dev holds only the listening side.

## Corrections to the earlier record

Three claims in previous versions of this issue were wrong:

- **"The reverse direction is available only over SSH."** Wrong. Arbitrary TCP from topsail to
  gd-dev works; SSH was merely the first thing tried. The earlier conclusion came from a probe that
  could not work: busybox `sh` in the Alpine container does not support `/dev/tcp`, so
  `echo > /dev/tcp/host/port` failed for every target including `1.1.1.1:443`. Re-testing with
  `nc -z` returned `OPEN 192.168.2.3:22`. This is the `LEARN.md` lesson "a probe path bypasses the
  rule under test".
- **"A CLI on gd-dev needs direct network access to the Server API, satisfied by a route."** Wrong
  framing. The CLI needs a Server it can reach, and the Server was moved onto gd-dev, so the path is
  loopback. No route is involved.
- **"The route is a deployment prerequisite."** Wrong. It was never a prerequisite; it was a
  workaround for a topology that has since been replaced. It has been removed.

## Impact

None remaining. The Server runs on gd-dev, every Endpoint dials it outbound, and the CLI on gd-dev
uses loopback. No application code, TLS configuration or channel-direction default was changed.

## Status

Resolved by topology, not by routing. The Server was moved to gd-dev, the route was deleted, and the
fleet was verified `online(3)` afterwards.
