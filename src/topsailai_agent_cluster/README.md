# Agent Cluster

Agent Cluster provides provider-neutral Server, Endpoint, and TUI command entry points. The Server
holds the operator API and the latest inventory projection, the Endpoint owns local adapter
execution and collection, and the CLI serves both an interactive REPL and noninteractive
subcommands. TopsailAI is the first adapter; the protocol does not depend on it.

The implementation is functional but still under active development. The design documents under
`docs/` describe the intended contract and are not an approved final specification.

## Deployment

A node is provisioned from a Debian package. The package carries the same payload as a
relocatable bundle: the node controller, the role binary, the role configuration and the TLS
material. Three packages exist because a machine has one role.

| Package | Installs | Role |
|---|---|---|
| `agent-cluster-node` | `agent-clusterctl`, `agent-cluster-node-setup`, the shared env writer | controller, required by both role packages |
| `agent-cluster-server` | `agent-cluster-server` | Server daemon |
| `agent-cluster-endpoint` | `agent-cluster-endpoint`, `agent-cluster-cli`, `topsailai_agent_cluster` and `topsailai2` (symlinks) | Endpoint daemon and operator CLI |

Every installed file is visible in one real directory. The program payload, configuration, TLS
material, state, logs and pid files all live under `/opt/agent-cluster`, and each entry point is a
symlink in `/usr/local/sbin`, which is on the default `PATH`:

```text
/opt/agent-cluster/
  agent-clusterctl              controller
  bin/agent-cluster-<role>      role binary
  bin/agent-cluster-cli         operator CLI (endpoint only)
  bin/agent-cluster-node-setup  env-file regenerator
  lib/cli-env.sh                shared env writer
  conf/                         configuration conffiles
  certs/                        TLS material
  data/                         SQLite state
  logs/                         log files
  run/                          pid files
```

Configuration, TLS material, state, logs and pid files are real directories, not symlinks into
`/etc`, `/var/lib`, `/var/log` and `/run`. A symlinked layout silently redirects a write to whatever
filesystem the link names, so a state directory can land on a full root filesystem while the
operator believes it lives under `/opt`. One real tree also makes backup, removal and inspection a
single-path operation. `dpkg` honours a conffile at any absolute path, so an operator edit under
`conf/` still survives an upgrade.

The controller finds its configuration beside itself in both the bundle and the package layout, and
the configuration keeps the same relative paths in both.

A bundle install is not the same file set. `install-node.sh` copies only the role binary and, for
an endpoint, the operator CLI into `/opt/agent-cluster/bin`, then links them from
`/usr/local/sbin`. The controller, `lib/cli-env.sh`, `agent-cluster-node-setup` and the five
layout directories stay in the bundle, which is run in place. A bundle install therefore adds the
commands to `PATH` without replacing the bundle as the node's configuration source, and
`agent-clusterctl` is not on `PATH` until the node package is installed.

Build the packages with the Makefile:

```bash
make deb
```

The packages are written to `DEB_DIR`, which defaults to `.tmp/deb/`. Override it to write the
artifacts outside the source tree, for example into a mounted volume or a CI artifact directory:

```bash
make deb DEB_DIR=/srv/artifacts/deb
```

The staging tree is controlled separately by `DEB_BUILD_DIR` (default `.tmp/deb/build`), so the
output directory never contains build intermediates:

```bash
make deb DEB_DIR=/srv/artifacts/deb DEB_BUILD_DIR=/var/tmp/agent-cluster-build
```

A real deployment supplies its own site configuration and
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
conffiles, but `/opt/agent-cluster/data` (the SQLite database) and `/opt/agent-cluster/logs` are
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

## Container image

The Server also runs as a container image, built from `docker/Dockerfile`:

```bash
make image-build
make image-run
```

The image uses the same `/opt/agent-cluster` tree as the package, and every mount point is the same
path on both sides, so a host path and a container path are never two names for one file:

```text
/opt/agent-cluster/
  bin/agent-cluster-server      role binary
  certs/                        mounted read-only from the host
  data/                         mounted read-write from the host
  logs/                         unused, because logs go to stderr
```

The image differs from a package only where the difference is real. It carries no `conf/`, because
it is configured by environment variables rather than a conffile, and it writes no pid file, because
the container runtime supervises the process. Creating those directories empty would suggest a
`node.conf` or a pid file is honoured inside the container, which it is not.

`make image-run` publishes both ports on the host, so endpoints dial a bridge gateway address and a
new container IP after a recreate changes nothing on their side. It mounts
`/opt/agent-cluster/certs` read-only and `/opt/agent-cluster/data` read-write, which are the same
directories the packaged node uses. Ownership is granted per entry rather than recursively: the
directory and the server database belong to the image's unprivileged uid `10001`, while the endpoint
database keeps its own owner, so the container cannot read it. A recursive chown would hand that
database to the container and weaken the isolation. SQLite reports a permission failure as
`out of memory (14)`, which hides the real cause.

`docs/agent-cluster-architecture.md` carries the authoritative description of this deployment form,
including the full path table and the reason each difference from a package exists. This section is
the short version for someone who only wants to start the container.
