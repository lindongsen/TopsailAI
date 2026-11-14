---
maintainer: AI
author: DawsonLin
---

# Ready-to-Run Node Bundle

> The zip is no longer the default. `make package` now produces one executable
> with the configuration compiled in; the zip is built with `make package-zip`.
> This document describes the zip, which stays available for a recipient who must
> edit the scopes themselves or reload the policy.

## What an operator sees

One command produces a zip. The person receiving it unzips it, runs one start
script, and the Node is connected and reachable by the CLI. No editing, no
second step, no reading of the design document.

```
make package-zip PACKAGE_SERVER_URL=wss://cloud.example.com:8443/channel \
                 PACKAGE_SCOPES='project=/home/me/project tool=/opt/tool'
```

The command prints the `node-id.node-token` pair and a ready-to-paste CLI
invocation, so the operator can make the first request without asking the user
for anything.

## Behaviour

- `PACKAGE_SCOPES` takes one or more `name=path` entries. `PACKAGE_SCOPES_FILE`
  takes a file of the same lines, for paths that contain spaces.
- The scope paths are **not** written into `policy.yaml` at packaging time. The
  bundle ships `scopes.txt`, and the start script generates `policy.yaml` on the
  target machine. A build host's absolute paths are not the user's paths, so
  baking them in would produce a bundle that fails on the machine it was built
  for.
- The identity pair **is** generated at packaging time, by running the Node's own
  `id` command. Otherwise the operator would have to wait for the user to read the
  pair back before the CLI could reach the machine, which defeats the purpose of
  a bundle that works on first start.
- `PACKAGE_TUNNEL_TOKEN` is optional. When set, the token is written to
  `config/tunnel_token` with owner-only permissions and the start script exports
  it. When absent, the start script requires `CONNECTOR_NODE_TUNNEL_TOKEN` in the
  environment and says so.
- One `PACKAGE_SERVER_URL` input is normalised into both forms the bundle needs:
  the WebSocket URL the Node dials and the HTTP base URL the CLI uses.
- `make package-windows` is a separate target rather than a variable, because
  forgetting `PACKAGE_GOOS` produces a Linux binary in a zip a Windows user cannot
  run.
- The start scripts refuse a scope that is missing, a filesystem root, the home
  directory, or a directory that contains the bundle's own `config` directory.
  The last check is in the script because the Node does not yet enforce it; see
  `issues/issue-scope-may-contain-config-directory.md`.

## What this feature does not do

- It does not install a service. The bundle runs in the foreground so the user
  sees the log and can stop it with Ctrl-C. Turning it into a service is a
  deployment decision for the user's platform.
- It does not fetch the `tunnel_token` from anywhere. The token is either embedded
  at packaging time or supplied by the environment, because a bundle that fetched
  its own credential would need a second credential to authenticate the fetch.
- It does not verify that the Server is reachable at packaging time. A bundle
  built while the Server is down is still valid; the Node retries.
