---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai_agent_cluster
ProjectFolder: /TopsailAI/src/topsailai_agent_cluster
---

# Interactive `start <endpoint>` rejects the hostname the list displays

## Trigger

Human report (verbatim):

> cli中 我在workspace scope里面敲入start topsail这个命令无法工作，你分析原因

## Observed behavior

Live local cluster, three online Endpoints: `ai-dev`, `local-endpoint` (hostname `topsail`),
`topsailai-dev`.

```text
workspace> start topsail
error: server request failed (503): launch query failed
usage: start <endpoint> <resource> [--profile <id>] [--profile-revision <revision>] [--folder <path>] [--task <text>]
next: Run help start for valid syntax.
```

The same failure occurs when `topsail` is typed at the wizard's own endpoint prompt:

```text
workspace> start
1. ai-dev / ai-dev / ai-dev
2. topsail / local-endpoint / local-endpoint
3. topsailai-dev / topsailai-dev / topsailai-dev
Choose an endpoint number or enter an endpoint ID; empty/cancel cancels.
start.endpoint> topsail
error: server request failed (503): launch query failed
```

`start 2` also fails with the identical 503, even though the wizard advertises a numbered choice.
Only the fully interactive path works: `start` then `2` at the prompt reaches project selection.

Direct API evidence:

| Request | Result |
|---|---|
| `GET /api/v1/launch-options?endpoint_id=topsail` | 503 `endpoint_unavailable` `launch query failed` |
| `GET /api/v1/launch-options?endpoint_id=does-not-exist` | 503 `endpoint_unavailable` `launch query failed` |
| `GET /api/v1/launch-options?endpoint_id=local-endpoint` | 200, one handler `topsailai-local` |

## Root cause

`topsail` is the **hostname** of Endpoint `local-endpoint`, not an endpoint ID. The launch path
accepts only endpoint IDs.

1. `internal/tui/launch.go` `projectLaunch` assigns the positional argument to `endpointID`
   verbatim, then calls `resolveLaunchEndpoint`.
2. `internal/tui/launch_endpoint_choice.go` `resolveLaunchEndpoint` returns immediately when
   `endpointID != ""`, so no inventory lookup or hostname resolution happens. The same function's
   `resolveLaunchEndpointAnswer` returns any non-numeric answer literally, so a hostname typed at the
   prompt is also forwarded unchanged.
3. `internal/client/launch.go` sends it as `endpoint_id=topsail`.
4. `internal/server/launch.go` calls `RequestLaunchOptions`, which resolves the peer through
   `internal/channel/server.go` `currentPeer`. `s.Active["topsail"]` is nil, so it returns
   `ErrOffline`, and the handler maps every error to 503 `endpoint_unavailable`.

The operator is actively taught to use the hostname: `internal/tui/model.go` `endpointLabel` returns
`Hostname` before `DisplayName` and `EndpointID`, so the list's `ENDPOINT` column shows `topsail`.
`cd topsail` works because `internal/tui/navigation.go` `resolveEndpoint` resolves by exact endpoint
ID first and then by unique hostname. `start` has no equivalent resolution step, so the two commands
disagree about what an endpoint name is.

## Contributing defects

- **Positional number is not resolved.** `start 2` passes `"2"` as a literal endpoint ID because
  `resolveLaunchEndpoint` short-circuits on a non-empty argument. The numbered list is printed only
  when the argument is absent, so the advertised number form works at the prompt but not as an
  argument.
- **Unknown identifier is indistinguishable from an offline endpoint.** `currentPeer` returns
  `ErrOffline` for both a missing key and a fenced peer, and `launchOptions` collapses every error to
  503 `endpoint_unavailable`. A typo therefore looks like an infrastructure outage.
- **Misleading diagnostic.** `internal/tui/interactive.go` `writeInteractiveError` prints the
  command's `usage:` syntax line for any error, including a server-side 503. The operator is told to
  fix their syntax when the identifier was the problem.

## Impact

`start` is the primary MVP action, and the workspace scope is the default entry point. An operator
who copies the endpoint name from the list cannot launch an agent, and the error text points at
syntax instead of the identifier. The only working path is the fully interactive wizard, which
defeats the documented `start [endpoint]` form.

## Suggested fix

Resolve the launch endpoint through the same inventory lookup `cd` uses, so endpoint ID and unique
hostname are both accepted, and resolve a bare number against the printed list. Then distinguish an
unknown identifier from an offline endpoint in the server response, and stop printing a `usage:`
line when the failure is not a syntax error.

## Verification evidence

