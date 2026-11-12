# Agent Cluster

Agent Cluster provides provider-neutral Server, Endpoint, and TUI command entry points. The Server
holds the operator API and the latest inventory projection, the Endpoint owns local adapter
execution and collection, and the CLI serves both an interactive REPL and noninteractive
subcommands. TopsailAI is the first adapter; the protocol does not depend on it.

The implementation is functional but still under active development. The design documents under
`docs/` describe the intended contract and are not an approved final specification.

## Deployment

A node is provisioned from Debian packages. The payload is split into a binary package that is
identical on every machine and a configuration package that carries this site's identity. Five
packages provide the shared controller, role binaries, and role-specific site configuration; a machine may run both roles under one product root.

| Package | Installs | Role |
|---|---|---|
| `agent-cluster-node` | `agent-clusterctl`, `agent-cluster-node-setup`, the shared env writer | controller, required by every other package |
| `agent-cluster-server` | `agent-cluster-server` | Server daemon binary |
| `agent-cluster-endpoint` | `agent-cluster-endpoint`, `agent-cluster-cli`, `topsailai_agent_cluster` and `topsailai2` (symlinks) | Endpoint daemon and operator CLI binaries |
| `agent-cluster-config-server-<site>` | `conf/server/node.conf`, `certs/server/ca.pem`, `certs/server/node.pem`, `certs/server/node-key.pem` | Server site configuration and TLS identity |
| `agent-cluster-config-endpoint-<site>` | `conf/endpoint/node.conf`, `certs/endpoint/*`, `conf/endpoint/command-allowlist.conf` and `conf/endpoint/control-actions.conf` | Endpoint site configuration and TLS identity |

The split exists because a site replaces the shipped certificate with its own identity, and a
certificate that lives in the binary package is overwritten on every upgrade. Keeping the identity
in its own package means a binary upgrade cannot revert it, and it keeps a private key out of an
artifact that is copied to every node. The binary packages therefore carry no configuration and no
TLS material, so one build serves every machine of the same architecture.

A config package name carries the site it belongs to, because two sites build packages with the same
role and version but different contents. Without the suffix dpkg compares only the name and the
version, so it accepts the wrong site's package silently and `dpkg -l` cannot show which site a
machine carries. Each suffixed package also provides the unsuffixed name as a virtual package, so a
generic binary package depends on one stable name and never names a site.

A binary package depends on the matching config package exactly, because the daemon cannot start
without `node.conf` and its TLS material. The two config packages do not conflict: their conffiles and TLS paths are role-scoped, so Server and
Endpoint can run together on gd-dev. Each role is selected explicitly with
`agent-clusterctl -c /opt/agent-cluster/conf/<role>/node.conf`; omitting `-c` is rejected when both
role configurations exist.

Every installed file is visible in one real directory. The program payload, configuration, TLS
material, state, logs and pid files all live under `/opt/agent-cluster`, and each entry point is a
symlink in `/usr/local/sbin`, which is on the default `PATH`:

```text
/opt/agent-cluster/
  agent-clusterctl              controller            (node package)
  bin/agent-cluster-<role>      role binary           (binary package)
  bin/agent-cluster-cli         operator CLI          (endpoint binary package)
  bin/agent-cluster-node-setup  env-file regenerator  (node package)
  lib/cli-env.sh                shared env writer     (node package)
  conf/server/node.conf        Server configuration   (server config package)
  conf/endpoint/node.conf       Endpoint configuration (endpoint config package)
  certs/server/                 Server TLS material   (server config package)
  certs/endpoint/               Endpoint TLS material (endpoint config package)
  data/server/                  Server SQLite state   (created at runtime)
  data/endpoint/                Endpoint SQLite state (created at runtime)
  logs/server/                  Server logs           (created at runtime)
  logs/endpoint/                Endpoint logs         (created at runtime)
  run/server/                   Server pid files      (created at runtime)
  run/endpoint/                 Endpoint pid files   (created at runtime)
```

The binary package owns the program payload and declares all six layout directories (`bin/`, `conf/`,
`certs/`, `data/`, `logs/`, `run/`) so the tree is complete after an install. The config package
declares only `conf/` and `certs/`, the two directories it actually populates. Two packages may
declare the same directory: `dpkg` reports a conflict only when they ship the same file, so the
overlap on `conf/` and `certs/` is intentional and harmless. State, logs and pid files are created at
runtime and belong to no package.

Configuration, TLS material, state, logs and pid files are real directories, not symlinks into
`/etc`, `/var/lib`, `/var/log` and `/run`. A symlinked layout silently redirects a write to whatever
filesystem the link names, so a state directory can land on a full root filesystem while the
operator believes it lives under `/opt`. One real tree also makes backup, removal and inspection a
single-path operation. `dpkg` honours a conffile at any absolute path, so an operator edit under
`conf/` still survives an upgrade.

The controller selects a role configuration explicitly in the co-located package layout. A standalone
bundle contains one `conf/<role>/node.conf`, which the controller can select automatically. Relative
paths are resolved from the selected role configuration directory.

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

A real deployment supplies its own site configuration and TLS material to the config package,
because the default build uses the example configuration and the development certificates. The site
identifier is required, because it suffixes the package name:

```bash
make deb-config-endpoint DEB_SITE=ai-dev DEB_CONFIG=conf/site/node.conf \
     DEB_CERT=site/node.pem DEB_KEY=site/node-key.pem
```

The site arguments apply only to the config packages. The binary packages ignore them, so a binary
built once can be reused for every machine while each site rebuilds only its own config package.

One `make deb` run resolves the version once and pins it for every package, so the set is always
internally consistent: each package depends on the exact controller version that was built beside
it. Pass `DEB_VERSION` to label a release explicitly, and `DEB_SITE` because the set includes a
config package:

```bash
make deb DEB_VERSION=1.0.0 DEB_SITE=ai-dev
```

Install on the target node. The binary package pulls its config package, so both are named
explicitly here to make the pairing visible:

```bash
dpkg -i agent-cluster-node_<version>_amd64.deb \
        agent-cluster-endpoint_<version>_amd64.deb \
        agent-cluster-config-endpoint-<site>_<version>_amd64.deb
```

The endpoint package also installs the operator CLI as `/opt/agent-cluster/bin/agent-cluster-cli`,
with `/usr/local/sbin/agent-cluster-cli`, `/usr/local/sbin/topsailai_agent_cluster` and
`/usr/local/sbin/topsailai2` as symlinks to it. The config package writes
`${HOME}/.topsailai/.topsailai_agent_cluster.env`, which is how the CLI learns
the Server address and token. Re-generate that file after a token rotation with
`agent-cluster-node-setup`.

The TLS material is registered as a conffile, so an upgrade keeps the certificate the site
installed and leaves the shipped copy beside it as a `.dpkg-dist` file to compare against. Without
that registration an upgrade would revert the certificate to the build host's name while
`node.conf` kept the site `ENDPOINT_ID`, and the peer would reject the connection because the
certificate subject no longer matched the identity in the hello frame.

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
