# Agent Cluster

Agent Cluster provides provider-neutral Server, Endpoint, and TUI command entry points.

The implementation is under active development. The current foundation provides shared configuration and structured logging only.

## Deployment

A node is provisioned from a Debian package. The package carries the same payload as a
relocatable bundle: the node controller, the role binary, the role configuration and the TLS
material. Three packages exist because a machine has one role.

| Package | Installs | Role |
|---|---|---|
| `agent-cluster-node` | `agent-clusterctl`, `agent-cluster-node-setup`, the shared env writer | controller, required by both role packages |
| `agent-cluster-server` | `agent-cluster-server` | Server daemon |
| `agent-cluster-endpoint` | `agent-cluster-endpoint`, `topsailai_agent_cluster` | Endpoint daemon and operator CLI |

Build the packages with the Makefile:

```bash
make deb
```

The packages are written to `.tmp/deb/`. A real deployment supplies its own site configuration and
TLS material, because the default build uses the example configuration and the development
certificates:

```bash
make deb DEB_CONFIG=conf/site/node.conf DEB_CERT=site/node.pem DEB_KEY=site/node-key.pem
```

One `make deb` run resolves the version once and pins it for all three packages, so the set is
always internally consistent: the role packages depend on the exact controller version that was
built beside them. Pass `DEB_VERSION` to label a release explicitly:

```bash
make deb DEB_VERSION=1.0.0
```

Install on the target node:

```bash
dpkg -i agent-cluster-node_<version>_amd64.deb agent-cluster-endpoint_<version>_amd64.deb
```

The endpoint package also installs the operator CLI as `/usr/local/sbin/topsailai_agent_cluster` and
writes `${HOME}/.topsailai/.topsailai_agent_cluster.env`, which is how the CLI learns the Server
address and token. Re-generate that file after a token rotation with `agent-cluster-node-setup`.

Operate the node with the controller:

```bash
agent-clusterctl doctor
agent-clusterctl start
agent-clusterctl status
agent-clusterctl stop
```

`make deb-inspect` reports the control fields, conffiles and contents of every built package.