- `tmux` REPL session against the live local cluster on 2026-11-07: `start topsail`, `start 2`,
  `start` + `topsail`, `start` + `2`, `cd topsail`, `show topsail`, `endpoints`.
- `curl` against `GET /api/v1/launch-options` for `topsail`, `does-not-exist`, `local-endpoint`,
  `ai-dev`, `topsailai-dev`.

## Resolution

Fixed in two logical units, committed as `3f962356 fix: resolve start endpoint by hostname and row
number` and `254b825b fix: drop duplicated endpoint hint from launch error`.

- `internal/tui/launch_endpoint_choice.go` no longer short-circuits on a non-empty argument. The new
  `resolveLaunchEndpointTarget` reads the inventory and delegates to `resolveLaunchEndpointValue`,
  which resolves in the order **exact endpoint ID, then bare decimal as printed row number, then
  unique hostname**. Exact ID is checked first so a numeric endpoint ID is never mistaken for a row
  number. An ambiguous hostname is rejected instead of picking one arbitrarily.
- `internal/tui/launch.go` `projectLaunch` resolves an explicit positional argument through that
  helper, so `start <hostname>` and `start <number>` behave like the wizard.
- `internal/storage/server/query.go` adds `Store.GetEndpoint`, a single-endpoint lookup that reports
  whether the identifier is registered at all.
- `internal/server/launch.go` adds `writeLaunchFailure`, which returns 404 `endpoint_not_found` for an
  unregistered identifier and 503 `endpoint_unavailable` for a registered endpoint with no live
  connection. A typo no longer looks like an infrastructure outage.
- `internal/tui/interactive.go` adds `nonSyntaxError`. `writeInteractiveError` omits the `usage:` line
  for a non-syntax failure and uses the error's own `next` hint, so a valid command shape is no longer
  reported as a syntax problem.

## Verification

- Unit tests in `internal/tui/launch_endpoint_choice_test.go`:
  `TestProjectLaunchEndpointHostnameResolvesToIdentifier`,
  `TestProjectLaunchEndpointArgumentNumberResolves`, `TestProjectLaunchUnknownEndpointFailsLocally`,
  `TestResolveLaunchEndpointValuePrefersExactIdentifier`,
  `TestResolveLaunchEndpointValueRejectsAmbiguousHostname`,
  `TestWriteInteractiveErrorOmitsUsageForNonSyntaxFailure`.
- `internal/server/launch_test.go` `TestLaunchOptionsDistinguishesUnknownEndpointFromOffline` asserts
  the 404/503 split.
- `go test ./...` passes (18 packages `ok`, 0 `FAIL`); `gofmt -l` and `go vet` are clean;
  `go build ./...` exits 0.
- Live `tmux` REPL against the rebuilt local cluster, evidence under
  `.tmp/live-tmux-audit/route-b/`:

| Case | Command | Result |
|---|---|---|
| `start-hostname-final` | `start topsail` | Reaches project selection (previously 503) |
| `start-row-number` | `start 2` | Reaches project selection (previously 503) |
| `start-by-id` | `start local-endpoint` | Reaches project selection (unchanged) |
| `start-wizard` | `start` | Prints the numbered endpoint list |
| `wizard-hostname` | `topsail` at `start.endpoint>` | Reaches project selection |
| `start-unknown-final` | `start no-such-host` | `error: endpoint "no-such-host" was not found` and a `next:` hint, with no `usage:` line |

- Live authenticated API check against the running Server:

| Request | Result |
|---|---|
| `GET /api/v1/launch-options?endpoint_id=topsail` | 404 `endpoint_not_found` `endpoint topsail is not registered` |
| `GET /api/v1/launch-options?endpoint_id=does-not-exist` | 404 `endpoint_not_found` `endpoint does-not-exist is not registered` |
| `GET /api/v1/launch-options?endpoint_id=local-endpoint` | 200 `success` |

## Prevention

- A user-facing identifier that the UI displays must be accepted by every command that takes that
  identifier. `cd` already resolved ID then hostname; `start` did not, and the divergence was the
  defect. When adding a command that accepts an endpoint or session reference, reuse the existing
  resolution helper instead of accepting the raw argument.
- Do not collapse distinct failure causes into one availability error. An unknown identifier and an
  unreachable endpoint need different status codes, because the operator's remedy differs.
- Do not print a syntax `usage:` line for a failure that is not a syntax error. The misleading advice
  sent the operator looking for a syntax mistake that did not exist.
- A numbered list printed by a command must be accepted as a positional argument, not only at the
  interactive prompt.
