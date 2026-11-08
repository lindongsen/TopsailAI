---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai_agent_cluster
ProjectFolder: /TopsailAI/src/topsailai_agent_cluster
---

# Output reads never enforce the `read_output` scope

Security-related. Highest priority among the output follow limitations.

## Trigger

Any authenticated operator credential calls `GET /api/v1/output` or
`GET /api/v1/output/follow` for an Endpoint and resource it can name. No scope is
required beyond presenting a valid credential.

## Observed behavior

`security.ScopeReadOutput` is declared in `internal/security/scopes.go` and
accepted by the scope validator, and the TopsailAI adapter advertises
`ctl.inspect` with `RequiredPermission: security.ScopeReadOutput`. The Server
never consults it on the output paths:

- `Handler.output` (`internal/server/http.go`) validates the method, channel
  availability, `endpoint_id`, `resource_id` and `max_bytes`, then calls
  `RequestOutput` directly.
- `Handler.outputFollow` (`internal/server/http.go`) does the same and calls
  `RequestFollow` directly.

Neither handler resolves a required permission, and neither compares one against
the caller's scopes. The command path does resolve one
(`internal/server/commands.go`), so the gap is specific to output reads rather
than a general absence of authorization.

## Impact

Session output is the most sensitive payload the cluster carries: it contains
prompts, model answers, tool arguments and command output. A credential issued
for `view` only, or one narrowed after an incident, can still read any session's
output on any Endpoint it can address. The follow route inherits the same gap, so
the exposure is continuous rather than a single snapshot.

This is a permission gap, not a display defect.

## Root cause

The output routes were added as read-only conveniences and were never wired into
the permission model. `ScopeReadOutput` exists because the adapter needed to
advertise a permission for `ctl.inspect`, but no Server handler was ever changed
to require it. The follow route was then written by copying the snapshot handler,
so it copied the missing check as well.

## Proposed resolution

- Resolve the required permission for an output read the same way the command
  path does, and reject a caller that lacks `read_output` with `403` and a stable
  code such as `forbidden`.
- Apply the check to both `/api/v1/output` and `/api/v1/output/follow` from one
  shared helper, so a future output route cannot be added without it.
- Check the scope before the channel is contacted, so an unauthorized caller
  cannot use response timing to learn whether an Endpoint is online.
- Keep the check independent of Endpoint-local policy: the Server decides whether
  the operator may read, and the Endpoint still decides whether the target
  exists.

## Verification

- A handler test with a `view`-only credential asserts `403` on both routes and
  asserts the transport was never called.
- A handler test with a `read_output` credential asserts the request reaches the
  transport.
- A BDD scenario drives the real cluster with a narrowed credential and asserts
  the CLI reports a permission failure rather than output.
