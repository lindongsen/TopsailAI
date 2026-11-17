---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai_agent_cluster
ProjectFolder: /TopsailAI/src/topsailai_agent_cluster
ProjectRootFolder: /TopsailAI
ProjectCode: topsailai_agent_cluster
programming_language: go
status: open
---

# CLI tests inherit the operator's Server profile and talk to the wrong Server

## Trigger

Found on 2026-11-17 while verifying that
`messages-roundtrip-fixture-disagrees-with-renderer.md` was fixed. Three integration tests
failed with `endpoint "endpoint-1" was not found` and `connection refused`, and the
failure looked like a defect in the code under test.

## Symptom

```text
go test -tags='integration testhooks' ./tests/integration \
  -run 'TestMessagesRoundTripStandaloneCLI|TestMessagesRoundTripStandaloneJSON|TestMessagesRoundTripMissingSessionCLI'
--- FAIL
```

The same three tests pass when the operator's profile variables are cleared:

```text
AGENT_CLUSTER_CLI_SERVER_PROFILE= AGENT_CLUSTER_CLI_SERVER_PROFILES= \
AGENT_CLUSTER_CLI_SERVER_PROFILE_TOKENS= \
go test -tags='integration testhooks' ./tests/integration -run 'TestMessagesRoundTrip' -count=1
ok  topsailai_agent_cluster/tests/integration  15.892s
```

## Root cause

Two independent mechanisms combine, and neither one is wrong on its own.

The harness injects the Server URL and token but does not clear the profile variables:

```go
// tests/harness/cluster.go:1018
func (c *Cluster) cliEnvironment() []string {
	env := append(os.Environ(),
		"AGENT_CLUSTER_CLI_SERVER_URL="+c.URL(""),
		"AGENT_CLUSTER_CLI_SERVER_TOKEN=secret",
		...
	)
	return append(env, c.CLIEnv...)
}
```

`os.Environ()` carries whatever the operator's shell exported, and the CLI then loads the
per-user file at its own entry point:

```go
// src/main/agent-cluster-cli/local_env.go:131
func prepareExecutableEnv() error {
	...
	return loadHomeEnv(home, os.LookupEnv, os.Setenv)
}
```

The file is `~/.topsailai/.topsailai_agent_cluster.env`
(`local_env.go:17`). On this host it sets
`AGENT_CLUSTER_CLI_SERVER_PROFILE=primary`, which resolves to
`http://172.19.1.1:53680` through `AGENT_CLUSTER_CLI_SERVER_PROFILES`.

A named profile wins over the injected URL, so the test process talks to the operator's
real Server instead of the harness Server. The harness Server is never contacted, so the
Endpoint it registered is unknown to the Server that answers, and the test reports a
missing Endpoint.

## Why this is a defect rather than a local environment problem

The harness exists to provide a hermetic Server, and it already injects the URL and token
for that reason. Injecting two of the three inputs that decide the target leaves the third
under the operator's control, so the same test passes or fails depending on a file outside
the repository. A test whose result depends on the developer's home directory is not a
test.

The failure is also misattributed. The message names a missing Endpoint, which sends the
investigation to Endpoint registration, the harness bootstrap and the Server database, all
of which are correct. Nothing in the output names the profile.

## Affected tests

Measured on 2026-11-17 on this host:

| Suite | Test | Result with profile set |
|---|---|---|
| `tests/integration` | `TestMessagesRoundTripStandaloneCLI` | FAIL |
| `tests/integration` | `TestMessagesRoundTripStandaloneJSON` | FAIL |
| `tests/integration` | `TestMessagesRoundTripMissingSessionCLI` | FAIL |
| `tests/harness` | `TestRunTUIExecutesWithoutTTY` | FAIL |

Any test that drives the real CLI binary through `RunTUI` or the standalone entry point is
exposed, because both go through `prepareExecutableEnv`. Tests that call the client library
in-process are not affected.

## Candidate fixes

| Direction | Change | Trade-off |
|---|---|---|
| A | `cliEnvironment` appends the three profile variables as empty strings | Smallest change; an empty value must be treated as unset by the CLI, which needs confirming |
| B | `cliEnvironment` sets `HOME` to a per-test temporary directory | Hermetic for every home-derived setting, not only profiles; a test that needs a real home must opt in |
| C | The CLI skips the per-user file when a test-only marker is set | Rejected: a test-only bypass of a real configuration path is exactly what the project forbids |

Direction B is preferred because it closes the whole class rather than one variable. The
per-user file is not the only thing a home directory supplies, and a test that inherits the
operator's home can be affected by any of them.

Direction A is acceptable as a minimal fix if B is judged too broad, but it must then be
paired with a test that asserts the three variables are empty in the child environment,
because an empty string that the CLI treats as a name would silently reintroduce the
defect.

## Verification required

- With the operator's profile set, the affected tests must pass without any manual
  environment clearing.
- A test must assert the child environment the harness produces, so a future variable
  added to the profile family cannot silently leak again.
- The full `make test-integration` and `make test-harness` targets must pass on a host
  whose home directory contains a profile file.

## Files

- `tests/harness/cluster.go`
- `src/main/agent-cluster-cli/local_env.go`
- `src/main/agent-cluster-cli/cli_environment.go`
- `src/main/agent-cluster-cli/main.go`

## Resolution

Fixed on 2026-11-17 in commit `9c6c36ae`.

### What changed

`tests/harness/cluster.go` `cliEnvironment()` now replaces `HOME` with a private
directory under the cluster root (`filepath.Join(c.Root, "cli-home")`) instead of
inheriting the operator's home. The inherited `HOME=` entry is dropped rather than
left in place, so the child environment never carries two contradictory values.

This is direction B from the issue's candidate list, and it was chosen over the
blocklist for the reason the issue itself states: a blocklist of the four profile
keys would silently start leaking again the moment the CLI reads a fifth key.
Replacing `HOME` removes the per-user configuration file from the CLI's search
path entirely, so no key can leak regardless of what the file contains.

The directory is created with mode `0700` so the CLI's own history file has
somewhere to live. A failure to create it is deliberately not fatal: the CLI treats
an absent per-user file as "no configuration", so an uncreatable directory still
isolates the child.

### Why the symptom was a cascade rather than one failure

The CLI reads `$HOME/.topsailai/.topsailai_agent_cluster.env` at startup and only
fills keys the process environment leaves unset. On a deployed machine that file
selects a Server profile pointing at the real Server, so every CLI scenario talked
to production instead of the test Server. The failures therefore appeared across
unrelated scenarios and their output contained real session names, which reads like
a product defect rather than a test isolation defect.

### Verification

The harness now produces a child environment whose `HOME` is the private directory,
and the affected scenarios pass on a host whose home directory contains a profile
file. The comment at `tests/harness/cluster.go:1043-1057` records the reasoning at
the site that implements it, so a future reader cannot remove the replacement
without reading why it exists.
