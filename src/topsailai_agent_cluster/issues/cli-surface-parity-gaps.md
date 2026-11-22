---
maintainer: AI
author: DawsonLin
status: partially-fixed
---

# Interactive and non-interactive command surfaces are not fully aligned

## Requirement being checked

The non-interactive surface must cover every interactive command. It may offer more, never less.

## Verified state

Both surfaces were read from source, not from documentation:

- Interactive dispatch: `internal/tui/interactive.go:582-712`, scope matrix
  `internal/tui/scope_commands.go:29-70`, help catalog `internal/tui/help.go:74-100`.
- Standalone dispatch: `src/main/agent-cluster-cli/main.go:322-455`, advertised order
  `internal/tui/help.go:283`.

Interactive canonical commands (25): `list`, `cd`, `show`, `info`, `start`, `resume`, `stop`,
`clean`, `btw`, `interrupt`, `ctl`, `drive`, `logs`, `project`, `history`, `messages`, `model`,
`send`, `endpoints`, `status`, `refresh`, `watch`, `help`, `quit`, `exit`.

Standalone advertised commands (23): `list`, `refresh`, `project`, `history`, `messages`, `model`,
`endpoints`, `show`, `info`, `logs`, `status`, `send`, `btw`, `interrupt`, `ctl`, `exec`, `start`,
`resume`, `stop`, `clean`, `drive`, `help`, `interactive`.

## Gaps where an interactive capability has no standalone path

### 1. `agent.model.registry` and `agent.model.set` are interactive-only — FIXED

Standalone `model` accepted only `<endpoint> <session> [profile]`
(`src/main/agent-cluster-cli/main.go:380-387`), which reaches the session catalog read and the
session-scoped select. The machine-wide registry read and the machine-wide launch-default
declaration existed only in `internal/tui/interactive_model_registry.go` and
`internal/tui/interactive_model_set.go`.

Evidence at the time: `GetModelRegistry` had no caller outside `internal/tui`, and
`OperationAgentModelSet` was constructed only at `internal/tui/interactive_model_set.go:237`.

Impact: a script could not read which model a launch from an Endpoint would use, and could not
declare one. Both are standard operations with their own capability entries, so the capability was
advertised but unreachable non-interactively. This is the exact defect the project's own
"non-interactive first" rule forbids.

Resolution: the standalone surface now dispatches `model registry <endpoint>` and
`model set <endpoint> <profile>` (`src/main/agent-cluster-cli/model_registry_cli.go`). Both reuse the
interactive helpers rather than reimplementing them: `tui.GetModelRegistry`,
`tui.ResolveModelRegistrySelector`, `tui.ModelRegistryError`, `tui.ModelRegistryRowLabel`,
`tui.ModelSetPayload` and the shared `submitActionWithProgress` path. `model set` submits a
target-less intent, matching the contract that a machine-wide declaration carries no resource
target. The standalone `model` help entry advertises all three forms, and
`TestModelRegistryAndSetAreAdvertised` fails if the advertisement is removed.

### 2. `resume -s <session_id>` has no standalone spelling

Interactive `resume` accepts `-s`/`--session` and forwards `ProviderSessionHandle`
(`internal/tui/interactive_ops.go:1209`). Standalone `resume` builds
`CommandTarget{Kind: "session", ResourceID: resourceID}` only
(`src/main/agent-cluster-cli/main.go:1554`), and `ProviderSessionHandle` appears nowhere in
`src/main/agent-cluster-cli/` (`grep -c ProviderSessionHandle` returns 0).

Impact: a session the Endpoint has never discovered has no cluster resource ID, so it can be
resumed interactively but not from a script. The handle form exists precisely for that case.

### 3. Endpoint-scope `command.exec` has no standalone spelling

Interactive `!` runs in session scope and in endpoint scope; endpoint scope sends a target-less
intent (`internal/tui/interactive_shell.go:220-250`, `requireShellScope`). Standalone `exec`
requires `<endpoint> <resource> <generation> -- <argv...>` and refuses without a resource
(`src/main/agent-cluster-cli/ctl_exec.go:105-121`). The standalone help states the asymmetry
explicitly (`internal/tui/help.go`, `exec` entry).

Impact: the machine-scoped form of `command.exec` is unreachable from a script, even though the
Endpoint serves it and the capability is advertised.

## Deliberate exceptions, not gaps

- `cd`, `quit`, `exit` navigate state that exists only inside the REPL loop.
- `watch` ticks add no behaviour: each tick is `list` or `refresh`, both reachable standalone. Its
  `--trigger` script is a foreground convenience in the operator's own client process.
- `>`, `!`, `/`, `ctl.<action>`, `logf`, `lf`, `lb` and the one-letter aliases are spellings, not
  capabilities. `exec`, `ctl`, `logs` and `list` carry the same behaviour standalone.

## Documentation defect found while checking

The audit table in `docs/cli-command-surface-rules.md:347-372` has no row for `model`
(`agent.model.registry`, `agent.model.set`) or `project` (`project.add`, `project.remove`). Both
families are implemented and advertised, so the table that claims to record "the verified state of
every command" is stale for the two newest families. A stale audit table is worse than a missing
one, because it reads as a complete verification.

## Suggested order of repair

1. Add a standalone `model registry <endpoint>` read and `model set <endpoint> <profile>` mutation,
   reusing the existing runner methods so the two surfaces cannot diverge.
2. Add `-s`/`--session` to standalone `resume`, forwarding `ProviderSessionHandle`.
3. Allow standalone `exec` to omit the resource and generation, producing a target-less intent,
   gated on the same "exactly one capable adapter" rule the Endpoint already applies.
4. Add the missing audit rows and a structural test that every interactive canonical command is
   either dispatched standalone or listed in one explicit exception set.

## Status

Gap 1 fixed and verified. Gaps 2 and 3 recorded, not fixed.

Gap 1 evidence: `go build ./...` clean, `go vet` clean, `go test ./internal/tui/
./src/main/agent-cluster-cli/` green, and the new tests were proven to fail when each dispatch branch
and the help advertisement were deliberately removed.
