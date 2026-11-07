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
| `agent-cluster-endpoint` | `agent-cluster-endpoint`, `agent-cluster-cli`, `topsailai_agent_cluster` and `topsailai2` (symlinks) | Endpoint daemon and operator CLI |

Every installed file is visible in one directory. The program payload lives under
`/opt/agent-cluster`, and each entry point is a symlink in `/usr/local/sbin`, which is on the
default `PATH`:

```text
/opt/agent-cluster/
  agent-clusterctl              controller
  bin/agent-cluster-<role>      role binary
  bin/agent-cluster-cli         operator CLI (endpoint only)
  bin/agent-cluster-node-setup  env-file regenerator
  lib/cli-env.sh                shared env writer
  conf  -> /etc/agent-cluster
  certs -> /etc/agent-cluster/certs
  data  -> /var/lib/agent-cluster
  logs  -> /var/log/agent-cluster
  run   -> /run/agent-cluster
```

Configuration, TLS material, state, logs and pid files stay in `/etc`, `/var/lib`, `/var/log`
and `/run`. A conffile must live in `/etc` to survive an upgrade, and mutable state must not share
a directory with immutable payload. They appear inside `/opt/agent-cluster` as symlinks, so the
operator still sees one folder while `dpkg` and backup tooling see the policy locations.

Because `conf` is a symlink, the controller finds its configuration beside itself in both the
bundle and the package layout, and the configuration keeps the same relative paths in both.

A bundle install is not the same file set. `install-node.sh` copies only the role binary and, for
an endpoint, the operator CLI into `/opt/agent-cluster/bin`, then links them from
`/usr/local/sbin`. The controller, `lib/cli-env.sh`, `agent-cluster-node-setup` and the five
layout symlinks stay in the bundle, which is run in place. A bundle install therefore adds the
commands to `PATH` without replacing the bundle as the node's configuration source, and
`agent-clusterctl` is not on `PATH` until the node package is installed.

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

The endpoint package also installs the operator CLI as `/opt/agent-cluster/bin/agent-cluster-cli`,
with `/usr/local/sbin/agent-cluster-cli`, `/usr/local/sbin/topsailai_agent_cluster` and
`/usr/local/sbin/topsailai2` as symlinks to it, and writes
`${HOME}/.topsailai/.topsailai_agent_cluster.env`, which is how the CLI learns
the Server address and token. Re-generate that file after a token rotation with
`agent-cluster-node-setup`.

Removing a package does not remove its state. `dpkg --purge` deletes the shipped files and the
conffiles, but `/var/lib/agent-cluster` (the SQLite database) and `/var/log/agent-cluster` are
left in place, because deleting a node's state during a package purge is destructive and cannot
be undone. Remove those two directories by hand when a node is decommissioned.

Operate the node with the controller:

```bash
agent-clusterctl doctor
agent-clusterctl start
agent-clusterctl status
agent-clusterctl stop
```

`make deb-inspect` reports the control fields, conffiles and contents of every built package.
