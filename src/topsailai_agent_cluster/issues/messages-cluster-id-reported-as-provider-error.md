---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai_agent_cluster
ProjectFolder: /TopsailAI/src/topsailai_agent_cluster
ProjectRootFolder: /TopsailAI/src
ProjectCode: topsailai_agent_cluster
programming_language: go
---

# A cluster resource ID passed to `messages` is reported as a provider failure

## Trigger

Found during the live mock-provider command sweep on 2026-11-15. The sweep invoked
every standalone CLI command once through CLI -> Server -> Endpoint -> mock
Provider, and `messages` was the only read command that failed.

## Observed behaviour

```text
$ agent-cluster-cli messages live-tmux-endpoint res_fd925f856cda9ff17bc8a0a995fbf2d9 --json
server request failed (502): provider_error: provider messages read failed
```

The Endpoint log records the real reason:

```text
query adapter messages
error: validate provider query request: provider_resource_key must be a
provider-private key, not a Cluster resource ID "res_fd925f856cda9ff17bc8a0a995fbf2d9"
```

## Expected behaviour

The caller passed a cluster resource ID where a provider session ID belongs. That
is a caller error, and it must be reported as one. The operator must be told which
identity the command needs, not sent to investigate a provider that was never
invoked.

## Root cause

Two defects compound.

1. `internal/endpoint/messages.go:34` and `:67` collapse every adapter error into
   `protocol.MessagesProviderError`:

   ```go
   if err != nil {
       if result.ErrorCode == "" {
           result.ErrorCode = protocol.MessagesProviderError
       }
       return result, err
   }
   ```

   A request-validation failure is not a provider failure. The same collapse
   already exists for the history path and was recorded separately in
   `issues/history-disconnect-reported-as-provider-error.md`, so this is the same
   defect class in a second command.

2. `internal/server/messages.go:102` maps the resulting code to a fixed message,
   `"provider messages read failed"`, so the Endpoint's own explanation never
   reaches the operator. The Server has the error text and discards it.

## Impact

- The operator is told to investigate a provider that was never called.
- The CLI help at `internal/tui/help.go:351` states `<session-id>` without saying
  which identity it means. The parameter list does say "provider session ID; a
  cluster resource ID is not accepted", but that text is only visible through
  `help messages`, not through the failure.
- A script that reads the exit status sees a generic 502 and cannot distinguish a
  wrong identity from a provider outage.

## Reproduction

```bash
agent-cluster-cli messages <endpoint> <cluster-resource-id> --json
```

The same command with the provider session ID succeeds:

```bash
agent-cluster-cli messages <endpoint> session:stable --json
```

## Proposed fix

Classify the request-validation failure before the provider default, and forward
the Endpoint's own message instead of replacing it.

- Add a distinct code for a rejected request identity, so a caller error is never
  reported as `provider_error`.
- Keep the Endpoint's error text in the Server's response message, because the
  Server is the only component that can tell the operator what to change.
- Consider rejecting a cluster resource ID in the CLI before submission, since the
  CLI already knows the two identities are different.

## Verification

The live sweep must show `messages` passing with a provider session ID and failing
with a caller-error code, not `provider_error`, when a cluster resource ID is
supplied.
