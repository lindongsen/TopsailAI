---
maintainer: AI
author: DawsonLin
ProjectFolder: /TopsailAI/src/topsailai_agent_cluster
ProjectRootFolder: /TopsailAI
ProjectCode: AGENT_CLUSTER
programming_language: go
---

# AI-added capabilities

Capabilities added autonomously during implementation, recorded so the feature
inventory stays complete. Each entry names the capability, why it exists, the key
logic, and its effect on the system.

## Operator permission scopes

`internal/security/scopes.go` adds the five operator scopes `view`, `read_output`,
`send_message`, `control` and `endpoint_admin`, and `AuthorizeOperation` decides
whether a scope set may perform an operation. Command admission in
`internal/server/commands.go` now reads the permission each capability declares and
returns 403 `permission_denied` when the caller does not hold it. An empty scope set
means unrestricted, preserving the single-administrator deployment, and any `ctl.*`
operation that declares no permission is rejected so a sensitive action cannot
become reachable because an Endpoint omitted the declaration.

## Endpoint command allowlist

`internal/endpoint/allowlist.go` gates the `command.exec` operation behind a
line-based policy file, matched as a prefix of the argv array, with the 16 programs
that can execute other programs requiring at least two tokens. `allowlist_file.go`
loads the file at startup and reloads it on `SIGHUP`, parsing the whole document
before swapping so a malformed edit keeps the previous policy in force. A missing
file disables the operation with an explicit error rather than falling back to an
unrestricted shell, and the deployment scripts install a read-only default policy so
a fresh node starts with the feature available.

## Allowlisted command execution

`internal/adapter/topsailai/exec_*.go` implements `command.exec`: it confines the
argv array, resolves the session directory from `project_workspace` then `pwd`,
runs the program without a shell in its own process group with a minimal
environment, and bounds both output and lifetime. A non-zero exit is reported as a
legitimate result, while a timeout reports unknown effects because the program may
have acted. The receipt distinguishes `not_started`, `submitted` and `acknowledged`
so a transport acknowledgement is never presented as task completion.

## Provider control channel

`internal/adapter/topsailai/ctl_actions.go` advertises the ten reviewed provider
control actions as `ctl.<action>` operations, each with its own required
permission, so the operator reaches the provider's control surface through the
standard API instead of a provider-specific passthrough. The reviewed list is
static because `Describe` is called per command and a live registry query would
spawn a provider subprocess each time; a test parses the provider's own fallback
registry so drift is caught rather than silently ignored.
