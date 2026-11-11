---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai_agent_cluster
ProjectFolder: /TopsailAI/src/topsailai_agent_cluster
ProjectRootFolder: /TopsailAI
ProjectCode: topsailai_agent_cluster
programming_language: go
status: pending
---

# gd-dev cannot reach the Agent Cluster Server

## Trigger

Observed while preparing gd-dev as an Agent Cluster node. The Endpoint and CLI on gd-dev need a usable path to the Server, but direct connectivity from gd-dev to the known Server entry points could not be established.

## Symptom

TCP probes from gd-dev to every known Server-facing address and both published Agent Cluster ports reported the destination as closed. As a result, a CLI running on gd-dev cannot use the normal HTTPS path to the Server, and an Endpoint using the default endpoint-initiated direction cannot establish its WebSocket channel.

## Verified facts

- The Server container listens on both configured Agent Cluster ports and publishes them on the Server host.
- Eight candidate address-and-port paths from gd-dev were tested; none accepted a TCP connection.
- The reverse direction is available: the Server environment can reach gd-dev over SSH.
- Agent Cluster supports the `server-initiated` channel direction, so the Server-to-Endpoint WebSocket leg can use the reachable direction.
- `server-initiated` does not solve the separate CLI-to-Server HTTPS requirement. A CLI on gd-dev still needs direct network access to the Server API.

## Directions already excluded

- Rebuilding the Server image does not address a network path that is closed before the application protocol is reached.
- Changing TLS certificates does not address this symptom because no TLS handshake is reached.
- Treating this as the earlier Endpoint protocol-version mismatch is unsupported: that failure reached the Server and produced a handshake rejection, while this symptom is a failed TCP connection.
- A reverse SSH tunnel was verified as technically able to carry traffic, but the tunnel design was explicitly rejected. It must not be restored as the product solution.

## Impact

- gd-dev cannot run the cluster CLI against the Server through the normal network path.
- An Endpoint on gd-dev must use a Server-initiated channel if deployed before the underlying network path is fixed.
- Endpoint access policy does not solve this problem; authorization is evaluated only after transport connectivity exists.

## Root cause status

Unconfirmed. The evidence establishes an asymmetric connectivity problem, not whether the cause is routing, firewall policy, address publication, host networking, or an upstream network control.

## Decision for this task

Record only. Do not change networking, deployment, TLS, channel direction defaults, or application code in the current authorization-cleanup task.

## Follow-up acceptance criteria

- Identify one supported Server API address that gd-dev can reach directly over TLS.
- Verify the CLI can authenticate and list Endpoint nodes through that address.
- Verify the Endpoint channel in the selected direction without an SSH tunnel.
- Record the actual network-layer root cause and the operational fix with reproducible probes.
